"""Project paths and config."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
REMOTE = DATA / "remote"
CONFIG_PATH = ROOT / "config.json"

DEFAULTS = {
    "airplay_name": "",
    "mirror_title": "Direct3D12 Renderer",
    "phone_mouse_dir": "mouse",
    "msys_shell": r"C:\msys64\msys2_shell.cmd",
    "uxplay_exe": "",
    "videosink": "",
    "mouse_host": "127.0.0.1",
    "mouse_port": 7777,
    "phone_aspect": 2.168,
    "gain": [0.93, 0.925],
    "llm": {
        "provider": "openai",
        "base_url": "http://127.0.0.1:1234/v1",
        "api_key": "",
        "model": "",
        "max_steps": 12,
        "timeout": 120,
    },
}


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    cfg["llm"] = dict(DEFAULTS["llm"])
    try:
        file = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        if not isinstance(file, dict):
            raise ValueError("config.json must be an object")
        llm_over = file.pop("llm", None)
        cfg.update(file)
        if isinstance(llm_over, dict):
            cfg["llm"].update(llm_over)
    except (OSError, ValueError):
        pass
    return cfg


def mouse_dir() -> Path:
    raw = Path(str(load_config().get("phone_mouse_dir", "mouse")))
    return raw if raw.is_absolute() else (ROOT / raw)
