"""
遗物词条数值检测的端到端测试：用项目自带字体渲染一张模拟的遗物仪式界面，经真实的截图→OCR→折行合并→匹配流程得到标注
需要 rapidocr（程序运行本来就依赖它），未安装时跳过
"""
import os
import sys
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

pytest.importorskip("rapidocr")
pytest.importorskip("cv2")
from PIL import Image, ImageDraw, ImageFont

from src.detector.relic_detector import RelicDetector
from src.detector.weapon_detector import WeaponDetectParam, WeaponDetector
from src.weapon.annotate import NO_DATA_TEXT
from src.weapon.ocr import get_shared_ocr

FRAME_SIZE = (1920, 1080)
REGION = (1200, 300, 640, 420)      # 描述栏所在区域 (x, y, w, h)，屏幕坐标
FONT_PATH = os.path.join(ROOT, "data", "fonts", "SourceHanSansSC-Normal.otf")

# 描述栏里的文字：(屏幕坐标 x, y, 字号, 文字)。较长的词条名折成了紧挨着的两行
PANEL_LINES = [
    (1230, 330, 32, "单眼镜的皮革袋"),
    (1230, 400, 26, "【送葬者】使用祷告将辅助效果附加在自己身上时"),
    (1230, 431, 26, "提升物理攻击力"),
    (1230, 500, 26, "延长魔法、祷告的有效时间"),
    (1230, 570, 26, "提升物理攻击力＋２"),
    (1230, 640, 26, "集中力＋３"),
]


@pytest.fixture(autouse=True)
def repo_cwd(monkeypatch):
    monkeypatch.chdir(ROOT)


class FakeEngine:
    def __init__(self, frame: Image.Image):
        self.frame = frame

    def grab_fullscreen(self) -> Image.Image:
        return self.frame


def render_frame(lines=PANEL_LINES) -> Image.Image:
    img = Image.new("RGB", FRAME_SIZE, (30, 34, 48))     # 模拟遗物仪式界面的深色背景
    draw = ImageDraw.Draw(img)
    x, y, w, h = REGION
    draw.rectangle((x, y, x + w, y + h), fill=(22, 20, 26))
    for lx, ly, size, text in lines:
        draw.text((lx, ly), text, font=ImageFont.truetype(FONT_PATH, size), fill=(225, 215, 190))
    return img


def wait_for_result(detector, engine, param, timeout=60.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = detector.detect(engine, param)
        if result.updated:
            return result
        time.sleep(0.1)
    pytest.fail("等待 OCR 结果超时")


@pytest.fixture
def detector():
    d = RelicDetector()
    yield d
    d.stop()


def test_detects_relic_affixes_including_wrapped_name(detector):
    result = wait_for_result(detector, FakeEngine(render_frame()), WeaponDetectParam(region=REGION))

    by_name = {a.name: a for a in result.annotations}
    assert set(by_name) == {
        "【送葬者】使用祷告将辅助效果附加在自己身上时 提升物理攻击力", "延长魔法、祷告的有效时间",
        "提升物理攻击力＋２", "集中力＋３",
    }, [(a.name, a.text) for a in result.annotations]
    assert by_name["【送葬者】使用祷告将辅助效果附加在自己身上时 提升物理攻击力"].text == "物理攻击力+19%，持续60秒"
    assert by_name["延长魔法、祷告的有效时间"].text == "延长50%，向下取整"
    assert by_name["提升物理攻击力＋２"].text == "物理攻击力 +6%"
    assert by_name["集中力＋３"].text == "+3点集中力（固定+15点专注值上限）"
    assert not any(a.dim for a in result.annotations)

    # 折行的词条标注在两行文字合起来的位置上，字号参照单行高度
    wrapped = by_name["【送葬者】使用祷告将辅助效果附加在自己身上时 提升物理攻击力"]
    x, y, w, h = wrapped.box
    assert abs(x - 1230) < 26 and abs(y - 400) < 26 and h > 26 * 1.6
    assert 0 < wrapped.line_height < h
    # 标题等其他文字不会被标注，但都作为避让区域返回
    assert len(result.line_boxes) == len(PANEL_LINES)
    assert not result.stale


def test_switching_relic_hides_old_values_immediately(detector):
    param = WeaponDetectParam(region=REGION)
    first = wait_for_result(detector, FakeEngine(render_frame()), param)
    assert "提升物理攻击力＋２" in {a.name for a in first.annotations}

    # 换了一件遗物：这一行词条变成了另一条，旧的数值不能留在新文字旁边
    other = [(x, y, size, "提升火属性攻击力＋１" if text == "提升物理攻击力＋２" else text) for x, y, size, text in PANEL_LINES]
    engine = FakeEngine(render_frame(lines=other))
    assert detector.detect(engine, param).stale

    result = wait_for_result(detector, engine, param)
    names = {a.name for a in result.annotations}
    assert "提升火属性攻击力＋１" in names and "提升物理攻击力＋２" not in names
    assert not result.stale


def test_clearing_region_clears_overlay_once(detector):
    engine = FakeEngine(render_frame())
    wait_for_result(detector, engine, WeaponDetectParam(region=REGION))
    assert detector.detect(engine, WeaponDetectParam(region=None)).updated
    assert not detector.detect(engine, WeaponDetectParam(region=None)).updated


def test_relic_and_weapon_detectors_use_their_own_data():
    # 同名词条在武器和遗物上的数值不同：同一张画面交给两个检测器，各自查各自的表
    frame = render_frame([(1230, 400, 26, "延长魔法、祷告的有效时间")])
    engine, param = FakeEngine(frame), WeaponDetectParam(region=REGION)
    relic, weapon = RelicDetector(), WeaponDetector()
    try:
        relic_result = wait_for_result(relic, engine, param)
        weapon_result = wait_for_result(weapon, engine, param)
    finally:
        relic.stop()
        weapon.stop()
    assert [a.text for a in relic_result.annotations] == ["延长50%，向下取整"]
    assert [a.text for a in weapon_result.annotations] == [NO_DATA_TEXT]
    # 两个检测器共用同一个 OCR 引擎，不重复加载模型
    assert relic.ocr is weapon.ocr is get_shared_ocr()


def test_none_params_is_a_noop(detector):
    assert not detector.detect(FakeEngine(render_frame()), None).updated


def test_detector_manager_routes_relic_param_to_relic_detector():
    from src.detector import DetectorManager, DetectParam

    manager = DetectorManager(FakeEngine(render_frame()))
    try:
        param = DetectParam(relic_detect_param=WeaponDetectParam(region=REGION))
        deadline = time.time() + 60
        result = manager.detect(param)
        while not result.relic_detect_result.updated and time.time() < deadline:
            time.sleep(0.1)
            result = manager.detect(param)
        assert "集中力＋３" in {a.name for a in result.relic_detect_result.annotations}
        # 武器信息没有收到参数，保持不动
        assert not result.weapon_detect_result.updated and result.weapon_detect_result.annotations == []
    finally:
        manager.relic_detector.stop()
        manager.weapon_detector.stop()

