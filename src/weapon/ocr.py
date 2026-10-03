"""
文字识别（OCR）封装：基于 RapidOCR(onnxruntime)，模型随安装包离线提供，识别简体中文。

RapidOCR 在第一次识别时才加载（约 30MB 模型），没启用武器信息功能时不占内存；
加载失败（缺依赖、模型文件损坏）时只记录原因并降级为“不可用”，不影响程序的其他功能。
"""
import threading
from dataclasses import dataclass

import numpy as np

from src.logger import error, info


@dataclass
class OcrLine:
    text: str
    box: tuple[int, int, int, int]
    score: float


class OcrEngine:
    def __init__(self, threads: int = 2):
        self.threads = max(1, int(threads))
        self.error: str | None = None
        self._engine = None
        self._lock = threading.Lock()

    @property
    def available(self) -> bool:
        return self.error is None

    def _ensure_loaded(self) -> None:
        if self._engine is not None or self.error is not None:
            return
        try:
            from rapidocr import RapidOCR
            self._engine = RapidOCR(params={
                "Global.use_cls": False,
                "Global.log_level": "warning",
                "EngineConfig.onnxruntime.intra_op_num_threads": self.threads,
                "EngineConfig.onnxruntime.inter_op_num_threads": 1,
            })
            info(f"OCR engine loaded (threads={self.threads})")
        except Exception as e:
            self.error = f"{type(e).__name__}: {e}"
            error(f"Failed to load OCR engine: {self.error}")

    def recognize(self, image_rgb: np.ndarray) -> list[OcrLine]:
        """识别一张 RGB 图像，返回按位置排序的文字行；引擎不可用时返回空列表"""
        with self._lock:
            self._ensure_loaded()
            if self._engine is None:
                return []
            output = self._engine(np.ascontiguousarray(image_rgb[:, :, ::-1]))   # RapidOCR 需要 BGR
            # boxes 是 numpy 数组，不能直接做真假判断（多于一个元素时会抛 ValueError）
            boxes = getattr(output, "boxes", None)
            if boxes is None or len(boxes) == 0 or output.txts is None:
                return []
            lines: list[OcrLine] = []
            for poly, text, score in zip(output.boxes, output.txts, output.scores):
                xs = [p[0] for p in poly]
                ys = [p[1] for p in poly]
                x, y = int(min(xs)), int(min(ys))
                w = max(1, int(max(xs) - x))
                h = max(1, int(max(ys) - y))
                lines.append(OcrLine(str(text), (x, y, w, h), float(score)))
            lines.sort(key=lambda line: (line.box[1], line.box[0]))
            return lines
