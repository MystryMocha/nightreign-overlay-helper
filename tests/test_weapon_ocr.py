from types import SimpleNamespace

import numpy as np

from src.weapon.ocr import OcrEngine


class _FakeRapidOcr:
    def __init__(self, output):
        self.output = output
        self.received = None

    def __call__(self, image):
        self.received = image
        return self.output


def _engine_with(output) -> tuple[OcrEngine, _FakeRapidOcr]:
    engine = OcrEngine()
    engine._engine = _FakeRapidOcr(output)
    return engine, engine._engine


def test_multiple_boxes_as_numpy_array():
    # RapidOCR 返回的 boxes 是 numpy 数组，多于一行文字时不能做真假判断
    boxes = np.array([
        [[10, 40], [90, 40], [90, 60], [10, 60]],
        [[10, 5], [120, 5], [120, 30], [10, 30]],
    ], dtype=np.float32)
    engine, _ = _engine_with(SimpleNamespace(boxes=boxes, txts=("攻击", "夜与火之剑"), scores=(0.9, 0.95)))
    lines = engine.recognize(np.zeros((80, 160, 3), np.uint8))
    assert [line.text for line in lines] == ["夜与火之剑", "攻击"]
    assert lines[0].box == (10, 5, 110, 25)


def test_no_text_detected():
    engine, _ = _engine_with(SimpleNamespace(boxes=None, txts=None, scores=None))
    assert engine.recognize(np.zeros((8, 8, 3), np.uint8)) == []
    engine, _ = _engine_with(SimpleNamespace(boxes=np.zeros((0, 4, 2)), txts=(), scores=()))
    assert engine.recognize(np.zeros((8, 8, 3), np.uint8)) == []


def test_image_is_passed_as_bgr():
    engine, fake = _engine_with(SimpleNamespace(boxes=None, txts=None, scores=None))
    image = np.zeros((2, 2, 3), np.uint8)
    image[..., 0] = 255     # 红色（RGB）
    engine.recognize(image)
    assert fake.received[0, 0].tolist() == [0, 0, 255]
