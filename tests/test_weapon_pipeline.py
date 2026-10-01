import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.weapon.annotate import NO_DATA_TEXT, build_annotations
from src.weapon.info import WeaponInfo
from src.weapon.layout import (
    POSITION_BELOW, POSITION_RIGHT, inside, intersects, layout_annotations, place_annotation,
)
from src.weapon.ocr import OcrLine


def make_info() -> WeaponInfo:
    return WeaponInfo({
        "weapons": {"火焰匕首": {"type": "短剑", "rarity": "普通", "correct": [13, 73, 0, 0, 0]}},
        "affixes": {"提升魔力属性攻击力": [
            {"tier": 1, "text": "魔力伤害 +6%"}, {"tier": 2, "text": "魔力伤害 +9%"}]},
        "affix_names_without_values": ["提升血量上限"],
    })


def line(text, x, y, w=200, h=24, score=0.95):
    return OcrLine(text=text, box=(x, y, w, h), score=score)


class TestBuildAnnotations:
    def test_weapon_and_affixes(self):
        lines = [line("火焰匕首", 10, 10), line("提升魔力属性攻击力＋２", 10, 60), line("提升血量上限", 10, 100),
                 line("无关的描述文字，不会被匹配", 10, 140)]
        anns, boxes = build_annotations(lines, make_info(), origin=(1000, 500))
        assert [(a.kind, a.name) for a in anns] == [
            ("weapon", "火焰匕首"), ("affix", "提升魔力属性攻击力"), ("affix", "提升血量上限")]
        assert anns[0].text == "基础补正：力量 E 13 · 敏捷 C 73"
        assert anns[1].text == "魔力伤害 +9%"
        assert anns[2].text == NO_DATA_TEXT and anns[2].dim
        # 坐标换算为屏幕坐标
        assert anns[0].box == (1010, 510, 200, 24)
        assert len(boxes) == 4

    def test_scale_is_undone(self):
        anns, _ = build_annotations([line("火焰匕首", 50, 20, 100, 12)], make_info(), origin=(100, 100), scale=0.5)
        assert anns[0].box == (200, 140, 200, 24)

    def test_low_score_lines_are_dropped(self):
        anns, boxes = build_annotations([line("火焰匕首", 0, 0, score=0.3)], make_info(), origin=(0, 0))
        assert anns == [] and boxes == []

    def test_own_annotation_text_is_ignored(self):
        lines = [line("魔力伤害+9%", 0, 0), line("提升魔力属性攻击力", 0, 40)]
        anns, boxes = build_annotations(lines, make_info(), origin=(0, 0), ignore_texts={"魔力伤害 +9%"})
        assert [a.name for a in anns] == ["提升魔力属性攻击力"]
        assert len(boxes) == 1

    def test_same_affix_on_two_weapons_both_annotated(self):
        lines = [line("提升魔力属性攻击力", 0, 0), line("提升魔力属性攻击力", 600, 0)]
        anns, _ = build_annotations(lines, make_info(), origin=(0, 0))
        assert len(anns) == 2


class TestLayout:
    bounds = (0, 0, 1920, 1080)

    def test_below_preferred(self):
        assert place_annotation((100, 100, 200, 24), (180, 20), POSITION_BELOW, [], self.bounds) == (100, 126, 180, 20)

    def test_right_preferred(self):
        x, y, w, h = place_annotation((100, 100, 200, 24), (180, 20), POSITION_RIGHT, [], self.bounds)
        assert x > 300 and y == 102

    def test_below_collides_with_next_line_falls_back_to_right(self):
        next_line = (100, 126, 200, 24)
        rect = place_annotation((100, 100, 200, 24), (180, 20), POSITION_BELOW, [next_line], self.bounds)
        assert not intersects(rect, next_line) and rect[0] > 300

    def test_right_overflows_screen_falls_back_to_below(self):
        rect = place_annotation((1700, 100, 200, 24), (180, 20), POSITION_RIGHT, [], self.bounds)
        assert rect == (1700, 126, 180, 20)

    def test_nothing_fits_still_visible_inside_bounds(self):
        obstacles = [(0, 0, 1920, 1080)]
        rect = place_annotation((1800, 1070, 100, 10), (300, 40), POSITION_BELOW, obstacles, self.bounds)
        assert inside(rect, self.bounds)

    def test_annotations_do_not_overlap_each_other(self):
        anchors = [(100, 100, 200, 24), (100, 124, 200, 24)]
        sizes = [(400, 40), (400, 40)]
        placed = layout_annotations(anchors, sizes, anchors, POSITION_BELOW, self.bounds)
        assert not intersects(placed[0], placed[1])
        for p, a in zip(placed, anchors):
            assert not intersects(p, a)

    def test_tight_panel_has_no_overlaps(self):
        # 行距比标注还窄的紧凑面板（来自端到端测试的实际数值）：既不压住面板文字，标注之间也不重叠
        anchors = [(348, 107, 124, 35), (348, 176, 241, 24), (348, 220, 136, 27),
                   (349, 266, 243, 25), (348, 311, 136, 25)]
        sizes = [(330, 31), (134, 26), (380, 30), (458, 26), (120, 26)]
        for preferred in (POSITION_BELOW, POSITION_RIGHT):
            placed = layout_annotations(anchors, sizes, anchors, preferred, (0, 0, 1920, 1080))
            for i, p in enumerate(placed):
                assert inside(p, (0, 0, 1920, 1080))
                assert not any(intersects(p, a) for a in anchors), (preferred, i, p)
                assert not any(intersects(p, q) for j, q in enumerate(placed) if j != i), (preferred, i, p)

    def test_gutter_column_is_used_when_adjacent_positions_are_blocked(self):
        # 下方被下一行文字挡住，紧贴右侧又被前一条（很宽的）标注挡住且错开也躲不开：放到面板文字右侧的对齐列
        anchor = (100, 126, 200, 24)
        next_line = (100, 152, 300, 24)
        first = (100, 126, 500, 50)                  # 前一条标注：又宽又高，盖住了右侧的位置
        rect = place_annotation(anchor, (180, 22), POSITION_BELOW, [(100, 100, 200, 24), next_line, first],
                                (0, 0, 1920, 1080), gutter_x=620)
        assert rect[0] == 620

    def test_least_overlapping_position_is_chosen_when_everything_collides(self):
        # 下方完全被文字挡住，右侧只有一小部分被挡：应选右侧
        anchor = (100, 100, 200, 24)
        obstacles = [(100, 126, 400, 24), (320, 100, 10, 24)]
        rect = place_annotation(anchor, (180, 20), POSITION_BELOW, obstacles, (0, 0, 1920, 1080))
        total = sum(max(0, min(rect[0] + rect[2], o[0] + o[2]) - max(rect[0], o[0])) *
                    max(0, min(rect[1] + rect[3], o[1] + o[3]) - max(rect[1], o[1])) for o in obstacles)
        below_total = 180 * 20 - 0   # 下方候选与第一个障碍完全重叠
        assert total < below_total

    def test_never_covers_the_annotated_text_when_avoidable(self):
        # 屏幕右边界很窄，右侧放不下；下方被挡住一点点：宁可轻微压住下一行，也不能盖住被标注的词条本身
        anchor = (348, 107, 124, 35)
        next_line = (348, 176, 241, 24)
        rect = place_annotation(anchor, (375, 37), POSITION_BELOW, [next_line], (0, 0, 800, 800))
        assert not intersects(rect, anchor)
