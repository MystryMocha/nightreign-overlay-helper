import sys
import time
import os

# assets、config.yaml 等都用相对路径，启动时先切到程序根目录
# （管理员提权、快捷方式启动时工作目录可能是 System32，会导致图标等资源加载失败）
if getattr(sys, "frozen", False):
    os.chdir(os.path.dirname(sys.executable))
else:
    # 兼容直接运行 python src\app.py：把仓库根目录加入模块搜索路径
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _root not in sys.path:
        sys.path.insert(0, _root)
    os.chdir(_root)
from PyQt6.QtCore import QThread, Qt, pyqtSignal
from PyQt6.QtGui import QIcon, QAction, QCursor
from PyQt6.QtWidgets import (
    QApplication, QSystemTrayIcon, QMenu
)

from src.ui.input import InputWorker
from src.ui.overlay import OverlayWidget
from src.ui.map_overlay import MapOverlayWidget
from src.ui.hp_overlay import HpOverlayWidget
from src.ui.settings import SettingsWindow
from src.ui.admin_prompt import show_admin_prompt
from src.updater import Updater
from src.common import APP_FULLNAME, APP_VERSION, ICON_PATH
from src.logger import info, warning, error
from src.screencap import get_engine


def log_system_and_screen_info(app: QApplication):
    try:
        import platform
        system = platform.system()
        release = platform.release()
        version = platform.version()
        info(f"Operating System: {system} {release} ({version})")
    except Exception as e:
        warning(f"Error getting OS info: {e}")

    try:
        screens = app.screens()
        info(f"QApplication detected {len(screens)} screen(s):")
        for i, screen in enumerate(screens, start=1):
            size = screen.size()
            pos = screen.geometry().topLeft()
            dpi = screen.logicalDotsPerInch()
            device_pixel_ratio = screen.devicePixelRatio()
            phys_w = int(size.width() * device_pixel_ratio)
            phys_h = int(size.height() * device_pixel_ratio)
            info(f"    Screen {i}: {size.width()}x{size.height()} (logical) / {phys_w}x{phys_h} (physical) at ({pos.x()},{pos.y()}), DPI: {dpi}, Device Pixel Ratio: {device_pixel_ratio}")
    except Exception as e:
        warning(f"Error getting screens from QApplication: {e}")


def log_uncaught_exception(exc_type, exc_value, exc_tb):
    # 用 pythonw 启动时没有控制台，未捕获的异常只能写进日志
    import traceback
    error("Uncaught exception:\n" + "".join(traceback.format_exception(exc_type, exc_value, exc_tb)), print_trace=False)


if __name__ == "__main__":
    sys.excepthook = log_uncaught_exception
    info("=" * 40)
    info(f"Starting app v{APP_VERSION}...")

    QApplication.setAttribute(Qt.ApplicationAttribute.AA_Use96Dpi)
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

    app = QApplication(sys.argv)

    log_system_and_screen_info(app)

    # 防止因没有窗口而导致程序退出
    # （需在启动弹窗前设置，避免弹窗关闭时被判定为“最后一个窗口关闭”而退出程序）
    app.setQuitOnLastWindowClosed(False)

    # 启动时检测管理员权限并弹窗提示（未提权时游戏内将无法正常监听按键）
    if not show_admin_prompt():
        time.sleep(0.5)  # 等待以管理员身份启动的新实例拉起
        os._exit(0)

    # 创建对象
    input = InputWorker()
    overlay = OverlayWidget()
    map_overlay = MapOverlayWidget()
    hp_overlay = HpOverlayWidget()

    updater = Updater(input, overlay, map_overlay, hp_overlay)
    settings_window = SettingsWindow(overlay, map_overlay, updater, input)
    
    # 创建系统托盘图标和菜单
    tray_icon = QSystemTrayIcon()
    icon = QIcon(ICON_PATH)
    if icon.isNull():
        # 图标为空时 Windows 不会显示托盘图标，退回系统默认图标
        warning(f"Failed to load tray icon: {os.path.abspath(ICON_PATH)}")
        icon = app.style().standardIcon(app.style().StandardPixmap.SP_ComputerIcon)
    tray_icon.setIcon(icon)
    app.setWindowIcon(icon)
    tray_icon.setToolTip(APP_FULLNAME)

    menu = QMenu()
    settings_action = QAction("设置")
    def show_settings():
        settings_window.show()
        settings_window.activateWindow()
        settings_window.raise_()
    settings_action.triggered.connect(show_settings)
    menu.addAction(settings_action)
    timer_visible_action = QAction("显示计时器")
    timer_visible_action.setCheckable(True)
    timer_visible_action.setChecked(settings_window.timer_visible_checkbox.isChecked())
    timer_visible_action.toggled.connect(settings_window.timer_visible_checkbox.setChecked)
    settings_window.timer_visible_checkbox.toggled.connect(timer_visible_action.setChecked)
    menu.addAction(timer_visible_action)
    recover_timer_action = QAction("找回计时器（重置位置/大小/透明度）")
    recover_timer_action.triggered.connect(settings_window.recover_timer)
    menu.addAction(recover_timer_action)
    map_detect_action = QAction("启用地图识别")
    map_detect_action.setCheckable(True)
    map_detect_action.setChecked(settings_window.map_detect_enable_checkbox.isChecked())
    map_detect_action.toggled.connect(settings_window.map_detect_enable_checkbox.setChecked)
    settings_window.map_detect_enable_checkbox.toggled.connect(map_detect_action.setChecked)
    menu.addAction(map_detect_action)
    menu.addSeparator()
    quit_action = QAction("退出")
    quit_action.triggered.connect(app.quit)
    menu.addAction(quit_action)
    tray_icon.setContextMenu(menu)
    # 左键单击托盘图标直接打开设置
    def on_tray_activated(reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            show_settings()
    tray_icon.activated.connect(on_tray_activated)
    tray_icon.show()
    info(f"Tray icon shown: available={QSystemTrayIcon.isSystemTrayAvailable()}, visible={tray_icon.isVisible()}, cwd={os.getcwd()}")
    
    def show_menu_at_cursor_pos():
        cursor_pos = QCursor.pos()
        menu.move(cursor_pos)
        menu.show()
    def on_menu_show():
        overlay.is_menu_opened = True
        map_overlay.is_menu_opened = True
        updater.is_menu_opened = True
        # info("Menu opened")
    def on_menu_hide():
        overlay.is_menu_opened = False
        map_overlay.is_menu_opened = False
        updater.is_menu_opened = False
        # info("Menu closed")

    overlay.right_click_signal.connect(show_menu_at_cursor_pos)
    overlay.right_click_signal.connect(on_menu_show)
    menu.aboutToShow.connect(on_menu_show)
    menu.aboutToHide.connect(on_menu_hide)

    # 启动输入监听
    input_thread = QThread()
    input.moveToThread(input_thread)
    input_thread.started.connect(input.run)
    input_thread.start()
    
    # 设置并启动后台检测器
    updater_thread = QThread()
    updater.moveToThread(updater_thread)
    updater_thread.started.connect(updater.run)
    updater_thread.start()

    # 清理：程序退出时，停止worker并等待线程结束
    def on_quit():
        info("Stopping worker thread...")
        updater.stop()
        updater_thread.quit()
        if not updater_thread.wait(1000):
            print("Updater thread did not exit in time. Forcing termination.")
            updater_thread.terminate()
        else:
            info("Updater thread stopped.")
        input.stop()
        input_thread.quit()
        if not input_thread.wait(1000):
            print("Input thread did not exit in time. Forcing termination.")
            input_thread.terminate()
        else:
            info("Input thread stopped.")
        info("All Thread stopped.")

        try:
            get_engine().shutdown()
        except Exception as e:
            warning(f"Error shutting down screencap engine: {e}")

        tray_icon.deleteLater()

    app.aboutToQuit.connect(on_quit)
    
    overlay.show()

    try:
        exit_code = app.exec() 
        info(f"QApp event loop finished with exit code {exit_code}.")
    except Exception as e:
        exit_code = 1
        error(f"Exception in app exec: {e}")

    settings_window.save_settings()

    time.sleep(1)
    os._exit(exit_code)
