"""
遗物词条数值：把 OCR 识别出的词条名匹配到词条库，得到游戏里看不到的具体数值
（数据见 data/relics.json，由 scripts/build_relic_data.py 生成）

和武器词条（src/weapon/info.py）是两套数据：同名词条（如“提升物理攻击力”“延长魔法、祷告的有效时间”）
在武器上和遗物上的数值并不相同，所以不能共用一张表。

本模块只负责“文字 -> 词条 -> 展示文案”，不依赖 Qt / OpenCV，便于单独测试。
"""
import json
import re
from dataclasses import dataclass, field

from src.common import get_data_path
from src.weapon.info import NameIndex, normalize_text

RELICS_DATA_PATH = "relics.json"

# 个别词条的说明很长（逐阶段的增伤表等），悬浮显示时截断，数值一般都在前面
MAX_TEXT_CHARS = 100

# 遗物词条的档位写在名字里（“提升物理攻击力＋２”是和“＋１”不同的另一条词条）。
# 识别文字紧跟在词条名后面的“+”或数字，说明档位没认全或被识别成了别的档位
_TIER_LEFTOVER_RE = re.compile(r"[+\d]")
_TIER_ONLY_RE = re.compile(r"\+?(\d{1,2})")


@dataclass
class RelicAffixEntry:
    id: int
    text: str
    deep: bool = False      # 只出现在深夜遗物上


@dataclass
class RelicAffixLookup:
    name: str
    entries: list[RelicAffixEntry] = field(default_factory=list)

    @property
    def has_values(self) -> bool:
        return bool(self.entries)

    def display_text(self) -> str:
        """
        词条数值文案。同名的不同词条（深夜遗物是百分比、普通遗物是固定点数）要分开写，否则会看错：
        深夜遗物：生命值上限+10% ｜ 普通遗物：+5点生命力（固定+100点生命值上限）
        """
        if not self.entries:
            return ""
        texts = list(dict.fromkeys(e.text for e in self.entries))
        if len(texts) == 1:
            return _shorten(texts[0])
        return " ｜ ".join(
            f"{'深夜遗物' if e.deep else '普通遗物'}：{_shorten(e.text)}" for e in self.entries)


def _shorten(text: str) -> str:
    return text if len(text) <= MAX_TEXT_CHARS else text[:MAX_TEXT_CHARS - 1] + "…"


class RelicInfo:
    def __init__(self, data: dict):
        self.game_version: str = data.get("game_version", "")
        self._affixes: dict[str, list[dict]] = data.get("affixes", {})
        self._no_value_affixes: set[str] = set(data.get("affix_names_without_values", []))
        self._index = NameIndex([*self._affixes.keys(), *self._no_value_affixes])

    @property
    def affix_count(self) -> int:
        return len(self._affixes) + len(self._no_value_affixes)

    def lookup_affix(self, text: str, strict: bool = False) -> RelicAffixLookup | None:
        """
        匹配一行（或几行折行合并后的）文字。strict=True 时只认完全一致和少量错字，用于折行合并的文字
        档位拿不准时宁可不显示，也不把另一档的数值显示出来
        """
        name = self._match_name(text, strict)
        if name is None:
            return None
        entries = [RelicAffixEntry(e["id"], e["text"], e.get("deep", False)) for e in self._affixes.get(name, [])]
        return RelicAffixLookup(name=name, entries=entries)

    def _match_name(self, text: str, strict: bool) -> str | None:
        name = self._index.match(text, strict=strict)
        if name is None:
            return None
        shown, known = normalize_text(text), normalize_text(name)
        if shown == known or not shown.startswith(known):
            return name
        # 词条名后面还跟着“+”或数字：游戏里这是另一档的词条（没有“+2”时的词条名是“+2”的前缀），
        # 把它认成不带档位的那条会显示错误的数值。只有补回漏识别的“+”后恰好是已知词条才接受
        leftover = shown[len(known):]
        if not _TIER_LEFTOVER_RE.match(leftover):
            return name
        if tier := _TIER_ONLY_RE.fullmatch(leftover):
            return self._index.exact(f"{known}+{tier.group(1)}")
        return None


_relic_info: RelicInfo | None = None


def load_relic_info(path: str | None = None) -> RelicInfo:
    with open(path or get_data_path(RELICS_DATA_PATH), "r", encoding="utf-8") as f:
        return RelicInfo(json.load(f))


def get_relic_info() -> RelicInfo:
    global _relic_info
    if _relic_info is None:
        _relic_info = load_relic_info()
    return _relic_info
