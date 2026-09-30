import yaml
import os
from dataclasses import dataclass, fields

from .common import load_yaml, save_yaml, get_appdata_path

CONFIG_PATH = "config.yaml"
# 用户在设置界面修改的参数保存在这里，覆盖 config.yaml 中的同名项（程序更新时不会被覆盖）
CONFIG_OVERRIDE_FILENAME = "config_override.yaml"

_config: dict = {}
_config_mtime = None
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

    crystal_detect_hsv_lower: list[int]
    crystal_detect_hsv_upper: list[int]
    crystal_detect_radius: int
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

    art_detect_standard_size: int
    art_detect_match_scales: tuple[float, float, int]
    art_detect_threshold: float
    art_detect_delay_seconds: float
    art_info: dict[str, dict[str, float]]

    bug_report_email: str

    @staticmethod
    def get() -> 'Config':
        global _config, _config_mtime
        override_path = get_config_override_path()
        mtime = (os.path.getmtime(CONFIG_PATH), _get_mtime(override_path))
        if mtime != _config_mtime:
            base = load_yaml(CONFIG_PATH)
            override = Config.load_override() if mtime[1] is not None else {}
            base.update({k: v for k, v in override.items() if k in base})
            _config = base
            _config_mtime = mtime
        # 忽略当前版本不认识的字段，避免 config.yaml 比程序新时整个检测线程崩溃
        return Config(**{k: v for k, v in _config.items() if k in _CONFIG_FIELDS})

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

    @staticmethod
    def clear_override(keys: list[str] | None = None):
        override = Config.load_override()
        for k in (keys if keys is not None else list(override.keys())):
            override.pop(k, None)
        save_yaml(get_config_override_path(), override)

_CONFIG_FIELDS = {f.name for f in fields(Config)}
