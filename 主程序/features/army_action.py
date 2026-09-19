# -*- coding: utf-8 -*-
"""军情板块（查询出征/行军记录）。

★ 协议：op 5632 → 0xD600，四段结构（分类统计+分区+两组状态）
★ 前端契约：`/api/bot/<id>/army-action` 读 bot._army_action，结构为 {
    "categories": [...],
    "sections": [{type, groups, records: [{recordId, members, target信息, 坐标, flag/时间}]}],
    "extraStatus": [...],
    "extraStatus2": [...]
  }
"""
from app.feature import Feature


class ArmyActionFeature(Feature):
    NAME = "军情"
    TYPE = None          # 无配置项，始终运行
    ZONE = None
    INTERVAL = 30        # 原 _army_last 的 30 秒节流
    ORDER = 20           # 配兵(10) 之后、刷黄(30) 之前
    REQUIRES = ()

    def run(self, ctx, rows):
        from core.protocol.op5632_army_action import 解析军情

        # 载荷为空：DEX 显示 I(1,0,0,1) 即 4 个 int，但实测只要 op 就行
        packs = ctx.client.send_ops([(5632, b"")])
        parsed = 解析军情(packs)

        if not parsed:
            ctx.log("[军情] 查询无数据（op 0xd600 未返回有效载荷）")
            return False

        ctx.bot._army_action = parsed

        sections = parsed.get("sections") or []
        条数 = len(sections[0].get("records", [])) if sections else 0
        ctx.log("[军情] 查到 %d 条记录（消耗 %s/%s 字节）" % (
            条数, parsed.get("consumed", 0), parsed.get("total", 0)))
        return True
