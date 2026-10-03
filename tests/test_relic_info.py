import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import build_relic_data
from src.relic.info import MAX_TEXT_CHARS, RelicAffixEntry, RelicAffixLookup, RelicInfo, load_relic_info
from src.weapon.info import NameIndex


def make_info() -> RelicInfo:
    return RelicInfo({
        "affixes": {
            "提升物理攻击力": [{"id": 1, "text": "物理攻击力 +4%"}],
            "提升物理攻击力＋１": [{"id": 2, "text": "物理攻击力 +5%"}],
            "提升物理攻击力＋２": [{"id": 3, "text": "物理攻击力 +6%"}],
            "集中力＋３": [{"id": 4, "text": "+3点集中力（固定+15点专注值上限）"}],
            "延长魔法、祷告的有效时间": [{"id": 5, "text": "延长50%，向下取整"}],
            "提升血量上限": [
                {"id": 6, "text": "生命值上限+10%", "deep": True},
                {"id": 7, "text": "+5点生命力（固定+100点生命值上限）", "deep": False},
            ],
            "出击时，武器祷告改为“兽爪” ※仅限能使用的武器类别": [{"id": 8, "text": "仅复仇者有效"}],
            "出击时，武器祷告改为“龙焰” ※仅限能使用的武器类别": [{"id": 9, "text": "仅复仇者有效"}],
        },
        "affix_names_without_values": ["出击时，会持有“红结晶露滴”"],
    })


class TestLookup:
    info = make_info()

    @pytest.mark.parametrize("text,name,value", [
        ("提升物理攻击力＋２", "提升物理攻击力＋２", "物理攻击力 +6%"),
        ("提升物理攻击力+2", "提升物理攻击力＋２", "物理攻击力 +6%"),       # 半角加号
        ("提升物理攻击力 + 2", "提升物理攻击力＋２", "物理攻击力 +6%"),     # 多出的空格
        ("提升物理攻击力＋１", "提升物理攻击力＋１", "物理攻击力 +5%"),
        ("提升物理攻击力", "提升物理攻击力", "物理攻击力 +4%"),
        ("集中力+3", "集中力＋３", "+3点集中力（固定+15点专注值上限）"),
        ("延长魔法、祷告的有效时间", "延长魔法、祷告的有效时间", "延长50%，向下取整"),
    ])
    def test_exact_names(self, text, name, value):
        lookup = self.info.lookup_affix(text)
        assert lookup is not None and lookup.name == name
        assert lookup.display_text() == value and lookup.has_values

    def test_leading_junk_from_the_icon_is_tolerated(self):
        assert self.info.lookup_affix("口集中力+3").name == "集中力＋３"

    def test_one_wrong_character_is_tolerated(self):
        assert self.info.lookup_affix("延长魔法、祷告的有效时问").name == "延长魔法、祷告的有效时间"

    def test_unrelated_text_is_not_matched(self):
        assert self.info.lookup_affix("遗物一览") is None
        assert self.info.lookup_affix("") is None
        assert self.info.lookup_affix("A") is None

    def test_affix_without_values(self):
        lookup = self.info.lookup_affix("出击时，会持有“红结晶露滴”")
        assert lookup is not None and not lookup.has_values and lookup.display_text() == ""

    def test_unreadable_symbol_is_ignored(self):
        # OCR 经常漏掉“※”，两种写法都要匹配到同一条
        for text in ("出击时，武器祷告改为“兽爪”※仅限能使用的武器类别", "出击时，武器祷告改为“兽爪”仅限能使用的武器类别"):
            assert self.info.lookup_affix(text, strict=True).name == "出击时，武器祷告改为“兽爪” ※仅限能使用的武器类别"


class TestTierSafety:
    """档位写在词条名里：档位没认全时宁可不显示，也不能把另一档的数值显示出来"""
    info = make_info()

    @pytest.mark.parametrize("text", [
        "提升物理攻击力+",        # 档位数字漏识别
        "提升物理攻击力+z",       # 档位数字被识别成字母
        "提升物理攻击力＋５",     # 不存在的档位
        "提升物理攻击力＋Ⅱ",
    ])
    def test_unresolvable_tier_is_not_shown_as_another_tier(self, text):
        assert self.info.lookup_affix(text) is None

    def test_missing_plus_sign_is_recovered(self):
        # “提升物理攻击力2”：补回漏识别的“+”后恰好是已知词条
        assert self.info.lookup_affix("提升物理攻击力2").name == "提升物理攻击力＋２"

    def test_trailing_junk_that_is_not_a_tier_is_ignored(self):
        assert self.info.lookup_affix("提升物理攻击力 口").name == "提升物理攻击力"

    def test_strict_skips_the_contained_name_rule(self):
        # 紧挨着的两行合并出来的文字里，若恰好包含其中一条词条的名字，不能把整段都当作那一条（另一行就被吞掉了）
        text = "提升物理攻击力生命力"
        assert self.info.lookup_affix(text).name == "提升物理攻击力"
        assert self.info.lookup_affix(text, strict=True) is None


class TestDisplay:
    def test_same_name_in_deep_and_normal_relics_are_listed_separately(self):
        lookup = make_info().lookup_affix("提升血量上限")
        assert lookup.display_text() == "深夜遗物：生命值上限+10% ｜ 普通遗物：+5点生命力（固定+100点生命值上限）"

    def test_identical_texts_are_not_repeated(self):
        lookup = RelicAffixLookup("x", [RelicAffixEntry(1, "+5%"), RelicAffixEntry(2, "+5%", deep=True)])
        assert lookup.display_text() == "+5%"

    def test_long_text_is_shortened(self):
        text = "数" * 300
        shown = RelicAffixLookup("x", [RelicAffixEntry(1, text)]).display_text()
        assert len(shown) == MAX_TEXT_CHARS and shown.endswith("…")


class TestBuildScript:
    def test_clean_explanation_drops_the_echoed_name(self):
        assert build_relic_data.clean_explanation(
            "延长魔法、祷告的有效时间", "延长魔法、祷告的有效时间 (延长50%，向下取整)") == "延长50%，向下取整"
        assert build_relic_data.clean_explanation(
            "提升近战攻击力", "近战攻击造成的伤害 +6% (包括近战武器打出的弹道型远程战技)"
        ) == "近战攻击造成的伤害 +6% (包括近战武器打出的弹道型远程战技)"

    def test_clean_explanation_joins_bullets(self):
        assert build_relic_data.clean_explanation(
            "x", "召唤家人时激活不同的增益效果: ∘ 海伦：每秒回复1点 ∘ 弗雷德利克：+10%") == \
            "召唤家人时激活不同的增益效果:海伦：每秒回复1点；弗雷德利克：+10%"
        assert build_relic_data.clean_explanation("x", "∘ 在隐身的12.5秒内 ∘ 每层增伤15%") == "在隐身的12.5秒内；每层增伤15%"

    def test_build_affixes_keeps_same_named_affixes_apart(self):
        affixes, without_values = build_relic_data.build_affixes([
            {"effectId": 10, "name": "提升血量上限", "explanation": "生命值上限+10%", "requiresCurse": True},
            {"effectId": 11, "name": "提升血量上限", "explanation": "+5点生命力", "requiresCurse": False},
            {"effectId": 12, "name": "出击时，会持有“红结晶露滴”", "explanation": ""},
            {"effectId": 13, "name": "出击时，会持有“红结晶露滴”", "explanation": ""},
        ])
        assert affixes == {"提升血量上限": [
            {"id": 10, "text": "生命值上限+10%", "deep": True}, {"id": 11, "text": "+5点生命力", "deep": False}]}
        assert without_values == ["出击时，会持有“红结晶露滴”"]


@pytest.fixture(scope="module")
def data():
    with open(os.path.join(ROOT, "data", "relics.json"), encoding="utf-8") as f:
        return json.load(f)


class TestBundledData:
    """随程序打包的 data/relics.json 本身要满足的约束（刷新数据后也能发现问题）"""

    def test_every_name_resolves_to_itself(self, data):
        info = RelicInfo(data)
        names = [*data["affixes"], *data["affix_names_without_values"]]
        assert len(names) > 400
        wrong = [name for name in names if (found := info.lookup_affix(name)) is None or found.name != name]
        assert wrong == []

    def test_no_name_is_both_with_and_without_values(self, data):
        assert not set(data["affixes"]) & set(data["affix_names_without_values"])

    def test_every_entry_has_text(self, data):
        for name, entries in data["affixes"].items():
            assert entries and all(e["text"].strip() for e in entries), name

    def test_names_are_not_ambiguous_after_normalization(self, data):
        names = [*data["affixes"], *data["affix_names_without_values"]]
        index = NameIndex(names)
        assert len(index) == len(set(names))

    def test_known_values(self, data):
        info = RelicInfo(data)
        assert info.lookup_affix("提升物理攻击力＋２").display_text() == "物理攻击力 +6%"
        assert info.lookup_affix("提升物理攻击力＋３").display_text() == "物理攻击力+10.5%"
        assert info.lookup_affix("集中力＋３").display_text() == "+3点集中力（固定+15点专注值上限）"
        assert info.lookup_affix("延长魔法、祷告的有效时间").display_text() == "延长50%，向下取整"
        assert info.lookup_affix("【送葬者】发动绝招时，恢复触碰到的我方人物的血量").display_text() == \
            "绝招触碰到的友方单位，固定回复[最大生命值 × 30% + 100]点血量"
        assert info.lookup_affix("提升血量上限").display_text().startswith("深夜遗物：生命值上限+10% ｜ 普通遗物：")

    def test_load_relic_info(self):
        info = load_relic_info(os.path.join(ROOT, "data", "relics.json"))
        assert info.affix_count > 500 and info.game_version
