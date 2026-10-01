import os
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 必须在导入 src.* 之前设置：日志目录、设置文件路径等都是在导入时根据 APPDATA 计算的
_APPDATA = tempfile.mkdtemp(prefix="nroh-test-")
os.environ["APPDATA"] = _APPDATA
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# 程序使用相对路径（config.yaml、data/、assets/）访问资源，和 app.py 一样先切到仓库根目录
os.chdir(ROOT)


def _stub_input_libs():
    """pygame / pynput 在无头环境（如 Linux CI）无法导入或不可用，测试用不到真实的输入设备，用桩模块代替"""
    try:
        import pygame  # noqa: F401
        from pynput import keyboard, mouse  # noqa: F401
        return
    except Exception:
        pass

    pygame = types.ModuleType("pygame")
    pygame.QUIT = 256
    pygame.JOYAXISMOTION, pygame.JOYBUTTONDOWN, pygame.JOYBUTTONUP, pygame.JOYHATMOTION = 1536, 1539, 1540, 1538
    pygame.error = type("error", (Exception,), {})
    pygame.joystick = types.SimpleNamespace(JoystickType=object, get_count=lambda: 0, init=lambda: None)
    sys.modules["pygame"] = pygame

    pynput = types.ModuleType("pynput")
    keyboard = types.ModuleType("pynput.keyboard")
    mouse = types.ModuleType("pynput.mouse")

    class Key:
        pass

    class KeyCode:
        def __init__(self, char=None):
            self.char = char

    class Listener:
        def __init__(self, *args, **kwargs):
            pass

    keyboard.Key, keyboard.KeyCode, keyboard.Listener = Key, KeyCode, Listener
    mouse.Listener = Listener
    pynput.keyboard, pynput.mouse = keyboard, mouse
    sys.modules.update({"pynput": pynput, "pynput.keyboard": keyboard, "pynput.mouse": mouse})


_stub_input_libs()


import pytest  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def appdata():
    return Path(_APPDATA)
