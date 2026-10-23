"""Capture the AirPlay mirror window."""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from dataclasses import dataclass

import cv2
import mss
import numpy as np

from .paths import load_config

_WMCTRL_LINE = re.compile(
    r"^(\S+)\s+(\S+)\s+(-?\d+)\s+(-?\d+)\s+(\d+)\s+(\d+)\s+\S+\s+(.*\S)\s*$"
)

if sys.platform == "win32":
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


@dataclass
class Region:
    left: int
    top: int
    width: int
    height: int


class _ListedWindow:
    """One row from wmctrl, with the same fields the Windows window objects expose."""

    def __init__(self, title: str, left: int, top: int, width: int, height: int):
        self.title = title
        self.left = left
        self.top = top
        self.width = width
        self.height = height

    @property
    def isMinimized(self) -> bool:
        return self.left <= -10000 or self.top <= -10000 or self.width <= 0 or self.height <= 0


def parse_wmctrl(text: str) -> list[_ListedWindow]:
    """Parse `wmctrl -lG` output. The title may contain spaces."""
    found = []
    for line in text.splitlines():
        match = _WMCTRL_LINE.match(line.strip())
        if not match:
            continue
        found.append(
            _ListedWindow(
                match.group(7),
                int(match.group(3)),
                int(match.group(4)),
                int(match.group(5)),
                int(match.group(6)),
            )
        )
    return found


def _gw():
    import pygetwindow as gw

    return gw


def _all_windows():
    if sys.platform.startswith("linux"):
        if not shutil.which("wmctrl"):
            raise LookupError("On Linux, install wmctrl so the mirror window can be found: sudo apt install wmctrl")
        try:
            out = subprocess.run(["wmctrl", "-lG"], capture_output=True, text=True, timeout=3, check=False)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise LookupError(f"wmctrl failed: {e}") from e
        return parse_wmctrl(out.stdout)
    return _gw().getAllWindows()


def list_windows() -> list[str]:
    return sorted({w.title.strip() for w in _all_windows() if getattr(w, "title", "").strip()})


def _minimized(w) -> bool:
    return bool(getattr(w, "isMinimized", False)) or w.left <= -10000 or w.top <= -10000


def _matches(title_part: str):
    t = title_part.lower()
    ws = [w for w in _all_windows() if t in w.title.lower() and w.width > 0]
    return sorted(ws, key=lambda w: (w.title.lower() != t, len(w.title)))


def _client_region(w) -> Region:
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            hwnd = w._hWnd
            r = wintypes.RECT()
            pt = wintypes.POINT(0, 0)
            if (
                ctypes.windll.user32.GetClientRect(hwnd, ctypes.byref(r))
                and ctypes.windll.user32.ClientToScreen(hwnd, ctypes.byref(pt))
                and r.right > 0
                and r.bottom > 0
            ):
                return Region(pt.x, pt.y, r.right, r.bottom)
        except Exception:
            pass
    return Region(w.left, w.top, w.width, w.height)


def find_window(title_part: str) -> Region:
    ws = _matches(title_part)
    if not ws:
        raise LookupError(f"No window matching {title_part!r}. Run: python -m phone_remote windows")
    shown = [w for w in ws if not _minimized(w)]
    if not shown:
        raise LookupError(f"Window {ws[0].title!r} is minimized.")
    return _client_region(shown[0])


def find_mirror(title_part: str | None = None) -> Region:
    """Find the AirPlay window, trying the configured title, the AirPlay name, then UxPlay."""
    cfg = load_config()
    hints: list[str] = []
    seen: set[str] = set()
    for candidate in (title_part, cfg.get("mirror_title"), cfg.get("airplay_name"), "uxplay"):
        text = str(candidate or "").strip()
        key = text.lower()
        if text and key not in seen:
            hints.append(text)
            seen.add(key)
    errors: list[str] = []
    for hint in hints:
        try:
            return find_window(hint)
        except LookupError as e:
            errors.append(str(e))
    looked = ", ".join(repr(hint) for hint in hints) or "(none)"
    detail = f" {errors[-1]}" if errors else ""
    raise LookupError(f"No mirror window. Looked for {looked}.{detail}")


def phone_box(img: np.ndarray, aspect: float | None = None) -> tuple[int, int, int, int]:
    if aspect is None:
        aspect = float(load_config().get("phone_aspect", 2.168))
    H, W = img.shape[:2]
    if W * aspect > H:
        w = int(round(H / aspect))
        return (W - w) // 2, 0, w, H
    h = int(round(W * aspect))
    return 0, (H - h) // 2, W, h


def crop_phone(img: np.ndarray) -> np.ndarray:
    x, y, w, h = phone_box(img)
    out = np.zeros((h, w, 3), dtype=img.dtype)
    sy0, sy1 = max(0, y), min(img.shape[0], y + h)
    out[sy0 - y : sy1 - y] = img[sy0:sy1, x : x + w]
    return out


def grab(region: Region | None = None, phone: bool = True) -> np.ndarray:
    with mss.mss() as sct:
        if region is None:
            shot = np.array(sct.grab(sct.monitors[1]))
            img = cv2.cvtColor(shot, cv2.COLOR_BGRA2BGR)
            return crop_phone(img) if phone else img
        screen = sct.monitors[0]
        x0, y0 = max(region.left, screen["left"]), max(region.top, screen["top"])
        x1 = min(region.left + region.width, screen["left"] + screen["width"])
        y1 = min(region.top + region.height, screen["top"] + screen["height"])
        canvas = np.zeros((region.height, region.width, 3), dtype=np.uint8)
        if x1 > x0 and y1 > y0:
            shot = cv2.cvtColor(
                np.array(sct.grab({"left": x0, "top": y0, "width": x1 - x0, "height": y1 - y0})),
                cv2.COLOR_BGRA2BGR,
            )
            canvas[y0 - region.top : y1 - region.top, x0 - region.left : x1 - region.left] = shot
    return crop_phone(canvas) if phone else canvas
