import importlib.util
import sys
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from src.screencap import ScreencapRuntimeError


# ---------------------------------------------------------------- grab_region

class FrameEngine:
    def __init__(self, size=(200, 100)):
        self.frame = Image.new("RGB", size, (0, 0, 0))
        for x in range(size[0]):
            self.frame.putpixel((x, 5), (x % 256, 1, 2))

    def grab_fullscreen(self):
        return self.frame


@pytest.fixture
def no_monitors(monkeypatch):
    import src.detector.utils as utils
    monkeypatch.setattr(utils, "get_monitors", lambda: [])
    return utils


def test_grab_region_crops_requested_area(no_monitors):
    img = no_monitors.grab_region(FrameEngine(), (10, 5, 30, 4))
    assert img.size == (30, 4)
    assert img.getpixel((0, 0)) == (10, 1, 2)
    assert img.getpixel((29, 0)) == (39, 1, 2)


@pytest.mark.parametrize("region", [(190, 0, 20, 10), (0, 95, 10, 10), (-1, 0, 10, 10), (0, -3, 10, 10)])
def test_grab_region_out_of_frame_raises_capture_error(no_monitors, region):
    with pytest.raises(ScreencapRuntimeError):
        no_monitors.grab_region(FrameEngine(), region)


def test_grab_region_invalid_size(no_monitors):
    with pytest.raises(ValueError):
        no_monitors.grab_region(FrameEngine(), (0, 0, 0, 5))


def test_grab_region_does_not_copy_whole_frame(no_monitors, monkeypatch):
    import numpy as np
    sizes = []
    original = np.array
    monkeypatch.setattr(np, "array", lambda obj, *a, **k: (sizes.append(getattr(obj, "size", None)), original(obj, *a, **k))[1])
    no_monitors.grab_region(FrameEngine((4000, 2000)), (10, 10, 50, 20))
    assert all(s != (4000, 2000) for s in sizes)


# ---------------------------------------------------------------- 水晶布局 / 地图工具函数

def test_crystal_layout_matching():
    from src.detector.crystal_info import load_crystal_info
    info = load_crystal_info()
    layouts = info.layouts
    assert len(layouts) > 1
    target = layouts[1]
    assert info.match_layouts(set(target.initial[:3])) != []
    assert info.match_layouts(set()) == []
    # 布局 1 的水晶全部被识别到时，布局 1 一定在候选里
    assert 1 in info.match_layouts(target.all)


def test_map_prefix_helpers():
    from src.detector.map_detector import has_same_base_icon, match_prefix
    assert match_prefix(32101, 32)
    assert match_prefix(32101, 321)
    assert not match_prefix(32101, 33)
    assert match_prefix(0, 0) and not match_prefix(30, 0)
    assert has_same_base_icon(32101, 32200)
    assert not has_same_base_icon(30301, 32101)


# ---------------------------------------------------------------- 单实例

def test_single_instance_guard():
    from src.single_instance import acquire_single_instance
    name = f"Local\\nroh-test-{id(object())}"
    assert acquire_single_instance(name) is True
    if sys.platform == "win32":
        assert acquire_single_instance(name) is False


# ---------------------------------------------------------------- BUG 反馈打包范围

def test_bug_report_zip_contains_only_log_dir(qapp, tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox
    from src.ui.bug_report import BugReportWindow

    appdata = tmp_path / "appdata"
    logs = appdata / "logs"
    (logs / "debug").mkdir(parents=True)
    (logs / "2026-01-01.log").write_text("log")
    (logs / "debug" / "map.jpg").write_bytes(b"jpg")
    (appdata / "settings.yaml").write_text("hotkeys")
    (appdata / "detect_region_screenshot.jpg").write_bytes(b"whole desktop")

    monkeypatch.setattr(QMessageBox, "exec", lambda self: 0)
    window = BugReportWindow(str(logs), str(tmp_path / "export"), "dev@example.com")
    monkeypatch.setattr(window, "open_file_location", lambda path: None)
    window.feedback_text.setPlainText("it broke")
    window.create_zip_package()

    zips = list((tmp_path / "export").glob("*.zip"))
    assert len(zips) == 1
    names = {n.replace("\\", "/") for n in zipfile.ZipFile(zips[0]).namelist()}
    assert "logs/2026-01-01.log" in names and "logs/debug/map.jpg" in names
    assert not any("settings.yaml" in n or "screenshot" in n for n in names)


# ---------------------------------------------------------------- CI 版本脚本

def _load_ci_version():
    spec = importlib.util.spec_from_file_location("ci_version", Path(__file__).parent.parent / "scripts" / "ci_version.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("tag, expected", [
    ("v1.2.3", ("1.2.3", False)),
    ("refs/tags/v1.2.3", ("1.2.3", False)),
    ("v1.2.3-rc.1", ("1.2.3rc1", True)),
    ("v0.10.8-dev.1", ("0.10.8.dev1", True)),
    ("v2.0-beta2", ("2.0b2", True)),
])
def test_tag_to_pep440(tag, expected):
    assert _load_ci_version().tag_to_pep440(tag) == expected


@pytest.mark.parametrize("tag", ["1.2.3", "v", "v1.2.x", "v1.2.3-nightly", 'v1.0$(calc)'])
def test_tag_to_pep440_rejects_bad_tags(tag):
    module = _load_ci_version()
    with pytest.raises(module.VersionError):
        module.tag_to_pep440(tag)
