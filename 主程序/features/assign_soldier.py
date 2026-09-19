# -*- coding: utf-8 -*-
"""配兵功能 —— 自动补兵到配置的兵种/数量。

迁移自 features/military.py 的 自动配兵()。
"""
import time
from app.feature import Feature, Ctx


出征最低兵力 = 1200
冲车最低兵力 = 200
冲车seq = 5


class AssignSoldier(Feature):
    NAME = "自动配兵"
    TYPE = "ASSIGN_SOLDIER"
    ZONE = "zone3"
    INTERVAL = 10
    ORDER = 10
    REQUIRES = ("generals",)

    def run(self, ctx: Ctx, rows):
        """按配置补兵。

        每个武将 60 秒内最多补一次。
        连续 3 次空应答视为会话失效，暂停。
        """
        from core.king_client import 配兵 as _配兵, 解析配兵应答

        # 提取启用的配置行
        行 = []
        for z in rows:
            if not z.get("enabled"):
                continue
            seq = ctx.兵种seq(z.get("soldierType"))
            if seq is None:
                continue
            try:
                cnt = int(z.get("count") or 0)
            except Exception:
                cnt = 0
            for gid in (z.get("generalIds") or []):
                try:
                    行.append((int(gid), seq, cnt))
                except Exception:
                    continue

        if not 行:
            return False

        # 会话失效保护
        dead_count = ctx.cooldowns.get("assign_soldier_dead", 0)
        if dead_count >= 3:
            return False

        bot = ctx.bot
        now = time.time()
        success = False

        for gid, seq, cnt in 行:
            # 检查是否已符合配置
            当前 = bot._部队表.get(gid)
            if 当前 and 当前[0] == seq and 当前[1] == cnt:
                continue

            # 冷却检查（60秒/将）
            if not ctx.cooldowns.check(f"assign_{gid}", 60):
                continue

            # 发送配兵请求
            try:
                r = 解析配兵应答(_配兵(ctx.client, gid, seq, cnt))
            except Exception as e:
                ctx.log(f"[自动配兵] 异常: {e}")
                dead_count += 1
                ctx.cooldowns.set("assign_soldier_dead", dead_count)
                continue

            # 记录本次尝试时间
            ctx.cooldowns.set(f"assign_{gid}")

            if r.get("ok"):
                # 成功：重置失败计数
                ctx.cooldowns.set("assign_soldier_dead", 0)

                # ★ 关键：直接更新原子数据（_部队表）
                #   投影架构下不需要再调用 _同步部队到前端()
                if r.get("newCount"):
                    bot._部队表[gid] = (r.get("newSeq") or seq, r["newCount"])
                else:
                    bot._部队表.pop(gid, None)

                ctx.log(f"[自动配兵] 武将{gid} → {seq} × {cnt}（{r.get('oldCount')}→{r.get('newCount')}）")
                success = True

            elif not (r.get("raw") or ""):
                # 空应答：会话可能失效
                dead_count += 1
                ctx.cooldowns.set("assign_soldier_dead", dead_count)
                ctx.log(f"[自动配兵] 无应答（{dead_count}/3），会话可能已失效")

                if dead_count >= 3:
                    ctx.log("[自动配兵] 已暂停：会话失效，请在页面上重新启动账号")
                    return False

            else:
                # 其他错误
                ctx.cooldowns.set("assign_soldier_dead", 0)
                ctx.log(f"[自动配兵] 失败 武将{gid} (应答 {(r.get('raw') or '')[:30]})")

        return success


def 配兵配置(bot, cfg, 兵种seq函数):
    """账号配置 zone3 里的配兵表 → {武将ID: {"seq","count","enabled"}}

    这是工具函数，供其他功能（如刷黄）调用，检查出征资格。
    """
    out = {}
    for z in (cfg.get("zone3") or []):
        if not isinstance(z, dict):
            continue
        if (z.get("type") or "ASSIGN_SOLDIER") != "ASSIGN_SOLDIER":
            continue
        seq = 兵种seq函数(z.get("soldierType"))
        try:
            cnt = int(z.get("count") or 0)
        except Exception:
            cnt = 0
        for gid in (z.get("generalIds") or []):
            try:
                out[int(gid)] = {"seq": seq, "count": cnt,
                                 "enabled": bool(z.get("enabled"))}
            except Exception:
                continue
    return out


def 检查出征资格(bot, cfg, 兵种seq函数, 武将ID):
    """商辅规则：① 必须在配兵列表启用 ② 兵力不低于 1200(冲车 200)。

    返回 (是否可出征, 原因)。出征类功能派将前调用它即可。
    """
    try:
        武将ID = int(武将ID)
    except Exception:
        return False, "无效武将ID"
    row = 配兵配置(bot, cfg, 兵种seq函数).get(武将ID)
    if not row:
        return False, "未在配兵列表配置"
    if not row.get("enabled"):
        return False, "配兵列表中未打勾启用"
    当前 = bot._部队表.get(武将ID)
    cnt = 当前[1] if 当前 else 0
    门槛 = 冲车最低兵力 if row.get("seq") == 冲车seq else 出征最低兵力
    if cnt < 门槛:
        return False, f"兵力不足 {门槛}（当前 {cnt}）"
    return True, "可出征"
