import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src.relic.annotate import build_relic_annotations, is_wrapped_below
from src.relic.info import RelicInfo, load_relic_info
from src.weapon.annotate import NO_DATA_TEXT
from src.weapon.ocr import OcrLine


def line(text, x, y, w=200, h=28, score=0.95):
    return OcrLine(text=text, box=(x, y, w, h), score=score)


# 遗物仪式界面的真实截图（2000x1088）经 OCR 得到的文字行：左侧是已装备遗物“辽阔的水滴情景”的描述，
# 右侧是遗物一览里选中的“单眼镜的皮革袋”。两条较长的词条名在窄栏里折成了两行
RELIC_SCREEN = [
    OcrLine("遗物仪式", (140, 38, 137, 42), 1.0),
    OcrLine("正在准备", (1412, 53, 110, 35), 1.0),
    OcrLine("0/2", (1870, 56, 57, 32), 0.96),
    OcrLine("复仇者", (490, 126, 83, 36), 1.0),
    OcrLine("取得时间", (1433, 160, 211, 41), 1.0),
    OcrLine("遗物一览", (958, 161, 110, 35), 1.0),
    OcrLine("LB", (76, 176, 38, 23), 1.0),
    OcrLine("RB", (741, 176, 38, 23), 1.0),
    OcrLine("空格1", (110, 243, 81, 37), 1.0),
    OcrLine("209", (1822, 732, 50, 33), 1.0),
    OcrLine("21", (1725, 735, 40, 30), 0.97),
    OcrLine("单眼镜的皮革袋", (1118, 771, 181, 33), 1.0),
    OcrLine("辽阔的水滴情景", (245, 773, 180, 30), 1.0),
    OcrLine("【送葬者】发动绝招时，恢复触碰到的我方人物的血量", (287, 812, 498, 30), 1.0),
    OcrLine("【送葬者】使用祷告将辅助效果附加在自己身上时", (1156, 812, 460, 30), 1.0),
    OcrLine("提升物理攻击力", (1153, 837, 151, 28), 1.0),
    OcrLine("出击时，武器祷告改为“兽爪”", (278, 872, 288, 28), 1.0),
    OcrLine("延长魔法、祷告的有效时间", (1153, 872, 255, 28), 1.0),
    OcrLine("仅限能使用的武器类别", (280, 896, 236, 28), 1.0),
    OcrLine("提升物理攻击力+2", (1148, 932, 195, 32), 1.0),
    OcrLine("集中力+3", (276, 933, 111, 30), 1.0),
    OcrLine(":详细信息", (70, 1005, 126, 35), 0.98),
    OcrLine(":确定B:返回:登记/移除喜爱", (1320, 1006, 417, 32), 0.99),
    OcrLine(":翻页", (1801, 1006, 70, 31), 0.97),
]


@pytest.fixture(scope="module")
def info() -> RelicInfo:
    os.chdir(ROOT)
    return load_relic_info()


def texts(annotations):
    return [(a.name, a.text) for a in annotations]


class TestRealScreen:
    def test_all_affixes_on_the_screen_are_annotated(self, info):
        annotations, _ = build_relic_annotations(RELIC_SCREEN, info, origin=(0, 0))
        assert texts(annotations) == [
            ("【送葬者】发动绝招时，恢复触碰到的我方人物的血量", "绝招触碰到的友方单位，固定回复[最大生命值 × 30% + 100]点血量"),
            ("【送葬者】使用祷告将辅助效果附加在自己身上时 提升物理攻击力", "物理攻击力+19%，持续60秒"),
            ("出击时，武器祷告改为“兽爪” ※仅限能使用的武器类别", "仅复仇者有效"),
            ("延长魔法、祷告的有效时间", "延长50%，向下取整"),
            ("提升物理攻击力＋２", "物理攻击力 +6%"),
            ("集中力＋３", "+3点集中力（固定+15点专注值上限）"),
        ]
        assert not any(a.dim for a in annotations)

    def test_wrapped_tail_is_not_taken_for_a_separate_affix(self, info):
        # 折行后的“提升物理攻击力”单独看是另一条词条（+4%），不能被当成它
        annotations, _ = build_relic_annotations(RELIC_SCREEN, info, origin=(0, 0))
        assert "提升物理攻击力" not in {a.name for a in annotations}
        assert "物理攻击力 +4%" not in {a.text for a in annotations}

    def test_wrapped_affix_covers_all_its_lines(self, info):
        annotations, boxes = build_relic_annotations(RELIC_SCREEN, info, origin=(0, 0))
        wrapped = annotations[1]
        assert wrapped.box == (1153, 812, 463, 53)       # 两行文字的外框
        assert wrapped.line_height == 30                 # 字号按单行高度算，而不是外框高度
        assert annotations[0].line_height == 30
        assert len(boxes) == len(RELIC_SCREEN)           # 所有文字行都作为避让区域返回

    def test_coordinates_are_converted_to_screen_space(self, info):
        lines = [OcrLine("集中力+3", (10, 20, 50, 15), 0.95)]
        annotations, boxes = build_relic_annotations(lines, info, origin=(1000, 500), scale=0.5)
        assert annotations[0].box == (1020, 540, 100, 30) and boxes == [(1020, 540, 100, 30)]

    def test_second_column_is_not_mixed_into_the_first(self, info):
        # 左右两栏的行在 y 方向交错，折行合并只能发生在同一栏里
        annotations, _ = build_relic_annotations(RELIC_SCREEN, info, origin=(0, 0))
        left = [a for a in annotations if a.box[0] < 1000]
        right = [a for a in annotations if a.box[0] >= 1000]
        assert len(left) == 3 and len(right) == 3


class TestWrapping:
    def test_three_line_wrap(self, info):
        lines = [line("【送葬者】使用祷告将辅助", 100, 100), line("效果附加在自己身上时", 100, 128),
                 line("提升物理攻击力", 100, 156)]
        annotations, _ = build_relic_annotations(lines, info, origin=(0, 0))
        assert texts(annotations) == [
            ("【送葬者】使用祷告将辅助效果附加在自己身上时 提升物理攻击力", "物理攻击力+19%，持续60秒")]
        assert annotations[0].box == (100, 100, 200, 84)

    def test_separate_affixes_with_normal_spacing_are_not_merged(self, info):
        lines = [line("集中力+3", 100, 100, w=111), line("提升物理攻击力+2", 100, 148, w=195)]
        annotations, _ = build_relic_annotations(lines, info, origin=(0, 0))
        assert [a.name for a in annotations] == ["集中力＋３", "提升物理攻击力＋２"]

    def test_tightly_stacked_short_affixes_are_both_kept(self):
        # 行距小到会被当作折行，但合并后的文字太短、不可能是折行的长词条名：不能靠少量错字的容忍把两行硬凑成别的词条。
        # “提升物理攻击力”+“力气+2”合并后与“提升物理攻击力＋２”只差两个字
        info = RelicInfo({"affixes": {
            "提升物理攻击力": [{"id": 1, "text": "物理攻击力 +4%"}],
            "提升物理攻击力＋２": [{"id": 2, "text": "物理攻击力 +6%"}],
            "力气＋２": [{"id": 3, "text": "+2点力气"}],
        }})
        lines = [line("提升物理攻击力", 100, 100, w=150), line("力气+2", 100, 128, w=60)]
        annotations, _ = build_relic_annotations(lines, info, origin=(0, 0))
        assert texts(annotations) == [("提升物理攻击力", "物理攻击力 +4%"), ("力气＋２", "+2点力气")]

    def test_unmatched_first_line_blocks_its_wrapped_tail(self, info):
        # 第一行没认出来（新词条 / 识别错误）时，下面折下来的“提升物理攻击力”不能单独配上 +4%
        lines = [line("【送葬者】某个数据里还没有的新词条名称很长很长", 100, 100, w=460),
                 line("提升物理攻击力", 100, 128, w=151)]
        annotations, _ = build_relic_annotations(lines, info, origin=(0, 0))
        assert annotations == []

    def test_lone_affix_with_the_same_name_is_still_annotated(self, info):
        annotations, _ = build_relic_annotations([line("提升物理攻击力", 100, 100)], info, origin=(0, 0))
        assert texts(annotations) == [("提升物理攻击力", "物理攻击力 +4%")]

    def test_matched_affix_above_does_not_block_the_next_one(self, info):
        # 上一行已经是完整的词条时，紧挨着的下一行是另一条词条
        lines = [line("提升物理攻击力+2", 100, 100, w=195), line("集中力+3", 100, 126, w=111)]
        assert len(build_relic_annotations(lines, info, origin=(0, 0))[0]) == 2


class TestFiltering:
    def test_low_score_lines_are_dropped(self, info):
        annotations, boxes = build_relic_annotations([line("集中力+3", 0, 0, score=0.3)], info, origin=(0, 0))
        assert annotations == [] and boxes == []

    def test_own_annotation_text_is_ignored(self, info):
        lines = [line("+3点集中力（固定+15点专注值上限）", 0, 0), line("集中力+3", 0, 100)]
        annotations, boxes = build_relic_annotations(
            lines, info, origin=(0, 0), ignore_texts={"+3点集中力（固定+15点专注值上限）"})
        assert [a.name for a in annotations] == ["集中力＋３"]
        assert len(boxes) == 1

    def test_affix_without_values_is_dimmed(self, info):
        annotations, _ = build_relic_annotations([line("出击时，会持有“红结晶露滴”", 0, 0)], info, origin=(0, 0))
        assert texts(annotations) == [("出击时，会持有“红结晶露滴”", NO_DATA_TEXT)] and annotations[0].dim

    def test_same_affix_on_two_relics_gets_two_annotations(self, info):
        lines = [line("集中力+3", 10, 100), line("集中力+3", 900, 100)]
        assert len(build_relic_annotations(lines, info, origin=(0, 0))[0]) == 2

    def test_unrelated_text_gives_no_annotations(self, info):
        lines = [line("遗物仪式", 0, 0), line("单眼镜的皮革袋", 0, 50), line("取得时间", 0, 100)]
        assert build_relic_annotations(lines, info, origin=(0, 0))[0] == []


class TestIsWrappedBelow:
    upper = (100, 100, 400, 30)

    def test_next_line_below_aligned_left(self):
        assert is_wrapped_below(self.upper, (100, 128, 150, 30))

    def test_overlapping_boxes_from_ocr_still_count(self):
        assert is_wrapped_below(self.upper, (103, 125, 150, 28))

    @pytest.mark.parametrize("lower", [
        (100, 172, 150, 30),      # 间距太大：是下一条词条
        (160, 128, 150, 30),      # 左边缘没对齐
        (520, 100, 150, 30),      # 同一行里并排的文字
        (100, 128, 150, 12),      # 字高差太多
        (100, 90, 150, 30),       # 在上面
    ])
    def test_not_a_continuation(self, lower):
        assert not is_wrapped_below(self.upper, lower)
