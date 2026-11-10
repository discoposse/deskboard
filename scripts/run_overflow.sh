#!/usr/bin/env bash
# Headless overflow + screenshot pass across fixtures, themes, and sizes.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
SHOTS="${SHOTS:-$ROOT/shots}"
mkdir -p "$SHOTS"
SIZES="${SIZES:-1920x1080 1280x720 1024x600 2560x1440 1080x1920}"
FIXTURES="${FIXTURES:-demo world dense noclock}"
THEMES="${THEMES:-warm-dark tiling nord}"
NODE="${NODE:-node}"
PYTHON="${PYTHON:-python3}"
CDP="$ROOT/scripts/cdp.mjs"
fail=0
pass=0
report="$SHOTS/overflow-report.txt"
: > "$report"

cleanup() {
  if [[ -n "${SERVER_PID:-}" ]]; then
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
  fi
  if [[ -n "${WORKDIR:-}" && -d "$WORKDIR" ]]; then
    rm -rf "$WORKDIR"
  fi
}
trap cleanup EXIT

WORKDIR="$(mktemp -d "${TMPDIR:-/tmp}/deskboard-overflow.XXXXXX")"
export DESKBOARD_CONFIG="$WORKDIR/config.json"
export DESKBOARD_WIDGETS="$WORKDIR/widgets.json"
# Keep the real machine name out of screenshots.
export DESKBOARD_HOSTNAME="${DESKBOARD_HOSTNAME:-deskboard}"
cp "$ROOT/config.example.json" "$DESKBOARD_CONFIG"
# Force a free high port via config.
"$PYTHON" - <<'PY' "$DESKBOARD_CONFIG"
import json, sys
path = sys.argv[1]
data = json.load(open(path))
data["port"] = 18730
data["bind_tailscale"] = False
data["extra_bind"] = []
json.dump(data, open(path, "w"), indent=2)
PY

"$PYTHON" "$ROOT/serve.py" >"$WORKDIR/server.log" 2>&1 &
SERVER_PID=$!

for i in $(seq 1 50); do
  if curl -sf "http://127.0.0.1:18730/api/status" >/dev/null; then
    break
  fi
  sleep 0.1
done
curl -sf "http://127.0.0.1:18730/api/status" >/dev/null

for fx in $FIXTURES; do
  curl -sf "http://127.0.0.1:18730/api/widgets/import" \
    -X PUT -H 'Content-Type: application/json' \
    --data-binary @"$ROOT/tests/fixtures/$fx.json" >/dev/null
  for theme in $THEMES; do
    curl -sf "http://127.0.0.1:18730/api/config" \
      -X PATCH -H 'Content-Type: application/json' \
      -d "{\"theme\":\"$theme\"}" >/dev/null
    for size in $SIZES; do
      w=${size%x*}
      h=${size#*x}
      shot="$SHOTS/board-$fx-$theme-$size.png"
      # Only keep a few curated README shots permanently; others are local artifacts.
      if [[ "$fx" == "demo" && "$theme" == "warm-dark" && "$size" == "1920x1080" ]]; then
        shot="$SHOTS/board-demo-1920x1080.png"
      elif [[ "$fx" == "world" && "$theme" == "tiling" && "$size" == "1920x1080" ]]; then
        shot="$SHOTS/board-theme-tiling-1920x1080.png"
      elif [[ "$fx" == "world" && "$theme" == "nord" && "$size" == "1920x1080" ]]; then
        shot="$SHOTS/board-theme-nord-1920x1080.png"
      fi
      raw="$("$NODE" "$CDP" "http://127.0.0.1:18730/?check" "$w" "$h" "$shot" 2800 'document.documentElement.getAttribute("data-overflow")' || true)"
      line="$(printf '%s\n' "$raw" | "$PYTHON" -c '
import json, sys
w, h = int(sys.argv[1]), int(sys.argv[2])
raw = sys.stdin.read().strip()
try:
    r = json.loads(raw)
    ok = bool(r.get("ok")) and r.get("viewport") == [w, h] and int(r.get("badCount", 99)) == 0
    print(("PASS" if ok else "FAIL"), "tiles=%s bad=%s ellipsized=%s" % (r.get("tiles"), r.get("badCount"), r.get("ellipsized")))
except Exception as e:
    print("FAIL no report", e, raw[:200])
' "$w" "$h")"
      printf '%-8s %-12s %-10s %s\n' "$fx" "$theme" "$size" "$line" | tee -a "$report"
      case "$line" in
        PASS*) pass=$((pass + 1)) ;;
        *) fail=$((fail + 1)); echo "  $raw" | head -c 1200; echo ;;
      esac
    done
  done
done

echo "overall: pass=$pass fail=$fail" | tee -a "$report"
if [[ "$fail" -ne 0 ]]; then
  exit 1
fi
