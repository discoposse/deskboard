# Themes

Themes are JSON manifests plus optional images under `web/themes/<id>/`.

`web/themes/index.json` lists shipped ids. The active theme is `config.theme` (default `warm-dark`).

Each `theme.json` holds:

- `id`, `name`, `description`
- `fonts` for ui, display, and mono families (local or system stacks only)
- `variables` mapped to CSS custom properties (`--bg`, `--ink`, `--accent`, and friends)
- `tiling` flag for the tiling-window look (crisper borders, tighter radius, mono display)
- `images` presets for `theme_card` tiles

## Shipped themes

| Id | Feel |
|---|---|
| `warm-dark` | Quiet warm charcoal desk (default) |
| `tokyo-night` | Cool night city |
| `catppuccin` | Soft pastel mocha |
| `gruvbox` | Warm earthy terminal |
| `nord` | Cool arctic |
| `rose-pine` | Muted dusk pink |
| `tiling` | tiling window manager cues |
| `paper` | Light ink on paper |

## Picking a theme

In the configurator open `/?config` and use the theme picker, or:

```bash
curl -s http://127.0.0.1:8730/api/config \
  -X PATCH -H 'Content-Type: application/json' \
  -d '{"theme":"nord"}'
```

## Theme card tiles

Add a `theme_card` widget and set `image` to a preset id from that theme (`default`, or names listed in the manifest). Users can also drop their own files into `web/media/` and point an `image` widget at `/media/your-file.svg`.

## Adding a theme

1. Copy an existing folder under `web/themes/`.
2. Edit `theme.json` variables and fonts.
3. Add original SVG images under `images/`.
4. Append the id to `web/themes/index.json`.
