# -*- coding: utf-8 -*-
"""副本板块（扫描副本 + 出征打副本）。

★ 参照 thief.py（刷黄）的单页翻页架构，改 3 行就能工作：
  1. 扫描山贼 op 5440 → 扫描副本 op 5442
  2. 出征打山贼 op 5410 → 出征打副本 op 5412
  3. 锚点序列 → 副本有固定坐标，不需要螺旋扫描（从配置直接读）

★ 副本规则（逆自前端说明文字 + 真机抓包）：
    ① 将领必须先在「配兵列表」启用，否则禁止出征
    ② 兵力低于 1200（冲车 200）的将，限制出征
    ③ 出征前把兵补齐到配置的兵种/数量
    ④ 副本有固定坐标（150,30）等，从配置读取
"""
import time
import struct


def 执行(bot, cfg):
    """打副本：扫描副本 → 有符合等级的就出征 → 没有就等下一轮。

    与刷黄的唯一区别：
      - 副本坐标固定（从 instanceGlobal 读），不需要螺旋扫描
      - 扫描 op 5442 / 出征 op 5412
    """
    try:
        from core.king_client import 出征打副本
        now = time.time()
        if now - getattr(bot, "_inst_last", 0) < 15:
            return
        bot._inst_last = now

        # ---- 1) 读启用的副本编队（zone4 / type=INSTANCE）
        队 = []
        for t in (cfg.get("zone4") or []):
            if t.get("type") != "INSTANCE" or not t.get("enabled"):
                continue
            gids = t.get("generalIds") or []
            lvs = set(int(v) for v in (t.get("instanceLevels") or []) if str(v).isdigit())
            if gids and lvs:
                队.append({"generalIds": [int(x) for x in gids], "levels": lvs})
        if not 队:
            bot.log("[副本] 未配置启用的副本编队（军事→副本 里设置）")
            return
        lv = 队[0]["levels"]

        # ---- 2) 找所有空闲编队
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

        # ---- 3) 扫描副本（固定坐标，从 instanceGlobal 读取）
        inst_cfg = cfg.get("instanceGlobal") or {}
        坐标列表 = inst_cfg.get("coordinates") or []  # 例如 [[150,30], [151,30]]
        if not 坐标列表:
            bot.log("[副本] 未配置副本坐标（军事→副本→全局设置）")
            return

        已打 = {k: v for k, v in getattr(bot, "_inst_done", {}).items() if now - v < 900}
        bot._inst_done = 已打
        已打坐标 = {k: v for k, v in getattr(bot, "_inst_xy", {}).items() if now - v < 900}
        bot._inst_xy = 已打坐标

        # ---- 4) 为每个空闲编队找目标并出征
        from core.king_client import 扫描副本
        dispatched = 0
        for 可用队 in 可用队列:
            目标 = None
            for xy in 坐标列表:
                if not isinstance(xy, (list, tuple)) or len(xy) < 2:
                    continue
                x, y = int(xy[0]), int(xy[1])
                if (x, y) in 已打坐标:
                    continue
                try:
                    fs = 扫描副本(bot.client, [(x, y)])
                except Exception:
                    continue
                for t in fs.values():
                    if t.get("lvl") not in lv:
                        continue
                    if t["id"] in 已打 or (t["x"], t["y"]) in 已打坐标:
                        continue
                    目标 = t
                    break
                if 目标:
                    break
            if 目标 is None:
                bot.log("[副本] 无符合等级%s的副本（已打%d）" % (sorted(lv), len(已打)))
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
                bot._inst_xy[(目标["x"], 目标["y"])] = now
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
