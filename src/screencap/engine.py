import time

import cv2
import numpy as np
from PIL import Image

from src.common import GAME_WINDOW_TITLE, GAME_PROCESS_NAME
from src.logger import info, warning
from src.screencap.errors import ScreencapInitError, ScreencapRuntimeError
from src.screencap.hwnd_resolver import (
    GameWindow,
    find_game_window,
    is_game_window_alive,
    is_window_minimized,
    is_window_ready_for_capture,
)
from src.screencap.native_loader import get_native_dll_dir, get_native_dll_path
from src.screencap.types import EngineStatus, ScreencapMode


# 连续截图失败达到该次数且持续超过该时长时，认为当前连接已失效，需要重新连接
RECONNECT_FAILURE_COUNT = 10
RECONNECT_FAILURE_SECONDS = 5.0
# 重连后仍持续失败时，下一次因失败触发重连所需的持续时长翻倍，直到该上限，避免反复重连刷屏
RECONNECT_FAILURE_SECONDS_MAX = 60.0
# 新出现的游戏窗口需存在该时长后才连接，避免游戏刚创建窗口时测速选出错误的截图方式
NEW_WINDOW_GRACE_SECONDS = 3.0
# 连接失败后的重试间隔，连接时会对各截图方式测速，不宜频繁重试
CONNECT_RETRY_SECONDS = 3.0


class ScreencapEngine:
    def __init__(self):
        self._status: EngineStatus = EngineStatus.UNINITIALIZED
        self._mgr = None
        self._selected_method_name: str | None = None
        self._last_frame: Image.Image | None = None
        self._last_frame_time: float = 0.0
        self._window: GameWindow | None = None
        self._consecutive_failures: int = 0
        self._first_failure_time: float = 0.0
        self._failure_reconnect_seconds: float = RECONNECT_FAILURE_SECONDS
        self._pending_window: GameWindow | None = None
        self._pending_window_since: float = 0.0
        self._last_connect_error: ScreencapInitError | None = None
        self._next_connect_time: float = 0.0

    @property
    def status(self) -> EngineStatus:
        return self._status

    @property
    def selected_method_name(self) -> str | None:
        return self._selected_method_name

    @property
    def may_capture_overlays(self) -> bool:
        """
        当前截图方式是否可能截到覆盖在游戏上方的其他窗口（如本程序的悬浮窗）
        桌面复制/屏幕DC方式截取的是屏幕内容，会包含悬浮窗；FramePool/PrintWindow等窗口截图方式不会
        """
        name = (self._selected_method_name or "").lower()
        if not name:
            return True
        return any(k in name for k in ("dxgi", "desktop", "screen"))

    def check_reconnect_reason(self) -> str | None:
        """
        检查已连接的引擎是否需要重新连接，需要时返回原因，否则返回None
        游戏重启后旧窗口句柄失效、新游戏是另一个窗口，若不重连会一直对旧句柄截图失败
        """
        if self._status != EngineStatus.CONNECTED or self._window is None:
            return None
        if not is_game_window_alive(self._window):
            return f"game window {self._window.hwnd} (pid {self._window.pid}) no longer exists"
        if is_window_minimized(self._window.hwnd):
            # 最小化时截图失败是正常的，重连也无济于事，不计入连续失败
            self._consecutive_failures = 0
            return None
        if self._consecutive_failures >= RECONNECT_FAILURE_COUNT and \
                time.time() - self._first_failure_time >= self._failure_reconnect_seconds:
            reason = f"{self._consecutive_failures} consecutive screen capture failures " \
                     f"in {self._failure_reconnect_seconds:.0f}s"
            self._failure_reconnect_seconds = min(self._failure_reconnect_seconds * 2, RECONNECT_FAILURE_SECONDS_MAX)
            return reason
        return None

    def _record_failure(self) -> None:
        self._last_frame = None
        if self._consecutive_failures == 0:
            self._first_failure_time = time.time()
        self._consecutive_failures += 1

    def _release_mgr(self) -> None:
        if self._mgr is not None:
            try:
                self._mgr.inactive()
            except Exception as e:
                warning(f"ScreencapEngine: inactive() failed: {e}")
            self._mgr = None

    def initialize(self, mode: ScreencapMode = ScreencapMode.AUTO) -> None:
        now = time.time()
        if self._last_connect_error is not None and now < self._next_connect_time:
            # 冷却期内直接抛出上次的错误，保持错误信息不变，避免调用方重复输出日志
            self._status = EngineStatus.FAILED
            raise ScreencapInitError(self._last_connect_error.code, self._last_connect_error.message)
        try:
            self._status = EngineStatus.INITIALIZING

            dll_path = get_native_dll_path()
            if not dll_path.exists():
                raise ScreencapInitError(
                    "dll_not_found",
                    f"MaaWin32Screencap.dll not found at {dll_path}",
                )

            from src.screencap.maa_win32_screencap import Manager, set_dll_path

            set_dll_path(str(get_native_dll_dir()))

            window = find_game_window(GAME_WINDOW_TITLE, GAME_PROCESS_NAME)
            if window is None:
                self._pending_window = None
                raise ScreencapInitError(
                    "connect_failed",
                    f"Game window '{GAME_WINDOW_TITLE}' not found.",
                )
            if window != self._pending_window:
                self._pending_window = window
                self._pending_window_since = now
            if now - self._pending_window_since < NEW_WINDOW_GRACE_SECONDS \
                    or not is_window_ready_for_capture(window.hwnd):
                raise ScreencapInitError(
                    "window_not_ready",
                    f"Game window {window.hwnd} (pid {window.pid}) is not ready for capture yet.",
                )

            if mode == ScreencapMode.FOREGROUND:
                methods = Manager.METHOD_FOREGROUND
            elif mode == ScreencapMode.BACKGROUND:
                methods = Manager.METHOD_BACKGROUND
            else:
                # AUTO：排除 DXGI 桌面复制方式（全桌面 / 单窗口），
                # 这两种方式在独占全屏/HDR下抓不到游戏画面，会导致地图识别失效；
                # 也排除 GDI：测速时它最快而常被选中，但对 DirectX 游戏窗口只能截到白图或过期画面
                methods = Manager.METHOD_ALL & ~(
                    Manager.METHOD_DXGI_DESKTOP_DUP | Manager.METHOD_DXGI_DESKTOP_DUP_WINDOW
                    | Manager.METHOD_GDI
                )

            self._release_mgr()
            self._window = None
            self._consecutive_failures = 0
            self._mgr = Manager(hwnd=window.hwnd, methods=methods)

            if not self._mgr.connect():
                self._release_mgr()
                self._last_connect_error = ScreencapInitError(
                    "connect_failed",
                    f"Manager.connect() returned False for game window {window.hwnd}.",
                )
                self._next_connect_time = now + CONNECT_RETRY_SECONDS
                raise self._last_connect_error

            self._window = window
            self._last_connect_error = None

            self._selected_method_name = self._mgr.selected_unit_name()
            info(f"ScreencapEngine initialized, hwnd: {window.hwnd}, pid: {window.pid}, "
                 f"selected method: {self._selected_method_name}")
            self._status = EngineStatus.CONNECTED

        except ScreencapInitError:
            self._status = EngineStatus.FAILED
            raise
        except Exception as e:
            self._status = EngineStatus.FAILED
            self._release_mgr()
            self._window = None
            self._last_connect_error = ScreencapInitError("connect_failed", str(e))
            self._next_connect_time = now + CONNECT_RETRY_SECONDS
            raise self._last_connect_error from e

    def grab_fullscreen(self) -> Image.Image:
        if self._status != EngineStatus.CONNECTED or self._mgr is None:
            raise ScreencapRuntimeError("not_connected", "Engine is not connected.")

        try:
            from src.config import Config
            cache_interval = Config.get().update_interval
        except Exception:
            cache_interval = 0.0

        now = time.time()
        if (
            self._last_frame is not None
            and cache_interval > 0
            and (now - self._last_frame_time) < cache_interval
        ):
            return self._last_frame

        info_obj = self._mgr.screencap()
        if info_obj is None:
            self._record_failure()
            raise ScreencapRuntimeError("grab_failed", "mgr.screencap() returned None.")

        try:
            arr = np.frombuffer(info_obj.data, dtype=np.uint8)
            row_len = info_obj.step if info_obj.step > 0 else info_obj.width * info_obj.channels
            arr = arr.reshape(info_obj.height, row_len)[:, : info_obj.width * info_obj.channels]
            arr = arr.reshape(info_obj.height, info_obj.width, info_obj.channels)

            if info_obj.channels == 4:
                arr = cv2.cvtColor(arr, cv2.COLOR_BGRA2RGB)
            elif info_obj.channels == 3:
                arr = cv2.cvtColor(arr, cv2.COLOR_BGR2RGB)
            else:
                raise ScreencapRuntimeError(
                    "grab_failed",
                    f"Unsupported channel count: {info_obj.channels}",
                )

            img = Image.fromarray(arr)
            self._last_frame = img
            self._last_frame_time = now
            self._consecutive_failures = 0
            self._failure_reconnect_seconds = RECONNECT_FAILURE_SECONDS
            return img

        except ScreencapRuntimeError:
            self._record_failure()
            raise
        except Exception as e:
            self._record_failure()
            raise ScreencapRuntimeError("grab_failed", str(e)) from e

    def shutdown(self) -> None:
        self._release_mgr()
        self._last_frame = None
        self._window = None
        self._consecutive_failures = 0
        self._status = EngineStatus.SHUTDOWN
        info("ScreencapEngine shutdown.")
