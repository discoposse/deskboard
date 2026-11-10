# Changelog

## Unreleased

- Deskboard MCP server in `mcp/deskboard_mcp.py`. Stdio with the standard library, optional streamable HTTP on 127.0.0.1 through the `mcp` SDK. Tools are `post_status`, `list_tiles`, `read_tile`, and `board_status`. Posts go only to list tiles managed by `bots` unless `DESKBOARD_ALLOW_ANY_LIST=1`. `docs/mcp.md` covers Cursor, Claude Desktop, and other stdio clients.

- Managed tiles. An optional `managed_by` on any widget marks it as filled by a bot. The configurator shows its content read-only and still edits its size, order, and visibility. Apply sends `keep_managed`, so it never writes over a bot's content.
- Layout revisions. `GET /api/widgets` returns `revision` and `layout_revision`, also as headers. `If-Match` or `base_revision` makes a write conditional, and a stale write gets `409`. The configurator shows a notice with **Reload from board** instead of overwriting. Writes without a revision work as before.
- `POST /api/widgets/{id}/post` adds a timestamped line to a list tile, keeps the newest `max_items` (default 6), and never creates a tile. `scripts/post.sh` wraps it.
- `docs/bots.md`, including how to get your bot to update your Deskboard.

- Tile catalog. Each tile type outside the built-in set is a folder under `tiles/` with `tile.json`, `render.js`, an optional `tile.css`, and `README.md`. The server discovers folders at startup and validates widget fields against `tile.json`.
- The metric widget now lives in `tiles/metric/` as the reference tile. Its API and look are unchanged.
- `tiles/community/` for contributed tiles, off until listed in the new `enabled_community_tiles` config key (file only, not editable through `PATCH /api/config`). Includes a sample `quote` tile.
- `scripts/new_tile.sh <id>` scaffolds a tile that passes `python3 tiles.py check`.
- `/?tilepreview=<id>` shows one tile at every span, and `scripts/run_overflow.sh` now checks every discovered tile in every theme and size.
- `POST /api/reload`, `scripts/reload.sh`, and a **Reload tiles** button in the configurator pick up new and changed tiles without a restart. The board refetches tile code within 5 seconds, and a tile that fails after an edit keeps its last good version.
- `GET /api/tiles` lists the catalog. Pages are served with `Content-Security-Policy: connect-src 'self'`.
- `docs/tiles.md`, a tile checklist in `CONTRIBUTING.md`, and a pull request template.
- README examples with an animation of the configurator and the board side by side, recorded by `scripts/record_demo.sh`.
- Fix the board not switching themes until a reload when the theme changed in the configurator or through `PATCH /api/config`.

## 0.1.0

- First community release of Deskboard.
- Stdlib Python server with loopback bind, optional Tailscale and extra binds, no CORS.
- Tile grid frontend with overflow fitting from small landscape up to 4K and portrait.
- Drag-and-drop configurator at `/?config` with theme picker, widget gallery, span controls, import/export, and undo.
- Widget types: clock, world clocks, stats, note, markdown, metric, list, weather, countdown, calendar, GitHub stars, embed, RSS, image, timer, status, theme card.
- Theme system with warm-dark default plus Tokyo Night, Catppuccin, Gruvbox, Nord, Rose Pine, Tiling, and Paper.
- Ubuntu kiosk install via Cage + WebKitGTK.
- Unit tests and headless overflow checks.
