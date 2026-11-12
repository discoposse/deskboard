#!/usr/bin/env python3
"""Tests for the Deskboard MCP server against a real board on a loopback port."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "mcp"))

FRESH = ("widgets", "deskboard_config", "fetches", "serve", "tiles", "deskboard_mcp")
SERVER = ROOT / "mcp" / "deskboard_mcp.py"


class BoardCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        os.environ["DESKBOARD_WIDGETS"] = str(self.dir / "widgets.json")
        os.environ["DESKBOARD_CONFIG"] = str(self.dir / "config.json")
        os.environ["DESKBOARD_HOSTNAME"] = "secret-host-name"
        for key in ("DESKBOARD_SOURCE", "DESKBOARD_ALLOW_ANY_LIST", "DESKBOARD_MANAGED_BY"):
            os.environ.pop(key, None)
        for name in list(sys.modules):
            if name in FRESH:
                del sys.modules[name]
        import deskboard_mcp
        import serve
        import widgets

        self.m = deskboard_mcp
        self.w = widgets
        self.w.create_widget({"type": "list", "id": "botstatus", "title": "Bots", "items": ["Waiting"], "managed_by": "bots"})
        self.w.create_widget({"type": "list", "id": "todo", "title": "Todo", "items": ["Ship"]})
        self.w.create_widget({"type": "list", "id": "meetings", "title": "Meetings", "items": ["None"], "managed_by": "calendar"})
        self.w.create_widget({"type": "note", "id": "memo", "text": "hi", "managed_by": "bots"})
        self.server = serve.Server4(("127.0.0.1", 0), serve.Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        os.environ["DESKBOARD_URL"] = self.url
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()
        for key in ("DESKBOARD_WIDGETS", "DESKBOARD_CONFIG", "DESKBOARD_HOSTNAME", "DESKBOARD_URL", "DESKBOARD_SOURCE", "DESKBOARD_ALLOW_ANY_LIST"):
            os.environ.pop(key, None)

    def items(self, widget_id):
        return self.w.get_widget(widget_id)["items"]


class ToolTests(BoardCase):
    def test_post_status_to_botstatus(self):
        ok, out = self.m.call_tool("post_status", {"text": "Backup finished", "source": "Backup"})
        self.assertTrue(ok, out)
        self.assertRegex(out["posted"], r"^\d{1,2}:\d\d (AM|PM)  Backup  Backup finished$")
        self.assertEqual(self.items("botstatus")[0], out["posted"])

    def test_post_flash_reaches_the_board(self):
        import flashes

        flashes.reset_flashes()
        ok, out = self.m.call_tool(
            "post_flash",
            {"title": "Leave in 10 minutes", "body": "Downtown review starts soon.", "source": "Calendar", "level": "warning", "duration": 30},
        )
        self.assertTrue(ok, out)
        self.assertEqual(out["title"], "Leave in 10 minutes")
        self.assertEqual(out["level"], "warning")
        self.assertEqual(out["duration"], 30)
        self.assertFalse(out["deduped"])
        again, replay = self.m.call_tool(
            "post_flash",
            {"title": "Leave in 10 minutes", "body": "Downtown review starts soon.", "source": "Calendar", "level": "warning"},
        )
        self.assertTrue(again, replay)
        self.assertTrue(replay["deduped"])
        self.assertEqual(replay["id"], out["id"])
        ok, msg = self.m.call_tool("post_flash", {"title": "Hi", "body": "There", "level": "panic"})
        self.assertFalse(ok)
        self.assertIn("level", msg)
        flashes.reset_flashes()

    def test_default_source_comes_from_env(self):
        os.environ["DESKBOARD_SOURCE"] = "Night bot"
        ok, out = self.m.call_tool("post_status", {"text": "hello"})
        self.assertTrue(ok, out)
        self.assertIn("Night bot  hello", out["posted"])

    def test_refuses_tiles_not_managed_by_bots(self):
        for widget in ("todo", "meetings"):
            with self.subTest(widget=widget):
                ok, msg = self.m.call_tool("post_status", {"text": "x", "widget": widget})
                self.assertFalse(ok)
                self.assertIn("managed_by 'bots'", msg)
        self.assertEqual(self.items("todo"), ["Ship"])

    def test_allow_any_list_flag(self):
        os.environ["DESKBOARD_ALLOW_ANY_LIST"] = "1"
        ok, out = self.m.call_tool("post_status", {"text": "x", "widget": "todo"})
        self.assertTrue(ok, out)
        ok, msg = self.m.call_tool("post_status", {"text": "x", "widget": "memo"})
        self.assertFalse(ok)
        self.assertIn("Only list tiles", msg)

    def test_hidden_and_missing_tiles_are_refused_and_never_created(self):
        self.w.update_widget("botstatus", {"enabled": False})
        ok, msg = self.m.call_tool("post_status", {"text": "x"})
        self.assertFalse(ok)
        self.assertIn("hidden", msg)
        ok, msg = self.m.call_tool("post_status", {"text": "x", "widget": "ghost"})
        self.assertFalse(ok)
        self.assertIn("Do not create one", msg)
        self.assertNotIn("ghost", [w["id"] for w in self.w.list_widgets()])

    def test_plain_text_rules(self):
        for args in ({"text": "two\nlines"}, {"text": "tab\there"}, {"text": "esc\x1b"}, {"text": ""}, {"text": "x" * 201}, {"text": "ok", "source": "s" * 25}, {"text": 5}):
            with self.subTest(args=args):
                ok, _msg = self.m.call_tool("post_status", args)
                self.assertFalse(ok)
        self.assertEqual(self.items("botstatus"), ["Waiting"])

    def test_bad_arguments(self):
        self.assertFalse(self.m.call_tool("post_status", {})[0])
        self.assertFalse(self.m.call_tool("post_status", {"text": "x", "colour": "red"})[0])
        self.assertFalse(self.m.call_tool("read_tile", {"id": "../config"})[0])
        self.assertFalse(self.m.call_tool("delete_tile", {"id": "todo"})[0])

    def test_list_and_read(self):
        ok, out = self.m.call_tool("list_tiles", {})
        self.assertTrue(ok)
        bot = next(t for t in out["tiles"] if t["id"] == "botstatus")
        self.assertEqual(bot, {"id": "botstatus", "type": "list", "title": "Bots", "enabled": True, "managed_by": "bots"})
        ok, out = self.m.call_tool("read_tile", {"id": "todo"})
        self.assertTrue(ok)
        self.assertEqual(out["tile"]["items"], ["Ship"])

    def test_board_status_leaves_out_the_hostname(self):
        ok, out = self.m.call_tool("board_status", {})
        self.assertTrue(ok)
        self.assertNotIn("hostname", out["status"])
        self.assertNotIn("secret-host-name", json.dumps(out))
        self.assertIn("timezone", out["status"])

    def test_only_safe_tools_exist(self):
        self.assertEqual(sorted(self.m.TOOLS), ["board_status", "list_tiles", "post_flash", "post_status", "read_tile"])


class OldServerHandler(BaseHTTPRequestHandler):
    """A board from before the post route. GET works, the post route is 404."""

    def log_message(self, *args):
        pass

    def _send(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/widgets/botstatus":
            self._send(200, {"id": "botstatus", "type": "list", "enabled": True, "items": ["a"], "managed_by": "bots"})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        self._send(404, {"error": "widget not found"})


class OldAndMissingBoardTests(unittest.TestCase):
    def setUp(self):
        for name in list(sys.modules):
            if name in FRESH:
                del sys.modules[name]
        import deskboard_mcp

        self.m = deskboard_mcp

    def test_old_server_gets_a_clear_message(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), OldServerHandler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            os.environ["DESKBOARD_URL"] = f"http://127.0.0.1:{server.server_address[1]}"
            ok, msg = self.m.call_tool("post_status", {"text": "x"})
            self.assertFalse(ok)
            self.assertIn("older Deskboard server", msg)
        finally:
            server.shutdown()
            server.server_close()
            os.environ.pop("DESKBOARD_URL", None)

    def test_unreachable_board(self):
        os.environ["DESKBOARD_URL"] = "http://127.0.0.1:9"
        try:
            ok, msg = self.m.call_tool("list_tiles", {})
            self.assertFalse(ok)
            self.assertIn("Could not reach the Deskboard", msg)
        finally:
            os.environ.pop("DESKBOARD_URL", None)

    def test_bad_url(self):
        os.environ["DESKBOARD_URL"] = "file:///etc/passwd"
        try:
            ok, msg = self.m.call_tool("list_tiles", {})
            self.assertFalse(ok)
            self.assertIn("http or https", msg)
        finally:
            os.environ.pop("DESKBOARD_URL", None)


class StdioTests(BoardCase):
    def rpc(self, messages):
        lines = "".join(json.dumps(m) + "\n" for m in messages)
        env = {**os.environ, "DESKBOARD_URL": self.url, "DESKBOARD_SOURCE": "Stdio bot"}
        proc = subprocess.run([sys.executable, str(SERVER)], input=lines, env=env, capture_output=True, text=True, timeout=30)
        return [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]

    def test_stdio_session(self):
        out = self.rpc(
            [
                {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "post_status", "arguments": {"text": "over stdio"}}},
                {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "post_status", "arguments": {"text": "x", "widget": "todo"}}},
                {"jsonrpc": "2.0", "id": 5, "method": "nope"},
            ]
        )
        self.assertEqual([m.get("id") for m in out], [1, 2, 3, 4, 5])
        self.assertEqual(out[0]["result"]["protocolVersion"], "2025-06-18")
        self.assertEqual(out[0]["result"]["serverInfo"]["name"], "deskboard")
        self.assertEqual(sorted(t["name"] for t in out[1]["result"]["tools"]), ["board_status", "list_tiles", "post_flash", "post_status", "read_tile"])
        self.assertFalse(out[2]["result"]["isError"])
        self.assertIn("Stdio bot  over stdio", out[2]["result"]["structuredContent"]["posted"])
        self.assertTrue(out[3]["result"]["isError"])
        self.assertEqual(out[4]["error"]["code"], -32601)
        self.assertIn("Stdio bot  over stdio", self.items("botstatus")[0])

    def test_unknown_protocol_version_gets_the_latest(self):
        out = self.rpc([{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "1999-01-01"}}])
        self.assertEqual(out[0]["result"]["protocolVersion"], "2025-06-18")


if __name__ == "__main__":
    unittest.main()
