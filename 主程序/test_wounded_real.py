#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""实战测试：查询基地伤兵（游戏里看到 143 伤兵）"""
import sys, struct, json
from core.king_client import KingClient, 取区服列表

# 账号 1
accts = json.load(open('accounts.json', encoding='utf-8'))
a = accts[0]
user, pwd = a['gameUsername'], a['gamePassword']

print('登录...')
s, st, areas = 取区服列表(user, pwd)
match = next((n, h, p) for n, h, p in areas if '328' in n)
name, host, port = match
print(f'区服：{name}')

c = KingClient(user, pwd, host, port)
c.session, c.sub_token = s, st
c.enter_game()
pk_login = c.game_login()
print(f'play_id={c.play_id}')

# 从 gameLogin 包里扫 fiefId（偏移 10 开始的第一个 long ∈ [1,100000]）
base_fief_id = None
for p in pk_login or []:
    if p['op'] == 32772:
        d = p['data']
        for i in range(10, min(100, len(d)-8)):
            v = struct.unpack_from('>q', d, i)[0]
            if 1 <= v <= 100000:
                base_fief_id = v
                print(f'疑似基地 fiefId={v} (偏移 {i})')
                break
        break

if not base_fief_id:
    print('未找到 fiefId，尝试 fid=1')
    base_fief_id = 1

# 发 op 4657 查伤兵
print(f'\n查询 fiefId={base_fief_id} 的伤兵...')
payload = struct.pack(">q", base_fief_id) + struct.pack(">h", -1) + struct.pack(">i", 0)
pk = c.send_op(4657, b"\x00\x00" + payload)

found = False
for p in pk or []:
    if p['op'] == 4657 + 0x7000:
        d = p['data']
        print(f'响应包长度: {len(d)} 字节')
        if len(d) < 50:
            print(f'包太短: {d.hex()}')
            continue

        # 按 king_client.py:1056-1080 的结构解析
        try:
            resp_fid = struct.unpack_from('>q', d, 41)[0]
            print(f'响应封地ID: {resp_fid}')
            n1 = d[49]
            print(f'健康兵种数: {n1}')

            pos = 50
            # 跳过健康兵
            for i in range(min(n1, 20)):
                if pos + 5 > len(d):
                    break
                pos += 5

            if pos < len(d):
                n2 = d[pos]
                print(f'伤兵种数: {n2}')
                pos += 1

                伤兵总数 = 0
                for i in range(min(n2, 20)):
                    if pos + 5 > len(d):
                        break
                    seq = d[pos]
                    cnt = struct.unpack_from('>i', d, pos+1)[0]
                    伤兵总数 += cnt
                    print(f'  伤兵 seq={seq} 数量={cnt}')
                    pos += 5

                print(f'\n伤兵总数: {伤兵总数}')
                found = True
        except Exception as e:
            print(f'解析失败: {e}')
            print(f'前120字节: {d[:120].hex()}')
        break

if not found:
    print('未收到有效响应')
