import time
from unittest.mock import MagicMock

import pytest

import src.updater as updater_module
from src.screencap import EngineStatus, ScreencapInitError, ScreencapRuntimeError
from src.ui.overlay import OverlayUIState
from src.updater import Phase, Updater


class FakeInput:
    def __init__(self):
        self.blocked = []

    def set_signals_blocked(self, blocked):
        self.blocked.append(blocked)


class FakeEngine:
    def __init__(self, init_error=None):
        self.status = EngineStatus.UNINITIALIZED
        self.init_error = init_error
        self.init_calls = 0

    def check_reconnect_reason(self):
        return None

    def initialize(self, mode):
        self.init_calls += 1
        if self.init_error is not None:
            self.status = EngineStatus.FAILED
            raise self.init_error
        self.status = EngineStatus.CONNECTED

    def shutdown(self):
        self.status = EngineStatus.SHUTDOWN


@pytest.fixture
def make_updater(qapp, monkeypatch):
    monkeypatch.setattr(updater_module, "DetectorManager", lambda engine: MagicMock())
    monkeypatch.setattr(updater_module, "is_window_in_foreground", lambda *a, **k: False)

    def make(engine):
        monkeypatch.setattr(updater_module, "get_engine", lambda: engine)
        fake_input = FakeInput()
        updater = Updater(fake_input, MagicMock(), MagicMock(), MagicMock(), MagicMock())
        updater.fake_input = fake_input
        updater.overlay_states = []
        updater.update_overlay_ui_state_signal.connect(updater.overlay_states.append)
        return updater
    return make


def test_progress_text_with_partial_state_does_not_raise(make_updater):
    updater = make_updater(FakeEngine())
    assert updater.get_phase_progress_text() == (0.0, None)
    # 模拟快捷键线程已经设置了 day，但阶段信息还没写完
    updater.day = 1
    assert updater.get_phase_progress_text() == (0.0, None)
    updater.current_phase = Phase.FIRST_CIRCLE_STABLE
    assert updater.get_phase_progress_text() == (0.0, None)


def test_start_day1_sets_day_last(make_updater):
    updater = make_updater(FakeEngine())
    seen = []
    original_get_time = updater.get_time

    def spy():
        seen.append(updater.day)         # 计算开始时间时 day 还不能被设置
        return original_get_time()
    updater.get_time = spy
    updater.start_day1()
    assert seen and all(day is None for day in seen)
    progress, text = updater.get_phase_progress_text()
    assert text.startswith("DAY I - ")


def test_timer_ui_keeps_updating_when_screencap_init_fails(make_updater):
    engine = FakeEngine(init_error=ScreencapInitError("connect_failed", "no game"))
    updater = make_updater(engine)
    updater.start_day1()
    updater.update_overlay_ui_state_signal.disconnect(updater.overlay_states.append)
    states: list[OverlayUIState] = []
    updater.update_overlay_ui_state_signal.connect(states.append)
    updater.run_once()
    assert engine.init_calls == 1
    assert any(s.day_text and s.day_text.startswith("DAY I") for s in states)


def test_run_survives_exceptions_in_an_iteration(make_updater, monkeypatch):
    updater = make_updater(FakeEngine())
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise RuntimeError("boom")
        updater.stop()
    monkeypatch.setattr(updater, "run_once", flaky)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    updater.run()
    assert len(calls) == 3


def test_capture_error_in_one_detector_does_not_stop_others(make_updater):
    updater = make_updater(FakeEngine())
    order = []

    def failing():
        order.append("dayx")
        raise ScreencapRuntimeError("grab_failed", "region outside frame")

    updater.detect_and_update_dayx = failing
    updater.detect_and_update_in_rain = lambda: order.append("rain")
    updater.detect_and_update_map = lambda: order.append("map")
    updater.detect_and_update_hp = lambda: order.append("hp")
    updater.detect_and_update_art = lambda: order.append("art")
    updater.detect_and_update_all()
    assert order == ["dayx", "rain", "map", "hp", "art"]


def test_repeated_failures_are_logged_at_most_once_per_interval(make_updater):
    updater = make_updater(FakeEngine())
    messages = []
    for _ in range(50):
        updater._log_throttled(messages.append, "k", "same failure", interval=60)
    assert messages == ["same failure"]


def test_foreground_check_blocks_input_directly(make_updater):
    updater = make_updater(FakeEngine())
    updater.only_detect_when_game_foreground = True
    updater.check_game_foreground()           # 游戏不在前台
    updater.is_menu_opened = True
    updater.check_game_foreground()           # 右键菜单打开时不阻止，菜单需要用到按键
    updater.only_detect_when_game_foreground = False
    updater.is_menu_opened = False
    updater.check_game_foreground()
    assert updater.fake_input.blocked == [True, False, False]


def test_hp_overlay_receives_foreground_only_option(make_updater):
    updater = make_updater(FakeEngine())
    states = []
    updater.hp_overlay_ui_state_signal.connect(states.append)
    updater.only_detect_when_game_foreground = True
    updater.check_game_foreground()
    assert states[-1].only_show_when_game_foreground is True
    assert states[-1].is_game_foreground is False


def test_map_pattern_failure_restores_overlay_and_schedules_retry(make_updater):
    updater = make_updater(FakeEngine())
    updater.manual_map_region = [0, 0, 100, 100]
    detect_results = iter([
        # 1) 全图检测
        MagicMock(map_detect_result=MagicMock(is_full_map=True, img=object())),
        # 2) 地形识别
        MagicMock(map_detect_result=MagicMock(earth_shifting=0)),
    ])

    def fake_detect(param):
        try:
            return next(detect_results)
        except StopIteration:
            raise RuntimeError("matching exploded")
    updater.detector.detect = fake_detect
    updater.do_match_map_pattern_flag = updater_module.DoMatchMapPatternFlag.TRUE
    updater.last_map_pattern_match_time = updater.get_time()
    updater.crystal_auto_detect_enabled = False
    updater.current_is_full_map = True      # 地图已打开一段时间，已完全淡入
    updater.full_map_opened_time = 0.0
    map_states = []
    updater.update_map_overlay_ui_state_signal.connect(map_states.append)
    updater.detect_and_update_map()
    assert updater.map_pattern_retry_on_next_open is True
    assert map_states[-1].map_pattern_matching is False     # 不能停在"正在识别中"



def test_map_pattern_waits_for_map_fade_in(make_updater):
    """刚打开地图的第一帧还是半透明的，不能用它识别种子，要等地图完全淡入"""
    updater = make_updater(FakeEngine())
    updater.manual_map_region = [0, 0, 100, 100]
    calls = []

    def fake_detect(param):
        calls.append(param.map_detect_param)
        return MagicMock(map_detect_result=MagicMock(is_full_map=True, img=object(), earth_shifting=None))
    updater.detector.detect = fake_detect
    updater.do_match_map_pattern_flag = updater_module.DoMatchMapPatternFlag.TRUE
    updater.last_map_pattern_match_time = updater.get_time()
    updater.crystal_auto_detect_enabled = False

    updater.detect_and_update_map()     # 地图刚打开
    assert len(calls) == 1              # 只做了全图检测，没有识别地形和种子
    assert updater.do_match_map_pattern_flag == updater_module.DoMatchMapPatternFlag.TRUE

    updater.full_map_opened_time -= 10  # 地图已打开足够久
    updater.detect_and_update_map()
    assert any(p.do_match_earth_shifting for p in calls[1:])

def make_weapon_result(updated=False, annotations=(), stale=False, ocr_error=None):
    return MagicMock(weapon_detect_result=MagicMock(
        updated=updated, annotations=list(annotations), line_boxes=[(0, 0, 10, 10)], stale=stale, ocr_error=ocr_error))


def test_weapon_detect_publishes_results_and_stale_state(make_updater):
    from src.weapon.annotate import WeaponAnnotation
    updater = make_updater(FakeEngine())
    updater.weapon_detect_enabled = True
    updater.weapon_region = [100, 200, 300, 400]
    states, statuses = [], []
    updater.weapon_overlay_ui_state_signal.connect(states.append)
    updater.weapon_status_signal.connect(statuses.append)

    ann = WeaponAnnotation("affix", "强化魔法", "伤害 +5%/+8%/+11%（档位1/2/3）", (110, 210, 100, 20))
    results = iter([
        make_weapon_result(updated=True, annotations=[ann]),    # 新识别结果
        make_weapon_result(stale=False),                        # 没变化：不应再发送
        make_weapon_result(stale=True),                         # 画面变了：隐藏旧标注
    ])
    updater.detector.detect = lambda param: next(results)

    updater.detect_and_update_weapon()
    assert len(states) == 1
    assert states[0].annotations == [ann] and states[0].region == (100, 200, 300, 400) and states[0].stale is False
    assert statuses == []                                       # 识别组件正常时不发错误

    updater.detect_and_update_weapon()
    assert len(states) == 1

    updater.detect_and_update_weapon()
    assert len(states) == 2 and states[1].stale is True and states[1].annotations is None


def test_weapon_detect_reports_ocr_error_once(make_updater):
    updater = make_updater(FakeEngine())
    updater.weapon_detect_enabled = True
    updater.weapon_region = [1, 2, 3, 4]
    statuses = []
    updater.weapon_status_signal.connect(statuses.append)
    updater.detector.detect = lambda param: make_weapon_result(updated=True, ocr_error="ImportError: boom")
    updater.detect_and_update_weapon()
    updater.detect_and_update_weapon()
    assert statuses == ["ImportError: boom"]


def test_disabled_weapon_detect_clears_overlay_and_ignores_own_text(make_updater):
    updater = make_updater(FakeEngine())
    updater.weapon_region = [1, 2, 3, 4]
    updater._weapon_own_texts = {"伤害 +5%"}
    states = []
    updater.weapon_overlay_ui_state_signal.connect(states.append)
    updater.detector.detect = lambda param: make_weapon_result(updated=True)   # 检测器通知“已清除”
    updater.detect_and_update_weapon()          # 未启用
    assert len(states) == 1 and states[0].annotations == [] and states[0].stale is False
    assert updater._weapon_own_texts == set()


def test_foreground_state_is_forwarded_to_weapon_overlay(make_updater):
    updater = make_updater(FakeEngine())
    states = []
    updater.weapon_overlay_ui_state_signal.connect(states.append)
    updater.check_game_foreground()
    assert states[-1].is_game_foreground is False


def test_stop_stops_weapon_ocr_worker(make_updater):
    updater = make_updater(FakeEngine())
    updater.stop()
    updater.detector.weapon_detector.stop.assert_called_once()
