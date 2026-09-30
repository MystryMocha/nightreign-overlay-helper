from dataclasses import dataclass

from src.common import load_yaml, get_data_path


@dataclass
class CrystalLayout:
    initial: list[int]  # 开局即刷新的水晶
    later: list[int]    # 之后额外刷新的水晶

    @property
    def all(self) -> set[int]:
        return set(self.initial) | set(self.later)


@dataclass
class CrystalInfo:
    crystals: dict[int, tuple[float, float]]    # 水晶序号 -> 地图相对坐标(x, y)，包含地下水晶
    underground: set[int]                       # 地下水晶序号
    layouts: list[CrystalLayout]                # 下标0为"所有水晶"，1..N为具体布局

    def match_layouts(self, detected: set[int]) -> list[int]:
        """
        根据地图上识别到的水晶，返回可能的布局序号列表（1..N）
        识别结果可能包含少量误识别，允许的冲突数量随识别数量增加
        返回空列表表示无法判断
        """
        detected = set(detected) & set(self.crystals.keys())
        if not detected:
            return []
        conflicts = {
            i: len(detected - self.layouts[i].all)
            for i in range(1, len(self.layouts))
        }
        min_conflict = min(conflicts.values())
        if min_conflict > (len(detected) - 1) // 3:
            return []
        return [i for i, c in conflicts.items() if c == min_conflict]


def load_crystal_info(path: str | None = None) -> CrystalInfo:
    data = load_yaml(path or get_data_path("crystal.yaml"))
    crystals = {int(k): tuple(v) for k, v in data['crystals'].items()}
    underground = {int(k): tuple(v) for k, v in data['underground_crystals'].items()}
    layouts = [
        CrystalLayout(
            initial=[int(x) for x in p.get('initial') or []],
            later=[int(x) for x in p.get('later') or []],
        )
        for p in data['patterns']
    ]
    return CrystalInfo(
        crystals={**crystals, **underground},
        underground=set(underground.keys()),
        layouts=layouts,
    )
