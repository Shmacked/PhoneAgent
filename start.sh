#!/usr/bin/env bash
# Linux and macOS launcher. Starts UxPlay, the Bluetooth pointer on Linux, then the agent.
# macOS can receive AirPlay. It cannot be the Bluetooth mouse; use Linux or Windows for taps.
set -euo pipefail
cd "$(dirname "$0")"

CALIBRATE=0
if [[ "${1:-}" == "--calibrate" ]]; then
  CALIBRATE=1
fi

if [[ ! -f config.json ]]; then
  echo "config.json is missing." >&2
  exit 1
fi

cfg() {
  python3 - "$1" <<'PY'
import json, sys
value = json.load(open("config.json", encoding="utf-8")).get(sys.argv[1], "")
print(value if isinstance(value, str) else "")
PY
}

AIRPLAY="$(cfg airplay_name)"
SINK="$(cfg videosink)"
if [[ -z "$AIRPLAY" ]]; then
  echo 'Set "airplay_name" in config.json. That is the name in Screen Mirroring.' >&2
  exit 1
fi
if [[ -z "$SINK" ]]; then
  SINK="autovideosink"
fi

if ! command -v uxplay >/dev/null 2>&1; then
  echo "UxPlay is not on PATH. From this folder run: bash build_uxplay_unix.sh" >&2
  exit 1
fi

if pgrep -x uxplay >/dev/null 2>&1; then
  echo "UxPlay is already running. It keeps the name it was started with."
  echo "Close it and run this again to broadcast as '$AIRPLAY'."
else
  echo "Starting AirPlay receiver as '$AIRPLAY'..."
  uxplay -n "$AIRPLAY" -nh -p -vs "$SINK" >"${TMPDIR:-/tmp}/phoneagent-uxplay.log" 2>&1 &
fi
echo "On the iPhone: Control Center > Screen Mirroring > $AIRPLAY"

mouse_status() {
  python3 - <<'PY'
import socket, sys
try:
    sock = socket.create_connection(("127.0.0.1", 7777), 2)
    handle = sock.makefile("rw", encoding="utf-8", newline="\n")
    handle.write("status\n")
    handle.flush()
    print((handle.readline() or "").strip())
except OSError:
    sys.exit(1)
PY
}

OS="$(uname -s)"
if ! mouse_status >/dev/null 2>&1; then
  if [[ "$OS" == "Linux" ]]; then
    echo "Starting the Bluetooth mouse. sudo is required so BlueZ can use the adapter."
    sudo -v
    sudo python3 "$PWD/mouse/bt_mouse.py" >"${TMPDIR:-/tmp}/phoneagent-mouse.log" 2>&1 &
  elif [[ "$OS" == "Darwin" ]]; then
    echo "macOS cannot present this Mac as a Bluetooth mouse." >&2
    echo "Use Linux (bash start.sh) or Windows (Start PhoneAgent.bat) for taps." >&2
    exit 1
  else
    echo "The phone mouse is not running on port 7777." >&2
    exit 1
  fi
fi

echo "Waiting for the phone mouse..."
ST=""
for _ in $(seq 1 60); do
  if ST="$(mouse_status 2>/dev/null)"; then
    break
  fi
  sleep 1
done
if [[ -z "${ST:-}" ]]; then
  echo "Nothing answered on port 7777." >&2
  echo "On Linux install: sudo apt install bluez python3-dbus python3-gi" >&2
  exit 1
fi
echo "Phone mouse: $ST"
if [[ "$ST" != "connected" ]]; then
  echo "On the iPhone: Settings > Bluetooth > Phone Mouse"
  echo "Turn AssistiveTouch on, and turn off Automatically Hide Pointer."
  for _ in $(seq 1 45); do
    ST="$(mouse_status 2>/dev/null || true)"
    if [[ "$ST" == "connected" ]]; then
      break
    fi
    sleep 2
  done
  echo "Phone mouse: ${ST:-down}"
fi

if [[ ! -x .venv/bin/python ]]; then
  echo "Creating .venv and installing Python packages..."
  python3 -m venv .venv
  .venv/bin/python -m pip install -e .
fi

if [[ "$CALIBRATE" == "1" ]]; then
  exec .venv/bin/python -m phone_remote calibrate
fi
exec .venv/bin/python -m phone_remote agent
