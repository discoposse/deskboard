# Changelog

## Unreleased

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
