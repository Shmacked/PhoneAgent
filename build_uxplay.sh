#!/usr/bin/env bash
# Builds and installs UxPlay (AirPlay receiver) inside MSYS2 UCRT64.
# UxPlay is a separate project: https://github.com/FDH2/UxPlay
set -euo pipefail

echo "== Installing build tools and GStreamer =="
pacman -S --needed --noconfirm git \
  mingw-w64-ucrt-x86_64-gcc mingw-w64-ucrt-x86_64-cmake \
  mingw-w64-ucrt-x86_64-ninja mingw-w64-ucrt-x86_64-pkgconf \
  mingw-w64-ucrt-x86_64-libplist \
  mingw-w64-ucrt-x86_64-gstreamer mingw-w64-ucrt-x86_64-gst-plugins-base \
  mingw-w64-ucrt-x86_64-gst-libav mingw-w64-ucrt-x86_64-gst-plugins-good \
  mingw-w64-ucrt-x86_64-gst-plugins-bad

echo "== Getting UxPlay source =="
cd ~
if [ -d UxPlay/.git ]; then git -C UxPlay pull --ff-only; else git clone https://github.com/FDH2/UxPlay; fi

echo "== Building =="
mkdir -p UxPlay/build && cd UxPlay/build
cmake -G Ninja ..
ninja

echo "== Installing to /ucrt64 =="
cmake --install . --prefix /ucrt64

echo
echo "UxPlay installed: $(command -v uxplay)"
