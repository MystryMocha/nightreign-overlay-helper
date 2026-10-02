"""
把 OCR 识别出的文字行匹配到武器/词条/战技/法术，生成要显示在对应文字旁边的标注（纯逻辑，不依赖 Qt / OpenCV）
"""
from dataclasses import dataclass

from src.weapon.info import SkillLookup, SpellLookup, WeaponInfo, WeaponLookup, normalize_text
from src.weapon.ocr import OcrLine

Rect = tuple[int, int, int, int]

NO_DATA_TEXT = "暂无数值数据"


@dataclass
class WeaponAnnotation:
    kind: str
    name: str
    text: str
    box: Rect
    dim: bool = False


def _shown(text: str | None) -> tuple[str, bool]:
    if text:
        return text, False
    return NO_DATA_TEXT, True


def _nearest_weapon(weapons: list[tuple[Rect, WeaponLookup]], box: Rect) -> WeaponLookup | None:
    if not weapons:
        return None
    line_y = box[1]
    above = [(rect, weapon) for rect, weapon in weapons if rect[1] <= line_y + 4]
    pool = above or weapons
    return min(pool, key=lambda item: abs(item[0][1] - line_y))[1]


def _action_annotation(text: str, box: Rect, skill: SkillLookup | None, spell: SpellLookup | None,
                       weapon: WeaponLookup | None) -> WeaponAnnotation | None:
    if skill is None and spell is None:
        return None
    prefer_skill = text.startswith("战技")
    prefer_spell = text.startswith("魔法") or text.startswith("祷告")
    weapon_id = weapon.id if weapon is not None else None
    if skill is not None and spell is not None and not prefer_skill and not prefer_spell:
        if weapon is None:
            skill_text, skill_dim = _shown(skill.text_for(None))
            spell_text, spell_dim = _shown(spell.text)
            return WeaponAnnotation(
                "mixed", skill.name, f"战技：{skill_text} · 法术：{spell_text}", box,
                dim=skill_dim and spell_dim,
            )
        if weapon.caster:
            prefer_spell = True
        else:
            prefer_skill = True
    if prefer_spell and spell is not None:
        shown, dim = _shown(spell.text)
        return WeaponAnnotation("spell", spell.name, shown, box, dim=dim)
    if skill is not None and (prefer_skill or spell is None):
        shown, dim = _shown(skill.text_for(weapon_id))
        return WeaponAnnotation("skill", skill.name, shown, box, dim=dim)
    if spell is not None:
        shown, dim = _shown(spell.text)
        return WeaponAnnotation("spell", spell.name, shown, box, dim=dim)
    return None


def build_annotations(lines: list[OcrLine], info: WeaponInfo, origin: tuple[int, int],
                      scale: float = 1.0, min_score: float = 0.5,
                      ignore_texts: set[str] | None = None) -> tuple[list[WeaponAnnotation], list[Rect]]:
    """
    Args:
        lines: OCR 文字行，坐标相对送去识别的图像
        origin: 识别图像左上角对应的屏幕坐标
        scale: 送去识别的图像相对屏幕的缩放（<1 表示识别前缩小过）
        ignore_texts: 要忽略的文字（本程序自己画上去的标注，截图方式可能截到悬浮窗）
    Returns:
        (标注列表, 所有文字行在屏幕上的位置——用于标注布局时避开其他文字)
    """
    ignored = {
        normalize_text(text) for text in (ignore_texts or set())
        if len(normalize_text(text)) >= 4
    }
    ox, oy = origin
    annotations: list[WeaponAnnotation] = []
    line_boxes: list[Rect] = []
    weapons: list[tuple[Rect, WeaponLookup]] = []
    pending: list[tuple[str, Rect]] = []

    for line in lines:
        if line.score < min_score:
            continue
        norm = normalize_text(line.text)
        if any(norm == text or (len(norm) >= 4 and (norm in text or text in norm)) for text in ignored):
            continue
        x, y, w, h = line.box
        box = (
            ox + int(x / scale),
            oy + int(y / scale),
            max(1, int(w / scale)),
            max(1, int(h / scale)),
        )
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

    for text, box in pending:
        annotation = _action_annotation(
            text, box, info.lookup_skill(text), info.lookup_spell(text), _nearest_weapon(weapons, box),
        )
        if annotation is not None:
            annotations.append(annotation)
    return annotations, line_boxes
