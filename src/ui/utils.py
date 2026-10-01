from PyQt6.QtWidgets import QWidget, QApplication
from src.logger import info, warning


def set_widget_always_on_top(widget: QWidget):
    try:
        import win32gui
        import win32con
        hwnd = widget.winId().__int__()
        win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, 
                                0, 0, 0, 0, 
                                win32con.SWP_NOSIZE | win32con.SWP_NOMOVE)
        info(f"Window HWND: {hwnd} set to TOPMOST.")
    except Exception as e:
        warning(f"Error setting system always on top: {e}")


def is_window_in_foreground(window_title: str, process_name: str | None = None) -> bool:
    """
    检查包含特定标题的窗口是否在 Windows 的最前面。
    指定 process_name 时还会核对窗口所属进程，避免把标题里恰好包含游戏名的浏览器标签页、资源管理器窗口当成游戏
    （无法获取进程名时只按标题判断）
    """
    try:
        import win32gui
        active_window_handle = win32gui.GetForegroundWindow()
        active_window_title = win32gui.GetWindowText(active_window_handle)
        if window_title.lower() not in active_window_title.lower():
            return False
        if process_name:
            from src.screencap.hwnd_resolver import get_window_exe_name
            exe_name = get_window_exe_name(active_window_handle)
            if exe_name is not None and exe_name != process_name.lower():
                return False
        return True
    except Exception:
        return False


def get_qt_screen_by_region(region: tuple[int]) -> QWidget:
    """
    根据物理像素 region 获取对应的 QScreen 对象。
    """
    x, y, w, h = region
    app: QApplication = QApplication.instance()
    screens = app.screens()
    for screen in screens:
        sx = screen.geometry().x()
        sy = screen.geometry().y()
        sw = screen.geometry().width()
        sh = screen.geometry().height()
        ratio = screen.devicePixelRatio()
        phys_sw = int(sw * ratio)
        phys_sh = int(sh * ratio)
        if sx <= x <= sx + phys_sw and sy <= y <= sy + phys_sh:
            return screen
    raise ValueError(f"Region {region} is out of all screen bounds")


_warned_out_of_screen_regions: set[tuple] = set()

def region_to_qt_region(region: tuple[int]):
    try:
        screen = get_qt_screen_by_region(region)
    except ValueError:
        # 区域不在任何屏幕内（例如截图坐标与屏幕坐标不一致），按主屏幕换算，避免整个界面更新中断
        if tuple(region) not in _warned_out_of_screen_regions:
            _warned_out_of_screen_regions.add(tuple(region))
            warning(f"Region {region} is out of all screen bounds, fallback to primary screen.")
        screen = QApplication.instance().primaryScreen()
    x, y, w, h = region
    sx = screen.geometry().x()
    sy = screen.geometry().y()
    ratio = screen.devicePixelRatio()
    qx = sx + int((x - sx) / ratio)
    qy = sy + int((y - sy) / ratio)
    qw = int(w / ratio)
    qh = int(h / ratio)
    return (qx, qy, qw, qh)

    

def process_region_to_adapt_scale(region: tuple[int], scale: float) -> tuple[int]:
    """
    处理一个region的大小，使其能够适配指定的缩放比例。
    即 w/scale, h/scale为整数。
    """
    x, y, w, h = region
    new_w = int(int(w / scale) * scale)
    new_h = int(int(h / scale) * scale)
    return [x, y, new_w, new_h]