#!/usr/bin/env bash
# Post one flash message to a running board.
# usage: scripts/flash.sh <source> <title> <body> [level] [duration]
#        DESKBOARD_URL=http://127.0.0.1:8730 scripts/flash.sh Calendar "Leave in 10 minutes" "Downtown review starts soon." warning 30
# level is info, warning, or urgent. duration is seconds. The server clamps it to 5..120 and defaults to 30.
# Exit codes: 0 posted, 1 the server refused the flash, 2 the server could not be reached.
set -uo pipefail
if [ "$#" -lt 3 ] || [ "$#" -gt 5 ]; then
  echo "usage: scripts/flash.sh <source> <title> <body> [level] [duration]" >&2
  exit 1
fi
URL="${DESKBOARD_URL:-http://127.0.0.1:8730}"
PYTHON="${PYTHON:-python3}"
body="$("$PYTHON" -c 'import json, sys
payload = {"source": sys.argv[1], "title": sys.argv[2], "body": sys.argv[3]}
if len(sys.argv) > 4 and sys.argv[4]:
    payload["level"] = sys.argv[4]
if len(sys.argv) > 5 and sys.argv[5]:
    payload["duration"] = int(sys.argv[5])
print(json.dumps(payload))' "$1" "$2" "$3" "${4:-}" "${5:-}")" || exit 1
out="$(curl -sS --max-time 15 -w '\n%{http_code}' -X POST -H 'Content-Type: application/json' -d "$body" "${URL%/}/api/flash")" || {
  echo "flash: could not reach ${URL%/}. Is serve.py running?" >&2
  exit 2
}
code="${out##*$'\n'}"
reply="${out%$'\n'*}"
if [ "$code" = "200" ]; then
  printf '%s' "$reply" | "$PYTHON" -c 'import json, sys
item = json.load(sys.stdin)
word = "already showing" if item.get("deduped") else "posted"
print(word + " " + item["title"] + " " + str(item["duration"]) + "s")'
  exit $?
fi
msg="$(printf '%s' "$reply" | "$PYTHON" -c 'import json, sys
try:
    print(json.load(sys.stdin).get("error", ""))
except ValueError:
    print("")' 2>/dev/null)"
echo "flash: HTTP ${code} ${msg:-no details}" >&2
exit 1
