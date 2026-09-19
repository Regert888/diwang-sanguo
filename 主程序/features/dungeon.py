# -*- coding: utf-8 -*-
"""副本板块（扫描 + 出征）。

★ 与刷黄（thief.py）完全同构，只改了 3 处：
  ① op 5440 → 5442（扫描）
  ② op 5410 → 5412（出征）
  ③ type "THIEF" → "DUNGEON"
"""
import time
import struct


def _副本锚点序列(bot, cx, cy):
    """生成 6×6 锚点坐标，从中心向外一圈圈铺开。

    ★ 与山贼共用同一套锚点序列（步长 = 6）。
    """
    STEP = 6
    w = int(getattr(bot.client, "map_w", 0) or 0) or 187
    h = int(getattr(bot.client, "map_h", 0) or 0) or 56
    if cx <= 0 or cy <= 0:          # 未配置中心 → 从地图中心开始
        cx, cy = w // 2, h // 2
    pts = []
    for r in range(max(w, h) // STEP + 2):
        if r == 0:
            ring = [(0, 0)]
        else:                        # 第 r 圈（切比雪夫环）
            ring = [(d, -r) for d in range(-r, r + 1)]
            ring += [(d, r) for d in range(-r, r + 1)]
            ring += [(-r, d) for d in range(-r + 1, r)]
            ring += [(r, d) for d in range(-r + 1, r)]
        for dx, dy in ring:
            x, y = cx + dx * STEP, cy + dy * STEP
            if 0 <= x < w and 0 <= y < h:
                pts.append((x, y))
    return pts


def _翻页找副本(bot, lv, 已打, 已打坐标, cx, cy, 最多翻页=15):
    """刷新副本：一次翻一页（一个锚点＝一个 5442 包），
    命中符合等级的就【立刻返回】，没有就翻下一页。

    游标 _du_i 跨轮持久化，避免每次都从同一片区域重新翻。
    """
    from core.king_client import 扫描副本
    pts = getattr(bot, "_du_pts", None)
    if not pts:
        pts = _副本锚点序列(bot, cx, cy)
        bot._du_pts = pts
    if not pts:
        return None, 0
    i0 = getattr(bot, "_du_i", 0)
    翻过 = 0
    for k in range(min(最多翻页, len(pts))):
        i = (i0 + k) % len(pts)
        x, y = pts[i]
        翻过 = k + 1
        try:
            fs = 扫描副本(bot.client, [(x, y)])    # ★ 一个请求只发一个包
        except Exception:
            continue
        for t in fs.values():
            if t.get("lvl") not in lv:
                continue
            if t["id"] in 已打 or (t["x"], t["y"]) in 已打坐标:
                continue
            bot._du_i = (i + 1) % len(pts)
            bot.log("[副本] 翻第%d页 锚点(%d,%d) → 命中 %s Lv%s 坐标(%d,%d)" % (
                翻过, x, y, t.get("name"), t.get("lvl"), t["x"], t["y"]))
            return t, 翻过
    bot._du_i = (i0 + 翻过) % len(pts)
    return None, 翻过


def 执行(bot, cfg):
    """副本：刷新一页副本 → 有符合等级的就出征 → 没有就翻下一页。

    ★ 与刷黄同构（op 5442 扫描，op 5412 出征）。
    """
    try:
        from core.king_client import 出征打副本
        now = time.time()
        if now - getattr(bot, "_du_last", 0) < 15:
            return
        bot._du_last = now

        dg_cfg = cfg.get("dungeonGlobal") or {}
        cx = int(dg_cfg.get("centerX", 0) or 0)
        cy = int(dg_cfg.get("centerY", 0) or 0)

        # ---- 1) 读启用的副本编队（zone3 / type=DUNGEON）
        队 = []
        for t in (cfg.get("zone3") or []):
            if t.get("type") != "DUNGEON" or not t.get("enabled"):
                continue
            gids = t.get("generalIds") or []
            lvs = set(int(v) for v in (t.get("dungeonLevels") or []) if str(v).isdigit())
            if gids and lvs:
                队.append({"generalIds": [int(x) for x in gids], "levels": lvs})
        if not 队:
            bot.log("[副本] 未配置启用的副本编队（军事→副本 里设置）")
            return
        lv = 队[0]["levels"]

        # ---- 2) 找所有空闲编队（支持多队并行出征）
        武将表 = {g.get("genId"): g for g in bot.generals}
        可用队列 = []
        全忙原因 = []
        for t in 队:
            sts = [武将表.get(g) for g in t["generalIds"]]
            if any(x is None for x in sts):
                continue
            if not all((x.get("statusText") or "待命") == "待命" for x in sts):
                全忙原因.append("非待命")
                continue
            if any(int(x.get("soldierCount", 0) or 0) < 1 for x in sts):
                全忙原因.append("%s无兵" % sts[0].get("name", "?"))
                continue
            if any(int(x.get("curHp", 0) or 0) < 1 for x in sts):
                全忙原因.append("%s体力0" % sts[0].get("name", "?"))
                continue
            可用队列.append(t)
        if not 可用队列:
            bot.log("[副本] 编队未就绪（%s），等待返回" % "/".join(全忙原因 or ["未知"]))
            return

        # ---- 3+4+5) ★ 刷新一页 → 有符合的就出征，没有就翻下一页
        已打 = {k: v for k, v in getattr(bot, "_du_done", {}).items() if now - v < 900}
        bot._du_done = 已打
        已打坐标 = {k: v for k, v in getattr(bot, "_du_xy", {}).items() if now - v < 900}
        bot._du_xy = 已打坐标

        # ---- 6+7+8) 为每个空闲编队翻页找目标并出征
        dispatched = 0
        总翻页 = 0
        for 可用队 in 可用队列:
            目标, 用页数 = _翻页找副本(bot, lv, 已打, 已打坐标, cx, cy)
            总翻页 += 用页数
            if 目标 is None:
                bot.log("[副本] 翻了%d页仍无符合等级%s的副本（已打%d）" % (
                    总翻页, sorted(lv), len(已打)))
                break
            已打坐标[(目标["x"], 目标["y"])] = now
            # 出征
            for gid in 可用队["generalIds"]:
                w = 武将表.get(gid, {})
                bot.log("[副本] 出征 → %s Lv%d 坐标(%d,%d) | %s 体力%d/%d 兵%d" % (
                    目标["name"], 目标["lvl"], 目标["x"], 目标["y"],
                    w.get("name", "?"), w.get("curHp", 0), w.get("maxHp", 0),
                    w.get("soldierCount", 0)))
            try:
                r = 出征打副本(bot.client, 可用队["generalIds"], 目标["id"])
                已打[目标["id"]] = now
                bot._du_xy[(目标["x"], 目标["y"])] = now
                bot._force_full_at = time.time() + 4
                出征成功 = False
                resp_op = 5412 + 0x7000
                出征码 = None
                出征消息 = ""
                for p in (r or []):
                    if p.get("op") == resp_op and p.get("data") and len(p["data"]) >= 1:
                        d = p["data"]
                        出征码 = struct.unpack_from(">b", d, 0)[0]
                        if len(d) >= 3:
                            try:
                                mlen = struct.unpack_from(">H", d, 1)[0]
                                if 1 <= mlen <= 200 and 3 + mlen <= len(d):
                                    出征消息 = d[3:3+mlen].decode("utf-8", "replace")
                            except Exception:
                                pass
                        出征成功 = (出征码 == 0)
                        break
                if 出征成功:
                    bot.log("[副本] ✓ 已出征，行军至 (%d,%d)" % (目标["x"], 目标["y"]))
                    for gen in getattr(bot, "generals", []):
                        if gen.get("genId") in 可用队["generalIds"]:
                            gen["statusText"] = "行军中"
                    dispatched += 1
                elif r:
                    raw_hex = ""
                    for p in r:
                        if p.get("op") == resp_op and p.get("data"):
                            raw_hex = p["data"][:32].hex()
                            break
                    bot.log("[副本] ✗ 出征被拒 code=%s msg='%s' raw=%s | 响应包数=%d" % (
                        出征码, 出征消息, raw_hex, len(r)))
                else:
                    bot.log("[副本] ✗ 出征无响应")
            except Exception as ex:
                bot.log("[副本] ✗ 出征失败: %s" % ex)
    except Exception as e:
        bot.log("[副本] 异常: %s" % e)
