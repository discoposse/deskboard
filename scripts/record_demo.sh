#!/usr/bin/env bash
# Record the README demo animation (configurator + board) with headless Chrome.
# Needs Node 22+, Google Chrome or Chromium, and ffmpeg.
# Output: docs/media/demo-configurator-board.gif, docs/media/demo-board.gif,
# and docs/media/demo-configurator-board.mp4.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
OUT="${OUT:-$ROOT/docs/media}"
NODE="${NODE:-node}"
PYTHON="${PYTHON:-python3}"
FPS="${FPS:-10}"
PORT=18731
mkdir -p "$OUT"

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

WORKDIR="$(mktemp -d "${TMPDIR:-/tmp}/deskboard-demo.XXXXXX")"
export DESKBOARD_CONFIG="$WORKDIR/config.json"
export DESKBOARD_WIDGETS="$WORKDIR/widgets.json"
# Keep the real machine name out of the recording.
export DESKBOARD_HOSTNAME="${DESKBOARD_HOSTNAME:-deskboard}"
cp "$ROOT/config.example.json" "$DESKBOARD_CONFIG"
"$PYTHON" - <<'PY' "$DESKBOARD_CONFIG" "$PORT"
import json, sys
path, port = sys.argv[1], int(sys.argv[2])
data = json.load(open(path))
data["port"] = port
data["bind_tailscale"] = False
data["extra_bind"] = []
json.dump(data, open(path, "w"), indent=2)
PY

"$PYTHON" "$ROOT/serve.py" >"$WORKDIR/server.log" 2>&1 &
SERVER_PID=$!
BASE="http://127.0.0.1:$PORT"
for _ in $(seq 1 50); do
  curl -sf "$BASE/api/status" >/dev/null && break
  sleep 0.1
done
curl -sf "$BASE/api/widgets/import" -X PUT -H 'Content-Type: application/json' \
  --data-binary @"$ROOT/examples/demo-board.json" >/dev/null
curl -sf "$BASE/api/config" -X PATCH -H 'Content-Type: application/json' \
  -d '{"theme":"warm-dark"}' >/dev/null

FRAMES="$WORKDIR/frames"
"$NODE" "$ROOT/scripts/record_demo.mjs" "$BASE" "$FRAMES"

# Side by side: configurator (1280x800) left, board (1280x720 padded to 800) right.
ffmpeg -loglevel error -y -framerate "$FPS" -i "$FRAMES/cfg_%05d.jpg" -framerate "$FPS" -i "$FRAMES/board_%05d.jpg" \
  -filter_complex "[1:v]pad=1280:800:0:40:color=0x111111[b];[0:v][b]hstack=inputs=2,scale=1600:-2:flags=lanczos[v]" \
  -map "[v]" -map_metadata -1 -c:v libx264 -pix_fmt yuv420p -crf 26 -movflags +faststart -an "$OUT/demo-configurator-board.mp4"

gif() {
  local filter="$1" out="$2" colors="$3"
  ffmpeg -loglevel error -y -framerate "$FPS" -i "$FRAMES/cfg_%05d.jpg" -framerate "$FPS" -i "$FRAMES/board_%05d.jpg" \
    -filter_complex "$filter,split[s0][s1];[s0]palettegen=max_colors=$colors:stats_mode=diff[p];[s1][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle" \
    -map_metadata -1 -loop 0 "$out"
}
gif "[1:v]pad=1280:800:0:40:color=0x111111[b];[0:v][b]hstack=inputs=2,scale=1600:-2:flags=lanczos" "$OUT/demo-configurator-board.gif" 128
gif "[1:v]scale=960:-2:flags=lanczos" "$OUT/demo-board.gif" 128
ls -l "$OUT"
