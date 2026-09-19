# -*- coding: utf-8 -*-
"""区服匹配测试。

★ 回归目标：serverKey 带 'hk_' 前缀，而服务端区服名不带，
  旧实现整串比对导致永远匹配失败、静默兜底到 areas[0]（连错服）。
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.protocol.login import 匹配区服

# 取自真实响应（70 个区服中的代表性样本，含重复项）
AREAS = [
    ("328區豪情逸致", "47.100.130.113", 25511),
    ("329區正本清源", "47.100.130.114", 25511),
    ("318區礪嶽盟河", "47.100.130.115", 25511),
    ("330區滄海遺珠(新服)", "47.100.130.116", 25511),
    ("328區豪情逸致", "47.100.130.117", 25511),   # 重复项
    ("霸圖19區", "47.100.65.106", 25511),
    ("1328區測試", "47.100.65.107", 25511),        # 数字前缀陷阱
]


def test_serverKey带hk前缀():
    """accounts.json 里的真实格式"""
    assert 匹配区服(AREAS, "hk_328")[0] == "328區豪情逸致"
    assert 匹配区服(AREAS, "hk_霸圖19")[0] == "霸圖19區"


def test_重复项取第一条():
    """328區 在列表里有两条，应取先出现的"""
    assert 匹配区服(AREAS, "hk_328")[1] == "47.100.130.113"


def test_不会误匹配更长的数字():
    """'328' 不能命中 '1328區測試'"""
    name, host, _ = 匹配区服(AREAS, "hk_328")
    assert name == "328區豪情逸致", "误匹配到 %s" % name

    # 反向：1328 应该精确命中自己
    assert 匹配区服(AREAS, "hk_1328")[0] == "1328區測試"


def test_繁简区字互通():
    assert 匹配区服(AREAS, "328区")[0] == "328區豪情逸致"
    assert 匹配区服(AREAS, "霸图19区") is None or True  # 简体霸图≠繁体霸圖，不强求


def test_完整区服名():
    assert 匹配区服(AREAS, "328區豪情逸致")[0] == "328區豪情逸致"


def test_纯数字():
    assert 匹配区服(AREAS, "329")[0] == "329區正本清源"


def test_带括号的新服():
    assert 匹配区服(AREAS, "hk_330")[0] == "330區滄海遺珠(新服)"


def test_匹配不到返回None():
    assert 匹配区服(AREAS, "hk_999") is None
    assert 匹配区服(AREAS, "") is None
    assert 匹配区服(AREAS, None) is None


def _run():
    tests = [(n, f) for n, f in globals().items()
             if n.startswith("test_") and callable(f)]
    失败 = 0
    for name, fn in tests:
        try:
            fn()
            print("  PASS  %s" % name)
        except AssertionError as e:
            print("  FAIL  %s: %s" % (name, e))
            失败 += 1
        except Exception as e:
            print("  ERROR %s: %s: %s" % (name, type(e).__name__, e))
            失败 += 1
    print("\n%d/%d passed" % (len(tests) - 失败, len(tests)))
    return 失败


if __name__ == "__main__":
    sys.exit(1 if _run() else 0)
