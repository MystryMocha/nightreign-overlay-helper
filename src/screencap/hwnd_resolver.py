import sys
from dataclasses import dataclass

from src.logger import warning


@dataclass(frozen=True)
class GameWindow:
    hwnd: int
    pid: int


@dataclass(frozen=True)
class _Candidate:
    hwnd: int
    pid: int
    exe_name: str | None
    visible: bool
    area: int


_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

_user32 = None
_kernel32 = None
_enum_windows_proc = None


def _win32():
    """
    使用独立的 WinDLL 实例并声明参数类型，避免64位句柄被当作int截断，也不影响其他模块对 windll.user32 的使用
    """
    global _user32, _kernel32, _enum_windows_proc
    if _user32 is None:
        import ctypes
        from ctypes import wintypes as wt

        _enum_windows_proc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.EnumWindows.argtypes = [_enum_windows_proc, wt.LPARAM]
        user32.EnumWindows.restype = wt.BOOL
        user32.GetWindowTextLengthW.argtypes = [wt.HWND]
        user32.GetWindowTextLengthW.restype = ctypes.c_int
        user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
        user32.GetWindowTextW.restype = ctypes.c_int
        user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
        user32.GetWindowThreadProcessId.restype = wt.DWORD
        user32.IsWindow.argtypes = [wt.HWND]
        user32.IsWindow.restype = wt.BOOL
        user32.IsWindowVisible.argtypes = [wt.HWND]
        user32.IsWindowVisible.restype = wt.BOOL
        user32.IsIconic.argtypes = [wt.HWND]
        user32.IsIconic.restype = wt.BOOL
        user32.GetClientRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
        user32.GetClientRect.restype = wt.BOOL

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
        kernel32.OpenProcess.restype = wt.HANDLE
        kernel32.QueryFullProcessImageNameW.argtypes = [wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)]
        kernel32.QueryFullProcessImageNameW.restype = wt.BOOL
        kernel32.CloseHandle.argtypes = [wt.HANDLE]
        kernel32.CloseHandle.restype = wt.BOOL

        _kernel32 = kernel32
        _user32 = user32
    return _user32, _kernel32


def _get_window_pid(hwnd: int) -> int:
    import ctypes
    from ctypes import wintypes as wt
    user32, _ = _win32()
    pid = wt.DWORD(0)
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def _get_process_exe_name(pid: int) -> str | None:
    """获取进程的可执行文件名（小写），无法获取时返回None"""
    import ctypes
    from ctypes import wintypes as wt
    _, kernel32 = _win32()
    handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        size = wt.DWORD(1024)
        buf = ctypes.create_unicode_buffer(size.value)
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return None
        return buf.value.replace("/", "\\").rsplit("\\", 1)[-1].lower()
    finally:
        kernel32.CloseHandle(handle)


def get_window_exe_name(hwnd: int) -> str | None:
    """窗口所属进程的可执行文件名（小写），无法获取时返回None"""
    return _get_process_exe_name(_get_window_pid(hwnd))


def _get_client_area(hwnd: int) -> int:
    import ctypes
    from ctypes import wintypes as wt
    user32, _ = _win32()
    rect = wt.RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
        return 0
    return max(0, rect.right - rect.left) * max(0, rect.bottom - rect.top)


def _enum_title_candidates(title: str) -> list[_Candidate]:
    import ctypes
    user32, _ = _win32()
    title = title.lower()
    hwnds: list[int] = []

    @_enum_windows_proc
    def enum_proc(hwnd, lparam):
        length = user32.GetWindowTextLengthW(hwnd)
        if length > 0:
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            if title in buf.value.lower():
                hwnds.append(int(hwnd))
        return True

    user32.EnumWindows(enum_proc, 0)

    candidates = []
    for hwnd in hwnds:
        pid = _get_window_pid(hwnd)
        if pid == 0:
            continue
        candidates.append(_Candidate(
            hwnd=hwnd,
            pid=pid,
            exe_name=_get_process_exe_name(pid),
            visible=bool(user32.IsWindowVisible(hwnd)),
            area=_get_client_area(hwnd),
        ))
    return candidates


def _pick_game_window(candidates: list[_Candidate], process_name: str) -> GameWindow | None:
    """
    从标题匹配的窗口中选出游戏窗口
    能确定所属进程且不是游戏进程的窗口一律排除（如游戏安装目录的资源管理器窗口、浏览器标签页），
    否则会绑定到错误的窗口上，而这类窗口截图又能成功，导致永远不会触发重连；
    优先选择确认属于游戏进程、可见、客户区最大的窗口
    """
    process_name = process_name.lower()
    valid = [c for c in candidates if c.exe_name is None or c.exe_name == process_name]
    if not valid:
        return None
    best = max(valid, key=lambda c: (c.exe_name == process_name, c.visible, c.area))
    return GameWindow(hwnd=best.hwnd, pid=best.pid)


def find_game_window(title: str, process_name: str) -> GameWindow | None:
    if sys.platform != "win32":
        warning(f"find_game_window: non-Windows platform ({sys.platform}), returning None.")
        return None
    try:
        return _pick_game_window(_enum_title_candidates(title), process_name)
    except Exception as e:
        warning(f"find_game_window: failed to find window by title '{title}': {e}")
        return None


def is_game_window_alive(window: GameWindow) -> bool:
    """
    窗口是否仍然存在且仍属于原来的进程
    游戏退出后其窗口句柄会失效，且句柄值可能被其他窗口复用，因此同时核对进程ID
    """
    if sys.platform != "win32":
        return True
    try:
        user32, _ = _win32()
        if not user32.IsWindow(window.hwnd):
            return False
        return _get_window_pid(window.hwnd) == window.pid
    except Exception as e:
        warning(f"is_game_window_alive: check failed: {e}")
        return True


def is_window_minimized(hwnd: int) -> bool:
    if sys.platform != "win32":
        return False
    try:
        user32, _ = _win32()
        return bool(user32.IsIconic(hwnd))
    except Exception:
        return False


def is_window_ready_for_capture(hwnd: int) -> bool:
    """窗口是否已显示、未最小化且有有效尺寸；游戏刚创建窗口或最小化时连接，测速可能选出错误的截图方式"""
    if sys.platform != "win32":
        return True
    try:
        user32, _ = _win32()
        return bool(user32.IsWindowVisible(hwnd)) and not user32.IsIconic(hwnd) and _get_client_area(hwnd) > 0
    except Exception:
        return True
