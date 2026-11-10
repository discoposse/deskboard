#!/usr/bin/env bash
# Rescan tiles/ on a running server so new or changed tiles load without a restart.
# usage: scripts/reload.sh            (DESKBOARD_URL defaults to http://127.0.0.1:8730)
#        DESKBOARD_URL=http://100.x.y.z:8730 scripts/reload.sh
# Exit codes: 0 every tile loaded, 1 a tile folder was skipped, 2 the server could not be reached.
set -uo pipefail
URL="${DESKBOARD_URL:-http://127.0.0.1:8730}"
PYTHON="${PYTHON:-python3}"
body="$(curl -sS --max-time 20 -X POST -H 'Content-Type: application/json' -d '{}' "${URL%/}/api/reload")" || {
  echo "reload: could not reach ${URL%/}/api/reload. Is serve.py running?" >&2
  exit 2
}
printf '%s' "$body" | "$PYTHON" -c '
import json, sys
try:
    r = json.load(sys.stdin)
except ValueError:
    print("reload: the server did not return JSON", file=sys.stderr)
    sys.exit(2)
if "error" in r:
    print("reload: " + r["error"], file=sys.stderr)
    sys.exit(2)
print("tiles version %s" % r["version"])
for t in r["loaded"]:
    print("loaded   %s (%s)" % (t["id"], t["source"]))
for tile_id in r["disabled"]:
    print("off      %s (list it in enabled_community_tiles to turn it on)" % tile_id)
for problem in r["skipped"]:
    print("skipped  %s" % problem)
sys.exit(0 if r["ok"] else 1)
'
