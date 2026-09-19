# -*- coding: utf-8 -*-
"""刷黄功能 —— 山贼扫描 + 出征。

★ 从旧版 thief.py 改造成 Feature 类
★ 增加武将锁定机制（state.claim），防止多功能同时派遣同一武将
"""
import time
import struct
from app.feature import Feature


class ThiefFeature(Feature):
    NAME = "刷黄"
    TYPE = "THIEF"
    ZONE = "zone3"
    GLOBAL_KEY = "thiefGlobal"
    INTERVAL = 15       # 15秒检查一次（原来是 _sh_last 冷却）
    ORDER = 30          # 低于配兵（10），高于伤兵（50）
    REQUIRES = ("generals",)
    DAILY = False

    def __init__(self):
        super().__init__()
        # 状态：锚点列表、游标、已打列表
        self._pts = []       # 锚点序列
        self._i = 0          # 当前游标
        self._done = {}      # {山贼ID: 时间戳}
        self._xy = {}        # {(x,y): 时间戳}

    def _山贼锚点序列(self, bot, cx, cy):
        """生成 6×6 锚点坐标，从中心向外一圈圈铺开。

        ★ 真机抓包（刷新山贼.har）实证：op 5440 载荷 (0,x,y) 里的 x,y 是
          【地图坐标】不是页码，锚点步长 = 6（每个锚点覆盖 [x,x+5]×[y,y+5]）。
        """
        STEP = 6
        w = int(getattr(bot.client, "map_w", 0) or 0) or 187
        h = int(getattr(bot.client, "map_h", 0) or 0) or 56
        if cx <= 0 or cy <= 0:
            cx, cy = w // 2, h // 2
        pts = []
        for r in range(max(w, h) // STEP + 2):
            if r == 0:
                ring = [(0, 0)]
            else:
                ring = [(d, -r) for d in range(-r, r + 1)]
                ring += [(d, r) for d in range(-r, r + 1)]
                ring += [(-r, d) for d in range(-r + 1, r)]
                ring += [(r, d) for d in range(-r + 1, r)]
            for dx, dy in ring:
                x, y = cx + dx * STEP, cy + dy * STEP
                if 0 <= x < w and 0 <= y < h:
                    pts.append((x, y))
        return pts

    def _翻页找山贼(self, ctx, lv, cx, cy, 最多翻页=15):
        """刷新山贼：一次翻一页，命中符合等级的就立刻返回。

        游标 self._i 跨轮持久化，避免每次都从同一片区域重新翻。
        """
        from core.king_client import 扫描山贼

        if not self._pts:
            self._pts = self._山贼锚点序列(ctx.bot, cx, cy)
        if not self._pts:
            return None, 0

        now = time.time()
        # 清理过期记录（15分钟）
        self._done = {k: v for k, v in self._done.items() if now - v < 900}
        self._xy = {k: v for k, v in self._xy.items() if now - v < 900}

        翻过 = 0
        for k in range(min(最多翻页, len(self._pts))):
            i = (self._i + k) % len(self._pts)
            x, y = self._pts[i]
            翻过 = k + 1
            try:
                fs = 扫描山贼(ctx.client, [(x, y)])
            except Exception as e:
                ctx.log("[刷黄] 扫描锚点(%d,%d)失败: %s" % (x, y, e))
                continue
            for t in fs.values():
                if t.get("lvl") not in lv:
                    continue
                if t["id"] in self._done or (t["x"], t["y"]) in self._xy:
                    continue
                self._i = (i + 1) % len(self._pts)
                ctx.log("[刷黄] 翻第%d页 锚点(%d,%d) → 命中 %s Lv%s 坐标(%d,%d)" % (
                    翻过, x, y, t.get("name"), t.get("lvl"), t["x"], t["y"]))
                return t, 翻过
        self._i = (self._i + 翻过) % len(self._pts)
        return None, 翻过

    def run(self, ctx, rows):
        """刷黄主逻辑：刷新一页山贼 → 有符合等级的就出征 → 没有就翻下一页。

        Args:
            rows: zone3 里所有 type=THIEF 的配置行
        """
        from core.king_client import 出征打山贼

        # 读取全局配置（中心坐标）
        gcfg = ctx.gcfg or {}
        cx = int(gcfg.get("centerX", 0) or 0)
        cy = int(gcfg.get("centerY", 0) or 0)

        # 1) 解析启用的刷黄编队
        队 = []
        for row in rows:
            gids = row.get("generalIds") or []
            lvs = set(int(v) for v in (row.get("thiefLevels") or []) if str(v).isdigit())
            if gids and lvs:
                队.append({"generalIds": [int(x) for x in gids], "levels": lvs})
        if not 队:
            return False
        lv = 队[0]["levels"]

        # 2) 找所有空闲编队（支持多队并行出征）
        武将表 = {g.get("genId"): g for g in ctx.bot.generals}
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

            # ★ 武将锁定：尝试锁定这支队伍的所有武将（120秒）
            if not ctx.state.claim(t["generalIds"], ttl=120):
                全忙原因.append("武将被占用")
                continue

            可用队列.append(t)

        if not 可用队列:
            if 全忙原因:
                ctx.log("[刷黄] 编队未就绪（%s），等待返回" % "/".join(全忙原因))
            return False

        # 3) 为每个空闲编队翻页找目标并出征
        dispatched = 0
        总翻页 = 0
        now = time.time()

        for 可用队 in 可用队列:
            目标, 用页数 = self._翻页找山贼(ctx, lv, cx, cy)
            总翻页 += 用页数
            if 目标 is None:
                ctx.log("[刷黄] 翻了%d页仍无符合等级%s的山贼（已打%d）" % (
                    总翻页, sorted(lv), len(self._done)))
                break

            self._xy[(目标["x"], 目标["y"])] = now

            # 出征前日志
            for gid in 可用队["generalIds"]:
                w = 武将表.get(gid, {})
                ctx.log("[刷黄] 出征 → %s Lv%d 坐标(%d,%d) | %s 体力%d/%d 兵%d" % (
                    目标["name"], 目标["lvl"], 目标["x"], 目标["y"],
                    w.get("name", "?"), w.get("curHp", 0), w.get("maxHp", 0),
                    w.get("soldierCount", 0)))

            try:
                r = 出征打山贼(ctx.client, 可用队["generalIds"], 目标["id"])
                self._done[目标["id"]] = now

                # ★ 请求全量刷新（4秒后，同步武将状态）
                ctx.bus.request("full_refresh", 4)

                # 解析出征结果
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
                    ctx.log("[刷黄] ✓ 已出征，行军至 (%d,%d)" % (目标["x"], 目标["y"]))
                    dispatched += 1
                elif r:
                    raw_hex = ""
                    for p in r:
                        if p.get("op") == resp_op and p.get("data"):
                            raw_hex = p["data"][:32].hex()
                            break
                    ctx.log("[刷黄] ✗ 出征被拒 code=%s msg='%s' raw=%s | 响应包数=%d" % (
                        出征码, 出征消息, raw_hex, len(r)))
                else:
                    ctx.log("[刷黄] ✗ 出征无响应")
            except Exception as ex:
                ctx.log("[刷黄] ✗ 出征失败: %s" % ex)

        return dispatched > 0
