from PyQt6.QtCore import Qt, pyqtSignal, QPoint, QEvent, QTimer
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QFormLayout,
    QLabel, QSlider, QGroupBox, QCheckBox, QPushButton,
    QMessageBox, QApplication, QFrame, QComboBox, QToolTip, 
    QLineEdit, QScrollArea, QTabWidget, QSpinBox, QDoubleSpinBox,
)
from PyQt6.QtGui import QPixmap, QIcon, QMouseEvent, QEnterEvent
import yaml
from dataclasses import dataclass, asdict
import os
import ctypes
import shutil
import re

from src.updater import Updater
from src.common import (
    APP_FULLNAME, APP_NAME, APP_VERSION,
    get_appdata_path, get_asset_path, get_desktop_path,
    ICON_PATH, load_yaml, save_yaml,
)
from src.logger import info, warning, error, set_log_level, INFO, DEBUG
from src.config import Config
from src.ui.overlay import OverlayUIState, OverlayWidget, MIN_OVERLAY_OPACITY
from src.ui.map_overlay import MapOverlayWidget, MapOverlayUIState
from src.ui.input import InputWorker, InputSettingWidget, InputSetting
from src.ui.capture_region import CaptureRegionWindow
from src.detector.rain_detector import RainDetector
from src.detector.utils import hls_to_rgb
from src.ui.bug_report import BugReportWindow
from src.ui.utils import process_region_to_adapt_scale, get_qt_screen_by_region


BUTTON_STYLE = "padding: 4px; min-height: 20px;"

SETTINGS_SAVE_PATH = get_appdata_path("settings.yaml")
PRESET_SETTINGS_DIR = get_appdata_path("preset_settings")

DETECT_REGION_TUTORIAL_IMG_PATH = get_asset_path("detect_region_tutorial/{i}.jpg")
COLOR_ALIGN_TUTORIAL_IMG_PATH = get_asset_path("color_align_tutorial/{i}.jpg")
MAP_DETECT_TUTORIAL_IMG_PATH = get_asset_path("map_detect_tutorial/{i}.jpg")
HP_DETECT_TUTORIAL_IMG_PATH = get_asset_path("hp_detect_tutorial/{i}.jpg")
ART_DETECT_TUTORIAL_IMG_PATH = get_asset_path("art_detect_tutorial/{i}.jpg")


def info_box(message: str, parent=None):
    msg = QMessageBox(parent)
    msg.setIcon(QMessageBox.Icon.Information)
    msg.setWindowTitle(APP_FULLNAME)
    msg.setText(message)
    msg.exec()

def warning_box(message: str, parent=None):
    msg = QMessageBox(parent)
    msg.setIcon(QMessageBox.Icon.Warning)
    msg.setWindowTitle(APP_FULLNAME)
    msg.setText(message)
    msg.exec()

def error_box(message: str, parent=None):
    msg = QMessageBox(parent)
    msg.setIcon(QMessageBox.Icon.Critical)
    msg.setWindowTitle(APP_FULLNAME)
    msg.setText(message)
    msg.exec()

def comfirm_box(message: str, parent=None) -> bool:
    msg = QMessageBox(parent)
    msg.setIcon(QMessageBox.Icon.Question)
    msg.setWindowTitle(APP_FULLNAME)
    msg.setText(message)
    msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    result = msg.exec()
    return result == QMessageBox.StandardButton.Yes


class QuickTooltipLabel(QLabel):
    """快速显示tooltip的标签"""
    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)
    
    def enterEvent(self, event: QEnterEvent):
        # 鼠标进入时立即显示tooltip
        if self.toolTip():
            QToolTip.showText(self.mapToGlobal(QPoint(0, self.height())), self.toolTip(), self)
        super().enterEvent(event)
    
    def mousePressEvent(self, event: QMouseEvent):
        # 点击时也显示tooltip
        if event.button() == Qt.MouseButton.LeftButton and self.toolTip():
            QToolTip.showText(event.globalPosition().toPoint(), self.toolTip(), self)
        super().mousePressEvent(event)


def make_help_label(text: str) -> QuickTooltipLabel:
    label = QuickTooltipLabel("?")
    label.setStyleSheet("color: gray; font-weight: bold; padding: 0 4px;")
    label.setToolTip(text.strip())
    return label

def make_button(text: str, slot=None, tooltip: str | None = None) -> QPushButton:
    button = QPushButton(text)
    button.setStyleSheet(BUTTON_STYLE)
    if slot is not None:
        button.clicked.connect(slot)
    if tooltip:
        button.setToolTip(tooltip)
    return button

def make_tip_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet("color: gray;")
    return label

def make_value_label() -> QLabel:
    label = QLabel()
    label.setMinimumWidth(48)
    label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    return label

def make_row(*widgets: QWidget, stretch: bool = True) -> QWidget:
    """把多个控件横向排成一行，stretch=False 时第一个控件占满剩余宽度"""
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    for i, w in enumerate(widgets):
        layout.addWidget(w, 0 if stretch or i > 0 else 1)
    if stretch:
        layout.addStretch()
    return row

def set_region_label(label: QLabel, region: list | None):
    if region is None:
        label.setText("❌ 未设置")
        label.setStyleSheet("color: #e67e22;")
    else:
        label.setText(f"✔️ 已设置 {region}")
        label.setStyleSheet("color: #27ae60;")

def make_form(group: QGroupBox) -> QFormLayout:
    form = QFormLayout(group)
    form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
    return form


# (配置项, 名称, 最小值, 最大值, 步长, 单位, 说明)，步长为 int 时使用整数输入框
ADVANCED_PARAMS = [
    ("foward_day_seconds", "快进缩圈秒数", 1, 120, 1, " 秒", "按一次「快进缩圈」快捷键前进的时间"),
    ("back_day_seconds", "倒退缩圈秒数", 1, 120, 1, " 秒", "按一次「倒退缩圈」快捷键后退的时间"),
    ("map_pattern_retry_error_threshold", "地图重新识别阈值", 10, 300, 5, "",
     "最佳识别结果的误差高于此值时，下次打开地图会自动重新识别\n正确结果的误差通常在 0~30，错误结果通常在 100 以上"),
    ("crystal_detect_delay", "水晶识别等待", 0.0, 3.0, 0.1, " 秒",
     "开启水晶布局自动识别时，打开地图后等待多久再识别水晶，期间地图悬浮窗保持隐藏\n打开地图有动画，太短可能识别不准"),
    ("art_detect_delay_seconds", "绝招检测延迟", 0.0, 3.0, 0.1, " 秒", "按下绝招按键后等待多久再检测绝招图标"),
]


class PresetDialog(QWidget):
    save_preset_signal = pyqtSignal(str)
    load_preset_signal = pyqtSignal(str)
    remove_preset_signal = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("预设设置")
        self.setMinimumSize(350, 400)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        self._init_ui()

    def _init_ui(self):
        self.main_layout = QVBoxLayout(self)

        # --- 1. 保存预设部分 ---
        save_layout = QHBoxLayout()
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("输入新预设名称...")
        self.save_btn = QPushButton("保存预设")
        self.save_btn.clicked.connect(self._on_save_clicked)
        
        save_layout.addWidget(self.name_input)
        save_layout.addWidget(self.save_btn)
        self.main_layout.addLayout(save_layout)

        # 分割线
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        self.main_layout.addWidget(line)

        # --- 2. 预设列表展示部分 ---
        self.main_layout.addWidget(QLabel("已有预设列表:"))
        
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.list_container = QWidget()
        self.list_layout = QVBoxLayout(self.list_container)
        self.list_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll_area.setWidget(self.list_container)
        
        self.main_layout.addWidget(self.scroll_area)

    def set_preset_names(self, names: list[str]):
        """更新预设名称列表并重新渲染UI"""
        # 清空当前布局中的所有组件
        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        # 重新填充
        for name in names:
            item_widget = QWidget()
            item_layout = QHBoxLayout(item_widget)
            item_layout.setContentsMargins(5, 2, 5, 2)

            name_label = QLabel(name)
            load_btn = QPushButton("加载")
            load_btn.setFixedWidth(60)
            # 使用 lambda 捕获当前的 name
            load_btn.clicked.connect(lambda checked, n=name: self.load_preset_signal.emit(n))

            remove_btn = QPushButton("删除")
            remove_btn.setFixedWidth(60)
            remove_btn.setStyleSheet("color: red;")
            remove_btn.clicked.connect(lambda checked, n=name: self.remove_preset_signal.emit(n))

            item_layout.addWidget(name_label)
            item_layout.addWidget(load_btn)
            item_layout.addWidget(remove_btn)
            
            self.list_layout.addWidget(item_widget)

    def _is_valid_filename(self, filename: str) -> bool:
        """检查是否是合适的文件名 (Windows/Linux 通用规则)"""
        if not filename or filename.strip() == "":
            return False
        # 禁止包含 / \ : * ? " < > |
        invalid_chars = r'[\\/:*?"<>|]'
        if re.search(invalid_chars, filename):
            return False
        # 限制长度
        if len(filename) > 200:
            return False
        return True

    def _on_save_clicked(self):
        """保存按钮点击逻辑"""
        name = self.name_input.text().strip()
        if self._is_valid_filename(name):
            self.save_preset_signal.emit(name)
            self.name_input.clear()  # 发送后清空输入框
        else:
            warning_box("无效的预设名称！请避免使用特殊字符 / \\ : * ? \" < > | 并确保名称非空且不过长。", self)


class SettingsWindow(QWidget):
    update_overlay_ui_state_signal = pyqtSignal(OverlayUIState)
    update_map_overlay_ui_state_signal = pyqtSignal(MapOverlayUIState)
    update_preset_list_signal = pyqtSignal(list)

    TAB_TIMER, TAB_AUTO_TIMER, TAB_MAP, TAB_HP_ART, TAB_GENERAL = range(5)

    def add_hotkey_row(self, form: QFormLayout, name: str, slot=None, help_text: str | None = None,
                       label: QLabel | None = None) -> InputSettingWidget:
        """在表单中添加一行快捷键设置，并登记用于冲突检测"""
        widget = InputSettingWidget(self.input)
        if slot is not None:
            widget.input_triggered.connect(slot)
        field = widget if help_text is None else make_row(widget, make_help_label(help_text), stretch=False)
        form.addRow(label if label is not None else name, field)
        self.hotkey_widgets.append((name, widget))
        return widget

    def init_appearance_group(self):
        # 计时器显示
        self.appearance_group = QGroupBox("计时器显示")
        form = make_form(self.appearance_group)

        self.timer_visible_checkbox = QCheckBox("显示计时器")
        self.timer_visible_checkbox.setChecked(True)
        self.timer_visible_checkbox.stateChanged.connect(self.update_timer_visible)
        self.hide_text_checkbox = QCheckBox("隐藏文字")
        self.hide_text_checkbox.stateChanged.connect(self.update_hide_text)
        form.addRow(make_row(self.timer_visible_checkbox, self.hide_text_checkbox))

        self.size_slider = QSlider(Qt.Orientation.Horizontal)
        self.size_slider.setRange(30, 1000)
        self.size_slider.setValue(self.overlay.width())
        self.size_value_label = make_value_label()
        self.size_slider.valueChanged.connect(self.update_overlay_size)
        form.addRow("大小", make_row(self.size_slider, self.size_value_label, stretch=False))

        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        # 下限 20%，避免计时器完全透明后无法右键打开设置
        self.opacity_slider.setRange(MIN_OVERLAY_OPACITY, 100)
        self.opacity_slider.setValue(int(self.overlay.windowOpacity() * 100))
        self.opacity_value_label = make_value_label()
        self.opacity_slider.valueChanged.connect(self.update_overlay_opacity)
        form.addRow("不透明度", make_row(self.opacity_slider, self.opacity_value_label, stretch=False))

        position_grid = QGridLayout()
        position_grid.addWidget(make_button("顶部居中", self.update_overlay_position_top_center), 0, 0)
        position_grid.addWidget(make_button("水平居中", self.update_overlay_position_center), 0, 1)
        position_grid.addWidget(make_button("屏幕中心", self.reset_overlay_position), 0, 2)
        form.addRow("位置", position_grid)

        form.addRow(make_tip_label("打开设置时可用鼠标左键拖动计时器调整位置"))

    def init_input_group(self):
        config = Config.get()

        # 计时快捷键
        self.input_group = QGroupBox("计时快捷键")
        form = make_form(self.input_group)

        self.day_input_setting_widget = self.add_hotkey_row(form, "重置缩圈", self.updater.start_day_by_shortcut,
                                                            "从 Day 1 第一次缩圈开始重新计时")
        self.forward_day_label = QLabel(f"快进缩圈 {config.foward_day_seconds} 秒")
        self.forward_day_input_setting_widget = self.add_hotkey_row(form, "快进缩圈", self.updater.foward_day_by_shortcut,
                                                                    label=self.forward_day_label)
        self.back_day_label = QLabel(f"倒退缩圈 {config.back_day_seconds} 秒")
        self.back_day_input_setting_widget = self.add_hotkey_row(form, "倒退缩圈", self.updater.back_day_by_shortcut,
                                                                 label=self.back_day_label)
        self.in_rain_input_setting_widget = self.add_hotkey_row(form, "开始雨中冒险", self.updater.start_in_rain_by_shortcut)
        self.toggle_timer_input_setting_widget = self.add_hotkey_row(form, "显示/隐藏计时器", self.toggle_timer_visible)

        form.addRow(make_tip_label("点击按钮修改，支持键盘、鼠标或手柄组合键；快进/倒退秒数可在「通用 → 高级参数」中修改"))

    def init_performance_group(self):
        config = Config.get()

        # 性能设置
        self.performance_group = QGroupBox("检测与性能")
        form = make_form(self.performance_group)

        self.detect_interval_combobox = QComboBox()
        for k in config.detect_intervals.keys():
            self.detect_interval_combobox.addItem(k)
        self.detect_interval_combobox.setCurrentText("高")
        self.detect_interval_combobox.currentTextChanged.connect(self.update_detect_interval)
        form.addRow("自动检测频率", make_row(self.detect_interval_combobox, make_help_label(
            "检测频率越高，自动计时越及时，但占用的CPU也越多\n"
            + "\n".join(f"{k}：每 {v} 秒检测一次" for k, v in config.detect_intervals.items())
        ), stretch=False))

        self.screencap_mode_combobox = QComboBox()
        self.screencap_mode_combobox.addItems(["自动", "仅前台", "仅后台"])
        self.screencap_mode_combobox.setCurrentText("自动")
        self.screencap_mode_combobox.currentTextChanged.connect(self.update_screencap_mode)
        form.addRow("截图方式", make_row(self.screencap_mode_combobox, make_help_label(
            "自动：优先使用后台截图，失败时切换到前台截图\n"
            "仅前台：游戏窗口必须在最前面\n"
            "仅后台：游戏窗口被遮挡时也能截图\n"
            "截图黑屏或识别不到时可以尝试切换"
        ), stretch=False))

        self.only_show_when_game_foreground_checkbox = QCheckBox("仅在游戏窗口处于前台时显示和检测")
        self.only_show_when_game_foreground_checkbox.setChecked(False)
        self.only_show_when_game_foreground_checkbox.stateChanged.connect(self.update_only_show_when_game_foreground)
        form.addRow(self.only_show_when_game_foreground_checkbox)

        # HDR图像处理选项
        self.hdr_processing_checkbox = QCheckBox("启用HDR图像处理")
        self.hdr_processing_checkbox.setChecked(False)
        self.hdr_processing_checkbox.stateChanged.connect(self.update_hdr_processing)
        form.addRow(make_row(self.hdr_processing_checkbox, make_help_label(
            "在HDR显示模式下启用此选项可提高识别准确性\n"
            "程序会自动对不同检测模块应用最佳的图像处理方式：\n"
            "• 缩圈倒计时：HDR到SDR转换\n"
            "• 地图识别：图像归一化(CLAHE)\n"
            "• 血条/雨中检测：保持原始图像\n"
            "如果遇到识别问题，可以尝试关闭此选项"
        )))

        form.addRow(make_tip_label("⚠️请使用窗口化/无边框窗口化模式启动游戏\n"
                                   "⚠️悬浮窗与部分AI补帧工具（小黄鸭）不兼容，同时使用可能出现卡顿"))

    def init_auto_timer_group(self):
        config = Config.get()

        # 自动计时设置
        self.auto_timer_group = QGroupBox("缩圈 && 雨中冒险自动计时")
        form = make_form(self.auto_timer_group)

        self.dayx_detect_enable_checkbox = QCheckBox("缩圈自动计时")
        self.dayx_detect_enable_checkbox.stateChanged.connect(self.update_dayx_detect_enable)
        self.in_rain_detect_enable_checkbox = QCheckBox("雨中冒险自动计时")
        self.in_rain_detect_enable_checkbox.stateChanged.connect(self.update_in_rain_detect_enable)
        form.addRow(make_row(self.dayx_detect_enable_checkbox, self.in_rain_detect_enable_checkbox))

        self.dayx_detect_lang = "chs"
        self.lang_combobox = QComboBox()
        self.lang_combobox.addItems(config.dayx_detect_langs.values())
        self.lang_combobox.setCurrentText(config.dayx_detect_langs[self.dayx_detect_lang])
        self.lang_combobox.currentTextChanged.connect(self.update_detect_lang)
        form.addRow("游戏语言", make_row(self.lang_combobox, make_help_label(
            "需要与游戏内语言一致，否则无法识别 DAY 图标"), stretch=False))

        self.capture_dayx_hpcolor_region_input_widget = self.add_hotkey_row(
            form, "框选检测区域", self.capture_day1_hpcolor_region,
            "在 DAY I 图标出现时按下，框选血条和 DAY I 图标")

        self.day1_detect_region = None
        self.day1_detect_region_label = QLabel()
        form.addRow("缩圈区域", self.day1_detect_region_label)
        self.hpcolor_detect_region = None
        self.hpcolor_detect_region_label = QLabel()
        form.addRow("雨中冒险区域", self.hpcolor_detect_region_label)

        self.clear_day1_hpcolor_region_button = make_button("清除检测区域", self.clear_day1_hpcolor_regions)
        form.addRow(make_row(
            make_button("查看自动计时帮助", self.show_capture_day1_hpcolor_region_tutorial),
            self.clear_day1_hpcolor_region_button,
        ))

    def init_hp_color_group(self):
        # 血条颜色校准
        self.hp_color_group = QGroupBox("血条颜色校准（雨中冒险识别不准时使用）")
        form = make_form(self.hp_color_group)

        self.align_to_detect_hp_color_input_widget = self.add_hotkey_row(
            form, "校准血条颜色", self.capture_hp_color, "画面中有血条时按下，框选血条中的纯色部分")

        self.not_in_rain_hls = None
        self.in_rain_hls = None
        self.not_in_rain_hls_hdr = None
        self.in_rain_hls_hdr = None
        self.not_in_rain_label = QLabel("默认")
        self.in_rain_label = QLabel("默认")
        for label in (self.not_in_rain_label, self.in_rain_label):
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setMinimumWidth(70)
        form.addRow("正常血条", make_row(self.not_in_rain_label))
        form.addRow("雨中血条", make_row(self.in_rain_label))

        form.addRow(make_row(
            make_button("查看校准血条颜色帮助", self.show_capture_hp_color_help),
            make_button("恢复默认颜色", self.clear_hp_color),
        ))

    def init_map_detect_group(self):
        config = Config.get()

        # 地图识别设置
        self.map_detect_group = QGroupBox("地图识别")
        form = make_form(self.map_detect_group)

        self.map_detect_enable_checkbox = QCheckBox("启用地图识别")
        self.map_detect_enable_checkbox.stateChanged.connect(self.update_map_detect_enable)
        form.addRow(make_row(self.map_detect_enable_checkbox,
                             make_button("查看地图识别帮助", self.show_capture_map_region_tutorial)))

        self.map_pattern_return_topk_combobox = QComboBox()
        for i in range(config.min_map_pattern_match_topk, config.max_map_pattern_match_topk + 1):
            self.map_pattern_return_topk_combobox.addItem(str(i))
        self.map_pattern_return_topk_combobox.setCurrentText(str(config.default_map_pattern_match_topk))
        self.map_pattern_return_topk_combobox.currentTextChanged.connect(self.update_map_pattern_return_topk)
        form.addRow("候选结果数量", make_row(self.map_pattern_return_topk_combobox, make_help_label(
            "设置每次地图识别时返回的最佳结果数量\n"
            "由于大空洞某些地图地表建筑相似度较高，难以定位到唯一地图结果，\n"
            "因此需要在多个候选地图中选择正确的地图\n"
            "如果识别地图时程序闪退，或者内存占用过大，可以尝试减小此数值"
        ), stretch=False))

        self.crystal_auto_detect_checkbox = QCheckBox("大空洞水晶布局自动识别（实验性）")
        self.crystal_auto_detect_checkbox.setChecked(False)
        self.crystal_auto_detect_checkbox.stateChanged.connect(self.update_crystal_auto_detect)
        form.addRow(make_row(self.crystal_auto_detect_checkbox, make_help_label(
            "开启后每次打开地图时尝试从地图画面识别水晶并自动切换水晶布局，\n"
            "识别期间地图悬浮窗会短暂隐藏（看起来会闪一下）。\n"
            "目前容易把地图上的蓝色火焰、瀑布等误认成水晶，导致布局判断错误，默认关闭。\n"
            "关闭时悬浮窗显示所有水晶点位，可用「下一个/上一个水晶布局」快捷键手动切换。"
        )))

        # 地图区域
        self.map_region_group = QGroupBox("地图区域")
        region_form = make_form(self.map_region_group)
        self.map_region = None
        self.map_region_label = QLabel()
        self.map_region_label.setWordWrap(True)
        region_form.addRow("当前区域", self.map_region_label)
        self.capture_map_region_input_widget = self.add_hotkey_row(
            region_form, "手动框选区域", self.capture_map_region,
            "默认会按游戏画面大小自动推算地图位置，一般不需要框选\n"
            "只有自动推算不准时，才需要在地图画面按下此快捷键手动框选")
        self.clear_map_region_button = make_button("清除手动区域，恢复自动推算", self.clear_map_region)
        region_form.addRow(self.clear_map_region_button)

        # 地图快捷键
        self.map_hotkey_group = QGroupBox("地图快捷键")
        hotkey_form = make_form(self.map_hotkey_group)
        self.set_to_detect_map_input_setting_widget = self.add_hotkey_row(
            hotkey_form, "立即识别地图", self.updater.set_to_detect_map_pattern_once,
            "每局 Day 1 开始后第一次打开完整地图会自动识别，\n识别错误时可以用此快捷键重新识别")
        self.show_map_overlay_input_setting_widget = self.add_hotkey_row(
            hotkey_form, "显示/隐藏地图信息", self.updater.show_or_hide_map_overlay_by_shortcut)
        self.map_pattern_next_input_setting_widget = self.add_hotkey_row(
            hotkey_form, "下一个识别结果", self.map_overlay.next_overlay_image)
        self.map_pattern_last_input_setting_widget = self.add_hotkey_row(
            hotkey_form, "上一个识别结果", self.map_overlay.last_overlay_image)
        self.crystal_layout_next_input_setting_widget = self.add_hotkey_row(
            hotkey_form, "下一个水晶布局", self.map_overlay.next_crystal_layout,
            "在大空洞中切换显示的水晶布局（第0个为所有水晶点位）。\n"
            "开启水晶布局自动识别时，使用快捷键手动切换后本局不再自动切换。")
        self.crystal_layout_last_input_setting_widget = self.add_hotkey_row(
            hotkey_form, "上一个水晶布局", self.map_overlay.last_crystal_layout)

    def init_hp_detect_group(self):
        # HP检测设置
        self.hp_detect_group = QGroupBox("血条比例标记")
        form = make_form(self.hp_detect_group)

        self.hp_detect_enable_checkbox = QCheckBox("启用血条比例标记")
        self.hp_detect_enable_checkbox.stateChanged.connect(self.update_hp_detect_enable)
        form.addRow(make_row(self.hp_detect_enable_checkbox,
                             make_button("查看帮助", self.show_capture_hpbar_region_tutorial)))

        self.hp_detect_keep_last_valid_checkbox = QCheckBox("检测失败时保持上次结果")
        self.hp_detect_keep_last_valid_checkbox.setChecked(False)
        self.hp_detect_keep_last_valid_checkbox.stateChanged.connect(self.update_hp_detect_keep_last_valid)
        form.addRow(make_row(self.hp_detect_keep_last_valid_checkbox, make_help_label(
            "开启后，当血条检测暂时失败时，会继续显示上一次的有效结果\n"
            "可以减少标记的抖动和闪烁，提高稳定性"
        )))

        self.hpbar_region = None
        self.capture_hpbar_region_input_widget = self.add_hotkey_row(
            form, "框选血条区域", self.capture_hpbar_region)
        self.hpbar_region_label = QLabel()
        self.clear_hpbar_region_button = make_button("清除", self.clear_hpbar_region)
        form.addRow("当前区域", make_row(self.hpbar_region_label, self.clear_hpbar_region_button))

    def init_art_timer_group(self):
        # 绝招计时器设置
        self.art_timer_group = QGroupBox("绝招倒计时")
        form = make_form(self.art_timer_group)

        self.art_detect_enable_checkbox = QCheckBox("启用绝招倒计时")
        self.art_detect_enable_checkbox.stateChanged.connect(self.update_art_detect_enable)
        form.addRow(make_row(self.art_detect_enable_checkbox,
                             make_button("查看帮助", self.show_capture_art_region_tutorial)))

        self.use_art_input_setting_widget = self.add_hotkey_row(
            form, "游戏内绝招按键", self.updater.use_art_by_shortcut, "设置为你在游戏中释放绝招的按键")

        self.art_region = None
        self.capture_art_region_input_widget = self.add_hotkey_row(
            form, "框选绝招图标区域", self.capture_art_region)
        self.art_region_label = QLabel()
        self.clear_art_region_button = make_button("清除", self.clear_art_region)
        form.addRow("当前区域", make_row(self.art_region_label, self.clear_art_region_button))

    def init_advanced_group(self):
        # 高级参数（保存到 config_override.yaml，覆盖 config.yaml）
        self.advanced_group = QGroupBox("高级参数")
        form = make_form(self.advanced_group)
        config = Config.get()
        self.advanced_param_widgets: dict[str, QSpinBox | QDoubleSpinBox] = {}
        for key, name, lo, hi, step, suffix, help_text in ADVANCED_PARAMS:
            value = getattr(config, key)
            if isinstance(step, int):
                spin = QSpinBox()
            else:
                spin = QDoubleSpinBox()
                spin.setDecimals(1)
            spin.setRange(lo, hi)
            spin.setSingleStep(step)
            spin.setSuffix(suffix)
            spin.setValue(value)
            spin.valueChanged.connect(lambda v, k=key: self.update_advanced_param(k, v))
            form.addRow(name, make_row(spin, make_help_label(help_text), stretch=False))
            self.advanced_param_widgets[key] = spin
        form.addRow(make_row(
            make_button("恢复默认参数", self.reset_advanced_params),
            make_button("打开配置文件夹", self.open_log_directory),
        ))
        form.addRow(make_tip_label("这些参数保存在配置文件夹的 config_override.yaml 中，程序更新后仍然保留"))

    def init_other_group(self):
        # 其他设置
        self.other_group = QGroupBox("其他")
        form = make_form(self.other_group)

        self.debug_log_checkbox = QCheckBox("开启调试日志")
        self.debug_log_checkbox.setChecked(False)
        self.debug_log_checkbox.stateChanged.connect(self.update_debug_log)
        form.addRow(make_row(self.debug_log_checkbox, make_help_label("反馈问题前建议开启，日志中会记录更详细的识别信息")))

        grid = QGridLayout()
        grid.addWidget(make_button("管理预设", self.open_preset_dialog), 0, 0)
        grid.addWidget(make_button("打开日志位置", self.open_log_directory), 0, 1)
        grid.addWidget(make_button("BUG反馈", self.open_bug_report_window), 1, 0)
        grid.addWidget(make_button("关于", self.open_about_dialog), 1, 1)
        form.addRow(grid)

        reset_all_button = make_button("恢复全部默认设置", self.reset_all_settings)
        reset_all_button.setStyleSheet(BUTTON_STYLE + " color: #c0392b;")
        form.addRow(reset_all_button)

    def init_status_bar(self):
        # 顶部功能状态概览，点击可跳转到对应页面
        self.status_frame = QFrame()
        self.status_frame.setObjectName("status_frame")
        self.status_frame.setStyleSheet("#status_frame { border: 1px solid palette(mid); border-radius: 4px; }")
        grid = QGridLayout(self.status_frame)
        grid.setContentsMargins(8, 6, 8, 6)
        grid.setHorizontalSpacing(16)
        self.status_labels: list[QLabel] = []
        for i in range(6):
            label = QLabel()
            label.setTextFormat(Qt.TextFormat.RichText)
            label.linkActivated.connect(lambda link: self.tabs.setCurrentIndex(int(link)))
            grid.addWidget(label, i // 3, i % 3)
            self.status_labels.append(label)

    def init_layouts(self):
        self.tabs = QTabWidget()
        pages = [
            ("计时器", [self.appearance_group, self.input_group]),
            ("自动计时", [self.auto_timer_group, self.hp_color_group]),
            ("地图识别", [self.map_detect_group, self.map_region_group, self.map_hotkey_group]),
            ("血条 / 绝招", [self.hp_detect_group, self.art_timer_group]),
            ("通用", [self.performance_group, self.advanced_group, self.other_group]),
        ]
        for title, groups in pages:
            page = QWidget()
            page_layout = QVBoxLayout(page)
            for group in groups:
                page_layout.addWidget(group)
            page_layout.addStretch()
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setWidget(page)
            self.tabs.addTab(scroll, title)

        footer = QHBoxLayout()
        footer.addWidget(make_tip_label("修改会自动保存"))
        footer.addStretch()
        footer.addWidget(make_button("关闭", self.close))

        self.layout: QVBoxLayout = QVBoxLayout(self)
        self.layout.addWidget(self.status_frame)
        self.layout.addWidget(self.tabs)
        self.layout.addLayout(footer)

    def init_autosave(self):
        # 任意设置变化后延迟保存，避免程序异常退出时丢失设置
        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.setInterval(800)
        self.save_timer.timeout.connect(self.save_settings)
        for cb in self.findChildren(QCheckBox):
            cb.toggled.connect(self.on_setting_changed)
        for slider in self.findChildren(QSlider):
            slider.valueChanged.connect(self.on_setting_changed)
        for combo in self.findChildren(QComboBox):
            combo.currentTextChanged.connect(self.on_setting_changed)
        for _, widget in self.hotkey_widgets:
            widget.setting_changed.connect(self.on_setting_changed)

    def on_setting_changed(self, *args):
        if self._loading:
            return
        self.refresh_status()
        self.save_timer.start()

    def update_hotkey_conflicts(self):
        """相同快捷键被设置给多个功能时标红提示"""
        combos: dict[tuple, list[str]] = {}
        for name, widget in self.hotkey_widgets:
            setting = widget.get_setting()
            if setting.type and setting.combo:
                combos.setdefault((setting.type, tuple(setting.combo)), []).append(name)
        for name, widget in self.hotkey_widgets:
            setting = widget.get_setting()
            names = combos.get((setting.type, tuple(setting.combo or ())), [])
            others = [n for n in names if n != name]
            if setting.type and setting.combo and others:
                widget.setting_button.setStyleSheet("padding: 4px; color: #c0392b; font-weight: bold;")
                widget.setting_button.setToolTip(f"⚠️与「{'」「'.join(others)}」使用了相同的快捷键")
            else:
                widget.setting_button.setStyleSheet("padding: 4px;")
                widget.setting_button.setToolTip("")

    def refresh_status(self):
        def item(name: str, tab: int, enabled: bool, ready: bool, hint: str = "未设置区域", ok_text: str = "就绪"):
            if not enabled:
                color, text = "gray", "已关闭"
            elif ready:
                color, text = "#27ae60", ok_text
            else:
                color, text = "#e67e22", hint
            return (f'<a href="{tab}" style="text-decoration: none;">{name}</a>'
                    f'：<span style="color: {color};">{text}</span>')
        items = [
            item("计时器", self.TAB_TIMER, self.timer_visible_checkbox.isChecked(), True, ok_text="显示中"),
            item("缩圈自动计时", self.TAB_AUTO_TIMER, self.dayx_detect_enable_checkbox.isChecked(),
                 self.day1_detect_region is not None),
            item("雨中冒险", self.TAB_AUTO_TIMER, self.in_rain_detect_enable_checkbox.isChecked(),
                 self.hpcolor_detect_region is not None),
            item("地图识别", self.TAB_MAP, self.map_detect_enable_checkbox.isChecked(), True,
                 ok_text="手动区域" if self.map_region is not None else "自动区域"),
            item("血条标记", self.TAB_HP_ART, self.hp_detect_enable_checkbox.isChecked(),
                 self.hpbar_region is not None),
            item("绝招倒计时", self.TAB_HP_ART, self.art_detect_enable_checkbox.isChecked(),
                 self.art_region is not None and bool(self.use_art_input_setting_widget.get_setting().type),
                 hint="未设置区域" if self.art_region is None else "未设置按键"),
        ]
        for label, text in zip(self.status_labels, items):
            label.setText(text)
        self.update_hotkey_conflicts()

    def init_preset_dialog(self):
        self.preset_dialog = PresetDialog()
        self.preset_dialog.save_preset_signal.connect(self.save_preset)
        self.preset_dialog.load_preset_signal.connect(self.load_preset)
        self.preset_dialog.remove_preset_signal.connect(self.remove_preset)
        self.update_preset_list_signal.connect(self.preset_dialog.set_preset_names)
        self.update_preset_list()


    def load_settings(self):
        try:
            def load_checkbox_state(checkbox: QCheckBox, state: bool):
                checkbox.setChecked(not state)
                checkbox.setChecked(state)
            def load_slider_value(slider: QSlider, value: int):
                slider.setValue(value - 1)
                slider.setValue(value)
            def load_combobox_value(combobox: QComboBox, value: str):
                combobox.setCurrentText(None)
                combobox.setCurrentText(value)

            self._loading = True
            info("------------------------")
            info("Start to load settings")
            config = Config.get()
            if os.path.exists(SETTINGS_SAVE_PATH):
                data = load_yaml(SETTINGS_SAVE_PATH)
                info(f"Loaded settings from {SETTINGS_SAVE_PATH}")
            else:
                data = {}
                warning(f"Settings file not found: {SETTINGS_SAVE_PATH}, using defaults")
            # 外观
            load_slider_value(self.size_slider, data.get("size", 200))
            load_slider_value(self.opacity_slider, data.get("opacity", 60))
            self.update_overlay_ui_state_signal.emit(OverlayUIState(
                x=data.get("x"),
                y=data.get("y"),
            ))
            load_checkbox_state(self.hide_text_checkbox, data.get("hide_text", False))
            load_checkbox_state(self.timer_visible_checkbox, data.get("timer_visible", True))
            self.toggle_timer_input_setting_widget.set_setting(InputSetting.load_from_dict(data.get("toggle_timer_input_setting")))
            # 快捷键
            self.day_input_setting_widget.set_setting(InputSetting.load_from_dict(data.get("day_input_setting")))
            self.forward_day_input_setting_widget.set_setting(InputSetting.load_from_dict(data.get("forward_day_input_setting")))
            self.back_day_input_setting_widget.set_setting(InputSetting.load_from_dict(data.get("back_day_input_setting")))
            self.in_rain_input_setting_widget.set_setting(InputSetting.load_from_dict(data.get("in_rain_input_setting")))
            # 性能
            load_checkbox_state(self.only_show_when_game_foreground_checkbox, data.get("only_show_when_game_foreground", False))
            load_combobox_value(self.detect_interval_combobox, data.get("detect_interval", "高"))
            load_combobox_value(self.screencap_mode_combobox, data.get("screencap_mode", "自动"))
            # 自动计时
            load_checkbox_state(self.dayx_detect_enable_checkbox, data.get("dayx_detect_enabled", True))
            load_checkbox_state(self.in_rain_detect_enable_checkbox, data.get("in_rain_detect_enabled", True))
            self.capture_dayx_hpcolor_region_input_widget.set_setting(InputSetting.load_from_dict(data.get("capture_dayx_hpbar_region_input_setting")))
            self.dayx_detect_lang = data.get("dayx_detect_lang", "chs")
            load_combobox_value(self.lang_combobox, config.dayx_detect_langs[self.dayx_detect_lang])
            self.day1_detect_region = data.get("day1_detect_region", None)
            self.hpcolor_detect_region = data.get("hp_bar_detect_region", None)
            self.update_day1_hpcolor_regions()
            self.align_to_detect_hp_color_input_widget.set_setting(InputSetting.load_from_dict(data.get("align_to_detect_hp_color_input_setting")))
            self.not_in_rain_hls = data.get("not_in_rain_hls", None)
            self.in_rain_hls = data.get("in_rain_hls", None)
            self.not_in_rain_hls_hdr = data.get("not_in_rain_hls_hdr", None)
            self.in_rain_hls_hdr = data.get("in_rain_hls_hdr", None)
            self.update_hp_color()
            # 地图识别
            load_checkbox_state(self.map_detect_enable_checkbox, data.get("map_detect_enabled", True))
            self.capture_map_region_input_widget.set_setting(InputSetting.load_from_dict(data.get("capture_map_region_input_setting")))
            self.map_region = data.get("map_region", None)
            self.update_map_region()
            self.set_to_detect_map_input_setting_widget.set_setting(InputSetting.load_from_dict(data.get("set_to_detect_map_input_setting")))
            self.show_map_overlay_input_setting_widget.set_setting(InputSetting.load_from_dict(data.get("show_map_overlay_input_setting")))
            load_combobox_value(self.map_pattern_return_topk_combobox, str(data.get("map_pattern_return_topk", config.default_map_pattern_match_topk)))
            self.map_pattern_next_input_setting_widget.set_setting(InputSetting.load_from_dict(data.get("next_map_pattern_input_setting")))
            self.map_pattern_last_input_setting_widget.set_setting(InputSetting.load_from_dict(data.get("last_map_pattern_input_setting")))
            self.crystal_layout_next_input_setting_widget.set_setting(InputSetting.load_from_dict(data.get("next_crystal_layout_input_setting")))
            self.crystal_layout_last_input_setting_widget.set_setting(InputSetting.load_from_dict(data.get("last_crystal_layout_input_setting")))
            # 血条比例标记
            load_checkbox_state(self.hp_detect_enable_checkbox, data.get("hp_detect_enabled", True))
            load_checkbox_state(self.hp_detect_keep_last_valid_checkbox, data.get("hp_detect_keep_last_valid", False))
            self.capture_hpbar_region_input_widget.set_setting(InputSetting.load_from_dict(data.get("capture_hpbar_region_input_setting")))
            self.hpbar_region = data.get("hpbar_region", None)
            self.update_hpbar_region()
            # 绝招计时器
            load_checkbox_state(self.art_detect_enable_checkbox, data.get("art_detect_enabled", True))
            self.capture_art_region_input_widget.set_setting(InputSetting.load_from_dict(data.get("capture_art_region_input_setting")))
            self.use_art_input_setting_widget.set_setting(InputSetting.load_from_dict(data.get("use_art_input_setting")))
            self.art_region = data.get("art_region", None)
            self.update_art_region()
            # 其他
            load_checkbox_state(self.debug_log_checkbox, data.get("debug_log_enabled", False))
            # HDR图像处理
            load_checkbox_state(self.hdr_processing_checkbox, data.get("hdr_processing_enabled", False))
            load_checkbox_state(self.crystal_auto_detect_checkbox, data.get("crystal_auto_detect_enabled", False))

            info("Settings loaded successfully")
        except Exception as e:
            error(f"Failed to load settings: {e}")
        finally:
            self._loading = False
        self.refresh_status()
        info("------------------------")

    def save_settings(self):
        try:
            data = {
                # 外观
                "size": self.size_slider.value(),
                "opacity": self.opacity_slider.value(),
                "x": self.overlay.x(),
                "y": self.overlay.y(),
                "hide_text": self.hide_text_checkbox.isChecked(),
                "timer_visible": self.timer_visible_checkbox.isChecked(),
                "toggle_timer_input_setting": asdict(self.toggle_timer_input_setting_widget.get_setting()),
                # 快捷键
                "day_input_setting": asdict(self.day_input_setting_widget.get_setting()),
                "forward_day_input_setting": asdict(self.forward_day_input_setting_widget.get_setting()),
                "back_day_input_setting": asdict(self.back_day_input_setting_widget.get_setting()),
                "in_rain_input_setting": asdict(self.in_rain_input_setting_widget.get_setting()),
                # 性能
                "only_show_when_game_foreground": self.only_show_when_game_foreground_checkbox.isChecked(),
                "detect_interval": self.detect_interval_combobox.currentText(),
                "screencap_mode": self.screencap_mode_combobox.currentText(),
                # 自动计时
                "dayx_detect_enabled": self.dayx_detect_enable_checkbox.isChecked(),
                "in_rain_detect_enabled": self.in_rain_detect_enable_checkbox.isChecked(),
                "capture_dayx_hpbar_region_input_setting": asdict(self.capture_dayx_hpcolor_region_input_widget.get_setting()),
                "dayx_detect_lang": self.dayx_detect_lang,
                "day1_detect_region": self.day1_detect_region,
                "hp_bar_detect_region": self.hpcolor_detect_region,
                "align_to_detect_hp_color_input_setting": asdict(self.align_to_detect_hp_color_input_widget.get_setting()),
                "not_in_rain_hls": self.not_in_rain_hls,
                "in_rain_hls": self.in_rain_hls,
                "not_in_rain_hls_hdr": self.not_in_rain_hls_hdr,
                "in_rain_hls_hdr": self.in_rain_hls_hdr,
                # 地图识别
                "map_detect_enabled": self.map_detect_enable_checkbox.isChecked(),
                "capture_map_region_input_setting": asdict(self.capture_map_region_input_widget.get_setting()),
                "map_region": self.map_region,
                "set_to_detect_map_input_setting": asdict(self.set_to_detect_map_input_setting_widget.get_setting()),
                "show_map_overlay_input_setting": asdict(self.show_map_overlay_input_setting_widget.get_setting()),
                "map_pattern_return_topk": int(self.map_pattern_return_topk_combobox.currentText()),
                "next_map_pattern_input_setting": asdict(self.map_pattern_next_input_setting_widget.get_setting()),
                "last_map_pattern_input_setting": asdict(self.map_pattern_last_input_setting_widget.get_setting()),
                "next_crystal_layout_input_setting": asdict(self.crystal_layout_next_input_setting_widget.get_setting()),
                "last_crystal_layout_input_setting": asdict(self.crystal_layout_last_input_setting_widget.get_setting()),
                # 血条比例标记
                "hp_detect_enabled": self.hp_detect_enable_checkbox.isChecked(),
                "hp_detect_keep_last_valid": self.hp_detect_keep_last_valid_checkbox.isChecked(),
                "capture_hpbar_region_input_setting": asdict(self.capture_hpbar_region_input_widget.get_setting()),
                "hpbar_region": self.hpbar_region,
                # 绝招计时器
                "art_detect_enabled": self.art_detect_enable_checkbox.isChecked(),
                "capture_art_region_input_setting": asdict(self.capture_art_region_input_widget.get_setting()),
                "use_art_input_setting": asdict(self.use_art_input_setting_widget.get_setting()),
                "art_region": self.art_region,
                # 其他
                "debug_log_enabled": self.debug_log_checkbox.isChecked(),
                "hdr_processing_enabled": self.hdr_processing_checkbox.isChecked(),
                "crystal_auto_detect_enabled": self.crystal_auto_detect_checkbox.isChecked(),
            }
            save_yaml(SETTINGS_SAVE_PATH, data)
            info(f"Saved settings to {SETTINGS_SAVE_PATH}")
        except Exception as e:
            error(f"Failed to save settings: {e}")


    def showEvent(self, event):
        self.update_overlay_ui_state_signal.emit(OverlayUIState(
            draggable=True,
            is_setting_opened=True,
        ))
        self.update_map_overlay_ui_state_signal.emit(MapOverlayUIState(
            is_setting_opened=True,
        ))
        self.updater.is_setting_opened = True
        # self.load_settings()
        super().showEvent(event)
        info("Settings window opened")

    def closeEvent(self, event):
        self.update_overlay_ui_state_signal.emit(OverlayUIState(
            draggable=False,
            is_setting_opened=False,
        ))
        self.update_map_overlay_ui_state_signal.emit(MapOverlayUIState(
            is_setting_opened=False,
        ))
        self.updater.is_setting_opened = False
        self.save_settings()
        super().closeEvent(event)
        info("Settings window closed")


    def __init__(self, overlay: OverlayWidget, map_overlay: MapOverlayWidget, updater: Updater, input: InputWorker):
        super().__init__()
        config = Config.get()
        self.overlay = overlay
        self.map_overlay = map_overlay
        self.update_overlay_ui_state_signal.connect(overlay.update_ui_state)
        self.update_map_overlay_ui_state_signal.connect(map_overlay.update_ui_state)
        self.updater = updater
        self.input = input

        self.setWindowIcon(QIcon(ICON_PATH))
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(f'{APP_NAME}.{APP_VERSION}')
        except Exception as e:
            warning(f"Failed to set AppUserModelID: {e}")

        self.setWindowTitle(f"{APP_FULLNAME} - 设置")
        self.setMinimumSize(480, 480)
        self.resize(560, 720)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)

        self._loading = False
        self.hotkey_widgets: list[tuple[str, InputSettingWidget]] = []

        self.init_appearance_group()
        self.init_input_group()
        self.init_performance_group()
        self.init_auto_timer_group()
        self.init_hp_color_group()
        self.init_map_detect_group()
        self.init_hp_detect_group()
        self.init_art_timer_group()
        self.init_advanced_group()
        self.init_other_group()
        self.init_status_bar()

        self.init_layouts()

        self.init_preset_dialog()

        # 加载设置
        self.load_settings()

        self.init_autosave()


    # =========================== Preset =========================== #

    def load_preset(self, preset_name: str):
        info(f"Loading preset settings '{preset_name}'")

        if not comfirm_box(f"是否加载预设设置：\"{preset_name}\"？\n当前设置将被覆盖。", self.preset_dialog):
            info(f"Loading preset settings '{preset_name}' canceled by user")
            return

        preset_path = os.path.join(PRESET_SETTINGS_DIR, f"{preset_name}.yaml")
        if not os.path.exists(preset_path):
            warning(f"Preset settings file not found: {preset_path}")
            error_box(f"预设配置文件未找到：{preset_path}", self.preset_dialog)
            self.update_preset_list()
            return
        
        # overide current settings with preset
        current_path = SETTINGS_SAVE_PATH
        self.save_settings()
        if os.path.exists(current_path + '.bak'):
            os.remove(current_path + '.bak')
        os.rename(current_path, current_path + ".bak")
        try:
            shutil.copyfile(preset_path, current_path)
            self.load_settings()
            info(f"Loaded preset settings '{preset_name}' from {preset_path}")
            info_box(f"成功加载预设设置：{preset_name}", self.preset_dialog)
        except Exception as e:
            os.replace(current_path + ".bak", current_path)
            self.load_settings()
            error(f"Failed to load preset settings '{preset_name}': {e}")
            error_box(f"加载预设设置失败：{e}\n已还原到之前的设置。", self.preset_dialog)
        
        self.update_preset_list()
        
    def save_preset(self, preset_name: str):
        preset_path = os.path.join(PRESET_SETTINGS_DIR, f"{preset_name}.yaml")
        if os.path.exists(preset_path):
            if not comfirm_box(f"预设设置 \"{preset_name}\"已存在，是否覆盖？", self.preset_dialog):
                info(f"Saving preset settings '{preset_name}' canceled by user")
                return
        try:
            os.makedirs(PRESET_SETTINGS_DIR, exist_ok=True)
            self.save_settings()
            shutil.copyfile(SETTINGS_SAVE_PATH, preset_path)
            info(f"Saved preset settings '{preset_name}' to {preset_path}")
            # info_box(f"成功保存预设设置：\"{preset_name}\"", self.preset_dialog)

        except Exception as e:
            error(f"Failed to save preset settings '{preset_name}': {e}")
            error_box(f"保存预设设置失败：{e}", self.preset_dialog)

        self.update_preset_list()

    def remove_preset(self, preset_name: str):
        preset_path = os.path.join(PRESET_SETTINGS_DIR, f"{preset_name}.yaml")
        if not os.path.exists(preset_path):
            warning(f"Preset settings file not found: {preset_path}")
            error_box(f"预设配置文件未找到：{preset_path}", self.preset_dialog)
            return
        if not comfirm_box(f"是否删除预设设置：\"{preset_name}\"？", self.preset_dialog):
            info(f"Removing preset settings '{preset_name}' canceled by user")
            return
        try:
            os.remove(preset_path)
            info(f"Removed preset settings '{preset_name}'")
            # info_box(f"成功删除预设设置：\"{preset_name}\"", self.preset_dialog)

        except Exception as e:
            error(f"Failed to remove preset settings '{preset_name}': {e}")
            error_box(f"删除预设设置失败：{e}", self.preset_dialog)

        self.update_preset_list()

    def open_preset_dialog(self):
        self.preset_dialog.show()
        self.preset_dialog.activateWindow()

    def update_preset_list(self):
        try:
            preset_names = []
            if os.path.exists(PRESET_SETTINGS_DIR):
                for file in os.listdir(PRESET_SETTINGS_DIR):
                    if file.endswith(".yaml"):
                        preset_names.append(os.path.splitext(file)[0])
            self.update_preset_list_signal.emit(preset_names)
        except Exception as e:
            error(f"Failed to update preset list: {e}")

    # =========================== Overlay Appearance =========================== #

    def update_overlay_size(self, value):
        self.size_value_label.setText(f"{value}%")
        self.update_overlay_ui_state_signal.emit(OverlayUIState(scale=value / 100.0))
        info(f"Overlay size changed to {value}")

    def update_overlay_opacity(self, value):
        self.opacity_value_label.setText(f"{value}%")
        self.update_overlay_ui_state_signal.emit(OverlayUIState(opacity=value / 100.0))
        info(f"Overlay opacity changed to {value}")

    def update_overlay_position_center(self):
        self.update_overlay_ui_state_signal.emit(OverlayUIState(set_x_to_center=True))
        info("Overlay position set to center")

    def update_overlay_position_top_center(self):
        self.update_overlay_ui_state_signal.emit(OverlayUIState(set_to_top_center=True))
        info("Overlay position set to top center")

    def recover_timer(self):
        """找回计时器：打开显示、恢复可见的大小和不透明度，并移到顶部居中"""
        self.timer_visible_checkbox.setChecked(True)
        if self.opacity_slider.value() < 60:
            self.opacity_slider.setValue(60)
        if self.size_slider.value() < 100:
            self.size_slider.setValue(100)
        self.update_overlay_position_top_center()
        self.on_setting_changed()
        info("Timer overlay recovered.")

    def update_timer_visible(self, state):
        visible = bool(state)
        self.update_overlay_ui_state_signal.emit(OverlayUIState(visible=visible))
        info(f"Overlay timer visible set to {visible}")

    def toggle_timer_visible(self):
        self.timer_visible_checkbox.setChecked(not self.timer_visible_checkbox.isChecked())

    def update_hide_text(self, state):
        self.update_overlay_ui_state_signal.emit(OverlayUIState(hide_text=state))
        info(f"Overlay hide text set to {state}")

    def reset_overlay_position(self):
        screen_size = QApplication.primaryScreen().geometry().size()
        sw, sh = screen_size.width(), screen_size.height()
        ow, oh = self.overlay.width(), self.overlay.height()
        self.overlay.move(int((sw - ow) / 2), int((sh - oh) / 2))
        info("Overlay position reset to main screen center")

    # =========================== DayX In Rain Detect =========================== #

    def update_dayx_detect_enable(self, state):
        enabled = self.dayx_detect_enable_checkbox.isChecked()
        self.updater.dayx_detect_enabled = enabled
        info(f"DayX detect enabled: {enabled}")

    def update_detect_lang(self):
        config = Config.get()
        lang_name = self.lang_combobox.currentText()
        for k, v in config.dayx_detect_langs.items():
            if v == lang_name:
                self.dayx_detect_lang = k
                break
        self.updater.dayx_detect_lang = self.dayx_detect_lang
        info(f"DayX detect lang changed to {self.dayx_detect_lang}")

    def capture_day1_hpcolor_region(self):
        COLOR_HPCOLOR = "#a84747"
        COLOR_DAY_I = "#686435"
        SCREENSHOT_WINDOW_CONFIG = {
            'annotation_buttons': [
                {'pos': (0.8, 0.1), 'size': 32, 'color': COLOR_HPCOLOR, 'text': '点我并框出 血条 的区域'},
                {'pos': (0.8, 0.2), 'size': 32, 'color': COLOR_DAY_I, 'text': '点我并框出 DAY I 图标 的区域'},
            ],
            'control_buttons': {
                'cancel':   {'pos': (0.8, 0.5), 'size': 50, 'color': "#b3b3b3", 'text': '取消'},
                'save':     {'pos': (0.8, 0.6), 'size': 50, 'color': "#ffffff", 'text': '保存'},
            }
        }
        window = CaptureRegionWindow(SCREENSHOT_WINDOW_CONFIG, self.input)
        region_result = window.capture_and_show()
        if region_result is None:
            warning("Day1 hpcolor region setting canceled")
            return
        else:
            if screenshot := window.screenshot_at_saving:
                save_path = get_appdata_path("detect_region_screenshot.jpg")
                screenshot.save(save_path)
            for item in region_result:
                if item['color'] == COLOR_HPCOLOR:
                    self.hpcolor_detect_region = list(item['rect'])
                elif item['color'] == COLOR_DAY_I:
                    self.day1_detect_region = list(item['rect'])
            self.update_day1_hpcolor_regions()
            self.save_settings()

    def show_capture_day1_hpcolor_region_tutorial(self):
        tutorial_imgs = [QPixmap(str(DETECT_REGION_TUTORIAL_IMG_PATH).format(i=i)) for i in range(1, 8)]
        img_widgets: list[QLabel] = []
        for img in tutorial_imgs:
            img_widget = QLabel()
            img = img.scaledToHeight(min(100, img.height()), Qt.TransformationMode.SmoothTransformation)
            img_widget.setPixmap(img)
            img_widget.setStyleSheet("border: 1px solid #ccc;")
            img_widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
            img_widgets.append(img_widget)
        msg = QMessageBox(self)
        msg.setMaximumWidth(400)
        msg.setWindowTitle("自动计时帮助")
        layout: QVBoxLayout = QVBoxLayout()
        layout.addWidget(QLabel("自动计时原理为通过定时截图分析画面内容，因此需要先框选检测区域，请按照以下步骤操作："))
        layout.addWidget(QLabel("1. 首先在设置界面调整\"截取检测区域快捷键\""))
        layout.addWidget(img_widgets[0])
        layout.addWidget(QLabel("2. 开始一局单人游戏，在游戏第一天开始，出现\"DAY I\"图标时，按下设置的快捷键\n"
                                "画面会定格，并出现几个按钮（如果此时鼠标被锁定在屏幕中间，点一下左键即可）"))
        hlayout = QHBoxLayout()
        hlayout.addWidget(img_widgets[1])
        hlayout.addWidget(img_widgets[2])
        layout.addLayout(hlayout)
        layout.addWidget(QLabel("3. 点击\"点我并框出 血条 的区域\"按钮，然后用鼠标框选屏幕上的血条区域\n"
                                "框选的区域如下图所示，需要把血条的纯色内部框进去，尽量不要框到边框\n"
                                "⚠️即使你画面里的血条可能更长，但也只需要框【最左边的一小段】！"))
        layout.addWidget(img_widgets[3])
        layout.addWidget(QLabel("4. 点击\"点我并框出 DAY I 图标 的区域\"按钮，然后用鼠标框选屏幕上的 DAY I 图标\n"
                                "框选的区域如下图所示，需要把最左边的D和最右边的I的突出部分也要框进去\n"
                                "⚠️尽量严丝合缝，上下不要留有空隙"))
        layout.addWidget(img_widgets[4])
        layout.addWidget(QLabel("5. 最后点击\"保存\"按钮完成设置，在设置界面查看是否显示\"已设置\""))
        layout.addWidget(img_widgets[5])
        layout.addWidget(QLabel("6. 之后正常游玩即可自动计时，若修改游戏分辨率则需要重新框选"))
        layout.addWidget(QLabel("ℹ️ 缩圈自动计时可能失效的场景：DAY X图标出现时正在浏览背包和地图\n"
                                "ℹ️ 雨中冒险计时可能失效的场景：当前血量过少 / 开启HDR"))
        layout.addWidget(QLabel("⚠️ 即使开启了自动检测，仍然推荐设置快捷键作为备用"))
        layout.addWidget(QLabel("7. 如果缩圈检测失效，可能是因为游戏语言不同，可以调整设置里的\"游戏语言\""))
        layout.addWidget(img_widgets[6])
        layout.addWidget(QLabel("8. 如果雨中冒险检测失效，可能是因为色差，可以尝试设置里的\"校准血条颜色\""))
        msg.layout().addLayout(layout, 0, 0)
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg.exec()
    
    def update_day1_hpcolor_regions(self):
        self.updater.day1_detect_region = self.day1_detect_region
        self.updater.hpcolor_detect_region = self.hpcolor_detect_region
        info(f"Updated detect regions: day1={self.day1_detect_region}, hpcolor={self.hpcolor_detect_region}")
        set_region_label(self.day1_detect_region_label, self.day1_detect_region)
        set_region_label(self.hpcolor_detect_region_label, self.hpcolor_detect_region)
        self.clear_day1_hpcolor_region_button.setEnabled(
            self.day1_detect_region is not None or self.hpcolor_detect_region is not None)
        self.refresh_status()

    def clear_day1_hpcolor_regions(self):
        if not comfirm_box("确定要清除缩圈和雨中冒险的检测区域吗？\n清除后需要重新框选才能自动计时。", self):
            return
        self.day1_detect_region = None
        self.hpcolor_detect_region = None
        self.update_day1_hpcolor_regions()
        self.save_settings()
 
    # ===========================  Hp Color Align =========================== #

    def update_in_rain_detect_enable(self, state):
        enabled = self.in_rain_detect_enable_checkbox.isChecked()
        self.updater.in_rain_detect_enabled = enabled
        info(f"In Rain detect enabled: {enabled}")

    def capture_hp_color(self):
        COLOR_NOT_IN_RAIN = "#b83232"
        COLOR_IN_RAIN = "#c03184"
        SCREENSHOT_WINDOW_CONFIG = {
            'annotation_buttons': [
                {'pos': (0.8, 0.1), 'size': 32, 'color': COLOR_NOT_IN_RAIN, 'text': '点我并框出 正常颜色血条 的区域'},
                {'pos': (0.8, 0.2), 'size': 32, 'color': COLOR_IN_RAIN,     'text': '点我并框出 雨中颜色血条 的区域'},
            ],
            'control_buttons': {
                'cancel':   {'pos': (0.8, 0.5), 'size': 50, 'color': "#b3b3b3", 'text': '取消'},
                'save':     {'pos': (0.8, 0.6), 'size': 50, 'color': "#ffffff", 'text': '保存'},
            }
        }
        window = CaptureRegionWindow(SCREENSHOT_WINDOW_CONFIG, self.input)
        region_result = window.capture_and_show()
        if region_result is None:
            warning("align hp color setting canceled")
            return
        else:
            for item in region_result:
                if item['color'] == COLOR_NOT_IN_RAIN:
                    hls = RainDetector.get_to_detect_hp_hls(window.screenshot_pixmap, item['rect'])
                    # 根据HDR处理是否开启来决定修改哪个配置项
                    if self.updater.hdr_processing_enabled:
                        self.not_in_rain_hls_hdr = hls
                    else:
                        self.not_in_rain_hls = hls
                elif item['color'] == COLOR_IN_RAIN:
                    hls = RainDetector.get_to_detect_hp_hls(window.screenshot_pixmap, item['rect'])
                    # 根据HDR处理是否开启来决定修改哪个配置项
                    if self.updater.hdr_processing_enabled:
                        self.in_rain_hls_hdr = hls
                    else:
                        self.in_rain_hls = hls
            self.update_hp_color()
            self.save_settings()

    def clear_hp_color(self):
        # 根据HDR模式显示不同的确认信息
        mode_text = "HDR模式" if self.updater.hdr_processing_enabled else "普通模式"
        reply = QMessageBox.question(self, '确认', f'确定要重置{mode_text}下的血条颜色设置为默认吗？', 
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            # 根据HDR模式仅重置对应的配置
            if self.updater.hdr_processing_enabled:
                self.not_in_rain_hls_hdr = None
                self.in_rain_hls_hdr = None
            else:
                self.not_in_rain_hls = None
                self.in_rain_hls = None
            self.update_hp_color()

    def show_capture_hp_color_help(self):
        tutorial_imgs = [QPixmap(str(COLOR_ALIGN_TUTORIAL_IMG_PATH).format(i=i)) for i in range(1, 4)]
        img_widgets: list[QLabel] = []
        for img in tutorial_imgs:
            img_widget = QLabel()
            img = img.scaledToHeight(min(100, img.height()), Qt.TransformationMode.SmoothTransformation)
            img_widget.setPixmap(img)
            img_widget.setStyleSheet("border: 1px solid #ccc;")
            img_widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
            img_widgets.append(img_widget)
        msg = QMessageBox(self)
        msg.setMaximumWidth(400)
        msg.setWindowTitle("校准血条颜色帮助")
        layout: QVBoxLayout = QVBoxLayout()
        layout.addWidget(QLabel("ℹ️ 如果你设置完检测区域后能正常计时，则不需要进行校准"))
        layout.addWidget(QLabel("雨中冒险自动计时原理为检测血条颜色，有可能因为色差而失效，则需要使用校准步骤："))
        layout.addWidget(QLabel("1. 首先在设置界面调整\"校准血条颜色快捷键\""))
        layout.addWidget(QLabel("2. 开始一局单人游戏，在画面中有血条时按下设置的快捷键\n"
                                "画面定格并显示出按钮"))
        layout.addWidget(img_widgets[0])
        layout.addWidget(QLabel("3. 如果画面中有正常血条，则点击\"点我框选 正常颜色血条 的区域\"按钮\n"
                                "然后拖动鼠标框出血条中的纯色部分，点击保存按钮"))
        layout.addWidget(img_widgets[1])
        layout.addWidget(QLabel("4. 以相同的步骤对在雨里的血条也框选一次（推荐单人去roll在圈外的出生点）"))
        layout.addWidget(QLabel("5. 设置界面看到两个颜色显示已设置即可，重置按钮可以退回到程序内置的默认颜色"))
        layout.addWidget(img_widgets[2])

        msg.layout().addLayout(layout, 0, 0)
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg.exec()

    def update_hp_color(self):
        self.updater.not_in_rain_hls = self.not_in_rain_hls
        self.updater.in_rain_hls = self.in_rain_hls
        self.updater.not_in_rain_hls_hdr = self.not_in_rain_hls_hdr
        self.updater.in_rain_hls_hdr = self.in_rain_hls_hdr
        info(f"Updated hp color: not_in_rain_hls={self.not_in_rain_hls}, in_rain_hls={self.in_rain_hls}, not_in_rain_hls_hdr={self.not_in_rain_hls_hdr}, in_rain_hls_hdr={self.in_rain_hls_hdr}")
        
        # 根据HDR模式显示不同的配置状态
        if self.updater.hdr_processing_enabled:
            # HDR模式：显示HDR配置状态
            if self.not_in_rain_hls_hdr is None:
                self.not_in_rain_label.setText(f"HDR:默认")
                self.not_in_rain_label.setStyleSheet(f"background-color: #fff; color: black")
            else:
                self.not_in_rain_label.setText(f"HDR:已设置")
                self.not_in_rain_label.setStyleSheet(f"background-color: rgb{hls_to_rgb(self.not_in_rain_hls_hdr)}; color: white")
            if self.in_rain_hls_hdr is None:
                self.in_rain_label.setText(f"HDR:默认")
                self.in_rain_label.setStyleSheet(f"background-color: #fff; color: black")
            else:
                self.in_rain_label.setText(f"HDR:已设置")
                self.in_rain_label.setStyleSheet(f"background-color: rgb{hls_to_rgb(self.in_rain_hls_hdr)}; color: white")
        else:
            # 非HDR模式：显示普通配置状态
            if self.not_in_rain_hls is None:
                self.not_in_rain_label.setText(f"默认")
                self.not_in_rain_label.setStyleSheet(f"background-color: #fff; color: black")
            else:
                self.not_in_rain_label.setText(f"已设置")
                self.not_in_rain_label.setStyleSheet(f"background-color: rgb{hls_to_rgb(self.not_in_rain_hls)}; color: white")
            if self.in_rain_hls is None:
                self.in_rain_label.setText(f"默认")
                self.in_rain_label.setStyleSheet(f"background-color: #fff; color: black")
            else:
                self.in_rain_label.setText(f"已设置")
                self.in_rain_label.setStyleSheet(f"background-color: rgb{hls_to_rgb(self.in_rain_hls)}; color: white")

    # =========================== Map Detect =========================== #

    def update_map_detect_enable(self, state):
        enabled = self.map_detect_enable_checkbox.isChecked()
        self.updater.map_detect_enabled = enabled
        info(f"Map detect enabled: {enabled}")

    def show_capture_map_region_tutorial(self):
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setWindowTitle("注意事项")
        msg.setText("""
该功能通过解包数据展示详细的地图剧透信息，建议在休闲游戏时避免使用。
请确保在不会影响到你以及你的队友的游戏体验的前提下使用该功能。
对于使用该功能对游戏体验产生的破坏，工具作者不承担任何责任。
（感谢来自 Fuwish@bilibili 的地图解包数据）
""".strip())
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg.exec()

        tutorial_imgs = [QPixmap(str(MAP_DETECT_TUTORIAL_IMG_PATH).format(i=i)) for i in range(1, 4)]
        img_widgets: list[QLabel] = []
        for img in tutorial_imgs:
            img_widget = QLabel()
            img = img.scaledToHeight(min(100, img.height()), Qt.TransformationMode.SmoothTransformation)
            img_widget.setPixmap(img)
            img_widget.setStyleSheet("border: 1px solid #ccc;")
            img_widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
            img_widgets.append(img_widget)
        msg = QMessageBox(self)
        msg.setMaximumWidth(400)
        msg.setWindowTitle("识别地图帮助")
        layout: QVBoxLayout = QVBoxLayout()
        layout.addWidget(QLabel("1. 首先在设置界面调整\"截取地图区域快捷键\""))
        layout.addWidget(img_widgets[0])
        layout.addWidget(QLabel("2. 在任意有地图的游戏画面下按下设置的快捷键，并框选地图的区域\n"
                                "⚠️框的区域需要和地图的边框完全贴合"))
        layout.addWidget(img_widgets[1])
        layout.addWidget(QLabel("3. 回到设置界面看到\"已设置\"即可"))
        layout.addWidget(img_widgets[2])
        layout.addWidget(QLabel("4. 识别地图功能触发机制："))
        layout.addWidget(QLabel("ℹ️ 地图必须要完整展示（缩放到最小）时才能正常识别"))
        layout.addWidget(QLabel("ℹ️ 自动识别触发："))
        layout.addWidget(QLabel("       每次缩圈Day1计时开始后（无论是自动计时还是手动开始），第一次检测到完整地图时，\n"
                                "       会触发一次自动识别，直到下一次Day1计时开始前不会再次触发"))
        layout.addWidget(QLabel("ℹ️ 手动识别触发："))
        layout.addWidget(QLabel("       可以用“识别地图快捷键”手动触发识别"))
        layout.addWidget(QLabel("5. 识别成功后，地图在缩放到最小的状态时，信息会悬浮显示在地图上（暂时不支持跟随缩放）\n"
                                "可以用“显示/隐藏信息快捷键”切换显示\n"))
        layout.addWidget(QLabel("⚠️某些地图的数据可能有错误，发现错误可截图反馈给作者"))
        msg.layout().addLayout(layout, 0, 0)
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg.exec()

    def capture_map_region(self):
        COLOR_MAP_REGION = "#4384b9"
        SCREENSHOT_WINDOW_CONFIG = {
            'annotation_buttons': [
                {'pos': (0.5, 0.1), 'size': 32, 'color': COLOR_MAP_REGION, 'text': '点我并框出 地图 的区域'},
            ],
            'control_buttons': {
                'cancel':   {'pos': (0.3, 0.5), 'size': 50, 'color': "#b3b3b3", 'text': '取消'},
                'save':     {'pos': (0.3, 0.6), 'size': 50, 'color': "#ffffff", 'text': '保存'},
            }
        }
        window = CaptureRegionWindow(SCREENSHOT_WINDOW_CONFIG, self.input)
        region_result = window.capture_and_show()
        if region_result is None:
            warning("Map region setting canceled")
            return
        else:
            if screenshot := window.screenshot_at_saving:
                save_path = get_appdata_path("map_region_screenshot.jpg")
                screenshot.save(save_path)
            for item in region_result:
                if item['color'] == COLOR_MAP_REGION:
                    # 保持正方形
                    x, y, w, h = item['rect']
                    self.map_region = list((x, y, min(w, h), min(w, h)))
                self.update_map_region()
            self.save_settings()

    def update_map_region(self):
        map_region = self.map_region
        if map_region is not None:
            old_map_region = map_region.copy()
            screen = get_qt_screen_by_region(map_region)
            scale = screen.devicePixelRatio()
            map_region = process_region_to_adapt_scale(map_region, scale)
            info(f"Map region adapted to screen scale {scale}: {old_map_region} -> {map_region}")
        if self.updater.map_region != map_region:
            self.updater.set_to_detect_map_pattern_once()
        self.updater.map_region = map_region
        info(f"Updated map region: map_region={map_region}")
        if map_region is None:
            self.map_region_label.setText("自动推算（按游戏画面大小，识别不准时再手动框选）")
            self.map_region_label.setStyleSheet("color: #27ae60;")
        else:
            self.map_region_label.setText(f"手动框选 {map_region}")
            self.map_region_label.setStyleSheet("color: #2980b9;")
        self.clear_map_region_button.setEnabled(map_region is not None)
        self.refresh_status()

    def clear_map_region(self):
        self.map_region = None
        self.update_map_region()
        self.save_settings()

    def update_map_pattern_return_topk(self, text: str):
        self.updater.map_pattern_return_topk = int(text)
        info(f"Map pattern return topk changed to {text}")

    # =========================== Performance =========================== #

    def update_detect_interval(self, text: str):
        config = Config.get()
        detect_interval = config.detect_intervals.get(text, 0.2)
        self.updater.detect_interval = detect_interval
        info(f"Detect interval changed to {detect_interval} seconds ({text})")

    def update_screencap_mode(self, text: str):
        from src.screencap import ScreencapMode
        mode_map = {"自动": ScreencapMode.AUTO, "仅前台": ScreencapMode.FOREGROUND, "仅后台": ScreencapMode.BACKGROUND}
        mode = mode_map.get(text, ScreencapMode.AUTO)
        self.updater.screencap_mode = mode
        info(f"Screencap mode changed to {text}")

    def update_only_show_when_game_foreground(self, state):
        enabled = self.only_show_when_game_foreground_checkbox.isChecked()
        self.update_overlay_ui_state_signal.emit(OverlayUIState(only_show_when_game_foreground=enabled))
        self.update_map_overlay_ui_state_signal.emit(MapOverlayUIState(only_show_when_game_foreground=enabled))
        self.updater.only_detect_when_game_foreground = enabled
        info(f"Overlay only show when game foreground: {enabled}")

    # =========================== HP Detect =========================== #
        
    def update_hp_detect_enable(self, state):
        self.updater.hp_detect_enabled = self.hp_detect_enable_checkbox.isChecked()
        info(f"HP detect enabled: {self.updater.hp_detect_enabled}")

    def update_hp_detect_keep_last_valid(self, state):
        enabled = self.hp_detect_keep_last_valid_checkbox.isChecked()
        self.updater.hp_detect_keep_last_valid = enabled
        info(f"HP detect keep last valid: {enabled}")

    def capture_hpbar_region(self):
        COLOR_HPBAR_REGION = "#eb3b3b"
        SCREENSHOT_WINDOW_CONFIG = {
            'annotation_buttons': [
                {'pos': (0.5, 0.1), 'size': 32, 'color': COLOR_HPBAR_REGION, 'text': '点我并框出 血条 的区域'},
            ],
            'control_buttons': {
                'cancel':   {'pos': (0.3, 0.5), 'size': 50, 'color': "#b3b3b3", 'text': '取消'},
                'save':     {'pos': (0.3, 0.6), 'size': 50, 'color': "#ffffff", 'text': '保存'},
            }
        }
        window = CaptureRegionWindow(SCREENSHOT_WINDOW_CONFIG, self.input)
        region_result = window.capture_and_show()
        if region_result is None:
            warning("Hpbar region setting canceled")
            return
        else:
            if screenshot := window.screenshot_at_saving:
                save_path = get_appdata_path("hpbar_region_screenshot.jpg")
                screenshot.save(save_path)
            for item in region_result:
                if item['color'] == COLOR_HPBAR_REGION:
                    self.hpbar_region = list(item['rect'])
                self.update_hpbar_region()
            self.save_settings()

    def show_capture_hpbar_region_tutorial(self):
        tutorial_imgs = [QPixmap(str(HP_DETECT_TUTORIAL_IMG_PATH).format(i=i)) for i in range(1, 5)]
        img_widgets: list[QLabel] = []
        for img in tutorial_imgs:
            img_widget = QLabel()
            img = img.scaledToHeight(min(100, img.height()), Qt.TransformationMode.SmoothTransformation)
            img_widget.setPixmap(img)
            img_widget.setStyleSheet("border: 1px solid #ccc;")
            img_widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
            img_widgets.append(img_widget)
        msg = QMessageBox(self)
        msg.setMaximumWidth(400)
        msg.setWindowTitle("血条比例标记")
        layout: QVBoxLayout = QVBoxLayout()
        layout.addWidget(QLabel("该功能用于在血条上显示：40%（血量偏低触发词条）\n"
                                "85%（非满血时触发的负面词条）和100%（满血）三个标记"))
        layout.addWidget(QLabel("1. 首先在设置界面调整\"截取血条区域快捷键\""))
        layout.addWidget(img_widgets[0])
        layout.addWidget(QLabel("2. 在任意有血条的游戏画面下按下设置的快捷键，并框选血条的区域"))
        layout.addWidget(img_widgets[1])
        layout.addWidget(QLabel("⚠️ 框选的要求：\n"
                                "【高度】和血条完全相同\n"
                                "【左侧边】和血条贴合\n"
                                "【长度】无所谓"))
        layout.addWidget(img_widgets[2])
        layout.addWidget(QLabel("3. 回到设置界面看到\"已设置\"即可"))
        layout.addWidget(img_widgets[3])
        layout.addWidget(QLabel("4. 之后游玩时，在血条的上方就会悬浮显示三个标记\n"))
        msg.layout().addLayout(layout, 0, 0)
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg.exec()

    def update_hpbar_region(self):
        self.updater.hpbar_region = self.hpbar_region
        info(f"Updated hpbar region: hpbar_region={self.hpbar_region}")
        set_region_label(self.hpbar_region_label, self.hpbar_region)
        self.clear_hpbar_region_button.setEnabled(self.hpbar_region is not None)
        self.refresh_status()

    def clear_hpbar_region(self):
        self.hpbar_region = None
        self.update_hpbar_region()
        self.save_settings()

    # =========================== Art Detect =========================== #

    def update_art_detect_enable(self, state):
        self.updater.art_detect_enabled = self.art_detect_enable_checkbox.isChecked()
        info(f"Art detect enabled: {self.updater.art_detect_enabled}")
    
    def capture_art_region(self):
        COLOR_ART_REGION = "#3235eb"
        SCREENSHOT_WINDOW_CONFIG = {
            'annotation_buttons': [
                {'pos': (0.5, 0.5), 'size': 32, 'color': COLOR_ART_REGION, 'text': '点我并框出 绝招图标 的区域'},
            ],
            'control_buttons': {
                'cancel':   {'pos': (0.3, 0.5), 'size': 50, 'color': "#b3b3b3", 'text': '取消'},
                'save':     {'pos': (0.3, 0.6), 'size': 50, 'color': "#ffffff", 'text': '保存'},
            }
        }
        window = CaptureRegionWindow(SCREENSHOT_WINDOW_CONFIG, self.input)
        region_result = window.capture_and_show()
        if region_result is None:
            warning("Art region setting canceled")
            return
        else:
            if screenshot := window.screenshot_at_saving:
                save_path = get_appdata_path("art_region_screenshot.jpg")
                screenshot.save(save_path)
            for item in region_result:
                if item['color'] == COLOR_ART_REGION:
                    self.art_region = list(item['rect'])
                self.update_art_region()
            self.save_settings()

    def show_capture_art_region_tutorial(self):
        tutorial_imgs = [QPixmap(str(ART_DETECT_TUTORIAL_IMG_PATH).format(i=i)) for i in range(1, 6)]
        img_widgets: list[QLabel] = []
        for img in tutorial_imgs:
            img_widget = QLabel()
            img = img.scaledToHeight(min(100, img.height()), Qt.TransformationMode.SmoothTransformation)
            img_widget.setPixmap(img)
            img_widget.setStyleSheet("border: 1px solid #ccc;")
            img_widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
            img_widgets.append(img_widget)
        msg = QMessageBox(self)
        msg.setMaximumWidth(400)
        msg.setWindowTitle("绝招倒计时")
        layout: QVBoxLayout = QVBoxLayout()
        layout.addWidget(QLabel("该功能用于显示绝招效果的倒计时，支持的角色：女爵、隐士、执行者、复仇者、学者\n"
                                "只能显示自己使用的绝招效果的倒计时"))
        layout.addWidget(QLabel("1. 首先在设置界面调整\"截取绝招图标区域快捷键\""))
        layout.addWidget(img_widgets[0])
        layout.addWidget(QLabel("2. 在任意有绝招图标的游戏画面下按下设置的快捷键，并框选绝招图标的区域"))
        layout.addWidget(img_widgets[1])
        layout.addWidget(QLabel("⚠️ 框选的要求：框和绝招图标的圆的边缘贴合"))
        layout.addWidget(img_widgets[2])
        layout.addWidget(QLabel("3. 回到设置界面看到\"已设置\""))
        layout.addWidget(img_widgets[3])
        layout.addWidget(QLabel("4. 然后设置\"绝招快捷键\"为你的游戏中使用绝招的按键即可"))
        layout.addWidget(img_widgets[4])
        msg.layout().addLayout(layout, 0, 0)
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg.exec()

    def update_art_region(self):
        self.updater.art_region = self.art_region
        info(f"Updated art region: art_region={self.art_region}")
        set_region_label(self.art_region_label, self.art_region)
        self.clear_art_region_button.setEnabled(self.art_region is not None)
        self.refresh_status()

    def clear_art_region(self):
        self.art_region = None
        self.update_art_region()
        self.save_settings()

    # =========================== Other =========================== #
    
    def open_log_directory(self):
        log_dir = get_appdata_path("")
        os.startfile(log_dir)

    def open_about_dialog(self):
        about_path = "manual.txt"
        try:
            with open(about_path, "r", encoding="utf-8") as f:
                about_text = f.read()
        except Exception as e:
            warning(f"Failed to read {about_path}: {e}")
            about_text = f"{APP_FULLNAME}"
        msg = QMessageBox(self)
        msg.setWindowTitle("关于")
        msg.setText(about_text)
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg.exec()
    
    def open_bug_report_window(self):
        w = BugReportWindow(
            log_dir=get_appdata_path(""),
            export_dir=get_desktop_path(),
            mail_address=Config.get().bug_report_email,
            parent=self,
        )
        w.show()

    def update_debug_log(self, state):
        enabled = self.debug_log_checkbox.isChecked()
        set_log_level(INFO if not enabled else DEBUG)
        info(f"Debug log enabled: {enabled}")

    def update_advanced_param(self, key: str, value):
        if isinstance(value, float):
            value = round(value, 2)
        Config.set_override(key, value)
        config = Config.get()
        self.forward_day_label.setText(f"快进缩圈 {config.foward_day_seconds} 秒")
        self.back_day_label.setText(f"倒退缩圈 {config.back_day_seconds} 秒")
        info(f"Advanced param {key} changed to {value}")

    def reset_advanced_params(self):
        if not comfirm_box("确定要把高级参数恢复为默认值吗？", self):
            return
        Config.clear_override([p[0] for p in ADVANCED_PARAMS])
        config = Config.get()
        for key, spin in self.advanced_param_widgets.items():
            spin.setValue(getattr(config, key))
        info("Advanced params reset to default")

    def reset_all_settings(self):
        if not comfirm_box("确定要恢复全部默认设置吗？\n"
                           "快捷键、框选的区域、血条颜色等都会被清除（高级参数不受影响）。\n"
                           "当前设置会备份为 settings.yaml.bak。", self):
            return
        try:
            if os.path.exists(SETTINGS_SAVE_PATH):
                shutil.copyfile(SETTINGS_SAVE_PATH, SETTINGS_SAVE_PATH + ".bak")
                os.remove(SETTINGS_SAVE_PATH)
            self.load_settings()
            self.reset_overlay_position()
            self.save_settings()
            info("All settings reset to default")
            info_box("已恢复默认设置", self)
        except Exception as e:
            error(f"Failed to reset settings: {e}")
            error_box(f"恢复默认设置失败：{e}", self)

    def update_crystal_auto_detect(self, state):
        enabled = self.crystal_auto_detect_checkbox.isChecked()
        self.updater.crystal_auto_detect_enabled = enabled
        if not enabled:
            self.updater.reset_crystal_detection()
            # 清除之前的自动识别结果，恢复显示所有水晶点位
            if self.map_overlay.crystal_auto_candidates or self.map_overlay.crystal_auto_detected:
                self.map_overlay.crystal_auto_candidates = []
                self.map_overlay.crystal_auto_detected = set()
                if self.map_overlay.crystal_layout_idx is not None and not self.map_overlay.crystal_manual:
                    self.map_overlay.crystal_layout_idx = 0
                self.map_overlay.update_crystal_layout()
        info(f"Crystal auto detect enabled: {enabled}")

    def update_hdr_processing(self, state):
        enabled = self.hdr_processing_checkbox.isChecked()
        self.updater.hdr_processing_enabled = enabled
        info(f"HDR image processing enabled: {enabled}")
        # HDR模式切换时更新血条颜色显示
        self.update_hp_color()

