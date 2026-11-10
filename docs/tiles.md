# Tile catalog

Every tile type outside the built-in set lives in its own folder under `tiles/`. Adding a folder adds a tile type. You do not edit `serve.py`, `widgets.py`, or `web/app.js`.

`tiles/metric/` is the reference tile. It is the board's metric widget, moved into the catalog with the same API and the same look.

## Layout

```text
tiles/
  metric/                 core tile, always on
    tile.json
    render.js
    tile.css              optional
    README.md
  community/
    quote/                contributed tile, off until enabled
      tile.json
      render.js
      tile.css
      README.md
```

The server reads every folder once at startup. A folder that fails validation is skipped and the reason is printed to the server log, so one broken tile never takes the board down. Run `python3 tiles.py check` to see the same report without starting the server.

## Add a tile in three steps

1. Scaffold it with `scripts/new_tile.sh my_tile` (add `--community` for a contributed tile). The stub passes validation as is.
2. Edit `tile.json` for the fields and `render.js` for the markup. Keep `README.md` current with a sample payload.
3. Run `scripts/reload.sh`, open `http://127.0.0.1:8730/?tilepreview=my_tile`, then run the checks in [CONTRIBUTING.md](../CONTRIBUTING.md).

## Reloading

A running server picks up new and changed tile folders without a restart. Pick one of these.

- Run `scripts/reload.sh` on the machine that runs the server.
- Click **Reload tiles** in the configurator at `/?config`.
- Send `POST /api/reload` with an empty JSON body.

```bash
scripts/reload.sh
DESKBOARD_URL=http://127.0.0.1:8731 scripts/reload.sh   # a server on another port
```

The script prints each tile it loaded, each community tile that is off, and each folder it skipped with the reason. It exits 0 when every folder loaded, 1 when a folder was skipped, and 2 when it could not reach the server.

```text
tiles version 3
loaded   metric (core)
loaded   my_tile (core)
off      quote (list it in enabled_community_tiles to turn it on)
skipped  tiles/broken: missing render.js
```

A reload rescans `tiles/` and `tiles/community/`, rereads `enabled_community_tiles` from `config.json`, and runs the same checks as startup. Every reload bumps the catalog version. The board sees the new version on its next poll (within 5 seconds), drops its tile code, and fetches `render.js` and `tile.css` again with `?v=<version>` in the URL, so the browser cache never serves an old copy. Open preview pages need a page reload.

A folder that fails its checks is skipped and the other tiles keep working. If a tile that was already loaded fails after an edit, the server keeps serving the last version that passed and lists the tile under `skipped` until you fix it. The server serves the copy of `render.js` and `tile.css` it checked, so a bad edit on disk never reaches the board.

Deleting a tile folder and reloading removes the tile type. Widgets of that type are left out of the board and dropped from `widgets.json` the next time the layout is saved.

### When to restart instead

Reload covers tile folders and `enabled_community_tiles`. Restart the service after you change any server Python file (`serve.py`, `widgets.py`, `tiles.py`, `deskboard_config.py`, `fetches.py`) or a config key the server reads only at startup, such as the port or bind addresses.

On Ubuntu with the units in `systemd/`

```bash
sudo systemctl restart deskboard          # server Python or startup config
sudo systemctl restart deskboard-kiosk    # kiosk.py or a stuck kiosk browser
journalctl -u deskboard -n 50             # startup log, including tile problems
```

On macOS with a LaunchAgent (use the label from your own plist)

```bash
launchctl kickstart -k gui/$(id -u)/com.example.deskboard
```

Changes to `web/app.js`, `web/style.css`, or a theme need a reload of the board page only. The kiosk service restart above does that on a desk kiosk.

## tile.json

```json
{
  "id": "metric",
  "name": "Metric",
  "description": "One big value with a label, an optional trend, and a hint.",
  "col_span": 1,
  "row_span": 1,
  "fit": "metric",
  "fields": {
    "label": { "type": "line", "label": "Label", "required": true, "max": 24 },
    "value": { "type": "line", "label": "Value", "required": true, "max": 24 },
    "hint": { "type": "line", "label": "Hint", "max": 48, "default": "" },
    "trend": { "type": "line", "label": "Trend", "max": 24, "default": "" }
  },
  "example": { "label": "Focus", "value": "3", "hint": "open", "trend": "+1" }
}
```

| Key | Rules |
| --- | --- |
| `id` | Same as the folder name. 2 to 32 characters of `a-z`, `0-9`, and `_`, starting with a letter. Built-in widget types and ids already in the catalog are refused. |
| `name` | Shown in the configurator gallery. Up to 32 characters. |
| `description` | One line, up to 160 characters. |
| `col_span`, `row_span` | Default size for new tiles, `1` or `2`. Both default to `1`. |
| `fit` | How the board shrinks text to fit. `metric` shrinks `.metric-value`, `text` shrinks the `.fit-text` element, `none` leaves sizes alone. |
| `fields` | 1 to 12 fields. The API accepts these names plus the common widget fields and rejects anything else. |
| `example` | Values used by the configurator for a new tile and by the preview page. It must pass the field rules. |

Field types and their keys.

| Type | Value | Keys |
| --- | --- | --- |
| `line` | One line of text | `required`, `max` (default 80), `default` |
| `text` | Text with line breaks | `required`, `max` (default 280), `max_lines` (default 4), `default` |
| `lines` | A list of one-line strings | `required`, `max` per line (default 80), `max_items` (default 8), `default` |
| `integer` | A whole number | `min`, `max`, `default` (all three needed) |
| `boolean` | `true` or `false` | `default` |
| `choice` | One of a fixed set | `options` (short lowercase names), `default` |

Every field can also carry a `label` for the configurator form. A required field cannot have a default. On create, a missing optional field takes its default. On `PATCH`, missing fields keep their stored value. Text fields reject control characters, and the configurator warns about anything that looks like a token, key, or email address.

## render.js

```js
DeskboardTiles.register("metric", {
  render(data, h) {
    let out = '<p class="metric-label">' + h.escape(data.label) + "</p>";
    out += '<p class="metric-value">' + h.escape(data.value) + "</p>";
    return out;
  },
});
```

`render(data, h)` gets a frozen copy of the tile's fields plus `col_span` and `row_span`, and returns a string of markup. `h.escape(value)` turns any value into safe text. The board wraps the result in `<section class="tile tile-<id>"><div class="tile-body">`.

Rules the board enforces.

- Markup is rebuilt from a short list of tags (`div p span strong em b i small ul ol li br blockquote figure figcaption`). Every attribute except `class` is dropped. Scripts, images, links, iframes, and inline styles are removed with their content.
- `tiles.py check` rejects render code that names network, storage, DOM, timer, or dynamic code globals, such as `fetch`, `XMLHttpRequest`, `WebSocket`, `document`, `window`, `localStorage`, `setTimeout`, `eval`, `import`, or `innerHTML`.
- The page is served with `Content-Security-Policy: connect-src 'self'`, so page scripts can only reach this server.
- If `render` throws, the tile shows a short error line and the overflow check fails.

Escape every value, even with the sanitizer behind you. Plain text is the default and there is no switch for raw HTML.

## tile.css

Optional. Every selector must start with `.tile-<id>`, optionally after `.board` or `.tile` (for example `.board .tile-quote .quote-text`). Colors come from theme variables such as `var(--ink)`, `var(--muted)`, `var(--faint)`, `var(--accent)`, `var(--ok)`, and `var(--bad)`, so the tile follows every theme. Hex colors, color functions, `url()`, and `@import` are rejected. `@media` blocks are allowed.

Size inner text in `em` when the tile uses `"fit": "text"`, so it scales with the fitted element.

## Community tiles

Folders under `tiles/community/` are off by default. To turn one on, list its id in `config.json` and run `scripts/reload.sh`.

```json
{
  "enabled_community_tiles": ["quote"]
}
```

This key is read from the file only. `PATCH /api/config` refuses it, because a community tile runs code in the board page and turning one on should take a change on the machine itself. `GET /api/tiles` lists community tiles with `"enabled": false` until then. Tiles of a type that is switched off are left out of the board and dropped from `widgets.json` the next time the layout is saved.

## Preview page

`/?tilepreview=<id>` draws the tile at 2×2, 1×2, 1×1, and 2×1 on a 4 by 3 board using the `example` values. Pick a theme from the menu at the top right or add `&theme=<id>` to the URL. Add `&check` to get the overflow report that `scripts/run_overflow.sh` reads.

`scripts/run_overflow.sh` turns on every community tile, runs `tiles.py check`, then loads each tile's preview in every checked theme and screen size. A tile passes when all four copies render with nothing outside its box.

## API

`GET /api/tiles` returns the catalog and its version.

```json
{"version": 1, "tiles": [{"id": "metric", "name": "Metric", "source": "core", "enabled": true, "col_span": 1, "row_span": 1, "fit": "metric", "fields": {}, "example": {}, "has_css": true}]}
```

Catalog tiles use the same widget routes as built-in ones (`POST /api/widgets`, `PATCH /api/widgets/{id}`, `PUT /api/widgets/import`), and they count toward `max_widgets`. The board loads `/tiles/<id>/render.js` and `/tiles/<id>/tile.css` for enabled tiles only. Nothing else in a tile folder is served.

`POST /api/reload` takes `{}` and returns the reload summary. `ok` is false when any folder was skipped. `GET /api/status` includes `tiles_version`.

```json
{"ok": false, "version": 3, "loaded": [{"id": "metric", "source": "core"}], "disabled": ["quote"], "skipped": ["tiles/broken: missing render.js"]}
```
