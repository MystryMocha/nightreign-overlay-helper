"""
从社区整理的词条库生成 data/relics.json（遗物词条名 -> 具体数值文案）。

上游数据：https://github.com/sganggs/nightreign-relic-checker 的 data/nightreign-affixes-*.json（GPL-3.0）。
词条名取自游戏内简中文本；数值说明（“物理攻击力 +6%”这类）来自其中整理的 NightreignQuickRef（GPL-3.0），
并与 AttachEffectParam / SpEffectParam 的参数核对过一致。

用法：
    python scripts/build_relic_data.py --upstream <nightreign-relic-checker 的 data 目录>

只在游戏版本更新、需要刷新 data/relics.json 时运行，程序运行时不依赖上游数据。
"""
import argparse
import glob
import json
import os
import re
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_OUT = os.path.join(ROOT, "data", "relics.json")

SOURCES = [
    {
        "name": "nightreign-relic-checker (sganggs)",
        "url": "https://github.com/sganggs/nightreign-relic-checker",
        "license": "GPL-3.0",
        "use": "遗物词条库（nightreign-affixes）：游戏内简中词条名与数值说明",
    },
    {
        "name": "NightreignQuickRef (xxiixi)",
        "url": "https://github.com/xxiixi/NightreignQuickRef",
        "license": "GPL-3.0",
        "use": "词条数值说明文案（经上游整理）",
    },
    {
        "name": "ELDEN RING NIGHTREIGN regulation.bin / 游戏内文本",
        "license": "游戏数据，版权归 FromSoftware / Bandai Namco",
    },
]

# 说明里把多个要点连成一行时用的分隔符（“∘ 要点一 ∘ 要点二”）
_BULLET = "∘"
_LABEL_BULLET_RE = re.compile(rf"([:：])\s*{_BULLET}\s*")
_BULLET_RE = re.compile(rf"\s*{_BULLET}\s*")
# 词条名末尾的档位标记：“提升物理攻击力＋２”
_TIER_SUFFIX_RE = re.compile(r"\s*[+＋]\s*[0-9０-９]+\s*$")


def find_json(upstream: str, prefix: str) -> dict:
    paths = sorted(glob.glob(os.path.join(upstream, f"{prefix}-*.json")))
    if not paths:
        sys.exit(f"在 {upstream} 下找不到 {prefix}-*.json")
    with open(paths[-1], encoding="utf-8") as f:
        data = json.load(f)
    print(f"读取 {os.path.basename(paths[-1])}")
    return data


def clean_explanation(name: str, text: str) -> str:
    """
    整理成适合悬浮显示的一行文案：
      · 说明开头把词条名又念了一遍时（“延长魔法、祷告的有效时间 (延长50%，向下取整)”）去掉重复的名字，只留括号里的数值
      · “∘” 分隔的多个要点改用“；”连接
    """
    text = " ".join(text.split())
    base =_TIER_SUFFIX_RE.sub("", name).strip()
    if base and text.startswith(base):
        rest = text[len(base):].strip()
        if len(rest) > 2 and rest[0] in "(（" and rest[-1] in ")）":
            text = rest[1:-1].strip()
    text = _LABEL_BULLET_RE.sub(r"\1", text.strip())
    text = _BULLET_RE.sub("；", text.lstrip(f"{_BULLET} "))
    return text.strip("； ")


def build_affixes(affixes: list[dict]) -> tuple[dict[str, list[dict]], list[str]]:
    """
    游戏里显示的词条名 -> 各条词条数值。
    同名的不同词条（目前只有“提升血量上限”“提升专注值上限”“提升精力上限”：深夜遗物是百分比、普通遗物是固定点数）
    各自保留一条，并用 deep 标出是不是只出现在深夜遗物上，展示时才能分开。
    没有数值说明的词条名（如“出击时，会持有……”）单独列出，识别后可以明确告知“暂无数值数据”而不是静默忽略。
    """
    by_name: dict[str, list[dict]] = defaultdict(list)
    no_text: dict[str, None] = {}
    for affix in affixes:
        name = affix["name"].strip()
        text = clean_explanation(name, affix.get("explanation") or "")
        if not text:
            no_text[name] = None
            continue
        entry = {"id": affix["effectId"], "text": text, "deep": bool(affix.get("requiresCurse"))}
        if entry not in by_name[name]:
            by_name[name].append(entry)
    without_values = sorted(name for name in no_text if name not in by_name)
    return dict(by_name), without_values


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--upstream", required=True, help="nightreign-relic-checker 的 data 目录")
    parser.add_argument("--out", default=DEFAULT_OUT)
    args = parser.parse_args()

    source = find_json(args.upstream, "nightreign-affixes")
    affixes, without_values = build_affixes(source["affixes"])
    out = {
        "game_version": source.get("gameVersion"),
        "data_version": source.get("dataVersion"),
        "sources": SOURCES,
        "affix_names_without_values": without_values,
        "affixes": affixes,
    }
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"), sort_keys=False)
        f.write("\n")
    duplicated = sorted(name for name, entries in affixes.items() if len(entries) > 1)
    print(f"有数值的词条 {len(affixes)} 个，无数值词条 {len(without_values)} 个"
          + (f"；同名词条：{'、'.join(duplicated)}" if duplicated else "")
          + f" -> {args.out} ({os.path.getsize(args.out) // 1024} KB)")


if __name__ == "__main__":
    main()
