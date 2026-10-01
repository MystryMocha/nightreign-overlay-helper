"""
把 OCR 识别出的文字行匹配到武器/词条，生成要显示在对应文字旁边的标注（纯逻辑，不依赖 Qt / OpenCV）
"""
from dataclasses import dataclass

from src.weapon.info import WeaponInfo, normalize_text
from src.weapon.ocr import OcrLine

Rect = tuple[int, int, int, int]    # x, y, w, h

NO_DATA_TEXT = "暂无数值数据"


@dataclass
class WeaponAnnotation:
    kind: str       # "weapon" 武器属性补正 / "affix" 词条数值
    name: str       # 匹配到的武器名/词条名
    text: str       # 要显示的文案
    box: Rect       # 被识别文字行在屏幕上的位置（与截图区域相同的坐标系）
    dim: bool = False   # 数据里没有数值，只提示“已识别”


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

    return annotations, line_boxes
