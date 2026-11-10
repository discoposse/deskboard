# Quote

A short quote in the display font with an optional author line under it. The text shrinks to fit the tile.

This is a community tile, so it is off by default. Turn it on in `config.json` and restart the server.

```json
{
  "enabled_community_tiles": ["quote"]
}
```

## Fields

| Field | Type | Notes |
| --- | --- | --- |
| `quote` | text | Required, up to 200 characters and 4 lines |
| `author` | line | Optional, up to 48 characters |

## Sample payload

```bash
curl -s http://127.0.0.1:8730/api/widgets \
  -X POST -H 'Content-Type: application/json' \
  -d '{"type":"quote","quote":"Make it work, make it right, make it fast.","author":"Kent Beck"}'
```

Preview it at `http://127.0.0.1:8730/?tilepreview=quote` once it is on.
