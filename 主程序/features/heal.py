# -*- coding: utf-8 -*-
"""伤兵板块（查询 + 自动治疗）。

★ 原样搬运自 server.py（2026-09-17 实测版本），
  仅把方法的 self 改为 bot 参数，逻辑一字未动。
"""


def 查伤兵(bot):
    """主动向服务器查询实时伤兵数据（不再依赖 login_packets 旧数据）"""
    from core.king_client import 刷新伤兵
    if not bot.client:
        return
    fiefs = 刷新伤兵(bot.client)
    if not fiefs:
        bot.log("[伤兵] 查询无数据（op4368 未返回有效封地）")
        return
    bot._伤兵表_raw = fiefs
    seq伤兵 = {}
    for fid, info in fiefs.items():
        for seq, cnt in info.get("wounded", []):
            if cnt > 0:
                seq伤兵[seq] = seq伤兵.get(seq, 0) + cnt
    bot._伤兵总数 = sum(seq伤兵.values())
    seq到将 = {}
    for gid, (s, _c) in getattr(bot, "_部队表", {}).items():
        seq到将.setdefault(s, []).append(gid)
    伤兵 = {}
    for seq, cnt in seq伤兵.items():
        gids = seq到将.get(seq)
        if gids:
            伤兵[gids[0]] = 伤兵.get(gids[0], 0) + cnt
    bot._伤兵表 = 伤兵
    if bot._伤兵总数 > 0:
        bot.log("[伤兵] 查到 %d 伤兵（封地%d个 兵种%s）" % (
            bot._伤兵总数, len(fiefs), dict(seq伤兵)))


def 治疗伤兵(bot, cfg):
    """自动治疗伤兵（读配置 zone2 里 type=HEAL_SOLDIER 的 enabled）
    用封地 fiefId + 兵种 seq 发 op 4656 治疗。
    """
    from core.king_client import 治疗伤兵 as _治疗伤兵
    # ★ Bug2 修复：从 zone2 数组里找 type=HEAL_SOLDIER
    heal_cfg = None
    for z in (cfg.get("zone2") or []):
        if isinstance(z, dict) and z.get("type") == "HEAL_SOLDIER":
            heal_cfg = z
            break
    if not heal_cfg or not heal_cfg.get("enabled"):
        if getattr(bot, "_伤兵总数", 0) > 0 and not getattr(bot, "_heal_warn", False):
            bot.log("[治疗] ⚠ 有%d伤兵但自动治疗未开启（前端→伤兵治疗→开关）" % bot._伤兵总数)
            bot._heal_warn = True
        return
    if not bot.client:
        return
    伤兵raw = getattr(bot, "_伤兵表_raw", {})
    if not 伤兵raw:
        return
    for fid, info in 伤兵raw.items():
        for seq, cnt in info.get("wounded", []):
            if cnt <= 0:
                continue
            try:
                r = _治疗伤兵(bot.client, fid, soldier_type=seq, count=cnt)
                if r and r.get("ok"):
                    bot.log("[治疗] ✓ 封地%d 兵种%d ×%d 已治疗" % (fid, seq, cnt))
                elif r:
                    bot.log("[治疗] ✗ %s" % r.get("msg", "失败"))
            except Exception as e:
                bot.log("[治疗] 异常: %s" % e)
