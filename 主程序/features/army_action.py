# -*- coding: utf-8 -*-
"""军情板块（查询+展示出征/行军记录）。

★ 协议：op 5632 → 0xD600，四段结构（分类统计+分区+两组状态）
★ 前端契约：`/api/bot/<id>/army-action` 返回 {
    "categories": [...],
    "sections": [{type, groups, records: [{recordId, members, target信息, 坐标, flag/时间}]}],
    "extraStatus": [...],
    "extraStatus2": [...]
  }
"""
import time


def 执行(bot, cfg):
    """每轮刷新时查询军情（间隔控制避免频繁请求）。"""
    from core.king_client import send_ops
    from core.protocol.op5632_army_action import 解析军情

    now = time.time()
    if now - getattr(bot, "_army_last", 0) < 30:
        return

    bot._army_last = now

    try:
        # 发送 op 5632，载荷为空（DEX 显示 I(1,0,0,1) 即 4 个 int，但实测只要 op 就行）
        packs = send_ops(bot.client, [(5632, b"")])
        parsed = 解析军情(packs)

        if parsed:
            bot._army_action = parsed
            bot.log(f"[军情] 查到 {len(parsed.get('sections',[])[0].get('records',[]) if parsed.get('sections') else 0)} 条记录（消耗 {parsed.get('consumed',0)}/{parsed.get('total',0)} 字节）")
        else:
            bot.log("[军情] 查询无数据（op 0xd600 未返回有效载荷）")
    except Exception as e:
        bot.log(f"[军情] 异常: {e}")
