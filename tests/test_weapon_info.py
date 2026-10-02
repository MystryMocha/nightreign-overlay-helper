import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.weapon.info import (
    AffixLookup, AffixTier, NameIndex, WeaponInfo, WeaponLookup,
    action_summary, grade_of, load_weapon_info, normalize_text, parse_tier, spell_summary,
    strip_action_prefix, usable_action_hit,
)


def make_info() -> WeaponInfo:
    return WeaponInfo({
        "weapons": {
            "匕首": {"type": "短剑", "rarity": "普通", "correct": [13, 73, 0, 0, 0]},
            "火焰匕首": {"type": "短剑", "rarity": "普通", "correct": [13, 73, 0, 0, 0]},
            "火焰长剑": {"type": "直剑", "rarity": "普通", "correct": [50, 50, 0, 0, 0]},
            "火焰短剑": {"type": "直剑", "rarity": "普通", "correct": [40, 60, 0, 0, 0]},
            "指头圣印记": {"type": "圣印记", "rarity": "普通", "correct": [0, 0, 0, 100, 0]},
        },
        "affixes": {
            "提升魔力属性攻击力": [
                {"tier": 1, "text": "魔力伤害 +6%", "roles": ["affix"]},
                {"tier": 2, "text": "魔力伤害 +9%", "roles": ["affix"]},
                {"tier": 3, "text": "魔力伤害 +12%", "roles": ["affix"]},
            ],
            "血量偏低时，提升攻击力": [
                {"tier": 1, "text": "伤害 +13%", "conditional": True},
                {"tier": 2, "text": "伤害 +17%", "conditional": True},
            ],
            "陷入中毒时，形成毒性烟雾": [
                {"tier": 0, "text": "中毒累积 +200", "conditional": True},
            ],
        },
        "affix_names_without_values": ["提升血量上限"],
    })


class TestHelpers:
    @pytest.mark.parametrize("text,expected", [
        ("提升魔力属性攻击力＋２", ("提升魔力属性攻击力", 2)),
        ("提升魔力属性攻击力+3", ("提升魔力属性攻击力", 3)),
        ("提升魔力属性攻击力 + 1", ("提升魔力属性攻击力", 1)),
        ("强化魔法 Ⅱ", ("强化魔法", 2)),
        ("强化魔法Ⅲ", ("强化魔法", 3)),
        ("强化魔法", ("强化魔法", None)),
    ])
    def test_parse_tier(self, text, expected):
        assert parse_tier(text) == expected

    @pytest.mark.parametrize("value,grade", [
        (0, "-"), (1, "E"), (24, "E"), (25, "D"), (59, "D"), (60, "C"),
        (89, "C"), (90, "B"), (139, "B"), (140, "A"), (174, "A"), (175, "S"),
    ])
    def test_grade_of(self, value, grade):
        assert grade_of(value) == grade

    def test_normalize_text_ignores_punctuation_and_width(self):
        assert normalize_text("血量偏低时， 提升攻击力") == "血量偏低时提升攻击力"
        assert normalize_text("ＡＢＣ·d") == "abcd"


class TestNameIndex:
    index = NameIndex(["匕首", "火焰匕首", "火焰长剑", "火焰短剑", "提升魔力属性攻击力"])

    def test_exact_and_punctuation(self):
        assert self.index.match("火焰匕首") == "火焰匕首"
        assert self.index.match(" 火焰 匕首 ") == "火焰匕首"

    def test_prefers_longest_contained_name(self):
        # “匕首”与“火焰匕首”都被包含在行内时取更长的
        assert self.index.match("火焰匕首Lv15") == "火焰匕首"

    def test_short_names_need_exact_match(self):
        assert self.index.match("匕首") == "匕首"
        assert self.index.match("战技：匕首风暴") is None

    def test_long_sentences_are_not_matched(self):
        assert self.index.match("使用火焰匕首进行攻击时造成额外的伤害并且") is None

    def test_one_ocr_error_is_tolerated(self):
        assert self.index.match("提升魔力属性攻击刀") == "提升魔力属性攻击力"

    def test_ambiguous_fuzzy_match_is_rejected(self):
        # “火焰?剑”与“火焰长剑”“火焰短剑”同样接近，无法确定
        assert self.index.match("火焰丑剑") is None

    def test_unknown_text(self):
        assert self.index.match("完全无关的文字") is None
        assert self.index.match("") is None
        assert self.index.match("火") is None


class TestAffixDisplay:
    def test_unknown_tier_merges_numbers(self):
        a = make_info().lookup_affix("提升魔力属性攻击力")
        assert a.display_text() == "魔力伤害 +6%/+9%/+12%（档位1/2/3）"

    def test_detected_tier_shows_single_value(self):
        a = make_info().lookup_affix("提升魔力属性攻击力＋２")
        assert a.detected_tier == 2
        assert a.display_text() == "魔力伤害 +9%"

    def test_tier_not_in_data_falls_back_to_all(self):
        a = make_info().lookup_affix("提升魔力属性攻击力＋７")
        assert a.display_text() == "魔力伤害 +6%/+9%/+12%（档位1/2/3）"

    def test_conditional_marker(self):
        a = make_info().lookup_affix("血量偏低时，提升攻击力")
        assert a.display_text() == "伤害 +13%/+17%（档位1/2）（条件触发）"

    def test_single_tier_without_tier_number(self):
        a = make_info().lookup_affix("陷入中毒时，形成毒性烟雾")
        assert a.display_text() == "中毒累积 +200（条件触发）"

    def test_name_known_but_no_values(self):
        a = make_info().lookup_affix("提升血量上限")
        assert a is not None and not a.has_values
        assert a.display_text() == ""

    def test_different_skeletons_fall_back_to_per_tier_lines(self):
        a = AffixLookup("x", [AffixTier(1, "物理伤害 +8%"), AffixTier(2, "魔力伤害 +9%")])
        assert a.display_text() == "档位1 物理伤害 +8%；档位2 魔力伤害 +9%"

    def test_trailing_digit_that_is_part_of_name_is_not_lost(self):
        info = WeaponInfo({"affixes": {"强化2段攻击": [{"tier": 0, "text": "伤害 +5%"}]}})
        a = info.lookup_affix("强化2段攻击")
        assert a is not None and a.name == "强化2段攻击"


class TestWeaponLookup:
    def test_correct_text(self):
        w = make_info().lookup_weapon("匕首")
        assert w.correct_text() == "基础补正：力量 E 13 · 敏捷 C 73"

    def test_only_nonzero_attributes_shown(self):
        w = make_info().lookup_weapon("指头圣印记")
        assert w.correct_parts() == [("信仰", "B", 100)]

    def test_level_suffix_is_ignored(self):
        assert make_info().lookup_weapon("火焰匕首 +4").name == "火焰匕首"
        assert make_info().lookup_weapon("火焰匕首 Lv.15").name == "火焰匕首"

    def test_no_correct_at_all(self):
        assert WeaponLookup("x", "拳", "普通", [0, 0, 0, 0, 0]).correct_text() == "基础补正：无"

    def test_unknown_weapon(self):
        assert make_info().lookup_weapon("不存在的武器名字") is None


def motion(value, **overrides):
    return {key: overrides.get(key, value) for key in ("physical", "magic", "fire", "lightning", "holy")}


class TestActionSummary:
    def test_uniform_motion_collapses_to_one_percent(self):
        assert action_summary([{"motion": motion(240)}]) == "240%"

    def test_uneven_motion_lists_elements(self):
        assert action_summary([{"motion": motion(100, magic=150, fire=0)}]) == \
            "物理 100% 魔力 150% 火焰 0% 雷电 100% 圣 100%"

    def test_flat_damage_with_base_attack(self):
        assert action_summary([{"flat": {"holy": 180}, "addBaseAtk": True}]) == "圣 180+基础"

    def test_motion_and_flat_in_one_segment(self):
        assert action_summary([{"motion": motion(40), "flat": {"magic": 30}, "addBaseAtk": True}]) == "40% 魔力 30+基础"

    def test_base_attack_only(self):
        assert action_summary([{"addBaseAtk": True}]) == "武器基础"

    def test_consecutive_identical_segments_are_merged(self):
        hits = [{"motion": motion(35)}, {"motion": motion(35)}, {"motion": motion(80)}, {"motion": motion(35)}]
        assert action_summary(hits) == "35%×2 / 80% / 35%"

    def test_unusable_segments_are_skipped(self):
        hits = [
            {"motion": motion(10), "noFp": True},
            {"motion": motion(20), "notInvoked": True},
            {"motion": motion(30), "noDamage": True},
            {"motion": motion(40), "selfOrAllyOnly": True},
            {"motion": motion(50), "chargeBranch": "charged"},
            {"motion": motion(60), "chargeBranch": "partial"},
            {"motion": motion(70), "chargeBranch": "uncharged"},
            {"motion": motion(80), "chargeBranch": "both"},
        ]
        assert [usable_action_hit(hit) for hit in hits] == [False] * 6 + [True] * 2
        assert action_summary(hits) == "70% / 80%"

    def test_no_damage_at_all(self):
        assert action_summary([{"noDamage": True}, {}]) is None
        assert action_summary([]) is None

    def test_spell_hides_the_constant_100_percent_motion(self):
        hit = {"motion": motion(100), "flat": {"magic": 152}}
        assert action_summary([hit], spell=True) == "魔力 152"
        assert action_summary([hit]) == "100% 魔力 152"

    def test_spell_summary_includes_fp_cost(self):
        hit = {"motion": motion(100), "flat": {"magic": 152}}
        assert spell_summary(7, [hit]) == "FP 7 · 魔力 152"
        assert spell_summary(None, [hit]) == "魔力 152"
        assert spell_summary(7, [{"noDamage": True}]) is None

    def test_strip_action_prefix(self):
        assert strip_action_prefix("战技：神圣刀刃") == "神圣刀刃"
        assert strip_action_prefix("魔法: 辉石魔砾") == "辉石魔砾"
        assert strip_action_prefix("祷告：黄金树立誓") == "黄金树立誓"
        assert strip_action_prefix("神圣刀刃") == "神圣刀刃"


class TestSkillSpellLookup:
    info = WeaponInfo({
        "weapons": {"火焰匕首": {"type": "短剑", "rarity": "普通", "correct": [13, 73, 0, 0, 0], "id": 1000000},
                    "隐士的手杖": {"type": "辉石魔杖", "rarity": "普通", "correct": [0, 0, 100, 0, 0],
                                   "id": 33750000, "caster": True}},
        "skills": {"神圣刀刃": {"id": 201, "text": "圣 180+基础 / 65%", "byWeapon": {"2000000": "圣 200+基础"}},
                   "无数值战技": {"id": 5, "text": None, "byWeapon": {}}},
        "spells": {"辉石魔砾": {"id": 4000, "text": "FP 7 · 魔力 152"}},
    })

    def test_weapon_carries_id_and_caster_flag(self):
        dagger = self.info.lookup_weapon("火焰匕首")
        assert dagger.id == 1000000 and not dagger.caster
        assert self.info.lookup_weapon("隐士的手杖").caster

    def test_skill_lookup_ignores_prefix(self):
        skill = self.info.lookup_skill("战技：神圣刀刃")
        assert skill.name == "神圣刀刃" and skill.id == 201
        assert skill.by_weapon == {2000000: "圣 200+基础"}

    def test_skill_text_depends_on_weapon(self):
        skill = self.info.lookup_skill("神圣刀刃")
        assert skill.text_for(1000000) == "圣 180+基础 / 65%"
        assert skill.text_for(2000000) == "圣 200+基础"
        assert skill.text_for(None) == "圣 180+基础 / 65%"

    def test_spell_lookup(self):
        assert self.info.lookup_spell("魔法：辉石魔砾").text == "FP 7 · 魔力 152"
        assert self.info.lookup_skill("辉石魔砾") is None

    def test_unknown_action(self):
        assert self.info.lookup_skill("完全无关的文字") is None
        assert self.info.lookup_spell("完全无关的文字") is None

    def test_skill_without_damage_data_is_still_found(self):
        skill = self.info.lookup_skill("无数值战技")
        assert skill is not None and skill.text is None

    def test_data_without_skills_section(self):
        assert make_info().lookup_skill("神圣刀刃") is None


class TestRealData:
    """用仓库里实际打包的 data/weapons.json 做冒烟测试，防止数据格式和代码脱节"""
    info = load_weapon_info()

    def test_counts(self):
        assert self.info.weapon_count > 1000
        assert self.info.affix_count > 100

    def test_dagger(self):
        w = self.info.lookup_weapon("匕首")
        assert w is not None and w.type == "短剑"
        assert w.correct[:2] == [13, 73]

    def test_affix_with_values(self):
        a = self.info.lookup_affix("提升魔力属性攻击力")
        assert a is not None and a.has_values
        assert "魔力伤害" in a.display_text()

    def test_affix_without_values_is_still_recognized(self):
        a = self.info.lookup_affix("提升血量上限")
        assert a is not None and not a.has_values

    def test_every_weapon_name_matches_itself(self):
        # 抽样检查：每个武器名都应能被识别回自己（排除多个名称归一化后相同的少数情况）
        for name in list(self.info._weapons)[::7]:
            w = self.info.lookup_weapon(name)
            assert w is not None and w.name == name, name

    def test_skill_summaries(self):
        assert self.info.lookup_skill("神圣刀刃").text == "圣 180+基础 / 65%"
        assert self.info.lookup_skill("狮子斩").text == "240%"

    def test_same_name_skill_and_spell(self):
        assert self.info.lookup_skill("辉石魔砾").text
        assert self.info.lookup_spell("辉石魔砾").text == "FP 7 · 魔力 152"

    def test_caster_weapons_are_flagged(self):
        assert self.info.lookup_weapon("隐士的手杖").caster
        assert not self.info.lookup_weapon("匕首").caster

    def test_same_name_skills_of_unique_weapons_keep_their_own_numbers(self):
        # 两条同名的“不可挡之刃”分别属于直剑和拳套，合并成一行后仍要按武器区分
        skill = self.info.lookup_skill("不可挡之刃")
        texts = {skill.text_for(weapon_id) for weapon_id in (*skill.by_weapon, None)}
        assert texts == {"250%+基础", "297%"}
