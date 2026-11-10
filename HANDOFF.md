# Handoff

Community Deskboard is ready for a later public GitHub publish. Nothing was pushed or created remotely from this work.

## What was built

Self-hosted desk dashboard:

- Python stdlib server (`serve.py`, `widgets.py`, `deskboard_config.py`, `fetches.py`, `wait_ready.py`)
- Cage + WebKitGTK kiosk (`kiosk.py`, `install.sh`, systemd units)
- Plain DOM frontend (`web/`) with tile grid, overflow fitting, and `/?config` configurator
- Themes under `web/themes/` (warm-dark default, Tokyo Night, Catppuccin, Gruvbox, Nord, Rose Pine, Tiling, Paper) with original SVG preset images
- Widgets: clock, world clocks, stats, note, markdown, metric, list, weather, countdown, calendar, GitHub stars, embed, RSS, image, timer, status, theme card
- Docs, MIT license, CONTRIBUTING, CHANGELOG, examples, CI workflow

`reference/` is input-only and gitignored. `BRIEF.md` is also gitignored.

## How to run

```bash
cp config.example.json config.json
python3 serve.py
```

- Board: `http://127.0.0.1:8730`
- Configurator: `http://127.0.0.1:8730/?config`

Ubuntu kiosk: `sudo DESKBOARD_USER="$USER" ./install.sh` (see `docs/install-ubuntu.md`).

## Test results

Unit tests: **14 passed** (`python3 -m unittest discover -s tests -v`).

Overflow / layout checks (`bash scripts/run_overflow.sh`):

- Fixtures: `demo`, `world`, `dense`, `noclock`
- Themes: `warm-dark`, `tiling`, `nord`
- Sizes: `1920x1080`, `1280x720`, `1024x600`, `2560x1440`, `1080x1920`
- **pass=60 fail=0**

## Screenshots

- `shots/board-demo-1920x1080.png`
- `shots/board-theme-tiling-1920x1080.png`
- `shots/board-theme-nord-1920x1080.png`

## Scrub grep

Checked the public tree for the private hostname, old Tailscale name, private username, and the two private IPs named in the build brief. Skipped `reference/` and `BRIEF.md` (both gitignored).

Result: **no hits** outside those ignored inputs.

`tests/test_widgets.py` (`ScrubTests`) asserts the same list on every test run, with the strings split in source so the test file does not store them as contiguous literals.

## Left undone / known gaps

- Embed “site blocks framing” detection is best-effort. Cross-origin frame blockers cannot always be observed; the fallback card covers the obvious cases.
- Dropped image files become `/media/...` stubs. There is no media upload API yet. Place files in `web/media/` by hand.
- Timer countdown is client-side from page load and is not persisted across reloads.
- Optional GitHub API token is env-only (`DESKBOARD_GITHUB_TOKEN`). Without it, public unauthenticated GitHub rate limits apply.
- No remote GitHub repo was created. Publish when you are ready.
