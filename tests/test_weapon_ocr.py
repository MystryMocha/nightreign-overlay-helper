import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.weapon.ocr import OcrEngine


class FakeOutput:
    """与 RapidOCR 的输出一致：boxes 是 numpy 数组而不是列表，不能直接做真值判断"""
    def __init__(self, boxes, txts, scores):
        self.boxes, self.txts, self.scores = boxes, txts, scores


def make_engine(output) -> OcrEngine:
    engine = OcrEngine()
    engine._engine = lambda image: output
    return engine


def poly(x, y, w=100, h=20):
    return [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]


def test_multiple_lines_from_numpy_boxes_are_returned_in_reading_order():
    boxes = np.array([poly(10, 80), poly(10, 20), poly(200, 20)], dtype=np.float32)
    engine = make_engine(FakeOutput(boxes, ("下面", "左上", "右上"), (0.9, 0.8, 0.7)))
    lines = engine.recognize(np.zeros((120, 320, 3), np.uint8))
    assert [(line.text, line.box) for line in lines] == [
        ("左上", (10, 20, 100, 20)), ("右上", (200, 20, 100, 20)), ("下面", (10, 80, 100, 20))]


def test_no_text_found():
    image = np.zeros((10, 10, 3), np.uint8)
    assert make_engine(None).recognize(image) == []
    assert make_engine(FakeOutput(None, None, None)).recognize(image) == []
