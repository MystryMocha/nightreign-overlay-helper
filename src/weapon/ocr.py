"""
文字识别（OCR）封装：基于 RapidOCR(onnxruntime)，模型随安装包离线提供，识别简体中文。

RapidOCR 在第一次识别时才加载（约 30MB 模型），没启用武器信息功能时不占内存；
加载失败（缺依赖、模型文件损坏）时只记录原因并降级为“不可用”，不影响程序的其他功能。
"""
import threading
from dataclasses import dataclass

import numpy as np

from src.logger import info, error


@dataclass
class OcrLine:
    text: str
    box: tuple[int, int, int, int]  # x, y, w, h，相对传入图像的左上角
    score: float


class OcrEngine:
    def __init__(self, threads: int = 2):
        # 限制推理线程数：默认会占满所有 CPU 核心，游戏里会明显掉帧
        self.threads = max(1, int(threads))
        self.error: str | None = None
        self._engine = None
        self._lock = threading.Lock()

    @property
    def available(self) -> bool:
        return self.error is None

    def _ensure_loaded(self) -> bool:
        if self._engine is not None:
            return True
        if self.error is not None:
            return False
        try:
            from rapidocr import RapidOCR
            self._engine = RapidOCR(params={
                "Global.use_cls": False,            # 游戏里的文字不会旋转，省掉方向分类
                "Global.log_level": "warning",
                "EngineConfig.onnxruntime.intra_op_num_threads": self.threads,
                "EngineConfig.onnxruntime.inter_op_num_threads": 1,
            })
            info(f"OCR engine loaded (threads={self.threads})")
            return True
        except Exception as e:
            self.error = f"{type(e).__name__}: {e}"
            error(f"Failed to load OCR engine: {self.error}")
            return False

    def recognize(self, image_rgb: np.ndarray) -> list[OcrLine]:
        """识别一张 RGB 图像，返回按位置排序的文字行；引擎不可用时返回空列表"""
        with self._lock:
            if not self._ensure_loaded():
                return []
            result = self._engine(np.ascontiguousarray(image_rgb[:, :, ::-1]))   # RapidOCR 需要 BGR
        if result is None or result.boxes is None or result.txts is None:
            return []
        lines = []
        for poly, text, score in zip(result.boxes, result.txts, result.scores):
            xs = [p[0] for p in poly]
            ys = [p[1] for p in poly]
            x, y = int(min(xs)), int(min(ys))
            lines.append(OcrLine(text=text, box=(x, y, int(max(xs)) - x, int(max(ys)) - y), score=float(score)))
        lines.sort(key=lambda l: (l.box[1], l.box[0]))
        return lines
