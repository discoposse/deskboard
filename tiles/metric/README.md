# Metric

One big value with a small label above it, an optional trend, and an optional hint. A trend that starts with `+` or contains "up" shows in the theme's ok color. One that starts with `-` or contains "down" shows in the bad color.

This is the reference tile for the catalog. Copy its layout when you build your own.

## Fields

| Field | Type | Notes |
| --- | --- | --- |
| `label` | line | Required, up to 24 characters |
| `value` | line | Required, up to 24 characters |
| `hint` | line | Optional, up to 48 characters |
| `trend` | line | Optional, up to 24 characters, such as `+2` or `-3` |

The value shrinks to fit the tile (`"fit": "metric"`).

## Sample payload

```bash
curl -s http://127.0.0.1:8730/api/widgets \
  -X POST -H 'Content-Type: application/json' \
  -d '{"type":"metric","id":"issues","label":"Open issues","value":"12","hint":"deskboard","trend":"-3"}'
```

Preview it at `http://127.0.0.1:8730/?tilepreview=metric`.
