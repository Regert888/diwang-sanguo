#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""副本功能测试（与刷黄同构）"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.king_client import KingClient, 扫描副本, 出征打副本

def test_dungeon():
    """测试副本扫描和出征"""
    print("=== 副本功能测试 ===\n")

    # 1. 创建客户端
    username = os.environ.get("GAME_USER", "")
    password = os.environ.get("GAME_PASS", "")
    zone_name = os.environ.get("GAME_ZONE", "")

    if not username or not password:
        print("请设置环境变量: GAME_USER, GAME_PASS, GAME_ZONE")
        print("或者参考 test_thief.py 查看实际运行示例")
        return

    client = KingClient(
        username=username,
        password=password,
        zone_name=zone_name
    )

    print("1. 登录游戏...")
    try:
        area_name, role_id, generals = client.login()
        print(f"   ✓ 已登录 {area_name} 角色ID={role_id} 武将数={len(generals)}")
    except Exception as e:
        print(f"   ✗ 登录失败: {e}")
        return

    # 2. 扫描副本（地图中心附近）
    print("\n2. 扫描副本（锚点 93,28）...")
    try:
        dungeons = 扫描副本(client, [(93, 28)])
        print(f"   找到 {len(dungeons)} 个副本:")
        for did, d in list(dungeons.items())[:5]:
            print(f"     · {d.get('name')} Lv{d.get('lvl')} 坐标({d.get('x')},{d.get('y')}) ID={did}")
    except Exception as e:
        print(f"   ✗ 扫描失败: {e}")
        return

    if not dungeons:
        print("   提示：未找到副本，可能需要调整锚点坐标")
        return

    # 3. 出征（用第一个副本测试，但不真正发送）
    first_dungeon = list(dungeons.values())[0]
    print(f"\n3. 出征测试目标: {first_dungeon.get('name')} Lv{first_dungeon.get('lvl')}")

    if not generals:
        print("   ✗ 无可用武将")
        return

    gen_ids = [g["genId"] for g in generals[:3]]  # 取前3个武将
    print(f"   武将: {[g['name'] for g in generals[:3]]}")
    print(f"   ID列表: {gen_ids}")

    # 构造载荷（不真正发送，避免扣体力）
    import struct
    cnt = len(gen_ids)
    fmt = ">BI" + "I" * cnt
    payload = struct.pack(fmt, cnt, first_dungeon["id"], *gen_ids)
    print(f"   载荷: op=5412 len={len(payload)} hex={payload[:16].hex()}...")
    print("   （测试通过，实际出征请在配置里启用）")

if __name__ == "__main__":
    test_dungeon()
