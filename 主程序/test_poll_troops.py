#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""直接从 server.py 拿到的实时武将数据看看有没有伤兵"""
import json, time, requests

# 轮询 3 次，间隔 2 秒
for i in range(3):
    print(f'\n第 {i+1} 次轮询...')
    r = requests.get('http://localhost:3456/api/bot/1/poll?sinceIndex=0', timeout=5)
    data = r.json()

    if data.get('status') != 'ok':
        print(f'错误: {data}')
        continue

    bot = data['data']
    troops = bot.get('troops') or []

    print(f'troops 数组长度: {len(troops)}')

    if not troops:
        print('  troops 为空')
    else:
        for t in troops:
            print(f'  封地{t.get("fiefIndex")} {t.get("fiefName")} '
                  f'{t.get("soldierName")} '
                  f'健康={t.get("idleCount")} 伤兵={t.get("woundedCount")} '
                  f'genId={t.get("genId")}')

    if i < 2:
        time.sleep(2)
