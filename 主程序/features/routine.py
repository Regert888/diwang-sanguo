# -*- coding: utf-8 -*-
"""zone2 常规任务 —— 持续执行的自动化功能。

与 zone1 日常任务不同，zone2 任务没有「每天一次」的限制，
只要启用就会持续检查并执行。

操作码来源：_ops.json（DEX 逆向产物）
"""
import struct

RESP_DELTA = 0x7000

# type -> (op, 构造载荷函数, 中文名, 检查间隔秒数)
# 检查间隔：避免频繁发包，每个功能有自己的冷却时间
TASKS = {}


def _构造兑换载荷(cfg, character):
    """AUTO_EXCHANGE: 粮转铜

    当铜钱 < copperThreshold 万时，用粮食兑换铜钱。
    协议：op 4434 reqExchange
    载荷格式：需要抓包确认，先尝试简单格式
    """
    threshold = int(cfg.get("copperThreshold", 20)) * 10000
    copper = int(character.get("copper", 0) or 0)
    food = int(character.get("food", 0) or 0)

    # 铜钱足够，无需兑换
    if copper >= threshold:
        return None

    # 粮食不足（至少留 1 万粮食）
    if food < 10000:
        return None

    # 简单载荷：前导 0x0000 + 可能的兑换类型/数量
    # 需要实测验证格式
    return b"\x00\x00"


TASKS["AUTO_EXCHANGE"] = (4434, _构造兑换载荷, "粮转铜", 60)


def 执行(client, cfg, character, log):
    """执行 zone2 常规任务。

    character: 角色资源信息（copper, food 等）
    返回成功执行的 type 列表
    """
    执行完成 = []

    for row in (cfg.get("zone2") or []):
        if not isinstance(row, dict) or not row.get("enabled"):
            continue

        t = row.get("type")
        if t not in TASKS:
            continue

        op, 构造载荷, name, _ = TASKS[t]

        try:
            # 构造载荷（可能返回 None 表示不需要执行）
            payload = 构造载荷(row, character)
            if payload is None:
                continue

            # 发包
            pk = client.send_ops([(op, payload)])

            # 检查响应
            want = op + RESP_DELTA
            hit = any(p.get("op") == want for p in (pk or []))

            if hit:
                log("[常规] ✓ %s 完成" % name)
                执行完成.append(t)
            else:
                got = [p.get("op") for p in (pk or [])]
                log("[常规] ✗ %s 无预期应答（期望%d，实得%s）" % (
                    name, want, got or "无包"))
        except Exception as e:
            log("[常规] %s 失败: %s" % (name, e))

    return 执行完成
