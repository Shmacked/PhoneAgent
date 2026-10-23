"""CLI: python -m phone_remote <command>"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# Allow running without install: python -m phone_remote from this folder
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="phone-agent",
        description="Drive an AirPlay-mirrored iPhone via the bundled Bluetooth pointer.",
    )
    p.add_argument("--title", help="part of the mirror window title (default: config)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("agent", help="poll data/remote/cmd.txt forever")
    sub.add_parser("status", help="mouse + mirror status")
    sub.add_parser("windows", help="list window titles")
    sub.add_parser("shot", help="save one mirror shot to data/remote/shot.png")
    sub.add_parser("calibrate", help="watch the mirror and write data/mouse.json")

    t = sub.add_parser("tap", help="tap at fraction x y")
    t.add_argument("x", type=float)
    t.add_argument("y", type=float)
    t.add_argument("--hold", type=float, default=0.08)

    m = sub.add_parser("move", help="move pointer to fraction x y")
    m.add_argument("x", type=float)
    m.add_argument("y", type=float)

    d = sub.add_parser("drag", help="drag from x0 y0 to x1 y1")
    d.add_argument("x0", type=float)
    d.add_argument("y0", type=float)
    d.add_argument("x1", type=float)
    d.add_argument("y1", type=float)
    d.add_argument("--secs", type=float, default=0.5)

    sub.add_parser("home", help="shove pointer to top-left")
    sc = sub.add_parser("scroll", help="scroll wheel")
    sc.add_argument("n", type=int)

    q = sub.add_parser("queue", help="append a line to cmd.txt for the running agent")
    q.add_argument("id", help="unique command id")
    q.add_argument("rest", nargs=argparse.REMAINDER, help="command words, e.g. tap 0.5 0.5")

    task = sub.add_parser("do", help="ask the configured LLM to carry out one task on the phone")
    task.add_argument("instruction", nargs="+", help="what to do, in plain language")

    a = p.parse_args(argv)

    from . import screen
    from .agent import Agent, write_cmd
    from .mouse import MouseError, PhoneMouse
    from .paths import REMOTE, load_config

    title = a.title or load_config()["mirror_title"]

    if a.cmd == "agent":
        Agent(title=title).run_forever()
        return 0

    if a.cmd == "windows":
        for t_ in screen.list_windows():
            print(t_)
        return 0

    if a.cmd == "status":
        mouse = PhoneMouse()
        print(f"mouse: {mouse.status()}")
        print(f"problem: {mouse.problem() or 'none'}")
        print(f"airplay name: {load_config().get('airplay_name') or '(set airplay_name in config.json)'}")
        print(f"mirror title config: {title!r}")
        try:
            region = screen.find_mirror(title)
            print(f"mirror window: {region.width}x{region.height} at ({region.left},{region.top})")
        except LookupError as e:
            print(f"mirror window: {e}")
        return 0

    if a.cmd == "calibrate":
        mouse = PhoneMouse()
        mouse.log = print

        def grab():
            return screen.grab(screen.find_mirror(title), phone=True)

        try:
            mouse.calibrate(grab)
        except (LookupError, MouseError) as e:
            print(e, file=sys.stderr)
            return 1
        return 0

    if a.cmd == "queue":
        rest = " ".join(a.rest).strip()
        if not rest:
            print("usage: phone-agent queue <id> <command...>", file=sys.stderr)
            return 2
        path = write_cmd(a.id, rest)
        print(f"queued -> {path}: {a.id} {rest}")
        return 0

    if a.cmd == "do":
        from .llm import LLMError, run_task

        text = " ".join(a.instruction).strip()
        driver = Agent(title=title)
        try:
            print(run_task(text, driver.mouse, driver._grab))
        except (LookupError, MouseError, LLMError) as e:
            print(e, file=sys.stderr)
            return 1
        return 0

    agent = Agent(title=title)
    mouse = agent.mouse

    if a.cmd == "shot":
        print(agent._shot())
        print(f"wrote {REMOTE / 'shot.png'}")
        return 0

    if a.cmd == "home":
        mouse.home()
        print("home")
        return 0

    if a.cmd == "tap":
        mouse.tap(a.x, a.y, hold=a.hold)
        time.sleep(0.5)
        print(agent._shot())
        return 0

    if a.cmd == "move":
        mouse.goto(a.x, a.y)
        time.sleep(0.4)
        print(agent._shot())
        return 0

    if a.cmd == "drag":
        mouse.drag(a.x0, a.y0, a.x1, a.y1, secs=a.secs)
        time.sleep(0.5)
        print(agent._shot())
        return 0

    if a.cmd == "scroll":
        mouse.scroll(a.n)
        time.sleep(0.4)
        print(agent._shot())
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
