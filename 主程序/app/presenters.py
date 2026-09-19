# -*- coding: utf-8 -*-
"""数据投影层 —— 原始数据 → 前端结构。

★ 武将/部队不是状态，是投影（A4 × 部队表 × 伤兵表 × 兵种名表）。
  改成投影后，当前「6 个读者 / 3 个写者」的纠缠矩阵直接消失。
"""


def build_generals(raw_a4, 部队表, 兵种名表):
    """原始 A4 数据 → 前端英雄表结构。

    Args:
        raw_a4: 解析武将列表() 返回的字典列表
        部队表: {武将ID: (兵种seq, 数量)}
        兵种名表: {seq字符串: 兵种名}

    Returns:
        前端 generals 数组，每项 13 个键（genId/name/statusText/typeText/level/
        curHp/maxHp/curLoyalty/maxLoyalty/soldierCount/curTroops/maxTroops/soldierName）
    """
    gens = []
    for g in raw_a4:
        nm = g.get("name", "")
        将类 = {0: "步", 1: "弓", 2: "骑", 4: "勇"}.get(g.get("ga"), "—")

        # 兵种/数量来自 部队表（真实数据）
        sid, scnt = 部队表.get(g.get("genId"), (None, 0))

        gens.append({
            "genId": g.get("genId", 0),
            "name": nm,
            "statusText": {0: "待命", 1: "行军中", 8: "返回中"}.get(
                g.get("Oa"), ("状态%s" % g.get("Oa")) if g.get("Oa") else "—"),
            "typeText": 将类,
            "level": int(g.get("ja", 1) or 1),
            "curHp": int(g.get("ra", 0) or 0),       # ★ ra=体力（A4 真值验证）
            "maxHp": int(g.get("sa", 0) or 0),        # sa=体力上限
            "curLoyalty": int(g.get("wa", 0) or 0),    # ★ wa=忠诚（A4 真值验证）
            "maxLoyalty": 100,
            "soldierCount": int(scnt or 0),
            "curTroops": int(scnt or 0),
            "maxTroops": int(scnt or 0),
            "soldierName": (兵种名表 or {}).get(str(sid), "—") if sid else "—",
        })
    return gens


def build_troops(伤兵表, 兵种名表):
    """封地 → 军队表结构（显示每个封地的闲兵和伤兵）。

    Args:
        伤兵表: {封地名: {"闲兵": [(seq,cnt),...], "伤兵": [(seq,cnt),...]}}
        兵种名表: {seq字符串: 兵种名}

    Returns:
        前端 troops 数组，每项 6 个键（fiefIndex/soldierName/idleCount/
        woundedCount/fiefName/genId）
    """
    out = []

    # 伤兵表结构：{封地名: {"闲兵": [(seq,cnt),...], "伤兵": [(seq,cnt),...]}}
    for idx, (fief_name, data) in enumerate(伤兵表.items()):
        闲兵列表 = data.get("闲兵", [])
        伤兵列表 = data.get("伤兵", [])

        # 按兵种分组显示（每个兵种一行）
        兵种汇总 = {}  # {seq: {"闲兵": cnt, "伤兵": cnt}}
        for seq, cnt in 闲兵列表:
            if seq not in 兵种汇总:
                兵种汇总[seq] = {"闲兵": 0, "伤兵": 0}
            兵种汇总[seq]["闲兵"] = cnt

        for seq, cnt in 伤兵列表:
            if seq not in 兵种汇总:
                兵种汇总[seq] = {"闲兵": 0, "伤兵": 0}
            兵种汇总[seq]["伤兵"] = cnt

        # 每个兵种一行
        for seq, counts in 兵种汇总.items():
            soldier_name = (兵种名表 or {}).get(str(seq), f"兵种{seq}")
            out.append({
                "fiefIndex": idx + 1,
                "soldierName": soldier_name,
                "idleCount": counts["闲兵"],
                "woundedCount": counts["伤兵"],
                "fiefName": fief_name,
                "genId": 0,  # 封地没有武将ID
            })

    return out


def to_poll(bot):
    """BotSession → /api/bot/{id}/poll 响应结构（21 个键契约）。

    前端契约的 21 个键（已对线上响应实测校正）：
    status/character/generals/officers/troops/items/roleStatuses/roleStatusList/
    convoyCountries/logs/total/nextIndex/running/uptime/alarmActive/alarmCount/
    tasks/worker/lastError/lastAccessTime/source
    """
    return {
        "status": bot.status,
        "character": bot.character,
        "generals": bot.generals,
        "officers": bot.officers or [],       # 即使空也要存在
        "troops": bot.troops,
        "items": bot.items,
        "roleStatuses": bot.role_statuses,
        "roleStatusList": bot.role_status_list,
        "convoyCountries": bot.convoy_countries or [],  # 即使空也要存在
        "logs": bot.logs,
        "total": bot.total,
        "nextIndex": bot.next_index,
        "running": bot.running,
        "uptime": int(bot.uptime),
        "alarmActive": bot.alarm_active,
        "alarmCount": bot.alarm_count,
        "tasks": bot.tasks,
        "worker": bot.worker,
        "lastError": bot.last_error,
        "lastAccessTime": bot.last_access_time,
        "source": "backend",
    }
