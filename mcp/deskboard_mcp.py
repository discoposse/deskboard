#!/usr/bin/env python3
"""Deskboard MCP server.

Lets AI assistants post status lines to a Deskboard and read what is on it.
It speaks MCP over stdio with the standard library only. `--http` serves
streamable HTTP on 127.0.0.1 through the official `mcp` SDK when installed.

Tools: post_status, list_tiles, read_tile, board_status. There are no tools
that create, delete, move, resize, theme, or import tiles.

Environment
  DESKBOARD_URL         board base URL, default http://127.0.0.1:8730
  DESKBOARD_SOURCE      default source name for post_status, default "Bot"
  DESKBOARD_MANAGED_BY  owner tag a tile needs before posting, default "bots"
  DESKBOARD_ALLOW_ANY_LIST=1  allow posts to any enabled list tile
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

VERSION = "0.1.0"
SERVER_NAME = "deskboard"
PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
SOURCE_MAX = 24
TEXT_MAX = 200
TIMEOUT = 10
# Fields from GET /api/status that could identify the machine. Left out.
PRIVATE_STATUS_KEYS = {"hostname", "host", "ip", "ips", "addr", "address", "addresses", "bind", "binds"}


class BoardError(Exception):
    """A message meant for the assistant. Never carries a stack trace."""


def board_url() -> str:
    url = os.environ.get("DESKBOARD_URL", "").strip() or "http://127.0.0.1:8730"
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise BoardError(f"DESKBOARD_URL must be an http or https URL, got {url!r}")
    return url.rstrip("/")


def default_source() -> str:
    return os.environ.get("DESKBOARD_SOURCE", "").strip() or "Bot"


def managed_tag() -> str:
    return os.environ.get("DESKBOARD_MANAGED_BY", "").strip() or "bots"


def allow_any_list() -> bool:
    return os.environ.get("DESKBOARD_ALLOW_ANY_LIST", "").strip().lower() in ("1", "true", "yes")


def _request(method: str, path: str, body: dict | None = None) -> tuple[int, object]:
    url = board_url() + path
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as res:
            raw = res.read()
            code = res.status
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        code = exc.code
    except (urllib.error.URLError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        raise BoardError(f"Could not reach the Deskboard at {board_url()} ({reason}). Check DESKBOARD_URL and that the board is running.") from None
    try:
        payload = json.loads(raw.decode("utf-8")) if raw else None
    except (UnicodeDecodeError, json.JSONDecodeError):
        payload = None
    return code, payload


def _error_text(payload) -> str:
    if isinstance(payload, dict) and isinstance(payload.get("error"), str):
        return payload["error"]
    return "no details"


def _check_id(widget_id) -> str:
    if not isinstance(widget_id, str) or not ID_RE.match(widget_id):
        raise BoardError("Tile id must be a short lowercase name such as botstatus.")
    return widget_id


def _plain(value, field: str, limit: int) -> str:
    if not isinstance(value, str):
        raise BoardError(f"{field} must be text.")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise BoardError(f"{field} must be one plain line with no newlines, tabs, or control characters.")
    value = " ".join(value.split())
    if not value:
        raise BoardError(f"{field} must not be empty.")
    if len(value) > limit:
        raise BoardError(f"{field} is limited to {limit} characters. Keep it short.")
    return value


def _get_tile(widget_id: str) -> dict:
    code, payload = _request("GET", f"/api/widgets/{widget_id}")
    if code == 404:
        raise BoardError(f"There is no tile named {widget_id} on the board. Do not create one. Ask the owner.")
    if code != 200 or not isinstance(payload, dict):
        raise BoardError(f"The board answered HTTP {code} for tile {widget_id}: {_error_text(payload)}")
    return payload


def _summary(widget: dict) -> dict:
    return {
        "id": widget.get("id"),
        "type": widget.get("type"),
        "title": widget.get("title") or widget.get("label") or "",
        "enabled": widget.get("enabled", True),
        "managed_by": widget.get("managed_by") or None,
    }


def post_status(text, source=None, widget: str = "botstatus") -> dict:
    widget = _check_id(widget or "botstatus")
    text = _plain(text, "text", TEXT_MAX)
    source = _plain(source if source not in (None, "") else default_source(), "source", SOURCE_MAX)
    tile = _get_tile(widget)
    if tile.get("enabled") is False:
        raise BoardError(f"Tile {widget} is hidden on the board. Not posting. The owner hid it on purpose.")
    if tile.get("type") != "list":
        raise BoardError(f"Tile {widget} is a {tile.get('type')} tile. Only list tiles take status posts.")
    tag = managed_tag()
    if tile.get("managed_by") != tag and not allow_any_list():
        owner = tile.get("managed_by")
        why = f"is managed by {owner}" if owner else "is not marked as managed"
        raise BoardError(
            f"Tile {widget} {why}. This server only posts to tiles with managed_by {tag!r}. "
            "Ask the owner to mark the tile, or set DESKBOARD_ALLOW_ANY_LIST=1."
        )
    code, payload = _request("POST", f"/api/widgets/{widget}/post", {"source": source, "text": text})
    if code in (404, 405):
        raise BoardError(
            f"The board at {board_url()} has no post route (HTTP {code}). It runs an older Deskboard server. "
            "Update it and restart the service, then try again."
        )
    if code != 200 or not isinstance(payload, dict):
        raise BoardError(f"The board refused the post (HTTP {code}): {_error_text(payload)}")
    items = payload.get("items") or []
    return {"posted": items[0] if items else "", "widget": widget, "lines": items}


def list_tiles() -> dict:
    code, payload = _request("GET", "/api/widgets")
    if code != 200 or not isinstance(payload, dict) or not isinstance(payload.get("widgets"), list):
        raise BoardError(f"The board answered HTTP {code} for the tile list: {_error_text(payload)}")
    return {"tiles": [_summary(w) for w in payload["widgets"] if isinstance(w, dict)]}


def read_tile(id) -> dict:  # noqa: A002 - the tool argument is called id
    return {"tile": _get_tile(_check_id(id))}


def board_status() -> dict:
    code, payload = _request("GET", "/api/status")
    if code != 200 or not isinstance(payload, dict):
        raise BoardError(f"The board answered HTTP {code} for status: {_error_text(payload)}")
    return {"status": {k: v for k, v in payload.items() if k.lower() not in PRIVATE_STATUS_KEYS}}


TOOLS = {
    "post_status": {
        "fn": post_status,
        "description": (
            "Post one short plain-text status line to a Deskboard list tile. The board adds the time and keeps the newest lines. "
            "Use it when a job finishes, fails, or needs the owner. No secrets, tokens, or private mail. "
            "Only posts to tiles marked managed_by bots. Never creates tiles."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "One short line, plain text, under 60 characters is best.", "maxLength": TEXT_MAX},
                "source": {"type": "string", "description": "Who is posting, for example the bot's name.", "maxLength": SOURCE_MAX},
                "widget": {"type": "string", "description": "Tile id. Defaults to botstatus.", "default": "botstatus"},
            },
            "required": ["text"],
            "additionalProperties": False,
        },
    },
    "list_tiles": {
        "fn": list_tiles,
        "description": "List the tiles on the Deskboard with id, type, title, enabled, and managed_by. Read-only.",
        "schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    "read_tile": {
        "fn": read_tile,
        "description": "Read one tile's stored fields by id. Read-only.",
        "schema": {
            "type": "object",
            "properties": {"id": {"type": "string", "description": "Tile id such as botstatus."}},
            "required": ["id"],
            "additionalProperties": False,
        },
    },
    "board_status": {
        "fn": board_status,
        "description": "Read the board's status (theme, timezone, uptime, load, memory). The hostname is left out. Read-only.",
        "schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
}


def call_tool(name: str, arguments: dict | None) -> tuple[bool, dict | str]:
    """Run a tool. Returns (ok, result or error message)."""
    tool = TOOLS.get(name)
    if tool is None:
        return False, f"Unknown tool {name}."
    args = arguments or {}
    if not isinstance(args, dict):
        return False, "Arguments must be an object."
    allowed = set(tool["schema"]["properties"])
    extra = sorted(set(args) - allowed)
    if extra:
        return False, "Unknown arguments: " + ", ".join(extra)
    missing = [key for key in tool["schema"].get("required", []) if key not in args]
    if missing:
        return False, "Missing arguments: " + ", ".join(missing)
    try:
        return True, tool["fn"](**args)
    except BoardError as exc:
        return False, str(exc)


# ---- stdio JSON-RPC (MCP) without dependencies ----------------------------


def _result_for(ok: bool, value) -> dict:
    if ok:
        return {"content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False)}], "structuredContent": value, "isError": False}
    return {"content": [{"type": "text", "text": str(value)}], "isError": True}


def handle(message: dict) -> dict | None:
    """Answer one JSON-RPC message. Notifications get no reply."""
    method = message.get("method")
    msg_id = message.get("id")
    is_request = "id" in message
    params = message.get("params") or {}

    def reply(result=None, error=None):
        if not is_request:
            return None
        out = {"jsonrpc": "2.0", "id": msg_id}
        if error is not None:
            out["error"] = error
        else:
            out["result"] = result
        return out

    if method == "initialize":
        asked = params.get("protocolVersion") if isinstance(params, dict) else None
        version = asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
        return reply(
            {
                "protocolVersion": version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": VERSION},
                "instructions": (
                    "Post short plain-text status lines with post_status when a job finishes, fails, or needs the owner. "
                    "Never include secrets, tokens, or private mail. The board cannot be changed in any other way through this server."
                ),
            }
        )
    if method in ("notifications/initialized", "notifications/cancelled") or (method or "").startswith("notifications/"):
        return None
    if method == "ping":
        return reply({})
    if method == "tools/list":
        tools = [{"name": name, "description": t["description"], "inputSchema": t["schema"]} for name, t in TOOLS.items()]
        return reply({"tools": tools})
    if method == "tools/call":
        if not isinstance(params, dict) or not isinstance(params.get("name"), str):
            return reply(error={"code": -32602, "message": "tools/call needs a tool name"})
        ok, value = call_tool(params["name"], params.get("arguments"))
        return reply(_result_for(ok, value))
    if method in ("resources/list", "prompts/list"):
        return reply({"resources": []} if method == "resources/list" else {"prompts": []})
    return reply(error={"code": -32601, "message": f"method not found: {method}"})


def serve_stdio(stdin=None, stdout=None) -> None:
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    while True:
        line = stdin.readline()
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            answer = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        else:
            if isinstance(message, list):
                answers = [a for a in (handle(m) for m in message if isinstance(m, dict)) if a]
                answer = answers or None
            elif isinstance(message, dict):
                answer = handle(message)
            else:
                answer = {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "invalid request"}}
        if answer is not None:
            stdout.write(json.dumps(answer, ensure_ascii=False) + "\n")
            stdout.flush()


# ---- optional streamable HTTP through the mcp SDK -------------------------


def serve_http(port: int) -> None:
    """Loopback only. Needs `pip install mcp`."""
    host = "127.0.0.1"  # loopback only, never 0.0.0.0
    try:
        from mcp.server.mcpserver import MCPServer  # type: ignore  # mcp 2.x

        server = MCPServer(SERVER_NAME, version=VERSION)
        start = lambda: server.run(transport="streamable-http", host=host, port=port)  # noqa: E731
    except ImportError:
        try:
            from mcp.server.fastmcp import FastMCP  # type: ignore  # mcp 1.x
        except ImportError:
            sys.exit("--http needs the mcp package. Install it with: pip install -r mcp/requirements-http.txt")
        server = FastMCP(SERVER_NAME, host=host, port=port)
        start = lambda: server.run(transport="streamable-http")  # noqa: E731

    def wrap(name):
        def run(**kwargs):
            ok, value = call_tool(name, kwargs)
            if not ok:
                raise ValueError(value)
            return value

        return run

    @server.tool(name="post_status", description=TOOLS["post_status"]["description"])
    def _post(text: str, source: str = "", widget: str = "botstatus") -> dict:
        return wrap("post_status")(text=text, source=source or None, widget=widget)

    @server.tool(name="list_tiles", description=TOOLS["list_tiles"]["description"])
    def _list() -> dict:
        return wrap("list_tiles")()

    @server.tool(name="read_tile", description=TOOLS["read_tile"]["description"])
    def _read(id: str) -> dict:  # noqa: A002
        return wrap("read_tile")(id=id)

    @server.tool(name="board_status", description=TOOLS["board_status"]["description"])
    def _status() -> dict:
        return wrap("board_status")()

    print(f"deskboard mcp: streamable HTTP on http://{host}:{port}/mcp", file=sys.stderr, flush=True)
    start()


def main(argv=None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] in (["-h"], ["--help"]):
        print(__doc__)
        return
    if argv[:1] == ["--version"]:
        print(VERSION)
        return
    if argv[:1] == ["--http"]:
        port = int(argv[1]) if len(argv) > 1 else 8740
        serve_http(port)
        return
    if argv:
        sys.exit("usage: deskboard_mcp.py [--http [port]]")
    try:
        board_url()
    except BoardError as exc:
        sys.exit(str(exc))
    print(f"deskboard mcp {VERSION}: stdio, board {board_url()}", file=sys.stderr, flush=True)
    serve_stdio()


if __name__ == "__main__":
    main()
