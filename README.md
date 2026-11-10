# Deskboard

A self-hosted desk dashboard for a spare mini PC and a monitor. It runs fullscreen in a kiosk browser, shows a tile grid that always fits the screen, and lets you edit the layout from another machine on your private network.

![Deskboard demo at 1920x1080](shots/board-demo-1920x1080.png)

![Tiling theme](shots/board-theme-tiling-1920x1080.png)

## Quick start (any OS)

Needs Python 3.10+.

```bash
cp config.example.json config.json
python3 serve.py
```

Open:

- Board: `http://127.0.0.1:8730`
- Configurator: `http://127.0.0.1:8730/?config`

No build step. The page is plain HTML, CSS, and JS with fonts vendored under `web/fonts/`.

Load the sample layout:

```bash
curl -s http://127.0.0.1:8730/api/widgets/import \
  -X PUT -H 'Content-Type: application/json' \
  --data-binary @examples/demo-board.json
```

## Install as a desk kiosk (Ubuntu)

See [docs/install-ubuntu.md](docs/install-ubuntu.md). Short version:

```bash
sudo DESKBOARD_USER="$USER" ./install.sh
```

That installs Cage + WebKitGTK, writes systemd units, and starts the board on the attached display.

## What you get

- Tile grid that stays inside the viewport from 1024x600 up to 4K, including portrait
- Drag-and-drop configurator: drop files, reorder tiles, resize spans, live preview
- Themes (warm dark default, plus Tokyo Night, Catppuccin, Gruvbox, Nord, Rose Pine, Tiling, Paper)
- Widgets for notes, lists, metrics, markdown, weather, countdown, ICS calendar, GitHub stars, embeds, RSS, images, timers, URL status, world clocks, and theme art cards
- Stdlib Python server. No CORS. Loopback by default. Optional Tailscale bind

## Security in one paragraph

Anything on the board is readable by every device that can reach the port. Keep it on loopback or a Tailscale tailnet. Do not bind `0.0.0.0`. Do not put secrets, tokens, or private mail in tiles. Embed hosts must be allowlisted. Details: [docs/security.md](docs/security.md).

## Docs

- [API reference](docs/api.md)
- [Widget reference](docs/widgets.md)
- [Theme guide](docs/themes.md)
- [Ubuntu kiosk install](docs/install-ubuntu.md)
- [Security](docs/security.md)
- [Contributing](CONTRIBUTING.md)

## Tests

```bash
python3 -m unittest discover -s tests -v
bash scripts/run_overflow.sh
```

Overflow checks need Google Chrome or Chromium. Screenshots land in `shots/`.

## License

MIT. Instrument Sans and Instrument Serif ship under the SIL Open Font License in `web/fonts/`.
