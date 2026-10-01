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


# ---------------------------------------------------------------- 副屏全屏：桌面坐标 → 画面坐标

def _monitors(*screens):
    """get_monitors 的返回格式：第 0 项是所有屏幕的汇总，其后是各屏幕"""
    return [{"left": 0, "top": 0, "width": 0, "height": 0}] + [
        {"left": l, "top": t, "width": w, "height": h} for l, t, w, h in screens
    ]


@pytest.mark.parametrize("screens, region, frame, expected", [
    # 主屏全屏：偏移为 0，区域坐标即画面坐标
    ([(0, 0, 200, 100), (200, 0, 200, 100)], (10, 5, 30, 4), (200, 100), (10, 5)),
    # 游戏全屏在右侧副屏：画面是副屏的内容，要减去副屏偏移
    ([(0, 0, 200, 100), (200, 0, 200, 100)], (250, 5, 30, 4), (200, 100), (50, 5)),
    # 游戏全屏在左侧副屏（坐标为负）
    ([(0, 0, 200, 100), (-200, 0, 200, 100)], (-150, 5, 30, 4), (200, 100), (50, 5)),
    # 窗口化：画面尺寸与屏幕不一致，无法得知窗口位置，保持原有行为
    ([(0, 0, 200, 100), (200, 0, 200, 100)], (250, 5, 30, 4), (180, 90), (250, 5)),
])
def test_region_origin_on_fullscreen_monitor(monkeypatch, screens, region, frame, expected):
    import src.detector.utils as utils
    monkeypatch.setattr(utils, "get_monitors", lambda: _monitors(*screens))
    assert utils._resolve_region_origin(region, frame) == expected


def test_grab_region_fullscreen_on_secondary_monitor(monkeypatch):
    import src.detector.utils as utils
    monkeypatch.setattr(utils, "get_monitors", lambda: _monitors((0, 0, 200, 100), (200, 0, 200, 100)))
    img = utils.grab_region(FrameEngine((200, 100)), (210, 5, 30, 4))
    assert img.size == (30, 4)
    assert img.getpixel((0, 0)) == (10, 1, 2)  # 画面里 x=10 的像素


# ---------------------------------------------------------------- 预设名称

@pytest.mark.parametrize("name", ["我的预设", "preset 1", "a.b", "CONSOLE", "COM10", "x" * 200])
def test_preset_name_valid(name):
    from src.ui.settings import is_valid_preset_name
    assert is_valid_preset_name(name)


@pytest.mark.parametrize("name", [
    "", "   ", "a/b", "a\\b", "a:b", "a*b", 'a"b', "a|b", "a\tb", "x" * 201,
    "CON", "con", "NUL", "Aux", "PRN", "COM1", "LPT9", "com3.backup", "CON .x",
    "name.", "name ", "...",
])
def test_preset_name_invalid(name):
    from src.ui.settings import is_valid_preset_name
    assert not is_valid_preset_name(name)


# ---------------------------------------------------------------- 悬浮窗水平居中（副屏）

def test_overlay_set_x_to_center_uses_screen_offset(qapp, monkeypatch):
    from types import SimpleNamespace

    from PyQt6.QtCore import QRect

    from src.ui.overlay import OverlayUIState, OverlayWidget

    overlay = OverlayWidget()
    secondary = SimpleNamespace(geometry=lambda: QRect(1920, 0, 1000, 600))
    monkeypatch.setattr(overlay, "screen", lambda: secondary)
    overlay.move(2000, 40)
    overlay.update_ui_state(OverlayUIState(set_x_to_center=True))
    assert overlay.x() == 1920 + (1000 - overlay.width()) // 2
    assert overlay.y() == 40


# ---------------------------------------------------------------- native 二进制校验

def _load_verify_native():
    spec = importlib.util.spec_from_file_location(
        "verify_native", Path(__file__).parent.parent / "scripts" / "verify_native.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_repo_native_binaries_match_manifest():
    vn = _load_verify_native()
    assert vn.verify(vn.NATIVE_DIR) == []


def test_verify_native_detects_tampering(tmp_path):
    vn = _load_verify_native()
    (tmp_path / "a.dll").write_bytes(b"original")
    assert vn.main(["--dir", str(tmp_path), "--update"]) == 0
    assert vn.verify(tmp_path) == []

    (tmp_path / "a.dll").write_bytes(b"tampered")
    assert any("mismatch" in p for p in vn.verify(tmp_path))

    (tmp_path / "a.dll").write_bytes(b"original")
    (tmp_path / "b.dll").write_bytes(b"new, unlisted")
    assert any("b.dll" in p and "not listed" in p for p in vn.verify(tmp_path))

    (tmp_path / "b.dll").unlink()
    (tmp_path / "a.dll").unlink()
    assert any("missing" in p for p in vn.verify(tmp_path))


def test_verify_native_requires_manifest(tmp_path):
    vn = _load_verify_native()
    (tmp_path / "a.dll").write_bytes(b"x")
    assert vn.main(["--dir", str(tmp_path)]) == 1


def test_verify_native_accepts_crlf_manifest(tmp_path):
    vn = _load_verify_native()
    (tmp_path / "a.dll").write_bytes(b"x")
    digest = vn.sha256_of(tmp_path / "a.dll")
    (tmp_path / "SHA256SUMS").write_bytes(f"{digest}  a.dll\r\n".encode())
    assert vn.verify(tmp_path) == []
