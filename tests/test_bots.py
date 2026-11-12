#!/usr/bin/env python3
"""Unit tests for managed tiles, layout revisions, and the bot post route."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FRESH = ("widgets", "deskboard_config", "fetches", "serve", "tiles")


class BotCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.widgets_path = self.dir / "widgets.json"
        self.config_path = self.dir / "config.json"
        os.environ["DESKBOARD_WIDGETS"] = str(self.widgets_path)
        os.environ["DESKBOARD_CONFIG"] = str(self.config_path)
        self.config_path.write_text(json.dumps({"timezone": "America/New_York"}), encoding="utf-8")
        for name in list(sys.modules):
            if name in FRESH:
                del sys.modules[name]
        import widgets

        self.w = widgets
        self.w.create_widget({"type": "list", "id": "botstatus", "title": "Bots", "items": ["Waiting"], "managed_by": "bots"})
        self.w.create_widget({"type": "list", "id": "todo", "title": "Todo", "items": ["Ship"]})

    def tearDown(self):
        self.tmp.cleanup()
        for key in ("DESKBOARD_WIDGETS", "DESKBOARD_CONFIG"):
            os.environ.pop(key, None)

    def by_id(self, widget_id):
        return next(x for x in self.w.list_widgets() if x["id"] == widget_id)

    def layout(self):
        return self.w.revision()["layout_revision"]


class ManagedTests(BotCase):
    def test_managed_by_is_stored_and_listed(self):
        self.assertEqual(self.by_id("botstatus")["managed_by"], "bots")
        self.assertNotIn("managed_by", self.by_id("todo"))
        stored = json.loads(self.widgets_path.read_text())
        self.assertEqual(next(x for x in stored["widgets"] if x["id"] == "botstatus")["managed_by"], "bots")

    def test_managed_by_must_be_a_short_name(self):
        for bad in ("Bots", "a b", "x" * 30, 3):
            with self.subTest(bad=bad):
                with self.assertRaises(self.w.WidgetError):
                    self.w.update_widget("todo", {"managed_by": bad})

    def test_managed_by_can_be_cleared(self):
        self.w.update_widget("botstatus", {"managed_by": ""})
        self.assertNotIn("managed_by", self.by_id("botstatus"))

    def test_keep_managed_import_keeps_content_and_takes_layout(self):
        base = self.layout()
        self.w.post_line("botstatus", {"source": "Backup", "text": "done"})
        stale_copy = [
            {"type": "list", "id": "botstatus", "title": "Old", "items": ["Waiting"], "col_span": 2, "enabled": True, "order": 0},
            {"type": "list", "id": "todo", "title": "Todo", "items": ["Ship", "Test"], "order": 10},
        ]
        self.w.replace_widgets(stale_copy, base_revision=base, keep_managed=True)
        bot = self.by_id("botstatus")
        self.assertEqual(bot["title"], "Bots")
        self.assertIn("Backup", bot["items"][0])
        self.assertEqual(bot["col_span"], 2)
        self.assertEqual(bot["managed_by"], "bots")
        self.assertEqual(self.by_id("todo")["items"], ["Ship", "Test"])

    def test_plain_import_still_replaces_everything(self):
        self.w.replace_widgets([{"type": "list", "id": "botstatus", "items": ["Reset"]}])
        bot = self.by_id("botstatus")
        self.assertEqual(bot["items"], ["Reset"])
        self.assertNotIn("managed_by", bot)

    def test_apply_keeps_posted_lines_when_the_owner_changes(self):
        base = self.layout()
        self.w.post_line("botstatus", {"source": "Backup", "text": "done"})
        posted = list(self.by_id("botstatus")["items"])
        self.w.replace_widgets(
            [
                {
                    "type": "list",
                    "id": "botstatus",
                    "title": "Old",
                    "items": ["Waiting"],
                    "managed_by": "calendar",
                    "col_span": 2,
                    "order": 0,
                },
                {"type": "list", "id": "todo", "items": ["Ship"], "order": 10},
            ],
            base_revision=base,
            keep_managed=True,
        )
        self.assertEqual(self.by_id("botstatus")["items"], posted)
        self.assertEqual(self.by_id("botstatus")["col_span"], 2)
        self.assertEqual(self.by_id("botstatus")["managed_by"], "bots")
        self.assertEqual(self.by_id("botstatus")["title"], "Bots")
        self.w.update_widget("botstatus", {"managed_by": "calendar"})
        self.assertEqual(self.by_id("botstatus")["items"], posted)
        self.assertEqual(self.by_id("botstatus")["managed_by"], "calendar")

    def test_apply_keeps_posted_lines_when_the_owner_is_cleared(self):
        base = self.layout()
        self.w.post_line("botstatus", {"source": "Backup", "text": "done"})
        posted = list(self.by_id("botstatus")["items"])
        self.w.replace_widgets(
            [
                {"type": "list", "id": "botstatus", "title": "Old", "items": ["Waiting"], "enabled": True, "order": 0},
                {"type": "list", "id": "todo", "items": ["Ship"], "order": 10},
            ],
            base_revision=base,
            keep_managed=True,
        )
        self.w.update_widget("botstatus", {"managed_by": ""})
        bot = self.by_id("botstatus")
        self.assertNotIn("managed_by", bot)
        self.assertEqual(bot["items"], posted)
        self.assertEqual(bot["title"], "Bots")

    def test_apply_can_mark_an_unmanaged_tile_without_touching_a_managed_one(self):
        posted = list(self.by_id("botstatus")["items"])
        self.w.replace_widgets(
            [
                {"type": "list", "id": "botstatus", "title": "Old", "items": ["Waiting"], "order": 0},
                {
                    "type": "list",
                    "id": "todo",
                    "title": "Today",
                    "items": ["Ship", "Test"],
                    "managed_by": "tasks",
                    "col_span": 2,
                    "order": 10,
                },
            ],
            keep_managed=True,
        )
        bot = self.by_id("botstatus")
        self.assertEqual(bot["items"], posted)
        self.assertEqual(bot["managed_by"], "bots")
        self.assertEqual(bot["title"], "Bots")
        todo = self.by_id("todo")
        self.assertEqual(todo["managed_by"], "tasks")
        self.assertEqual(todo["items"], ["Ship", "Test"])
        self.assertEqual(todo["col_span"], 2)

    def test_set_clear_and_apply_keep_text_on_note_status_and_embed(self):
        self.config_path.write_text(json.dumps({"timezone": "America/New_York", "embed_allowlist": ["example.com"]}), encoding="utf-8")
        self.w.create_widget({"type": "note", "id": "memo", "title": "Memo", "text": "Original note"})
        self.w.create_widget(
            {"type": "status", "id": "pings", "title": "Status", "targets": [{"label": "Site", "url": "https://example.com"}]}
        )
        self.w.create_widget({"type": "embed", "id": "frame", "title": "Embed", "url": "https://example.com"})
        self.w.update_widget("memo", {"managed_by": "bots"})
        self.w.update_widget("pings", {"managed_by": "calendar"})
        self.w.update_widget("frame", {"managed_by": "tasks"})
        self.assertEqual(self.by_id("memo")["managed_by"], "bots")
        self.assertEqual(self.by_id("pings")["managed_by"], "calendar")
        self.assertEqual(self.by_id("frame")["managed_by"], "tasks")
        self.w.update_widget("memo", {"text": "Posted by the bot"})
        self.w.update_widget("pings", {"targets": [{"label": "Site", "url": "https://example.com/live"}]})
        self.w.update_widget("frame", {"title": "Live embed"})
        base = self.layout()
        stale = []
        for item in self.w.list_widgets():
            copy = json.loads(json.dumps(item))
            if copy["id"] == "memo":
                copy["text"] = "Stale note"
            elif copy["id"] == "pings":
                copy["targets"] = [{"label": "Old", "url": "https://example.com/old"}]
            elif copy["id"] == "frame":
                copy["title"] = "Stale embed"
                copy["url"] = "https://example.com/stale"
            stale.append(copy)
        self.w.replace_widgets(stale, base_revision=base, keep_managed=True)
        self.assertEqual(self.by_id("memo")["text"], "Posted by the bot")
        self.assertEqual(self.by_id("pings")["targets"][0]["url"], "https://example.com/live")
        self.assertEqual(self.by_id("frame")["title"], "Live embed")
        self.assertEqual(self.by_id("frame")["url"], "https://example.com")
        for widget_id in ("memo", "pings", "frame"):
            self.w.update_widget(widget_id, {"managed_by": ""})
            self.assertNotIn("managed_by", self.by_id(widget_id))
        self.assertEqual(self.by_id("memo")["text"], "Posted by the bot")
        self.assertEqual(self.by_id("pings")["targets"][0]["url"], "https://example.com/live")
        self.assertEqual(self.by_id("frame")["url"], "https://example.com")

    def test_keep_managed_can_hide_a_managed_tile(self):
        self.w.replace_widgets(
            [{"type": "list", "id": "botstatus", "items": ["x"], "enabled": False}, {"type": "list", "id": "todo", "items": ["Ship"]}],
            keep_managed=True,
        )
        self.assertFalse(self.by_id("botstatus")["enabled"])
        self.assertEqual(self.by_id("botstatus")["items"], ["Waiting"])


class RevisionTests(BotCase):
    def test_every_write_bumps_revision(self):
        start = self.w.revision()["revision"]
        self.w.update_widget("todo", {"title": "Today"})
        self.w.post_line("botstatus", {"source": "A", "text": "b"})
        self.w.reorder_widgets([x["id"] for x in self.w.list_widgets()])
        self.assertEqual(self.w.revision()["revision"], start + 3)
        stored = json.loads(self.widgets_path.read_text())
        self.assertEqual(stored["revision"], start + 3)

    def test_stale_base_is_refused_and_nothing_changes(self):
        base = self.layout()
        self.w.update_widget("todo", {"title": "Changed elsewhere"})
        before = self.widgets_path.read_text()
        with self.assertRaises(self.w.StaleRevision) as caught:
            self.w.replace_widgets([{"type": "list", "id": "todo", "items": ["Mine"]}], base_revision=base, keep_managed=True)
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(self.widgets_path.read_text(), before)

    def test_current_base_is_accepted(self):
        base = self.layout()
        self.w.update_widget("todo", {"title": "Mine"}, base_revision=base)
        self.assertEqual(self.by_id("todo")["title"], "Mine")

    def test_bot_posts_do_not_make_the_configurator_stale(self):
        base = self.layout()
        self.w.post_line("botstatus", {"source": "A", "text": "one"})
        self.w.update_widget("botstatus", {"items": ["refreshed"]})
        self.assertEqual(self.layout(), base)
        self.w.replace_widgets([{"type": "list", "id": "todo", "items": ["Ship"]}], base_revision=base, keep_managed=True)

    def test_layout_change_to_a_managed_tile_does_bump_layout(self):
        base = self.layout()
        self.w.update_widget("botstatus", {"col_span": 2})
        self.assertGreater(self.layout(), base)

    def test_no_base_revision_keeps_working(self):
        self.w.update_widget("todo", {"title": "Script"})
        self.w.replace_widgets([{"type": "list", "id": "todo", "items": ["Ship"]}])

    def test_bad_base_revision(self):
        with self.assertRaises(self.w.WidgetError):
            self.w.update_widget("todo", {"title": "x"}, base_revision="3")

    def test_old_widgets_file_without_revision_reads_as_zero(self):
        self.widgets_path.write_text(json.dumps({"widgets": [{"id": "todo", "type": "list", "order": 0, "items": ["a"]}]}))
        self.assertEqual(self.w.revision(), {"revision": 0, "layout_revision": 0})
        self.w.update_widget("todo", {"title": "t"}, base_revision=0)
        self.assertEqual(self.w.revision()["revision"], 1)


class PostTests(BotCase):
    def test_post_prepends_a_timestamped_line(self):
        widget = self.w.post_line("botstatus", {"source": "Backup", "text": "Nightly backup finished"})
        line = widget["items"][0]
        self.assertRegex(line, r"^(1[0-2]|[1-9]):[0-5]\d (AM|PM)  Backup  Nightly backup finished$")
        self.assertEqual(widget["items"][1], "Waiting")

    def test_stamp_uses_the_board_timezone(self):
        noon_utc = datetime(2026, 11, 10, 17, 5, tzinfo=timezone.utc)
        self.assertEqual(self.w._clock_stamp(noon_utc), "12:05 PM")
        self.config_path.write_text(json.dumps({"timezone": "UTC"}), encoding="utf-8")
        self.assertEqual(self.w._clock_stamp(noon_utc), "5:05 PM")

    def test_keeps_the_newest_six_by_default(self):
        for n in range(9):
            self.w.post_line("botstatus", {"source": "Bot", "text": f"line {n}"})
        items = self.by_id("botstatus")["items"]
        self.assertEqual(len(items), 6)
        self.assertTrue(items[0].endswith("line 8"))

    def test_max_items_per_widget(self):
        self.w.update_widget("botstatus", {"max_items": 3})
        for n in range(5):
            self.w.post_line("botstatus", {"source": "Bot", "text": f"line {n}"})
        self.assertEqual(len(self.by_id("botstatus")["items"]), 3)
        with self.assertRaises(self.w.WidgetError):
            self.w.update_widget("botstatus", {"max_items": 9})

    def test_long_text_is_trimmed_to_one_board_line(self):
        widget = self.w.post_line("botstatus", {"source": "S" * 40, "text": "word " * 40})
        line = widget["items"][0]
        self.assertLessEqual(len(line), 80)
        self.assertTrue(line.endswith("…"))

    def test_control_characters_are_refused(self):
        for text in ("two\nlines", "bell\x07", "esc\x1b[31m", "del\x7f"):
            with self.subTest(text=text):
                with self.assertRaises(self.w.WidgetError):
                    self.w.post_line("botstatus", {"source": "Bot", "text": text})
        with self.assertRaises(self.w.WidgetError):
            self.w.post_line("botstatus", {"source": "Bot\t", "text": "ok"})

    def test_body_shape(self):
        for body in ({"source": "Bot"}, {"text": "x"}, {"source": "", "text": "x"}, {"source": "a", "text": "b", "extra": 1}, {"source": 1, "text": "x"}):
            with self.subTest(body=body):
                with self.assertRaises(self.w.WidgetError):
                    self.w.post_line("botstatus", body)

    def test_missing_or_hidden_tile_is_404_and_never_created(self):
        with self.assertRaises(self.w.WidgetError) as caught:
            self.w.post_line("nosuch", {"source": "Bot", "text": "hi"})
        self.assertEqual(caught.exception.status, 404)
        self.assertNotIn("nosuch", [x["id"] for x in self.w.list_widgets()])
        self.w.update_widget("botstatus", {"enabled": False})
        with self.assertRaises(self.w.WidgetError) as caught:
            self.w.post_line("botstatus", {"source": "Bot", "text": "hi"})
        self.assertEqual(caught.exception.status, 404)
        self.w.delete_widget("botstatus")
        with self.assertRaises(self.w.WidgetError):
            self.w.post_line("botstatus", {"source": "Bot", "text": "hi"})
        self.assertNotIn("botstatus", [x["id"] for x in self.w.list_widgets()])

    def test_only_list_tiles_take_posts(self):
        self.w.create_widget({"type": "note", "id": "memo", "text": "hi"})
        with self.assertRaises(self.w.WidgetError) as caught:
            self.w.post_line("memo", {"source": "Bot", "text": "hi"})
        self.assertEqual(caught.exception.status, 409)


class HttpTests(BotCase):
    """The routes through serve.Handler on a loopback port picked by the OS."""

    def setUp(self):
        super().setUp()
        import serve

        self.server = serve.Server4(("127.0.0.1", 0), serve.Handler)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        super().tearDown()

    def call(self, method, path, body=None, headers=None):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.base + path, data=data, method=method)
        if body is not None:
            req.add_header("Content-Type", "application/json")
        for key, value in (headers or {}).items():
            req.add_header(key, value)
        try:
            with urllib.request.urlopen(req, timeout=5) as res:
                return res.status, dict(res.headers), json.loads(res.read() or b"null")
        except urllib.error.HTTPError as exc:
            return exc.code, dict(exc.headers), json.loads(exc.read() or b"null")

    def test_get_widgets_carries_revision(self):
        code, headers, body = self.call("GET", "/api/widgets")
        self.assertEqual(code, 200)
        self.assertIn("revision", body)
        self.assertEqual(int(headers["X-Deskboard-Layout-Revision"]), body["layout_revision"])

    def test_if_match_stale_is_409(self):
        _c, _h, body = self.call("GET", "/api/widgets")
        base = body["layout_revision"]
        self.call("PATCH", "/api/widgets/todo", {"title": "elsewhere"})
        code, _h, err = self.call("PATCH", "/api/widgets/todo", {"title": "mine"}, {"If-Match": f'"{base}"'})
        self.assertEqual(code, 409)
        self.assertTrue(err["stale"])
        code, _h, err = self.call("PUT", "/api/widgets/import", {"widgets": [], "base_revision": base, "keep_managed": True})
        self.assertEqual(code, 409)
        self.assertEqual(self.by_id("todo")["title"], "elsewhere")

    def test_post_route(self):
        code, headers, body = self.call("POST", "/api/widgets/botstatus/post", {"source": "Inbox bot", "text": "hello"})
        self.assertEqual(code, 200)
        self.assertIn("Inbox bot  hello", body["items"][0])
        self.assertIn("X-Deskboard-Revision", headers)
        code, _h, _b = self.call("POST", "/api/widgets/ghost/post", {"source": "a", "text": "b"})
        self.assertEqual(code, 404)
        code, _h, _b = self.call("GET", "/api/widgets/botstatus/post")
        self.assertEqual(code, 405)

    def test_import_body_without_new_keys_still_works(self):
        code, _h, _b = self.call("PUT", "/api/widgets/import", {"widgets": [{"type": "list", "id": "todo", "items": ["a"]}]})
        self.assertEqual(code, 200)

    def test_post_script(self):
        env = {**os.environ, "DESKBOARD_URL": self.base}
        ok = subprocess.run(["bash", str(ROOT / "scripts" / "post.sh"), "botstatus", "Script", "from post.sh"], env=env, capture_output=True, text=True)
        self.assertEqual(ok.returncode, 0, ok.stderr)
        self.assertIn("Script  from post.sh", ok.stdout)
        missing = subprocess.run(["bash", str(ROOT / "scripts" / "post.sh"), "ghost", "Script", "x"], env=env, capture_output=True, text=True)
        self.assertEqual(missing.returncode, 1)
        self.assertIn("404", missing.stderr)


if __name__ == "__main__":
    unittest.main()
