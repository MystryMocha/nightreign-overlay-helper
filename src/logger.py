from logging import getLogger, StreamHandler, Formatter, DEBUG, INFO
import os
import sys
import threading
import time
from datetime import datetime
import traceback

from src.common import get_appdata_path

LOG_DIR = get_appdata_path("logs")
# 按日期命名的日志保留天数，更早的在启动时清理
LOG_KEEP_DAYS = 14
# crash.log 超过该大小时在启动时清空，避免无限增长
CRASH_LOG_MAX_BYTES = 5 * 1024 * 1024

LOGGER_NAME = "nroh"

_logger = None
_logger_lock = threading.Lock()


def _cleanup_old_logs():
    try:
        now = time.time()
        for name in os.listdir(LOG_DIR):
            path = os.path.join(LOG_DIR, name)
            if not os.path.isfile(path):
                continue
            if name.endswith(".log") and name != "crash.log":
                if now - os.path.getmtime(path) > LOG_KEEP_DAYS * 86400:
                    os.remove(path)
    except OSError:
        pass


def setup_logger(level: int = INFO):
    # 使用独立的命名 logger，避免 DEBUG 级别把 PIL 等第三方库的调试输出也打开
    logger = getLogger(LOGGER_NAME)
    logger.setLevel(level)
    logger.propagate = False
    formatter = Formatter('%(asctime)s [%(levelname)s] %(message)s')

    # 以 pythonw / --windowed 启动时 sys.stderr 为 None，此时不添加控制台输出
    if sys.stderr is not None:
        handler = StreamHandler()
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    os.makedirs(LOG_DIR, exist_ok=True)
    _cleanup_old_logs()
    date = datetime.now().strftime("%Y-%m-%d")
    file_handler = StreamHandler(open(os.path.join(LOG_DIR, f"{date}.log"), "a", encoding="utf-8"))
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    return logger


def _get_logger():
    global _logger
    if _logger is None:
        with _logger_lock:
            if _logger is None:
                _logger = setup_logger()
    return _logger


def set_log_level(level: int):
    _get_logger().setLevel(level)


def is_debug_enabled() -> bool:
    return _logger is not None and _logger.isEnabledFor(DEBUG)


def get_debug_file_path(filename: str) -> str:
    """调试图片等文件的保存路径（位于日志目录下，随 BUG 反馈一起打包；仅应在开启调试日志时写入）"""
    debug_dir = os.path.join(LOG_DIR, "debug")
    os.makedirs(debug_dir, exist_ok=True)
    return os.path.join(debug_dir, filename)


def debug(msg: str):
    _get_logger().debug(msg)


def info(msg: str):
    _get_logger().info(msg)


def warning(msg: str):
    _get_logger().warning(msg)


def error(msg: str, print_trace: bool = True):
    logger = _get_logger()
    logger.error(msg)
    # 不在异常处理中调用时 format_exc() 只会得到 "NoneType: None"，没有意义
    if print_trace and sys.exc_info()[0] is not None:
        logger.error(traceback.format_exc())
