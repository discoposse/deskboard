# Contributing

Thanks for helping with Deskboard.

## Local setup

```bash
python3 serve.py
```

Open `http://127.0.0.1:8730` for the board and `http://127.0.0.1:8730/?config` for the configurator. No build step. No package manager for the page itself.

## Checks to run

```bash
python3 -m unittest discover -s tests -v
python3 tiles.py check
bash scripts/run_overflow.sh
```

Overflow checks need a Chromium-based browser. On macOS the script looks for Google Chrome in `/Applications`.

## Style

- Keep the server on the Python standard library.
- Keep the frontend as plain DOM. No bundler, no CDN at runtime.
- Reject unknown JSON fields. Cap widgets. Never bind `0.0.0.0` by default.
- Do not put secrets, tokens, or private mail in widget content. The board is readable by every device that can reach it.
- Prefer small, focused pull requests with a short note on what you checked.

## Adding a tile

New tile types go in their own folder. The full guide is [docs/tiles.md](docs/tiles.md).

```bash
scripts/new_tile.sh my_tile --community
```

Contributed tiles go under `tiles/community/` and stay off until someone lists them in `enabled_community_tiles`. A tile pull request should touch only its own folder.

### Reloading

Run `scripts/reload.sh` after you add or edit a tile folder. The running server rescans `tiles/`, prints what loaded and what was skipped with the reason, and the board fetches the new tile code within 5 seconds. The **Reload tiles** button in the configurator does the same. Restart the server after a change to any Python file. [docs/tiles.md](docs/tiles.md#reloading) has the restart commands.

Tile checklist

- [ ] The folder name matches `id` in `tile.json`, and the id is not a built-in type
- [ ] `python3 tiles.py check` passes, and `scripts/reload.sh` loads the tile on a running server
- [ ] `render.js` escapes every value with `h.escape` and makes no network, storage, timer, or DOM calls
- [ ] `tile.css` scopes every selector to `.tile-<id>` and takes colors from theme variables
- [ ] `README.md` explains the tile and has a sample `curl` payload that works
- [ ] `/?tilepreview=<id>` looks right in at least warm-dark, Tiling, Nord, and Paper
- [ ] `bash scripts/run_overflow.sh` passes with no tile errors
- [ ] No secrets, tokens, private names, or personal data in the example values
- [ ] Fonts, images, and text are yours to share under the MIT license

## Themes and images

Theme presets live under `web/themes/`. Preset images should be original SVG or generated art you own. Do not copy wallpaper packs with unclear licenses.
