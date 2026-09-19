# -*- coding: utf-8 -*-
"""投影层测试 —— 原子数据 → 前端结构。

投影是纯函数（无状态、无 IO），直接喂原子数据断言输出即可。
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.presenters import build_generals, build_troops


GENERAL_KEYS = {
    "genId", "name", "statusText", "typeText", "level",
    "curHp", "maxHp", "curLoyalty", "maxLoyalty",
    "soldierCount", "curTroops", "maxTroops", "soldierName",
}

TROOP_KEYS = {
    "fiefIndex", "soldierName", "idleCount",
    "woundedCount", "fiefName", "genId",
}

兵种名表 = {"3": "轻骑兵", "2": "弓兵", "10": "重骑兵"}


def test_generals_基本投影():
    raw = [
        {"genId": 2001, "name": "张飞", "ga": 0, "Oa": 0,
         "ja": 55, "ra": 95, "sa": 100, "wa": 65},
        {"genId": 2002, "name": "赵云", "ga": 2, "Oa": 8,
         "ja": 60, "ra": 100, "sa": 100, "wa": 80},
    ]
    部队表 = {2001: (3, 8000), 2002: (10, 6000)}

    out = build_generals(raw, 部队表, 兵种名表)

    assert len(out) == 2
    assert set(out[0].keys()) == GENERAL_KEYS, "键集漂移"

    张飞 = out[0]
    assert 张飞["name"] == "张飞"
    assert 张飞["typeText"] == "步"          # ga=0
    assert 张飞["statusText"] == "待命"      # Oa=0
    assert 张飞["level"] == 55               # ja
    assert 张飞["curHp"] == 95               # ra
    assert 张飞["maxHp"] == 100              # sa
    assert 张飞["curLoyalty"] == 65          # wa
    assert 张飞["soldierCount"] == 8000      # 来自部队表
    assert 张飞["soldierName"] == "轻骑兵"   # seq 3

    赵云 = out[1]
    assert 赵云["typeText"] == "骑"          # ga=2
    assert 赵云["statusText"] == "返回中"    # Oa=8
    assert 赵云["soldierName"] == "重骑兵"   # seq 10


def test_generals_无部队():
    """武将不在部队表里 → 兵力 0，兵种显示占位符"""
    raw = [{"genId": 3001, "name": "关羽", "ga": 1, "Oa": 0,
            "ja": 30, "ra": 80, "sa": 80, "wa": 90}]

    out = build_generals(raw, {}, 兵种名表)

    assert out[0]["soldierCount"] == 0
    assert out[0]["soldierName"] == "—"
    assert out[0]["typeText"] == "弓"        # ga=1


def test_generals_空输入():
    assert build_generals([], {}, 兵种名表) == []


def test_troops_基本投影():
    伤兵表 = {
        "主城": {
            "闲兵": [(3, 5000), (2, 3000)],
            "伤兵": [(3, 200)],
        },
    }

    out = build_troops(伤兵表, 兵种名表)

    assert len(out) == 2, "两个兵种应拆成两行"
    assert set(out[0].keys()) == TROOP_KEYS, "键集漂移"

    轻骑 = next(t for t in out if t["soldierName"] == "轻骑兵")
    assert 轻骑["fiefName"] == "主城"
    assert 轻骑["idleCount"] == 5000
    assert 轻骑["woundedCount"] == 200

    弓兵 = next(t for t in out if t["soldierName"] == "弓兵")
    assert 弓兵["idleCount"] == 3000
    assert 弓兵["woundedCount"] == 0, "只有闲兵没伤兵时应为 0"


def test_troops_多封地():
    伤兵表 = {
        "主城": {"闲兵": [(3, 1000)], "伤兵": []},
        "封地A": {"闲兵": [(2, 500)], "伤兵": [(2, 50)]},
    }

    out = build_troops(伤兵表, 兵种名表)

    assert len(out) == 2
    assert {t["fiefName"] for t in out} == {"主城", "封地A"}


def test_troops_空输入():
    assert build_troops({}, 兵种名表) == []


def _run():
    tests = [(n, f) for n, f in globals().items()
             if n.startswith("test_") and callable(f)]
    失败 = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  PASS  {name}")
        except AssertionError as e:
            print(f"  FAIL  {name}: {e}")
            失败 += 1
        except Exception as e:
            print(f"  ERROR {name}: {type(e).__name__}: {e}")
            失败 += 1
    print(f"\n{len(tests) - 失败}/{len(tests)} passed")
    return 失败


if __name__ == "__main__":
    sys.exit(1 if _run() else 0)
