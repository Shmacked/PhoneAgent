"""Ask a local or remote vision model to operate the phone.

The model sees the latest mirror shot and returns one JSON action. This module
speaks the OpenAI chat-completions API (LM Studio, Ollama, vLLM, OpenAI,
OpenRouter) and the Anthropic Messages API. The API key is read from the
PHONEAGENT_LLM_API_KEY environment variable when that is set, otherwise from
config.json.
"""
from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.request
from typing import Callable

import cv2
import numpy as np

from .paths import REMOTE, load_config

SYSTEM = """You control an iPhone from a screenshot. Choose exactly one next action.
Coordinates are fractions of the image: x=0 left, x=1 right, y=0 top, y=1 bottom.
Reply with one JSON object and no other text.

{"action":"tap","x":0.5,"y":0.2}
{"action":"drag","x0":0.5,"y0":0.8,"x1":0.5,"y1":0.3}
{"action":"scroll","n":-3}
{"action":"wait","seconds":1}
{"action":"home"}
{"action":"done","message":"what you finished"}
{"action":"fail","message":"why the task cannot be done"}

Negative scroll moves the page down. To type, tap the on-screen keys you can see.
The round AssistiveTouch pointer is not a button. Finish with done as soon as the
task is complete.
"""

_LOCAL_OPENAI = "http://127.0.0.1:1234/v1"


class LLMError(RuntimeError):
    pass


def llm_settings() -> dict:
    raw = load_config().get("llm") or {}
    provider = str(raw.get("provider") or "openai").strip().lower()
    if provider not in ("openai", "anthropic"):
        raise LLMError('llm.provider must be "openai" or "anthropic".')
    base_url = str(raw.get("base_url") or "").strip().rstrip("/")
    if provider == "anthropic" and base_url in ("", _LOCAL_OPENAI):
        base_url = "https://api.anthropic.com"
    if provider == "openai" and not base_url:
        base_url = _LOCAL_OPENAI
    key = os.environ.get("PHONEAGENT_LLM_API_KEY", "").strip() or str(raw.get("api_key") or "").strip()
    try:
        steps = int(raw.get("max_steps") or 12)
        timeout = float(raw.get("timeout") or 120)
    except (TypeError, ValueError) as e:
        raise LLMError("llm.max_steps and llm.timeout must be numbers.") from e
    return {
        "provider": provider,
        "base_url": base_url,
        "api_key": key,
        "model": str(raw.get("model") or "").strip(),
        "max_steps": max(1, min(steps, 40)),
        "timeout": max(5.0, timeout),
    }


def parse_action(text: str) -> dict:
    """Pull the first JSON object out of a model reply and normalize it."""
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1]
        raw = raw.rsplit("```", 1)[0]
    start = raw.find("{")
    if start < 0:
        raise ValueError("reply had no JSON object")
    try:
        data, _ = json.JSONDecoder().raw_decode(raw[start:])
    except json.JSONDecodeError as e:
        raise ValueError("reply was not valid JSON") from e
    if not isinstance(data, dict):
        raise ValueError("reply JSON was not an object")
    op = str(data.get("action") or "").strip().lower()
    if op == "tap":
        return {"action": "tap", "x": _frac(data.get("x")), "y": _frac(data.get("y"))}
    if op == "drag":
        return {
            "action": "drag",
            "x0": _frac(data.get("x0")),
            "y0": _frac(data.get("y0")),
            "x1": _frac(data.get("x1")),
            "y1": _frac(data.get("y1")),
        }
    if op == "scroll":
        try:
            n = int(float(data.get("n")))
        except (TypeError, ValueError) as e:
            raise ValueError("scroll needs an integer n") from e
        return {"action": "scroll", "n": max(-12, min(12, n))}
    if op == "wait":
        try:
            seconds = float(data.get("seconds", 1))
        except (TypeError, ValueError) as e:
            raise ValueError("wait needs seconds") from e
        return {"action": "wait", "seconds": max(0.0, min(15.0, seconds))}
    if op == "home":
        return {"action": "home"}
    if op in ("done", "fail"):
        message = str(data.get("message") or "").strip()[:500]
        if not message:
            message = "done" if op == "done" else "could not finish"
        return {"action": op, "message": message}
    raise ValueError(f"unknown action {op or '(missing)'}")


def execute(mouse, action: dict) -> str:
    op = action["action"]
    if op == "tap":
        mouse.tap(action["x"], action["y"])
        return f"tapped {action['x']:.3f},{action['y']:.3f}"
    if op == "drag":
        mouse.drag(action["x0"], action["y0"], action["x1"], action["y1"])
        return (
            f"dragged {action['x0']:.3f},{action['y0']:.3f} -> "
            f"{action['x1']:.3f},{action['y1']:.3f}"
        )
    if op == "scroll":
        mouse.scroll(action["n"])
        return f"scrolled {action['n']}"
    if op == "wait":
        time.sleep(action["seconds"])
        return f"waited {action['seconds']:.1f}s"
    if op == "home":
        mouse.home()
        return "moved to the corner"
    raise ValueError(f"cannot execute {op}")


def run_task(
    instruction: str,
    mouse,
    grab: Callable[[], np.ndarray],
    *,
    complete: Callable[..., str] | None = None,
    max_steps: int | None = None,
) -> str:
    """See, ask the model, act, repeat. Returns the model's done/fail message."""
    instruction = (instruction or "").strip()
    if not instruction:
        raise LLMError("Tell the model what to do. Example: python -m phone_remote do open Clock")
    settings = llm_settings()
    steps = max_steps if max_steps is not None else settings["max_steps"]
    if complete is None:
        settings["model"] = _resolve_model(settings)
        ask = lambda img, history, note: _complete(settings, instruction, img, history, note)
    else:
        ask = lambda img, history, note: complete(settings, instruction, img, history, note)

    history: list[str] = []
    errors = 0
    print(f"llm task: {instruction}", flush=True)
    for step in range(1, steps + 1):
        img = grab()
        _save_shot(img)
        note = ""
        action = None
        for _try in range(2):
            reply = ask(_png_b64(img), history, note)
            try:
                action = parse_action(reply)
                break
            except ValueError as e:
                note = f"Rejected: {e}. Reply with one JSON object and nothing else."
                print(f"step {step}: {note}", flush=True)
        if action is None:
            return f"stopped: the model did not return a valid action on step {step}"
        if action["action"] == "done":
            print(f"step {step}: done — {action['message']}", flush=True)
            return action["message"]
        if action["action"] == "fail":
            print(f"step {step}: fail — {action['message']}", flush=True)
            return f"could not do it: {action['message']}"
        try:
            result = execute(mouse, action)
            errors = 0
        except Exception as e:
            result = f"error: {type(e).__name__}: {e}"
            errors += 1
        line = f"{step}. {json.dumps(action, separators=(',', ':'))} -> {result}"
        history.append(line)
        print(line, flush=True)
        if errors >= 3:
            return f"stopped: {result}"
    return f"stopped after {steps} steps"


def _resolve_model(settings: dict) -> str:
    if settings["model"]:
        return settings["model"]
    if settings["provider"] == "anthropic":
        raise LLMError("Set llm.model in config.json, for example claude-sonnet-4-5.")
    data = _request("GET", settings["base_url"] + "/models", None, _headers(settings), settings["timeout"])
    ids = [item.get("id") for item in data.get("data") or [] if isinstance(item, dict) and item.get("id")]
    if not ids:
        raise LLMError(
            f"No model is loaded at {settings['base_url']}. Set llm.model in config.json."
        )
    print(f"llm model: {ids[0]}", flush=True)
    return str(ids[0])


def _complete(settings: dict, instruction: str, image_b64: str, history: list[str], note: str) -> str:
    user = _user_text(instruction, history, note)
    if settings["provider"] == "anthropic":
        return _anthropic(settings, user, image_b64)
    return _openai(settings, user, image_b64)


def _user_text(instruction: str, history: list[str], note: str) -> str:
    lines = [f"Task: {instruction}"]
    if history:
        lines.append("What you already did:")
        lines.extend(history[-12:])
    if note:
        lines.append(note)
    lines.append("Look at the screenshot and reply with the next action.")
    return "\n".join(lines)


def _openai(settings: dict, user: str, image_b64: str) -> str:
    payload = {
        "model": settings["model"],
        "temperature": 0,
        "max_tokens": 400,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
                ],
            },
        ],
    }
    data = _request(
        "POST",
        settings["base_url"] + "/chat/completions",
        payload,
        _headers(settings),
        settings["timeout"],
    )
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise LLMError(f"Unexpected LLM response: {str(data)[:300]}") from e
    if isinstance(content, list):
        return "\n".join(str(part.get("text") or "") if isinstance(part, dict) else str(part) for part in content)
    return str(content or "")


def _anthropic(settings: dict, user: str, image_b64: str) -> str:
    if not settings["api_key"]:
        raise LLMError("Set PHONEAGENT_LLM_API_KEY, or llm.api_key, for Anthropic.")
    base = settings["base_url"]
    if base.endswith("/v1"):
        url = base + "/messages"
    elif base.endswith("/messages"):
        url = base
    else:
        url = base + "/v1/messages"
    payload = {
        "model": settings["model"],
        "max_tokens": 400,
        "temperature": 0,
        "system": SYSTEM,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": "image/png", "data": image_b64},
                    },
                    {"type": "text", "text": user},
                ],
            }
        ],
    }
    data = _request("POST", url, payload, _headers(settings), settings["timeout"])
    parts = [
        block.get("text") or ""
        for block in data.get("content") or []
        if isinstance(block, dict) and block.get("type") == "text"
    ]
    if not parts:
        raise LLMError(f"Unexpected Anthropic response: {str(data)[:300]}")
    return "\n".join(parts)


def _headers(settings: dict) -> dict:
    headers = {"Content-Type": "application/json"}
    key = settings.get("api_key") or ""
    if settings["provider"] == "anthropic":
        headers["x-api-key"] = key
        headers["anthropic-version"] = "2023-06-01"
    elif key:
        headers["Authorization"] = f"Bearer {key}"
    return headers


def _request(method: str, url: str, payload: dict | None, headers: dict, timeout: float) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:500]
        raise LLMError(f"LLM HTTP {e.code} from {url}: {detail}") from e
    except urllib.error.URLError as e:
        raise LLMError(f"Could not reach the LLM at {url}: {e.reason}") from e
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as e:
        raise LLMError(f"LLM returned non-JSON from {url}") from e
    if not isinstance(parsed, dict):
        raise LLMError(f"LLM returned an unexpected payload from {url}")
    return parsed


def _frac(value) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as e:
        raise ValueError("a coordinate was missing") from e
    if number != number or number in (float("inf"), float("-inf")):
        raise ValueError("a coordinate was not a finite number")
    return max(0.0, min(1.0, number))


def _png_b64(img: np.ndarray) -> str:
    height, width = img.shape[:2]
    long_side = max(height, width)
    if long_side > 1024:
        scale = 1024 / long_side
        img = cv2.resize(
            img,
            (max(1, int(round(width * scale))), max(1, int(round(height * scale)))),
            interpolation=cv2.INTER_AREA,
        )
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise LLMError("Could not encode the mirror shot.")
    return base64.b64encode(buf.tobytes()).decode("ascii")


def _save_shot(img: np.ndarray) -> None:
    REMOTE.mkdir(parents=True, exist_ok=True)
    tmp = REMOTE / "shot.tmp.png"
    if cv2.imwrite(str(tmp), img):
        tmp.replace(REMOTE / "shot.png")
