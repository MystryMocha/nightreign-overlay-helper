import json

from src.weapon.info import (
    WeaponInfo,
    action_summary,
    grade_of,
    parse_tier,
    spell_summary,
)


def load_info() -> WeaponInfo:
    with open("data/weapons.json", encoding="utf-8") as f:
        return WeaponInfo(json.load(f))


def test_grade_and_tier_parsing():
    assert grade_of(64) == "C"
    assert grade_of(28) == "D"
    assert grade_of(0) == "-"
    assert parse_tier("提升物理攻击力＋２") == ("提升物理攻击力", 2)
    assert parse_tier("某某战技 ii")[1] == 2


def test_dagger_scaling_and_prefixed_name_is_not_a_weapon():
    info = load_info()
    dagger = info.lookup_weapon("匕首")
    assert dagger is not None
    assert dagger.correct_text() == "基础补正：力量 E 13 · 敏捷 C 73"
    assert info.lookup_weapon("战技：匕首风暴") is None


def test_affix_tiers_merge():
    info = load_info()
    affix = info.lookup_affix("提升魔力属性攻击力")
    assert affix is not None
    assert affix.display_text() == "魔力伤害 +6%/+9%/+12%（档位1/2/3）"


def test_action_summary_drops_charged_and_no_fp_hits():
    hits = [
        {"motion": {"physical": 200}, "chargeBranch": "charged"},
        {"motion": {"physical": 40}, "noFp": True},
        {"motion": {"physical": 70}},
        {"motion": {"physical": 70}},
        {"flat": {"holy": 180}, "addBaseAtk": True},
        {"motion": {key: 65 for key in ("physical", "magic", "fire", "lightning", "holy")}},
    ]
    assert action_summary(hits) == "70%×2 / 圣 180+基础 / 65%"


def test_spell_placeholder_motion_is_hidden():
    hits = [{
        "motion": {key: 100 for key in ("physical", "magic", "fire", "lightning", "holy")},
        "flat": {"magic": 152},
    }]
    assert spell_summary(7, hits) == "FP 7 · 魔力 152"
    assert action_summary([{"noDamage": True, "motion": {"physical": 100}}]) is None


def test_named_skill_and_spell_summaries():
    info = load_info()
    hammer = info.lookup_weapon("送葬者的铁锤")
    holy = info.lookup_skill("神圣刀刃")
    assert hammer is not None and hammer.id == 11750000
    assert hammer.correct_text() == "基础补正：力量 C 64 · 敏捷 D 28"
    assert holy is not None
    assert holy.text_for(hammer.id) == "圣 180+基础 / 65%"
    assert info.lookup_skill("狮子斩").text == "240%"
    pebble = info.lookup_spell("辉石魔砾")
    assert pebble is not None and pebble.text == "FP 7 · 魔力 152"
    skill = info.lookup_skill("辉石魔砾")
    assert skill is not None and skill.text != pebble.text
    assert info.lookup_skill("黄金树立誓").text is None
    assert info.lookup_spell("黄金树立誓").text is None
    assert info.lookup_skill("战技：盲击") is not None
    staff = info.lookup_weapon("辉石杖")
    assert staff is not None and staff.caster is True
