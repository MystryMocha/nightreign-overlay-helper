import numpy as np
from types import SimpleNamespace

from PIL import Image

from src.detector.map_detector import (
    MapDetector,
    PoiCategoryInfo,
    STD_POI_SIZE,
    SubPoiInfo,
    get_poi_key,
)


def test_match_poi_resizes_category_icon_instead_of_calling_logger():
    """循环变量不能再叫 info，否则会撞上日志函数，地图识别会在 POI 匹配处直接失败。"""
    pos = (STD_POI_SIZE[0] // 2, STD_POI_SIZE[1] // 2)
    ctype = 30301
    poi_key = get_poi_key(ctype)
    assert poi_key is not None

    det = MapDetector.__new__(MapDetector)
    det.info = SimpleNamespace(
        all_nightlords={8},
        possible_poi_types={(0, 8, pos): {ctype}},
    )
    base = Image.new("RGBA", (16, 16), (180, 40, 40, 255))
    det.poi_cate_info = {
        poi_key: PoiCategoryInfo(
            base_image=base,
            subtypes={None: SubPoiInfo(ctypes={ctype}, image=base)},
        ),
        0: PoiCategoryInfo(
            base_image=Image.new("RGBA", (16, 16), (0, 0, 0, 0)),
            subtypes={None: SubPoiInfo(ctypes={0}, image=base)},
        ),
    }
    img = np.zeros((80, 80, 3), np.uint8)

    matched, score = det._match_poi(img, img, pos, earth_shifting=0, nightlord=8)

    assert matched == ctype
    assert score >= 0
