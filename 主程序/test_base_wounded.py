#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试基地伤兵查询（op 4657）"""
import sys, struct, json
from core.king_client import KingClient, 取区服列表, 匹配区服

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
pk_login = c.game_login()

print(f'play_id={c.play_id}')

# 尝试从 gameLogin 包里提取基地 fiefId
print('\n从 gameLogin 响应扫描 fiefId...')
for p in pk_login or []:
    if p['op'] == 32772:  # gameLogin 响应
        d = p['data']
        print(f'gameLogin 响应长度: {len(d)} 字节')
        # 扫描 long 范围 1-100000
        candidates = []
        for i in range(0, min(300, len(d)-8)):
            try:
                v = struct.unpack_from('>q', d, i)[0]
                if 1 <= v <= 100000:
                    candidates.append((i, v))
            except:
                pass
        print(f'候选 fiefId: {candidates[:10]}')

        # 尝试偏移 10-50 之间的第一个 long
        for i in range(10, min(50, len(d)-8)):
            try:
                v = struct.unpack_from('>q', d, i)[0]
                if 1 <= v <= 100000:
                    base_fief_id = v
                    print(f'疑似基地 fiefId: {base_fief_id} (偏移 {i})')
                    break
            except:
                pass

# 尝试几个候选值
test_ids = [1, 10, 100, 1000]
if 'base_fief_id' in locals():
    test_ids.insert(0, base_fief_id)

for fid in test_ids:
    print(f'\n测试 fiefId={fid} 查伤兵...')
    payload = struct.pack(">q", fid) + struct.pack(">h", -1) + struct.pack(">i", 0)
    pk = c.send_op(4657, b"\x00\x00" + payload)

    for p in pk or []:
        if p['op'] == 4657 + 0x7000:
            d = p['data']
            print(f'  响应长度: {len(d)} 字节')
            if len(d) > 1:
                print(f'  前80字节: {d[:80].hex()}')
                # 尝试解析
                if len(d) >= 50:
                    try:
                        resp_fid = struct.unpack_from('>q', d, 41)[0]
                        print(f'  解析封地ID: {resp_fid}')
                        n1 = d[49]
                        print(f'  健康兵种数: {n1}')
                        if n1 <= 10:
                            pos = 50
                            for i in range(n1):
                                if pos + 5 <= len(d):
                                    seq = d[pos]
                                    cnt = struct.unpack_from('>i', d, pos+1)[0]
                                    print(f'    健康 seq={seq} cnt={cnt}')
                                    pos += 5
                            if pos < len(d):
                                n2 = d[pos]
                                print(f'  伤兵种数: {n2}')
                                pos += 1
                                for i in range(min(n2, 10)):
                                    if pos + 5 <= len(d):
                                        seq = d[pos]
                                        cnt = struct.unpack_from('>i', d, pos+1)[0]
                                        print(f'    伤兵 seq={seq} cnt={cnt}')
                                        pos += 5
                    except Exception as e:
                        print(f'  解析失败: {e}')
            else:
                print(f'  返回: {d.hex()}')
            break
