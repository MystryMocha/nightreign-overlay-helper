"""
武器信息：属性补正、局内武器词条数值，以及战技 / 法术伤害摘要的查询
（数据见 data/weapons.json，由 scripts/build_weapon_data.py 生成）

本模块只负责“文字 -> 武器/词条/战技/法术 -> 展示文案”，不依赖 Qt / OpenCV，便于单独测试。
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
_STRIP_RE = re.compile(r"[\s·・•\-－—_:：,，.。、'\"“”‘’()（）\[\]【】<>《》|/\\!！?？~～※]+")
_NUMBER_RE = re.compile(r"([+-]?\d+(?:\.\d+)?%?)")
# 装备面板里战技 / 法术名前可能带的类别前缀：“战技：神圣刀刃”“魔法：辉石魔砾”
_ACTION_PREFIX_RE = re.compile(r"^(?:战技|魔法|祷告)\s*[:：]\s*")

# 战技 / 法术伤害摘要里的属性顺序与名称（与 weapons.json 的 hits.motion / hits.flat 键一致）
ELEM_ORDER = ("physical", "magic", "fire", "lightning", "holy")
ELEM_ZH = {"physical": "物理", "magic": "魔力", "fire": "火焰", "lightning": "雷电", "holy": "圣"}


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
    strict=True 时跳过“包含”这一步：折行合并出来的文字里，另一条词条的名字恰好被包含的概率更高，只认完全一致和少量错字
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
        self._cache: dict[tuple[str, bool], str | None] = {}

    def __len__(self) -> int:
        return len(self._norm_to_names)

    def _unique(self, norm: str) -> str | None:
        names = self._norm_to_names[norm]
        return names[0] if len(set(names)) == 1 else None

    def exact(self, text: str) -> str | None:
        """只认完全一致（忽略标点、空白和全半角）"""
        norm = normalize_text(text)
        return self._unique(norm) if norm in self._norm_to_names else None

    def match(self, text: str, strict: bool = False) -> str | None:
        key = (text, strict)
        if key in self._cache:
            return self._cache[key]
        result = self._match(normalize_text(text), strict)
        if len(self._cache) > 2000:
            self._cache.clear()
        self._cache[key] = result
        return result

    def _match(self, t: str, strict: bool = False) -> str | None:
        if len(t) < 2:
            return None
        if t in self._norm_to_names:
            return self._unique(t)

        # 行内包含完整名称（后面可能带强化等级、档位等少量多余字符）：取最长的
        contained = [] if strict else [
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
    id: int | None = None               # 武器 id，战技在不同武器上的动作不同时用它挑选
    caster: bool = False                # 法杖 / 圣印记：同名战技和法术优先显示法术

    def correct_parts(self) -> list[tuple[str, str, int]]:
        """(属性名, 评级, 补正数值)，只含有补正的属性"""
        return [(CORRECT_NAMES[i], grade_of(v), v) for i, v in enumerate(self.correct) if v > 0]

    def correct_text(self) -> str:
        parts = self.correct_parts()
        if not parts:
            return "基础补正：无"
        return "基础补正：" + " · ".join(f"{name} {grade} {value}" for name, grade, value in parts)


def usable_action_hit(hit: dict) -> bool:
    """带专注的普通施放。蓄力版、专注不足的弱化版、未调用段和不造成伤害的段不计入。"""
    if hit.get("noFp") or hit.get("notInvoked") or hit.get("noDamage") or hit.get("selfOrAllyOnly"):
        return False
    return hit.get("chargeBranch") not in ("charged", "partial")


def _segment_text(hit: dict, *, spell: bool) -> str | None:
    """一段攻击的文案：'240%'（各属性倍率一致）/ '魔力 137+基础'（固定伤害 + 武器基础攻击力）"""
    motion = hit.get("motion") or {}
    flat = {key: value for key, value in (hit.get("flat") or {}).items() if value}
    # 法术的倍率恒为 100%（伤害全在固定值里），不必再写
    show_motion = bool(motion) and not (spell and all(motion.get(key) == 100 for key in ELEM_ORDER))
    parts: list[str] = []
    if show_motion:
        present = [motion[key] for key in ELEM_ORDER if key in motion]
        if present and len(set(present)) == 1:
            parts.append(f"{present[0]}%")
        else:
            parts.extend(f"{ELEM_ZH[key]} {motion[key]}%" for key in ELEM_ORDER if key in motion)
    parts.extend(f"{ELEM_ZH[key]} {flat[key]}" for key in ELEM_ORDER if key in flat)
    if not parts:
        return "武器基础" if hit.get("addBaseAtk") else None
    text = " ".join(parts)
    return text + "+基础" if hit.get("addBaseAtk") else text


def _collapse(parts: list[str]) -> list[str]:
    """连续相同的段合并：['35%', '35%', '35%'] -> ['35%×3']"""
    collapsed: list[list] = []
    for part in parts:
        if collapsed and collapsed[-1][0] == part:
            collapsed[-1][1] += 1
        else:
            collapsed.append([part, 1])
    return [part if count == 1 else f"{part}×{count}" for part, count in collapsed]


def action_summary(hits: list[dict], *, spell: bool = False) -> str | None:
    """战技 / 法术各段伤害的一行摘要，没有可展示的伤害时返回 None"""
    parts = []
    for hit in hits:
        if usable_action_hit(hit) and (text := _segment_text(hit, spell=spell)):
            parts.append(text)
    return " / ".join(_collapse(parts)) if parts else None


def spell_summary(mp: int | None, hits: list[dict]) -> str | None:
    damage = action_summary(hits, spell=True)
    if not damage:
        return None
    return damage if mp is None else f"FP {mp} · {damage}"


@dataclass
class SkillLookup:
    name: str
    id: int
    text: str | None                    # 大多数武器上的摘要
    by_weapon: dict[int, str | None] = field(default_factory=dict)  # 动作与默认不同的武器 id -> 摘要

    def text_for(self, weapon_id: int | None) -> str | None:
        if weapon_id is not None and weapon_id in self.by_weapon:
            return self.by_weapon[weapon_id]
        return self.text


@dataclass
class SpellLookup:
    name: str
    id: int
    text: str | None

    @property
    def kind(self) -> str:
        """SPELL_SORCERY 魔法（id 4000~5999）/ SPELL_INCANTATION 祷告（id 6000 起）"""
        return SPELL_INCANTATION if self.id >= 6000 else SPELL_SORCERY

    def text_with_scaling(self, scaling: int | None) -> str | None:
        """
        按施法器的“魔法加成 / 祷告加成”换算伤害：法术伤害 = 法术基础值 × 加成 / 100
        （未计敌人防御、减伤和其他增伤效果）；没有加成数值时返回基础值文案
        """
        if not self.text or not scaling:
            return self.text
        scaled = _SPELL_DAMAGE_RE.sub(lambda m: f"{m.group(1)} {int(m.group(2)) * scaling // 100}", self.text)
        if scaled == self.text:     # 没有伤害数值可以换算
            return self.text
        return f"{scaled}（加成 {scaling}）"


SPELL_SORCERY = "sorcery"
SPELL_INCANTATION = "incantation"
SPELL_SCALING_LABELS = {SPELL_SORCERY: "魔法加成", SPELL_INCANTATION: "祷告加成"}
# 法术文案里的固定伤害：“物理 87”“100% 雷电 234”中的 87、234（不含“50%”这类倍率）
_SPELL_DAMAGE_RE = re.compile(r"(物理|魔力|火焰|雷电|圣) (\d+)(?![\d%])")


def strip_action_prefix(text: str) -> str:
    return _ACTION_PREFIX_RE.sub("", text.strip(), count=1)


class WeaponInfo:
    def __init__(self, data: dict):
        self.game_version: str = data.get("game_version", "")
        self._weapons: dict[str, dict] = data.get("weapons", {})
        self._affixes: dict[str, list[dict]] = data.get("affixes", {})
        self._no_value_affixes: set[str] = set(data.get("affix_names_without_values", []))
        self._skills: dict[str, dict] = data.get("skills", {})
        self._spells: dict[str, dict] = data.get("spells", {})
        self._weapon_index = NameIndex(self._weapons.keys())
        self._affix_index = NameIndex([*self._affixes.keys(), *self._no_value_affixes])
        self._skill_index = NameIndex(self._skills.keys())
        self._spell_index = NameIndex(self._spells.keys())

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
        return WeaponLookup(
            name=name, type=w["type"], rarity=w["rarity"], correct=list(w["correct"]),
            id=w.get("id"), caster=bool(w.get("caster")),
        )

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

    def lookup_skill(self, text: str) -> SkillLookup | None:
        name = self._skill_index.match(strip_action_prefix(text))
        if name is None:
            return None
        raw = self._skills[name]
        by_weapon = {int(weapon_id): summary for weapon_id, summary in raw.get("byWeapon", {}).items()}
        return SkillLookup(name=name, id=raw["id"], text=raw.get("text"), by_weapon=by_weapon)

    def lookup_spell(self, text: str) -> SpellLookup | None:
        name = self._spell_index.match(strip_action_prefix(text))
        if name is None:
            return None
        raw = self._spells[name]
        return SpellLookup(name=name, id=raw["id"], text=raw.get("text"))


_weapon_info: WeaponInfo | None = None


def load_weapon_info(path: str | None = None) -> WeaponInfo:
    with open(path or get_data_path(WEAPONS_DATA_PATH), "r", encoding="utf-8") as f:
        return WeaponInfo(json.load(f))


def get_weapon_info() -> WeaponInfo:
    global _weapon_info
    if _weapon_info is None:
        _weapon_info = load_weapon_info()
    return _weapon_info
