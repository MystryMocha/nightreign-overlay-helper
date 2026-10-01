"""
武器信息：属性补正与局内武器词条数值的查询（数据见 data/weapons.json，由 scripts/build_weapon_data.py 生成）

本模块只负责“文字 -> 武器/词条 -> 展示文案”，不依赖 Qt / OpenCV，便于单独测试。
"""
import json
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Iterable

from src.common import get_data_path

WEAPONS_DATA_PATH = "weapons.json"

CORRECT_NAMES = ["力量", "敏捷", "智力", "信仰", "感应"]

# 补正数值对应的评级（与艾尔登法环一致：S≥175 / A≥140 / B≥90 / C≥60 / D≥25 / E>0）
GRADE_THRESHOLDS = [(175, "S"), (140, "A"), (90, "B"), (60, "C"), (25, "D"), (1, "E")]

# 词条名后面可能跟着的档位标记：“+2”“＋２”（NFKC 后统一为 +2）与罗马数字“Ⅱ”（NFKC 后为 ii）
_TIER_PLUS_RE = re.compile(r"\s*\+\s*(\d{1,2})\s*$")
_TIER_ROMAN_RE = re.compile(r"\s*(iii|ii|i)\s*$")
_ROMAN = {"i": 1, "ii": 2, "iii": 3}
# 武器名后面可能带的强化等级，识别时忽略
_LEVEL_SUFFIX_RE = re.compile(r"\s*(?:\+\s*\d{1,2}|lv\.?\s*\d{1,2})\s*$")
# 比对前直接删掉的标点和空白（OCR 经常多识别或漏识别这些字符）
_STRIP_RE = re.compile(r"[\s·・•\-－—_:：,，.。、'\"“”‘’()（）\[\]【】<>《》|/\\!！?？~～]+")
_NUMBER_RE = re.compile(r"([+-]?\d+(?:\.\d+)?%?)")


def grade_of(value: int) -> str:
    for threshold, letter in GRADE_THRESHOLDS:
        if value >= threshold:
            return letter
    return "-"


def parse_tier(text: str) -> tuple[str, int | None]:
    """从 OCR 文本末尾拆出档位标记：'提升物理攻击力＋２' -> ('提升物理攻击力', 2)"""
    t = unicodedata.normalize("NFKC", text).lower()
    if m := _TIER_PLUS_RE.search(t):
        return t[:m.start()], int(m.group(1))
    if m := _TIER_ROMAN_RE.search(t):
        return t[:m.start()], _ROMAN[m.group(1)]
    return t, None


def normalize_text(text: str) -> str:
    t = unicodedata.normalize("NFKC", text).lower()
    return _STRIP_RE.sub("", t)


def _edit_budget(length: int) -> int:
    """允许的编辑距离：名字越长，越能容忍 OCR 错字"""
    if length <= 3:
        return 0
    if length <= 6:
        return 1
    if length <= 12:
        return 2
    return 3


def _edit_distance(a: str, b: str, limit: int) -> int:
    """Levenshtein 距离，超过 limit 时提前返回 limit + 1"""
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        row_min = cur[0]
        for j, cb in enumerate(b, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
            row_min = min(row_min, cur[j])
        if row_min > limit:
            return limit + 1
        prev = cur
    return prev[-1]


class NameIndex:
    """
    名称索引：把 OCR 识别出的一行文字匹配到已知名称
    依次尝试 完全一致 -> 包含（行内多出的字符数有限）-> 少量错字容忍；多个名称同样接近时视为无法确定
    """
    MIN_SUBSTRING_LEN = 3

    def __init__(self, names: Iterable[str], max_extra_chars: int = 4):
        self.max_extra_chars = max_extra_chars
        self._norm_to_names: dict[str, list[str]] = {}
        for name in names:
            norm = normalize_text(name)
            if norm:
                self._norm_to_names.setdefault(norm, []).append(name)
        self._by_len: dict[int, list[str]] = {}
        for norm in self._norm_to_names:
            self._by_len.setdefault(len(norm), []).append(norm)
        self._cache: dict[str, str | None] = {}

    def __len__(self) -> int:
        return len(self._norm_to_names)

    def _unique(self, norm: str) -> str | None:
        names = self._norm_to_names[norm]
        return names[0] if len(set(names)) == 1 else None

    def match(self, text: str) -> str | None:
        if text in self._cache:
            return self._cache[text]
        result = self._match(normalize_text(text))
        if len(self._cache) > 2000:
            self._cache.clear()
        self._cache[text] = result
        return result

    def _match(self, t: str) -> str | None:
        if len(t) < 2:
            return None
        if t in self._norm_to_names:
            return self._unique(t)

        # 行内包含完整名称（后面可能带强化等级、档位等少量多余字符）：取最长的
        contained = [
            norm for norm in self._norm_to_names
            if len(norm) >= self.MIN_SUBSTRING_LEN and norm in t
            and len(t) - len(norm) <= self.max_extra_chars
        ]
        if contained:
            return self._unique(max(contained, key=len))

        # OCR 错字：编辑距离最小且唯一的名称
        best_dist, best = None, []
        t_chars = set(t)
        for length in range(len(t) - 3, len(t) + 4):
            for norm in self._by_len.get(length, ()):
                budget = _edit_budget(max(len(norm), len(t)))
                if budget == 0 or len(set(norm) - t_chars) > budget:
                    continue
                dist = _edit_distance(norm, t, budget)
                if dist > budget:
                    continue
                if best_dist is None or dist < best_dist:
                    best_dist, best = dist, [norm]
                elif dist == best_dist:
                    best.append(norm)
        if len(best) == 1:
            return self._unique(best[0])
        return None


@dataclass
class AffixTier:
    tier: int
    text: str
    conditional: bool = False


@dataclass
class AffixLookup:
    name: str
    tiers: list[AffixTier]
    detected_tier: int | None = None    # OCR 文本里带的档位，没有为 None
    roles: list[str] = field(default_factory=list)

    @property
    def has_values(self) -> bool:
        return bool(self.tiers)

    def display_text(self) -> str:
        """
        词条数值文案。识别出档位时只显示该档；否则把各档数值合并显示：
        魔力伤害 +6%/+9%/+12%（档位1/2/3）
        """
        if not self.tiers:
            return ""
        tiers = self.tiers
        if self.detected_tier is not None:
            chosen = [t for t in tiers if t.tier == self.detected_tier]
            if chosen:
                return _with_condition(chosen[0].text, chosen[0].conditional)
        conditional = any(t.conditional for t in tiers)
        if len(tiers) == 1:
            return _with_condition(tiers[0].text, conditional)
        merged = _merge_tier_texts([t.text for t in tiers])
        tier_nos = "/".join(str(t.tier) for t in tiers)
        if merged is not None:
            return _with_condition(f"{merged}（档位{tier_nos}）", conditional)
        return _with_condition("；".join(f"档位{t.tier} {t.text}" for t in tiers), conditional)


def _with_condition(text: str, conditional: bool) -> str:
    return f"{text}（条件触发）" if conditional else text


def _merge_tier_texts(texts: list[str]) -> str | None:
    """
    把骨架相同、只有数字不同的各档文案合并：['魔力伤害 +6%', '魔力伤害 +9%'] -> '魔力伤害 +6%/+9%'
    骨架不一致时返回 None
    """
    parts = [_NUMBER_RE.split(t) for t in texts]
    skeletons = [p[0::2] for p in parts]
    if any(s != skeletons[0] for s in skeletons):
        return None
    merged = []
    for i, skeleton in enumerate(skeletons[0]):
        merged.append(skeleton)
        numbers = [p[1::2][i] for p in parts if i < len(p[1::2])]
        if numbers:
            unique = list(dict.fromkeys(numbers))
            merged.append("/".join(unique))
    return "".join(merged)


@dataclass
class WeaponLookup:
    name: str
    type: str
    rarity: str
    correct: list[int]

    def correct_parts(self) -> list[tuple[str, str, int]]:
        """(属性名, 评级, 补正数值)，只含有补正的属性"""
        return [(CORRECT_NAMES[i], grade_of(v), v) for i, v in enumerate(self.correct) if v > 0]

    def correct_text(self) -> str:
        parts = self.correct_parts()
        if not parts:
            return "基础补正：无"
        return "基础补正：" + " · ".join(f"{name} {grade} {value}" for name, grade, value in parts)


class WeaponInfo:
    def __init__(self, data: dict):
        self.game_version: str = data.get("game_version", "")
        self._weapons: dict[str, dict] = data.get("weapons", {})
        self._affixes: dict[str, list[dict]] = data.get("affixes", {})
        self._no_value_affixes: set[str] = set(data.get("affix_names_without_values", []))
        self._weapon_index = NameIndex(self._weapons.keys())
        self._affix_index = NameIndex([*self._affixes.keys(), *self._no_value_affixes])

    @property
    def weapon_count(self) -> int:
        return len(self._weapons)

    @property
    def affix_count(self) -> int:
        return len(self._affixes) + len(self._no_value_affixes)

    def lookup_weapon(self, text: str) -> WeaponLookup | None:
        t = _LEVEL_SUFFIX_RE.sub("", unicodedata.normalize("NFKC", text).lower())
        name = self._weapon_index.match(t)
        if name is None:
            return None
        w = self._weapons[name]
        return WeaponLookup(name=name, type=w["type"], rarity=w["rarity"], correct=list(w["correct"]))

    def lookup_affix(self, text: str) -> AffixLookup | None:
        base, tier = parse_tier(text)
        name = self._affix_index.match(base)
        if name is None and tier is not None:
            name = self._affix_index.match(text)    # 末尾的数字也许是名字的一部分，退回完整文本再试一次
            tier = None
        if name is None:
            return None
        tiers = [AffixTier(t["tier"], t["text"], t.get("conditional", False)) for t in self._affixes.get(name, [])]
        roles = sorted({r for t in self._affixes.get(name, []) for r in t.get("roles", [])})
        return AffixLookup(name=name, tiers=tiers, detected_tier=tier, roles=roles)


_weapon_info: WeaponInfo | None = None


def load_weapon_info(path: str | None = None) -> WeaponInfo:
    with open(path or get_data_path(WEAPONS_DATA_PATH), "r", encoding="utf-8") as f:
        return WeaponInfo(json.load(f))


def get_weapon_info() -> WeaponInfo:
    global _weapon_info
    if _weapon_info is None:
        _weapon_info = load_weapon_info()
    return _weapon_info
