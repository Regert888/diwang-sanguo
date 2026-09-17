# -*- coding: utf-8 -*-
"""军事板块（配兵/出征资格）。

★ 原样搬运自 server.py（2026-09-17 实测「配兵成功」版本），
  仅把方法的 self 改为 bot 参数，逻辑一字未动。
★ 商辅规则（逆自前端说明文字）：
    ① 将领必须先在「配兵列表」启用，否则禁止出征
    ② 兵力低于 1200（冲车 200）的将，限制出征
    ③ 出征前把兵补齐到配置的兵种/数量
"""
import time

出征最低兵力 = 1200
冲车最低兵力 = 200
冲车seq = 5                     # 沖城車（见 兵种名表.json）


def 配兵配置(bot, cfg, 兵种seq):
    """账号配置 zone3 里的配兵表 → {武将ID: {"seq","count","enabled"}}"""
    out = {}
    for z in (cfg.get("zone3") or []):
        if not isinstance(z, dict):
            continue
        if (z.get("type") or "ASSIGN_SOLDIER") != "ASSIGN_SOLDIER":
            continue
        seq = 兵种seq(z.get("soldierType"))
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


def 检查出征资格(bot, cfg, 兵种seq, 武将ID):
    """商辅规则：① 必须在配兵列表启用 ② 兵力不低于 1200(冲车 200)。

    返回 (是否可出征, 原因)。出征类功能派将前调用它即可。
    """
    try:
        武将ID = int(武将ID)
    except Exception:
        return False, "无效武将ID"
    row = 配兵配置(bot, cfg, 兵种seq).get(武将ID)
    if not row:
        return False, "未在配兵列表配置"
    if not row.get("enabled"):
        return False, "配兵列表中未打勾启用"
    当前 = bot._部队表.get(武将ID)
    cnt = 当前[1] if 当前 else 0
    门槛 = 冲车最低兵力 if row.get("seq") == 冲车seq else 出征最低兵力
    if cnt < 门槛:
        return False, "兵力不足 %d（当前 %d）" % (门槛, cnt)
    return True, "可出征"


def 出征资格表(bot, cfg, 兵种seq):
    """所有已配置将领的出征资格，供前端/出征功能使用。"""
    out = []
    for gid, row in 配兵配置(bot, cfg, 兵种seq).items():
        ok, why = 检查出征资格(bot, cfg, 兵种seq, gid)
        当前 = bot._部队表.get(gid)
        out.append({"genId": gid, "seq": row.get("seq"), "count": row.get("count"),
                    "enabled": row.get("enabled"), "curCount": 当前[1] if 当前 else 0,
                    "canDispatch": ok, "reason": why})
    return out


def 自动配兵(bot, cfg, 兵种seq):
    """按账号配置 zone3(ASSIGN_SOLDIER) 自动补兵。

    每轮刷新检查：武将当前（兵种seq, 数量）与配置不符 → 发 op 4646 补齐/取消。
    同一武将 60 秒内最多补一次，避免刷屏和封号风险。
    """
    from core.king_client import 配兵 as _配兵, 解析配兵应答
    行 = []
    for z in (cfg.get("zone3") or []):
        if not isinstance(z, dict):
            continue
        if (z.get("type") or "ASSIGN_SOLDIER") != "ASSIGN_SOLDIER":
            continue
        if not z.get("enabled"):
            continue
        seq = 兵种seq(z.get("soldierType"))
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
        return
    # 会话失效保护：连续空应答说明掉线/被踢，暂停自动配兵，避免持续发无效包
    if bot._pb_dead >= 3:
        return
    now = time.time()
    for gid, seq, cnt in 行:
        当前 = bot._部队表.get(gid)
        if 当前 and 当前[0] == seq and 当前[1] == cnt:
            continue                                  # 已符合配置
        if now - bot._pb_last.get(gid, 0) < 60:
            continue                                  # 冷却中
        try:
            r = 解析配兵应答(_配兵(bot.client, gid, seq, cnt))
        except Exception as e:
            bot.log(f"[自动配兵] 异常: {e}")
            bot._pb_dead += 1
            continue
        bot._pb_last[gid] = now
        if r.get("ok"):
            bot._pb_dead = 0
            # ★ 关键：服务端可能只给增量包，界面数据不会自动更新。
            #   所以把应答里的新值直接写回本地，避免每轮白发一次配兵包。
            if r.get("newCount"):
                bot._部队表[gid] = (r.get("newSeq") or seq, r["newCount"])
            else:
                bot._部队表.pop(gid, None)
            bot._同步部队到前端()
            bot.log(f"[自动配兵] 武将{gid} → {seq} × {cnt}（{r.get('oldCount')}→{r.get('newCount')}）")
        elif not (r.get("raw") or ""):
            bot._pb_dead += 1
            bot.log(f"[自动配兵] 无应答（{bot._pb_dead}/3），会话可能已失效")
            if bot._pb_dead >= 3:
                bot.log("[自动配兵] 已暂停：会话失效，请在页面上重新启动账号")
                return
        else:
            bot._pb_dead = 0
            bot.log(f"[自动配兵] 失败 武将{gid} (应答 {(r.get('raw') or '')[:30]})")
