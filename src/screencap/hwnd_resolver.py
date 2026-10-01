import sys

from src.logger import warning


def find_game_hwnd(title: str) -> int | None:
    if sys.platform != "win32":
        warning(f"find_game_hwnd: non-Windows platform ({sys.platform}), returning None.")
        return None
    try:
        from src.screencap.maa_win32_screencap import find_window_by_title
        return find_window_by_title(title)
    except Exception as e:
        warning(f"find_game_hwnd: failed to find window by title '{title}': {e}")
        return None


def is_window_alive(hwnd: int | None) -> bool:
    """窗口句柄是否仍然有效（游戏退出后其窗口句柄会失效）"""
    if hwnd is None:
        return False
    if sys.platform != "win32":
        return True
    try:
        import ctypes
        return bool(ctypes.windll.user32.IsWindow(hwnd))
    except Exception as e:
        warning(f"is_window_alive: IsWindow failed: {e}")
        return True
