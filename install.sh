#!/bin/bash
# Install the desk kiosk and start it on the connected HDMI display.
# Leaves SSH alone. Takes tty1, which is the local console.
set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run this as root: sudo $0" >&2
  exit 1
fi

SRC="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
cd "$SRC"

DESKBOARD_USER="${DESKBOARD_USER:-${SUDO_USER:-}}"
if [[ -z "$DESKBOARD_USER" || "$DESKBOARD_USER" == "root" ]]; then
  echo "Set DESKBOARD_USER to the non-root account that should own Deskboard," >&2
  echo "or run: sudo -u <user> sudo $0" >&2
  exit 1
fi

if ! id "$DESKBOARD_USER" >/dev/null 2>&1; then
  echo "User $DESKBOARD_USER does not exist." >&2
  exit 1
fi

USER_HOME="$(getent passwd "$DESKBOARD_USER" | cut -d: -f6)"
if [[ -z "$USER_HOME" || ! -d "$USER_HOME" ]]; then
  echo "Could not resolve home directory for $DESKBOARD_USER" >&2
  exit 1
fi

# Prefer an existing checkout under the user's home, then /opt/deskboard,
# otherwise install into ~/deskboard.
if [[ "$SRC" == "$USER_HOME/deskboard" || "$SRC" == "$USER_HOME/deskboard/"* ]]; then
  DEST="$SRC"
elif [[ -f "$USER_HOME/deskboard/serve.py" ]]; then
  DEST="$USER_HOME/deskboard"
elif [[ "$SRC" == /opt/deskboard || "$SRC" == /opt/deskboard/* ]]; then
  DEST="/opt/deskboard"
elif [[ -f /opt/deskboard/serve.py ]]; then
  DEST="/opt/deskboard"
else
  DEST="$USER_HOME/deskboard"
fi

if [[ "$SRC" != "$DEST" ]]; then
  mkdir -p "$DEST"
  rsync -a --delete \
    --exclude '.git' \
    --exclude 'reference' \
    --exclude '__pycache__' \
    --exclude '*.pyc' \
    --exclude 'config.json' \
    --exclude 'widgets.json' \
    "$SRC"/ "$DEST"/
  chown -R "$DESKBOARD_USER:$DESKBOARD_USER" "$DEST"
fi

if [[ ! -f "$DEST/config.json" && -f "$DEST/config.example.json" ]]; then
  install -o "$DESKBOARD_USER" -g "$DESKBOARD_USER" -m 0644 \
    "$DEST/config.example.json" "$DEST/config.json"
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y \
  -o Dpkg::Options::=--force-confdef \
  -o Dpkg::Options::=--force-confold \
  cage python3-gi gir1.2-gtk-3.0 gir1.2-webkit2-4.1 rsync

usermod -aG video,render,input "$DESKBOARD_USER"

render_unit() {
  local src="$1"
  local dst="$2"
  sed \
    -e "s|__DESKBOARD_USER__|${DESKBOARD_USER}|g" \
    -e "s|__DESKBOARD_HOME__|${DEST}|g" \
    "$src" > "$dst"
  chmod 0644 "$dst"
}

render_unit "$DEST/systemd/deskboard.service" /etc/systemd/system/deskboard.service
render_unit "$DEST/systemd/deskboard-kiosk.service" /etc/systemd/system/deskboard-kiosk.service

mkdir -p /etc/systemd/logind.conf.d
cat > /etc/systemd/logind.conf.d/deskboard.conf << 'EOF'
# The desk display should stay on. Idle does not suspend the machine.
[Login]
IdleAction=ignore
EOF

systemctl daemon-reload
systemctl enable deskboard.service deskboard-kiosk.service
systemctl restart deskboard.service
systemctl restart deskboard-kiosk.service || true

PYTHONPATH="$DEST" python3 - << 'PY'
import time
import urllib.request
from deskboard_config import load_config

url = f"http://127.0.0.1:{load_config()['port']}/api/status"
last = None
for _ in range(40):
    try:
        print(urllib.request.urlopen(url, timeout=1).read().decode())
        break
    except Exception as exc:
        last = exc
        time.sleep(0.25)
else:
    raise SystemExit(f"page not ready: {last}")
PY

ok=0
for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
  if systemctl is-active --quiet deskboard-kiosk.service; then
    ok=1
    break
  fi
  sleep 1
done

echo
if [[ -r /sys/class/drm/card1-HDMI-A-1/status ]]; then
  echo "HDMI-A-1: $(cat /sys/class/drm/card1-HDMI-A-1/status)"
fi

if [[ "$ok" -ne 1 ]]; then
  echo "Kiosk did not stay up. Recent log:" >&2
  journalctl -u deskboard-kiosk -n 80 --no-pager >&2 || true
  exit 1
fi

echo "Deskboard is running on the HDMI display."
api_port=$(PYTHONPATH="$DEST" python3 -c 'from deskboard_config import load_config; print(load_config()["port"])')
tz_line=$(PYTHONPATH="$DEST" python3 -c 'from deskboard_config import public_config; c=public_config(); print(c["timezone_resolved"] + " (" + c["timezone"] + ")")')
echo "Clock timezone:  $tz_line"
if command -v tailscale >/dev/null 2>&1; then
  ts_ip=$(tailscale ip -4 2>/dev/null || true)
  if [[ -n "${ts_ip}" ]]; then
    echo "If bind_tailscale is enabled: http://${ts_ip}:${api_port}/api"
  fi
fi
echo "Install path:     $DEST"
echo "Stop the screen:  sudo systemctl stop deskboard-kiosk"
echo "Start it again:   sudo systemctl start deskboard-kiosk"
echo "Logs:             journalctl -u deskboard-kiosk -u deskboard -f"
