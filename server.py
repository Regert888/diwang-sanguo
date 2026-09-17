#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""帝王三国辅助 — 后端服务"""
import json, os, sys, threading, time, hashlib, urllib.request, struct, re
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

BASE = os.path.dirname(os.path.abspath(__file__))
WWW = os.path.join(BASE, "www")
ASSETS = os.path.join(BASE, "assets")
sys.path.insert(0, BASE)
from core.king_client import (
    取区服列表, 匹配区服, 进入游戏,
    解析武将列表, 解析宝藏,
    刷新伤兵, 治疗伤兵,
    查询军情
)

# ====== 区服列表缓存 ======
def load_regions():
    p = os.path.join(BASE, "regions_fanti.json")
    if os.path.isfile(p):
        try: return json.load(open(p, encoding="utf-8"))
        except: pass
    return []
REGIONS = load_regions()

# ====== 账号存储 ======
ACCOUNTS_FILE = os.path.join(BASE, "accounts.json")
_LOCK = threading.Lock()
CONFIGS_FILE = os.path.join(BASE, "configs.json")


def load_configs():
    try:
        with open(CONFIGS_FILE, encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


configs_db = load_configs()


def save_configs():
    try:
        with open(CONFIGS_FILE, "w", encoding="utf-8") as f:
            json.dump(configs_db, f, ensure_ascii=False, indent=1)
    except Exception:
        pass


# 配兵兵种名（★ 顺序 = 协议里的 seq 0-15，与商辅前端 dt 数组一致）
兵种名_seq = ["民兵", "弩兵", "弓兵", "轻骑兵", "弩车", "冲城车", "轻步兵", "近卫兵",
            "重步兵", "弩骑兵", "重骑兵", "铁骑兵", "投石车", "重弩车", "强弩兵", "骁骑兵"]
# 繁体别名（游戏内显示）
兵种名_seq_trad = ["民兵", "弩兵", "弓兵", "輕騎兵", "弩車", "沖城車", "輕步兵", "近衛兵",
                   "重步兵", "弩騎兵", "重騎兵", "鐵騎兵", "投石車", "重弩車", "強弩兵", "驍騎兵"]


def 兵种seq(名):
    """兵种名 → seq（0-15）。支持简体/繁体。"""
    n = str(名 or "").strip()
    if n in 兵种名_seq:
        return 兵种名_seq.index(n)
    if n in 兵种名_seq_trad:
        return 兵种名_seq_trad.index(n)
    try:
        v = int(n)
        if 0 <= v <= 15:
            return v
    except Exception:
        pass
    return 0


def load_accounts():
    if os.path.isfile(ACCOUNTS_FILE):
        try: return json.load(open(ACCOUNTS_FILE, encoding="utf-8"))
        except: pass
    return []
def save_accounts():
    with open(ACCOUNTS_FILE, "w", encoding="utf-8") as f:
        json.dump(accounts_db, f, ensure_ascii=False, indent=1)
accounts_db = load_accounts()
next_id = max([a.get("id", 0) for a in accounts_db] + [0]) + 1

# ====== Bot 会话管理 ======
class BotSession:
    """一个账号的运行会话，按商辅前端契约输出数据"""

    def __init__(self, account):
        self.acct_id = account["id"]
        self.client = None
        self.user = account["gameUsername"]
        self.pwd = account["gamePassword"]
        self.server_name = account.get("serverName", "")
        self.running = False
        self.status = 0                       # 0=停止 1=运行中 2=启动中 5=需验证
        self.last_error = ""
        self.last_access = ""
        self.start_time = 0
        self.logs = []                        # 字符串数组（前端 rn() 直接 push 显示）
        self.character = {}                   # 角色面板数据
        self.generals = []
        self.troops = []
        self._部队表 = {}
        self._pb_last = {}                    # 自动配兵冷却（武将ID → 上次时间）
        self._pb_dead = 0                     # 自动配兵连续无应答次数（≥3 暂停）
        self._eg_last = 0                     # 上次 enter_game 时间（60秒冷却）
        self.items = []
        try:
            import json as _json
            self._兵种名表 = _json.load(open(
                os.path.join(BASE, "兵种名表.json"), encoding="utf-8"))
        except Exception:
            self._兵种名表 = {}
        self._实时包 = None
        self._实时包时间 = 0
        self._lastRefresh = 0
        self._物品名表 = None
        self._hb_thread = None

    def log(self, msg):
        self.logs.append(f"[{time.strftime('%H:%M:%S')}] {msg}")
        if len(self.logs) > 300:
            self.logs = self.logs[-300:]

    def start(self):
        self.running = True
        self.status = 1
        self.start_time = time.time()
        self.last_access = time.strftime("%Y-%m-%d %H:%M:%S")
        self._start_heartbeat()

    def stop(self):
        self.running = False
        self.status = 0
        self._stopped_at = time.time()

    def _刷新角色(self):
        """重新拉取角色面板数据"""
        try:
            res = self.client.取角色资源()
            if res:
                self.character.update(res)
        except Exception as e:
            self.log(f"[调试] 刷新角色失败: {e}")

    def _抓状态(self):
        """op 12593 → roleStatuses (11条buff/debuff)"""
        try:
            pk = self.client.send_op(12593, b"\x00" * 16)
            for p in pk or []:
                if p["op"] - 28672 == 12593:
                    self.roleStatuses = self._解析状态(p["data"])
                    break
        except Exception as e:
            self.log(f"[调试] 取状态失败: {e}")

    @staticmethod
    def _解析状态(data):
        out = []
        if len(data) < 60:
            return out
        # 找记录起始：0b 00 0d ff ff = count=11 + 记录前缀
        pos = -1
        for o in range(len(data) - 4):
            if data[o:o+5] == b"\x0b\x00\x0d\xff\xff":
                pos = o + 1
                break
        if pos < 0:
            return out
        count = data[pos - 1]  # 0x0b
        for _ in range(count):
            if pos >= len(data):
                break
            # 跳过前缀字节，直到找到 utf8 串
            s = None
            for _ in range(40):
                if pos + 2 > len(data):
                    break
                ln = struct.unpack_from(">H", data, pos)[0]
                if 2 <= ln <= 300 and pos + 2 + ln <= len(data):
                    try:
                        s2 = data[pos+2:pos+2+ln].decode("utf-8")
                        if s2 and re.search(r"[\u4e00-\u9fff]", s2):
                            s = s2
                            pos += 2 + ln
                            break
                    except Exception:
                        pass
                pos += 1
            if not s:
                break
            rem = struct.unpack_from(">q", data, pos)[0]
            pos += 8
            active = data[pos] if pos < len(data) else 1
            pos += 1
            out.append({
                "desc": s,
                "remainingMs": rem,
                "active": active,
                "isProtect": "保護" in s or "保护" in s,
            })
        return out

    def _start_heartbeat(self):
        def _hb():
            while self.running:
                time.sleep(45)
                if not (self.client and self.running):
                    break
                try:
                    pk = self.client.send_op(25215, b"\x00")
                    for p in pk or []:
                        if p["signed"] in (-1, -3, -4, -5):
                            self.log("[警告] 账号已被踢下线")
                            self.running = False
                            self.status = 0
                            break
                except Exception as e:
                    self.log(f"[警告] 心跳失败: {e}")
                    self.running = False
                    self.status = 0

        def _refresh():
            """独立刷新线程：所有数据都是动态的，每 10 秒全量刷新 + 自动补兵"""
            time.sleep(3)
            while self.running:
                if not (self.client and self.running):
                    break
                try:
                    self._rfc = getattr(self, "_rfc", 0) + 1
                    # ★ 首轮立即强制取完整包（不等 120 秒），之后每 12 轮强制一次
                    强制 = (self._rfc == 1 or self._rfc % 12 == 0)
                    # ★ 出征/配兵后 4 秒强制完整刷新（同步武将状态）
                    if time.time() >= getattr(self, "_force_full_at", 0) > 0:
                        self._force_full_at = 0
                        强制 = True
                    self._全量刷新(强制完整=强制)
                except Exception as e:
                    self.log(f"[调试] 刷新失败: {e}")
                try:
                    self._自动配兵()
                except Exception as e:
                    self.log(f"[调试] 自动配兵失败: {e}")
                try:
                    self._刷黄()
                except Exception as e:
                    self.log(f"[调试] 刷黄失败: {e}")
                # ★ 伤兵查询 + 自动治疗（每 3 轮执行一次 ≈ 30 秒）
                if self._rfc % 3 == 0:
                    try:
                        self._查伤兵()
                        self._同步部队到前端()
                    except Exception as e:
                        self.log(f"[调试] 查伤兵失败: {e}")
                    try:
                        self._治疗伤兵()
                    except Exception as e:
                        self.log(f"[调试] 治疗失败: {e}")
                # ★ zone1 日常任务（每 6 轮 ≈ 60 秒查一次，内部按天去重）
                if self._rfc % 6 == 0:
                    try:
                        self._日常任务()
                    except Exception as e:
                        self.log(f"[调试] 日常任务失败: {e}")
                # ★ zone2 常规任务（每 6 轮 ≈ 60 秒查一次，持续执行）
                if self._rfc % 6 == 0:
                    try:
                        self._常规任务()
                    except Exception as e:
                        self.log(f"[调试] 常规任务失败: {e}")
                time.sleep(10)

        # ★ 防止重复启动：已有存活线程则不再创建
        if getattr(self, "_hb_thread", None) is not None and self._hb_thread.is_alive():
            self.log("[警告] 检测到会话已在运行，忽略重复启动（防止重复出征）")
            return
        t = threading.Thread(target=_hb, daemon=True)
        self._hb_thread = t
        t.start()
        r = threading.Thread(target=_refresh, daemon=True)
        self._rf_thread = r
        r.start()

    # ==================== 配兵（按商辅规则） ====================
    # 商辅规则（逆自前端说明文字）：
    #   ① 将领必须先在「配兵列表」启用，否则禁止出征
    #   ② 兵力低于 1200（冲车 200）的将，限制出征
    #   ③ 出征前把兵补齐到配置的兵种/数量
    出征最低兵力 = 1200
    冲车最低兵力 = 200
    冲车seq = 5                     # 沖城車（见 兵种名表.json）

    def 配兵配置(self):
        """账号配置 zone3 里的配兵表 → {武将ID: {"seq","count","enabled"}}"""
        cfg = configs_db.get(str(self.acct_id)) or {}
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

    def 检查出征资格(self, 武将ID):
        """商辅规则：① 必须在配兵列表启用 ② 兵力不低于 1200(冲车 200)。

        返回 (是否可出征, 原因)。未来出征类功能派将前调用它即可。
        """
        try:
            武将ID = int(武将ID)
        except Exception:
            return False, "无效武将ID"
        row = self.配兵配置().get(武将ID)
        if not row:
            return False, "未在配兵列表配置"
        if not row.get("enabled"):
            return False, "配兵列表中未打勾启用"
        当前 = self._部队表.get(武将ID)
        cnt = 当前[1] if 当前 else 0
        门槛 = self.冲车最低兵力 if row.get("seq") == self.冲车seq else self.出征最低兵力
        if cnt < 门槛:
            return False, "兵力不足 %d（当前 %d）" % (门槛, cnt)
        return True, "可出征"

    def 出征资格表(self):
        """所有已配置将领的出征资格，供前端/出征功能使用。"""
        out = []
        for gid, row in self.配兵配置().items():
            ok, why = self.检查出征资格(gid)
            当前 = self._部队表.get(gid)
            out.append({"genId": gid, "seq": row.get("seq"), "count": row.get("count"),
                        "enabled": row.get("enabled"), "curCount": 当前[1] if 当前 else 0,
                        "canDispatch": ok, "reason": why})
        return out

    def _自动配兵(self):
        """按账号配置 zone3(ASSIGN_SOLDIER) 自动补兵。

        每轮刷新检查：武将当前（兵种seq, 数量）与配置不符 → 发 op 4646 补齐/取消。
        同一武将 60 秒内最多补一次，避免刷屏和封号风险。
        """
        from core.king_client import 配兵 as _配兵, 解析配兵应答
        cfg = configs_db.get(str(self.acct_id)) or {}
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
        if self._pb_dead >= 3:
            return
        now = time.time()
        for gid, seq, cnt in 行:
            当前 = self._部队表.get(gid)
            if 当前 and 当前[0] == seq and 当前[1] == cnt:
                continue                                  # 已符合配置
            if now - self._pb_last.get(gid, 0) < 60:
                continue                                  # 冷却中
            try:
                r = 解析配兵应答(_配兵(self.client, gid, seq, cnt))
            except Exception as e:
                self.log(f"[自动配兵] 异常: {e}")
                self._pb_dead += 1
                continue
            self._pb_last[gid] = now
            if r.get("ok"):
                self._pb_dead = 0
                # ★ 关键：服务端可能只给增量包，界面数据不会自动更新。
                #   所以把应答里的新值直接写回本地，避免每轮白发一次配兵包。
                if r.get("newCount"):
                    self._部队表[gid] = (r.get("newSeq") or seq, r["newCount"])
                else:
                    self._部队表.pop(gid, None)
                self._同步部队到前端()
                self.log(f"[自动配兵] 武将{gid} → {seq} × {cnt}（{r.get('oldCount')}→{r.get('newCount')}）")
            elif not (r.get("raw") or ""):
                self._pb_dead += 1
                self.log(f"[自动配兵] 无应答（{self._pb_dead}/3），会话可能已失效")
                if self._pb_dead >= 3:
                    self.log("[自动配兵] 已暂停：会话失效，请在页面上重新启动账号")
                    return
            else:
                self._pb_dead = 0
                self.log(f"[自动配兵] 失败 武将{gid} (应答 {(r.get('raw') or '')[:30]})")

    def _同步部队到前端(self):
        """把 _部队表 的变化同步回 generals/troops（增量包不刷新时也能立即看到）"""
        try:
            nm = self.character.get("charName", "")
            for g in self.generals:
                t2 = self._部队表.get(g.get("genId"))
                if t2:
                    g["soldierCount"] = t2[1]
                    g["curTroops"] = t2[1]
                    try:
                        g["soldierName"] = self._兵种名表.get(str(t2[0]), "—")
                    except Exception:
                        g["soldierName"] = "—"
                elif g.get("soldierCount"):
                    g["soldierCount"] = 0
                    g["curTroops"] = 0
                    g["soldierName"] = "—"
            self.troops = self._建部队(self.generals, nm)
        except Exception:
            pass


    def _日常任务(self):
        """zone1 日常任务（签到/俸禄/领奖/捐献…），每天最多成功一次。

        具体任务表在 features/daily.py，新增一类日常只改那里的 TASKS 字典。
        """
        if not self.client:
            return
        import features.daily as daily
        today = time.strftime("%Y-%m-%d")
        cfg = configs_db.get(str(self.acct_id)) or {}

        # UI 勾了但后端还做不了的，启动后提示一次就够，别每分钟刷屏
        if not getattr(self, "_daily_warned", False):
            for msg in daily.未支持提示(cfg):
                self.log("[日常] 暂不支持 —— %s" % msg)
            self._daily_warned = True

        做完 = daily.执行(self.client, cfg, today, self.log)
        if not 做完:
            return

        # 写回 lastRunDate：整份替换而不是就地改，避免与 HTTP 线程读到半截数据
        with _LOCK:
            cur = dict(configs_db.get(str(self.acct_id)) or {})
            rows = [dict(r) if isinstance(r, dict) else r
                    for r in (cur.get("zone1") or [])]
            for r in rows:
                if isinstance(r, dict) and r.get("type") in 做完:
                    r["lastRunDate"] = today
            cur["zone1"] = rows
            configs_db[str(self.acct_id)] = cur
            save_configs()

    def _常规任务(self):
        """zone2 常规任务（粮转铜/内政/喊话…），持续执行无每日限制。

        具体任务表在 features/routine.py，新增一类常规只改那里的 TASKS 字典。
        """
        if not self.client:
            return
        import features.routine as routine
        cfg = configs_db.get(str(self.acct_id)) or {}
        character = self.character or {}

        routine.执行(self.client, cfg, character, self.log)

    def _山贼锚点序列(self, cx, cy):
        """生成 6×6 锚点坐标，从中心向外一圈圈铺开。

        ★ 真机抓包（刷新山贼.har）实证：op 5440 载荷 (0,x,y) 里的 x,y 是
          【地图坐标】不是页码，锚点步长 = 6（每个锚点覆盖 [x,x+5]×[y,y+5]）。
          抓到的真机序列：(123,30)→(117,30)→(117,36)→(123,36)，x/y 差值都是 6。
        """
        STEP = 6
        w = int(getattr(self.client, "map_w", 0) or 0) or 187
        h = int(getattr(self.client, "map_h", 0) or 0) or 56
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

    def _翻页找山贼(self, lv, 已打, 已打坐标, cx, cy, 最多翻页=15):
        """刷新山贼：一次翻一页（一个锚点＝一个 5440 包），
        命中符合等级的就【立刻返回】，没有就翻下一页。

        这样出征紧跟在刷新之后发出，山贼 ID 还是新鲜的 —— 旧实现先扫全图
        （120 包/请求 × 很多轮，拿到 8 万个山贼）再出征，ID 早就失效了，
        服务端回 code=-28。

        游标 _sh_i 跨轮持久化，避免每次都从同一片区域重新翻。
        """
        from core.king_client import 扫描山贼
        pts = getattr(self, "_sh_pts", None)
        if not pts:
            pts = self._山贼锚点序列(cx, cy)
            self._sh_pts = pts
        if not pts:
            return None, 0
        i0 = getattr(self, "_sh_i", 0)
        翻过 = 0
        for k in range(min(最多翻页, len(pts))):
            i = (i0 + k) % len(pts)
            x, y = pts[i]
            翻过 = k + 1
            try:
                fs = 扫描山贼(self.client, [(x, y)])    # ★ 一个请求只发一个包
            except Exception:
                continue
            for t in fs.values():
                if t.get("lvl") not in lv:
                    continue
                if t["id"] in 已打 or (t["x"], t["y"]) in 已打坐标:
                    continue
                self._sh_i = (i + 1) % len(pts)
                self.log("[刷黄] 翻第%d页 锚点(%d,%d) → 命中 %s Lv%s 坐标(%d,%d)" % (
                    翻过, x, y, t.get("name"), t.get("lvl"), t["x"], t["y"]))
                return t, 翻过
        self._sh_i = (i0 + 翻过) % len(pts)
        return None, 翻过

    def _刷黄(self):
        """刷黄：刷新一页山贼 → 有符合等级的就出征 → 没有就翻下一页。

        ★ 真机抓包（刷新山贼.har）修正的认知：
          · op5440 一个请求只发【一个】包，载荷 (0,x,y) 的 x,y 是【地图坐标】
          · 每个锚点覆盖 6×6 区域，锚点步长 = 6
          · 旧代码把 (x,y) 当分页参数批量发 120 包扫全图，拿到 8 万个山贼后
            再出征，此时 ID 已失效 → 服务端回 code=-28
        """
        import time as _t
        try:
            from core.king_client import 出征打山贼
            now = _t.time()
            if now - getattr(self, "_sh_last", 0) < 15:
                return
            self._sh_last = now

            cfg = configs_db.get(str(self.acct_id)) or {}
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
                self.log("[刷黄] 未配置启用的刷黄编队（军事→刷黄 里设置）")
                return
            lv = 队[0]["levels"]

            # ---- 2) 找所有空闲编队（支持多队并行出征）
            武将表 = {g.get("genId"): g for g in self.generals}
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
                self.log("[刷黄] 编队未就绪（%s），等待返回" % "/".join(全忙原因 or ["未知"]))
                return

            # ---- 3+4+5) ★ 刷新一页 → 有符合的就出征，没有就翻下一页
            已打 = {k: v for k, v in getattr(self, "_sh_done", {}).items() if now - v < 900}
            self._sh_done = 已打
            已打坐标 = {k: v for k, v in getattr(self, "_sh_xy", {}).items() if now - v < 900}
            self._sh_xy = 已打坐标

            # ---- 6+7+8) 为每个空闲编队翻页找目标并出征
            dispatched = 0
            总翻页 = 0
            for 可用队 in 可用队列:
                目标, 用页数 = self._翻页找山贼(lv, 已打, 已打坐标, cx, cy)
                总翻页 += 用页数
                if 目标 is None:
                    self.log("[刷黄] 翻了%d页仍无符合等级%s的山贼（已打%d）" % (
                        总翻页, sorted(lv), len(已打)))
                    break
                已打坐标[(目标["x"], 目标["y"])] = now
                # 出征
                for gid in 可用队["generalIds"]:
                    w = 武将表.get(gid, {})
                    self.log("[刷黄] 出征 → %s Lv%d 坐标(%d,%d) | %s 体力%d/%d 兵%d" % (
                        目标["name"], 目标["lvl"], 目标["x"], 目标["y"],
                        w.get("name", "?"), w.get("curHp", 0), w.get("maxHp", 0),
                        w.get("soldierCount", 0)))
                try:
                    r = 出征打山贼(self.client, 可用队["generalIds"], 目标["id"])
                    已打[目标["id"]] = now
                    self._sh_xy[(目标["x"], 目标["y"])] = now
                    self._force_full_at = time.time() + 4
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
                        self.log("[刷黄] ✓ 已出征，行军至 (%d,%d)" % (目标["x"], 目标["y"]))
                        for gen in getattr(self, "generals", []):
                            if gen.get("genId") in 可用队["generalIds"]:
                                gen["statusText"] = "行军中"
                        dispatched += 1
                    elif r:
                        raw_hex = ""
                        for p in r:
                            if p.get("op") == resp_op and p.get("data"):
                                raw_hex = p["data"][:32].hex()
                                break
                        self.log("[刷黄] ✗ 出征被拒 code=%s msg='%s' raw=%s | 响应包数=%d" % (
                            出征码, 出征消息, raw_hex, len(r)))
                    else:
                        self.log("[刷黄] ✗ 出征无响应")
                except Exception as ex:
                    self.log("[刷黄] ✗ 出征失败: %s" % ex)
        except Exception as e:
            self.log("[刷黄] 异常: %s" % e)

    def 配兵(self, 任务列表):
        """配兵（op 4646 generalWithSoldier，真机格式）。

        任务列表 = [{"genId": 武将ID, "seq": 兵种seq, "count": 数量}, ...]
        count = 0 表示【取消配兵】。
        协议（真机抓包 + 实测验证）：
            载荷 17 字节 = [short 0][long 武将ID][byte 0][short 兵种seq][int 数量]
            明文载荷、长度字段=载荷长-2、无签名
        """
        from core.king_client import 配兵 as _配兵, 解析配兵应答
        任务 = []
        for t in (任务列表 or []):
            try:
                任务.append({"genId": int(t.get("genId")), "seq": int(t.get("seq")),
                            "count": int(t.get("count"))})
            except Exception:
                continue
        if not 任务:
            return {"ok": 0, "fail": 0, "changed": [], "msg": "未选择武将"}
        前 = {g.get("genId"): g.get("soldierCount") for g in self.generals}
        成功, 明细 = 0, []
        for t in 任务:
            try:
                r = 解析配兵应答(_配兵(self.client, t["genId"], t["seq"], t["count"]))
            except Exception as e:
                self.log("配兵异常 genId=%s: %s" % (t["genId"], e))
                明细.append({"genId": t["genId"], "seq": t["seq"], "count": t["count"], "ok": False})
                continue
            if r.get("ok"):
                成功 += 1
                if r.get("newCount"):
                    self._部队表[t["genId"]] = (r.get("newSeq") or t["seq"], r["newCount"])
                else:
                    self._部队表.pop(t["genId"], None)
                self._同步部队到前端()
                self.log("配兵成功: 武将%s 兵种%s %s→%s" % (
                    t["genId"], t["seq"], r.get("oldCount"), r.get("newCount")))
            else:
                self.log("配兵被拒: 武将%s seq%s × %s 应答=%s" % (
                    t["genId"], t["seq"], t["count"], (r.get("raw") or "")[:36]))
            明细.append({"genId": t["genId"], "seq": t["seq"], "count": t["count"],
                        "ok": bool(r.get("ok")), "oldCount": r.get("oldCount"),
                        "newCount": r.get("newCount")})
            time.sleep(0.4)
        time.sleep(1.0)
        try:
            self._全量刷新(强制完整=True)   # 写操作后强制取完整包
        except Exception as e:
            self.log("[调试] 配兵后刷新失败: %s" % e)
        后 = {g.get("genId"): g.get("soldierCount") for g in self.generals}
        变化 = []
        for t in 任务:
            a, b = 前.get(t["genId"]), 后.get(t["genId"])
            if a != b:
                变化.append({"genId": t["genId"], "before": a, "after": b})
        for c in 变化:
            self.log("  武将 %s: 统兵 %s → %s" % (c["genId"], c["before"], c["after"]))
        return {"ok": 成功, "fail": len(任务) - 成功, "changed": 变化, "detail": 明细,
                "msg": "配兵完成：成功 %d / %d" % (成功, len(任务))}

    def _拉实时包(self, 强制完整=False):
        """拉 op12560 实时包。

        ⚠️ 服务端行为（真机抓包 + 实测确认）：
           某会话【第一次】12560 返回完整包（1800+字节，含武将）；
           之后只返回【增量包】（130-160字节，不含武将数据）。
           要再拿完整包，必须重发 op 4099『进游戏』（复用 sub_token/session，
           比重新 gameLogin 轻得多，不增加封号风险）。
        """
        from core.king_client import 解析武将列表
        try:
            pk = self.client.send_op(12560, b"\x01")
        except Exception as e:
            self.log("[调试] 拉实时包失败: %s" % e)
            return None
        d = None
        for p in pk or []:
            if p["op"] == 41232 and p.get("data"):
                d = p["data"]
                break
        if d and 解析武将列表(d):
            return d
        # ★ 关键修复：只有【显式要求完整包】且距上次重进超过 60 秒，才重进游戏。
        #   旧写法 "or not d" 会在拿不到包时也调 enter_game()，
        #   而 enter_game = 重新进游戏 = 把玩家/别的会话挤下线，
        #   会话失效时会反复重进 → 账号被彻底踢下线（实测踩坑）。
        now = time.time()
        if 强制完整 and (now - getattr(self, "_eg_last", 0) > 60):   # ★ 60秒冷却
            self._eg_last = now
            try:
                self.client.enter_game()
                self.log("[刷新] 重进游戏取完整包")
            except Exception as e:
                self.log("[调试] 重进游戏失败: %s" % e)
                return d
            # ★ 修复：重进后用 game_login 拿 op 32772 数据（模式A 能正确解析武将+状态）
            #   之前用 12560 实时包，但实时包的 A4 记录没有 genId → 解析不稳定
            try:
                login_pk = self.client.game_login()
                self.client.login_packets = login_pk
                for p in login_pk or []:
                    if p.get("op") == 32772 and p.get("data"):
                        return p["data"]
            except Exception as e:
                self.log("[调试] 重进后 game_login 失败: %s" % e)
            # 兜底：尝试 12560
            try:
                pk2 = self.client.send_op(12560, b"\x01")
            except Exception as e:
                self.log("[调试] 重进后拉包失败: %s" % e)
                return d
            for p in pk2 or []:
                if p["op"] == 41232 and p.get("data"):
                    return p["data"]
        return d

    def _全量刷新(self, 强制完整=False):
        """用客户端自己的实时接口刷新（不再重复 gameLogin，避免封号风险）：
             op 12560 (REQ_HD_LIVEPACKET) → 武将实时数据
             op 4128  → 铜钱/粮食/人口/产速
             op 4356  → 宝物
             op 12593 → 状态 buff
        """
        from core.king_client import 解析武将列表, 解析宝藏
        ok = False
        # 1) 实时包 → 武将 / 部队（客户端原版接口）
        try:
            d = self._拉实时包(强制完整=强制完整)
            if d:
                raw = 解析武将列表(d)
                if raw:
                    from core.king_client import 解析部队
                    gids = {g["genId"] for g in raw}
                    self._部队表 = 解析部队(d, gids)
                    nm = self.character.get("charName", "")
                    self.generals = self._建武将(raw, nm)
                    self.troops = self._建部队(self.generals, nm)
                    ok = True
                    self._实时包 = d
                    self._实时包时间 = time.time()
        except Exception as e:
            self.log(f"[调试] 实时包失败: {e}")
        # 2) 资源
        try:
            res = self.client.取角色资源()
            if res:
                for k in ("copper", "food", "popUsed", "popMax",
                          "yieldCoin", "yieldFood", "gold", "silver"):
                    if res.get(k) is not None:
                        self.character[k] = res[k]
                self.character["copperRate"] = self.character.get("yieldCoin", 0)
                self.character["foodRate"] = self.character.get("yieldFood", 0)
                ok = True
        except Exception:
            pass
        # 3) 宝物
        try:
            tb = 解析宝藏(self.client.send_op(4356, b""))
            it = []
            for e in (tb.get("treasures") or []):
                it.append({"name": (self._物品名表 or {}).get(str(e["id"]), "物品#%d" % e["id"]),
                           "quantity": e["count"]})
            self.items = it
            self.character["treasureCur"] = tb.get("treasureCur", 0)
            self.character["treasureMax"] = tb.get("treasureMax", 0)
            ok = True
        except Exception:
            pass
        # 4) 状态 buff
        try:
            self._抓状态()
        except Exception:
            pass
        self._lastRefresh = time.time()
        return ok

    def _建武将(self, raw, charName=""):
        """原始 A4 数据 → 前端英雄表结构"""
        gens = []
        for g in raw:
            nm = g.get("name", "")
            将类 = {0: "步", 1: "弓", 2: "骑", 4: "勇"}.get(g.get("ga"), "—")
            # 兵种/数量来自 解析部队（真实数据）
            sid, scnt = self._部队表.get(g.get("genId"), (None, 0))
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
                "soldierName": (self._兵种名表 or {}).get(str(sid), "—") if sid else "—",
            })
        return gens

    def _建部队(self, gens, charName=""):
        """武将 → 军队表结构"""
        伤兵表 = getattr(self, "_伤兵表", {})
        out = []
        for i, g in enumerate(gens):
            cnt = int(g.get("soldierCount", 0) or 0)
            gid = g.get("genId")
            wounded = 伤兵表.get(gid, 0)
            if wounded <= 0:  # 只显示有伤兵的武将
                continue
            out.append({
                "fiefIndex": i + 1,
                "soldierName": g.get("soldierName", "—"),
                "idleCount": cnt,
                "woundedCount": wounded,
                "fiefName": (charName or "") + "基地",
                "genId": gid,
            })
        return out

    def _查伤兵(self):
        """主动向服务器查询实时伤兵数据（不再依赖 login_packets 旧数据）"""
        if not self.client:
            return
        fiefs = 刷新伤兵(self.client)
        if not fiefs:
            self.log("[伤兵] 查询无数据（op4368 未返回有效封地）")
            return
        self._伤兵表_raw = fiefs
        seq伤兵 = {}
        for fid, info in fiefs.items():
            for seq, cnt in info.get("wounded", []):
                if cnt > 0:
                    seq伤兵[seq] = seq伤兵.get(seq, 0) + cnt
        self._伤兵总数 = sum(seq伤兵.values())
        seq到将 = {}
        for gid, (s, _c) in getattr(self, "_部队表", {}).items():
            seq到将.setdefault(s, []).append(gid)
        伤兵 = {}
        for seq, cnt in seq伤兵.items():
            gids = seq到将.get(seq)
            if gids:
                伤兵[gids[0]] = 伤兵.get(gids[0], 0) + cnt
        self._伤兵表 = 伤兵
        if self._伤兵总数 > 0:
            self.log("[伤兵] 查到 %d 伤兵（封地%d个 兵种%s）" % (
                self._伤兵总数, len(fiefs), dict(seq伤兵)))

    def _治疗伤兵(self):
        """自动治疗伤兵（读 HEAL_SOLDIER.enabled 配置）
        用封地 fiefId + 兵种 seq 发 op 4656 治疗。
        """
        cfg = configs_db.get(str(self.acct_id)) or {}
        heal_cfg = cfg.get("HEAL_SOLDIER") or {}
        if not heal_cfg.get("enabled"):
            if getattr(self, "_伤兵总数", 0) > 0 and not getattr(self, "_heal_warn", False):
                self.log("[治疗] ⚠ 有%d伤兵但自动治疗未开启（前端→伤兵治疗→开关）" % self._伤兵总数)
                self._heal_warn = True
            return
        if not self.client:
            return
        伤兵raw = getattr(self, "_伤兵表_raw", {})
        if not 伤兵raw:
            return
        for fid, info in 伤兵raw.items():
            for seq, cnt in info.get("wounded", []):
                if cnt <= 0:
                    continue
                try:
                    r = 治疗伤兵(self.client, fid, soldier_type=seq, count=cnt)
                    if r and r.get("ok"):
                        self.log("[治疗] ✓ 封地%d 兵种%d ×%d 已治疗" % (fid, seq, cnt))
                    elif r:
                        self.log("[治疗] ✗ %s" % r.get("msg", "失败"))
                except Exception as e:
                    self.log("[治疗] 异常: %s" % e)

    def _刷新武将(self):
        """op 4368 实时包 → 刷新武将/部队（无需重新登录）"""
        pk = self.client.send_op(4368, b"")
        dd = None
        for p in pk or []:
            if p["op"] - 28672 == 4368 and p.get("data"):
                dd = p["data"]
                break
        if not dd:
            return False
        from core.king_client import 解析武将列表
        raw = 解析武将列表(dd)
        if not raw:
            return False
        gens = self._建武将(raw, self.character.get("charName", ""))
        self.generals = gens
        self.troops = self._建部队(gens, self.character.get("charName", ""))
        return True

    def to_poll(self, since=0):
        """商辅前端 wdApplyRuntimeData() / rn() 期望的结构"""
        try: since = max(0, int(since))
        except: since = 0
        new_logs = self.logs[since:] if since < len(self.logs) else []
        return {
            "status": self.status,
            "lastError": self.last_error,
            "lastAccessTime": self.last_access,
            "source": "game",
            "character": self.character or None,
            "generals": getattr(self, "generals", []),
            "officers": [],
            "troops": getattr(self, "troops", []),
            "items": getattr(self, "items", []),
            "roleStatuses": getattr(self, "roleStatuses", []),
            "roleStatusList": getattr(self, "roleStatuses", []),
            "convoyCountries": [],
            "logs": new_logs,
            "total": len(self.logs),
            "nextIndex": len(self.logs),
            "logs": new_logs,
            "total": len(self.logs),
            "nextIndex": len(self.logs),
            # 自用扩展字段
            "running": self.running,
            "uptime": int(time.time() - self.start_time) if self.start_time else 0,
            "alarmActive": False,
            "alarmCount": 0,
            "tasks": [],
            "worker": {},
        }

    def to_dict(self):
        return self.to_poll(0)

bots = {}  # account_id -> BotSession

def find_account(acct_id):
    for a in accounts_db:
        if a["id"] == acct_id:
            return a
    return None

def ok(data=None):
    return {"code": 200, "msg": "ok", "data": data}
def fail(msg):
    return {"code": 400, "msg": msg, "data": None}

def build_user_info():
    return ok({
        "id": 1, "userId": 1, "phone": "test", "username": "test",
        "nickname": "测试账号", "role": "USER", "isAdmin": True, "isAgent": False,
        "coin": 99999, "coinBalance": 99999,
        "vipStatus": "ACTIVE", "expireAt": "2027-12-31",
        "expireTime": "2027-12-31", "vipExpiresAt": "2027-12-31",
        "maxAccounts": 50, "maxSlots": 50, "maxConcurrentAccounts": 20,
        "expired": False, "isTrial": False,
        "email": "", "emailBound": False, "emailVerifiedAt": "",
        "verifiedPhone": "test", "maskedPhone": "te****st",
        "phoneBound": True, "phoneVerifiedAt": "2026-01-01T00:00:00",
        "permissions": {
            "admin": True, "agent": True,
            "linked_escort": True, "linked_country_change": True,
            "linked_fief_setup": True, "linked_server_transfer": True,
            "fief_setup": True, "apprentice": True, "city_transfer": True,
            "batch_server_transfer": True, "batch_country_change": True,
            "recruit_soldiers": True, "batch_import": True,
            "world_shout": True, "fief_repair": True,
            "batch_fief_repair": True, "recruit_generals": True,
            "auto_switch_roles": True
        },
        "gameAccounts": accounts_db,
        "unreadAnnouncements": [
            {"id": "notice-1", "title": "帝王三国辅助",
             "content": "欢迎使用，请先添加游戏账号", "publishDate": "2026-09-14",
             "enabled": True, "showMode": 1}
        ]
    })


class Handler(BaseHTTPRequestHandler):

    def _send(self, code, ctype, body):
        self.send_response(code)
        self.send_header("Content-type", ctype)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,PUT,DELETE,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()
        if isinstance(body, str): body = body.encode("utf-8")
        self.wfile.write(body)

    def _json(self, data):
        self._send(200, "application/json; charset=utf-8",
                   json.dumps(data, ensure_ascii=False))

    def _read_body(self):
        try:
            n = int(self.headers.get("Content-Length", 0))
            if not n: return {}
            raw = self.rfile.read(n).decode("utf-8", "replace")
            try: return json.loads(raw)
            except:
                from urllib.parse import parse_qs
                return {k: v[0] for k, v in parse_qs(raw).items()}
        except: return {}

    def _send_file(self, full):
        if not os.path.isfile(full):
            self._send(404, "text/plain", "not found"); return
        ext = os.path.splitext(full)[1].lstrip(".")
        ct = {"html":"text/html; charset=utf-8","css":"text/css; charset=utf-8",
              "js":"application/javascript; charset=utf-8","json":"application/json",
              "png":"image/png","mjs":"application/javascript"}.get(ext,"application/octet-stream")
        with open(full, "rb") as f:
            self._send(200, ct, f.read())

    def do_OPTIONS(self):
        self._send(200, "text/plain", "")

    # ==================== GET ====================
    def do_GET(self):
        path = urlparse(self.path).path
        qs = urlparse(self.path).query
        params = {}
        if qs:
            for kv in qs.split("&"):
                if "=" in kv:
                    k, v = kv.split("=", 1)
                    params[k] = urllib.request.unquote(v)

        # ---- API ----
        if path == "/api/auth/info":
            return self._json(build_user_info())
        elif path == "/api/servers/all":
            d = {}
            for r in REGIONS:
                d[r["serverKey"]] = {"serverId": 0, "name": r["serverName"], "key": r["serverKey"]}
            return self._json(ok(d))
        elif path == "/api/announcements/unread":
            return self._json(build_user_info())
        elif path == "/api/account/regions":
            return self._json(ok(REGIONS))
        elif path == "/api/account/list":
            return self._json(ok(accounts_db))
        elif path == "/api/account/configs":
            return self._json(ok({}))
        elif path == "/api/bot/char-names":
            return self._json(ok({}))
        # ---- 配兵：出征资格检查（商辅规则）----
        elif path.startswith("/api/bot/") and path.endswith("/peibing/check"):
            aid = int(path.split("/")[3])
            bot = bots.get(aid)
            if not bot or not bot.client:
                return self._json(fail("会话未运行"))
            return self._json(ok({"generals": bot.出征资格表(),
                                  "rule": {"minSoldiers": bot.出征最低兵力,
                                           "minSoldiersChongche": bot.冲车最低兵力}}))
        # ---- Bot poll ----
        elif path.startswith("/api/bot/") and path.endswith("/poll"):
            parts = path.split("/")
            aid = int(parts[3])
            since = int(params.get("sinceIndex", 0))
            bot = bots.get(aid)
            if not bot:
                return self._json(ok({
                    "status": 0, "lastError": "", "lastAccessTime": "",
                    "source": "", "character": None, "generals": [],
                    "officers": [], "troops": [], "items": [],
                    "roleStatuses": [], "roleStatusList": [],
                    "convoyCountries": [], "logs": [], "total": 0,
                    "nextIndex": 0, "running": False, "uptime": 0,
                }))
            return self._json(ok(bot.to_poll(since)))
        # ---- Bot army-action (军情) ----
        elif path.startswith("/api/bot/") and path.endswith("/army-action"):
            parts = path.split("/")
            aid = int(parts[3])
            bot = bots.get(aid)
            if not bot or not bot.running:
                return self._json(ok({"expeditions": [], "alerts": [], "garrison": []}))
            try:
                result = 查询军情(bot.client)
                return self._json(ok(result))
            except Exception as e:
                bot.log(f"[军情] 查询失败: {e}")
                return self._json(ok({"expeditions": [], "alerts": [], "garrison": []}))
        # ---- Account config ----
        elif path.startswith("/api/account/") and path.endswith("/config"):
            aid = int(path.split("/")[3])
            cfg = dict(configs_db.get(str(aid), {}))   # 真实持久化配置
            bot = bots.get(aid)
            if bot and bot.running:
                cfg["running"] = True
            return self._json(ok(cfg))
        elif path.startswith("/api/"):
            return self._json(ok(None))

        # ---- 静态文件 ----
        if path == "/":
            return self._send_file(os.path.join(WWW, "index.html"))
        for base in (BASE, WWW, ASSETS):
            f = os.path.join(base, path.lstrip("/"))
            if os.path.isfile(f):
                return self._send_file(f)
        self._send(404, "text/plain", "not found")

    # ==================== POST ====================
    def do_POST(self):
        path = urlparse(self.path).path
        body = self._read_body()

        if path == "/api/auth/login":
            d = build_user_info()["data"]; d["token"] = "dt" + str(int(time.time()))
            return self._json(ok(d))
        elif path in ("/api/auth/register", "/api/auth/send-code",
                      "/api/auth/reset-password", "/api/announcements/read"):
            return self._json(ok(True))
        elif path == "/api/account/probe/characters":
            return self._json(ok([{"characterId":1,"characterIndex":1,
                "characterName":"君主","name":"君主","label":"君主","level":1}]))
        elif path == "/api/account/add":
            return self._add_account(body)

        # ---- Bot start / stop ----
        elif path.startswith("/api/bot/") and path.endswith("/start"):
            aid = int(path.split("/")[3])
            return self._bot_start(aid)
        elif path.startswith("/api/bot/") and path.endswith("/stop"):
            aid = int(path.split("/")[3])
            bot = bots.get(aid)
            if bot:
                bot.stop()
                bot.log("已手动停止")
            with _LOCK:
                for a in accounts_db:
                    if a["id"] == aid:
                        a["status"] = 0
                        save_accounts()
                        break
            return self._json(ok({"id": aid, "status": 0, "msg": "已停止"}))

        # ---- 配兵（联网批量补兵）----
        # ---- Account config 保存（含配兵 zone3）----
        elif path.startswith("/api/account/") and path.endswith("/config"):
            aid = int(path.split("/")[3])
            return self._account_config_save(aid, body)

        elif path.startswith("/api/bot/") and path.endswith("/peibing"):
            aid = int(path.split("/")[3])
            return self._bot_peibing(aid, body)

        elif path.startswith("/api/"):
            return self._json(ok(True))
        return self._json(ok(True))

    def _account_config_save(self, aid, body):
        """保存账号配置。zone3 里 type=ASSIGN_SOLDIER 的是【配兵】配置：
               {type:"ASSIGN_SOLDIER", enabled:bool, generalIds:[武将ID], soldierType:"轻骑兵", count:N}
           保存后：若会话在运行且该项 enabled，立即执行 op 4646 配兵。
        """
        cfg = dict(configs_db.get(str(aid), {}))
        # ★ 过滤掉非配置字段：前端会把上一次的响应当配置缓存并原样回传，
        #   导致 ok/fail/detail/msg 等被写进 configs.json（实测踩坑）。
        body = {k: v for k, v in (body or {}).items()
                if k not in ("ok", "fail", "changed", "detail", "msg", "saved",
                             "peibing", "peibingResult", "sent", "pending")}
        旧配兵 = json.dumps(cfg.get("zone3") or [], sort_keys=True, ensure_ascii=False)
        新配兵 = json.dumps(body.get("zone3") or [], sort_keys=True, ensure_ascii=False)
        cfg.update(body)
        configs_db[str(aid)] = cfg
        save_configs()
        # ★ 只有【配兵配置本身发生变化】时才执行配兵。
        #   前端保存任一 tab 都会把整个配置（含 zone3）发过来，
        #   若无脑执行，保存刷黄/掠夺等也会触发配兵 + 重进游戏（实测踩坑）。
        if 新配兵 == 旧配兵:
            return self._json(ok(dict(cfg, peibing="unchanged")))
        # 收集配兵任务
        任务 = []
        for z in (cfg.get("zone3") or []):
            if not isinstance(z, dict):
                continue
            if (z.get("type") or "ASSIGN_SOLDIER") != "ASSIGN_SOLDIER":
                continue
            if not z.get("enabled"):
                continue
            seq = 兵种seq(z.get("soldierType"))
            try:
                数量 = int(z.get("count") or 0)
            except Exception:
                数量 = 0
            for gid in (z.get("generalIds") or []):
                try:
                    任务.append({"genId": int(gid), "seq": seq, "count": 数量})
                except Exception:
                    continue
        if not 任务:
            return self._json(ok(dict(cfg, peibingResult={"msg": "配置已保存（配兵项未启用或未选将领）"})))
        bot = bots.get(aid)
        if not bot or not bot.client:
            return self._json(ok(dict(cfg, peibingResult={
                "msg": "配置已保存；会话未运行，配兵未执行", "pending": len(任务)})))
        try:
            r = bot.配兵(任务)
        except Exception as e:
            return self._json(ok(dict(cfg, peibingResult={"msg": "配兵失败: %s" % e})))
        return self._json(ok(dict(cfg, peibingResult=r)))


    def _bot_peibing(self, aid, body):
        """POST /api/bot/<id>/peibing

        请求两种形式（任选）：
          {"items":[{"genId":2735850,"seq":3,"count":20}, ...]}   ← 推荐（每武将单独兵种/数量）
          {"generals":[2735850,2735849], "seq":3, "count":20}      ← 简写（同一兵种/数量）
        count=0 表示取消配兵。
        """
        bot = bots.get(aid)
        if not bot or not bot.client:
            return self._json(fail("会话未运行，请先启动"))
        items = body.get("items")
        if not items:
            ids = body.get("generals") or body.get("ids") or body.get("genIds") or []
            seq = body.get("seq", body.get("soldierSeq"))
            cnt = body.get("count", body.get("num"))
            if ids and seq is not None and cnt is not None:
                items = [{"genId": i, "seq": seq, "count": cnt} for i in ids]
        if not items:
            return self._json(fail("请提供 items 或 generals+seq+count"))
        try:
            r = bot.配兵(items)
        except Exception as e:
            return self._json(fail("配兵失败: %s" % e))
        d = bot.to_poll(0)
        r["generals"] = d.get("generals", [])
        return self._json(ok(r))

    def _add_account(self, body):
        global next_id
        if not body.get("gameUsername"):
            return self._json(fail("请填写游戏账号"))
        if not (body.get("serverKey") or body.get("serverName")):
            return self._json(fail("请选择区服"))
        acct = {
            "id": next_id, "userId": 1,
            "gameVersion": body.get("gameVersion", "fanti_dwsg"),
            "gameUsername": body.get("gameUsername", ""),
            "gamePassword": body.get("gamePassword", ""),
            "serverName": body.get("serverName", ""),
            "serverKey": body.get("serverKey", ""),
            "characterIndex": body.get("characterIndex", 0),
            "characterName": body.get("characterName", ""),
            "jiuyouPhone": body.get("jiuyouPhone", ""),
            "linkedRoleCount": 0, "linkRoleCount": 0, "sameServerRoleCount": 0,
            "remark": body.get("remark", body.get("gameUsername", "")),
            "status": 0, "lastError": "", "lastAccessTime": "",
            "createdAt": time.strftime("%Y-%m-%d %H:%M:%S"),
            "updatedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
            "sortOrder": len(accounts_db),
        }
        with _LOCK:
            accounts_db.append(acct)
            next_id += 1
            save_accounts()
        return self._json(ok(acct))

    def _bot_start(self, aid):
        acct = find_account(aid)
        if not acct:
            return self._json(fail("账号不存在"))

        user = acct["gameUsername"]
        pwd = acct["gamePassword"]
        srv_name = acct.get("serverName", "")
        srv_key = acct.get("serverKey", "")

        # ★ 先停掉该账号已有会话，防止多线程并行刷黄
        旧 = bots.get(aid)
        if 旧 is not None:
            try:
                旧.running = False
                旧.status = 0
                旧.log("[停止] 被新会话取代")
            except Exception:
                pass
            time.sleep(0.3)

        # 先登记会话，前端即可轮询到「启动中」与日志
        bot = BotSession(acct)
        bot.status = 2
        bots[aid] = bot

        def _err(msg):
            bot.status = 0
            bot.running = False
            bot.last_error = msg
            bot.log(f"[失败] {msg}")
            return self._json(fail(msg))

        try:
            bot.log("正在获取区服列表…")
            session, sub, areas = 取区服列表(user, pwd)
            if not areas:
                return _err("账号或密码错误")
            bot.log(f"获取到 {len(areas)} 个区服")

            # 匹配区服
            host, port = None, 25511
            for name, h, p in areas:
                if name == srv_name or (srv_name and srv_name in name) \
                        or (srv_key and srv_key in name):
                    host, port, srv_name = h, p, name
                    break
            if not host:
                m = 匹配区服(areas, srv_key or srv_name)
                if m: srv_name, host, port = m
            if not host:
                srv_name, host, port = areas[0][0], areas[0][1], areas[0][2]
            bot.log(f"目标区服：{srv_name}（{host}:{port}）")

            bot.log("正在进入游戏…")
            c, msg = 进入游戏(user, pwd, host, port, session, sub)
            if not c:
                return _err(msg or "进入游戏失败")
            bot.client = c
            bot.server_name = srv_name
            bot.log(f"登录成功，play_id={c.play_id}")

            # 读取角色信息
            bot.log("正在读取角色信息…")
            try:
                bot.character = c.取角色全部信息()
                nm = bot.character.get("charName", "?")
                lv = bot.character.get("level", "?")
                kd = bot.character.get("kingdom", "?")
                bot.log(f"君主：{nm}　等级：{lv}　国家：{kd}")
                bot.log("铜钱 {:,}　粮食 {:,}".format(
                    int(bot.character.get("copper") or 0),
                    int(bot.character.get("food") or 0)))
                bot.log("人口 {}/{}　产钱 {}/时　产粮 {}/时".format(
                    bot.character.get("popUsed", 0), bot.character.get("popMax", 0),
                    bot.character.get("copperRate", 0), bot.character.get("foodRate", 0)))
            except Exception as e:
                bot.log(f"[警告] 角色信息读取失败：{e}")

            # 拉取 buff 状态
            try:
                bot._抓状态()
            except Exception as e:
                bot.log(f"[调试] 状态拉取失败: {e}")

            # 从登录包解析武将
            try:
                login_pk = c.login_packets
                if login_pk:
                    from core.king_client import 解析登录包武将
                    pk_data = None
                    for p in login_pk:
                        if p.get('op') == 32772:
                            pk_data = p['data']; break
                    if pk_data:
                        from core.king_client import 解析武将列表
                        raw = 解析武将列表(pk_data)
                        gens = []
                        for g in raw:
                            nm = g.get("name", "")
                            # 兵种：DEX 数组验证 —— 1=弓 2=骑 3=步 4=勇
                            # 将类：0步 1弓 2骑 4勇（真值验证）
                            将类 = {0: "步", 1: "弓", 2: "骑", 4: "勇"}.get(g.get("ga"), "—")
                            # 兵种：按武将类别对应（步兵/弓兵/骑兵/勇兵）
                            兵种 = {0: "步兵", 1: "弓兵", 2: "骑兵", 4: "勇兵"}.get(g.get("ga"), "—")
                            gens.append({
                                "genId": g.get("genId", 0),
                                "name": nm,
                                # 状态码 Oa（真值验证）：0=待命 1=行军中 8=返回中
                                "statusText": {0: "待命", 1: "行军中", 8: "返回中"}.get(
                                    g.get("Oa"),
                                    ("状态%d" % g.get("Oa")) if g.get("Oa") else "—"),
                                "typeText": 将类,
                                "level": int(g.get("ja", 1) or 1),   # ja=等级（已验证）
                                # 已用真值验证：体力=ra, 忠诚=wa, 统兵=troops
                                "curHp": int(g.get("hp", 0) or 0),
                                "maxHp": int(g.get("sa", 0) or 0),
                                "curLoyalty": int(g.get("loyalty", 0) or 0),
                                "maxLoyalty": 100,
                                "soldierCount": int(g.get("troops", 0) or 0),
                                "curTroops": int(g.get("troops", 0) or 0),
                                "maxTroops": int(g.get("troops", 0) or 0),
                                "soldierName": 兵种,
                                "_raw": {k: v for k, v in g.items()
                                         if k not in ("genId", "name")},
                            })
                        if gens:
                            bot.generals = gens
                            # 军队 tab：走 _建部队 以包含伤兵数据
                            try:
                                bot._查伤兵()
                            except Exception:
                                pass
                            bot.troops = bot._建部队(gens, bot.character.get("charName", ""))
                            bot.log("解析到 %d 支部队" % len(bot.troops))

                        # 宝物 tab：op 4356 + 本地物品名表
                        try:
                            import json as _json, os as _os
                            if bot._物品名表 is None:
                                p = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                                                  "物品名表.json")
                                bot._物品名表 = _json.load(open(p, encoding="utf-8")) \
                                    if _os.path.exists(p) else {}
                            tb = c.send_op(4356, b"")
                            from core.king_client import 解析宝藏
                            t = 解析宝藏(tb)
                            it = []
                            for e in (t.get("treasures") or []):
                                nm = bot._物品名表.get(str(e["id"]), "物品#%d" % e["id"])
                                it.append({"name": nm, "quantity": e["count"]})
                            bot.items = it
                            bot.log("解析到 %d 种宝物" % len(it))
                        except Exception as _e:
                            bot.log("[调试] 宝物解析失败: %s" % _e)
                            bot.log("解析到 %d 个武将: %s" % (
                                len(gens), " ".join(g["name"] for g in gens)))
                            for g in gens:
                                bot.log("  原始字段: %s" % g["_raw"])
            except Exception as e:
                bot.log(f"[调试] 武将解析: {e}")

            bot.start()

            with _LOCK:
                for a in accounts_db:
                    if a["id"] == aid:
                        a["status"] = 1
                        a["lastAccessTime"] = time.strftime("%Y-%m-%d %H:%M:%S")
                        save_accounts()
                        break

            return self._json(ok({"id": aid, "status": 1, "msg": "启动成功"}))

        except Exception as e:
            return _err(f"启动失败: {e}")

    # ==================== PUT ====================
    def do_PUT(self):
        path = urlparse(self.path).path
        body = self._read_body()
        # ---- 账号配置保存：前端用 PUT /account/<id>/config ----
        if path.startswith("/api/account/") and path.endswith("/config"):
            try:
                aid = int(path.split("/")[3])
            except Exception:
                return self._json(fail("无效ID"))
            return self._account_config_save(aid, body)
        if path == "/api/account/sort":
            order = body if isinstance(body, list) else body.get("ids", [])
            if isinstance(order, list):
                m = {a["id"]: a for a in accounts_db}
                accounts_db[:] = [m[i] for i in order if i in m] + \
                                 [a for a in accounts_db if a["id"] not in order]
                save_accounts()
            return self._json(ok(True))
        if path.startswith("/api/account/"):
            try:
                aid = int(path.rstrip("/").rsplit("/", 1)[-1])
            except:
                return self._json(fail("无效ID"))
            for a in accounts_db:
                if a["id"] == aid:
                    for k, v in body.items():
                        if k in ("id", "userId"): continue
                        if k == "gamePassword" and not v: continue
                        a[k] = v
                    a["updatedAt"] = time.strftime("%Y-%m-%d %H:%M:%S")
                    save_accounts()
                    return self._json(ok(a))
            return self._json(fail("账号不存在"))
        self._json(ok(True))

    # ==================== DELETE ====================
    def do_DELETE(self):
        path = urlparse(self.path).path
        if path.startswith("/api/account/"):
            try:
                aid = int(path.rstrip("/").rsplit("/", 1)[-1])
            except:
                return self._json(fail("无效ID"))
            with _LOCK:
                before = len(accounts_db)
                accounts_db[:] = [a for a in accounts_db if a["id"] != aid]
                if len(accounts_db) != before:
                    if aid in bots:
                        bots[aid].stop()
                        del bots[aid]
                    save_accounts()
                    return self._json(ok(True))
            return self._json(fail("账号不存在"))
        self._json(ok(True))

    def log_message(self, *a):
        pass


def start(port=8080):
    srv = HTTPServer(("0.0.0.0", port), Handler)
    print("=" * 62)
    print("  帝王三国辅助  v0.5 — 支持启动登录")
    print("=" * 62)
    print(f"\n  http://0.0.0.0:{port}")
    print(f"  {len(REGIONS)} 个区服 | {len(accounts_db)} 个账号")
    print(f"  平台: 繁体版 (fanti_dwsg)")
    print(f"  Bot 会话: 启动后可轮询角色信息\n")
    srv.serve_forever()


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8080)
    start(ap.parse_args().port)
