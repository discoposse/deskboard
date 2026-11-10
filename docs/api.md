# API reference

Base URL for local work: `http://127.0.0.1:8730`.

Mutations need `Content-Type: application/json`. There is no CORS and no API token. Reachability is the boundary. Browser pages on other origins cannot call it. `curl` and scripts can.

Errors look like `{"error":"..."}`. Useful codes: `400` validation, `403` peer not allowed, `404` missing, `409` conflict (duplicate id, second singleton, widget cap), `413` body over 64KB, `415` wrong content type.

## Routes

```text
GET    /api
GET    /api/status
GET    /api/config
PATCH  /api/config
GET    /api/themes
GET    /api/widgets
POST   /api/widgets
GET    /api/widgets/{id}
PATCH  /api/widgets/{id}
DELETE /api/widgets/{id}
PUT    /api/widgets/order
PUT    /api/widgets/import
GET    /api/widget-data/{id}
GET    /api/github
```

`GET /api` lists types, the widget cap, and routes.

## Config

`GET /api/config` returns public settings: mark, timezone, port, night dim window, theme, max_widgets, embed_allowlist, bind_tailscale, extra_bind, grid_cols, grid_rows.

`PATCH /api/config` accepts a subset of those keys. Unknown keys are rejected. `extra_bind` may not include `0.0.0.0` or `::`. The clock timezone is display-only. The OS timezone is never changed.

## Widgets

Every widget has `id`, `type`, `enabled`, `order`, `col_span`, `row_span` (spans are `1` or `2`). Type-specific fields are listed in [widgets.md](widgets.md).

Unknown fields are rejected. Send only the fields you mean to change on `PATCH`.

`PUT /api/widgets/order` body: `{"ids":["clock","stats",...]}` with every id once.

`PUT /api/widgets/import` body: `{"widgets":[...]}` replaces the whole layout atomically.

## Live data

Network-backed tiles fetch on the server:

- `GET /api/widget-data/{id}` for weather, calendar, RSS, GitHub, and status widgets.
- `GET /api/github` aggregates every GitHub tile.

Optional GitHub auth uses the `DESKBOARD_GITHUB_TOKEN` environment variable only. Tokens are never stored in widget JSON.

## Access model

The server always listens on loopback. With `bind_tailscale: true` it also binds Tailscale addresses (`100.64.0.0/10` and `fd7a:115c:a1e0::/48`). `extra_bind` can add specific addresses you own. LAN catch-all and public catch-all binds are refused. Peers outside the allowed set get `403`.
