#!/usr/bin/env python3
"""Unit tests for the tile catalog: discovery, validation, community tiles, and the scaffold."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

RELOAD = ("widgets", "deskboard_config", "fetches", "serve", "tiles")


class CatalogCase(unittest.TestCase):
    """Fresh modules per test, pointed at temp config and widget files."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.config_path = self.dir / "config.json"
        os.environ["DESKBOARD_WIDGETS"] = str(self.dir / "widgets.json")
        os.environ["DESKBOARD_CONFIG"] = str(self.config_path)
        os.environ.pop("DESKBOARD_TILES", None)
        self.load()

    def tearDown(self):
        self.tmp.cleanup()
        for key in ("DESKBOARD_WIDGETS", "DESKBOARD_CONFIG", "DESKBOARD_TILES"):
            os.environ.pop(key, None)

    def load(self):
        for name in list(sys.modules):
            if name in RELOAD:
                del sys.modules[name]
        import tiles
        import widgets

        self.tiles = tiles
        self.w = widgets

    def write_config(self, **values):
        self.config_path.write_text(json.dumps(values), encoding="utf-8")
        self.load()

    def tile_root(self):
        """A copy of the repo's tiles/ folder that a test may change."""
        root = self.dir / "tiles"
        shutil.copytree(ROOT / "tiles", root)
        os.environ["DESKBOARD_TILES"] = str(root)
        self.load()
        return root


class DiscoveryTests(CatalogCase):
    def test_repo_tiles_are_valid(self):
        found = self.tiles.discover(enabled_community=["quote"], reserved=self.w.BUILTIN_TYPES)
        self.assertEqual(found.problems, [])
        self.assertIn("metric", found.tiles)
        self.assertIn("quote", found.tiles)
        self.assertEqual(found.tiles["metric"].source, "core")
        self.assertEqual(found.tiles["quote"].source, "community")

    def test_metric_is_a_catalog_tile_and_types_keep_their_order(self):
        self.assertNotIn("metric", self.w.BUILTIN_TYPES)
        self.assertIsNotNone(self.w.catalog().get("metric"))
        listed = self.w.types()
        self.assertEqual(listed.index("metric"), 5)
        self.assertEqual(listed[:5], ("clock", "worldclocks", "stats", "note", "markdown"))

    def test_folder_without_render_is_skipped(self):
        root = self.tile_root()
        (root / "metric" / "render.js").unlink()
        found = self.tiles.discover(reserved=self.w.BUILTIN_TYPES)
        self.assertNotIn("metric", found.tiles)
        self.assertTrue(any("missing render.js" in p for p in found.problems))

    def test_id_must_match_folder(self):
        root = self.tile_root()
        spec = json.loads((root / "metric" / "tile.json").read_text())
        spec["id"] = "other"
        (root / "metric" / "tile.json").write_text(json.dumps(spec))
        found = self.tiles.discover(reserved=self.w.BUILTIN_TYPES)
        self.assertTrue(any("must match the folder name" in p for p in found.problems))

    def test_builtin_type_ids_are_refused(self):
        root = self.tile_root()
        shutil.copytree(root / "metric", root / "note")
        spec = json.loads((root / "note" / "tile.json").read_text())
        spec["id"] = "note"
        (root / "note" / "tile.json").write_text(json.dumps(spec))
        (root / "note" / "render.js").write_text((root / "note" / "render.js").read_text().replace('"metric"', '"note"'))
        (root / "note" / "tile.css").unlink()
        found = self.tiles.discover(reserved=self.w.BUILTIN_TYPES)
        self.assertNotIn("note", found.tiles)
        self.assertTrue(any("built-in widget type" in p for p in found.problems))

    def test_community_id_cannot_shadow_a_core_tile(self):
        root = self.tile_root()
        shutil.copytree(root / "metric", root / "community" / "metric")
        found = self.tiles.discover(enabled_community=["metric"], reserved=self.w.BUILTIN_TYPES)
        self.assertEqual(found.tiles["metric"].source, "core")
        self.assertTrue(any("already used" in p for p in found.problems))


class SpecTests(CatalogCase):
    def spec(self, **changes):
        spec = {
            "id": "sample",
            "name": "Sample",
            "description": "A test tile.",
            "fields": {"text": {"type": "line", "required": True, "max": 10}},
            "example": {"text": "hi"},
        }
        spec.update(changes)
        return spec

    def test_good_spec(self):
        self.tiles.validate_spec(self.spec())

    def test_bad_specs(self):
        bad = [
            self.spec(extra=1),
            self.spec(id="Bad Id"),
            self.spec(col_span=3),
            self.spec(fit="zoom"),
            self.spec(fields={}),
            self.spec(fields={"id": {"type": "line"}}),
            self.spec(fields={"text": {"type": "html"}}),
            self.spec(fields={"text": {"type": "line", "required": True, "default": "x"}}),
            self.spec(fields={"n": {"type": "integer", "min": 1, "max": 5}}, example={"n": 2}),
            self.spec(fields={"c": {"type": "choice", "options": ["a", "A"]}}, example={}),
            self.spec(example={"text": "x" * 11}),
            self.spec(example={"text": "hi", "other": 1}),
            self.spec(example={}),
        ]
        for spec in bad:
            with self.subTest(spec=spec):
                with self.assertRaises(self.tiles.TileSpecError):
                    self.tiles.validate_spec(spec)

    def test_render_js_checks(self):
        ok = 'DeskboardTiles.register("sample", { render(data, h) { return "<p>" + h.escape(data.text) + "</p>"; } });'
        self.assertEqual(self.tiles.check_render_js(ok, "sample"), [])
        # Words inside strings and comments are fine.
        self.assertEqual(self.tiles.check_render_js("// no fetch here\n" + ok.replace("<p>", "<p>window "), "sample"), [])
        for bad in (
            ok.replace("return", "fetch('/x'); return"),
            ok.replace("return", "document.title = 1; return"),
            ok.replace("return", "eval('1'); return"),
            ok.replace("return", "setTimeout(() => 1); return"),
            ok.replace('"sample"', '"other"'),
        ):
            with self.subTest(bad=bad):
                self.assertNotEqual(self.tiles.check_render_js(bad, "sample"), [])

    def test_tile_css_checks(self):
        good = ".board .tile-sample .x { color: var(--ink); }\n@media (max-width: 600px) { .tile-sample p { margin: 0; } }"
        self.assertEqual(self.tiles.check_tile_css(good, "sample"), [])
        for bad in (
            ".board .note { color: var(--ink); }",
            ".tile-sample { color: #fff; }",
            ".tile-sample { color: rgb(1, 2, 3); }",
            ".tile-sample { background: url(https://example.com/x.png); }",
            "@import 'x.css';",
            ".tile-sampler { margin: 0; }",
        ):
            with self.subTest(bad=bad):
                self.assertNotEqual(self.tiles.check_tile_css(bad, "sample"), [])


class ValidationTests(CatalogCase):
    def test_metric_matches_the_old_builder(self):
        m = self.w.create_widget({"type": "metric", "id": "m", "label": "Outside", "value": "12°", "hint": "roof", "trend": "+2"})
        self.assertEqual(list(m), ["id", "type", "enabled", "order", "col_span", "row_span", "label", "value", "hint", "trend"])
        cases = [
            ({"type": "metric", "value": "1"}, "label is required"),
            ({"type": "metric", "label": " ", "value": "1"}, "label is required"),
            ({"type": "metric", "label": "x", "value": "1", "extra": 1}, "unknown fields: extra"),
            ({"type": "metric", "label": "x", "value": "1", "hint": "a\nb"}, "hint must be a single line"),
            ({"type": "metric", "label": "x" * 25, "value": "1"}, "label is limited to 24 characters"),
            ({"type": "metric", "label": "x", "value": "1", "col_span": 3}, "col_span must be 1 or 2"),
        ]
        for data, message in cases:
            with self.subTest(data=data):
                with self.assertRaises(self.w.WidgetError) as ctx:
                    self.w.create_widget(data)
                self.assertEqual(str(ctx.exception), message)
                self.assertEqual(ctx.exception.status, 400)
        bare = self.w.create_widget({"type": "metric", "id": "bare", "label": "A", "value": "1"})
        self.assertEqual((bare["hint"], bare["trend"]), ("", ""))

    def test_patch_keeps_other_fields(self):
        self.w.create_widget({"type": "metric", "id": "m", "label": "A", "value": "1", "hint": "h"})
        updated = self.w.update_widget("m", {"trend": "-5", "col_span": 2})
        self.assertEqual((updated["label"], updated["hint"], updated["trend"], updated["col_span"]), ("A", "h", "-5", 2))
        with self.assertRaises(self.w.WidgetError) as ctx:
            self.w.update_widget("m", {"label": None})
        self.assertEqual(str(ctx.exception), "label must be a single line")
        self.assertEqual(self.w.update_widget("m", {"hint": None})["hint"], "")
        with self.assertRaises(self.w.WidgetError):
            self.w.update_widget("m", {"text": "nope"})

    def test_import_validates_catalog_fields(self):
        with self.assertRaises(self.w.WidgetError):
            self.w.replace_widgets([{"id": "m", "type": "metric", "label": "A"}])
        done = self.w.replace_widgets([{"id": "m", "type": "metric", "label": "A", "value": "1"}])
        self.assertEqual(done[0]["value"], "1")

    def test_widget_cap_still_applies(self):
        self.write_config(max_widgets=3)
        for i in range(1):
            self.w.create_widget({"type": "metric", "id": f"m{i}", "label": "A", "value": "1"})
        with self.assertRaises(self.w.WidgetError) as ctx:
            self.w.create_widget({"type": "metric", "id": "over", "label": "A", "value": "1"})
        self.assertEqual(ctx.exception.status, 409)
        with self.assertRaises(self.w.WidgetError):
            self.w.replace_widgets([{"id": f"m{i}", "type": "metric", "label": "A", "value": "1"} for i in range(4)])


class CommunityTests(CatalogCase):
    def test_off_by_default(self):
        self.assertEqual(self.w.load_config()["enabled_community_tiles"], [])
        self.assertIsNone(self.w.catalog().get("quote"))
        self.assertIn("quote", self.w.catalog().disabled)
        self.assertNotIn("quote", self.w.types())
        with self.assertRaises(self.w.WidgetError) as ctx:
            self.w.create_widget({"type": "quote", "quote": "Hi"})
        self.assertIn("type must be one of", str(ctx.exception))
        listed = {t["id"]: t for t in self.w.catalog().meta()}
        self.assertFalse(listed["quote"]["enabled"])

    def test_enabled_by_config(self):
        self.write_config(enabled_community_tiles=["quote"])
        q = self.w.create_widget({"type": "quote", "id": "q", "quote": "Line one\nLine two", "author": "Me"})
        self.assertEqual(q["quote"], "Line one\nLine two")
        with self.assertRaises(self.w.WidgetError):
            self.w.create_widget({"type": "quote", "quote": "\n".join("x" * 5)})

    def test_config_api_cannot_turn_tiles_on(self):
        import deskboard_config as cfg

        with self.assertRaises(ValueError):
            cfg.update_config({"enabled_community_tiles": ["quote"]})
        self.write_config(enabled_community_tiles=["quote"], mark="LAB")
        import deskboard_config as cfg

        cfg.update_config({"mark": "DESK"})
        self.assertEqual(cfg.load_config()["enabled_community_tiles"], ["quote"])

    def test_stored_tiles_of_a_disabled_tile_are_left_out(self):
        self.write_config(enabled_community_tiles=["quote"])
        self.w.create_widget({"type": "quote", "id": "q", "quote": "Hi"})
        self.write_config(enabled_community_tiles=[])
        ids = [w["id"] for w in self.w.list_widgets()]
        self.assertNotIn("q", ids)
        self.assertIn("clock", ids)

    def test_server_only_serves_enabled_tile_assets(self):
        import serve

        self.assertIsNotNone(serve.tile_asset("/tiles/metric/render.js"))
        self.assertIsNotNone(serve.tile_asset("/tiles/metric/tile.css"))
        self.assertIsNone(serve.tile_asset("/tiles/metric/tile.json"))
        self.assertIsNone(serve.tile_asset("/tiles/metric/README.md"))
        self.assertIsNone(serve.tile_asset("/tiles/quote/render.js"))
        self.assertIsNone(serve.tile_asset("/tiles/community/quote/render.js"))
        self.assertIn("GET /api/tiles", serve.api_index()["routes"])


class ScaffoldTests(CatalogCase):
    def test_scaffold_passes_validation(self):
        root = self.dir / "scratch"
        folder = self.tiles.scaffold("sun_hours", root=root, reserved=self.w.BUILTIN_TYPES)
        self.assertEqual(sorted(p.name for p in folder.iterdir()), ["README.md", "render.js", "tile.css", "tile.json"])
        found = self.tiles.discover(root=root, reserved=self.w.BUILTIN_TYPES)
        self.assertEqual(found.problems, [])
        self.assertIn("sun_hours", found.tiles)
        readme = (folder / "README.md").read_text()
        self.assertIn('"type":"sun_hours"', readme)
        self.assertIn("\\\n", readme)

    def test_community_scaffold_is_off(self):
        root = self.dir / "scratch"
        self.tiles.scaffold("my_quote", community=True, root=root)
        found = self.tiles.discover(root=root)
        self.assertEqual(found.problems, [])
        self.assertIn("my_quote", found.disabled)

    def test_scaffold_refuses_bad_ids(self):
        root = self.dir / "scratch"
        self.tiles.scaffold("taken", root=root)
        for bad in ("taken", "Bad", "x", "note", "community", "has-dash"):
            with self.subTest(bad=bad):
                with self.assertRaises(self.tiles.TileSpecError):
                    self.tiles.scaffold(bad, root=root, reserved=self.w.BUILTIN_TYPES)

    def test_new_tile_script(self):
        root = self.dir / "scratch"
        root.mkdir()
        env = dict(os.environ, DESKBOARD_TILES=str(root))
        run = lambda *args: subprocess.run(
            ["bash", str(ROOT / "scripts" / "new_tile.sh"), *args], env=env, capture_output=True, text=True, timeout=60
        )
        made = run("bike_count")
        self.assertEqual(made.returncode, 0, made.stderr)
        self.assertTrue((root / "bike_count" / "tile.json").is_file())
        community = run("haiku", "--community")
        self.assertEqual(community.returncode, 0, community.stderr)
        self.assertTrue((root / "community" / "haiku" / "render.js").is_file())
        self.assertIn("enabled_community_tiles", community.stdout)
        self.assertNotEqual(run("bike_count").returncode, 0)
        self.assertNotEqual(run("list").returncode, 0)
        self.assertNotEqual(run().returncode, 0)


if __name__ == "__main__":
    unittest.main()
