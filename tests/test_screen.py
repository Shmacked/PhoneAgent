"""Window matching. No display required."""
import phone_remote.screen as screen


WMCTRL = """
0x0460000b  0 100 40 390 844 desk UxPlay
0x0460000c  0 10 10 800 600 desk Some other window
0x0460000d  0 -12000 -12000 100 100 desk Hidden UxPlay
"""


def test_parse_wmctrl_keeps_titles_with_spaces():
    found = screen.parse_wmctrl(WMCTRL)
    titles = [item.title for item in found]
    assert titles == ["UxPlay", "Some other window", "Hidden UxPlay"]
    assert found[0].left == 100 and found[0].width == 390 and found[0].height == 844
    assert found[2].isMinimized


def test_find_mirror_falls_through_to_uxplay(monkeypatch):
    monkeypatch.setattr(
        screen,
        "_all_windows",
        lambda: screen.parse_wmctrl(WMCTRL),
    )
    monkeypatch.setattr(
        screen,
        "load_config",
        lambda: {"mirror_title": "Direct3D12 Renderer", "airplay_name": "PhoneAgent"},
    )
    region = screen.find_mirror("Direct3D12 Renderer")
    assert (region.left, region.top, region.width, region.height) == (100, 40, 390, 844)
