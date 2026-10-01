import time

import cv2
import numpy as np
from PIL import Image

from src.common import GAME_WINDOW_TITLE
from src.logger import info, warning, error
from src.screencap.errors import ScreencapInitError, ScreencapRuntimeError
from src.screencap.hwnd_resolver import find_game_hwnd, is_window_alive
from src.screencap.native_loader import get_native_dll_dir, get_native_dll_path
from src.screencap.types import EngineStatus, ScreencapMode


# 连续截图失败达到该次数且持续超过该时长时，认为当前连接已失效，需要重新连接
RECONNECT_FAILURE_COUNT = 10
RECONNECT_FAILURE_SECONDS = 5.0


class ScreencapEngine:
    def __init__(self):
        self._status: EngineStatus = EngineStatus.UNINITIALIZED
        self._mgr = None
        self._selected_method_name: str | None = None
        self._last_frame: Image.Image | None = None
        self._last_frame_time: float = 0.0
        self._hwnd: int | None = None
        self._consecutive_failures: int = 0
        self._first_failure_time: float = 0.0

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
        if self._status != EngineStatus.CONNECTED:
            return None
        if self._hwnd is not None and not is_window_alive(self._hwnd):
            return f"game window {self._hwnd} no longer exists"
        if self._consecutive_failures >= RECONNECT_FAILURE_COUNT and \
                time.time() - self._first_failure_time >= RECONNECT_FAILURE_SECONDS:
            return f"{self._consecutive_failures} consecutive screen capture failures"
        return None

    def _record_failure(self) -> None:
        self._last_frame = None
        if self._consecutive_failures == 0:
            self._first_failure_time = time.time()
        self._consecutive_failures += 1

    def initialize(self, mode: ScreencapMode = ScreencapMode.AUTO) -> None:
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

            hwnd = find_game_hwnd(GAME_WINDOW_TITLE)
            if hwnd is None:
                raise ScreencapInitError(
                    "connect_failed",
                    f"Game window '{GAME_WINDOW_TITLE}' not found.",
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

            self._mgr = Manager(hwnd=hwnd, methods=methods)
            self._hwnd = hwnd
            self._consecutive_failures = 0

            if not self._mgr.connect():
                raise ScreencapInitError(
                    "connect_failed",
                    "Manager.connect() returned False.",
                )

            self._selected_method_name = self._mgr.selected_unit_name()
            info(f"ScreencapEngine initialized, hwnd: {hwnd}, selected method: {self._selected_method_name}")
            self._status = EngineStatus.CONNECTED

        except ScreencapInitError:
            self._status = EngineStatus.FAILED
            raise
        except Exception as e:
            self._status = EngineStatus.FAILED
            raise ScreencapInitError("connect_failed", str(e)) from e

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
            return img

        except ScreencapRuntimeError:
            self._record_failure()
            raise
        except Exception as e:
            self._record_failure()
            raise ScreencapRuntimeError("grab_failed", str(e)) from e

    def shutdown(self) -> None:
        if self._mgr is not None:
            try:
                self._mgr.inactive()
            except Exception as e:
                warning(f"ScreencapEngine.shutdown: inactive() failed: {e}")
            try:
                del self._mgr
            except Exception:
                pass
            self._mgr = None
        self._last_frame = None
        self._hwnd = None
        self._consecutive_failures = 0
        self._status = EngineStatus.SHUTDOWN
        info("ScreencapEngine shutdown.")
