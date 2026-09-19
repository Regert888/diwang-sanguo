#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""实战测试2：用 op 4368 刷新封地信息（含伤兵）"""
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

# 发 op 4368 刷新封地
print('\n发送 op 4368 刷新封地信息...')
pk = c.send_op(4368, b"")

for p in pk or []:
    if p['op'] == 4368 + 0x7000:
        d = p['data']
        print(f'响应包长度: {len(d)} 字节')

        if len(d) < 100:
            print(f'包太短: {d[:100].hex()}')
            continue

        # 按 king_client.py:1025-1037 的结构扫描
        print('\n扫描封地 ID（long ∈ [1,1000]）...')
        fief_ids = []
        for i in range(0, len(d) - 8):
            try:
                v = struct.unpack_from('>q', d, i)[0]
                if 1 <= v <= 1000:
                    fief_ids.append((i, v))
            except:
                pass

        print(f'找到 {len(fief_ids)} 个疑似封地ID:')
        for off, fid in fief_ids[:10]:
            print(f'  偏移 {off}: fiefId={fid}')

        # 在每个 fiefId 后面找伤兵
        print('\n查找伤兵块（fiefId 后约 30-50 字节）...')
        for off, fid in fief_ids[:5]:
            start = off + 8
            end = min(start + 100, len(d))
            chunk = d[start:end]

            # 找健康兵种数 n1（通常 <10）
            for j in range(min(50, len(chunk))):
                n1 = chunk[j]
                if 0 <= n1 <= 10:
                    # 跳过健康兵（每个 5 字节）
                    pos = j + 1 + n1 * 5
                    if pos >= len(chunk):
                        continue

                    n2 = chunk[pos]
                    if 0 <= n2 <= 10:
                        print(f'\nfiefId={fid} 偏移={off} 健康兵种={n1} 伤兵种={n2}')

                        伤兵总数 = 0
                        pos += 1
                        for k in range(min(n2, 10)):
                            if pos + 5 > len(chunk):
                                break
                            seq = chunk[pos]
                            cnt = struct.unpack_from('>i', chunk, pos+1)[0]
                            if 0 < cnt < 100000:
                                伤兵总数 += cnt
                                print(f'  伤兵 seq={seq} 数量={cnt}')
                            pos += 5

                        if 伤兵总数 > 0:
                            print(f'  ★ 伤兵总数: {伤兵总数}')
        break
