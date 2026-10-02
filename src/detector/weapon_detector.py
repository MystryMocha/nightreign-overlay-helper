"""
截取武器信息面板区域，OCR 识别其中的武器名、词条、战技和法术，并匹配出要显示的数值

OCR 一次要几百毫秒到一秒多，所以放在后台线程里跑，detect() 本身只截图、判断画面是否变化并取回最新结果，
不会阻塞其他检测。画面没有变化时不重复识别。
"""
import threading
import time
from dataclasses import dataclass, field

import cv2
import numpy as np

from src.config import Config
from src.detector.utils import grab_region
from src.logger import debug, error, info
from src.screencap import ScreencapEngine
from src.weapon.annotate import WeaponAnnotation, build_annotations
from src.weapon.info import get_weapon_info
from src.weapon.layout import Rect
from src.weapon.ocr import OcrEngine

THUMB_SIZE = (160, 96)
CHANGED_PIXEL_DELTA = 38


def _changed_ratio(a: np.ndarray, b: np.ndarray | None) -> float:
    """两张灰度缩略图中明显变化的像素占比（0~1）；没有可比较的画面时视为完全不同"""
    if b is None:
        return 1.0
    delta = np.abs(a.astype(np.int16) - b.astype(np.int16))
    return float(np.mean(delta > CHANGED_PIXEL_DELTA))


def _anchors_diff(gray: np.ndarray, ref: np.ndarray, anchors: list[Rect]) -> float:
    """当前画面与被识别画面在各标注锚点（被识别的文字行）处的最大平均灰度差（0~1）"""
    worst = 0.0
    height, width = gray.shape[:2]
    for x, y, bw, bh in anchors:
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(width, x + bw), min(height, y + bh)
        if x1 <= x0 or y1 <= y0:
            continue
        current = gray[y0:y1, x0:x1].astype(np.int16)
        old = ref[y0:y1, x0:x1].astype(np.int16)
        worst = max(worst, float(np.mean(np.abs(current - old))) / 255.0)
    return worst


@dataclass
class WeaponDetectParam:
    region: tuple[int, int, int, int] | None = None
    hdr_processing_enabled: bool = False
    ignore_texts: set[str] = field(default_factory=set)


@dataclass
class WeaponDetectResult:
    updated: bool = False
    annotations: list[WeaponAnnotation] = field(default_factory=list)
    line_boxes: list[Rect] = field(default_factory=list)
    stale: bool = False
    ocr_error: str | None = None


@dataclass
class _Job:
    generation: int
    image: np.ndarray
    scale: float
    origin: tuple[int, int]
    ignore_texts: set[str]
    gray: np.ndarray


class WeaponDetector:
    """
    截取武器信息面板区域，OCR 识别其中的武器名和词条名，并匹配出属性补正/词条数值

    OCR 一次要几百毫秒到一秒多，所以放在后台线程里跑，detect() 本身只截图、判断画面是否变化并取回最新结果，
    不会阻塞其他检测。画面没有变化时不重复识别。
    """

    def __init__(self):
        self.ocr: OcrEngine | None = None
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = False
        self._thread: threading.Thread | None = None
        self._generation = 0
        self._result_version = 0
        self._returned_version = 0
        self._busy = False
        self._active = False
        self._region: tuple[int, int, int, int] | None = None
        self._last_thumb: np.ndarray | None = None
        self._displayed: tuple[np.ndarray, list[Rect]] | None = None
        self._last_submit_time = 0.0
        self._job: _Job | None = None
        self._result: tuple | None = None

    def detect(self, engine: ScreencapEngine, params: WeaponDetectParam | None) -> WeaponDetectResult:
        if params is None:
            return WeaponDetectResult()
        if params.region is None:
            return self._deactivate()
        config = Config.get()
        region = tuple(params.region)
        if region != self._region:
            self._reset(region)
        processing = "hdr_to_sdr" if params.hdr_processing_enabled else "none"
        image = np.array(grab_region(engine, region, processing=processing).convert("RGB"))
        gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
        thumb = cv2.resize(gray, THUMB_SIZE, interpolation=cv2.INTER_AREA)
        with self._lock:
            busy = self._busy
        changed = _changed_ratio(thumb, self._last_thumb) > config.weapon_change_threshold
        waited = time.time() - self._last_submit_time >= config.weapon_ocr_min_interval
        if changed and not busy and waited:
            self._submit(image, gray, region, thumb, params.ignore_texts, config)

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
                    anchors = [
                        (item.box[0] - region[0], item.box[1] - region[1], item.box[2], item.box[3])
                        for item in annotations
                    ]
                    self._displayed = (result_gray, anchors)
        if result.updated:
            self._active = True
        if self._displayed is not None:
            ref, anchors = self._displayed
            result.stale = _anchors_diff(gray, ref, anchors) > config.weapon_hide_threshold
        return result

    def stop(self) -> None:
        self._stop = True
        self._wake.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)

    def _reset(self, region: tuple[int, int, int, int] | None) -> None:
        with self._lock:
            self._generation += 1
            self._result = None
            self._job = None
        self._region = region
        self._last_thumb = None
        self._displayed = None
        self._last_submit_time = 0.0
        self._active = region is not None

    def _deactivate(self) -> WeaponDetectResult:
        """功能关闭或没有设置区域：清掉已显示的标注（只通知一次）"""
        was_active = self._active or self._region is not None
        if not was_active:
            return WeaponDetectResult()
        self._reset(None)
        self._active = False
        return WeaponDetectResult(updated=True)

    def _submit(self, img: np.ndarray, gray: np.ndarray, region: tuple[int, int, int, int],
                thumb: np.ndarray, ignore_texts: set[str], config: Config) -> None:
        height, width = img.shape[:2]
        scale = min(1.0, config.weapon_ocr_max_side / max(width, height))
        if scale < 1.0:
            img = cv2.resize(img, (int(width * scale), int(height * scale)), interpolation=cv2.INTER_AREA)
        with self._lock:
            self._job = _Job(
                self._generation, img, scale, (region[0], region[1]), set(ignore_texts), gray,
            )
            self._busy = True
        self._last_thumb = thumb
        self._last_submit_time = time.time()
        if self.ocr is None:
            self.ocr = OcrEngine(threads=config.weapon_ocr_threads)
        if self._thread is None or not self._thread.is_alive():
            self._stop = False
            self._thread = threading.Thread(target=self._worker, name="WeaponOcr", daemon=True)
            self._thread.start()
        self._wake.set()

    def _worker(self) -> None:
        info("Weapon OCR worker started.")
        while not self._stop:
            self._wake.wait()
            self._wake.clear()
            if self._stop:
                break
            with self._lock:
                job = self._job
                self._job = None
            if job is None:
                continue
            annotations: list[WeaponAnnotation] = []
            line_boxes: list[Rect] = []
            ocr_error = None
            started = time.time()
            try:
                config = Config.get()
                lines = self.ocr.recognize(job.image) if self.ocr is not None else []
                annotations, line_boxes = build_annotations(
                    lines, get_weapon_info(), job.origin, job.scale,
                    min_score=config.weapon_ocr_min_score, ignore_texts=job.ignore_texts,
                )
                ocr_error = self.ocr.error if self.ocr is not None else None
                debug(
                    f"WeaponDetector: {len(lines)} lines, {len(annotations)} annotations, "
                    f"time={time.time() - started:.3f}s"
                )
            except Exception as e:
                ocr_error = f"{type(e).__name__}: {e}"
                error(f"Weapon OCR failed: {ocr_error}")
            with self._lock:
                if job.generation == self._generation:
                    self._result = (job.generation, annotations, line_boxes, ocr_error, job.gray)
                    self._result_version += 1
                self._busy = False
        info("Weapon OCR worker stopped.")
