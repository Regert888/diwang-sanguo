# -*- coding: utf-8 -*-
"""zone2 常规任务 —— 持续执行的自动化功能。

与 zone1 日常任务不同，zone2 任务没有「每天一次」的限制，
只要启用就会持续检查并执行。

新增一类常规任务只需往 TASKS 里加一行。

操作码来源：_ops.json（DEX 逆向产物）
"""
from app.feature import Feature

RESP_DELTA = 0x7000


def _构造兑换载荷(row, character):
    """AUTO_EXCHANGE: 粮转铜

    当铜钱 < copperThreshold 万时，用粮食兑换铜钱。
    协议：op 4434 reqExchange
    返回 None 表示本轮无需执行。

    ⚠ 载荷格式未经真机抓包验证。
    """
    threshold = int(row.get("copperThreshold", 20)) * 10000
    copper = int(character.get("copper", 0) or 0)
    food = int(character.get("food", 0) or 0)

    if copper >= threshold:
        return None            # 铜钱足够
    if food < 10000:
        return None            # 粮食不足（至少留 1 万）

    return b"\x00\x00"


# type -> (op, 构造载荷函数, 中文名)
TASKS = {
    "AUTO_EXCHANGE": (4434, _构造兑换载荷, "粮转铜"),
}


class RoutineFeature(Feature):
    NAME = "常规任务"
    TYPE = None          # 自己遍历 zone2 的多个 type
    ZONE = "zone2"
    INTERVAL = 60
    ORDER = 40           # 刷黄(30) 之后
    REQUIRES = ()

    @classmethod
    def rows(cls, cfg):
        """取整个 zone2 —— 本 Feature 自己按 TASKS 分派，不靠单一 TYPE 过滤。"""
        return [z for z in (cfg.get("zone2") or []) if isinstance(z, dict)]

    def run(self, ctx, rows):
        character = ctx.bot.character or {}
        做完 = []

        for row in rows:
            if not isinstance(row, dict) or not row.get("enabled"):
                continue

            t = row.get("type")
            if t not in TASKS:
                continue

            op, 构造载荷, name = TASKS[t]

            try:
                payload = 构造载荷(row, character)
                if payload is None:
                    continue       # 条件不满足，本轮跳过

                pk = ctx.client.send_ops([(op, payload)])

                want = op + RESP_DELTA
                if any(p.get("op") == want for p in (pk or [])):
                    ctx.log("[常规] ✓ %s 完成" % name)
                    做完.append(t)
                else:
                    got = [p.get("op") for p in (pk or [])]
                    ctx.log("[常规] ✗ %s 无预期应答（期望%d，实得%s）" % (
                        name, want, got or "无包"))
            except Exception as e:
                ctx.log("[常规] %s 失败: %s" % (name, e))

        return bool(做完)
