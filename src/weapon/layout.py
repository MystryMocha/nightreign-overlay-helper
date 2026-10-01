"""
标注布局：决定每条标注画在被识别文字的“下方”还是“后面（右侧）”，并避开其他文字和已放置的标注（纯逻辑）

候选位置：
  below   词条正下方
  right   紧贴词条右侧
  gutter  整块面板文字的右侧对齐列（永远不会压住面板里的文字）
首选位置不可用时依次尝试其余位置，右侧类位置可以向下错开几步以避开前一条标注；
全部有冲突时选重叠面积最小的位置，保证数值始终可见。
"""
Rect = tuple[int, int, int, int]    # x, y, w, h

POSITION_BELOW = "below"
POSITION_RIGHT = "right"

NUDGE_STEP = 4          # 向下错开的步长（像素）
NUDGE_MAX_STEPS = 12    # 最多错开几步
ANCHOR_OVERLAP_WEIGHT = 4   # 兜底选位置时，盖住被标注文字本身的惩罚权重


def intersects(a: Rect, b: Rect) -> bool:
    return a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]


def overlap_area(a: Rect, b: Rect) -> int:
    w = min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])
    h = min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1])
    return w * h if w > 0 and h > 0 else 0


def inside(rect: Rect, bounds: Rect) -> bool:
    return (rect[0] >= bounds[0] and rect[1] >= bounds[1]
            and rect[0] + rect[2] <= bounds[0] + bounds[2] and rect[1] + rect[3] <= bounds[1] + bounds[3])


def clamp(rect: Rect, bounds: Rect) -> Rect:
    x, y, w, h = rect
    bx, by, bw, bh = bounds
    return (min(max(x, bx), max(bx, bx + bw - w)), min(max(y, by), max(by, by + bh - h)), w, h)


def candidates(anchor: Rect, size: tuple[int, int], preferred: str, gap: int,
               gutter_x: int | None = None) -> list[tuple[Rect, bool]]:
    """按优先级排列的候选位置，每项为 (位置, 是否允许向下错开)"""
    ax, ay, aw, ah = anchor
    w, h = size
    row_y = ay + (ah - h) // 2
    below = ((ax, ay + ah + gap, w, h), False)
    right = ((ax + aw + gap * 3, row_y, w, h), True)
    result = [right, below] if preferred == POSITION_RIGHT else [below, right]
    if gutter_x is not None and gutter_x > right[0][0]:
        result.insert(2 if preferred != POSITION_RIGHT else 1, ((gutter_x, row_y, w, h), True))
    return result


def place_annotation(
    anchor: Rect,
    size: tuple[int, int],
    preferred: str,
    obstacles: list[Rect],
    bounds: Rect,
    gap: int = 2,
    gutter_x: int | None = None,
) -> Rect:
    """
    返回标注的位置

    Args:
        anchor: 被识别文字行的位置
        size: 标注的宽高
        obstacles: 不应被遮挡的区域（其他文字行、已放置的标注）
        bounds: 可绘制范围（所在屏幕）
        gutter_x: 面板文字右侧对齐列的 x 坐标，None 表示不使用
    """
    # 被标注的文字本身也不能盖住
    avoid = [anchor, *obstacles]

    def clear(rect: Rect) -> bool:
        return inside(rect, bounds) and not any(intersects(rect, o) for o in avoid)

    options: list[Rect] = []
    for rect, nudgeable in candidates(anchor, size, preferred, gap, gutter_x):
        if clear(rect):
            return rect
        options.append(rect)
        if nudgeable:
            for step in range(1, NUDGE_MAX_STEPS + 1):
                moved = (rect[0], rect[1] + step * NUDGE_STEP, rect[2], rect[3])
                if clear(moved):
                    return moved

    # 都有冲突：选重叠面积最小的（并保证在屏幕内）；盖住被标注的文字最糟，权重更高
    def cost(rect: Rect) -> int:
        return sum(overlap_area(rect, o) for o in obstacles) + ANCHOR_OVERLAP_WEIGHT * overlap_area(rect, anchor)

    return min((clamp(r, bounds) for r in options), key=cost)


def layout_annotations(
    anchors: list[Rect],
    sizes: list[tuple[int, int]],
    line_boxes: list[Rect],
    preferred: str,
    bounds: Rect,
    gap: int = 2,
) -> list[Rect]:
    """依次放置多条标注，后放置的会避开先放置的"""
    gutter_x = max((b[0] + b[2] for b in line_boxes), default=None)
    if gutter_x is not None:
        gutter_x += gap * 3
    placed: list[Rect] = []
    for anchor, size in zip(anchors, sizes):
        obstacles = [b for b in line_boxes if b != anchor] + placed
        placed.append(place_annotation(anchor, size, preferred, obstacles, bounds, gap, gutter_x))
    return placed
