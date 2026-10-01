import os
import threading
import time
from dataclasses import dataclass, fields

from .common import load_yaml, save_yaml, get_appdata_path

CONFIG_PATH = "config.yaml"
# 用户在设置界面修改的参数保存在这里，覆盖 config.yaml 中的同名项（程序更新时不会被覆盖）
CONFIG_OVERRIDE_FILENAME = "config_override.yaml"
# 检查配置文件是否被修改的最小间隔(秒)，Config.get() 在各处被高频调用，不必每次都 stat
CONFIG_CHECK_INTERVAL = 0.5

_lock = threading.RLock()
_config_obj: "Config | None" = None     # 最近一次成功加载的配置，配置文件损坏时继续使用
_config_mtime = None
_last_check_time: float = 0.0
_override_path: str | None = None


def get_config_override_path() -> str:
    global _override_path
    if _override_path is None:
        _override_path = get_appdata_path(CONFIG_OVERRIDE_FILENAME)
    return _override_path

def _get_mtime(path: str) -> float | None:
    try:
        return os.path.getmtime(path)
    except OSError:
        return None

def _warn(msg: str):
    from src.logger import warning
    warning(msg)

@dataclass
class Config:
    day_period_seconds: list[int]
    deadly_nightrain_seconds: int

    update_interval: float
    detect_intervals: dict[str, float]

    foward_day_seconds: int
    back_day_seconds: int

    day_progress_css: str
    day_text_css: str
    in_rain_progress_css: str
    in_rain_text_css: str
    art_progress_css: str
    art_text_css: str

    time_scale: float

    template_standard_height: int
    mask_lower_white: list[int]
    mask_upper_white: list[int]
    scale_range: list[float]
    dayx_score_threshold: float
    dayx_detect_langs: dict[str, str]

    lower_hls_not_in_rain: list[int]
    upper_hls_not_in_rain: list[int]
    lower_hls_in_rain: list[int]
    upper_hls_in_rain: list[int]
    lower_hls_not_in_rain_hdr: list[int]
    upper_hls_not_in_rain_hdr: list[int]
    lower_hls_in_rain_hdr: list[int]
    upper_hls_in_rain_hdr: list[int]
    h_tolerance: int
    l_tolerance: int
    s_tolerance: int
    hp_color_min_area_ratio: float
    hp_color_max_area_ratio: float

    fixed_map_overlay_draw_size: list[int] | None
    map_overlay_draw_size_ratio: float | None
    full_map_hough_circle_thres: list[int]
    full_map_error_threshold: float
    default_map_region_ratio: list[float]
    earth_shifting_min_matches: int
    map_pattern_match_interval: float
    subicon_template_match_threshold: float
    poi_match_sample_ratio_w_nightlord: float
    poi_match_sample_ratio_wo_nightlord: float
    default_map_pattern_match_topk: int
    max_map_pattern_match_topk: int
    min_map_pattern_match_topk: int
    map_pattern_retry_error_threshold: float
    map_pattern_max_retry: int

    crystal_detect_max_offset: int
    crystal_detect_threshold: float
    crystal_detect_delay: float

    hpbar_region_aspect_ratio: float
    hpbar_detect_std_height: int
    hpbar_border_v_peak_start: int
    hpbar_border_v_peak_lower: int
    hpbar_border_v_peak_threshold: int
    hpbar_border_v_peak_interval: int
    hpbar_recent_length_count: int
    hpbar_low_hp_marker: float
    hpbar_high_hp_marker: float

    weapon_ocr_min_interval: float
    weapon_change_threshold: float
    weapon_hide_threshold: float
    weapon_ocr_min_score: float
    weapon_ocr_max_side: int
    weapon_ocr_threads: int

    art_detect_standard_size: int
    art_detect_match_scales: tuple[float, float, int]
    art_detect_threshold: float
    art_detect_delay_seconds: float
    art_info: dict[str, dict[str, float]]

    bug_report_email: str

    @staticmethod
    def get() -> 'Config':
        """
        获取当前配置。配置文件被修改后会自动重新加载；
        重新加载失败（如用户编辑到一半保存了损坏的 YAML、缺少必填项）时保留上一次成功加载的配置，
        避免高频调用方（检测线程、定时器）因此崩溃
        """
        global _config_obj, _config_mtime, _last_check_time
        with _lock:
            now = time.monotonic()
            if _config_obj is not None and now - _last_check_time < CONFIG_CHECK_INTERVAL:
                return _config_obj
            _last_check_time = now

            override_path = get_config_override_path()
            mtime = (_get_mtime(CONFIG_PATH), _get_mtime(override_path))
            if _config_obj is None or mtime != _config_mtime:
                _config_mtime = mtime     # 失败时也记录，避免对同一份损坏文件反复解析和刷日志
                try:
                    _config_obj = Config._load()
                except Exception as e:
                    if _config_obj is None:
                        raise
                    _warn(f"Failed to reload {CONFIG_PATH}, keep using previous config: {e}")
            return _config_obj

    @staticmethod
    def _load() -> 'Config':
        base = load_yaml(CONFIG_PATH, raise_on_error=True)
        if not isinstance(base, dict):
            raise ValueError(f"{CONFIG_PATH} is not a mapping")
        override = Config.load_override()
        base.update({k: v for k, v in override.items() if k in base})
        missing = sorted(_CONFIG_FIELDS - set(base))
        if missing:
            raise ValueError(f"{CONFIG_PATH} is missing required keys: {', '.join(missing)}")
        # 忽略当前版本不认识的字段，避免 config.yaml 比程序新时整个检测线程崩溃
        return Config(**{k: v for k, v in base.items() if k in _CONFIG_FIELDS})

    @staticmethod
    def invalidate():
        """下次 Config.get() 时立即检查配置文件是否变化"""
        global _last_check_time
        with _lock:
            _last_check_time = 0.0

    @staticmethod
    def get_default(key: str):
        """config.yaml 中的原始值（不含用户覆盖）"""
        return load_yaml(CONFIG_PATH).get(key)

    @staticmethod
    def load_override() -> dict:
        path = get_config_override_path()
        if not os.path.exists(path):
            return {}
        data = load_yaml(path)
        return data if isinstance(data, dict) else {}

    @staticmethod
    def set_override(key: str, value):
        """设置一个覆盖值，与 config.yaml 相同时移除覆盖"""
        override = Config.load_override()
        if value == Config.get_default(key):
            override.pop(key, None)
        else:
            override[key] = value
        save_yaml(get_config_override_path(), override)
        Config.invalidate()

    @staticmethod
    def clear_override(keys: list[str] | None = None):
        override = Config.load_override()
        for k in (keys if keys is not None else list(override.keys())):
            override.pop(k, None)
        save_yaml(get_config_override_path(), override)
        Config.invalidate()

_CONFIG_FIELDS = {f.name for f in fields(Config)}
