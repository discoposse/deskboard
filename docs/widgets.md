# Widget reference

Widget cap defaults to 16 and is configurable as `max_widgets`. Singletons: one `clock`, one `stats`, one `worldclocks`.

| Type | Role |
|---|---|
| `clock` | Large desk clock. `style`: `digital` or `analog`. `show_seconds`, `show_date`. |
| `worldclocks` | City row. `cities`: `[{label, zone}]` with IANA zones. `style`: `analog`, `digital`, or `both`. `mark_markets` lights common market hours. |
| `stats` | Footer sensors. `fields`: subset of `temp`, `load`, `free`, `up`. |
| `note` | Short prose. `title` optional, `text` required (up to 280 chars). |
| `markdown` | Longer note with a small safe markdown subset. `text` up to 1200 chars. |
| `metric` | One number. `label`, `value`, optional `hint` and `trend`. |
| `list` | 1 to 8 short lines. |
| `weather` | Open-Meteo. `latitude`, `longitude`, optional `label`, `units` `metric` or `imperial`. |
| `countdown` | Time to an ISO `target`. Optional `title` and `label`. |
| `calendar` | ICS feed URL. `limit` 1 to 12. |
| `github` | Public repos as `owner/name` list. Stars, day/week change, sparkline. |
| `embed` | Iframe of an allowlisted HTTPS URL. `refresh_sec` 30 to 86400. Many sites block framing; the tile shows a fallback card. |
| `rss` | Feed URL. Headline list. |
| `image` | `src` under `/themes/...`, `/media/...`, or https. `fit`: `cover` or `contain`. |
| `timer` | `minutes` 1 to 180. `mode`: `pomodoro` or `countdown`. |
| `status` | `targets`: `[{label, url}]` pinged server-side. |
| `theme_card` | Preset image from the active theme. `image` id, optional `caption`. |

Spans: set `col_span` and `row_span` to `1` or `2` so a tile covers more grid cells.

## Examples

```bash
curl -s http://127.0.0.1:8730/api/widgets \
  -H 'Content-Type: application/json' \
  -d '{"type":"note","title":"Focus","text":"Ship the install docs."}'
```

```bash
curl -s http://127.0.0.1:8730/api/widgets \
  -H 'Content-Type: application/json' \
  -d '{"type":"worldclocks","cities":[{"label":"New York","zone":"America/New_York"},{"label":"London","zone":"Europe/London"}],"style":"analog","mark_markets":true,"col_span":2}'
```

Load a full layout:

```bash
curl -s http://127.0.0.1:8730/api/widgets/import \
  -X PUT -H 'Content-Type: application/json' \
  --data-binary @examples/demo-board.json
```
