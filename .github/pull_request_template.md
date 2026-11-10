## What this changes

<!-- One or two sentences. -->

## Checks

- [ ] `python3 -m unittest discover -s tests -v`
- [ ] `python3 tiles.py check`
- [ ] `bash scripts/run_overflow.sh`
- [ ] No secrets, tokens, private mail, or personal names in code, examples, or screenshots

## New or changed tile

Skip this part if the pull request does not touch `tiles/`.

- [ ] Only files inside the tile's own folder changed
- [ ] Community tiles live under `tiles/community/<id>/` and stay off by default
- [ ] `render.js` escapes every value and makes no network, storage, timer, or DOM calls
- [ ] `tile.css` is scoped to `.tile-<id>` and uses theme variables for color
- [ ] `README.md` has a sample payload
- [ ] Screenshot of `/?tilepreview=<id>` in one dark and one light theme
