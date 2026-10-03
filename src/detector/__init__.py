from src.detector.rain_detector import RainDetector, RainDetectResult, RainDetectParam
from src.detector.day_detector import DayDetector, DayDetectResult, DayDetectParam
from src.detector.map_detector import MapDetector, MapDetectResult, MapDetectParam
from src.detector.hp_detector import HpDetector, HpDetectResult, HpDetectParam
from src.detector.art_detector import ArtDetector, ArtDetectResult, ArtDetectParam
from src.detector.weapon_detector import WeaponDetector, WeaponDetectResult, WeaponDetectParam
from src.detector.relic_detector import RelicDetector
from dataclasses import dataclass
from src.screencap import ScreencapEngine


@dataclass
class DetectParam:
    day_detect_param: DayDetectParam = None
    rain_detect_param: RainDetectParam = None
    map_detect_param: MapDetectParam = None
    hp_detect_param: HpDetectParam = None
    art_detect_param: ArtDetectParam = None
    weapon_detect_param: WeaponDetectParam = None
    relic_detect_param: WeaponDetectParam = None    # 遗物词条识别与武器信息的参数、结果类型相同

@dataclass
class DetectResult:
    day_detect_result: DayDetectResult = None
    rain_detect_result: RainDetectResult = None
    map_detect_result: MapDetectResult = None
    hp_detect_result: HpDetectResult = None
    art_detect_result: ArtDetectResult = None
    weapon_detect_result: WeaponDetectResult = None
    relic_detect_result: WeaponDetectResult = None


class DetectorManager:
    def __init__(self, engine: ScreencapEngine):
        self.engine = engine
        self.rain_detector = RainDetector()
        self.day_detector = DayDetector()
        self.map_detector = MapDetector()
        self.hp_detector = HpDetector()
        self.art_detector = ArtDetector()
        self.weapon_detector = WeaponDetector()
        self.relic_detector = RelicDetector()

    def detect(self, params: DetectParam) -> DetectResult:
        result = DetectResult()
        result.day_detect_result = self.day_detector.detect(self.engine, params.day_detect_param)
        result.rain_detect_result = self.rain_detector.detect(self.engine, params.rain_detect_param)
        result.map_detect_result = self.map_detector.detect(self.engine, params.map_detect_param)
        result.hp_detect_result = self.hp_detector.detect(self.engine, params.hp_detect_param)
        result.art_detect_result = self.art_detector.detect(self.engine, params.art_detect_param)
        result.weapon_detect_result = self.weapon_detector.detect(self.engine, params.weapon_detect_param)
        result.relic_detect_result = self.relic_detector.detect(self.engine, params.relic_detect_param)
        return result
        
        