import pytest

from src.ui.input import InputSetting, InputWorker, format_combo


def test_format_combo_keeps_lock_keys_intact():
    text = format_combo("keyboard", ("caps_lock", "ctrl_l", "num_lock", "shift_r", "scroll_lock"))
    assert "CAPS_LOCK" in text and "NUM_LOCK" in text and "SCROLL_LOCK" in text
    assert "CTRL" in text and "CTRL_L" not in text and "SHIFT_R" not in text


def test_input_setting_load_from_dict_is_tolerant():
    assert InputSetting.load_from_dict(None) == InputSetting()
    assert InputSetting.load_from_dict("garbage") == InputSetting()
    assert InputSetting.load_from_dict({"type": "keyboard", "combo": ["a", "b"]}) == InputSetting("keyboard", ("a", "b"))
    assert InputSetting.load_from_dict({"type": "keyboard", "combo": "ab"}).combo == ()


@pytest.mark.parametrize("hat, expected", [
    ((0, 0), set()),
    ((1, 0), {InputWorker.HAT_RIGHT}),
    ((-1, 0), {InputWorker.HAT_LEFT}),
    ((0, 1), {InputWorker.HAT_UP}),
    ((0, -1), {InputWorker.HAT_DOWN}),
    ((1, 1), {InputWorker.HAT_RIGHT, InputWorker.HAT_UP}),
    ((-1, -1), {InputWorker.HAT_LEFT, InputWorker.HAT_DOWN}),
])
def test_hat_value_to_buttons(hat, expected):
    assert InputWorker.hat_value_to_buttons(hat) == expected


def _collect(worker):
    combos = []
    worker.joystick_combo_pressed.connect(combos.append)
    worker.key_combo_pressed.connect(combos.append)
    return combos


def test_hat_direction_change_releases_previous_direction(qapp):
    worker = InputWorker()
    combos = _collect(worker)
    worker._update_hat(0, (1, 0))
    worker._update_hat(0, (0, 1))       # 直接从右切到上，右必须被释放
    assert [p.identifier for p in worker.pressing_joystick_buttons[0]] == [InputWorker.HAT_UP]
    worker._update_hat(0, (0, 0))
    assert worker.pressing_joystick_buttons[0] == []
    assert combos == [(InputWorker.HAT_RIGHT,), (InputWorker.HAT_UP,)]


def test_signals_blocked_flag_suppresses_emit_but_tracks_state(qapp):
    worker = InputWorker()
    combos = _collect(worker)
    worker.set_signals_blocked(True)
    worker._press("keyboard", "a")
    assert combos == []
    assert [p.identifier for p in worker.pressing_keys] == ["a"]
    worker.set_signals_blocked(False)
    worker._press("keyboard", "b")
    assert combos == [("a", "b")]       # 解除阻止后，仍按着的键参与组合键判断


def test_debug_logs_do_not_contain_pressed_keys(qapp, appdata):
    import logging
    from src import logger
    logger.set_log_level(logging.DEBUG)
    try:
        worker = InputWorker()
        worker._press("keyboard", "zqxjk-secret")
        worker._release("keyboard", "zqxjk-secret")
        for h in logging.getLogger(logger.LOGGER_NAME).handlers:
            h.flush()
    finally:
        logger.set_log_level(logging.INFO)
    content = "".join(p.read_text(encoding="utf-8") for p in (appdata / "nightreign-overlay-helper" / "logs").glob("*.log"))
    assert "InputWorker: press" in content
    assert "zqxjk-secret" not in content


def test_dialog_disconnects_from_worker_on_accept_and_reject(qapp):
    from src.ui.input import InputSettingDialog
    worker = InputWorker()
    for finish in ("accept", "reject"):
        dialog = InputSettingDialog(worker)
        assert worker.receivers(worker.key_combo_pressed) >= 1
        getattr(dialog, finish)()
        assert not dialog._worker_connected
        dialog.deleteLater()
    qapp.processEvents()
    assert worker.receivers(worker.key_combo_pressed) == 0
    assert worker.receivers(worker.mousebutton_combo_pressed) == 0
    assert worker.receivers(worker.joystick_combo_pressed) == 0
