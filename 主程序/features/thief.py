# -*- coding: utf-8 -*-
"""刷黄板块（山贼扫描 + 出征）。

★ 原样搬运自 server.py（2026-09-17 实测「✓ 已出征」版本），
  仅把方法的 self 改为 bot 参数，逻辑一字未动。
★ 状态（锚点游标/已打列表）仍挂在 bot 会话对象上，每账号独立。
"""
import time
import struct


def _山贼锚点序列(bot, cx, cy):
    """生成 6×6 锚点坐标，从中心向外一圈圈铺开。

    ★ 真机抓包（刷新山贼.har）实证：op 5440 载荷 (0,x,y) 里的 x,y 是
      【地图坐标】不是页码，锚点步长 = 6（每个锚点覆盖 [x,x+5]×[y,y+5]）。
      抓到的真机序列：(123,30)→(117,30)→(117,36)→(123,36)，x/y 差值都是 6。
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


def _翻页找山贼(bot, lv, 已打, 已打坐标, cx, cy, 最多翻页=15):
    """刷新山贼：一次翻一页（一个锚点＝一个 5440 包），
    命中符合等级的就【立刻返回】，没有就翻下一页。

    这样出征紧跟在刷新之后发出，山贼 ID 还是新鲜的 —— 旧实现先扫全图
    （120 包/请求 × 很多轮，拿到 8 万个山贼）再出征，ID 早就失效了，
    服务端回 code=-28。

    游标 _sh_i 跨轮持久化，避免每次都从同一片区域重新翻。
    """
    from core.king_client import 扫描山贼
    pts = getattr(bot, "_sh_pts", None)
    if not pts:
        pts = _山贼锚点序列(bot, cx, cy)
        bot._sh_pts = pts
    if not pts:
        return None, 0
    i0 = getattr(bot, "_sh_i", 0)
    翻过 = 0
    for k in range(min(最多翻页, len(pts))):
        i = (i0 + k) % len(pts)
        x, y = pts[i]
        翻过 = k + 1
        try:
            fs = 扫描山贼(bot.client, [(x, y)])    # ★ 一个请求只发一个包
        except Exception:
            continue
        for t in fs.values():
            if t.get("lvl") not in lv:
                continue
            if t["id"] in 已打 or (t["x"], t["y"]) in 已打坐标:
                continue
            bot._sh_i = (i + 1) % len(pts)
            bot.log("[刷黄] 翻第%d页 锚点(%d,%d) → 命中 %s Lv%s 坐标(%d,%d)" % (
                翻过, x, y, t.get("name"), t.get("lvl"), t["x"], t["y"]))
            return t, 翻过
    bot._sh_i = (i0 + 翻过) % len(pts)
    return None, 翻过


def 执行(bot, cfg):
    """刷黄：刷新一页山贼 → 有符合等级的就出征 → 没有就翻下一页。

    ★ 真机抓包（刷新山贼.har）修正的认知：
      · op5440 一个请求只发【一个】包，载荷 (0,x,y) 的 x,y 是【地图坐标】
      · 每个锚点覆盖 6×6 区域，锚点步长 = 6
      · 旧代码把 (x,y) 当分页参数批量发 120 包扫全图，拿到 8 万个山贼后
        再出征，此时 ID 已失效 → 服务端回 code=-28
    """
    try:
        from core.king_client import 出征打山贼
        now = time.time()
        if now - getattr(bot, "_sh_last", 0) < 15:
            return
        bot._sh_last = now

        tg_cfg = cfg.get("thiefGlobal") or {}
        cx = int(tg_cfg.get("centerX", 0) or 0)
        cy = int(tg_cfg.get("centerY", 0) or 0)

        # ---- 1) 读启用的刷黄编队（zone3 / type=THIEF）
        队 = []
        for t in (cfg.get("zone3") or []):
            if t.get("type") != "THIEF" or not t.get("enabled"):
                continue
            gids = t.get("generalIds") or []
            lvs = set(int(v) for v in (t.get("thiefLevels") or []) if str(v).isdigit())
            if gids and lvs:
                队.append({"generalIds": [int(x) for x in gids], "levels": lvs})
        if not 队:
            bot.log("[刷黄] 未配置启用的刷黄编队（军事→刷黄 里设置）")
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
            bot.log("[刷黄] 编队未就绪（%s），等待返回" % "/".join(全忙原因 or ["未知"]))
            return

        # ---- 3+4+5) ★ 刷新一页 → 有符合的就出征，没有就翻下一页
        已打 = {k: v for k, v in getattr(bot, "_sh_done", {}).items() if now - v < 900}
        bot._sh_done = 已打
        已打坐标 = {k: v for k, v in getattr(bot, "_sh_xy", {}).items() if now - v < 900}
        bot._sh_xy = 已打坐标

        # ---- 6+7+8) 为每个空闲编队翻页找目标并出征
        dispatched = 0
        总翻页 = 0
        for 可用队 in 可用队列:
            目标, 用页数 = _翻页找山贼(bot, lv, 已打, 已打坐标, cx, cy)
            总翻页 += 用页数
            if 目标 is None:
                bot.log("[刷黄] 翻了%d页仍无符合等级%s的山贼（已打%d）" % (
                    总翻页, sorted(lv), len(已打)))
                break
            已打坐标[(目标["x"], 目标["y"])] = now
            # 出征
            for gid in 可用队["generalIds"]:
                w = 武将表.get(gid, {})
                bot.log("[刷黄] 出征 → %s Lv%d 坐标(%d,%d) | %s 体力%d/%d 兵%d" % (
                    目标["name"], 目标["lvl"], 目标["x"], 目标["y"],
                    w.get("name", "?"), w.get("curHp", 0), w.get("maxHp", 0),
                    w.get("soldierCount", 0)))
            try:
                r = 出征打山贼(bot.client, 可用队["generalIds"], 目标["id"])
                已打[目标["id"]] = now
                bot._sh_xy[(目标["x"], 目标["y"])] = now
                bot._force_full_at = time.time() + 4
                出征成功 = False
                resp_op = 5410 + 0x7000
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
                    bot.log("[刷黄] ✓ 已出征，行军至 (%d,%d)" % (目标["x"], 目标["y"]))
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
                    bot.log("[刷黄] ✗ 出征被拒 code=%s msg='%s' raw=%s | 响应包数=%d" % (
                        出征码, 出征消息, raw_hex, len(r)))
                else:
                    bot.log("[刷黄] ✗ 出征无响应")
            except Exception as ex:
                bot.log("[刷黄] ✗ 出征失败: %s" % ex)
    except Exception as e:
        bot.log("[刷黄] 异常: %s" % e)
