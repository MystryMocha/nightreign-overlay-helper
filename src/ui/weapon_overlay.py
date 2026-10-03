from dataclasses import dataclass

from PyQt6.QtCore import Qt, QPoint, QRect, QRectF
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter
from PyQt6.QtWidgets import QApplication, QWidget

from src.ui.utils import set_widget_always_on_top, region_to_qt_region
from src.weapon.annotate import WeaponAnnotation
from src.weapon.layout import POSITION_BELOW, Rect, layout_annotations

MIN_FONT_PIXEL = 11
MAX_FONT_PIXEL = 30
PADDING_X = 6
PADDING_Y = 2
MAX_TEXT_WIDTH_CHARS = 36

AFFIX_COLOR = QColor("#ffd98a")
WEAPON_COLOR = QColor("#9fd6ff")
SKILL_COLOR = QColor("#b7f0c0")
SPELL_COLOR = QColor("#ddc6ff")
MIXED_COLOR = QColor("#f0e6c0")
DIM_COLOR = QColor("#9a9a9a")
KIND_COLORS = {"weapon": WEAPON_COLOR, "affix": AFFIX_COLOR, "skill": SKILL_COLOR, "spell": SPELL_COLOR, "mixed": MIXED_COLOR}
BACKGROUND_COLOR = QColor(12, 12, 16, 205)


@dataclass
class WeaponOverlayUIState:
    annotations: list[WeaponAnnotation] | None = None   # 整体替换当前的标注
    line_boxes: list[Rect] | None = None                # 识别到的所有文字行，用于标注避让
    region: tuple[int, int, int, int] | None = None     # 武器信息面板的屏幕区域，用于确定悬浮窗所在屏幕
    position: str | None = None                         # 标注相对词条的位置：below / right
    font_scale: float | None = None
    stale: bool | None = None                           # 画面已大幅变化，旧标注先隐藏
    visible: bool | None = None

    only_show_when_game_foreground: bool | None = None
    is_game_foreground: bool | None = None
    is_menu_opened: bool | None = None
    is_setting_opened: bool | None = None


class WeaponOverlayWidget(QWidget):
    """
    覆盖整个屏幕的透明、鼠标穿透窗口，把武器属性补正/词条数值画在游戏里对应文字的旁边
    遗物词条数值的显示也用这个窗口（独立的另一个实例）：它只负责把标注画在文字旁边，不关心标注是哪来的
    """

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool |
            Qt.WindowType.WindowTransparentForInput |
            Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        set_widget_always_on_top(self)
        self.startTimer(50)

        self.annotations: list[WeaponAnnotation] = []
        self.line_boxes: list[Rect] = []
        self.region: tuple[int, int, int, int] | None = None
        self.position = POSITION_BELOW
        self.font_scale = 1.0
        self.stale = False
        self._placed: list[tuple[WeaponAnnotation, Rect, QFont, str]] = []   # 标注、位置、字体、文案

        self.visible = True
        self.only_show_when_game_foreground = False
        self.is_game_foreground = False
        self.is_menu_opened = False
        self.is_setting_opened = False

    # ------------------------------------------------------------ 状态更新

    def update_ui_state(self, state: WeaponOverlayUIState):
        relayout = False
        if state.region is not None and state.region != self.region:
            self.region = state.region
            self._move_to_region_screen()
            relayout = True
        if state.annotations is not None:
            self.annotations = state.annotations
            self.line_boxes = state.line_boxes if state.line_boxes is not None else []
            relayout = True
        if state.position is not None and state.position != self.position:
            self.position = state.position
            relayout = True
        if state.font_scale is not None and state.font_scale != self.font_scale:
            self.font_scale = state.font_scale
            relayout = True
        if state.stale is not None:
            self.stale = state.stale
        if state.visible is not None:
            self.visible = state.visible
        if state.only_show_when_game_foreground is not None:
            self.only_show_when_game_foreground = state.only_show_when_game_foreground
        if state.is_game_foreground is not None:
            self.is_game_foreground = state.is_game_foreground
        if state.is_menu_opened is not None:
            self.is_menu_opened = state.is_menu_opened
        if state.is_setting_opened is not None:
            self.is_setting_opened = state.is_setting_opened
        if relayout:
            self._relayout()
        self.update()

    def _move_to_region_screen(self):
        """悬浮窗铺满截图区域所在的屏幕"""
        qx, qy, qw, qh = region_to_qt_region(self.region)
        screen = QApplication.screenAt(QPoint(qx + qw // 2, qy + qh // 2)) or QApplication.primaryScreen()
        self.setGeometry(screen.geometry())

    # ------------------------------------------------------------ 布局

    def _font_for(self, anchor_height: int) -> QFont:
        font = QFont(self.font())
        font.setPixelSize(max(MIN_FONT_PIXEL, min(MAX_FONT_PIXEL, int(anchor_height * 0.7 * self.font_scale))))
        return font

    def _relayout(self):
        self._placed = []
        if not self.annotations:
            return
        # 物理像素 -> Qt 逻辑坐标，再换成相对窗口左上角的坐标
        origin = self.geometry().topLeft()
        def to_local(box: Rect) -> Rect:
            x, y, w, h = region_to_qt_region(box)
            return (x - origin.x(), y - origin.y(), w, h)

        anchors = [to_local(a.box) for a in self.annotations]
        obstacles = [to_local(b) for b in self.line_boxes]

        fonts, texts, sizes = [], [], []
        for ann, anchor in zip(self.annotations, anchors):
            # 词条名折成多行时锚点是整块文字，字号要按其中单行的高度算（换算到 Qt 逻辑像素的比例与锚点一致）
            line_height = anchor[3] * ann.line_height / ann.box[3] if ann.line_height else anchor[3]
            font = self._font_for(int(line_height))
            fm = QFontMetrics(font)
            max_w = fm.horizontalAdvance("字") * MAX_TEXT_WIDTH_CHARS
            text_rect = fm.boundingRect(QRect(0, 0, max_w, 10000), int(Qt.TextFlag.TextWordWrap), ann.text)
            fonts.append(font)
            texts.append(ann.text)
            sizes.append((text_rect.width() + PADDING_X * 2, text_rect.height() + PADDING_Y * 2))

        bounds = (0, 0, self.width(), self.height())
        rects = layout_annotations(anchors, sizes, obstacles, self.position, bounds)
        self._placed = list(zip(self.annotations, rects, fonts, texts))

    # ------------------------------------------------------------ 绘制与显示

    def paintEvent(self, event):
        if not self._placed:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        for ann, (x, y, w, h), font, text in self._placed:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(BACKGROUND_COLOR)
            painter.drawRoundedRect(QRectF(x, y, w, h), 4, 4)
            painter.setFont(font)
            painter.setPen(DIM_COLOR if ann.dim else KIND_COLORS.get(ann.kind, AFFIX_COLOR))
            painter.drawText(QRect(x + PADDING_X, y + PADDING_Y, w - PADDING_X * 2, h - PADDING_Y * 2),
                             int(Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                             text)

    def should_be_visible(self) -> bool:
        visible = self.visible and bool(self.annotations) and not self.stale
        if self.only_show_when_game_foreground:
            visible = visible and (self.is_game_foreground or self.is_menu_opened or self.is_setting_opened)
        return visible

    def timerEvent(self, event):
        visible = self.should_be_visible()
        if visible and not self.isVisible():
            self.show()
        elif not visible and self.isVisible():
            self.hide()
