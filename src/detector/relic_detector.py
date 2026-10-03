from src.config import Config
from src.detector.weapon_detector import WeaponDetector, OcrJob
from src.relic.annotate import build_relic_annotations
from src.relic.info import get_relic_info
from src.weapon.annotate import WeaponAnnotation
from src.weapon.layout import Rect
from src.weapon.ocr import OcrLine


class RelicDetector(WeaponDetector):
    """
    遗物仪式界面的词条数值识别：截图、判断画面变化、后台 OCR、取回结果的流程与武器信息完全相同，
    参数和结果也沿用 WeaponDetectParam / WeaponDetectResult，只是识别出的文字改按遗物词条库匹配
    （遗物和武器上同名词条的数值不同，两边不能共用一张表）
    """
    name = "Relic"

    def _annotate(self, lines: list[OcrLine], job: OcrJob, config: Config) -> tuple[list[WeaponAnnotation], list[Rect]]:
        return build_relic_annotations(
            lines, get_relic_info(), job.origin, job.scale,
            min_score=config.weapon_ocr_min_score, ignore_texts=job.ignore_texts,
        )
