#!/usr/bin/env bash
# Build UxPlay for Linux or macOS and install it to ~/.local.
# Windows uses Build UxPlay.bat instead.
set -euo pipefail

if [[ "$(uname -s)" == "Darwin" ]]; then
  if ! command -v brew >/dev/null 2>&1; then
    echo "Install Homebrew from https://brew.sh/ and run this again." >&2
    exit 1
  fi
  brew install cmake pkg-config openssl libplist gstreamer gst-plugins-base gst-plugins-good gst-plugins-bad gst-libav
elif command -v apt-get >/dev/null 2>&1; then
  sudo apt-get update
  sudo apt-get install -y git build-essential cmake pkg-config \
    libssl-dev libplist-dev libavahi-compat-libdnssd-dev \
    libgstreamer1.0-dev libgstreamer-plugins-base1.0-dev \
    gstreamer1.0-plugins-base gstreamer1.0-plugins-good \
    gstreamer1.0-plugins-bad gstreamer1.0-libav \
    gstreamer1.0-tools
else
  echo "Install git, cmake, pkg-config, OpenSSL, libplist, Avahi/dns_sd, and GStreamer (base, good, bad, libav), then run:" >&2
  echo "  SKIP_DEPS=1 bash build_uxplay_unix.sh" >&2
  if [[ "${SKIP_DEPS:-}" != "1" ]]; then
    exit 1
  fi
fi

SRC="${HOME}/.cache/phoneagent/UxPlay"
mkdir -p "$(dirname "$SRC")"
if [[ -d "$SRC/.git" ]]; then
  git -C "$SRC" pull --ff-only
else
  git clone https://github.com/FDH2/UxPlay "$SRC"
fi

cmake -S "$SRC" -B "$SRC/build" -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="${HOME}/.local"
cmake --build "$SRC/build"
cmake --install "$SRC/build"

echo
echo "Installed: ${HOME}/.local/bin/uxplay"
echo "If that directory is not on PATH, add this to your shell profile:"
echo "  export PATH=\"\$HOME/.local/bin:\$PATH\""
