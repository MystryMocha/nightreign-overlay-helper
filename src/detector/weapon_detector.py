import threading
import time
from dataclasses import dataclass, field

import cv2
import numpy as np

from src.config import Config
from src.detector.utils import grab_region
from src.logger import info, error, debug
from src.screencap import ScreencapEngine
from src.weapon.annotate import WeaponAnnotation, build_annotations
from src.weapon.info import get_weapon_info
from src.weapon.layout import Rect
from src.weapon.ocr import OcrEngine, OcrLine, get_shared_ocr

THUMB_SIZE = (160, 96)
CHANGED_PIXEL_DELTA = 38    # 灰度差超过 38/255（约 0.15）的像素算“明显变化”


def _changed_ratio(a: np.ndarray, b: np.ndarray | None) -> float:
    """两张灰度缩略图中明显变化的像素占比（0~1）；没有可比较的画面时视为完全不同"""
    if b is None:
        return 1.0
    return float((np.abs(a.astype(np.int16) - b.astype(np.int16)) > CHANGED_PIXEL_DELTA).mean())


def _anchors_diff(gray: np.ndarray, ref: np.ndarray, anchors: list[Rect]) -> float:
    """当前画面与被识别画面在各标注锚点（被识别的文字行）处的最大平均灰度差（0~1）"""
    worst = 0.0
    h, w = gray.shape[:2]
    for x, y, bw, bh in anchors:
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(w, x + bw), min(h, y + bh)
        if x1 <= x0 or y1 <= y0:
            continue
        cur = gray[y0:y1, x0:x1].astype(np.int16)
        old = ref[y0:y1, x0:x1].astype(np.int16)
        worst = max(worst, float(np.abs(cur - old).mean()) / 255.0)
    return worst


@dataclass
class WeaponDetectParam:
    region: tuple[int, int, int, int] | None = None     # 武器信息面板所在的屏幕区域
    hdr_processing_enabled: bool = False
    ignore_texts: set[str] = field(default_factory=set)  # 本程序自己画上去的文字，截到后不当作游戏文字


@dataclass
class WeaponDetectResult:
    updated: bool = False       # 本次是否带来新的识别结果（False 表示保持当前显示）
    annotations: list[WeaponAnnotation] = field(default_factory=list)
    line_boxes: list[Rect] = field(default_factory=list)    # 识别到的所有文字行位置，用于标注避让
    stale: bool = False         # 画面已大幅变化，当前显示的结果不再可信
    ocr_error: str | None = None


@dataclass
class OcrJob:
    generation: int
    image: np.ndarray
    scale: float
    origin: tuple[int, int]
    ignore_texts: set[str]
    gray: np.ndarray        # 被识别画面的灰度图（区域原始分辨率），用于之后判断标注是否过期


class WeaponDetector:
    """
    截取武器信息面板区域，OCR 识别其中的武器名和词条名，并匹配出属性补正/词条数值

    OCR 一次要几百毫秒到一秒多，所以放在后台线程里跑，detect() 本身只截图、判断画面是否变化并取回最新结果，
    不会阻塞其他检测。画面没有变化时不重复识别。

    “识别出的文字行 -> 标注”这一步由 _annotate 决定，子类（遗物词条识别）只需要换掉这一步。
    """
    name = "Weapon"     # 用于日志和线程名

    def __init__(self):
        self.ocr: OcrEngine | None = None
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = False
        self._thread: threading.Thread | None = None

        self._job: OcrJob | None = None
        self._busy = False
        self._generation = 0
        # (generation, 标注, 文字行位置, OCR 错误, 被识别画面的灰度图)
        self._result: tuple[int, list[WeaponAnnotation], list[Rect], str | None, np.ndarray] | None = None
        self._result_version = 0
        self._returned_version = 0

        self._region: tuple[int, int, int, int] | None = None
        self._last_thumb: np.ndarray | None = None       # 最近一次提交识别的画面缩略图，用于判断是否需要重新识别
        # 当前显示的结果所对应的画面和各标注锚点（区域内坐标），用于判断标注是否过期
        self._displayed: tuple[np.ndarray, list[Rect]] | None = None
        self._last_submit_time = 0.0
        self._active = False

    # ---------------------------------------------------------------- 主线程

    def detect(self, engine: ScreencapEngine, params: WeaponDetectParam | None) -> WeaponDetectResult:
        if params is None:      # 其他功能的检测调用，与本功能无关
            return WeaponDetectResult()
        if params.region is None:
            return self._deactivate()

        config = Config.get()
        region = tuple(params.region)
        if region != self._region:
            self._reset(region)

        processing = 'hdr_to_sdr' if params.hdr_processing_enabled else 'none'
        img = np.array(grab_region(engine, region, processing=processing).convert("RGB"))

        gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
        thumb = cv2.resize(gray, THUMB_SIZE, interpolation=cv2.INTER_AREA)

        # 画面相对上次提交识别的画面有明显变化才重新识别
        with self._lock:
            busy = self._busy
        if _changed_ratio(thumb, self._last_thumb) > config.weapon_change_threshold and not busy \
                and time.time() - self._last_submit_time >= config.weapon_ocr_min_interval:
            self._submit(img, gray, region, thumb, params.ignore_texts, config)

        result = WeaponDetectResult()
        with self._lock:
            if self._result is not None and self._result_version != self._returned_version:
                generation, annotations, line_boxes, ocr_error, result_gray = self._result
                self._returned_version = self._result_version
                if generation == self._generation:
                    result.updated = True
                    result.annotations = annotations
                    result.line_boxes = line_boxes
                    result.ocr_error = ocr_error
                    self._displayed = (result_gray, [(a.box[0] - region[0], a.box[1] - region[1], a.box[2], a.box[3])
                                                     for a in annotations])
        if result.updated:
            self._active = True

        # 标注所在的文字行画面变了（切换武器、关闭面板等），旧标注已经对不上，先隐藏等新结果；
        # 只看被标注的文字行，不受面板其他区域（如背后移动的游戏画面）影响
        if self._displayed is not None:
            ref, anchors = self._displayed
            result.stale = _anchors_diff(gray, ref, anchors) > config.weapon_hide_threshold
        return result

    def stop(self):
        self._stop = True
        self._wake.set()

    # ---------------------------------------------------------------- 内部

    def _reset(self, region):
        with self._lock:
            self._generation += 1       # 丢弃正在识别的旧区域的结果
            self._result = None
            self._job = None
        self._region = region
        self._last_thumb = None
        self._displayed = None
        self._last_submit_time = 0.0

    def _deactivate(self) -> WeaponDetectResult:
        """功能关闭或没有设置区域：清掉已显示的标注（只通知一次）"""
        was_active = self._active or self._region is not None
        if was_active:
            self._reset(None)
            self._active = False
            return WeaponDetectResult(updated=True)
        return WeaponDetectResult()

    def _submit(self, img: np.ndarray, gray: np.ndarray, region, thumb: np.ndarray,
                ignore_texts: set[str], config: Config):
        h, w = img.shape[:2]
        scale = min(1.0, config.weapon_ocr_max_side / max(w, h))
        if scale < 1.0:
            img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
        with self._lock:
            self._job = OcrJob(self._generation, img, scale, (region[0], region[1]), set(ignore_texts), gray)
            self._busy = True
        self._last_thumb = thumb
        self._last_submit_time = time.time()
        if self.ocr is None:
            self.ocr = get_shared_ocr(threads=config.weapon_ocr_threads)
        if self._thread is None or not self._thread.is_alive():
            self._stop = False
            self._thread = threading.Thread(target=self._worker, name=f"{self.name}Ocr", daemon=True)
            self._thread.start()
        self._wake.set()

    def _annotate(self, lines: list[OcrLine], job: OcrJob, config: Config) -> tuple[list[WeaponAnnotation], list[Rect]]:
        return build_annotations(
            lines, get_weapon_info(), job.origin, job.scale,
            min_score=config.weapon_ocr_min_score, ignore_texts=job.ignore_texts,
        )

    def _worker(self):
        info(f"{self.name} OCR worker started.")
        while not self._stop:
            self._wake.wait()
            self._wake.clear()
            if self._stop:
                break
            with self._lock:
                job, self._job = self._job, None
            if job is None:
                continue
            annotations: list[WeaponAnnotation] = []
            line_boxes: list[Rect] = []
            try:
                t = time.time()
                config = Config.get()
                lines = self.ocr.recognize(job.image)
                annotations, line_boxes = self._annotate(lines, job, config)
                debug(f"{self.name}Detector: {len(lines)} lines, {len(annotations)} annotations, "
                      f"time={time.time() - t:.3f}s")
            except Exception as e:
                error(f"{self.name} OCR failed: {type(e).__name__}: {e}")
            with self._lock:
                self._result = (job.generation, annotations, line_boxes, self.ocr.error, job.gray)
                self._result_version += 1
                self._busy = False
        info(f"{self.name} OCR worker stopped.")
