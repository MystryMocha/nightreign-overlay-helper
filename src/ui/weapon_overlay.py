"""把武器补正、词条、战技和法术的数值画在游戏面板文字旁边。"""
from dataclasses import dataclass

from PyQt6.QtCore import Qt, QRect
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QApplication, QWidget

from src.ui.utils import get_qt_screen_by_region, region_to_qt_region, set_widget_always_on_top
from src.weapon.annotate import WeaponAnnotation
from src.weapon.layout import POSITION_RIGHT, Rect, layout_annotations

WEAPON_COLOR = "#9fd6ff"
AFFIX_COLOR = "#ffd98a"
SKILL_COLOR = "#b7f0c0"
SPELL_COLOR = "#ddc6ff"
MIXED_COLOR = "#f0e6c0"
DIM_COLOR = "#9a9a9a"

KIND_COLORS = {
    "weapon": WEAPON_COLOR,
    "affix": AFFIX_COLOR,
    "skill": SKILL_COLOR,
    "spell": SPELL_COLOR,
    "mixed": MIXED_COLOR,
}


@dataclass
class WeaponOverlayUIState:
    annotations: list[WeaponAnnotation] | None = None
    line_boxes: list[Rect] | None = None
    region: tuple[int, int, int, int] | None = None
    stale: bool | None = None
    visible: bool | None = None
    is_game_foreground: bool | None = None
    only_show_when_game_foreground: bool | None = None
    is_menu_opened: bool | None = None
    is_setting_opened: bool | None = None
    clear: bool = False


class WeaponOverlayWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool |
            Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        set_widget_always_on_top(self)

        self.annotations: list[WeaponAnnotation] = []
        self.line_boxes: list[Rect] = []
        self.region: tuple[int, int, int, int] | None = None
        self.stale = False
        self.visible_flag = True
        self.is_game_foreground = False
        self.only_show_when_game_foreground = False
        self.is_menu_opened = False
        self.is_setting_opened = False
        self._placed: list[tuple[WeaponAnnotation, Rect]] = []
        self._font = QFont()
        self._font.setPixelSize(16)
        self.startTimer(50)

    def update_ui_state(self, state: WeaponOverlayUIState):
        if state.clear:
            self.annotations = []
            self.line_boxes = []
            self.stale = False
        if state.annotations is not None:
            self.annotations = list(state.annotations)
        if state.line_boxes is not None:
            self.line_boxes = list(state.line_boxes)
        if state.region is not None:
            self.region = tuple(state.region)
        if state.stale is not None:
            self.stale = state.stale
        if state.visible is not None:
            self.visible_flag = state.visible
        if state.is_game_foreground is not None:
            self.is_game_foreground = state.is_game_foreground
        if state.only_show_when_game_foreground is not None:
            self.only_show_when_game_foreground = state.only_show_when_game_foreground
        if state.is_menu_opened is not None:
            self.is_menu_opened = state.is_menu_opened
        if state.is_setting_opened is not None:
            self.is_setting_opened = state.is_setting_opened
        self._relayout()
        self._apply_visibility()
        self.update()

    def should_be_visible(self) -> bool:
        if not self.visible_flag or self.stale or not self.annotations:
            return False
        if self.only_show_when_game_foreground:
            return self.is_game_foreground or self.is_menu_opened or self.is_setting_opened
        return True

    def _screen_geometry(self):
        if self.region is None or QApplication.instance() is None:
            return None
        try:
            return get_qt_screen_by_region(self.region).geometry()
        except ValueError:
            screen = QApplication.instance().primaryScreen()
            return None if screen is None else screen.geometry()

    def _to_local(self, box: Rect) -> Rect:
        qx, qy, qw, qh = region_to_qt_region(box)
        return (qx - self.x(), qy - self.y(), max(1, qw), max(1, qh))

    def _relayout(self):
        geometry = self._screen_geometry()
        if geometry is not None and self.geometry() != geometry:
            self.setGeometry(geometry)
        if not self.annotations or self.width() <= 0:
            self._placed = []
            return
        anchors = [self._to_local(item.box) for item in self.annotations]
        lines = [self._to_local(box) for box in self.line_boxes]
        metrics = self.fontMetrics()
        self.setFont(self._font)
        metrics = self.fontMetrics()
        sizes = []
        for item in self.annotations:
            rect = metrics.boundingRect(item.text)
            sizes.append((rect.width() + 8, rect.height() + 4))
        bounds = (0, 0, self.width(), self.height())
        placed = layout_annotations(anchors, sizes, lines or anchors, POSITION_RIGHT, bounds, gap=4)
        self._placed = list(zip(self.annotations, placed))

    def _apply_visibility(self):
        visible = self.should_be_visible()
        if visible and not self.isVisible():
            self.show()
        elif not visible and self.isVisible():
            self.hide()

    def timerEvent(self, event):
        self._apply_visibility()

    def paintEvent(self, event):
        if not self._placed:
            return
        painter = QPainter(self)
        painter.setFont(self._font)
        for item, (x, y, w, h) in self._placed:
            color = QColor(DIM_COLOR if item.dim else KIND_COLORS.get(item.kind, WEAPON_COLOR))
            rect = QRect(x, y, w, h)
            painter.setPen(QPen(QColor(0, 0, 0, 220)))
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                painter.drawText(rect.translated(dx, dy), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, item.text)
            painter.setPen(QPen(color))
            painter.drawText(rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, item.text)
        painter.end()

