"""
武器信息：属性补正、局内词条，以及战技 / 法术伤害摘要的查询
（数据见 data/weapons.json，由 scripts/build_weapon_data.py 生成）

本模块只负责“文字 -> 武器/词条/战技/法术 -> 展示文案”，不依赖 Qt / OpenCV，便于单独测试。
"""
import json
import re
import unicodedata
from dataclasses import dataclass, field

from src.common import get_data_path

WEAPONS_DATA_PATH = "weapons.json"

CORRECT_NAMES = ["力量", "敏捷", "智力", "信仰", "感应"]
GRADE_THRESHOLDS = ((175, "S"), (140, "A"), (90, "B"), (60, "C"), (25, "D"), (1, "E"))

_TIER_PLUS_RE = re.compile(r"\s*\+\s*(\d{1,2})\s*$")
_TIER_ROMAN_RE = re.compile(r"\s*(iii|ii|i)\s*$")
_ROMAN = {"i": 1, "ii": 2, "iii": 3}
_LEVEL_SUFFIX_RE = re.compile(r"\s*(?:\+\s*\d{1,2}|lv\.?\s*\d{1,2})\s*$")
_STRIP_RE = re.compile(r"""[\s·・•\-－—_:：,，.。、'"“”‘’()（）\[\]【】<>《》|/\\!！?？~～]+""")
_NUMBER_RE = re.compile(r"([+-]?\d+(?:\.\d+)?%?)")
_ACTION_PREFIX_RE = re.compile(r"^(?:战技|魔法|祷告)\s*[:：]\s*")

ELEM_ORDER = ("physical", "magic", "fire", "lightning", "holy")
ELEM_ZH = {
    "physical": "物理",
    "magic": "魔力",
    "fire": "火焰",
    "lightning": "雷电",
    "holy": "圣",
}


def grade_of(value: int) -> str:
    for threshold, letter in GRADE_THRESHOLDS:
        if value >= threshold:
            return letter
    return "-"


def parse_tier(text: str) -> tuple[str, int | None]:
    """从 OCR 文本末尾拆出档位标记：'提升物理攻击力＋２' -> ('提升物理攻击力', 2)"""
    t = unicodedata.normalize("NFKC", text).lower()
    matched = _TIER_PLUS_RE.search(t)
    if matched:
        return t[:matched.start()].rstrip(), int(matched.group(1))
    matched = _TIER_ROMAN_RE.search(t)
    if matched:
        return t[:matched.start()].rstrip(), _ROMAN[matched.group(1)]
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
        cur = [i]
        row_min = i
        for j, cb in enumerate(b, 1):
            val = min(cur[j - 1] + 1, prev[j] + 1, prev[j - 1] + (ca != cb))
            cur.append(val)
            if val < row_min:
                row_min = val
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

    def __init__(self, names, max_extra_chars: int = 4):
        self.max_extra_chars = max_extra_chars
        self._norm_to_names: dict[str, list[str]] = {}
        for name in names:
            norm = normalize_text(name)
            if not norm:
                continue
            self._norm_to_names.setdefault(norm, []).append(name)
        self._by_len: dict[int, list[str]] = {}
        for norm in self._norm_to_names:
            self._by_len.setdefault(len(norm), []).append(norm)
        self._cache: dict[str, str | None] = {}

    def __len__(self) -> int:
        return len(self._norm_to_names)

    def _unique(self, norm: str) -> str | None:
        names = self._norm_to_names[norm]
        if len(set(names)) == 1:
            return names[0]
        return None

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
        contained = [
            norm for norm in self._norm_to_names
            if len(norm) >= self.MIN_SUBSTRING_LEN and norm in t
            and len(t) - len(norm) <= self.max_extra_chars
        ]
        if contained:
            return self._unique(max(contained, key=len))
        best: list[str] = []
        best_dist: int | None = None
        t_chars = set(t)
        for length in range(len(t) - 3, len(t) + 4):
            for norm in self._by_len.get(length, ()):
                budget = _edit_budget(max(len(norm), len(t)))
                if budget != 0 and len(set(norm) - t_chars) > budget:
                    continue
                dist = _edit_distance(norm, t, budget)
                if dist > budget:
                    continue
                if best_dist is None or dist < best_dist:
                    best_dist = dist
                    best = [norm]
                elif dist == best_dist:
                    best.append(norm)
        if len(best) == 1:
            return self._unique(best[0])
        return None


@dataclass
class AffixTier:
    tier: int
    text: str
    conditional: bool


@dataclass
class AffixLookup:
    name: str
    tiers: list[AffixTier]
    detected_tier: int | None
    roles: list[str] = field(default_factory=list)

    @property
    def has_values(self) -> bool:
        return bool(self.tiers)

    def display_text(self) -> str:
        """
        词条数值文案。识别出档位时只显示该档；否则把各档数值合并显示：
        魔力伤害 +6%/+9%/+12%（档位1/2/3）
        """
        tiers = sorted(self.tiers, key=lambda item: item.tier)
        if self.detected_tier is not None:
            chosen = [item for item in tiers if item.tier == self.detected_tier] or tiers[:1]
            return "；".join(_with_condition(item.text, item.conditional) for item in chosen)
        merged = _merge_tier_texts([item.text for item in tiers])
        conditional = any(item.conditional for item in tiers)
        if merged is not None and len(tiers) > 1:
            text = f"{merged}（档位{'/'.join(str(item.tier) for item in tiers)}）"
        elif merged is not None:
            text = merged
        else:
            text = "；".join(f"档位 {item.tier} {item.text}" for item in tiers)
        return _with_condition(text, conditional)


def _with_condition(text: str, conditional: bool) -> str:
    if conditional:
        return text + "（条件触发）"
    return text


def _merge_tier_texts(texts: list[str]) -> str | None:
    """
    把骨架相同、只有数字不同的各档文案合并：['魔力伤害 +6%', '魔力伤害 +9%'] -> '魔力伤害 +6%/+9%'
    骨架不一致时返回 None
    """
    if not texts:
        return None
    pieces = [_NUMBER_RE.split(text) for text in texts]
    skeleton = pieces[0][::2]
    if any(piece[::2] != skeleton for piece in pieces):
        return None
    merged: list[str] = []
    for index, part in enumerate(skeleton):
        merged.append(part)
        numbers = [piece[index * 2 + 1] for piece in pieces if index * 2 + 1 < len(piece)]
        if numbers:
            merged.append("/".join(dict.fromkeys(numbers)))
    return "".join(merged)


@dataclass
class WeaponLookup:
    name: str
    type: str
    rarity: str
    correct: list[int]
    id: int | None = None
    caster: bool = False
    skill_ids: tuple[int, ...] = ()

    def correct_parts(self) -> list[tuple[str, str, int]]:
        """(属性名, 评级, 补正数值)，只含有补正的属性"""
        parts = []
        for index, value in enumerate(self.correct):
            if value:
                parts.append((CORRECT_NAMES[index], grade_of(value), int(value)))
        return parts

    def correct_text(self) -> str:
        parts = self.correct_parts()
        if not parts:
            return "基础补正：无"
        return "基础补正：" + " · ".join(f"{name} {grade} {value}" for name, grade, value in parts)


def usable_action_hit(hit: dict) -> bool:
    """带专注的普通施放。蓄力版、专注不足的弱化版、未调用段和不造成伤害的段不计入。"""
    if hit.get("noFp") or hit.get("notInvoked") or hit.get("noDamage") or hit.get("selfOrAllyOnly"):
        return False
    if hit.get("chargeBranch") in ("charged", "partial"):
        return False
    return True


def _segment_text(hit: dict, *, spell: bool) -> str | None:
    motion = hit.get("motion") or {}
    flat = {key: value for key, value in (hit.get("flat") or {}).items() if value}
    show_motion = bool(motion)
    if spell and all(motion.get(key) == 100 for key in ELEM_ORDER):
        show_motion = False
    parts: list[str] = []
    if show_motion:
        present = [motion[key] for key in ELEM_ORDER if key in motion]
        if present and len(set(present)) == 1:
            parts.append(f"{present[0]}%")
        else:
            for key in ELEM_ORDER:
                if key in motion:
                    parts.append(f"{ELEM_ZH[key]} {motion[key]}%")
    for key in ELEM_ORDER:
        if key in flat:
            parts.append(f"{ELEM_ZH[key]} {flat[key]}")
    if not parts:
        return "武器基础" if hit.get("addBaseAtk") else None
    text = " ".join(parts)
    if hit.get("addBaseAtk"):
        text += "+基础"
    return text


def _collapse(parts: list[str]) -> list[str]:
    collapsed: list[list] = []
    for part in parts:
        if collapsed and collapsed[-1][0] == part:
            collapsed[-1][1] += 1
        else:
            collapsed.append([part, 1])
    return [part if count == 1 else f"{part}×{count}" for part, count in collapsed]


def action_summary(hits: list[dict], *, spell: bool = False) -> str | None:
    parts = []
    for hit in hits:
        if not usable_action_hit(hit):
            continue
        text = _segment_text(hit, spell=spell)
        if text:
            parts.append(text)
    if not parts:
        return None
    return " / ".join(_collapse(parts))


def spell_summary(mp, hits: list[dict]) -> str | None:
    damage = action_summary(hits, spell=True)
    if not damage:
        return None
    if mp is None:
        return damage
    return f"FP {mp} · {damage}"


@dataclass
class SkillLookup:
    name: str
    id: int
    text: str | None
    by_weapon: dict[int, str | None]

    def text_for(self, weapon_id: int | None) -> str | None:
        if weapon_id is not None and weapon_id in self.by_weapon:
            return self.by_weapon[weapon_id]
        return self.text


@dataclass
class SpellLookup:
    name: str
    id: int
    text: str | None


def strip_action_prefix(text: str) -> str:
    return _ACTION_PREFIX_RE.sub("", text.strip(), count=1)


class WeaponInfo:
    def __init__(self, data: dict):
        self.game_version = data.get("game_version") or ""
        self._weapons: dict = data.get("weapons") or {}
        self._affixes: dict = data.get("affixes") or {}
        self._no_value_affixes = set(data.get("affix_names_without_values") or [])
        self._skills: dict = data.get("skills") or {}
        self._spells: dict = data.get("spells") or {}
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
        stripped = _LEVEL_SUFFIX_RE.sub("", unicodedata.normalize("NFKC", text).lower())
        name = self._weapon_index.match(stripped)
        if name is None:
            return None
        weapon = self._weapons[name]
        return WeaponLookup(
            name=name,
            type=weapon.get("type") or "",
            rarity=weapon.get("rarity") or "",
            correct=list(weapon.get("correct") or []),
            id=weapon.get("id"),
            caster=bool(weapon.get("caster")),
            skill_ids=tuple(weapon.get("skillIds") or ()),
        )

    def lookup_affix(self, text: str) -> AffixLookup | None:
        base, tier = parse_tier(text)
        name = self._affix_index.match(base)
        if name is None:
            return None
        raw = self._affixes.get(name) or []
        tiers = sorted(
            (AffixTier(
                tier=int(item.get("tier") or 0),
                text=item.get("text") or "",
                conditional=bool(item.get("conditional")),
            ) for item in raw),
            key=lambda item: item.tier,
        )
        roles: list[str] = []
        for item in raw:
            for role in item.get("roles") or []:
                if role not in roles:
                    roles.append(role)
        return AffixLookup(name=name, tiers=tiers, detected_tier=tier, roles=roles)

    def lookup_skill(self, text: str) -> SkillLookup | None:
        name = self._skill_index.match(strip_action_prefix(text))
        if name is None:
            return None
        raw = self._skills[name]
        by_weapon = {}
        for key, value in (raw.get("byWeapon") or {}).items():
            by_weapon[int(key)] = value
        return SkillLookup(name=name, id=int(raw.get("id") or 0), text=raw.get("text"), by_weapon=by_weapon)

    def lookup_spell(self, text: str) -> SpellLookup | None:
        name = self._spell_index.match(strip_action_prefix(text))
        if name is None:
            return None
        raw = self._spells[name]
        return SpellLookup(name=name, id=int(raw.get("id") or 0), text=raw.get("text"))


def load_weapon_info(path: str | None = None) -> WeaponInfo:
    with open(get_data_path(path or WEAPONS_DATA_PATH), encoding="utf-8") as f:
        return WeaponInfo(json.load(f))


_weapon_info: WeaponInfo | None = None


def get_weapon_info() -> WeaponInfo:
    global _weapon_info
    if _weapon_info is None:
        _weapon_info = load_weapon_info()
    return _weapon_info
