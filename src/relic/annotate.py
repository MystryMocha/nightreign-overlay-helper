"""
把 OCR 识别出的文字行匹配到遗物词条，生成要显示在对应文字旁边的标注（纯逻辑，不依赖 Qt / OpenCV）

遗物界面的描述栏比较窄，较长的词条名会折成两三行（“……附加在自己身上时 / 提升物理攻击力”），
而折行后的第二行单独看往往恰好是另一条词条的名字。所以先把紧挨着、左对齐的几行合并起来尝试匹配，
合并后匹配不上的折行，下面的行也不再单独匹配，避免给半截文字配上不相干的数值。
"""
from src.relic.info import RelicInfo
from src.weapon.annotate import NO_DATA_TEXT, WeaponAnnotation, screen_lines
from src.weapon.info import normalize_text
from src.weapon.ocr import OcrLine

Rect = tuple[int, int, int, int]    # x, y, w, h

MAX_WRAP_LINES = 3          # 一条词条名最多折成几行
# 会折行的词条名一定很长（窄栏一行放得下二十来个字），合并后太短的多半是紧挨着的两行无关文字，
# 不能用少量错字的容忍把它们硬凑成某条短词条
MIN_WRAPPED_CHARS = 12
# 折行的下一行：左边缘与上一行对齐，且紧贴在上一行下面（行距远小于相邻两条词条之间的间距）
WRAP_MAX_LEFT_SHIFT = 0.5   # 左边缘允许偏差，单位为上一行的行高
WRAP_MIN_GAP = -0.6         # 下一行顶部相对上一行底部的位置范围（行高的倍数）：负值表示相互重叠
WRAP_MAX_GAP = 0.4
WRAP_HEIGHT_RATIO = 0.6     # 下一行的行高与上一行相差太大时不是同一段文字


def is_wrapped_below(upper: Rect, lower: Rect) -> bool:
    """lower 是不是 upper 折行后的下一行"""
    ux, uy, uw, uh = upper
    lx, ly, lw, lh = lower
    if ly < uy + uh * 0.5:      # 不在上一行的下面（同一行里并排的文字）
        return False
    if abs(lx - ux) > uh * WRAP_MAX_LEFT_SHIFT:
        return False
    if not (uh * WRAP_MIN_GAP <= ly - (uy + uh) <= uh * WRAP_MAX_GAP):
        return False
    return WRAP_HEIGHT_RATIO <= lh / uh <= 1 / WRAP_HEIGHT_RATIO


def _union(boxes: list[Rect]) -> Rect:
    x0 = min(b[0] for b in boxes)
    y0 = min(b[1] for b in boxes)
    x1 = max(b[0] + b[2] for b in boxes)
    y1 = max(b[1] + b[3] for b in boxes)
    return (x0, y0, x1 - x0, y1 - y0)


def _wrap_chains(index: int, boxes: list[Rect], consumed: set[int]) -> list[list[int]]:
    """从第 index 行开始可能的折行组合，由短到长：[[i], [i, j], [i, j, k]]"""
    chains = [[index]]
    while len(chains[-1]) < MAX_WRAP_LINES:
        last = chains[-1][-1]
        following = [
            j for j in range(len(boxes))
            if j not in consumed and j not in chains[-1] and is_wrapped_below(boxes[last], boxes[j])
        ]
        if not following:
            break
        # 同时有几行都像下一行时取最近的那行
        nearest = min(following, key=lambda j: (abs(boxes[j][1] - (boxes[last][1] + boxes[last][3])),
                                                abs(boxes[j][0] - boxes[last][0])))
        chains.append([*chains[-1], nearest])
    return chains


def build_relic_annotations(
    lines: list[OcrLine],
    info: RelicInfo,
    origin: tuple[int, int],
    scale: float = 1.0,
    min_score: float = 0.5,
    ignore_texts: set[str] | None = None,
) -> tuple[list[WeaponAnnotation], list[Rect]]:
    """
    参数含义见 src.weapon.annotate.screen_lines

    Returns:
        (标注列表, 所有文字行在屏幕上的位置——用于标注布局时避开其他文字)
    """
    kept = screen_lines(lines, origin, scale, min_score, ignore_texts)
    texts = [line.text for line, _ in kept]
    boxes = [box for _, box in kept]
    order = sorted(range(len(kept)), key=lambda i: (boxes[i][1], boxes[i][0]))

    annotations: list[WeaponAnnotation] = []
    consumed: set[int] = set()      # 已经归入某条词条的行
    leftover: list[int] = []        # 处理过但没有匹配上的行

    for i in order:
        if i in consumed:
            continue
        # 上面紧挨着一行没匹配上的文字时，这一行多半是它折下来的尾巴，不能单独当作词条
        orphan = any(is_wrapped_below(boxes[j], boxes[i]) for j in leftover)
        found = None
        for chain in reversed(_wrap_chains(i, boxes, consumed)):      # 先试最长的折行组合
            joined = "".join(texts[k] for k in chain)
            if len(chain) == 1 and orphan:
                continue
            if len(chain) > 1 and len(normalize_text(joined)) < MIN_WRAPPED_CHARS:
                continue
            lookup = info.lookup_affix(joined, strict=len(chain) > 1)
            if lookup is not None:
                found = (chain, lookup)
                break
        if found is None:
            leftover.append(i)
            continue
        chain, lookup = found
        consumed.update(chain)
        text, dim = (lookup.display_text(), False) if lookup.has_values else (NO_DATA_TEXT, True)
        annotations.append(WeaponAnnotation(
            "affix", lookup.name, text, _union([boxes[k] for k in chain]), dim=dim,
            line_height=max(boxes[k][3] for k in chain),
        ))
    return annotations, boxes
