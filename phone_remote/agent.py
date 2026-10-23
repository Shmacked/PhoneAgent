"""File-based remote control (cmd.txt / shot.png / done.txt).

Write one command per line to data/remote/cmd.txt; the first word is a unique id:
    1 shot
    2 tap 0.50 0.72
    3 drag 0.4 0.5 0.6 0.5 0.4
    4 home
    5 wait 1.5
    6 status
    7 scroll -3
    8 do Open the Clock app

Each new id is run once; results append to data/remote/done.txt. Screen-changing
commands refresh data/remote/shot.png.
"""
from __future__ import annotations

import time
import traceback
from pathlib import Path

import cv2

from . import screen
from .mouse import PhoneMouse
from .paths import REMOTE, load_config


class Agent:
    def __init__(self, title: str | None = None):
        cfg = load_config()
        self.title = title or cfg["mirror_title"]
        self.mouse = PhoneMouse()
        self.done: set[str] = set()
        self.mtime = 0.0
        try:
            for line in (REMOTE / "done.txt").read_text(encoding="utf-8").splitlines():
                if line.split():
                    self.done.add(line.split()[0])
        except OSError:
            pass

    def _say(self, cid: str, text: str) -> None:
        REMOTE.mkdir(parents=True, exist_ok=True)
        with open(REMOTE / "done.txt", "a", encoding="utf-8") as f:
            f.write(f"{cid} {time.strftime('%H:%M:%S')} {text}\n")
        print(f"remote {cid}: {text}", flush=True)

    def _grab(self):
        return screen.grab(screen.find_mirror(self.title), phone=True)

    def _shot(self) -> str:
        img = self._grab()
        REMOTE.mkdir(parents=True, exist_ok=True)
        tmp = REMOTE / "shot.tmp.png"
        cv2.imwrite(str(tmp), img)
        tmp.replace(REMOTE / "shot.png")
        return f"shot {img.shape[1]}x{img.shape[0]}"

    def poll_once(self) -> bool:
        """Process new cmd.txt lines. Returns True if any command ran."""
        f = REMOTE / "cmd.txt"
        try:
            m = f.stat().st_mtime
        except OSError:
            return False
        if m == self.mtime:
            return False
        self.mtime = m
        try:
            lines = f.read_text(encoding="utf-8").splitlines()
        except OSError:
            return False
        ran = False
        for line in lines:
            parts = line.split()
            if len(parts) < 2 or parts[0] in self.done:
                continue
            cid, op = parts[0], parts[1].lower()
            args = [float(x) for x in parts[2:] if _num(x)]
            self.done.add(cid)
            ran = True
            try:
                res = self._run(op, args, parts)
                if res is None:
                    self._say(cid, f"error unknown command {op}")
                else:
                    self._say(cid, "ok " + res)
            except Exception as e:
                self._say(
                    cid,
                    f"error {type(e).__name__}: {e} | {traceback.format_exc(limit=2)!r}",
                )
        return ran

    def _run(self, op: str, args: list[float], parts: list[str]) -> str | None:
        m = self.mouse
        if op == "shot":
            return self._shot()
        if op == "status":
            return f"status {m.status()} problem={m.problem()} mirror={self.title!r}"
        if op == "windows":
            return "windows " + " | ".join(screen.list_windows()[:40])
        if op == "home":
            m.home()
            return "home"
        if op == "wait":
            time.sleep(min(args[0] if args else 1.0, 60))
            return self._shot()
        if op == "tap":
            hold = args[2] if len(args) > 2 else 0.08
            m.tap(args[0], args[1], hold=hold)
            time.sleep(0.8)
            return self._shot()
        if op == "move":
            m.goto(args[0], args[1])
            time.sleep(0.5)
            return self._shot()
        if op == "drag":
            secs = args[4] if len(args) > 4 else 0.5
            m.drag(args[0], args[1], args[2], args[3], secs=secs)
            time.sleep(0.8)
            return self._shot()
        if op == "scroll":
            m.scroll(int(args[0]) if args else -3)
            time.sleep(0.5)
            return self._shot()
        if op == "click":
            m.cmd("click")
            time.sleep(0.5)
            return self._shot()
        if op == "raw":
            # raw <mouse-cmd...> e.g. "7 raw move 40 0"
            rest = " ".join(parts[2:])
            ans = m.cmd(rest)
            return f"raw {ans}"
        if op == "do":
            from .llm import run_task

            instruction = " ".join(parts[2:]).strip()
            return run_task(instruction, m, self._grab)
        return None

    def run_forever(self, interval: float = 0.25) -> None:
        REMOTE.mkdir(parents=True, exist_ok=True)
        print(f"phone-agent watching {REMOTE / 'cmd.txt'}", flush=True)
        print(f"airplay name: {load_config().get('airplay_name') or '(set airplay_name in config.json)'}", flush=True)
        print(f"mirror title: {self.title!r}", flush=True)
        print(f"mouse: {self.mouse.status()} ({self.mouse.problem() or 'ready'})", flush=True)
        print("llm task: write '<id> do <instruction>' to cmd.txt", flush=True)
        while True:
            self.poll_once()
            time.sleep(interval)


def _num(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


def write_cmd(cid: str, line: str) -> Path:
    """Append a command for the agent (creates cmd.txt if needed)."""
    REMOTE.mkdir(parents=True, exist_ok=True)
    path = REMOTE / "cmd.txt"
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"{cid} {line}\n")
    return path
