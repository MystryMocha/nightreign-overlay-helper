import os
from unittest.mock import MagicMock

import pytest
import yaml

import src.updater as updater_module


@pytest.fixture
def make_window(qapp, monkeypatch):
    import src.ui.settings as settings_module
    from src.ui.input import InputWorker
    from src.ui.map_overlay import MapOverlayWidget
    from src.ui.overlay import OverlayWidget
    from src.ui.settings import SETTINGS_SAVE_PATH, SettingsWindow

    monkeypatch.setattr(updater_module, "DetectorManager", lambda engine: MagicMock())
    for path in (SETTINGS_SAVE_PATH, SETTINGS_SAVE_PATH + ".bak", SETTINGS_SAVE_PATH + ".load_failed.bak"):
        if os.path.exists(path):
            os.remove(path)
    windows = []

    def make(settings_text: str | None = None):
        if settings_text is not None:
            with open(SETTINGS_SAVE_PATH, "w", encoding="utf-8") as f:
                f.write(settings_text)
        updater = updater_module.Updater(MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock())
        window = SettingsWindow(OverlayWidget(), MapOverlayWidget(), updater, InputWorker())
        windows.append(window)
        return window, updater

    make.module = settings_module
    make.path = SETTINGS_SAVE_PATH
    yield make
    for w in windows:
        w.save_timer.stop()


def test_default_detect_interval_is_applied_to_updater(make_window):
    # 界面默认显示"高"(0.1s)，更新线程不能还停留在构造函数里的 0.2s
    window, updater = make_window()
    assert window.detect_interval_combobox.currentText() == "高"
    assert updater.detect_interval == 0.1


def test_saved_combobox_values_are_applied(make_window):
    window, updater = make_window(yaml.safe_dump({"detect_interval": "低", "map_pattern_return_topk": 8}))
    assert updater.detect_interval == 0.5
    assert updater.map_pattern_return_topk == 8


def test_unknown_saved_language_falls_back(make_window):
    window, updater = make_window(yaml.safe_dump({"dayx_detect_lang": "klingon"}))
    assert updater.dayx_detect_lang == "chs" or window.dayx_detect_lang == "chs"


def test_off_screen_map_region_does_not_abort_loading(make_window):
    window, updater = make_window(yaml.safe_dump({
        "map_region": [99999, 99999, 300, 300],
        "hpbar_region": [10, 20, 30, 40],
        "art_region": [1, 2, 3, 4],
        "debug_log_enabled": False,
        "crystal_auto_detect_enabled": False,
    }))
    assert updater.map_region is not None
    assert updater.hpbar_region == [10, 20, 30, 40]            # 排在地图区域之后的设置也必须加载成功
    assert updater.art_region == [1, 2, 3, 4]
    assert updater.crystal_auto_detect_enabled is False
    assert not os.path.exists(make_window.path + ".load_failed.bak")


def test_invalid_region_values_are_ignored(make_window):
    window, updater = make_window(yaml.safe_dump({"hpbar_region": "oops", "art_region": [1, 2], "map_region": [1, 2, "a", 4]}))
    assert updater.hpbar_region is None and updater.art_region is None and updater.map_region is None


def test_corrupt_settings_file_is_backed_up(make_window):
    window, updater = make_window("hpbar_region: [1, 2\n")
    backup = make_window.path + ".load_failed.bak"
    assert os.path.exists(backup)
    with open(backup, encoding="utf-8") as f:
        assert "hpbar_region" in f.read()
    assert updater.hpbar_region is None


def test_corrupt_preset_is_rolled_back_without_success_message(make_window, monkeypatch):
    module = make_window.module
    window, updater = make_window(yaml.safe_dump({"hpbar_region": [1, 2, 3, 4]}))
    os.makedirs(module.PRESET_SETTINGS_DIR, exist_ok=True)
    with open(os.path.join(module.PRESET_SETTINGS_DIR, "bad.yaml"), "w", encoding="utf-8") as f:
        f.write("hpbar_region: [9, 9\n")
    messages = {"info": [], "error": []}
    monkeypatch.setattr(module, "comfirm_box", lambda *a, **k: True)
    monkeypatch.setattr(module, "info_box", lambda msg, *a, **k: messages["info"].append(msg))
    monkeypatch.setattr(module, "error_box", lambda msg, *a, **k: messages["error"].append(msg))

    window.load_preset("bad")

    assert messages["info"] == [] and len(messages["error"]) == 1
    assert updater.hpbar_region == [1, 2, 3, 4]
    with open(make_window.path, encoding="utf-8") as f:
        assert yaml.safe_load(f)["hpbar_region"] == [1, 2, 3, 4]


def test_valid_preset_is_loaded(make_window, monkeypatch):
    module = make_window.module
    window, updater = make_window(yaml.safe_dump({"hpbar_region": [1, 2, 3, 4]}))
    os.makedirs(module.PRESET_SETTINGS_DIR, exist_ok=True)
    with open(os.path.join(module.PRESET_SETTINGS_DIR, "good.yaml"), "w", encoding="utf-8") as f:
        yaml.safe_dump({"hpbar_region": [5, 6, 7, 8]}, f)
    messages = []
    monkeypatch.setattr(module, "comfirm_box", lambda *a, **k: True)
    monkeypatch.setattr(module, "info_box", lambda msg, *a, **k: messages.append(msg))
    monkeypatch.setattr(module, "error_box", lambda *a, **k: pytest.fail("unexpected error box"))
    window.load_preset("good")
    assert updater.hpbar_region == [5, 6, 7, 8]
    assert len(messages) == 1


def test_topk_handler_ignores_empty_text(make_window):
    window, updater = make_window()
    updater.map_pattern_return_topk = 5
    window.update_map_pattern_return_topk("")
    assert updater.map_pattern_return_topk == 5


def test_app_user_model_id_has_no_version(make_window, monkeypatch):
    """带版本号的 AppUserModelID 会让已固定到任务栏的快捷方式在升级后分裂成两个图标"""
    import ctypes
    from types import SimpleNamespace

    from src.common import APP_NAME

    seen = []
    fake_windll = SimpleNamespace(shell32=SimpleNamespace(SetCurrentProcessExplicitAppUserModelID=seen.append))
    monkeypatch.setattr(ctypes, "windll", fake_windll, raising=False)
    make_window()
    assert seen == [APP_NAME]
