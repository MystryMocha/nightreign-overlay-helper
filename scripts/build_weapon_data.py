"""
从 nightreign-relic-checker 的 nightreign-skills JSON 生成 data/weapons.json。

武器补正、词条沿用已有 weapons.json（词条数值来自同一上游的 buffs 管线）。
本脚本补上武器 id / 是否施法器，以及战技、法术的一行伤害摘要。

用法：
    uv run python scripts/build_weapon_data.py
    uv run python scripts/build_weapon_data.py --skills path/to/nightreign-skills.json
"""
import argparse
import json
import sys
import urllib.request
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.weapon.info import action_summary, spell_summary

SKILLS_URL = (
    "https://raw.githubusercontent.com/sganggs/nightreign-relic-checker/main/data/"
    "nightreign-skills-v1.03.5.json"
)
CORRECT_KEYS = ["strength", "dexterity", "intelligence", "faith", "arcane"]
CASTER_TYPES = {"辉石魔杖", "圣印记"}


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def find_base(explicit: str | None) -> dict:
    candidates = []
    if explicit:
        candidates.append(Path(explicit))
    candidates.extend([
        Path("data/weapons.json"),
        Path("dist/nightreign-overlay-helper/data/weapons.json"),
    ])
    for path in candidates:
        if path.is_file():
            print(f"keep affixes from {path}")
            return load_json(path)
    raise SystemExit("找不到已有的 weapons.json，无法保留词条数据")


def load_skills(path: str | None) -> dict:
    if path:
        return load_json(Path(path))
    print(f"download {SKILLS_URL}")
    with urllib.request.urlopen(SKILLS_URL, timeout=120) as response:
        return json.load(response)


def variant_hits(skill: dict, variant: dict) -> list[dict]:
    by_id = {hit["atkId"]: hit for hit in skill.get("hits") or []}
    return [by_id[atk_id] for atk_id in variant.get("atkIds") or [] if atk_id in by_id]


def summarize_skill(skill: dict) -> dict:
    groups = []
    for variant in skill.get("variants") or []:
        groups.append((action_summary(variant_hits(skill, variant)), variant.get("weaponIds") or []))
    if not groups:
        groups.append((action_summary(skill.get("hits") or []), []))
    default = max(groups, key=lambda item: len(item[1]))[0]
    by_weapon = {}
    for text, weapon_ids in groups:
        if text == default:
            continue
        for weapon_id in weapon_ids:
            by_weapon[str(weapon_id)] = text
    return {"id": skill["id"], "text": default, "byWeapon": by_weapon}


def build_skills(skills: list[dict]) -> dict:
    built: dict[str, dict] = {}
    for skill in skills:
        name = skill.get("nameZh") or ""
        if not name or name == "无战技":
            continue
        summary = summarize_skill(skill)
        previous = built.get(name)
        if previous is None or (not previous.get("text") and summary.get("text")):
            built[name] = summary
    return built


def build_spells(spells: list[dict]) -> dict:
    built = {}
    for spell in spells:
        name = spell.get("nameZh") or ""
        if not name:
            continue
        built[name] = {
            "id": spell["id"],
            "text": spell_summary(spell.get("mp"), spell.get("hits") or []),
        }
    return built


def build_weapons(raw_weapons: list[dict]) -> dict:
    weapons = {}
    for weapon in raw_weapons:
        name = weapon.get("nameZh") or ""
        if not name:
            continue
        correct_map = weapon.get("correct") or {}
        weapons[name] = {
            "type": weapon.get("wepTypeZh") or "",
            "rarity": weapon.get("rarityZh") or "",
            "correct": [int(correct_map.get(key) or 0) for key in CORRECT_KEYS],
            "id": weapon.get("id"),
            "caster": weapon.get("wepTypeZh") in CASTER_TYPES,
            "skillIds": list(weapon.get("skillIds") or []),
        }
    return weapons


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skills", help="nightreign-skills JSON 路径；省略则从上游下载")
    parser.add_argument("--base", help="保留词条用的现有 weapons.json")
    parser.add_argument("--out", default="data/weapons.json")
    args = parser.parse_args()

    base = find_base(args.base)
    skills_doc = load_skills(args.skills)
    weapons = build_weapons(skills_doc["weapons"])
    skill_rows = build_skills(skills_doc["skills"])
    spell_rows = build_spells(skills_doc["spells"])
    valued = sum(1 for row in skill_rows.values() if row.get("text"))
    spell_valued = sum(1 for row in spell_rows.values() if row.get("text"))
    differing = sum(1 for row in skill_rows.values() if row.get("byWeapon"))
    print(
        f"weapons {len(weapons)} skills {len(skill_rows)} ({valued} with damage, {differing} vary by weapon) "
        f"spells {len(spell_rows)} ({spell_valued} with damage)"
    )
    names = Counter(skill.get("nameZh") for skill in skills_doc["skills"])
    dupes = [name for name, count in names.items() if name and name in skill_rows and count > 1]
    if dupes:
        print("duplicate skill names kept as one row:", ", ".join(dupes))

    sources = list(base.get("sources") or [])
    note = "EquipParamWeapon 属性补正、SwordArts / Magic 战技与法术伤害摘要、局内武器词条数值与简中名称"
    if sources and isinstance(sources[0], dict):
        sources[0] = {**sources[0], "use": note}

    document = {
        "game_version": skills_doc.get("gameVersion") or base.get("game_version"),
        "data_version": skills_doc.get("dataVersion") or base.get("data_version"),
        "correct_keys": list(base.get("correct_keys") or CORRECT_KEYS),
        "sources": sources,
        "affix_names_without_values": base.get("affix_names_without_values") or [],
        "weapons": weapons,
        "affixes": base.get("affixes") or {},
        "skills": skill_rows,
        "spells": spell_rows,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        json.dump(document, f, ensure_ascii=False, indent=1)
        f.write("\n")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
