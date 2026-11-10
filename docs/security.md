# Security notes

Deskboard is a private desk display, not a public web app.

## Reachability is the boundary

- Default bind is loopback only (`127.0.0.1` / `::1`).
- Optional Tailscale bind uses CGNAT Tailscale ranges only.
- `extra_bind` can add specific addresses you control. Wildcards like `0.0.0.0` are rejected.
- There is no CORS. Other browser origins cannot call the API.
- There is no login. Everything on the board is readable by every device that can reach the port.

Prefer Tailscale (tailnet only) for remote editing. Do not put the port on the open internet. Do not enable a public funnel to this service.

## Content rules

- Widget JSON is plain text with strict validation.
- Unknown fields are rejected.
- Control characters are rejected.
- Widget count is capped (`max_widgets`, default 16).
- Embed URLs must match `embed_allowlist` hostnames.
- GitHub tokens come from `DESKBOARD_GITHUB_TOKEN` in the environment only. Never paste tokens into widget JSON or notes.

## Tile code

Tile folders under `tiles/` ship a small `render.js` that runs in the board page. The board limits what that code can do.

- Render output is rebuilt from a short list of text tags with only `class` kept. Scripts, images, links, frames, and inline styles never reach the page.
- `tiles.py check` refuses render code that names network, storage, DOM, timer, or dynamic code globals.
- Pages carry `Content-Security-Policy: connect-src 'self'`, so page scripts can only call this server.
- Community tiles under `tiles/community/` are off until their id is listed in `enabled_community_tiles` in `config.json`. The API cannot turn them on.

These checks are guard rails. Read a community tile before you enable it.

Treat the board like a shared whiteboard. No secrets, no private mail, no credentials.

## Kiosk notes

The Ubuntu path runs Cage + WebKitGTK with hardware acceleration forced off for older Intel GPUs. The page must still look right offline. Remote fonts and remote CSS are not used. Network widgets fetch on the server, except user-chosen embeds which load in a sandboxed iframe.
