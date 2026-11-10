# Bots and managed tiles

Scripts, sync jobs, and AI assistants can keep tiles current while you edit the layout in the configurator. Three pieces keep them out of each other's way.

- A tile marked with `managed_by` belongs to a bot. The configurator shows its content as read-only and still lets you move it, resize it, or hide it.
- Every widget write bumps a revision. The configurator sends the revision it loaded, and the server refuses a stale Apply with `409` instead of writing over someone else's change.
- `POST /api/widgets/{id}/post` adds one timestamped line to a list tile. It never creates a tile, so a tile you hid or deleted stays that way.

## Mark a tile as managed

Set `managed_by` to a short lowercase name such as `bots` or `calendar`. Any list tile works.

```bash
curl -sS -X PATCH http://127.0.0.1:8730/api/widgets/botstatus \
  -H 'Content-Type: application/json' \
  -d '{"managed_by": "bots", "max_items": 6}'
```

Send `"managed_by": ""` to hand the tile back to the configurator.

In the configurator a managed tile carries a dashed badge with the owner name. Its editor says who fills it and greys out the content fields. Size, order, and **Show on board** still save. When you click **Apply to board**, the configurator sends `keep_managed: true`, and the server keeps the stored content of every managed tile and takes only its layout from the request. A post that lands while you edit is never lost.

## Revisions and conflicts

`GET /api/widgets` returns `revision` and `layout_revision` in the body and as the `X-Deskboard-Revision` and `X-Deskboard-Layout-Revision` headers. Every write moves `revision`. Every write except a bot changing a managed tile's content also moves `layout_revision`, so bot posts never block your Apply.

To make a write conditional, send the `layout_revision` you loaded as `base_revision` in an import body or as an `If-Match` header on any widget write. If the board moved on, the server answers `409` with `"stale": true` and changes nothing.

```bash
curl -sS -X PATCH http://127.0.0.1:8730/api/widgets/todo \
  -H 'Content-Type: application/json' -H 'If-Match: 42' \
  -d '{"title": "Today"}'
```

Requests without a revision are not checked, so existing scripts keep working.

When the configurator gets a `409`, it keeps your edits and shows a notice with a **Reload from board** button. Reloading loads the new layout and drops your unsaved edits. Click **Export JSON** first if you want a copy.

## Posting from scripts and bots

`POST /api/widgets/{id}/post` with `{"source": "...", "text": "..."}` puts a new line at the top of a list tile.

```bash
curl -sS -X POST http://127.0.0.1:8730/api/widgets/botstatus/post \
  -H 'Content-Type: application/json' \
  -d '{"source": "Backup", "text": "Nightly backup finished"}'
```

The line reads `9:05 PM  Backup  Nightly backup finished`, with two spaces between parts and the time in the board's configured `timezone`. The rules are below.

- The tile keeps its newest `max_items` lines (1 to 8, default 6).
- A line is at most 80 characters. Long text is cut with `…`, and a source longer than 24 characters is cut too.
- Newlines, tabs, and other control characters are refused with `400`.
- A missing or hidden tile returns `404`. The route never creates a tile.
- Only list tiles take posts. Any other type returns `409`.

`scripts/post.sh` wraps the call. It reads `DESKBOARD_URL` and defaults to `http://127.0.0.1:8730`.

```bash
scripts/post.sh botstatus Backup "Nightly backup finished"
DESKBOARD_URL=http://<your-board-url>:8730 scripts/post.sh botstatus Backup "Nightly backup finished"
```

It prints the posted line and exits 0. It exits 1 when the server refuses the post and 2 when it cannot reach the server.

## How to get your bot to update your Deskboard

1. Create a list tile for your bots and mark it managed, for example `botstatus` with `"managed_by": "bots"`.
2. Make sure the machine the bot runs on can reach the board, on loopback or over your tailnet.
3. Give the bot the curl call or `scripts/post.sh`, and paste the prompt below into its instructions.

The call your bot runs

```bash
curl -sS -X POST http://<your-board-url>:8730/api/widgets/botstatus/post \
  -H 'Content-Type: application/json' \
  -d '{"source": "<bot name>", "text": "<one short line>"}'
```

Or, from a checkout of this repo

```bash
DESKBOARD_URL=http://<your-board-url>:8730 scripts/post.sh botstatus "<bot name>" "<one short line>"
```

Prompt for any AI assistant (copy the whole block)

```text
You can post short status lines to my Deskboard, a screen on my desk.

To post, run exactly this command, filling in your name and one line of text:

curl -sS -X POST http://<your-board-url>:8730/api/widgets/botstatus/post \
  -H 'Content-Type: application/json' \
  -d '{"source": "<your name>", "text": "<one short line>"}'

Rules:
- Plain text only. No markdown, no links, no emoji codes, no newlines.
- Never include secrets, passwords, tokens, codes, account numbers, or private mail. Every device on my network can read the board.
- Only post to tiles marked "managed_by": "bots". Today that is botstatus.
- Never create, delete, hide, resize, or reorder tiles. Never call any other Deskboard route that changes something.
- Keep each line under 60 characters. Say what happened and what I need to do, if anything.
- Post when a job finishes, when a job fails, or when something needs me. Do not post routine progress, and do not post the same thing twice.
- If the command returns 404, the tile is hidden or gone. Stop posting and tell me in chat.

Example:
curl -sS -X POST http://<your-board-url>:8730/api/widgets/botstatus/post \
  -H 'Content-Type: application/json' \
  -d '{"source": "Inbox bot", "text": "3 invoices need approval today"}'
```

The example shows up on the board as `4:12 PM  Inbox bot  3 invoices need approval today`.

A Deskboard MCP server is planned, so assistants that speak MCP can post without a shell command. Until it ships, use the curl call above.

## Security

The post route has the same access model as the rest of the API. It answers loopback and the addresses you allow, has no CORS, and needs `Content-Type: application/json`, so web pages on other sites cannot call it. Anyone who can reach the port can post, so keep the board on loopback or your tailnet. See [security.md](security.md).
