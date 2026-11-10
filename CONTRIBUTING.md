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
bash scripts/run_overflow.sh
```

Overflow checks need a Chromium-based browser. On macOS the script looks for Google Chrome in `/Applications`.

## Style

- Keep the server on the Python standard library.
- Keep the frontend as plain DOM. No bundler, no CDN at runtime.
- Reject unknown JSON fields. Cap widgets. Never bind `0.0.0.0` by default.
- Do not put secrets, tokens, or private mail in widget content. The board is readable by every device that can reach it.
- Prefer small, focused pull requests with a short note on what you checked.

## Themes and images

Theme presets live under `web/themes/`. Preset images should be original SVG or generated art you own. Do not copy wallpaper packs with unclear licenses.
