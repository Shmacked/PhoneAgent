"""Find the AssistiveTouch pointer in a pair of mirror frames.

The pointer is a see-through dark disc: where it arrives the picture gets darker,
where it left the picture gets lighter.
"""
from __future__ import annotations

import math
import time
from typing import Callable

import cv2
import numpy as np

LOOK = 0.3


def locate_by_shaking(grab: Callable[[], np.ndarray], move: Callable[[int, int], None],
                      nudge: tuple[int, int], direction: tuple[float, float], cycles: int = 3,
                      wait: float = LOOK, near: tuple[float, float] | None = None,
                      radius: float = 0.25, expect: float | None = None) -> tuple[float, float] | None:
    """Find the pointer even on a busy, animated screen: move it back and forth between
    A and B a few times, taking a picture at each, and keep only the change that happens
    every time. Animations don't follow that rhythm, so they drop out. Returns where the
    pointer is at A (where it ends up)."""
    at_a, at_b = [], []
    time.sleep(wait)
    for _ in range(cycles):
        at_a.append(grab().astype(np.int16))
        move(*nudge)
        time.sleep(wait)
        at_b.append(grab().astype(np.int16))
        move(-nudge[0], -nudge[1])
        time.sleep(wait)
    a = np.median(np.stack(at_a), axis=0).astype(np.uint8)
    b = np.median(np.stack(at_b), axis=0).astype(np.uint8)
    return find_pointer(a, b, direction, near=near, radius=radius, expect=expect)


def pointer_moves(before: np.ndarray, after: np.ndarray, direction,
                  near: tuple[float, float] | None = None, radius: float = 0.25,
                  expect: float | None = None):
    """Where the pointer was in `before` and where it is in `after`, as ((x, y), (x, y))
    in screen fractions, or None.

    The pointer is a see-through dark disc: where it arrives the picture gets darker, where
    it left it gets lighter, by about the same area, one move apart in the direction it was
    sent. Flashing or moving things on screen don't make that matched pair, so they're
    ignored. Works when the two spots overlap too (a dark and a light crescent).
    `expect`: how far it should have moved (fraction of the width), if known: a pair that
    moved a quite different distance isn't the pointer."""
    if before is None or after is None or before.shape != after.shape:
        return None
    if isinstance(direction, (int, float)):
        ux, uy = (1.0 if direction > 0 else -1.0), 0.0
    else:
        n = math.hypot(*direction) or 1.0
        ux, uy = direction[0] / n, direction[1] / n
    H, W = before.shape[:2]
    g0 = cv2.cvtColor(before, cv2.COLOR_BGR2GRAY).astype(np.int16)
    g1 = cv2.cvtColor(after, cv2.COLOR_BGR2GRAY).astype(np.int16)
    d = g1 - g0
    lo, hi = 0.00002 * H * W, 0.012 * H * W
    kern = np.ones((3, 3), np.uint8)
    k = max(5, int(0.012 * W)) | 1
    fill = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))

    def blobs(mask):
        # Over black letter strokes the pointer can't make anything darker, which splits
        # its spot into pieces: close those gaps first.
        mask = cv2.morphologyEx(mask.astype(np.uint8), cv2.MORPH_OPEN, kern)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, fill)
        n, lab, st, cen = cv2.connectedComponentsWithStats(mask)
        out = []
        for i in range(1, n):
            x, y, w, h, a = (int(v) for v in st[i])
            if not (lo <= a <= hi) or max(w, h) > 0.15 * W:
                continue
            cx, cy = float(cen[i][0]), float(cen[i][1])
            if near is not None and math.hypot(cx - near[0] * W, cy - near[1] * H) > radius * W:
                continue
            ys, xs = np.nonzero(lab[y:y + h, x:x + w] == i)
            along = (xs + x) * ux + (ys + y) * uy
            across = -(xs + x) * uy + (ys + y) * ux
            out.append((cx, cy, a, float(along.max() - along.min()), float(across.max() - across.min())))
        return out

    darker, lighter = blobs(d < -12), blobs(d > 12)
    # Normally the arriving spot gets darker; over a very dark background the pointer can
    # look lighter instead, so try it both ways round.
    pairs = [(a, b, 0.0) for a in darker for b in lighter] + [(b, a, 0.01) for a in darker for b in lighter]
    best, best_score = None, 1e9
    for (dx_, dy_, da, dspan, dthick), (lx, ly, la, lspan, lthick), penalty in pairs:
        vx, vy = dx_ - lx, dy_ - ly
        along = vx * ux + vy * uy
        across = abs(vx * uy - vy * ux)
        if along <= 0.003 * W or along > 0.45 * W or across > 0.25 * along + 0.01 * W:
            continue
        size = abs(math.log((da + 1) / (la + 1)))
        if size > 0.9 or abs(math.log((dthick + 1) / (lthick + 1))) > 0.6:
            continue
        diameter = max(dthick, lthick)
        # Apart: the blobs are the two spots. Overlapping: two crescents whose length
        # along the move equals the move.
        move = along if along >= diameter else (dspan + lspan) / 2
        if expect is not None and not (0.45 * expect * W <= move <= 2.2 * expect * W):
            continue
        score = across / W + 0.05 * size + penalty
        if expect is not None:
            score += 0.5 * abs(move / W - expect)
        if score < best_score:
            mx, my = (dx_ + lx) / 2, (dy_ + ly) / 2
            best = ((mx - ux * move / 2) / W, (my - uy * move / 2) / H), \
                   ((mx + ux * move / 2) / W, (my + uy * move / 2) / H)
            best_score = score
    return best


def find_pointer(before: np.ndarray, after: np.ndarray, direction=1,
                 near: tuple[float, float] | None = None, radius: float = 0.25,
                 expect: float | None = None) -> tuple[float, float] | None:
    """Where the pointer was in `before`, given that it moved a little in `after`
    (`direction`: +1 right / -1 left, or a (dx, dy) direction in screen pixels; `expect`:
    how far it should have moved, as a fraction of the width, if known)."""
    r = pointer_moves(before, after, direction, near, radius, expect)
    return None if r is None else r[0]
