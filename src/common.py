from pathlib import Path
import os
import sys
from datetime import timedelta
from platformdirs import user_data_dir, user_desktop_dir
import yaml
import tomllib


APP_NAME = "nightreign-overlay-helper"
APP_NAME_CHS = "黑夜君临悬浮助手"

def get_version() -> str:
    """从 pyproject.toml 读取版本号，自动适配源码和 PyInstaller 打包环境"""
    # 检测是否为 PyInstaller 打包后的环境
    if getattr(sys, 'frozen', False):
        # PyInstaller 打包后：pyproject.toml 在程序根目录（_MEIPASS）
        pyproject_path = Path(sys._MEIPASS) / "pyproject.toml"
    else:
        # 源码环境：pyproject.toml 在项目根目录
        pyproject_path = Path(__file__).parent.parent / "pyproject.toml"
    
    try:
        with open(pyproject_path, "rb") as f:
            data = tomllib.load(f)
        return data["project"]["version"]
    except Exception:
        return "unknown"

APP_VERSION = get_version()
APP_FULLNAME = f"{APP_NAME_CHS}v{APP_VERSION}"
APP_AUTHOR = "NeuraXmy"

GAME_WINDOW_TITLE = "ELDEN RING NIGHTREIGN"
GAME_PROCESS_NAME = "nightreign.exe"


def get_asset_path(path: str) -> str:
    return str(Path("assets") / path)

def get_data_path(path: str) -> str:
    return str(Path("data") / path)

def get_appdata_path(filename: str) -> str:
    if appdata := os.getenv("APPDATA"):
        app_data_dir = Path(appdata) / APP_NAME
    else:
        app_data_dir = Path(user_data_dir(appname=APP_NAME, appauthor=APP_AUTHOR))
    app_data_dir.mkdir(parents=True, exist_ok=True)
    return str(app_data_dir / filename)

def get_desktop_path(filename: str = "") -> str:
    desktop = Path(user_desktop_dir())
    desktop.mkdir(exist_ok=True)
    return str(desktop / filename) if filename else str(desktop)


ICON_PATH = get_asset_path("icon.ico")


def get_readable_timedelta(t: timedelta) -> str:
    seconds = int(t.total_seconds())
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours > 0:
        return f"{hours}小时{minutes}分钟{seconds}秒"
    elif minutes > 0:
        return f"{minutes}分钟{seconds}秒"
    else:
        return f"{seconds}秒"
    

def _log_warning(msg: str):
    # logger 依赖本模块，这里延迟导入避免循环依赖；打包成 --windowed 后 print 不可见，所以走日志
    try:
        from src.logger import warning
        warning(msg)
    except Exception:
        print(msg)

def load_yaml(path: str, raise_on_error: bool = False) -> dict:
    """
    读取 YAML。默认出错时记录警告并返回 {}；raise_on_error=True 时抛出异常，
    供调用方区分"文件为空"和"文件损坏"
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        if raise_on_error:
            raise
        _log_warning(f"Failed to load YAML file {path}: {e}")
        return {}

def save_yaml(path: str, data: dict):
    # 保存到临时文件然后替换，防止写入过程中程序崩溃导致文件损坏
    tmp_path = path + ".tmp"
    try:
        dir_name = os.path.dirname(path)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)
        with open(tmp_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True)
        os.replace(tmp_path, path)
    except Exception as e:
        _log_warning(f"Failed to save YAML file {path}: {e}")
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
