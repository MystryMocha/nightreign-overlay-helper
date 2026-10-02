"""
标注布局：决定每条标注画在被识别文字的“下方”还是“后面（右侧）”，并避开其他文字和已放置的标注（纯逻辑）

候选位置：
  below   词条正下方
  right   紧贴词条右侧
  gutter  整块面板文字的右侧对齐列（永远不会压住面板里的文字）
首选位置不可用时依次尝试其余位置，右侧类位置可以向下错开几步以避开前一条标注；
全部有冲突时选重叠面积最小的位置，保证数值始终可见。
"""
Rect = tuple[int, int, int, int]

POSITION_BELOW = "below"
POSITION_RIGHT = "right"

NUDGE_STEP = 4
NUDGE_MAX_STEPS = 12
ANCHOR_OVERLAP_WEIGHT = 4


def intersects(a: Rect, b: Rect) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah


def overlap_area(a: Rect, b: Rect) -> int:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    w = min(ax + aw, bx + bw) - max(ax, bx)
    h = min(ay + ah, by + bh) - max(ay, by)
    if w <= 0 or h <= 0:
        return 0
    return w * h


def inside(rect: Rect, bounds: Rect) -> bool:
    x, y, w, h = rect
    bx, by, bw, bh = bounds
    return x >= bx and y >= by and x + w <= bx + bw and y + h <= by + bh


def clamp(rect: Rect, bounds: Rect) -> Rect:
    x, y, w, h = rect
    bx, by, bw, bh = bounds
    x = min(max(x, bx), bx + bw - w)
    y = min(max(y, by), by + bh - h)
    return (x, y, w, h)


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
        gutter = ((gutter_x, row_y, w, h), True)
        result.insert(1 if preferred == POSITION_RIGHT else 2, gutter)
    return result


def place_annotation(anchor: Rect, size: tuple[int, int], preferred: str, obstacles: list[Rect],
                     bounds: Rect, gap: int = 2, gutter_x: int | None = None) -> Rect:
    """
    返回标注的位置

    Args:
        anchor: 被识别文字行的位置
        size: 标注的宽高
        obstacles: 不应被遮挡的区域（其他文字行、已放置的标注）
        bounds: 可绘制范围（所在屏幕）
        gutter_x: 面板文字右侧对齐列的 x 坐标，None 表示不使用
    """
    avoid = [anchor, *obstacles]

    def clear(rect: Rect) -> bool:
        return inside(rect, bounds) and not any(intersects(rect, other) for other in avoid)

    options: list[Rect] = []
    for rect, nudgeable in candidates(anchor, size, preferred, gap, gutter_x):
        if clear(rect):
            return rect
        options.append(rect)
        if not nudgeable:
            continue
        for step in range(1, NUDGE_MAX_STEPS + 1):
            moved = (rect[0], rect[1] + step * NUDGE_STEP, rect[2], rect[3])
            if clear(moved):
                return moved

    def cost(rect: Rect) -> int:
        return (sum(overlap_area(rect, other) for other in obstacles)
                + ANCHOR_OVERLAP_WEIGHT * overlap_area(rect, anchor))

    return min((clamp(rect, bounds) for rect in options), key=cost)


def layout_annotations(anchors: list[Rect], sizes: list[tuple[int, int]], line_boxes: list[Rect],
                       preferred: str, bounds: Rect, gap: int = 2) -> list[Rect]:
    """依次放置多条标注，后放置的会避开先放置的"""
    gutter_x = max((box[0] + box[2] for box in line_boxes), default=None)
    if gutter_x is not None:
        gutter_x += gap * 3
    placed: list[Rect] = []
    for anchor, size in zip(anchors, sizes):
        obstacles = [box for box in line_boxes if box != anchor] + placed
        placed.append(place_annotation(anchor, size, preferred, obstacles, bounds, gap, gutter_x))
    return placed
