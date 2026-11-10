#!/usr/bin/env bash
# Scaffold a tile folder that passes `python3 tiles.py check`.
# usage: scripts/new_tile.sh <id> [--community]
#   <id>          2 to 32 characters of a-z, 0-9, and _, starting with a letter
#   --community   create it under tiles/community/ (off until enabled in config.json)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${PYTHON:-python3}"
if [[ $# -lt 1 || "$1" == -* ]]; then
  echo "usage: scripts/new_tile.sh <id> [--community]" >&2
  exit 2
fi
cd "$ROOT"
"$PYTHON" "$ROOT/tiles.py" new "$@"
id="$1"
if [[ "${2:-}" == "--community" ]]; then
  where="tiles/community/$id"
  echo "Turn it on with \"enabled_community_tiles\": [\"$id\"] in config.json, then restart serve.py."
else
  where="tiles/$id"
fi
echo "Next: edit $where/tile.json and $where/render.js, restart serve.py, and open /?tilepreview=$id"
