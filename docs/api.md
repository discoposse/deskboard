# API reference

Base URL for local work: `http://127.0.0.1:8730`.

Mutations need `Content-Type: application/json`. There is no CORS and no API token. Reachability is the boundary. Browser pages on other origins cannot call it. `curl` and scripts can.

Errors look like `{"error":"..."}`. Useful codes are `400` validation, `403` peer not allowed, `404` missing, `409` conflict (duplicate id, second singleton, widget cap, stale revision), `413` body over 64KB, `415` wrong content type.

## Routes

```text
GET    /api
GET    /api/status
GET    /api/config
PATCH  /api/config
GET    /api/themes
GET    /api/tiles
POST   /api/reload
GET    /api/widgets
POST   /api/widgets
GET    /api/widgets/{id}
PATCH  /api/widgets/{id}
DELETE /api/widgets/{id}
PUT    /api/widgets/order
PUT    /api/widgets/import
POST   /api/widgets/{id}/post
GET    /api/widget-data/{id}
GET    /api/github
```

`GET /api` lists types, the widget cap, and routes.

## Config

`GET /api/config` returns the public settings mark, timezone, timezone_resolved, port, night dim window, theme, max_widgets, embed_allowlist, bind_tailscale, extra_bind, grid_cols, grid_rows, enabled_community_tiles.

`timezone` may be `auto` (the default, follow the host machine) or an IANA name such as `America/New_York`. `timezone_resolved` is the zone the clock, calendar, and bot stamps use. An invalid `timezone` value falls back to `auto` and the server logs a warning. Existing configs that already set an IANA name keep working.

`PATCH /api/config` accepts a subset of those keys. Unknown keys are rejected. `port`, `enabled_community_tiles`, and `timezone_resolved` are not editable here. `port` and `enabled_community_tiles` are read from `config.json` only. `extra_bind` may not include `0.0.0.0` or `::`. The clock timezone is display-only. The OS timezone is never changed.

## Widgets

Every widget has `id`, `type`, `enabled`, `order`, `col_span`, `row_span` (spans are `1` or `2`). Any widget may also have `managed_by`, a short lowercase owner name such as `bots`. Type-specific fields are listed in [widgets.md](widgets.md).

Unknown fields are rejected. Send only the fields you mean to change on `PATCH`.

`PUT /api/widgets/order` body: `{"ids":["clock","stats",...]}` with every id once.

`PUT /api/widgets/import` with `{"widgets":[...]}` replaces the whole layout atomically. Two optional keys exist. `base_revision` makes the import conditional, and `keep_managed: true` keeps the stored content of managed tiles and takes only their layout from the request.

`GET /api/widgets` returns `{"widgets": [...], "revision": 12, "layout_revision": 11}`. Widget responses carry the same numbers in `X-Deskboard-Revision` and `X-Deskboard-Layout-Revision`. Send `If-Match: <layout_revision>` on any widget write to make it conditional. A stale write gets `409` with `"stale": true` and changes nothing. Writes without a revision are not checked.

`POST /api/widgets/{id}/post` with `{"source":"Backup","text":"Nightly backup finished"}` adds a timestamped line to the top of a list tile and keeps the newest `max_items`. It returns `404` for a missing or hidden tile and never creates one. See [bots.md](bots.md).

## Tiles

`GET /api/tiles` lists every tile folder the server found at startup or at the last reload, with its fields, example values, and whether it is enabled. `POST /api/reload` with `{}` rescans `tiles/` and returns what loaded and what was skipped (see [tiles.md](tiles.md#reloading)). Catalog tiles use the widget routes above and count toward the widget cap. See [tiles.md](tiles.md).

## Live data

Network-backed tiles fetch on the server:

- `GET /api/widget-data/{id}` for weather, calendar, RSS, GitHub, and status widgets.
- `GET /api/github` aggregates every GitHub tile.

Optional GitHub auth uses the `DESKBOARD_GITHUB_TOKEN` environment variable only. Tokens are never stored in widget JSON.

## Access model

The server always listens on loopback. With `bind_tailscale: true` it also binds Tailscale addresses (`100.64.0.0/10` and `fd7a:115c:a1e0::/48`). `extra_bind` can add specific addresses you own. LAN catch-all and public catch-all binds are refused. Peers outside the allowed set get `403`.
