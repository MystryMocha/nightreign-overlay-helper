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


def make_action_info() -> WeaponInfo:
    return WeaponInfo({
        "weapons": {
            "火焰匕首": {"type": "短剑", "rarity": "普通", "correct": [13, 73, 0, 0, 0], "id": 1000000},
            "隐士的手杖": {"type": "辉石魔杖", "rarity": "普通", "correct": [0, 0, 100, 0, 0],
                           "id": 33750000, "caster": True},
        },
        "skills": {
            "辉石魔砾": {"id": 203, "text": "魔力 137+基础", "byWeapon": {"1000000": "魔力 99+基础"}},
            "神圣刀刃": {"id": 201, "text": "圣 180+基础 / 65%", "byWeapon": {}},
            "无数值战技": {"id": 5, "text": None, "byWeapon": {}},
        },
        "spells": {"辉石魔砾": {"id": 4000, "text": "FP 7 · 魔力 152"}},
        "affixes": {"提升魔力属性攻击力": [{"tier": 2, "text": "魔力伤害 +9%"}]},
    })


def action_texts(lines, **kwargs):
    anns, _ = build_annotations(lines, make_action_info(), origin=(0, 0), **kwargs)
    return [(a.kind, a.name, a.text, a.dim) for a in anns if a.kind != "weapon"]


class TestActionAnnotations:
    def test_skill_and_spell_summaries(self):
        lines = [line("火焰匕首", 10, 10), line("战技：神圣刀刃", 10, 60), line("无数值战技", 10, 100)]
        assert action_texts(lines) == [
            ("skill", "神圣刀刃", "圣 180+基础 / 65%", False),
            ("skill", "无数值战技", NO_DATA_TEXT, True),
        ]

    def test_same_name_uses_prefix(self):
        lines = [line("火焰匕首", 10, 10), line("魔法：辉石魔砾", 10, 60)]
        assert action_texts(lines) == [("spell", "辉石魔砾", "FP 7 · 魔力 152", False)]
        lines = [line("隐士的手杖", 10, 10), line("战技：辉石魔砾", 10, 60)]
        assert action_texts(lines) == [("skill", "辉石魔砾", "魔力 137+基础", False)]

    def test_same_name_without_prefix_follows_the_weapon_above(self):
        # 辉石魔砾在法杖上是法术，在剑上是战技；剑上的战技还按武器 id 取该武器的动作
        assert action_texts([line("隐士的手杖", 10, 10), line("辉石魔砾", 10, 60)]) == [
            ("spell", "辉石魔砾", "FP 7 · 魔力 152", False)]
        assert action_texts([line("火焰匕首", 10, 10), line("辉石魔砾", 10, 60)]) == [
            ("skill", "辉石魔砾", "魔力 99+基础", False)]

    def test_same_name_without_weapon_shows_both(self):
        assert action_texts([line("辉石魔砾", 10, 60)]) == [
            ("mixed", "辉石魔砾", "战技：魔力 137+基础 · 法术：FP 7 · 魔力 152", False)]

    def test_picks_the_nearest_weapon_above(self):
        lines = [line("隐士的手杖", 10, 10), line("辉石魔砾", 10, 60), line("火焰匕首", 10, 200), line("辉石魔砾", 10, 250)]
        assert action_texts(lines) == [
            ("spell", "辉石魔砾", "FP 7 · 魔力 152", False),
            ("skill", "辉石魔砾", "魔力 99+基础", False),
        ]

    def test_picks_the_weapon_in_the_same_column(self):
        # 对比面板：左列法杖、右列匕首，各自下面的行归各自的武器
        lines = [line("隐士的手杖", 10, 10), line("火焰匕首", 900, 10),
                 line("辉石魔砾", 10, 60), line("辉石魔砾", 900, 60)]
        assert action_texts(lines) == [
            ("spell", "辉石魔砾", "FP 7 · 魔力 152", False),
            ("skill", "辉石魔砾", "魔力 99+基础", False),
        ]

    def test_annotations_stay_in_reading_order(self):
        # 战技 / 法术在武器之后才处理，但返回时仍按从上到下排列，布局才会先放上面的标注
        lines = [line("火焰匕首", 10, 10), line("神圣刀刃", 10, 60), line("提升魔力属性攻击力", 10, 100)]
        anns, _ = build_annotations(lines, make_action_info(), origin=(0, 0))
        assert [a.kind for a in anns] == ["weapon", "skill", "affix"]

    def test_action_names_are_not_matched_from_long_sentences(self):
        assert action_texts([line("使用神圣刀刃可以造成大量伤害并且附带效果", 10, 60)]) == []


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


def make_seal_info() -> WeaponInfo:
    return WeaponInfo({
        "weapons": {
            "爪痕圣印记": {"type": "圣印记", "rarity": "优良", "correct": [0, 0, 0, 100, 0], "id": 34040000,
                           "caster": True},
            "隐士的手杖": {"type": "辉石魔杖", "rarity": "普通", "correct": [0, 0, 100, 0, 0],
                           "id": 33750000, "caster": True},
        },
        "spells": {
            "兽石": {"id": 6800, "text": "FP 7 · 物理 87"},
            "辉石魔砾": {"id": 4000, "text": "FP 7 · 魔力 152"},
            "恢复": {"id": 6421, "text": None},
        },
    })


def spell_texts(lines):
    anns, _ = build_annotations(lines, make_seal_info(), origin=(0, 0))
    return [(a.name, a.text) for a in anns if a.kind == "spell"]


class TestSpellScaling:
    def test_prayer_damage_uses_incantation_scaling(self):
        lines = [line("爪痕圣印记＋１", 10, 10), line("祷告加成", 10, 60, w=120), line("220", 400, 62, w=60),
                 line("兽石", 10, 200)]
        assert spell_texts(lines) == [("兽石", "FP 7 · 物理 191（加成 220）")]

    def test_scaling_recognized_with_label(self):
        lines = [line("爪痕圣印记", 10, 10), line("祷告加成 220", 10, 60), line("兽石", 10, 200)]
        assert spell_texts(lines) == [("兽石", "FP 7 · 物理 191（加成 220）")]

    def test_without_scaling_shows_base_values(self):
        assert spell_texts([line("爪痕圣印记", 10, 10), line("兽石", 10, 200)]) == [("兽石", "FP 7 · 物理 87")]

    def test_sorcery_does_not_use_incantation_scaling(self):
        lines = [line("隐士的手杖", 10, 10), line("祷告加成", 10, 60, w=120), line("220", 400, 62, w=60),
                 line("魔法加成", 10, 100, w=120), line("150", 400, 102, w=60), line("辉石魔砾", 10, 200)]
        assert spell_texts(lines) == [("辉石魔砾", "FP 7 · 魔力 228（加成 150）")]

    def test_value_on_another_row_is_ignored(self):
        lines = [line("爪痕圣印记", 10, 10), line("祷告加成", 10, 60, w=120), line("176", 400, 140, w=60),
                 line("兽石", 10, 200)]
        assert spell_texts(lines) == [("兽石", "FP 7 · 物理 87")]

    def test_spell_without_damage_is_unchanged(self):
        lines = [line("爪痕圣印记", 10, 10), line("祷告加成 220", 10, 60), line("恢复", 10, 200)]
        assert spell_texts(lines) == [("恢复", NO_DATA_TEXT)]

    def test_each_column_uses_its_own_scaling(self):
        lines = [line("爪痕圣印记", 10, 10), line("爪痕圣印记", 900, 10),
                 line("祷告加成", 10, 60, w=120), line("200", 300, 62, w=60),
                 line("祷告加成", 900, 60, w=120), line("300", 1200, 62, w=60),
                 line("兽石", 10, 200), line("兽石", 900, 200)]
        assert spell_texts(lines) == [("兽石", "FP 7 · 物理 174（加成 200）"), ("兽石", "FP 7 · 物理 261（加成 300）")]
