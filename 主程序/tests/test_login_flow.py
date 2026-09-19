# -*- coding: utf-8 -*-
"""测试登录流程（从借鉴代码迁移）"""
import sys
import os

# 添加主程序目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.king_client import KingClient
from core.protocol import enter_game, game_login


def test_login():
    """测试完整登录流程"""
    # 替换为真实账号信息
    user = "your_username"
    pwd = "your_password"

    # 创建客户端
    client = KingClient(user, pwd)

    print("1. 获取区服列表...")
    client.get_server_list()
    print(f"   找到 {len(client.areas)} 个区服")

    if not client.areas:
        print("   失败：未找到区服")
        return False

    # 使用第一个区服
    area_name, host, port = client.areas[0]
    print(f"   选择区服：{area_name} ({host}:{port})")

    client.game_host = host
    client.game_port = port

    print("\n2. 进入游戏（enter_game）...")
    packets = enter_game(client)
    print(f"   收到 {len(packets)} 个包")
    print(f"   play_id = {client.play_id}")

    if not client.play_id:
        print("   失败：未获取到 play_id")
        return False

    print("\n3. 登录游戏（game_login）...")
    packets = game_login(client, role_index=0)
    print(f"   收到 {len(packets)} 个包")
    print(f"   role_id = {client.role_id}")

    if not client.role_id:
        print("   失败：未获取到 role_id")
        return False

    print("\n✓ 登录成功！")
    return True


if __name__ == "__main__":
    test_login()
