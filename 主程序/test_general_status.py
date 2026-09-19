#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""查看武将实际状态（op 4368 增量包）"""
import sys, struct, json
from core.king_client import KingClient, 取区服列表, 匹配区服, 解析武将列表

# 用账号 1 的配置登录
accts = json.load(open('accounts.json', encoding='utf-8'))
a = accts[0]
user = a['gameUsername']
pwd = a['gamePassword']
area_key = a['serverKey']

print('登录中...')
s, st, areas = 取区服列表(user, pwd)
for name, host, port in areas:
    if '328' in name:
        match = (name, host, port)
        break

name, host, port = match
print(f'目标区服：{name}（{host}:{port}）')

c = KingClient(user, pwd, host, port)
c.session, c.sub_token = s, st
c.enter_game()
c.game_login()

print(f'\n发送 op 4368 查询武将增量包...')
pk = c.send_op(4368, b"")
print(f'收到 {len(pk or [])} 个包')

for p in pk or []:
    print(f'  op={p.get("op")} signed={p.get("signed")} len={len(p.get("data") or b"")}')

cache = {}
for p in pk or []:
    if p['op'] == 4368 + 0x7000:
        d = p['data']
        print(f'\n响应包长度: {len(d)} 字节')
        print(f'前120字节: {d[:120].hex()}')

        # 调用解析器（自动选择模式）
        gens = 解析武将列表(d)
        print(f'解析到 {len(gens)} 个武将:')

        for g in gens:
            print(f"  {g.get('name')} Lv{g.get('level')} "
                  f"体力{g.get('curHp')}/{g.get('maxHp')} "
                  f"忠{g.get('loyalty')} "
                  f"状态={g.get('status')} "
                  f"genId={g.get('genId')}")

        # 看原始 A4 字段
        print(f'\n原始 A4 字段:')
        for g in gens:
            print(f"  {g.get('name')}: ja={g.get('ja')} ra={g.get('ra')} sa={g.get('sa')} wa={g.get('wa')}")
        break
