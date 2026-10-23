"""Relative moves and the mirror correction. No phone required."""
import phone_remote.mouse as M


def _mouse(tmp_path, monkeypatch):
    monkeypatch.setattr(M, "POINTER_FILE", tmp_path / "pointer.json")
    m = M.PhoneMouse()
    m.cal = M.Calibration(ax=0.002, bx=0.01, ay=0.001, by=0.02, version=6, pace=16, ref=16, alpha=0.0)
    sent = []

    def fake(line, timeout=30, forget_on_drop=False):
        sent.append(line)
        return "ok"

    m.cmd = fake
    m.sent = sent
    return m


def test_known_position_does_not_go_home(tmp_path, monkeypatch):
    m = _mouse(tmp_path, monkeypatch)
    m.last = (0.20, 0.30)
    m._correct_to = lambda fx, fy: None
    m.goto(0.25, 0.32)
    assert not any(line == "home" for line in m.sent)
    assert any(line.startswith("move ") for line in m.sent)
    assert m.last == (0.25, 0.32)
    assert M.POINTER_FILE.read_text(encoding="utf-8")


def test_unknown_position_starts_from_the_corner(tmp_path, monkeypatch):
    m = _mouse(tmp_path, monkeypatch)
    m.last = None
    m._correct_to = lambda fx, fy: None
    m.goto(0.40, 0.50)
    assert m.sent[0] == "home"
    assert any(line.startswith("move ") for line in m.sent)


def test_position_is_reloaded(tmp_path, monkeypatch):
    m = _mouse(tmp_path, monkeypatch)
    m.last = (0.41, 0.62)
    m._save_pos()
    again = M.PhoneMouse()
    assert again.last == (0.41, 0.62)


def test_corrects_a_miss_without_homing(tmp_path, monkeypatch):
    m = _mouse(tmp_path, monkeypatch)
    m.last = (0.50, 0.50)
    m._grab_phone = lambda: None
    m._see = lambda near, nudge, grab, radius=0.12: (near[0] - 0.04, near[1])
    m._correct_to(0.50, 0.50)
    assert not any(line == "home" for line in m.sent)
    assert any(line.startswith("move ") for line in m.sent)
    assert m.last == (0.50, 0.50)


def test_lost_pointer_homes_once(tmp_path, monkeypatch):
    m = _mouse(tmp_path, monkeypatch)
    m.last = (0.20, 0.20)
    m._grab_phone = lambda: None
    calls = {"n": 0}

    def see(near, nudge, grab, radius=0.12):
        calls["n"] += 1
        if calls["n"] == 1:
            return None
        return near

    m._see = see
    m._correct_to(0.70, 0.70)
    assert m.sent.count("home") == 1
    assert m.last == (0.70, 0.70)
