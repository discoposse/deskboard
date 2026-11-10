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
3. Restart `serve.py`, open `http://127.0.0.1:8730/?tilepreview=my_tile`, then run the checks in [CONTRIBUTING.md](../CONTRIBUTING.md).

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

Folders under `tiles/community/` are off by default. To turn one on, list its id in `config.json` and restart the server.

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

`GET /api/tiles` returns the catalog.

```json
{"tiles": [{"id": "metric", "name": "Metric", "source": "core", "enabled": true, "col_span": 1, "row_span": 1, "fit": "metric", "fields": {}, "example": {}, "has_css": true}]}
```

Catalog tiles use the same widget routes as built-in ones (`POST /api/widgets`, `PATCH /api/widgets/{id}`, `PUT /api/widgets/import`), and they count toward `max_widgets`. The board loads `/tiles/<id>/render.js` and `/tiles/<id>/tile.css` for enabled tiles only. Nothing else in a tile folder is served.
