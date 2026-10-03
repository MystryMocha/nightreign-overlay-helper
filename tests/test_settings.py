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
        updater = updater_module.Updater(*(MagicMock() for _ in range(6)))
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


def test_weapon_info_defaults(make_window):
    window, updater = make_window()
    assert updater.weapon_detect_enabled is False and updater.weapon_region is None
    assert window.weapon_position_combobox.currentText() == "词条下方"
    assert window.weapon_font_scale_slider.value() == 100


def test_weapon_info_settings_are_applied_and_saved(make_window):
    window, updater = make_window(yaml.safe_dump({
        "weapon_detect_enabled": True,
        "weapon_region": [10, 20, 300, 200],
        "weapon_position": "词条右侧",
        "weapon_font_scale": 130,
    }))
    assert updater.weapon_detect_enabled is True
    assert updater.weapon_region == [10, 20, 300, 200]
    states = []
    updater.weapon_overlay_ui_state_signal.connect(states.append)
    window.weapon_position_combobox.setCurrentText("词条下方")
    window.weapon_font_scale_slider.setValue(80)
    assert [s.position for s in states if s.position] == ["below"]
    assert [s.font_scale for s in states if s.font_scale] == [0.8]

    window.save_settings()
    with open(make_window.path, encoding="utf-8") as f:
        saved = yaml.safe_load(f)
    assert saved["weapon_detect_enabled"] is True
    assert saved["weapon_region"] == [10, 20, 300, 200]
    assert saved["weapon_position"] == "词条下方" and saved["weapon_font_scale"] == 80


def test_invalid_weapon_settings_are_ignored(make_window):
    window, updater = make_window(yaml.safe_dump({
        "weapon_region": [1, 2, "a", 4], "weapon_font_scale": "huge", "weapon_position": "somewhere",
        "hpbar_region": [1, 2, 3, 4],
    }))
    assert updater.weapon_region is None
    assert window.weapon_font_scale_slider.value() == 100
    assert window.weapon_position_combobox.currentText() == "词条下方"
    assert updater.hpbar_region == [1, 2, 3, 4]         # 排在后面的设置不受影响
    assert not os.path.exists(make_window.path + ".load_failed.bak")


def test_clearing_weapon_region_updates_updater(make_window):
    window, updater = make_window(yaml.safe_dump({"weapon_region": [10, 20, 300, 200]}))
    window.clear_weapon_region()
    assert updater.weapon_region is None and not window.clear_weapon_region_button.isEnabled()


def test_weapon_ocr_error_is_reported_in_settings(make_window):
    window, updater = make_window(yaml.safe_dump({"weapon_detect_enabled": True, "weapon_region": [1, 2, 3, 4]}))
    updater.weapon_status_signal.emit("ImportError: boom")
    assert "ImportError: boom" in window.weapon_status_label.text()
    assert "识别组件不可用" in window.status_labels[4].text()
    updater.weapon_status_signal.emit("")
    assert window.weapon_status_label.text() == ""
    assert "识别组件不可用" not in window.status_labels[4].text()


def test_relic_affix_defaults(make_window):
    window, updater = make_window()
    assert updater.relic_detect_enabled is False and updater.relic_region is None
    assert window.relic_position_combobox.currentText() == "词条下方"
    assert window.relic_font_scale_slider.value() == 100


def test_relic_affix_settings_are_applied_and_saved(make_window):
    window, updater = make_window(yaml.safe_dump({
        "relic_detect_enabled": True,
        "relic_region": [10, 20, 300, 200],
        "relic_position": "词条右侧",
        "relic_font_scale": 130,
    }))
    assert updater.relic_detect_enabled is True
    assert updater.relic_region == [10, 20, 300, 200]
    states = []
    updater.relic_overlay_ui_state_signal.connect(states.append)
    window.relic_position_combobox.setCurrentText("词条下方")
    window.relic_font_scale_slider.setValue(80)
    assert [s.position for s in states if s.position] == ["below"]
    assert [s.font_scale for s in states if s.font_scale] == [0.8]

    window.save_settings()
    with open(make_window.path, encoding="utf-8") as f:
        saved = yaml.safe_load(f)
    assert saved["relic_detect_enabled"] is True
    assert saved["relic_region"] == [10, 20, 300, 200]
    assert saved["relic_position"] == "词条下方" and saved["relic_font_scale"] == 80


def test_relic_and_weapon_settings_are_independent(make_window):
    window, updater = make_window(yaml.safe_dump({
        "weapon_detect_enabled": True, "weapon_region": [1, 2, 3, 4], "weapon_font_scale": 150,
        "relic_detect_enabled": False, "relic_region": [5, 6, 7, 8], "relic_font_scale": 70,
    }))
    assert updater.weapon_detect_enabled is True and updater.relic_detect_enabled is False
    assert updater.weapon_region == [1, 2, 3, 4] and updater.relic_region == [5, 6, 7, 8]
    weapon_states, relic_states = [], []
    updater.weapon_overlay_ui_state_signal.connect(weapon_states.append)
    updater.relic_overlay_ui_state_signal.connect(relic_states.append)
    window.relic_font_scale_slider.setValue(90)
    assert [s.font_scale for s in relic_states if s.font_scale] == [0.9] and not weapon_states
    window.weapon_font_scale_slider.setValue(110)
    assert [s.font_scale for s in weapon_states if s.font_scale] == [1.1]
    assert [s.font_scale for s in relic_states if s.font_scale] == [0.9]


def test_invalid_relic_settings_are_ignored(make_window):
    window, updater = make_window(yaml.safe_dump({
        "relic_region": [1, 2, "a", 4], "relic_font_scale": "huge", "relic_position": "somewhere",
        "hpbar_region": [1, 2, 3, 4],
    }))
    assert updater.relic_region is None
    assert window.relic_font_scale_slider.value() == 100
    assert window.relic_position_combobox.currentText() == "词条下方"
    assert updater.hpbar_region == [1, 2, 3, 4]         # 排在后面的设置不受影响
    assert not os.path.exists(make_window.path + ".load_failed.bak")


def test_clearing_relic_region_updates_updater(make_window):
    window, updater = make_window(yaml.safe_dump({"relic_region": [10, 20, 300, 200]}))
    window.clear_relic_region()
    assert updater.relic_region is None and not window.clear_relic_region_button.isEnabled()


def test_relic_ocr_error_is_reported_in_settings(make_window):
    window, updater = make_window(yaml.safe_dump({"relic_detect_enabled": True, "relic_region": [1, 2, 3, 4]}))
    relic_label = next(label for label in window.status_labels if "遗物词条" in label.text())
    assert "就绪" in relic_label.text()
    updater.relic_status_signal.emit("ImportError: boom")
    assert "ImportError: boom" in window.relic_status_label.text()
    assert "识别组件不可用" in relic_label.text()
    assert window.weapon_status_label.text() == ""      # 武器信息的状态不受影响
    updater.relic_status_signal.emit("")
    assert window.relic_status_label.text() == ""
    assert "识别组件不可用" not in relic_label.text()


def test_relic_hotkeys_are_registered_for_conflict_detection(make_window):
    window, _ = make_window()
    names = [name for name, _ in window.hotkey_widgets]
    assert "框选遗物区域" in names and "显示/隐藏遗物数值" in names
    assert len(names) == len(set(names))

