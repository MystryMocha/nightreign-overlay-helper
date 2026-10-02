import json

from src.ui.weapon_overlay import KIND_COLORS, SKILL_COLOR, SPELL_COLOR, WEAPON_COLOR
from src.weapon.annotate import NO_DATA_TEXT, build_annotations
from src.weapon.info import WeaponInfo
from src.weapon.layout import POSITION_RIGHT, layout_annotations
from src.weapon.ocr import OcrLine


def load_info() -> WeaponInfo:
    with open("data/weapons.json", encoding="utf-8") as f:
        return WeaponInfo(json.load(f))


def line(text: str, y: int) -> OcrLine:
    return OcrLine(text, (0, y, 120, 18), 0.99)


def kinds(lines, info):
    annotations, _boxes = build_annotations(lines, info, (0, 0))
    return annotations


def test_holy_blade_uses_the_weapon_above():
    info = load_info()
    annotations = kinds([line("送葬者的铁锤", 0), line("神圣刀刃", 40)], info)
    weapon = next(item for item in annotations if item.kind == "weapon")
    skill = next(item for item in annotations if item.kind == "skill")
    assert weapon.text == "基础补正：力量 C 64 · 敏捷 D 28"
    assert skill.name == "神圣刀刃"
    assert skill.text == "圣 180+基础 / 65%"
    assert skill.dim is False


def test_glintstone_pebble_follows_caster_or_melee():
    info = load_info()
    spell_side = kinds([line("辉石杖", 0), line("辉石魔砾", 40)], info)
    spell = next(item for item in spell_side if item.kind == "spell")
    assert spell.text == "FP 7 · 魔力 152"

    skill_side = kinds([line("匕首", 0), line("辉石魔砾", 40)], info)
    skill = next(item for item in skill_side if item.kind == "skill")
    assert skill.text == info.lookup_skill("辉石魔砾").text
    assert "FP" not in skill.text

    mixed = kinds([line("辉石魔砾", 0)], info)
    assert len(mixed) == 1
    assert mixed[0].kind == "mixed"
    assert mixed[0].text.startswith("战技：")
    assert "法术：" in mixed[0].text

    prefixed = kinds([line("辉石杖", 0), line("战技：辉石魔砾", 40)], info)
    assert prefixed[-1].kind == "skill"
    spelled = kinds([line("匕首", 0), line("魔法：辉石魔砾", 40)], info)
    assert spelled[-1].kind == "spell"


def test_blind_spot_and_buff_with_no_damage():
    info = load_info()
    blind = kinds([line("战技：盲击", 0)], info)
    assert len(blind) == 1
    assert blind[0].kind == "skill"
    assert blind[0].dim is False
    assert "%" in blind[0].text

    vow = kinds([line("黄金树立誓", 0)], info)
    assert vow[0].kind == "mixed"
    assert vow[0].dim is True
    assert NO_DATA_TEXT in vow[0].text


def test_skill_variant_follows_weapon_above():
    info = load_info()
    blind = info.lookup_skill("盲击")
    weapon_id = next(iter(blind.by_weapon))
    weapon_name = next(name for name, row in info._weapons.items() if row.get("id") == weapon_id)
    annotations = kinds([line(weapon_name, 0), line("盲击", 40)], info)
    skill = next(item for item in annotations if item.kind == "skill")
    assert skill.text == blind.text_for(weapon_id)
    assert skill.text != blind.text


def test_skill_and_spell_colors_differ_from_weapons():
    assert KIND_COLORS["skill"] == SKILL_COLOR
    assert KIND_COLORS["spell"] == SPELL_COLOR
    assert len({KIND_COLORS["weapon"], KIND_COLORS["skill"], KIND_COLORS["spell"], WEAPON_COLOR}) == 3


def test_annotation_sits_to_the_right_of_its_line():
    placed = layout_annotations(
        [(10, 10, 40, 16)], [(80, 16)], [(10, 10, 40, 16)], POSITION_RIGHT, (0, 0, 400, 200), gap=4,
    )
    assert placed[0][0] >= 10 + 40
