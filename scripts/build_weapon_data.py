"""
从社区整理的解包数据生成 data/weapons.json（武器属性补正 + 局内武器词条数值 + 战技 / 法术伤害摘要）。

上游数据：https://github.com/sganggs/nightreign-relic-checker 的 data/ 目录（GPL-3.0，
由 regulation.bin 的 EquipParamWeapon / SpEffectParam / AttachEffectParam 与游戏内简中文本整理而成）。

用法：
    python scripts/build_weapon_data.py --upstream <nightreign-relic-checker 的 data 目录>

只在游戏版本更新、需要刷新 data/weapons.json 时运行，程序运行时不依赖上游数据。
"""
import argparse
import glob
import json
import os
import sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src.weapon.info import action_summary, spell_summary    # noqa: E402  摘要文案与程序里的展示逻辑共用

DEFAULT_OUT = os.path.join(ROOT, "data", "weapons.json")

SOURCES = [
    {
        "name": "nightreign-relic-checker (sganggs)",
        "url": "https://github.com/sganggs/nightreign-relic-checker",
        "license": "GPL-3.0",
        "use": "EquipParamWeapon 属性补正、局内武器词条（AttachEffectParam/SpEffectParam）数值、"
               "战技 / 法术（SwordArts / Magic）伤害摘要与简中名称",
    },
    {
        "name": "ELDEN RING NIGHTREIGN regulation.bin / 游戏内文本",
        "license": "游戏数据，版权归 FromSoftware / Bandai Namco",
    },
]

# 武器伤害倍率里五种伤害类型的字段（全部相同时合并为“伤害”）
DAMAGE_RATE_KEYS = ["physicsAttackRate", "magicAttackRate", "fireAttackRate",
                    "thunderAttackRate", "darkAttackRate"]
ATTACK_POWER_RATE_KEYS = ["physicsAttackPowerRate", "magicAttackPowerRate", "fireAttackPowerRate",
                          "thunderAttackPowerRate", "darkAttackPowerRate"]

CORRECT_KEYS = ["strength", "dexterity", "intelligence", "faith", "arcane"]
# 这两类武器拿在手里时，同名的战技 / 法术优先按法术显示
CASTER_TYPES = {"辉石魔杖", "圣印记"}


def find_json(upstream: str, prefix: str) -> dict:
    paths = sorted(glob.glob(os.path.join(upstream, f"{prefix}-*.json")))
    if not paths:
        sys.exit(f"在 {upstream} 下找不到 {prefix}-*.json")
    with open(paths[-1], encoding="utf-8") as f:
        data = json.load(f)
    print(f"读取 {os.path.basename(paths[-1])}")
    return data


def num(v: float) -> str:
    """去掉浮点误差并去掉多余的 0：1.0600000000000001 -> 1.06"""
    return f"{round(v, 2):g}"


def strip_suffix(label: str, *suffixes: str) -> str:
    for s in suffixes:
        if label.endswith(s) and len(label) > len(s):
            return label[:-len(s)]
    return label


def format_rates(rates: dict, rate_fields: dict) -> list[str]:
    """
    把一个 SpEffect 的 rates 转成玩家能读懂的文案，例如 {"magicAttackRate": 1.06} -> "魔力伤害 +6%"
    倍率类显示为相对 1 的百分比变化，加算类显示为点数，开关类忽略。
    """
    rates = dict(rates)
    parts: list[str] = []

    # 五种伤害倍率完全一致时合并为一条
    # 不写“全部伤害”：很多词条只对特定攻击生效（致命一击、蓄力攻击等），作用范围由紧邻的词条名体现
    for keys, label in ((DAMAGE_RATE_KEYS, "伤害"), (ATTACK_POWER_RATE_KEYS, "攻击力")):
        vals = [rates.get(k) for k in keys]
        if all(v is not None for v in vals) and len(set(vals)) == 1:
            parts.append(f"{label} {pct_text(vals[0])}")
            for k in keys:
                del rates[k]

    for key, value in rates.items():
        field = rate_fields.get(key)
        if not field:
            continue
        kind = field.get("valueKind")
        label = field["zh"]
        if kind == "multiplier":
            parts.append(f"{strip_suffix(label, '倍率')} {pct_text(value)}")
        elif kind == "flat":
            parts.append(f"{strip_suffix(label, '加算')} {value:+g}")
        # flag / special 等不是可直接展示的数值
    return parts


def pct_text(multiplier: float) -> str:
    pct = round((multiplier - 1.0) * 100, 2)
    return f"{pct:+g}%"


def build_weapons(skills: dict) -> dict:
    weapons: dict[str, dict] = {}
    for w in skills["weapons"]:
        name = w["nameZh"]
        if name in weapons:
            continue    # 少数重名行（不同来源的同一把武器）数值一致，取第一条
        correct = [int(w.get("correct", {}).get(k, 0)) for k in CORRECT_KEYS]
        weapons[name] = {
            "type": w["wepTypeZh"],
            "rarity": w["rarityZh"],
            "correct": correct,
            "id": w["id"],
            "caster": w["wepTypeZh"] in CASTER_TYPES,
        }
    return weapons


def variant_hits(skill: dict, variant: dict) -> list[dict]:
    by_id = {hit["atkId"]: hit for hit in skill.get("hits") or []}
    return [by_id[atk_id] for atk_id in variant.get("atkIds") or [] if atk_id in by_id]


def skill_groups(skill: dict) -> list[tuple[str | None, list[int]]]:
    """战技的 (伤害摘要, 带这个动作套的武器 id 列表)；同一战技在不同武器上的动作套可能不同（variants）"""
    groups = [(action_summary(variant_hits(skill, v)), v.get("weaponIds") or []) for v in skill.get("variants") or []]
    return groups or [(action_summary(skill.get("hits") or []), [])]


def build_skills(skills: list[dict]) -> dict:
    """
    战技名 -> 伤害摘要。出现在最多武器上的摘要作为默认文案 text，其余武器单独记在 byWeapon。
    少数战技重名（专属武器各自一条，数值不同），按名字合并后同样用 byWeapon 区分
    """
    ids: dict[str, int] = {}
    groups_by_name: dict[str, list] = defaultdict(list)
    for skill in skills:
        name = skill["nameZh"]
        if name == "无战技":
            continue
        ids.setdefault(name, skill["id"])
        groups_by_name[name].extend(skill_groups(skill))
    built = {}
    for name, groups in groups_by_name.items():
        default = max(groups, key=lambda group: len(group[1]))[0]
        by_weapon = {str(wid): text for text, weapon_ids in groups if text != default for wid in weapon_ids}
        built[name] = {"id": ids[name], "text": default, "byWeapon": by_weapon}
    return built


def build_spells(spells: list[dict]) -> dict:
    return {
        spell["nameZh"]: {"id": spell["id"], "text": spell_summary(spell.get("mp"), spell.get("hits") or [])}
        for spell in spells
    }


def build_affixes(buffs: dict, relics: dict) -> dict:
    """
    局内武器词条：游戏里显示的词条名（AttachEffectName）-> 各档位数值
    只收录上游数据里有数值的词条（伤害、异常累积、消耗倍率等）
    """
    rate_fields = {f["key"]: f for f in buffs["rateFields"]}
    buff_by_sp = {b["spEffectId"]: b for b in buffs["buffs"]}
    # 游戏内显示的词条名
    game_names = {a["effectId"]: a["name"] for a in relics["extraAffixes"]}

    # 词条名 -> 档位 -> 文案集合
    by_name: dict[str, dict] = defaultdict(lambda: defaultdict(lambda: {"texts": [], "roles": set(), "conditional": False}))
    skipped_no_text = 0
    for affix in buffs["weaponAffixes"]:
        name = game_names.get(affix["attachEffectId"], affix["nameZh"])
        tier = affix.get("potency") or 0
        entry = by_name[name][tier]
        for sid in affix["spEffectIds"]:
            buff = buff_by_sp.get(sid)
            if buff is None:
                continue
            texts = format_rates(buff.get("rates", {}), rate_fields)
            if not texts:
                skipped_no_text += 1
                continue
            text = "，".join(texts)
            if text not in entry["texts"]:
                entry["texts"].append(text)
            if buff.get("activation") not in (None, "passive"):
                entry["conditional"] = True
        entry["roles"].update(affix.get("roles", []))

    affixes: dict[str, list] = {}
    for name, tiers in by_name.items():
        tier_list = []
        for tier in sorted(tiers):
            entry = tiers[tier]
            if not entry["texts"]:
                continue
            tier_list.append({
                "tier": tier,
                "text": "；".join(entry["texts"]),
                "conditional": entry["conditional"],
                "roles": sorted(entry["roles"]),
            })
        if tier_list:
            affixes[name] = tier_list
    print(f"词条: {len(affixes)} 个名称有数值（{skipped_no_text} 个 SpEffect 没有可展示的数值字段）")
    return affixes


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--upstream", required=True, help="nightreign-relic-checker 的 data 目录")
    parser.add_argument("--out", default=DEFAULT_OUT)
    args = parser.parse_args()

    skills = find_json(args.upstream, "nightreign-skills")
    buffs = find_json(args.upstream, "nightreign-buffs")
    relics = find_json(args.upstream, "nightreign-relics")

    weapons = build_weapons(skills)
    affixes = build_affixes(buffs, relics)
    skill_rows = build_skills(skills["skills"])
    spell_rows = build_spells(skills["spells"])
    duplicated = sorted(n for n, count in Counter(s["nameZh"] for s in skills["skills"]).items() if count > 1 and n in skill_rows)
    print(f"战技: {len(skill_rows)} 个（{sum(1 for r in skill_rows.values() if r['text'])} 个有伤害，"
          f"{sum(1 for r in skill_rows.values() if r['byWeapon'])} 个因武器而异），"
          f"法术: {len(spell_rows)} 个（{sum(1 for r in spell_rows.values() if r['text'])} 个有伤害）"
          + (f"；重名战技已合并：{'、'.join(duplicated)}" if duplicated else ""))

    all_affix_names = {a["name"] for a in relics["extraAffixes"] if 8000000 <= a["effectId"] < 9000000}
    out = {
        "game_version": skills.get("gameVersion"),
        "data_version": skills.get("dataVersion"),
        "correct_keys": CORRECT_KEYS,
        "sources": SOURCES,
        # 游戏里存在但上游数据没有数值的词条名，用于识别后明确告知“暂无数值”而不是静默忽略
        "affix_names_without_values": sorted(n for n in all_affix_names if n not in affixes and not n.startswith("词条 ")),
        "weapons": weapons,
        "affixes": affixes,
        "skills": skill_rows,
        "spells": spell_rows,
    }
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"), sort_keys=False)
        f.write("\n")
    print(f"武器 {len(weapons)} 把，有数值的词条 {len(affixes)} 个，"
          f"无数值词条 {len(out['affix_names_without_values'])} 个 -> {args.out} ({os.path.getsize(args.out) // 1024} KB)")


if __name__ == "__main__":
    main()
