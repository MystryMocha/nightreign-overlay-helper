import csv

from src.common import get_data_path
from src.detector.map_info import load_map_info

ALLOWED_TERMS = {
    "火", "雷", "圣", "魔", "冰", "毒", "腐败", "出血", "冻伤",
    "睡眠", "发狂", "即死", "打击", "斩击", "突刺",
}


def load_boss_rows():
    with open(get_data_path("csv/boss_info.csv"), encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_boss_info_names_exist_in_names_csv():
    with open(get_data_path("csv/names.csv"), encoding="utf-8") as f:
        f.readline()
        names = {row[1] for row in csv.reader(f)}
    rows = load_boss_rows()
    assert rows
    assert len({r["name"] for r in rows}) == len(rows), "boss_info.csv 中有重复的BOSS名称"
    missing = [r["name"] for r in rows if r["name"] not in names]
    assert not missing, f"boss_info.csv 中的名称在 names.csv 中不存在: {missing}"


def test_boss_info_terms_are_known():
    for r in load_boss_rows():
        for col in ("weak", "resist"):
            terms = [t for t in r[col].split("/") if t]
            unknown = [t for t in terms if t not in ALLOWED_TERMS]
            assert not unknown, f"{r['name']} 的 {col} 含有未知词条: {unknown}"


def test_weakness_text():
    info = load_map_info(
        get_data_path("csv/map_patterns.csv"),
        get_data_path("csv/constructs.csv"),
        get_data_path("csv/names.csv"),
        get_data_path("csv/positions.csv"),
        get_data_path("csv/boss_info.csv"),
    )
    info.boss_weakness = {"甲": ("火/雷", "圣"), "乙": ("毒", ""), "丙": ("", "")}
    assert info.get_weakness_text("甲") == "弱:火/雷 抗:圣"
    assert info.get_weakness_text("乙") == "弱:毒"
    assert info.get_weakness_text("甲", with_resist=False) == "弱:火/雷"
    assert info.get_weakness_text("丙") is None
    assert info.get_weakness_text("不存在") is None
    assert info.get_weakness_text(None) is None
