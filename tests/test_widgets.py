#!/usr/bin/env python3
"""Unit tests for widget validation and config scrubbing."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class WidgetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.widgets_path = Path(self.tmp.name) / "widgets.json"
        self.config_path = Path(self.tmp.name) / "config.json"
        os.environ["DESKBOARD_WIDGETS"] = str(self.widgets_path)
        os.environ["DESKBOARD_CONFIG"] = str(self.config_path)
        # Modules capture paths at import; reload for isolation.
        for name in list(sys.modules):
            if name in ("widgets", "deskboard_config", "fetches", "serve"):
                del sys.modules[name]
        import deskboard_config as cfg
        import widgets as w

        self.cfg = cfg
        self.w = w

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("DESKBOARD_WIDGETS", None)
        os.environ.pop("DESKBOARD_CONFIG", None)

    def test_defaults(self):
        widgets = self.w.list_widgets()
        types = {item["type"] for item in widgets}
        self.assertIn("clock", types)
        self.assertIn("stats", types)

    def test_reject_unknown_fields(self):
        with self.assertRaises(self.w.WidgetError) as ctx:
            self.w.create_widget({"type": "note", "title": "Hi", "text": "Hello", "secret": "nope"})
        self.assertIn("unknown fields", str(ctx.exception))

    def test_note_limits(self):
        self.w.create_widget({"type": "note", "id": "focus", "text": "Ship it"})
        with self.assertRaises(self.w.WidgetError):
            self.w.create_widget({"type": "note", "text": "x" * 400})

    def test_metric_and_list(self):
        m = self.w.create_widget({"type": "metric", "label": "Outside", "value": "12°", "hint": "roof", "trend": "+2"})
        self.assertEqual(m["trend"], "+2")
        lst = self.w.create_widget({"type": "list", "title": "Today", "items": ["One", "Two"]})
        self.assertEqual(len(lst["items"]), 2)

    def test_singleton_clock(self):
        with self.assertRaises(self.w.WidgetError) as ctx:
            self.w.create_widget({"type": "clock"})
        self.assertEqual(ctx.exception.status, 409)

    def test_spans(self):
        note = self.w.create_widget({"type": "note", "text": "Wide", "col_span": 2, "row_span": 1})
        self.assertEqual(note["col_span"], 2)
        with self.assertRaises(self.w.WidgetError):
            self.w.create_widget({"type": "note", "text": "Bad", "col_span": 3})

    def test_weather_github_embed_rules(self):
        wx = self.w.create_widget(
            {"type": "weather", "latitude": 40.7, "longitude": -74.0, "label": "Home", "units": "metric"}
        )
        self.assertEqual(wx["latitude"], 40.7)
        gh = self.w.create_widget({"type": "github", "repos": ["torvalds/linux"]})
        self.assertEqual(gh["repos"], ["torvalds/linux"])
        with self.assertRaises(self.w.WidgetError):
            self.w.create_widget({"type": "embed", "url": "https://example.com"})

    def test_embed_allowlist(self):
        self.cfg.update_config({"embed_allowlist": ["example.com"]})
        emb = self.w.create_widget({"type": "embed", "url": "https://example.com/page", "title": "Ex"})
        self.assertEqual(emb["url"], "https://example.com/page")
        with self.assertRaises(self.w.WidgetError):
            self.w.create_widget({"type": "embed", "url": "https://evil.test/"})

    def test_worldclocks(self):
        wc = self.w.create_widget(
            {
                "type": "worldclocks",
                "cities": [
                    {"label": "New York", "zone": "America/New_York"},
                    {"label": "London", "zone": "Europe/London"},
                ],
                "style": "analog",
                "mark_markets": True,
            }
        )
        self.assertEqual(len(wc["cities"]), 2)

    def test_reorder_and_replace(self):
        self.w.create_widget({"type": "note", "id": "a", "text": "A"})
        self.w.create_widget({"type": "note", "id": "b", "text": "B"})
        ids = [w["id"] for w in self.w.list_widgets()]
        flipped = list(reversed(ids))
        ordered = self.w.reorder_widgets(flipped)
        self.assertEqual([w["id"] for w in ordered], flipped)
        replaced = self.w.replace_widgets(
            [
                {"id": "clock", "type": "clock", "order": 0},
                {"id": "note1", "type": "note", "text": "Only", "order": 10},
            ]
        )
        self.assertEqual([w["id"] for w in replaced], ["clock", "note1"])

    def test_control_chars_rejected(self):
        with self.assertRaises(self.w.WidgetError):
            self.w.create_widget({"type": "note", "text": "bad\x00text"})

    def test_config_rejects_wildcard_bind(self):
        with self.assertRaises(ValueError):
            self.cfg.update_config({"extra_bind": ["0.0.0.0"]})

    def test_config_theme_and_defaults(self):
        pub = self.cfg.public_config()
        self.assertEqual(pub["mark"], "DESK")
        self.assertEqual(pub["port"], 8730)
        self.assertEqual(pub["timezone"], "auto")
        self.assertIn("timezone_resolved", pub)
        self.assertFalse(pub["bind_tailscale"])
        updated = self.cfg.update_config({"theme": "nord", "mark": "LAB"})
        self.assertEqual(updated["theme"], "nord")
        self.assertEqual(updated["mark"], "LAB")


class TimezoneTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config_path = Path(self.tmp.name) / "config.json"
        self.widgets_path = Path(self.tmp.name) / "widgets.json"
        self._tz = os.environ.get("TZ")
        os.environ["DESKBOARD_CONFIG"] = str(self.config_path)
        os.environ["DESKBOARD_WIDGETS"] = str(self.widgets_path)
        for name in list(sys.modules):
            if name in ("widgets", "deskboard_config", "fetches", "serve"):
                del sys.modules[name]
        import deskboard_config as cfg
        import fetches
        import widgets as w

        self.cfg = cfg
        self.fetches = fetches
        self.w = w

    def tearDown(self):
        if self._tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = self._tz
        os.environ.pop("DESKBOARD_WIDGETS", None)
        os.environ.pop("DESKBOARD_CONFIG", None)
        self.tmp.cleanup()

    def test_auto_resolves_from_tz_env(self):
        os.environ["TZ"] = "America/Chicago"
        self.config_path.write_text(json.dumps({"timezone": "auto"}), encoding="utf-8")
        self.assertEqual(self.cfg.resolved_timezone(), "America/Chicago")
        pub = self.cfg.public_config()
        self.assertEqual(pub["timezone"], "auto")
        self.assertEqual(pub["timezone_resolved"], "America/Chicago")

    def test_missing_or_empty_timezone_is_auto(self):
        os.environ["TZ"] = "Asia/Tokyo"
        self.config_path.write_text(json.dumps({"mark": "LAB"}), encoding="utf-8")
        self.assertEqual(self.cfg.load_config()["timezone"], "auto")
        self.assertEqual(self.cfg.resolved_timezone(), "Asia/Tokyo")
        self.config_path.write_text(json.dumps({"timezone": "  "}), encoding="utf-8")
        self.assertEqual(self.cfg.resolved_timezone(), "Asia/Tokyo")

    def test_explicit_iana_overrides_host(self):
        os.environ["TZ"] = "America/Chicago"
        self.config_path.write_text(json.dumps({"timezone": "America/New_York"}), encoding="utf-8")
        self.assertEqual(self.cfg.resolved_timezone(), "America/New_York")
        pub = self.cfg.public_config()
        self.assertEqual(pub["timezone"], "America/New_York")
        self.assertEqual(pub["timezone_resolved"], "America/New_York")

    def test_invalid_timezone_falls_back_to_auto(self):
        os.environ["TZ"] = "Europe/Paris"
        self.config_path.write_text(json.dumps({"timezone": "Not/ARealZone"}), encoding="utf-8")
        from contextlib import redirect_stderr
        from io import StringIO

        buf = StringIO()
        with redirect_stderr(buf):
            self.assertEqual(self.cfg.resolved_timezone(), "Europe/Paris")
        log = buf.getvalue()
        self.assertIn("Not/ARealZone", log)
        self.assertIn("auto", log.lower())

    def test_detect_order_timezone_file_then_localtime(self):
        root = Path(self.tmp.name)
        zone_file = root / "timezone"
        zone_file.write_text("Europe/Berlin\n", encoding="utf-8")
        target = root / "zoneinfo" / "Pacific" / "Auckland"
        target.parent.mkdir(parents=True)
        target.write_text("x", encoding="utf-8")
        link = root / "localtime"
        link.symlink_to(target)
        self.assertEqual(
            self.cfg.detect_host_timezone(
                tz_env=None,
                timezone_path=zone_file,
                localtime_path=link,
                run_timedatectl=False,
            ),
            "Europe/Berlin",
        )
        zone_file.write_text("Not/ARealZone\n", encoding="utf-8")
        self.assertEqual(
            self.cfg.detect_host_timezone(
                tz_env=None,
                timezone_path=zone_file,
                localtime_path=link,
                run_timedatectl=False,
            ),
            "Pacific/Auckland",
        )

    def test_detect_tz_env_path_and_colon_prefix(self):
        self.assertEqual(
            self.cfg.detect_host_timezone(
                tz_env=":America/Denver",
                timezone_path=Path(self.tmp.name) / "missing",
                localtime_path=Path(self.tmp.name) / "missing",
                run_timedatectl=False,
            ),
            "America/Denver",
        )
        self.assertEqual(
            self.cfg.detect_host_timezone(
                tz_env="/usr/share/zoneinfo/Europe/London",
                timezone_path=Path(self.tmp.name) / "missing",
                localtime_path=Path(self.tmp.name) / "missing",
                run_timedatectl=False,
            ),
            "Europe/London",
        )

    def test_detect_falls_back_to_utc(self):
        self.assertEqual(
            self.cfg.detect_host_timezone(
                tz_env=None,
                timezone_path=Path(self.tmp.name) / "missing",
                localtime_path=Path(self.tmp.name) / "missing",
                run_timedatectl=False,
            ),
            "UTC",
        )

    def test_update_config_accepts_auto_and_rejects_invalid(self):
        updated = self.cfg.update_config({"timezone": "auto"})
        self.assertEqual(updated["timezone"], "auto")
        self.assertIn("timezone_resolved", updated)
        with self.assertRaises(ValueError):
            self.cfg.update_config({"timezone": "Not/ARealZone"})

    def test_calendar_times_use_board_zone(self):
        from datetime import datetime, timezone

        ics = (
            "BEGIN:VCALENDAR\n"
            "BEGIN:VEVENT\n"
            "DTSTART:20261111T150000Z\n"
            "SUMMARY:Standup\n"
            "END:VEVENT\n"
            "END:VCALENDAR\n"
        )
        now = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)
        items = self.fetches._parse_ics_upcoming(ics, limit=5, board_tz="America/New_York", now=now)
        self.assertEqual(items, ["Wed 10:00  Standup"])
        naive = (
            "BEGIN:VCALENDAR\n"
            "BEGIN:VEVENT\n"
            "DTSTART:20261111T150000\n"
            "SUMMARY:Local meeting\n"
            "END:VEVENT\n"
            "END:VCALENDAR\n"
        )
        items = self.fetches._parse_ics_upcoming(naive, limit=5, board_tz="America/New_York", now=now)
        self.assertEqual(items, ["Wed 15:00  Local meeting"])

    def test_stamp_uses_resolved_auto_zone(self):
        from datetime import datetime, timezone

        os.environ["TZ"] = "America/New_York"
        self.config_path.write_text(json.dumps({"timezone": "auto"}), encoding="utf-8")
        noon_utc = datetime(2026, 11, 10, 17, 5, tzinfo=timezone.utc)
        self.assertEqual(self.w._clock_stamp(noon_utc), "12:05 PM")


class ScrubTests(unittest.TestCase):

    # Tokens are split so this file does not contain the forbidden strings.
    FORBIDDEN = [
        "nous" + "nuc16",
        "taild" + "713f5",
        "disco" + "posse",
        "100.79." + "241.116",
        "10.0.0." + "180",
    ]

    def test_repo_files_scrubbed(self):
        skip_dirs = {".git", "reference", "__pycache__", "node_modules", "shots"}
        skip_names = {"BRIEF.md", ".build.log", ".login.log"}
        hits = []
        for path in ROOT.rglob("*"):
            if not path.is_file():
                continue
            if any(part in skip_dirs for part in path.parts):
                continue
            if path.name in skip_names or path.name.startswith(".build.log"):
                continue
            if path.suffix.lower() in {".woff2", ".png", ".jpg", ".jpeg", ".gif", ".webp"}:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            lower = text.lower()
            for token in self.FORBIDDEN:
                if token.lower() in lower:
                    hits.append(f"{path.relative_to(ROOT)}: {token}")
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
