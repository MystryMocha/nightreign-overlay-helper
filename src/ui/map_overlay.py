from PyQt6.QtCore import Qt, QPoint, pyqtSignal, QRect
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QProgressBar, 
    QLabel, QHBoxLayout, QSizePolicy, QStackedLayout,
)
from PyQt6.QtGui import QMouseEvent, QKeySequence, QKeyEvent
from dataclasses import dataclass, field
from PyQt6.QtWidgets import QGraphicsDropShadowEffect
from PyQt6.QtGui import QColor, QPixmap, QImage
from PIL import Image, ImageDraw
import os
from datetime import datetime, timedelta
import time
import glob

from src.common import get_readable_timedelta, get_data_path, load_yaml
from src.config import Config
from src.logger import info, warning, error
from src.ui.utils import set_widget_always_on_top, is_window_in_foreground, region_to_qt_region
from src.detector.utils import draw_text
from src.detector.crystal_info import load_crystal_info


@dataclass
class MapOverlayUIState:
    x: int | None = None
    y: int | None = None
    w: int | None = None
    h: int | None = None
    opacity: float | None = None
    visible: bool | None = None
    overlay_images: list[Image.Image] | None = None
    display_crystal_layout: bool | None = None
    crystal_detection: tuple[list[int], set[int]] | None = None  # (候选布局, 识别到的已破除水晶)
    capture_suspended: bool | None = None   # 截图识别期间临时隐藏，避免悬浮窗被截入画面
    clear_image: bool = False
    map_pattern_matching: bool | None = None
    map_pattern_match_time: float | None = None

    only_show_when_game_foreground: bool | None = None
    is_game_foreground: bool | None = None
    is_menu_opened: bool | None = None
    is_setting_opened: bool | None = None


class MapOverlayWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool |
            Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        set_widget_always_on_top(self)
        self.startTimer(50)

        # 悬浮地图信息
        self.map_pattern_idx: int | None = None
        self.overlay_images: list[Image.Image] | None = None
        self.map_pattern_match_time: float = 0.0
        self.map_pattern_matching: bool = False

        self.overlay_image_box = QLabel(self)
        self.overlay_image_box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.overlay_image_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.overlay_image_box.setScaledContents(True)

        # 悬浮水晶信息
        self.crystal_layout_idx: int | None = None
        self.crystal_manual: bool = False               # 是否手动切换过水晶布局
        self.crystal_auto_candidates: list[int] = []    # 自动识别的候选布局
        self.crystal_auto_detected: set[int] = set()    # 自动识别到的已破除水晶
        self.init_crystal_layout_imgs()

        self.crystal_layout_image_box = QLabel(self)
        self.crystal_layout_image_box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.crystal_layout_image_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.crystal_layout_image_box.setScaledContents(True)

        # 右下角标签VBOX
        self.vbox = QVBoxLayout(self)
        self.vbox.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)

        def add_shadow(label: QLabel):
            shadow_effect = QGraphicsDropShadowEffect(label)
            shadow_effect.setBlurRadius(5)
            shadow_effect.setOffset(2, 2)
            shadow_effect.setColor(QColor(0, 0, 0, 160))
            label.setGraphicsEffect(shadow_effect)


        # 水晶序号标签
        self.crystal_layout_label = QLabel(self)
        self.crystal_layout_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)
        add_shadow(self.crystal_layout_label)
        self.vbox.addWidget(self.crystal_layout_label)

        # 地图序号标签
        self.map_pattern_label = QLabel(self)
        self.map_pattern_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)
        add_shadow(self.map_pattern_label)
        self.vbox.addWidget(self.map_pattern_label)

        # 检测时间标签
        self.match_time_label = QLabel(self)
        self.match_time_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)
        add_shadow(self.match_time_label)
        self.vbox.addWidget(self.match_time_label)


        self.target_opacity = 1.0
        self.visible = True
        self.only_show_when_game_foreground = False
        self.is_game_foreground = False
        self.is_menu_opened = False
        self.is_setting_opened = False
        self.capture_suspended = False

        self.update_ui_state(MapOverlayUIState(
            w=10,
            h=10,
            opacity=0.0,
            visible=True,
        ))


    def set_overlay_images(self, imgs: list[Image.Image] | None):
        self.overlay_images = imgs
        self.map_pattern_idx = 0
        self.update_overlay_images()
        
    def update_overlay_images(self):
        if not self.overlay_images:
            self.overlay_images = None
            self.overlay_image_box.clear()
            return
        img = self.overlay_images[self.map_pattern_idx]
        data = img.convert("RGBA").tobytes("raw", "RGBA")
        qimg = QImage(data, img.width, img.height, QImage.Format.Format_RGBA8888)
        pixmap = QPixmap.fromImage(qimg)
        pixmap.setDevicePixelRatio(self.devicePixelRatio())
        self.overlay_image_box.setPixmap(pixmap)

    def next_overlay_image(self):
        if self.visible and self.overlay_images is not None:
            self.map_pattern_idx += 1
            if self.map_pattern_idx >= len(self.overlay_images):
                self.map_pattern_idx = 0
            self.update_overlay_images()

    def last_overlay_image(self):
        if self.visible and self.overlay_images is not None:
            self.map_pattern_idx -= 1
            if self.map_pattern_idx < 0:
                self.map_pattern_idx = len(self.overlay_images) - 1
            self.update_overlay_images()


    def init_crystal_layout_imgs(self):
        self.crystal_info = load_crystal_info()
        self.crystal_icon_cache: dict[tuple, Image.Image] = {}
        # 手动切换用的静态布局图片，下标0为所有水晶
        self.crystal_layout_imgs = [
            self.render_crystal_image([i]) for i in range(len(self.crystal_info.layouts))
        ]

    def load_crystal_icon(self, name: str, size: tuple[int, int], alpha: float) -> Image.Image:
        key = (name, size, alpha)
        if key not in self.crystal_icon_cache:
            path = get_data_path(f"icons/crystal/{name}.png")
            if not os.path.isfile(path):
                error(f"Failed to open image file: {path}")
            icon = Image.open(path).convert("RGBA")
            icon = icon.resize(size, Image.Resampling.BICUBIC)
            if alpha < 1.0:
                r, g, b, a = icon.split()
                a = a.point(lambda p: int(p * alpha))
                icon = Image.merge('RGBA', (r, g, b, a))
            self.crystal_icon_cache[key] = icon
        return self.crystal_icon_cache[key]

    def render_crystal_image(self, layout_indices: list[int], detected: set[int] | None = None) -> Image.Image:
        """
        绘制水晶布局图片
        layout_indices: 布局序号列表，[0]为所有水晶，多个序号时绘制所有候选布局的并集
        detected: 在地图上识别到的已破除水晶，会额外绘制高亮圈
        """
        MAP_SIZE = (750, 750)
        ICON_SIZE = (MAP_SIZE[0] // 25, MAP_SIZE[1] // 25)
        ICON_ALPHA = 0.8
        SPEC_PATTERN_ICON_SIZE = (MAP_SIZE[0] // 20, MAP_SIZE[1] // 20)
        SPEC_PATTERN_ICON_ALPHA = 0.8
        DETECTED_COLOR = (255, 230, 0, 230)

        detected = detected or set()
        layouts = self.crystal_info.layouts
        is_main = layout_indices == [0]

        initial, later = set(), set()
        for i in layout_indices:
            initial |= set(layouts[i].initial)
            later |= set(layouts[i].later)
        later -= initial

        size = SPEC_PATTERN_ICON_SIZE if not is_main else ICON_SIZE
        alpha = SPEC_PATTERN_ICON_ALPHA if not is_main else ICON_ALPHA
        icon = self.load_crystal_icon("crystal", size, alpha)
        icon_later = self.load_crystal_icon("later_crystal", size, alpha)
        icon_underground = self.load_crystal_icon("underground_crystal", size, alpha)

        img = Image.new("RGBA", MAP_SIZE, (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        def draw_crystal(idx: int, is_later: bool):
            if is_later: 
                icon_img = icon_later
            elif idx in self.crystal_info.underground:
                icon_img = icon_underground
            else:
                icon_img = icon
            x_ratio, y_ratio = self.crystal_info.crystals[idx]
            cx, cy = int(x_ratio * MAP_SIZE[0]), int(y_ratio * MAP_SIZE[1])
            img.alpha_composite(icon_img, (cx - icon_img.width // 2, cy - icon_img.height // 2))
            if idx in detected:
                r = int(max(icon_img.size) * 0.7)
                draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=DETECTED_COLOR, width=3)

        for idx in initial:
            draw_crystal(idx, is_later=False)
        for idx in later:
            draw_crystal(idx, is_later=True)

        # 图片正下方中间绘制图例
        sx = MAP_SIZE[0] * 0.2
        sy = MAP_SIZE[1] * 0.87
        legends = [(icon, "水晶点位"), (icon_underground, "地下水晶点位")]
        if later:
            legends.append((icon_later, "额外水晶点位"))
        if detected:
            legends.append((None, "已破除（自动识别）"))
        sy -= max(0, len(legends) - 3) * ICON_SIZE[1]
        if len(legends) < 3:
            sy += ICON_SIZE[1] * (3 - len(legends))
        for i, (legend_icon, text) in enumerate(legends):
            y = sy + i * ICON_SIZE[1]
            if legend_icon is not None:
                img.alpha_composite(legend_icon, (int(sx), int(y)))
            else:
                cx, cy, r = sx + ICON_SIZE[0] / 2, y + ICON_SIZE[1] / 2, ICON_SIZE[0] * 0.45
                draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=DETECTED_COLOR, width=3)
            draw_text(img, (sx + ICON_SIZE[0] + 5, y), text, 20, color=(255, 255, 255, 220), outline_width=2, align='lt')
        return img

    def set_crystal_image(self, img: Image.Image | None):
        if img is None:
            self.crystal_layout_image_box.clear()
            return
        img = img.convert("RGBA")
        data = img.tobytes("raw", "RGBA")
        qimg = QImage(data, img.width, img.height, QImage.Format.Format_RGBA8888)
        pixmap = QPixmap.fromImage(qimg)
        pixmap.setDevicePixelRatio(self.devicePixelRatio())
        self.crystal_layout_image_box.setPixmap(pixmap)

    def update_crystal_layout(self):
        if self.crystal_layout_idx is None:
            self.set_crystal_image(None)
        elif self.crystal_auto_candidates:
            self.set_crystal_image(self.render_crystal_image(self.crystal_auto_candidates, self.crystal_auto_detected))
        elif self.crystal_layout_idx == 0 and self.crystal_auto_detected:
            self.set_crystal_image(self.render_crystal_image([0], self.crystal_auto_detected))
        else:
            self.set_crystal_image(self.crystal_layout_imgs[self.crystal_layout_idx])

    def set_crystal_detection(self, candidates: list[int], detected: set[int]):
        """
        设置水晶自动识别结果（手动切换过布局后不再自动覆盖）
        """
        if self.crystal_layout_idx is None or self.crystal_manual:
            return
        self.crystal_auto_detected = set(detected)
        self.crystal_auto_candidates = list(candidates)
        self.crystal_layout_idx = candidates[0] if len(candidates) == 1 else 0
        self.update_crystal_layout()

    def next_crystal_layout(self):
        if self.visible and self.crystal_layout_idx is not None:
            self.crystal_manual = True
            self.crystal_auto_candidates = []
            self.crystal_layout_idx += 1
            if self.crystal_layout_idx >= len(self.crystal_layout_imgs):
                self.crystal_layout_idx = 0
            self.update_crystal_layout()

    def last_crystal_layout(self):
        if self.visible and self.crystal_layout_idx is not None:
            self.crystal_manual = True
            self.crystal_auto_candidates = []
            self.crystal_layout_idx -= 1
            if self.crystal_layout_idx < 0:
                self.crystal_layout_idx = len(self.crystal_layout_imgs) - 1
            self.update_crystal_layout()


    def update_ui_state(self, state: MapOverlayUIState):
        if state.x is not None:
            region = region_to_qt_region((state.x, state.y, state.w, state.h))
            self.setGeometry(*region)
        if state.opacity is not None:
            self.target_opacity = state.opacity
        if state.visible is not None:
            self.visible = state.visible
        if state.overlay_images is not None:
            self.set_overlay_images(state.overlay_images)
        if state.clear_image:
            self.set_overlay_images(None)
        if state.only_show_when_game_foreground is not None:
            self.only_show_when_game_foreground = state.only_show_when_game_foreground
        if state.is_game_foreground is not None:
            self.is_game_foreground = state.is_game_foreground
        if state.is_menu_opened is not None:
            self.is_menu_opened = state.is_menu_opened
        if state.is_setting_opened is not None:
            self.is_setting_opened = state.is_setting_opened
        if state.map_pattern_matching is not None:
            self.map_pattern_matching = state.map_pattern_matching
        if state.map_pattern_match_time is not None:
            self.map_pattern_match_time = state.map_pattern_match_time
        if state.display_crystal_layout is not None:
            self.crystal_layout_idx = 0 if state.display_crystal_layout else None
            self.crystal_manual = False
            self.crystal_auto_candidates = []
            self.crystal_auto_detected = set()
            self.update_crystal_layout()
        if state.crystal_detection is not None:
            self.set_crystal_detection(*state.crystal_detection)
        if state.capture_suspended is not None:
            self.capture_suspended = state.capture_suspended
            if self.capture_suspended and self.isVisible():
                self.hide()
        self.update()

    def timerEvent(self, event):
        w, h = self.width(), self.height()
        self.overlay_image_box.setGeometry(0, 0, w, h)
        self.crystal_layout_image_box.setGeometry(0, 0, w, h)

        font_size = max(8, 24 * h // 750)

        # 更新vbox
        margin = int(font_size * 0.5)
        self.vbox.setContentsMargins(margin, margin, margin, margin)
        self.vbox.setSpacing(margin // 2)

        # 更新地图序号标签
        map_pattern_text = ""
        if self.overlay_images is not None and self.map_pattern_idx is not None:
            map_pattern_text = f"识别结果: {self.map_pattern_idx + 1}/{len(self.overlay_images)}"
        self.map_pattern_label.setText(map_pattern_text)
        self.map_pattern_label.setStyleSheet(f"color: white; font-size: {font_size}px;")

        # 更新水晶布局标签
        crystal_layout_text = ""
        if self.crystal_layout_idx is not None:
            total = len(self.crystal_layout_imgs) - 1
            candidates = self.crystal_auto_candidates
            if len(candidates) == 1:
                crystal_layout_text = f"水晶布局: {candidates[0]}/{total} (自动识别)"
            elif len(candidates) > 1:
                crystal_layout_text = f"水晶布局: 候选 {'/'.join(map(str, candidates))} (已破除{len(self.crystal_auto_detected)}个水晶)"
            elif self.crystal_layout_idx == 0:
                crystal_layout_text = f"水晶布局: 所有/{total}"
            else:
                crystal_layout_text = f"水晶布局: {self.crystal_layout_idx}/{total}"
        self.crystal_layout_label.setText(crystal_layout_text)
        self.crystal_layout_label.setStyleSheet(f"color: white; font-size: {font_size}px;")

        # 更新识别时间标签
        match_time_text = ""
        if self.map_pattern_matching:
            spin_line = ['|', '/', '-', '\\'][int(time.time() * 4) % 4]
            match_time_text = f"正在识别中... {spin_line}"
        elif self.map_pattern_match_time > 0:
            elapsed = time.time() - self.map_pattern_match_time
            match_time_text = f"识别时间：{get_readable_timedelta(timedelta(seconds=elapsed))}前"
        self.match_time_label.setText(match_time_text)
        self.match_time_label.setStyleSheet(f"color: white; font-size: {font_size}px;")

        # 更新透明度
        threshold = 0.01
        step = 0.6
        real_opacity = self.windowOpacity()
        dlt = self.target_opacity - real_opacity
        if abs(dlt) > threshold:
            real_opacity += dlt * step
            self.setWindowOpacity(real_opacity)
        elif 0 < abs(dlt) <= threshold:
            real_opacity = self.target_opacity
            self.setWindowOpacity(real_opacity)

        visible = self.visible and real_opacity > 0.01
        if self.only_show_when_game_foreground:
            visible = visible and (self.is_game_foreground or self.is_menu_opened or self.is_setting_opened)
        visible = visible and not self.capture_suspended
        if visible and not self.isVisible():
            self.show()
        elif not visible and self.isVisible():
            self.hide()



