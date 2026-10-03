"""
把 OCR 识别出的文字行匹配到武器/词条/战技/法术，生成要显示在对应文字旁边的标注（纯逻辑，不依赖 Qt / OpenCV）
"""
import re
from dataclasses import dataclass

from src.weapon.info import (
    SPELL_SCALING_LABELS, SkillLookup, SpellLookup, WeaponInfo, WeaponLookup, normalize_text,
)
from src.weapon.ocr import OcrLine

Rect = tuple[int, int, int, int]    # x, y, w, h

NO_DATA_TEXT = "暂无数值数据"

_SCALING_VALUE_RE = re.compile(r"^\d{2,3}$")
_SCALING_INLINE_RE = re.compile(r"(\d{2,3})$")


@dataclass
class WeaponAnnotation:
    kind: str       # "weapon" 武器属性补正 / "affix" 词条数值 / "skill" 战技 / "spell" 法术 / "mixed" 战技与法术同名且无法区分
    name: str       # 匹配到的武器名/词条名
    text: str       # 要显示的文案
    box: Rect       # 被识别文字行在屏幕上的位置（与截图区域相同的坐标系）
    dim: bool = False   # 数据里没有数值，只提示“已识别”


def _shown(text: str | None) -> tuple[str, bool]:
    return (text, False) if text else (NO_DATA_TEXT, True)


def _nearest_weapon(weapons: list[tuple[Rect, WeaponLookup]], box: Rect) -> WeaponLookup | None:
    """
    战技 / 法术行所属的武器：装备面板里武器名在战技和法术的上方，所以优先取上方最近的；
    对比面板有左右两列武器时，水平位置相差越大越不可能是同一列
    """
    if not weapons:
        return None
    above = [item for item in weapons if item[0][1] <= box[1] + 4]
    return min(above or weapons, key=lambda item: abs(item[0][1] - box[1]) + 2 * abs(item[0][0] - box[0]))[1]


def _find_spell_scalings(entries: list[tuple[str, Rect]]) -> list[tuple[Rect, str, int]]:
    """
    面板上的“魔法加成 / 祷告加成”及其数值，返回 [(标签位置, 法术种类, 加成)]
    数值通常被识别成标签同一行右侧单独的一行，也可能和标签连在一起（“祷告加成220”）
    """
    found: list[tuple[Rect, str, int]] = []
    for text, box in entries:
        norm = normalize_text(text)
        kind = next((k for k, label in SPELL_SCALING_LABELS.items() if label in norm), None)
        if kind is None:
            continue
        if m := _SCALING_INLINE_RE.search(norm):
            found.append((box, kind, int(m.group(1))))
            continue
        center = box[1] + box[3] / 2
        values = [
            (other[0] - (box[0] + box[2]), int(normalize_text(t)))
            for t, other in entries
            if _SCALING_VALUE_RE.match(normalize_text(t)) and other[0] >= box[0] + box[2] - 4
            and abs(other[1] + other[3] / 2 - center) <= max(box[3], other[3]) * 0.6
        ]
        if values:
            found.append((box, kind, min(values)[1]))
    return found


def _nearest_scaling(scalings: list[tuple[Rect, str, int]], kind: str, box: Rect) -> int | None:
    """法术所属施法器的加成：与 _nearest_weapon 一样优先取同一列、上方最近的"""
    same = [(rect, value) for rect, k, value in scalings if k == kind]
    if not same:
        return None
    above = [item for item in same if item[0][1] <= box[1] + 4]
    return min(above or same, key=lambda item: abs(item[0][1] - box[1]) + 2 * abs(item[0][0] - box[0]))[1]


def _action_annotation(text: str, box: Rect, skill: SkillLookup | None, spell: SpellLookup | None,
                       weapon: WeaponLookup | None, spell_scaling: int | None = None) -> WeaponAnnotation | None:
    """
    战技和法术可能同名（如“辉石魔砾”）：行首有“战技：”“魔法：”前缀时按前缀，
    否则按上方武器是不是施法器；找不到武器时两个摘要都显示
    """
    if skill is None and spell is None:
        return None
    text = text.strip()
    prefer_spell = text.startswith(("魔法", "祷告"))
    prefer_skill = text.startswith("战技")
    if skill is not None and spell is not None and not prefer_skill and not prefer_spell:
        if weapon is None:
            skill_text, skill_dim = _shown(skill.text_for(None))
            spell_text, spell_dim = _shown(spell.text_with_scaling(spell_scaling))
            return WeaponAnnotation("mixed", skill.name, f"战技：{skill_text} · 法术：{spell_text}", box,
                                    dim=skill_dim and spell_dim)
        prefer_spell, prefer_skill = weapon.caster, not weapon.caster
    if spell is not None and (prefer_spell or skill is None):
        shown, dim = _shown(spell.text_with_scaling(spell_scaling))
        return WeaponAnnotation("spell", spell.name, shown, box, dim=dim)
    shown, dim = _shown(skill.text_for(weapon.id if weapon is not None else None))
    return WeaponAnnotation("skill", skill.name, shown, box, dim=dim)


def build_annotations(
    lines: list[OcrLine],
    info: WeaponInfo,
    origin: tuple[int, int],
    scale: float = 1.0,
    min_score: float = 0.5,
    ignore_texts: set[str] | None = None,
) -> tuple[list[WeaponAnnotation], list[Rect]]:
    """
    Args:
        lines: OCR 文字行，坐标相对送去识别的图像
        origin: 识别图像左上角对应的屏幕坐标
        scale: 送去识别的图像相对屏幕的缩放（<1 表示识别前缩小过）
        ignore_texts: 要忽略的文字（本程序自己画上去的标注，截图方式可能截到悬浮窗）

    Returns:
        (标注列表, 所有文字行在屏幕上的位置——用于标注布局时避开其他文字)
    """
    ignored = {normalize_text(t) for t in (ignore_texts or set()) if len(normalize_text(t)) >= 4}
    ox, oy = origin
    annotations: list[WeaponAnnotation] = []
    line_boxes: list[Rect] = []
    weapons: list[tuple[Rect, WeaponLookup]] = []
    pending: list[tuple[str, Rect]] = []    # 不是武器也不是词条的行，可能是战技 / 法术名

    for line in lines:
        if line.score < min_score:
            continue
        norm = normalize_text(line.text)
        # 注意不按名称去重：对比面板里两把武器可能带同名词条，各自都要有标注
        if any(norm == t or (len(norm) >= 4 and norm in t) or t in norm for t in ignored):
            continue
        x, y, w, h = line.box
        box = (ox + int(x / scale), oy + int(y / scale), max(1, int(w / scale)), max(1, int(h / scale)))
        line_boxes.append(box)

        affix = info.lookup_affix(line.text)
        if affix is not None:
            if affix.has_values:
                annotations.append(WeaponAnnotation("affix", affix.name, affix.display_text(), box))
            else:
                annotations.append(WeaponAnnotation("affix", affix.name, NO_DATA_TEXT, box, dim=True))
            continue

        weapon = info.lookup_weapon(line.text)
        if weapon is not None:
            annotations.append(WeaponAnnotation("weapon", weapon.name, weapon.correct_text(), box))
            weapons.append((box, weapon))
            continue

        pending.append((line.text, box))

    # 战技 / 法术要按上方的武器挑选动作，所以等武器都找到后再处理
    # 法术伤害按所在施法器面板上的“魔法加成 / 祷告加成”换算
    scalings = _find_spell_scalings(pending)
    for text, box in pending:
        spell = info.lookup_spell(text)
        scaling = _nearest_scaling(scalings, spell.kind, box) if spell is not None else None
        annotation = _action_annotation(
            text, box, info.lookup_skill(text), spell, _nearest_weapon(weapons, box), scaling)
        if annotation is not None:
            annotations.append(annotation)

    annotations.sort(key=lambda ann: (ann.box[1], ann.box[0]))    # 保持从上到下的顺序，布局时先放上面的
    return annotations, line_boxes
