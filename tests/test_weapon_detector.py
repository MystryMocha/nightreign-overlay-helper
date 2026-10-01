"""
武器信息检测的端到端测试：用项目自带字体渲染一张模拟的游戏画面，经真实的截图→OCR→匹配流程得到标注
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

from src.detector.weapon_detector import WeaponDetectParam, WeaponDetector

FRAME_SIZE = (1920, 1080)
REGION = (1200, 300, 640, 420)      # 面板区域 (x, y, w, h)，屏幕坐标
FONT_PATH = os.path.join(ROOT, "data", "fonts", "SourceHanSansSC-Normal.otf")

# 面板里的文字：(屏幕坐标 x, y, 字号, 文字)
PANEL_LINES = [
    (1230, 330, 34, "火焰匕首"),
    (1230, 420, 26, "提升魔力属性攻击力＋２"),
    (1230, 480, 26, "提升血量上限"),
    (1230, 540, 26, "强化致命一击"),
    (1230, 610, 22, "战技：盲击"),
]


@pytest.fixture(autouse=True)
def repo_cwd(monkeypatch):
    # Config / 数据文件都用相对路径，需要在仓库根目录运行
    monkeypatch.chdir(ROOT)


class FakeEngine:
    def __init__(self, frame: Image.Image):
        self.frame = frame

    def grab_fullscreen(self) -> Image.Image:
        return self.frame


def render_frame(lines=PANEL_LINES) -> Image.Image:
    img = Image.new("RGB", FRAME_SIZE, (46, 60, 40))     # 模拟游戏场景
    draw = ImageDraw.Draw(img)
    x, y, w, h = REGION
    draw.rectangle((x, y, x + w, y + h), fill=(22, 20, 18))     # 深色面板
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
    d = WeaponDetector()
    yield d
    d.stop()


def test_detects_weapon_and_affixes_on_screen(detector):
    engine = FakeEngine(render_frame())
    result = wait_for_result(detector, engine, WeaponDetectParam(region=REGION))

    by_name = {a.name: a for a in result.annotations}
    assert set(by_name) == {"火焰匕首", "提升魔力属性攻击力", "提升血量上限", "强化致命一击"}, \
        [(a.name, a.text) for a in result.annotations]

    assert by_name["火焰匕首"].kind == "weapon"
    assert by_name["火焰匕首"].text == "基础补正：力量 E 13 · 敏捷 C 73"
    # 识别到“＋２”档位时只显示该档
    assert by_name["提升魔力属性攻击力"].text == "魔力伤害 +9%"
    assert by_name["强化致命一击"].text == "伤害 +12%/+18%/+24%（档位1/2/3）"
    assert by_name["提升血量上限"].dim

    # 标注锚点位置是文字在屏幕上的位置（误差在字高以内）
    for lx, ly, size, text in PANEL_LINES:
        for ann in result.annotations:
            if ann.name.startswith(text[:3]):
                x, y, w, h = ann.box
                assert abs(x - lx) < size and abs(y - ly) < size * 1.5, (text, ann.box)
                assert w > size * 2 and h > size * 0.5
    # 所有文字行（含没匹配到的“战技：盲击”）都作为避让区域返回
    assert len(result.line_boxes) >= 5
    assert not result.stale


def test_scene_change_marks_stale_then_clears(detector):
    param = WeaponDetectParam(region=REGION)
    wait_for_result(detector, FakeEngine(render_frame()), param)

    empty_engine = FakeEngine(render_frame(lines=[]))   # 面板上的文字消失
    result = detector.detect(empty_engine, param)
    assert result.stale, "画面大幅变化后旧标注应先被标记为过期"

    result = wait_for_result(detector, empty_engine, param)
    assert result.annotations == [] and not result.stale


def test_switching_weapon_hides_old_values_immediately(detector):
    param = WeaponDetectParam(region=REGION)
    first = wait_for_result(detector, FakeEngine(render_frame()), param)
    assert "火焰匕首" in {a.name for a in first.annotations}

    # 同一块面板里换成另一把武器：旧武器的数值不能留在新文字旁边
    other = [(x, y, size, "火焰长剑" if text == "火焰匕首" else text) for x, y, size, text in PANEL_LINES]
    engine = FakeEngine(render_frame(lines=other))
    assert detector.detect(engine, param).stale

    result = wait_for_result(detector, engine, param)
    names = {a.name for a in result.annotations}
    assert "火焰长剑" in names and "火焰匕首" not in names
    assert not result.stale


def test_background_change_elsewhere_does_not_hide_annotations(detector):
    param = WeaponDetectParam(region=REGION)
    wait_for_result(detector, FakeEngine(render_frame()), param)

    # 面板里没有文字的地方画面变了（例如背后的游戏画面在动），已有标注依然有效
    frame = render_frame()
    ImageDraw.Draw(frame).rectangle((1200, 680, 1840, 720), fill=(200, 200, 60))
    result = detector.detect(FakeEngine(frame), param)
    assert not result.stale


def test_unchanged_frame_is_not_recognized_again(detector):
    engine = FakeEngine(render_frame())
    param = WeaponDetectParam(region=REGION)
    wait_for_result(detector, engine, param)
    version = detector._result_version
    for _ in range(10):
        result = detector.detect(engine, param)
        assert not result.updated and not result.stale
        time.sleep(0.05)
    assert detector._result_version == version


def test_own_annotation_text_is_ignored(detector):
    engine = FakeEngine(render_frame())
    param = WeaponDetectParam(region=REGION, ignore_texts={"基础补正：力量 E 13 · 敏捷 C 73"})
    result = wait_for_result(detector, engine, param)
    assert "火焰匕首" in {a.name for a in result.annotations}   # 游戏里的武器名仍然被识别


def test_clearing_region_clears_overlay_once(detector):
    engine = FakeEngine(render_frame())
    wait_for_result(detector, engine, WeaponDetectParam(region=REGION))
    cleared = detector.detect(engine, WeaponDetectParam(region=None))
    assert cleared.updated and cleared.annotations == []
    assert not detector.detect(engine, WeaponDetectParam(region=None)).updated   # 只通知一次


def test_none_params_is_a_noop(detector):
    # 其他功能触发的检测不应影响武器信息的状态
    assert not detector.detect(FakeEngine(render_frame()), None).updated
