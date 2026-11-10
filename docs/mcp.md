# Deskboard MCP server

`mcp/deskboard_mcp.py` lets any assistant that speaks the Model Context Protocol post status lines to your board and read what is on it. It runs over stdio with the Python standard library, so there is nothing to install beyond Python 3.9 or newer.

## Tools

| Tool | What it does |
| --- | --- |
| `post_status(text, source?, widget="botstatus")` | Adds one plain-text line to a list tile through `POST /api/widgets/{id}/post`. |
| `list_tiles()` | Lists tiles with `id`, `type`, `title`, `enabled`, and `managed_by`. |
| `read_tile(id)` | Returns one tile's stored fields. |
| `board_status()` | Returns `GET /api/status` with the hostname left out. |

There are no tools that create, delete, move, resize, theme, or import tiles. The server cannot change the board in any way other than adding a status line.

## Safety rules

- Posts go only to enabled list tiles with `"managed_by": "bots"`. Anything else is refused with a message that says why. Set `DESKBOARD_ALLOW_ANY_LIST=1` to allow any enabled list tile, or `DESKBOARD_MANAGED_BY` to use another owner tag.
- A missing or hidden tile is refused, and the server never creates one.
- Text is one plain line of at most 200 characters, and the source name is at most 24. Newlines, tabs, and other control characters are refused. The board trims each line to 80 characters.
- The server sends no secrets because it has none. Keep secrets, tokens, codes, and private mail out of what your assistant posts, since every device that can reach the board can read it.
- An older board without the post route answers `404` or `405`. The MCP server reports that the board needs an update and a restart, and it does not fall back to editing the tile.
- An unreachable board gets a clear error naming `DESKBOARD_URL`.

## Settings

| Variable | Default | Meaning |
| --- | --- | --- |
| `DESKBOARD_URL` | `http://127.0.0.1:8730` | Board base URL |
| `DESKBOARD_SOURCE` | `Bot` | Source name when `post_status` gets none |
| `DESKBOARD_MANAGED_BY` | `bots` | Owner tag a tile needs before posts are allowed |
| `DESKBOARD_ALLOW_ANY_LIST` | off | Set to `1` to post to any enabled list tile |

## Install

Clone the repo on the machine where your assistant runs. That machine needs to reach the board, on loopback or over your tailnet.

```bash
git clone <this-repo-url> ~/apps/deskboard
python3 ~/apps/deskboard/mcp/deskboard_mcp.py --version
```

The stdio server needs nothing else. The optional HTTP mode needs the official SDK.

```bash
python3 -m venv ~/apps/deskboard/.venv
~/apps/deskboard/.venv/bin/pip install -r ~/apps/deskboard/mcp/requirements-http.txt
```

With `uv`, skip the venv and run `uv run --with mcp ~/apps/deskboard/mcp/deskboard_mcp.py --http 8740`. Both 1.x and 2.x of the SDK work.

## Cursor

Add this to `~/.cursor/mcp.json`, or to `.cursor/mcp.json` in a project.

```json
{
  "mcpServers": {
    "deskboard": {
      "command": "python3",
      "args": ["/home/you/apps/deskboard/mcp/deskboard_mcp.py"],
      "env": {
        "DESKBOARD_URL": "http://<your-board-url>:8730",
        "DESKBOARD_SOURCE": "Cursor"
      }
    }
  }
}
```

## Claude Desktop

Add the same block to `claude_desktop_config.json` (Settings, Developer, Edit Config) and restart Claude Desktop.

```json
{
  "mcpServers": {
    "deskboard": {
      "command": "python3",
      "args": ["/home/you/apps/deskboard/mcp/deskboard_mcp.py"],
      "env": {
        "DESKBOARD_URL": "http://<your-board-url>:8730",
        "DESKBOARD_SOURCE": "Claude"
      }
    }
  }
}
```

## Other stdio clients

Any bot or client that launches a stdio MCP server needs the same three things.

```text
command  python3
args     /home/you/apps/deskboard/mcp/deskboard_mcp.py
env      DESKBOARD_URL=http://<your-board-url>:8730
         DESKBOARD_SOURCE=<bot name>
```

Use an absolute path to the Python you want, such as a venv's `bin/python`, if `python3` on the client's `PATH` is older than 3.9.

## Streamable HTTP

```bash
DESKBOARD_URL=http://<your-board-url>:8730 ~/apps/deskboard/.venv/bin/python ~/apps/deskboard/mcp/deskboard_mcp.py --http 8740
```

This serves `http://127.0.0.1:8740/mcp` through the SDK with the same four tools. It binds loopback only and adds no CORS headers. Do not put it behind a public proxy. Stdio is the main path, and most clients should use it.

## Try it by hand

```bash
printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18"}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"post_status","arguments":{"text":"MCP server connected"}}}' \
  | DESKBOARD_URL=http://<your-board-url>:8730 python3 mcp/deskboard_mcp.py
```

The second reply carries the posted line. `tests/test_mcp.py` runs the same session against a test board.

## What to tell your assistant

The prompt in [bots.md](bots.md#how-to-get-your-bot-to-update-your-deskboard) works with the MCP server too. Replace the curl command with "call the deskboard `post_status` tool" and keep the rules.
