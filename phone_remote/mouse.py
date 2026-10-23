"""Bluetooth phone-mouse client.

Talks to mouse/bt_mouse.py on 127.0.0.1:7777. Positions are fractions of the
mirrored phone picture: (0, 0) top-left, (1, 1) bottom-right.
"""
from __future__ import annotations

import json
import math
import socket
import time
from dataclasses import asdict, dataclass
from typing import Callable

import cv2
import numpy as np

from .paths import DATA, load_config, mouse_dir
from .pointer import find_pointer, locate_by_shaking, pointer_moves

CAL_FILE = DATA / "mouse.json"
POINTER_FILE = DATA / "pointer.json"
PACE = 16
ON_TARGET = 0.012
SETTLE = 0.6          # seconds for the mirror to show a pointer move (calibration: be patient)


class MouseError(RuntimeError):
    pass


@dataclass
class Calibration:
    ax: float = 0.0
    bx: float = 0.0
    ay: float = 0.0
    by: float = 0.0
    error: float = 0.0
    version: int = 1
    pace: int = 0
    ref: float = 16.0
    alpha: float = 0.0

    @property
    def ok(self) -> bool:
        return self.ax > 0 and self.ay > 0

    def gain(self, m: float) -> float:
        return (max(m, 0.5) / self.ref) ** self.alpha


def reports(dx: int, dy: int, pace: int) -> tuple[int, int]:
    big = max(abs(dx), abs(dy))
    if big == 0:
        return 0, 1
    step = max(1, min(127, round(pace * big / math.hypot(dx, dy))))
    return max(1, -(-big // step)), step


def load_calibration() -> Calibration:
    try:
        return Calibration(**json.loads(CAL_FILE.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        return Calibration()


class PhoneMouse:
    PACE = PACE

    def __init__(self, host: str | None = None, port: int | None = None):
        cfg = load_config()
        self.addr = (host or cfg["mouse_host"], int(port or cfg["mouse_port"]))
        gx, gy = cfg.get("gain", [1.0, 1.0])
        self.gain_xy = (float(gx), float(gy))
        self.sock: socket.socket | None = None
        self.file = None
        self.cal = load_calibration()
        self.last: tuple[float, float] | None = None
        self.since_home = 0
        self.log: Callable[[str], None] = lambda _msg: None
        self.lag = 0.35
        self._misses_saved = 0
        self._load_pos()

    def _load_pos(self) -> None:
        try:
            data = json.loads(POINTER_FILE.read_text(encoding="utf-8"))
            self.last = (float(data["x"]), float(data["y"]))
        except (OSError, ValueError, TypeError, KeyError):
            self.last = None

    def _save_pos(self) -> None:
        if self.last is None:
            self._clear_pos()
            return
        try:
            POINTER_FILE.parent.mkdir(parents=True, exist_ok=True)
            POINTER_FILE.write_text(
                json.dumps({"x": self.last[0], "y": self.last[1]}),
                encoding="utf-8",
            )
        except OSError:
            pass

    def _clear_pos(self) -> None:
        self.last = None
        try:
            POINTER_FILE.unlink()
        except OSError:
            pass

    def cmd(self, line: str, timeout: float = 30, forget_on_drop: bool = False) -> str:
        for attempt in (1, 2):
            try:
                if self.sock is None:
                    self.sock = socket.create_connection(self.addr, timeout=2)
                    self.file = self.sock.makefile("rw", encoding="utf-8", newline="\n")
                self.sock.settimeout(timeout)
                self.file.write(line + "\n")
                self.file.flush()
                ans = self.file.readline().strip()
                if not ans:
                    raise OSError("connection closed")
                if ans.startswith("err"):
                    raise MouseError(ans[4:] or "error")
                return ans
            except OSError:
                self.close()
                if forget_on_drop:
                    self._clear_pos()
                if attempt == 2:
                    raise MouseError(
                        "Phone mouse is not running. Start it with "
                        f'"Start phone mouse.bat" in {mouse_dir()}.'
                    )
        return ""

    def close(self) -> None:
        try:
            if self.sock:
                self.sock.close()
        except OSError:
            pass
        self.sock = self.file = None

    def status(self) -> str:
        try:
            return self.cmd("status", timeout=3)
        except MouseError:
            return "not-running"

    def problem(self) -> str | None:
        st = self.status()
        if st == "not-running":
            return "phone mouse not running"
        if st != "connected":
            return f"iPhone not connected ({st})"
        if not self.cal.ok:
            return "not calibrated (run Calibrate pointer.bat)"
        if self.cal.version < 6 or self.cal.pace != self.PACE:
            return "pointer speed changed: run Calibrate pointer.bat"
        return None

    def home(self) -> None:
        self.cmd("home", forget_on_drop=True)
        self.last = (self.cal.bx, self.cal.by)
        self.since_home = 0
        self._save_pos()

    def move(self, dx: int, dy: int, pace: int | None = None) -> None:
        if dx or dy:
            dx, dy = int(dx), int(dy)
            _, step = reports(dx, dy, pace or PACE)
            self.cmd(f"move {dx} {dy} {step} 8", forget_on_drop=True)

    def counts_for(self, fx: float, fy: float, pace: int | None = None) -> tuple[int, int]:
        if abs(fx) < 1e-9 and abs(fy) < 1e-9:
            return 0, 0
        cx, cy = fx / self.cal.ax, fy / self.cal.ay
        for _ in range(12):
            n, _ = reports(
                round(cx) or (1 if cx > 0 else -1 if cx < 0 else 0),
                round(cy) or (1 if cy > 0 else -1 if cy < 0 else 0),
                pace or PACE,
            )
            g = self.cal.gain(math.hypot(cx, cy) / max(1, n))
            nx, ny = fx / (self.cal.ax * g), fy / (self.cal.ay * g)
            cx, cy = (cx + nx) / 2, (cy + ny) / 2
        return round(cx), round(cy)

    def move_by(self, fx: float, fy: float, pace: int | None = None) -> None:
        self.move(*self.counts_for(fx, fy, pace), pace=pace)

    def _grab_phone(self) -> np.ndarray:
        from .screen import find_mirror, grab

        return grab(find_mirror(load_config().get("mirror_title")), phone=True)

    def _goto_open(self, fx: float, fy: float, from_corner: bool = False) -> None:
        """Move to a fraction. Uses the last known spot, or the corner when that spot is unknown."""
        gx, gy = self.gain_xy
        if from_corner or self.last is None:
            self.home()
            time.sleep(0.12)
            self.move_by((fx - self.cal.bx) / gx, (fy - self.cal.by) / gy)
        else:
            lx, ly = self.last
            self.move_by((fx - lx) / gx, (fy - ly) / gy)
        self.last = (fx, fy)
        self.since_home += 1
        self._save_pos()

    def _correct_to(self, fx: float, fy: float) -> None:
        """Look at the mirror and finish the move so the pointer is actually on (fx, fy)."""
        grab = self._grab_phone
        recovered = False
        for attempt in range(3):
            radius = 0.18 if attempt == 0 else 0.4
            sign = 0.06 if fx < 0.5 else -0.06
            seen = self._see((fx, fy), self.counts_for(sign, 0.0), grab, radius=radius)
            if seen is None:
                if recovered:
                    raise MouseError(
                        "Could not see the pointer. Turn AssistiveTouch on, keep the pointer "
                        "visible, and hold the phone still."
                    )
                print("pointer not seen near the target; one trip from the corner", flush=True)
                self._goto_open(fx, fy, from_corner=True)
                recovered = True
                continue
            ex, ey = fx - seen[0], fy - seen[1]
            if abs(ex) < ON_TARGET and abs(ey) < ON_TARGET:
                self.last = (fx, fy)
                self._save_pos()
                self.log(f"pointer on target ({fx:.3f},{fy:.3f})")
                return
            gx, gy = self.gain_xy
            self.log(f"pointer at ({seen[0]:.3f},{seen[1]:.3f}), correcting ({ex:+.3f},{ey:+.3f})")
            print(f"pointer off by ({ex:+.3f},{ey:+.3f}), correcting", flush=True)
            self.move_by(ex / gx, ey / gy)
            self.last = (fx, fy)
            self._save_pos()
            if max(abs(ex), abs(ey)) < 0.05:
                return

    def goto(self, fx: float, fy: float, from_corner: bool = False, check: bool = True) -> None:
        if not self.cal.ok:
            raise MouseError("not calibrated")
        self._goto_open(fx, fy, from_corner=from_corner)
        if check:
            self._correct_to(fx, fy)

    def tap(self, fx: float, fy: float, hold: float = 0.08, settle: float = 0.2) -> None:
        self.goto(fx, fy)
        time.sleep(settle)
        self.cmd("down")
        time.sleep(hold)
        self.cmd("up")

    def drag(self, x0: float, y0: float, x1: float, y1: float, secs: float = 0.5) -> None:
        self.goto(x0, y0)
        time.sleep(0.15)
        self.cmd("down")
        time.sleep(0.2)
        steps = max(1, int(secs / 0.05))
        gx, gy = self.gain_xy
        for _ in range(steps):
            self.move_by((x1 - x0) / steps / gx, (y1 - y0) / steps / gy)
            time.sleep(0.05)
        time.sleep(0.15)
        self.cmd("up")
        self.last = (x1, y1)
        self._save_pos()

    def scroll(self, n: int) -> None:
        self.cmd(f"scroll {int(n)}")

    def travel(self, dx: int, dy: int, pace: int | None = None) -> tuple[float, float]:
        """How far (screen fractions) a move of (dx, dy) counts takes the pointer."""
        n, _ = reports(int(dx), int(dy), pace or self.PACE)
        if n == 0:
            return 0.0, 0.0
        g = self.cal.gain(math.hypot(dx, dy) / n)
        return dx * self.cal.ax * g, dy * self.cal.ay * g

    def _watch(self, grab: Callable[[], np.ndarray], near: tuple[float, float] | None,
               radius: float, settle: float, still: float = 0.2,
               timeout: float = 1.5) -> list[tuple[float, np.ndarray]]:
        """Keep taking mirror pictures until the area around `near` has changed and then
        stayed the same. Returns (seconds since start, picture)."""
        t0 = time.monotonic()
        frames = [(0.0, grab())]
        H, W = frames[0][1].shape[:2]
        if near is None:
            x0, x1, y0, y1 = 0, W, 0, H
        else:
            x0, x1 = max(0, int((near[0] - radius) * W)), min(W, int((near[0] + radius) * W))
            y0, y1 = max(0, int(near[1] * H - radius * W)), min(H, int(near[1] * H + radius * W))
        changed, still_since = False, 0.0
        while True:
            time.sleep(0.02)
            cur = grab()
            now = time.monotonic() - t0
            prev = frames[-1][1]
            frames.append((now, cur))
            if x1 > x0 and y1 > y0:
                d = cv2.absdiff(cur[y0:y1, x0:x1], prev[y0:y1, x0:x1]).max(axis=2)
                diff = int(cv2.blur(d, (5, 5)).max()) if d.size else 0
            else:
                diff = 0
            if diff > 25:
                changed, still_since = True, now
            elif changed and now >= settle and now - still_since >= still:
                return frames
            if now > timeout:
                return frames

    def _see(self, near: tuple[float, float], nudge: tuple[int, int],
             grab: Callable[[], np.ndarray], radius: float = 0.12) -> tuple[float, float] | None:
        """Where the pointer is now: flick it by `nudge` counts and back, and find the flick."""
        time.sleep(0.08)
        self.move(*nudge)
        t_out = time.monotonic()
        time.sleep(0.12)
        self.move(-nudge[0], -nudge[1])
        since = time.monotonic() - t_out
        frames = self._watch(grab, near, radius + 0.05, settle=max(0.0, self.lag + 0.1 - since),
                             still=0.15, timeout=max(1.2, 2.5 * self.lag))
        a = np.median(np.stack([f for _, f in frames[-3:]]), axis=0).astype(np.uint8) if len(frames) >= 3 else frames[-1][1]
        H, W = a.shape[:2]
        tx, ty = self.travel(*nudge)
        direction = (tx * W, ty * H)
        expect = math.hypot(tx, ty * H / W)

        def search(rad: float):
            x0, x1 = max(0, int((near[0] - rad) * W)), min(W, int((near[0] + rad) * W))
            y0, y1 = max(0, int(near[1] * H - rad * W)), min(H, int(near[1] * H + rad * W))

            def differs(f):
                return float(cv2.absdiff(f[y0:y1, x0:x1], a[y0:y1, x0:x1]).mean()) if x1 > x0 and y1 > y0 else 0.0

            ranked, last = [], None
            for t, f in reversed(frames[:-1]):
                if last is not None and float(cv2.absdiff(f[y0:y1, x0:x1], last[y0:y1, x0:x1]).mean()) < 0.3:
                    continue
                if differs(f) >= 0.3:
                    ranked.append((t, f))
                    last = f
            due = self.lag - since + 0.06
            ranked.sort(key=lambda tf: 0 if -0.12 <= tf[0] - due <= 0.25 else 1)
            window = [i for i, (t, _) in enumerate(frames[:-1]) if -0.12 <= t - due <= 0.25]
            for i in window[1:-1]:
                trio = np.median(np.stack([frames[j][1] for j in (i - 1, i, i + 1)]), axis=0).astype(np.uint8)
                ranked.insert(0, (frames[i][0], trio))
            for t, b in ranked[:12]:
                p = find_pointer(a, b, direction, near=near, radius=rad, expect=expect)
                if p is not None:
                    self.lag = min(1.2, max(0.05, 0.7 * self.lag + 0.3 * (t + since - 0.07)))
                    return p, ranked
            return None, ranked

        p, ranked = search(radius)
        if p is None:
            p, ranked = search(min(0.4, radius * 2.5))
        if p is not None:
            return p
        self._save_miss(a, ranked[0][1] if ranked else a)
        return locate_by_shaking(grab, self.move, nudge, direction, cycles=2, near=near,
                                 radius=radius, expect=expect, wait=self.lag + 0.15)

    def _save_miss(self, a: np.ndarray, b: np.ndarray) -> None:
        if self._misses_saved >= 2:
            return
        self._misses_saved += 1
        try:
            path = CAL_FILE.parent / f"look-miss-{self._misses_saved}.png"
            path.parent.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(path), np.hstack([a, b]))
        except Exception:
            pass

    def calibrate(self, grab: Callable[[], np.ndarray], say: Callable[[str], None] = print) -> Calibration:
        """Learn how far the pointer moves per mouse count, and write data/mouse.json.

        Walks the pointer down and right in small steps, fits position against counts,
        then measures how much iOS speeds up faster moves. Keep the phone still.
        """
        st = self.status()
        if st != "connected":
            raise MouseError("The iPhone isn't connected to the phone mouse.")
        self.last = None
        say("Calibrating: keep the phone still and don't touch it (about 30 seconds).")

        self.home()
        time.sleep(SETTLE)
        H, W = grab().shape[:2]
        t0 = time.monotonic()
        self.move(self.PACE * 3, self.PACE * 6)
        frames = self._watch(grab, (0.08, 0.06), 0.15, settle=0.0, timeout=2.0)
        x1, y1 = int(0.23 * W), int(0.06 * H + 0.15 * W)

        def corner_change(f, g):
            d = cv2.absdiff(f[:y1, :x1], g[:y1, :x1]).max(axis=2)
            return int(cv2.blur(d, (5, 5)).max()) > 25

        moved = [corner_change(f, frames[0][1]) for _, f in frames]
        first = next((i for i in range(1, len(moved)) if all(moved[i:])), None)
        if first is not None and first < len(moved) - 1:
            self.lag = min(1.2, max(0.08, frames[first][0] - 0.02))
        self.log(f"calibration: the mirror shows moves after about {self.lag:.2f} s")
        self.home()
        time.sleep(max(SETTLE, self.lag + 0.3))
        prev = grab()
        step = self.PACE
        cum = (0, 0)
        pts: list[tuple[int, int, float, float]] = []
        here, per_step, lost, grown = None, None, 0, False
        for k in range(45):
            self.move(step, 2 * step)
            cum = (cum[0] + step, cum[1] + 2 * step)
            if here is not None and per_step is not None:
                watch_at, watch_r = (here[0] + per_step[0], here[1] + per_step[1]), 0.15
            else:
                watch_at, watch_r = None, 1.0
            cur = self._watch(grab, watch_at, watch_r, settle=max(self.lag, 0.3) + 0.1, still=0.15, timeout=2.0)
            cur = np.median(np.stack([f for _, f in cur[-3:]]), axis=0).astype(np.uint8) if len(cur) >= 3 else cur[-1][1]
            if here is not None and per_step is not None:
                near = (here[0] + per_step[0] / 2, here[1] + per_step[1] / 2)
                radius = 0.07 + math.hypot(per_step[0], per_step[1] * H / W)
                direction = (per_step[0] * W, per_step[1] * H)
            elif here is not None:
                near, radius, direction = here, 0.3, (1.0, 2.0)
            elif k == 0:
                near, radius, direction = (0.0, 0.0), 0.45, (1.0, 2.0)
            else:
                near, radius, direction = None, 1.0, (1.0, 2.0)
            exp = math.hypot(per_step[0], per_step[1] * H / W) if per_step is not None else None
            r = pointer_moves(prev, cur, direction, near=near, radius=radius, expect=exp)
            if r is not None:
                departed, arrived = r
                pts.append((cum[0], cum[1], arrived[0], arrived[1]))
                if len(pts) < 3:
                    per_step = (arrived[0] - departed[0], arrived[1] - departed[1])
                if len(pts) >= 3:
                    (c0, _, x0, y0), (c1, _, x1, y1) = pts[-3], pts[-1]
                    rate = ((x1 - x0) / max(1, c1 - c0), (y1 - y0) / max(1, c1 - c0))
                    if not grown and math.hypot(rate[0] * step, rate[1] * step * H / W) < 0.06:
                        step = max(step + 1, round(step * 0.06 / max(1e-6, math.hypot(rate[0], rate[1] * H / W) * step)))
                        grown = True
                    per_step = (rate[0] * step, rate[1] * step)
                here, lost = arrived, 0
            else:
                lost += 1
                if here is not None and per_step is not None:
                    here = (here[0] + per_step[0], here[1] + per_step[1])
                if lost > 6:
                    break
            prev = cur
            if here is not None and (here[0] > 0.85 or here[1] > 0.85):
                break
        self.log(f"calibration walk: {len(pts)} sightings: " +
                 " ".join(f"({x:.2f},{y:.2f})" for _, _, x, y in pts))
        good = [q for q in pts if q[2] > 0.04 and q[3] > 0.03]
        if len(good) < 5:
            try:
                path = CAL_FILE.parent / "calib-miss-walk.png"
                path.parent.mkdir(parents=True, exist_ok=True)
                cv2.imwrite(str(path), grab())
            except Exception:
                pass
            raise MouseError(
                f"Only saw the pointer {len(good)} times while walking it across the screen. "
                "Is AssistiveTouch on and the pointer visible (Settings > Accessibility > "
                "Pointer Control > turn off Automatically Hide Pointer)?"
            )
        arr = np.array(good, dtype=float)
        for _ in range(3):
            ax, bx = np.polyfit(arr[:, 0], arr[:, 2], 1)
            ay, by = np.polyfit(arr[:, 1], arr[:, 3], 1)
            res = np.hypot(arr[:, 0] * ax + bx - arr[:, 2], arr[:, 1] * ay + by - arr[:, 3])
            worst = int(np.argmax(res))
            if len(arr) > 6 and res[worst] > max(0.015, 3 * float(np.median(res))):
                arr = np.delete(arr, worst, axis=0)
            else:
                break
        n_walk, _ = reports(step, 2 * step, self.PACE)
        m_walk = math.hypot(step, 2 * step) / max(1, n_walk)
        cal = Calibration(float(ax), float(bx), float(ay), float(by), float(np.mean(res)), version=6,
                          pace=self.PACE, ref=float(m_walk), alpha=0.0)
        if not cal.ok:
            raise MouseError("Calibration came out backwards; try again.")
        self.cal = cal
        say(f"  walked {len(pts)} steps; per count: {ax:.5f} across, {ay:.5f} down")

        alphas = []
        walk_pace = max(1, round(m_walk))
        for tx, ty in ((0.3, 0.6), (0.7, 0.6)):
            self.home()
            self.move_by(tx - self.cal.bx, ty - self.cal.by, pace=walk_pace)
            sign = 1 if tx < 0.5 else -1
            nudge = self.counts_for(sign * 0.06, 0)
            q0 = self._see((tx, ty), nudge, grab, radius=0.2)
            if q0 is None:
                continue
            slow_pace = max(2, self.PACE // 4)
            c = round(0.25 / self.cal.ax)
            self.move(sign * c, 0, pace=slow_pace)
            guess = (q0[0] + sign * 0.25 * (slow_pace / m_walk) ** 0.5, q0[1])
            q1 = self._see(guess, (-nudge[0], 0), grab, radius=0.25)
            if q1 is None:
                continue
            self.move(-sign * c, 0)
            q2 = self._see(q0, nudge, grab, radius=0.25)
            if q2 is None:
                continue
            slow, fast = abs(q1[0] - q0[0]) / c, abs(q1[0] - q2[0]) / c
            m_slow = c / reports(c, 0, slow_pace)[0]
            m_fast = c / reports(c, 0, self.PACE)[0]
            if slow > 0 and fast > 0 and m_fast > m_slow:
                a = math.log(fast / slow) / math.log(m_fast / m_slow)
                alphas.append(a)
                self.log(f"calibration speed-up: slow {slow:.5f}/count at {m_slow:.1f}, fast {fast:.5f} at "
                         f"{m_fast:.1f} -> alpha {a:.2f}")
        self.cal.alpha = float(min(1.5, max(0.0, float(np.median(alphas))))) if alphas else 0.45
        say(f"  speed-up: {self.cal.alpha:.2f}" + ("" if alphas else " (couldn't measure; using a typical value)"))

        misses = []
        for tx, ty in ((0.3, 0.55), (0.7, 0.55), (0.3, 0.8), (0.7, 0.8)):
            self.home()
            self.move_by(tx - self.cal.bx, ty - self.cal.by)
            q = self._see((tx, ty), self.counts_for(0.06 if tx < 0.5 else -0.06, 0), grab, radius=0.18)
            if q is not None:
                misses.append(math.hypot(q[0] - tx, q[1] - ty))
                self.log(f"calibration check ({tx},{ty}): saw ({q[0]:.3f},{q[1]:.3f})")
            else:
                self.log(f"calibration check ({tx},{ty}): pointer not seen")
        miss = float(np.mean(misses)) if misses else cal.error
        self.cal.error = miss
        self.save_cal()
        self.home()
        say(f"Calibrated. Average miss {miss * 100:.1f}% of the screen. Saved {CAL_FILE}")
        return self.cal

    def save_cal(self) -> None:
        CAL_FILE.parent.mkdir(parents=True, exist_ok=True)
        CAL_FILE.write_text(json.dumps(asdict(self.cal), indent=2), encoding="utf-8")
