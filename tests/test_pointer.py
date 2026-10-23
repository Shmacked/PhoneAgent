"""Pointer finding and calibration math. No phone required."""
import math

import cv2
import numpy as np

from phone_remote.mouse import Calibration, PhoneMouse
from phone_remote.pointer import find_pointer, pointer_moves


def _pointer(img, x, y):
    """Like the iOS AssistiveTouch pointer: a see-through dark disc."""
    out = img.copy()
    mask = np.zeros(img.shape[:2], np.uint8)
    cv2.circle(mask, (x, y), 15, 1, -1)
    out[mask > 0] = (out[mask > 0] * 0.6).astype(np.uint8)
    return out


def test_finds_pointer_on_busy_and_plain_backgrounds():
    rng = np.random.default_rng(1)
    busy = cv2.GaussianBlur((rng.random((1406, 648, 3)) * 255).astype(np.uint8), (31, 31), 0)
    felt = np.full((1406, 648, 3), (60, 140, 60), np.uint8)
    for bg in (busy, felt):
        for x, y, d in ((100, 200, 40), (500, 1200, -30), (320, 700, 90), (320, 700, -90)):
            got = find_pointer(_pointer(bg, x, y), _pointer(bg, x + d, y), 1 if d > 0 else -1)
            assert got is not None
            assert abs(got[0] - x / 648) < 0.01 and abs(got[1] - y / 1406) < 0.01, got


def test_no_pointer_means_none():
    img = np.full((800, 400, 3), 90, np.uint8)
    assert find_pointer(img, img.copy()) is None


def test_counts_for_undoes_travel_with_speed_up():
    m = PhoneMouse()
    m.cal = Calibration(ax=0.002, bx=0.01, ay=0.001, by=0.02, version=6, pace=16, ref=16, alpha=0.6)
    for fx, fy in ((0.5, 0.5), (0.3, -0.1), (0.01, 0.0), (-0.004, 0.006), (0.0, 0.7)):
        tx, ty = m.travel(*m.counts_for(fx, fy))
        assert abs(tx - fx) < 0.003 and abs(ty - fy) < 0.003, (fx, fy, tx, ty)


def test_pointer_ignores_flashes_when_the_move_size_is_known():
    rng = np.random.default_rng(3)
    bg = cv2.GaussianBlur((rng.random((1400, 650, 3)) * 160 + 60).astype(np.uint8), (41, 41), 0)
    a = _pointer(bg, 300, 700)
    b = _pointer(bg, 340, 700)
    cv2.circle(b, (330, 640), 14, (20, 20, 20), -1)
    cv2.circle(a, (290, 640), 14, (250, 250, 250), -1)
    left, arrived = pointer_moves(a, b, (1, 0), near=(0.48, 0.48), radius=0.15, expect=40 / 650)
    assert math.hypot(left[0] - 300 / 650, left[1] - 0.5) < 0.01, left
    assert math.hypot(arrived[0] - 340 / 650, arrived[1] - 0.5) < 0.01, arrived
