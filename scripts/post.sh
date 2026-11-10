#!/usr/bin/env bash
# Post one line to a list tile on a running board.
# usage: scripts/post.sh <widget-id> <source> <text>
#        DESKBOARD_URL=http://<your-board-url>:8730 scripts/post.sh botstatus Backup "Nightly backup finished"
# The server adds the time, keeps the newest lines, and never creates a tile.
# Exit codes: 0 posted, 1 the server refused the post, 2 the server could not be reached.
set -uo pipefail
if [ "$#" -ne 3 ]; then
  echo "usage: scripts/post.sh <widget-id> <source> <text>" >&2
  exit 1
fi
URL="${DESKBOARD_URL:-http://127.0.0.1:8730}"
PYTHON="${PYTHON:-python3}"
widget="$1"
body="$("$PYTHON" -c 'import json, sys; print(json.dumps({"source": sys.argv[1], "text": sys.argv[2]}))' "$2" "$3")" || exit 1
out="$(curl -sS --max-time 15 -w '\n%{http_code}' -X POST -H 'Content-Type: application/json' -d "$body" "${URL%/}/api/widgets/${widget}/post")" || {
  echo "post: could not reach ${URL%/}. Is serve.py running?" >&2
  exit 2
}
code="${out##*$'\n'}"
reply="${out%$'\n'*}"
if [ "$code" = "200" ]; then
  printf '%s' "$reply" | "$PYTHON" -c 'import json, sys; print("posted: " + json.load(sys.stdin)["items"][0])'
  exit 0
fi
msg="$(printf '%s' "$reply" | "$PYTHON" -c 'import json, sys
try:
    print(json.load(sys.stdin).get("error", ""))
except ValueError:
    print("")' 2>/dev/null)"
echo "post: HTTP ${code} ${msg:-no details}" >&2
exit 1
