#!/usr/bin/env python3
"""Flash queue rules. Validation, clamping, order, expiry, and repeat suppression."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import flashes  # noqa: E402


def _note(title="Leave soon", body="Downtown review starts soon.", **extra):
    data = {"title": title, "body": body, "source": "Calendar"}
    data.update(extra)
    return data


class FlashQueueTests(unittest.TestCase):
    def setUp(self):
        flashes.reset_flashes()

    def test_defaults_level_and_duration(self):
        posted = flashes.post_flash(_note(), now=1_000)
        self.assertEqual(posted["level"], "info")
        self.assertEqual(posted["duration"], 30)
        self.assertFalse(posted["deduped"])
        self.assertEqual(posted["expires"], 1_000 + 30 + flashes.HOLD_SEC)

    def test_duration_is_clamped(self):
        low = flashes.post_flash(_note(title="Low", duration=1), now=2_000)
        high = flashes.post_flash(_note(title="High", duration=500), now=2_000)
        exact = flashes.post_flash(_note(title="Exact", duration=45), now=2_000)
        self.assertEqual(low["duration"], 5)
        self.assertEqual(high["duration"], 120)
        self.assertEqual(exact["duration"], 45)
        self.assertEqual(low["expires"], 2_000 + 5 + flashes.HOLD_SEC)
        self.assertEqual(high["expires"], 2_000 + 120 + flashes.HOLD_SEC)

    def test_validation(self):
        bad = [
            {},
            {"title": "Hi", "body": "There"},
            {"title": "", "body": "There", "source": "Calendar"},
            {"title": "Hi", "body": "", "source": "Calendar"},
            {"title": "Hi\nthere", "body": "There", "source": "Calendar"},
            {"title": "Hi", "body": "bell\x07", "source": "Calendar"},
            {"title": "Hi", "body": "There", "source": "Calendar", "level": "panic"},
            {"title": "Hi", "body": "There", "source": "Calendar", "duration": True},
            {"title": "Hi", "body": "There", "source": "Calendar", "duration": 1.5},
            {"title": "Hi", "body": "There", "source": "Calendar", "extra": 1},
            {"title": "x" * 81, "body": "There", "source": "Calendar"},
            {"title": "Hi", "body": "y" * 401, "source": "Calendar"},
            {"title": "Hi", "body": "\n".join(["line"] * 7), "source": "Calendar"},
        ]
        for body in bad:
            with self.subTest(body=body):
                with self.assertRaises(flashes.FlashError):
                    flashes.post_flash(body, now=3_000)

    def test_queue_order_and_expiry(self):
        first = flashes.post_flash(_note(title="First"), now=10_000)
        second = flashes.post_flash(_note(title="Second", level="warning"), now=10_010)
        listed = flashes.list_flashes(now=10_020)["flashes"]
        self.assertEqual([item["title"] for item in listed], ["First", "Second"])
        self.assertEqual(listed[0]["id"], first["id"])
        # First expires at 10_000 + 30 + HOLD. Just after that it is gone and Second remains.
        after = flashes.list_flashes(now=first["expires"] + 1)["flashes"]
        self.assertEqual([item["id"] for item in after], [second["id"]])
        self.assertEqual(flashes.list_flashes(now=second["expires"] + 1)["flashes"], [])

    def test_identical_repeat_is_deduped_and_does_not_extend_time(self):
        first = flashes.post_flash(_note(level="urgent"), now=20_000)
        again = flashes.post_flash(_note(level="urgent"), now=20_000 + flashes.DEDUPE_SEC - 1)
        self.assertTrue(again["deduped"])
        self.assertEqual(again["id"], first["id"])
        self.assertEqual(again["expires"], first["expires"])
        self.assertEqual(len(flashes.list_flashes(now=20_030)["flashes"]), 1)
        later = flashes.post_flash(_note(level="urgent"), now=20_000 + flashes.DEDUPE_SEC)
        self.assertFalse(later["deduped"])
        self.assertNotEqual(later["id"], first["id"])
        self.assertEqual(len(flashes.list_flashes(now=20_000 + flashes.DEDUPE_SEC)["flashes"]), 2)

    def test_a_different_body_is_a_new_flash(self):
        flashes.post_flash(_note(body="One"), now=30_000)
        other = flashes.post_flash(_note(body="Two"), now=30_001)
        self.assertFalse(other["deduped"])
        self.assertEqual(len(flashes.list_flashes(now=30_002)["flashes"]), 2)

    def test_queue_cap(self):
        for n in range(flashes.QUEUE_MAX):
            flashes.post_flash(_note(title=f"Item {n}"), now=40_000)
        with self.assertRaises(flashes.FlashError) as caught:
            flashes.post_flash(_note(title="One more"), now=40_001)
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(len(flashes.list_flashes(now=40_002)["flashes"]), flashes.QUEUE_MAX)


class FlashRouteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["DESKBOARD_WIDGETS"] = str(Path(self.tmp.name) / "widgets.json")
        os.environ["DESKBOARD_CONFIG"] = str(Path(self.tmp.name) / "config.json")
        os.environ["DESKBOARD_HOSTNAME"] = "deskboard"
        flashes.reset_flashes()
        import serve

        self.server = serve.Server4(("127.0.0.1", 0), serve.Handler)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()
        flashes.reset_flashes()
        for key in ("DESKBOARD_WIDGETS", "DESKBOARD_CONFIG", "DESKBOARD_HOSTNAME"):
            os.environ.pop(key, None)

    def test_post_and_list_and_script(self):
        import urllib.error
        import urllib.request

        body = json.dumps(_note(level="warning", duration=30)).encode()
        req = urllib.request.Request(self.base + "/api/flash", data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=5) as res:
            posted = json.loads(res.read())
        self.assertEqual(res.status, 200)
        self.assertEqual(posted["level"], "warning")
        with urllib.request.urlopen(self.base + "/api/flash", timeout=5) as res:
            listed = json.loads(res.read())
        self.assertEqual(listed["flashes"][0]["id"], posted["id"])
        env = {**os.environ, "DESKBOARD_URL": self.base}
        script = subprocess.run(
            ["bash", str(ROOT / "scripts" / "flash.sh"), "Calendar", "Bring the notes", "The review moved to the small room.", "info", "20"],
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(script.returncode, 0, script.stderr)
        self.assertIn("Bring the notes", script.stdout)
        with urllib.request.urlopen(self.base + "/api/flash", timeout=5) as res:
            listed = json.loads(res.read())
        self.assertEqual(len(listed["flashes"]), 2)
        bad = urllib.request.Request(
            self.base + "/api/flash",
            data=json.dumps({"title": "x"}).encode(),
            method="POST",
        )
        bad.add_header("Content-Type", "application/json")
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(bad, timeout=5)
        self.assertEqual(caught.exception.code, 400)


if __name__ == "__main__":
    unittest.main()
