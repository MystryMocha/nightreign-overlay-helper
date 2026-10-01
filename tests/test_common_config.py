import os
import shutil
import time

import pytest

import src.config as config_module
from src.common import load_yaml, save_yaml
from src.config import Config


def test_save_yaml_does_not_raise_on_unwritable_target(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    # 父目录是个文件，makedirs 必然失败：不应抛出 UnboundLocalError 之类的异常
    save_yaml(str(blocker / "sub" / "a.yaml"), {"a": 1})


def test_save_yaml_bare_filename(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    save_yaml("settings.yaml", {"a": 1})
    assert load_yaml("settings.yaml") == {"a": 1}
    assert not os.path.exists("settings.yaml.tmp")


def test_load_yaml_raise_on_error(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("a: [1, 2\n")
    assert load_yaml(str(bad)) == {}
    with pytest.raises(Exception):
        load_yaml(str(bad), raise_on_error=True)


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    """使用临时目录里的 config.yaml，并重置模块级缓存"""
    cfg = tmp_path / "config.yaml"
    shutil.copyfile("config.yaml", cfg)
    monkeypatch.setattr(config_module, "CONFIG_PATH", str(cfg))
    monkeypatch.setattr(config_module, "_override_path", str(tmp_path / "override.yaml"))
    monkeypatch.setattr(config_module, "_config_obj", None)
    monkeypatch.setattr(config_module, "_config_mtime", None)
    Config.invalidate()
    return cfg


def _touch_later(path, seconds=5):
    t = time.time() + seconds
    os.utime(path, (t, t))
    Config.invalidate()


def test_config_loads(isolated_config):
    assert Config.get().update_interval == 0.1


def test_config_reloads_after_edit(isolated_config):
    text = isolated_config.read_text(encoding="utf-8").replace("update_interval: 0.1", "update_interval: 0.5")
    isolated_config.write_text(text, encoding="utf-8")
    _touch_later(isolated_config)
    assert Config.get().update_interval == 0.5


def test_config_keeps_previous_when_file_is_broken(isolated_config):
    before = Config.get()
    isolated_config.write_text("day_period_seconds: [270, 180\n", encoding="utf-8")   # 编辑到一半的损坏 YAML
    _touch_later(isolated_config)
    assert Config.get() is before


def test_config_keeps_previous_when_required_key_missing(isolated_config):
    before = Config.get()
    text = isolated_config.read_text(encoding="utf-8").replace("update_interval: 0.1", "")
    isolated_config.write_text(text, encoding="utf-8")
    _touch_later(isolated_config)
    assert Config.get() is before


def test_config_keeps_previous_when_file_deleted(isolated_config):
    before = Config.get()
    isolated_config.unlink()
    Config.invalidate()
    assert Config.get() is before


def test_config_first_load_failure_raises(isolated_config):
    isolated_config.write_text("not: [valid", encoding="utf-8")
    with pytest.raises(Exception):
        Config.get()


def test_config_ignores_unknown_keys(isolated_config):
    isolated_config.write_text(isolated_config.read_text(encoding="utf-8") + "\nfuture_option: 1\n", encoding="utf-8")
    _touch_later(isolated_config)
    assert Config.get().update_interval == 0.1


def test_config_override_roundtrip(isolated_config):
    Config.set_override("foward_day_seconds", 30)
    assert Config.get().foward_day_seconds == 30      # set_override 后立即生效，不受检查间隔限制
    Config.set_override("foward_day_seconds", 10)     # 与默认值相同时移除覆盖
    assert Config.get().foward_day_seconds == 10
    assert "foward_day_seconds" not in Config.load_override()
