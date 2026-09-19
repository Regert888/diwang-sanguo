#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试 op 5474 封地列表响应格式"""
import sys, struct, json
from core.king_client import KingClient, 取区服列表, 匹配区服

# 用账号 1 的配置登录
accts = json.load(open('accounts.json', encoding='utf-8'))
a = accts[0]  # 数组第一个账号
user = a['gameUsername']
pwd = a['gamePassword']
area_key = a['serverKey']

print('登录中...')
s, st, areas = 取区服列表(user, pwd)
print(f'收到 {len(areas)} 个区服')
for name, host, port in areas[:5]:
    print(f'  {name} ({host}:{port})')

match = 匹配区服(areas, area_key)
if not match:
    print(f'区服未找到，目标key={area_key}')
    # 尝试用区服名匹配
    for name, host, port in areas:
        if '328' in name:
            match = (name, host, port)
            print(f'找到包含328的区服：{name}')
            break
    if not match:
        sys.exit(1)

name, host, port = match
print(f'目标区服：{name}（{host}:{port}）')

c = KingClient(user, pwd, host, port)
c.session, c.sub_token = s, st
c.enter_game()
c.game_login()

print(f'play_id={c.play_id}')
print('\n发送 op 5474 查封地列表...')
pk = c.send_op(5474, struct.pack('>ii', 0, 0))
print(f'收到 {len(pk or [])} 个包')

for p in pk or []:
    op = p.get("op")
    signed = p.get("signed")
    d = p.get("data") or b""
    print(f'  op={op} signed={signed} len={len(d)}')

    if op == 5474 + 0x7000:
        print(f'  响应包前120字节: {d[:120].hex()}')
        print(f'  总长度: {len(d)} 字节')

        # 尝试扫描 long 值（可能是 fiefId）
        print('\n  扫描可能的 fiefId（1-100000范围）:')
        for i in range(0, min(200, len(d)-8), 1):
            try:
                v = struct.unpack_from('>q', d, i)[0]
                if 1 <= v <= 100000:
                    print(f'    @{i}: {v}')
            except:
                pass

        # 尝试扫描中文字符串（封地名）
        print('\n  扫描中文字符串（封地名）:')
        i = 0
        while i < len(d) - 2:
            try:
                slen = struct.unpack_from('>H', d, i)[0]
                if 2 <= slen <= 60 and i + 2 + slen <= len(d):
                    s = d[i+2:i+2+slen].decode('utf-8')
                    if s and all(ord(c) >= 0x20 for c in s):
                        print(f'    @{i}: "{s}"')
                        i += 2 + slen
                        continue
            except:
                pass
            i += 1
