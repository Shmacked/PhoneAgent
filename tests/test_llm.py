"""LLM action parsing and the see-act loop. No network and no phone."""
import json

import numpy as np

import phone_remote.llm as llm


class _Mouse:
    def __init__(self):
        self.calls = []

    def tap(self, x, y, hold=0.08, settle=0.2):
        self.calls.append(("tap", x, y))

    def drag(self, x0, y0, x1, y1, secs=0.5):
        self.calls.append(("drag", x0, y0, x1, y1))

    def scroll(self, n):
        self.calls.append(("scroll", n))

    def home(self):
        self.calls.append(("home",))


def test_parse_strips_fences_and_clamps():
    action = llm.parse_action('```json\n{"action":"tap","x":2,"y":-0.2}\n```')
    assert action == {"action": "tap", "x": 1.0, "y": 0.0}


def test_parse_scroll_is_bounded():
    assert llm.parse_action('{"action":"scroll","n":99}')["n"] == 12


def test_parse_rejects_unknown_actions():
    try:
        llm.parse_action('{"action":"pinch"}')
    except ValueError as e:
        assert "pinch" in str(e)
    else:
        raise AssertionError("unknown action was accepted")


def test_env_key_overrides_config(monkeypatch):
    monkeypatch.setattr(
        llm,
        "load_config",
        lambda: {"llm": {"provider": "openai", "base_url": "http://127.0.0.1:11434/v1", "api_key": "file-key", "model": "qwen"}},
    )
    monkeypatch.setenv("PHONEAGENT_LLM_API_KEY", "env-key")
    settings = llm.llm_settings()
    assert settings["api_key"] == "env-key"
    assert settings["base_url"] == "http://127.0.0.1:11434/v1"
    assert settings["model"] == "qwen"


def test_anthropic_uses_its_own_endpoint_when_left_on_the_local_default(monkeypatch):
    monkeypatch.setattr(
        llm,
        "load_config",
        lambda: {"llm": {"provider": "anthropic", "base_url": "http://127.0.0.1:1234/v1", "model": "claude-sonnet-4-5"}},
    )
    assert llm.llm_settings()["base_url"] == "https://api.anthropic.com"


def test_task_taps_then_stops(tmp_path, monkeypatch):
    monkeypatch.setattr(llm, "REMOTE", tmp_path)
    replies = iter([
        '{"action":"tap","x":0.25,"y":0.75}',
        "Sure! ```json\n{\"action\":\"done\",\"message\":\"Clock is open\"}\n```",
    ])

    def complete(settings, instruction, image_b64, history, note):
        assert instruction == "open Clock"
        assert image_b64
        return next(replies)

    mouse = _Mouse()
    img = np.zeros((30, 20, 3), np.uint8)
    result = llm.run_task("open Clock", mouse, lambda: img, complete=complete)
    assert result == "Clock is open"
    assert mouse.calls == [("tap", 0.25, 0.75)]
    assert (tmp_path / "shot.png").exists()


def test_invalid_reply_is_sent_back_once(tmp_path, monkeypatch):
    monkeypatch.setattr(llm, "REMOTE", tmp_path)
    notes = []

    def complete(settings, instruction, image_b64, history, note):
        notes.append(note)
        if not note:
            return "I will tap the icon"
        return json.dumps({"action": "done", "message": "ok"})

    result = llm.run_task("look", _Mouse(), lambda: np.zeros((8, 8, 3), np.uint8), complete=complete)
    assert result == "ok"
    assert notes[0] == ""
    assert "Rejected" in notes[1]
