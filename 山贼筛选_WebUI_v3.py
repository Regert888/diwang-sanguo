#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
普通山贼筛选工具 - WebUI v3（独立版，单文件运行）
=====================================================================
v3 更新（2026-09-13）：
  ★ 全图扫描：坐标写死 0,0 ~ 249,61（覆盖 187×56 与 250×62 两种区）
  ★ 批量发包：一个 HTTP POST 塞 120 个 5440（实测上限，130 被拒）
  ★ 去掉 sleep：全图 318 区 ~2.0s / 霸图19区 ~3.7s
  ★ 模式自检：同点连查两次不一致 → 提示「枚举模式（<30 级号，坐标被忽略）」
  ★ 地图尺寸自动读：响应 34112 头前 4 字节 short w + short h（仅显示/告警，扫描上界写死 250×62）

按参考项目（sanguohx.exe）逻辑：
  * 只需填 账号 / 密码 / 区服号  → 自动解析区服 IP 端口
  * 筛选条件：山贼等级（多选）、守将兵种（下拉单选）、兵种大类上限、掉落物（多选）
  * 按距离排序输出坐标列表（不出征）

用法：
    python 山贼筛选_WebUI_v2.py --port 8080
    浏览器打开 http://localhost:8080
"""

import struct, time, math, json, hashlib, urllib.request, threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs

# ==================== 帝王三國客户端（内置，无外部依赖）====================
SALT = "FIC1atsuf30"
CHANNEL_ID = "0200000000"
C_VERSION = "1630107"
C_TYPE = "7054"
LOGIN_URL = "http://pass.dwsg.gameme5.com:8192/common/area/list.action"
VALIDATE_URL = "http://pass.dwsg.gameme5.com:8192/system/user/validate.action"
GAME_PATH = "/kingWapServer/HttpClient"
NO_ENC_OPS = {4096, 4098, 4101, 4118, 4099, 4097}
TARGET_ALL = "1,2,3,5,11,12,13,14,15,16,17,18,19,20,21,31,32,33,34,41,91"

# 服务端踢下线 / 账号异常的响应操作码（见 响应解析框架.md）
KICK_OPS = {-1, -3, -4, -5}
KICK_MSG = {-1: "账号异常（可能已被顶号/在别处登录）",
            -3: "账号异常（会话失效）",
            -4: "账号异常（被服务端断开）",
            -5: "服务端要求退出游戏（exitGame）"}

KEY_RAW = bytes.fromhex(
    "f33c2d941b8bef9e2cdcf7ee32bd3d18"
    "898c7c61a98389551a8f2b19a8fbeeeb"
)

def _wutf(s):
    b = s.encode("utf-8"); return struct.pack(">H", len(b)) + b
def _wlong(v): return struct.pack(">q", v)
def _wshort(v): return struct.pack(">H", v & 0xFFFF)
def _wbyte(v): return struct.pack(">B", v & 0xFF)

def md5_sign(op, cur_time, play_id):
    return hashlib.md5((str(op + cur_time + play_id) + SALT).encode()).hexdigest().lower()

def enc_key():
    wu = _wutf(SALT)
    return bytes((KEY_RAW[i] - wu[i % len(wu)]) & 0xFF for i in range(len(KEY_RAW)))

def encrypt(data, key=None):
    key = key or enc_key()
    return bytes((data[i] + key[i % len(key)]) & 0xFF for i in range(len(data)))

def decrypt(data, key=None):
    key = key or enc_key()
    return bytes((data[i] - key[i % len(key)]) & 0xFF for i in range(len(data)))


def 取区服列表(user, pwd):
    """登录通行证，返回 [(区服名, host, port), ...] 以及 session/subtoken"""
    url = (f"{LOGIN_URL}?username={user}&password={pwd}"
           f"&channelId={CHANNEL_ID}&source=diwang.sanguo"
           f"&cType={C_TYPE}&cVersion={C_VERSION}"
           f"&gameKey=diwang.sanguo&target={TARGET_ALL}")
    with urllib.request.urlopen(url, timeout=15) as r:
        resp = r.read().decode("utf-8", "replace")
    lines = resp.split("\n")
    head = lines[0].split("`")
    session = head[0] if head else ""
    sub_token = head[1] if len(head) > 1 else ""
    areas = []
    for line in lines[1:]:
        if not line.strip():
            continue
        parts = line.split("`")
        if len(parts) >= 4:
            name, url_str = parts[2], parts[3]
            if url_str.startswith("http://"):
                url_str = url_str[7:]
            url_str = url_str.split("/")[0]
            if ":" in url_str:
                host, port_str = url_str.split(":")[0], url_str.split(":")[1]
                port = int(port_str) if port_str.isdigit() else 25511
            else:
                host, port = url_str, 25511
            if host:
                areas.append((name, host, port))
    return session, sub_token, areas


def 匹配区服(areas, area_key):
    """按区服号/名字模糊匹配，例如 '328' 匹配 '328区'"""
    key = str(area_key).strip().replace("区", "").replace("區", "")
    for name, host, port in areas:
        n = name.replace("区", "").replace("區", "")
        if n == key:
            return name, host, port
    for name, host, port in areas:
        if key and key in name:
            return name, host, port
    return None


def 会话探活(session):
    """validate.action 探活：返回 True=会话有效。被顶号后此接口会失败"""
    try:
        url = f"{VALIDATE_URL}?session={session}&target=1,10"
        with urllib.request.urlopen(url, timeout=10) as r:
            txt = r.read().decode("utf-8", "replace").strip()
        # 正常返回 "次token`0"
        parts = txt.split("`")
        return len(parts) >= 2 and parts[0] and len(parts[0]) > 8
    except Exception:
        return False


def 检查踢下线(packets):
    """扫描响应封包，命中 -1/-3/-4/-5 说明已被服务端踢下线"""
    for p in packets or []:
        if p["signed"] in KICK_OPS:
            return KICK_MSG.get(p["signed"], f"账号异常(op={p['signed']})")
    return None


class KingClient:
    def __init__(self, user, pwd, game_host=None, game_port=25511):
        self.user, self.pwd = user, pwd
        self.channel_id, self.c_version, self.c_type = CHANNEL_ID, C_VERSION, C_TYPE
        self.game_url = f"http://{game_host}:{game_port}{GAME_PATH}" if game_host else None
        self.session = None
        self.sub_token = None
        self.play_id = 0

    def set_server(self, host, port):
        self.game_url = f"http://{host}:{port}{GAME_PATH}"

    def _game_post(self, packets, play_id=None):
        play_id = self.play_id if play_id is None else play_id
        cur = int(time.time() * 1000)
        header = f"{self.c_version}`{self.c_type}`{self.channel_id}"
        body = _wutf(header) + _wlong(cur) + _wbyte(len(packets))
        for op, data in packets:
            if op not in NO_ENC_OPS:
                data = encrypt(data)
            sig = md5_sign(op, cur, play_id)
            body += _wlong(play_id) + _wlong(0) + _wshort(len(data)) + _wshort(op) + _wutf(sig) + data
        req = urllib.request.Request(self.game_url, data=body, method="POST")
        req.add_header("Content-Type", "application/octet-stream")
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.read()

    def _game_post_raw(self, op, data, play_id=None):
        """业务操作发包（严格按真机抓包结构还原，2026-09-13 修正）

        与登录用的 _game_post 不同：无 md5 签名、数据体不加密。
        结构（HttpCanary 抓包实证）：
            writeUTF(版本`ctype`channelId)
            long   时间戳ms
            byte   包数量 = 1
            long   playId
            long   0
            short  数据长度 = len(数据体) - 2
            short  op
            bytes  数据体（明文，不加密）
        """
        play_id = self.play_id if play_id is None else play_id
        header = f"{self.c_version}`{self.c_type}`{self.channel_id}"
        body = _wutf(header)
        body += _wlong(int(time.time() * 1000))
        body += _wbyte(1)
        body += _wlong(play_id) + _wlong(0)
        body += _wshort(len(data) - 2) + _wshort(op) + data
        req = urllib.request.Request(self.game_url, data=body, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.read()

    def send_op_raw(self, op, data=b""):
        """业务操作（不加密、无签名）"""
        return self._parse_resp(self._game_post_raw(op, data))

    def send_ops_raw(self, ops):
        """★ v3：一个 HTTP POST 塞多个业务包（实测上限 120 个/请求，130 个被拒）
        结构同 _game_post_raw，只把开头「包数量」改成 len(ops)。
        ⚠️ 真机怪癖：长度字段是 short(len(data) - 2)，不是 len(data)！"""
        body = _wutf("%s`%s`%s" % (self.c_version, self.c_type, self.channel_id))
        body += _wlong(int(time.time() * 1000)) + _wbyte(len(ops))
        for op, data in ops:
            body += _wlong(self.play_id) + _wlong(0)
            body += _wshort(len(data) - 2) + _wshort(op) + data
        req = urllib.request.Request(self.game_url, data=body, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.read()

    def send_ops(self, ops):
        """批量业务操作（不加密、无签名），返回解析后的包列表"""
        return self._parse_resp(self.send_ops_raw(ops))

    @staticmethod
    def _parse_resp(resp):
        out, o = [], 0
        if len(resp) < 2:
            return out
        ng = resp[o]; o += 1
        for _ in range(ng):
            if o >= len(resp): break
            np = resp[o]; o += 1
            for _ in range(np):
                if o + 20 > len(resp): break
                play = struct.unpack(">q", resp[o:o+8])[0]; o += 8
                uid = struct.unpack(">q", resp[o:o+8])[0]; o += 8
                enc = resp[o]; o += 1
                ln = struct.unpack(">i", resp[o:o+4])[0]; o += 4
                op = struct.unpack(">H", resp[o:o+2])[0]; o += 2
                frag = resp[o]; o += 1
                data = resp[o:o+ln]; o += ln
                if enc:
                    data = decrypt(data)
                out.append({"play": play, "uid": uid, "enc": enc, "op": op,
                            "signed": op - 65536 if op > 32767 else op, "data": data})
        return out

    def enter_game(self):
        data = _wutf(self.sub_token) + _wutf(self.session) + _wutf(self.channel_id)
        resp = self._game_post([(4099, data)])
        for p in self._parse_resp(resp):
            if p["signed"] == -32765:
                b = p["data"]
                code = b[0]
                ln = struct.unpack(">H", b[1:3])[0]
                msg = b[3:3+ln].decode("utf-8", "replace")
                self.play_id = struct.unpack(">q", b[3+ln:3+ln+8])[0]
                return {"code": code, "msg": msg, "play_id": self.play_id}
        return None

    def game_login(self):
        resp = self._game_post([(4100, _wlong(-1))], play_id=self.play_id)
        return self._parse_resp(resp)

    def send_op(self, op, data=b""):
        resp = self._game_post([(op, data)], play_id=self.play_id)
        return self._parse_resp(resp)


# ==================== 常量 ====================
TROOP = {0: "民兵", 1: "弩兵", 2: "弓兵", 3: "轻骑兵", 4: "弩车", 5: "冲城车",
         6: "轻步兵", 7: "近卫兵", 8: "重步兵", 9: "弩骑兵", 10: "重骑兵",
         11: "铁骑兵", 12: "投石车", 13: "重弩车", 14: "强弩兵", 15: "骁骑兵"}
CLASS = {0: "步", 1: "弓", 2: "弓", 3: "骑", 4: "车", 5: "车", 6: "步", 7: "步",
         8: "步", 9: "骑", 10: "骑", 11: "骑", 12: "车", 13: "车", 14: "弓", 15: "骑"}
MAP_W, MAP_H = 187, 56          # 登录时自动探测到的「本区真实尺寸」（仅用于显示/告警）
SCAN_W, SCAN_H = 250, 62        # ★ 扫描上界：按主人指示「写死 0,0 ~ 249,61」，两种区一网打尽
ANCHOR_STEP = 6                 # 每个锚点覆盖 [x,x+5] × [y,y+5]
BATCH_MAX = 120                 # 一个 POST 最多 120 个包（实测 130 个被服务端拒绝）
OP_REQ, OP_RESP = 5440, 5440 + 0x7000
MAP_INFO = {"w": 187, "h": 56, "src": "默认(未探测)"}

current_task = {"running": False, "progress": "待机中", "results": [],
                "total": 0, "done": 0, "found": 0, "area": ""}

# ==================== 登录会话（常驻，不重复登录）====================
SESSION = {
    "client": None,      # KingClient 实例，登录一次后一直复用
    "logged": False,
    "user": "",
    "pwd": "",           # 用于掉线后自动重连
    "area_key": "",      # 用户填的区服号
    "area": "",
    "host": "",
    "login_time": 0,
    "hb_thread": None,   # 心跳线程
    "hb_last": 0,        # 上次心跳成功时间
    "hb_fail": 0,        # 连续心跳失败次数
    "hb_ok": True,
    "offline_reason": "",   # 掉线原因
    "offline_time": 0,      # 掉线时刻
    "auto_relogin": True,   # 掉线自动重连
    "relogin_count": 0,     # 重连次数
}
_LOCK = threading.Lock()


def 标记掉线(reason):
    """统一的掉线处理：置位 + 记录原因时间"""
    if SESSION["logged"]:
        SESSION["offline_time"] = time.time()
    SESSION["logged"] = False
    SESSION["hb_ok"] = False
    SESSION["offline_reason"] = reason
    print(f"⚠️ 掉线：{reason}")


def 尝试重连():
    """掉线后用缓存的账号密码静默重连一次"""
    if not SESSION["auto_relogin"] or not SESSION["user"]:
        return False
    try:
        ok, msg, _ = 执行登录(SESSION["user"], SESSION["pwd"],
                              SESSION["area_key"], _is_relogin=True)
        if ok:
            SESSION["relogin_count"] += 1
            SESSION["offline_reason"] = ""
            print(f"🔄 自动重连成功（第 {SESSION['relogin_count']} 次）")
            return True
        SESSION["offline_reason"] = f"自动重连失败：{msg}"
    except Exception as e:
        SESSION["offline_reason"] = f"自动重连异常：{e}"
    return False


def _心跳循环():
    """
    每 45 秒心跳一次，三重掉线判定：
      ① 请求异常（网络断/服务端拒绝）
      ② 响应封包含 -1/-3/-4/-5 → 被顶号或账号异常（主人遇到的挤号就是这种）
      ③ validate.action 探活失败 → 通行证会话已失效
    """
    while SESSION["client"]:
        for _ in range(45):
            if not SESSION["logged"] and not SESSION["auto_relogin"]:
                return
            time.sleep(1)
        if current_task["running"]:
            continue          # 搜索中本身就有流量，跳过心跳
        if not SESSION["logged"]:
            if SESSION["auto_relogin"]:
                尝试重连()
            continue
        try:
            with _LOCK:
                pk = SESSION["client"].send_op(25215, b"\x00")

            # ② 检查是否被踢（关键！服务端踢人后仍会回包，只是回错误码）
            kick = 检查踢下线(pk)
            if kick:
                标记掉线(kick)
                尝试重连()
                continue

            if not pk:
                raise RuntimeError("心跳无响应")

            # ③ 每 4 次心跳（约 3 分钟）用 validate.action 做一次通行证探活
            SESSION["hb_tick"] = SESSION.get("hb_tick", 0) + 1
            if SESSION["hb_tick"] % 4 == 0:
                if not 会话探活(SESSION["client"].session):
                    标记掉线("通行证会话已失效（validate 探活失败，多为异地登录顶号）")
                    尝试重连()
                    continue

            SESSION["hb_last"] = time.time()
            SESSION["hb_fail"] = 0
            SESSION["hb_ok"] = True
        except Exception as e:
            SESSION["hb_fail"] += 1
            SESSION["hb_ok"] = False
            print(f"⚠️ 心跳失败 {SESSION['hb_fail']}/2：{e}")
            if SESSION["hb_fail"] >= 2:
                标记掉线(f"心跳连续失败（{e}）")
                尝试重连()


def 执行登录(user, pwd, area_key, _is_relogin=False):
    """登录一次并常驻。已登录同账号同区则直接复用。"""
    if (not _is_relogin and SESSION["logged"] and SESSION["client"]
            and SESSION["user"] == user
            and str(area_key).strip().replace("区", "") in SESSION["area"]):
        return True, f"已在线：{SESSION['area']}（复用会话，未重复登录）", SESSION["area"]

    session, sub_token, areas = 取区服列表(user, pwd)
    if not session or not areas:
        return False, "登录失败：账号或密码错误", ""
    m = 匹配区服(areas, area_key)
    if not m:
        return False, "未找到区服「%s」。可用：%s" % (
            area_key, "、".join(a[0] for a in areas[:15])), ""
    area_name, host, port = m

    c = KingClient(user, pwd, game_host=host, game_port=port)
    c.session, c.sub_token = session, sub_token
    info = c.enter_game()
    if not info:
        return False, "进入游戏失败（该区可能没有角色）", ""
    c.game_login()
    SESSION["client"] = c          # 先挂上，供 探测地图尺寸 使用
    探测地图尺寸()                  # ★ 每个区地图尺寸不同，登录后立刻自动识别

    SESSION.update(client=c, logged=True, user=user, pwd=pwd,
                   area_key=area_key, area=area_name,
                   host=f"{host}:{port}",
                   hb_last=time.time(), hb_ok=True, hb_fail=0,
                   offline_reason="", offline_time=0)
    if not _is_relogin:
        SESSION["login_time"] = time.time()
        SESSION["relogin_count"] = 0
    if not SESSION["hb_thread"] or not SESSION["hb_thread"].is_alive():
        t = threading.Thread(target=_心跳循环, daemon=True)
        SESSION["hb_thread"] = t
        t.start()
    return True, f"登录成功：{area_name} ({host}:{port})，心跳保活已开启", area_name


# ==================== 解析与筛选 ====================
def ring_points(cx, cy, n):
    if n <= 0:
        return [(cx, cy)]
    pts = []
    for dy in range(-n, n + 1):
        for dx in range(-n, n + 1):
            if max(abs(dx), abs(dy)) == n:
                pts.append((cx + dx, cy + dy))
    return pts

def 越界(x, y):
    return not (0 <= x < MAP_W and 0 <= y < MAP_H)


def 探测地图尺寸():
    """★★★ 关键（2026-09-13 定案）：地图尺寸【每个区都不一样】！
    318 区 = 187×56；主人看过的另一个区 = 250×62（所以那边 249,61 能搜出山贼）。
    34112 响应头前 4 字节 = 本区真实 (w,h)，直接读，【千万不要硬编码】。"""
    global MAP_W, MAP_H
    c = SESSION.get("client")
    if not c:
        return MAP_W, MAP_H
    try:
        pk = c.send_op_raw(OP_REQ, struct.pack(">hhh", 0, 0, 0))
        b = next((z["data"] for z in pk if z["op"] == OP_RESP), None)
        if b and len(b) >= 4:
            w, h = struct.unpack_from(">hh", b, 0)
            if 1 <= w <= 4096 and 1 <= h <= 4096:
                MAP_W, MAP_H = w, h
                MAP_INFO.update(w=w, h=h, src="响应自动识别")
                print("🗺️  本区地图尺寸：%d×%d（自动识别，坐标范围 0..%d / 0..%d）"
                      % (w, h, w - 1, h - 1))
                return w, h
    except Exception as e:
        print("⚠️ 地图尺寸探测失败，沿用 %d×%d：%s" % (MAP_W, MAP_H, e))
    return MAP_W, MAP_H

def 功能_取山贼数据(data):
    o = 0
    def i16():
        nonlocal o; v = struct.unpack_from(">h", data, o)[0]; o += 2; return v
    def u8():
        nonlocal o; v = data[o]; o += 1; return v
    def i32():
        nonlocal o; v = struct.unpack_from(">i", data, o)[0]; o += 4; return v
    def i64():
        nonlocal o; v = struct.unpack_from(">q", data, o)[0]; o += 8; return v
    def utf():
        nonlocal o; n = struct.unpack_from(">H", data, o)[0]; o += 2
        v = data[o:o + n].decode("utf-8", "replace"); o += n; return v
    w, h, cnt = i16(), i16(), u8()
    out = []
    for _ in range(cnt):
        e = dict(id=i64(), name=utf(), A=i16(), lvl=u8(), x=i16(), y=i16(),
                 desc=utf(), E=i32(), F=i32())
        n1 = u8(); e["drops"] = [(u8(), i16(), u8()) for _ in range(n1)]
        n2 = u8(); e["gens"] = [dict(nm=utf(), s1=i16(), s2=i16(),
                                     b1=u8(), b2=u8(), b3=u8(), i1=i32()) for _ in range(n2)]
        out.append(e)
    return w, h, cnt, out

def 队伍统计(item):
    cnt = {"步": 0, "弓": 0, "骑": 0, "车": 0}
    names = []
    for g in item["gens"]:
        tid = g.get("b3", 0)
        cnt[CLASS.get(tid, "步")] += 1
        names.append(TROOP.get(tid, f"?{tid}"))
    return cnt, names

def 兵种摘要(item):
    """只输出兵种，相同兵种合并计数：民兵×2、铁骑兵"""
    order, cnt = [], {}
    for g in item["gens"]:
        nm = TROOP.get(g.get("b3", 0), f"?{g.get('b3',0)}")
        if nm not in cnt:
            order.append(nm)
            cnt[nm] = 0
        cnt[nm] += 1
    return "、".join(nm if cnt[nm] == 1 else f"{nm}×{cnt[nm]}" for nm in order)


def 是否符合(item, cfg):
    # 1) 等级多选
    if cfg["levels"] and item["lvl"] not in cfg["levels"]:
        return False
    cnt, names = 队伍统计(item)
    # 2) 兵种下拉（单选）：不限 / 某个具体兵种 / 某个大类
    t = cfg["troop"]
    if t and t != "不限":
        if t in ("步", "弓", "骑", "车"):          # 大类模式：队伍必须全是该大类
            if cnt.get(t, 0) != len(item["gens"]) or not item["gens"]:
                return False
        else:                                       # 具体兵种模式：队伍必须全是该兵种
            if not names or any(nm != t for nm in names):
                return False
    # 3) 兵种大类上限
    for k, limit in cfg["class_max"].items():
        if limit is not None and cnt.get(k, 0) > limit:
            return False
    # 4) 掉落物关键词（多选，任一命中）
    if cfg["drops"]:
        if not any(d in item["desc"] for d in cfg["drops"]):
            return False
    return True


# ==================== 后台任务 ====================
def 执行筛选任务(p):
    """只做搜索，不登录。使用已常驻的 SESSION['client']"""
    global current_task
    current_task.update(running=True, progress="准备搜索...", results=[],
                        total=0, done=0, found=0, area=SESSION["area"])
    try:
        if not SESSION["logged"] or not SESSION["client"]:
            current_task["progress"] = "❌ 尚未登录，请先点『登录』按钮"
            return
        c = SESSION["client"]

        cx, cy = int(p.get("center_x", 0)), int(p.get("center_y", 0))
        rings = int(p.get("rings", 3))
        delay = float(p.get("delay", 0.25))

        levels = set(int(v) for v in p.get("levels", "").split(",") if v.strip().isdigit())
        troop = p.get("troop", "不限").strip()
        drops = [v for v in p.get("drops", "").split(",") if v.strip()]
        class_max = {}
        for k in ["步", "弓", "骑", "车"]:
            v = p.get(f"max_{k}", "").strip()
            class_max[k] = int(v) if v.isdigit() else None
        cfg = {"levels": levels, "troop": troop, "drops": drops,
               "class_max": class_max}

        探测地图尺寸()   # 读本区真实尺寸（仅用于显示 + 超界告警）
        SW = max(SCAN_W, MAP_W)      # 扫描上界：写死 250×62；万一本区更大，自动扩到本区尺寸
        SH = max(SCAN_H, MAP_H)
        if MAP_W > SCAN_W or MAP_H > SCAN_H:
            current_task["progress"] = "⚠️ 本区地图 %d×%d 比写死的 250×62 还大，已自动扩大扫描范围！" % (
                MAP_W, MAP_H)

        # ★ v3：全图平铺锚点（每个锚点覆盖 6×6 格）+ 批量发包 + 无 sleep
        anchors = [(x, y) for y in range(0, SH, ANCHOR_STEP)
                   for x in range(0, SW, ANCHOR_STEP)]
        current_task["total"] = len(anchors)
        current_task["progress"] = "全图扫描 0,0~%d,%d（本区实测 %d×%d）｜锚点 %d 个｜每包 %d 个" % (
            SW - 1, SH - 1, MAP_W, MAP_H, len(anchors), BATCH_MAX)

        # 模式自检：同一点连查两次，结果不一致 = 枚举模式（<30 级号，服务端忽略坐标）
        try:
            _r1 = c.send_op_raw(OP_REQ, struct.pack(">hhh", 0, 0, 0))
            _r2 = c.send_op_raw(OP_REQ, struct.pack(">hhh", 0, 0, 0))
            _b1 = next((z["data"] for z in _r1 if z["op"] == OP_RESP), b"")
            _b2 = next((z["data"] for z in _r2 if z["op"] == OP_RESP), b"")
            _s1 = [q["id"] for q in 功能_取山贼数据(_b1)[3]]
            _s2 = [q["id"] for q in 功能_取山贼数据(_b2)[3]]
            if _s1 != _s2:
                current_task["progress"] += "｜⚠️ 检测到【枚举模式】：本号可能 <30 级，坐标会被服务端忽略！"
        except Exception:
            pass

        seen, hit, fail = set(), [], 0
        idx = 0
        for i in range(0, len(anchors), BATCH_MAX):
            if not current_task["running"]:
                current_task["progress"] = "已停止"
                break
            chunk = anchors[i:i + BATCH_MAX]
            try:
                with _LOCK:
                    pk = c.send_ops([(OP_REQ, struct.pack(">hhh", 0, x, y)) for (x, y) in chunk])
                # 搜索途中被顶号 → 立即停止并提示
                kick = 检查踢下线(pk)
                if kick:
                    标记掉线(kick)
                    current_task["progress"] = f"🔴 搜索中断：{kick}"
                    break
                got = [z["data"] for z in pk if z["op"] == OP_RESP]
                if len(got) < len(chunk):
                    fail += 1
                    if fail >= 3 and not 会话探活(c.session):
                        标记掉线("批量回包缺失且探活失败（疑似已被顶号）")
                        current_task["progress"] = "🔴 搜索中断：检测到掉线，请重新登录"
                        break
                else:
                    fail = 0
                for _body in got:
                    if len(_body) < 5:
                        continue
                    for it in 功能_取山贼数据(_body)[3]:
                        if it["id"] in seen:
                            continue
                        seen.add(it["id"])
                        if 是否符合(it, cfg):
                            hit.append({
                                "x": it["x"], "y": it["y"],
                                "level": it["lvl"],
                                "distance": round(math.hypot(it["x"] - cx, it["y"] - cy), 1),
                                "desc": it["desc"],
                                "gens": 兵种摘要(it),
                            })
            except Exception as e:
                fail += 1
                if fail >= 3:
                    标记掉线(f"批量请求连续失败（{e}）")
                    current_task["progress"] = f"🔴 搜索中断：连接异常，已掉线（{e}）"
                    break
            idx = min(i + len(chunk), len(anchors))
            current_task["done"] = idx
            current_task["found"] = len(hit)
            current_task["progress"] = "全图扫描中… %d/%d 锚点，山贼 %d 只，已匹配 %d 只" % (
                idx, len(anchors), len(seen), len(hit))

        hit.sort(key=lambda t: t["distance"])
        current_task["results"] = hit
        if current_task["running"] and SESSION["logged"]:
            current_task["progress"] = f"✅ 完成！扫描 {len(seen)} 只山贼，符合条件 {len(hit)} 只（会话保持在线）"
    except Exception as e:
        current_task["progress"] = f"❌ 错误：{e}"
    finally:
        current_task["running"] = False


# ==================== 网页 ====================
HTML = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>普通山贼筛选工具 v3</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:"Microsoft YaHei",Arial,sans-serif;background:linear-gradient(135deg,#667eea,#764ba2);padding:20px;min-height:100vh}
.container{max-width:1150px;margin:0 auto;background:#fff;border-radius:14px;box-shadow:0 8px 32px rgba(0,0,0,.15);overflow:hidden}
.header{background:linear-gradient(135deg,#667eea,#764ba2);color:#fff;padding:26px;text-align:center}
.header h1{font-size:28px;margin-bottom:6px}
.header p{opacity:.9;font-size:14px}
.content{padding:26px}
.sec{background:#f8f9fa;padding:18px;border-radius:10px;margin-bottom:16px}
.sec h3{color:#667eea;margin-bottom:14px;font-size:17px}
.row{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:14px;margin-bottom:12px}
.g{display:flex;flex-direction:column}
.g label{font-size:13px;color:#555;margin-bottom:5px;font-weight:500}
.g input,.g select{padding:9px;border:1px solid #ddd;border-radius:6px;font-size:14px}
.g input:focus,.g select:focus{outline:none;border-color:#667eea}
.chips{display:flex;flex-wrap:wrap;gap:8px}
.chip{position:relative}
.chip input{display:none}
.chip span{display:inline-block;padding:6px 13px;border:1px solid #d6d6e7;border-radius:16px;font-size:13px;cursor:pointer;background:#fff;user-select:none;transition:.15s}
.chip input:checked+span{background:#667eea;color:#fff;border-color:#667eea}
.mini{font-size:12px;color:#999;margin:6px 0 8px}
.btns{display:flex;gap:10px;align-items:center}
.btn{background:linear-gradient(135deg,#667eea,#764ba2);color:#fff;border:none;padding:12px 28px;border-radius:6px;font-size:15px;cursor:pointer;transition:.2s}
.btn:hover{transform:translateY(-2px)}
.btn:disabled{background:#ccc;cursor:not-allowed;transform:none}
.btn.gray{background:#adb5bd}
.link{background:none;border:none;color:#667eea;cursor:pointer;font-size:13px;text-decoration:underline}
.progress{background:#f1f3f9;padding:14px;border-radius:8px;margin:16px 0;display:none}
.progress.show{display:block}
.ptext{color:#667eea;font-weight:500;margin-bottom:9px;font-size:14px}
.pbar{height:7px;background:#e0e0e0;border-radius:4px;overflow:hidden}
.pfill{height:100%;background:linear-gradient(90deg,#667eea,#764ba2);width:0;transition:width .3s}
.rhead{display:flex;justify-content:space-between;align-items:center;margin:18px 0 12px}
.rhead h3{color:#667eea;font-size:18px}
.stats{color:#888;font-size:13px}
table{width:100%;border-collapse:collapse;font-size:13.5px}
th{background:#f1f3f9;padding:11px;text-align:left;color:#555;font-weight:600;position:sticky;top:0}
td{padding:10px 11px;border-top:1px solid #f0f0f0}
tr:hover{background:#fafbff}
.coord{color:#667eea;font-weight:600;cursor:pointer}
.wrap{max-height:520px;overflow:auto;border:1px solid #eee;border-radius:8px}
.areas{font-size:13px;color:#555;background:#fff;border:1px dashed #ccd;border-radius:6px;padding:10px;margin-top:8px;display:none}
.status{margin-top:10px;padding:9px 13px;border-radius:6px;font-size:13.5px;font-weight:500}
.status.off{background:#fdecea;color:#b3261e}
.status.on{background:#e7f7ed;color:#137333}
.status.wait{background:#fff6e0;color:#8a6100}
.alert{display:none;background:#fdecea;border:1px solid #f5c2c0;border-left:5px solid #d93025;
 color:#b3261e;padding:14px 16px;border-radius:8px;margin-bottom:16px;font-size:14.5px;
 font-weight:600;align-items:center;gap:12px;animation:blink 1.2s ease-in-out 3}
.alert.show{display:flex}
.alert button{margin-left:auto;background:#d93025;color:#fff;border:none;padding:7px 15px;
 border-radius:5px;cursor:pointer;font-size:13px;white-space:nowrap}
@keyframes blink{0%,100%{background:#fdecea}50%{background:#ffd9d6}}
</style></head><body>
<div class="container">
<div class="header"><h1>🎯 普通山贼筛选工具 v3</h1><p>全图扫描 0,0~249,61 · 批量 120 包/请求 · 2~4 秒扫完全区</p></div>
<div class="content">
<div id="alert" class="alert"><span id="alertTxt"></span>
  <button type="button" id="alertLogin">立即重新登录</button>
  <button type="button" id="alertClose" style="background:#888">关闭</button></div>
<form id="f">

<div class="sec"><h3>📝 账号 / 区服（登录一次，全程保持在线）</h3>
<div class="row">
  <div class="g"><label>账号</label><input name="user" value="Lgd2936" required></div>
  <div class="g"><label>密码</label><input type="password" name="pwd" value="L12345" required></div>
  <div class="g"><label>区服（只填数字，如 328）</label><input name="area" value="328" required></div>
</div>
<div class="btns" style="margin-top:6px">
  <button type="button" class="btn" id="login">🔑 登录</button>
  <button type="button" class="btn gray" id="logout">🚪 登出</button>
  <button type="button" class="link" id="chk">🩺 立即检测在线</button>
  <button type="button" class="link" id="qa">🔍 查询我的区服列表</button>
  <label style="font-size:13px;color:#555;display:flex;align-items:center;gap:5px">
    <input type="checkbox" id="ar" checked style="width:auto"> 掉线自动重连</label>
</div>
<div id="statusBar" class="status off">● 未登录</div>
<div class="areas" id="areaBox"></div>
</div>

<div class="sec"><h3>🎯 搜索范围</h3>
<div class="mini">★ v3：<b>全图扫描</b>，坐标写死 <b>0,0 ~ 249,61</b>（187×56 与 250×62 两种区通吃），
每个锚点覆盖 6×6 格，<b>每请求批量 120 个包、无间隔</b>，全图约 2~3 秒喵~<br>
中心坐标只用来<b>按距离排序</b>，填本城坐标即可。</div>
<div class="row">
  <div class="g"><label>参考点 X（仅排序用）</label><input type="number" name="center_x" value="93" required></div>
  <div class="g"><label>参考点 Y（仅排序用）</label><input type="number" name="center_y" value="28" required></div>
  <div class="g"><label>扫描上界</label><input type="text" value="0,0 ~ 249,61（写死）" disabled></div>
  <div class="g"><label>批量 / 请求</label><input type="text" value="120 个包" disabled></div>
</div></div>

<div class="sec"><h3>⚙️ 筛选条件</h3>

<div class="mini">山贼等级（可多选，不选=全部）</div>
<div class="chips" id="lvs"></div>

<div class="row" style="margin-top:14px">
  <div class="g"><label>守将兵种</label>
    <select name="troop" id="troopSel"></select></div>
  <div class="g"><label>步 ≤</label><input name="max_步" placeholder="不限"></div>
  <div class="g"><label>弓 ≤</label><input name="max_弓" placeholder="不限"></div>
  <div class="g"><label>骑 ≤</label><input name="max_骑" placeholder="不限"></div>
  <div class="g"><label>车 ≤</label><input name="max_车" placeholder="不限"></div>
</div>
<div class="mini">兵种下拉：选具体兵种＝队伍必须全是该兵种；选大类＝队伍全是该大类。右侧上限留空＝不限。</div>

<div class="mini" style="margin-top:10px">掉落物（可多选，命中任一即可；不选=全部）</div>
<div class="chips" id="dps"></div>
</div>

<div class="btns">
  <button type="submit" class="btn" id="go">🚀 开始搜索</button>
  <button type="button" class="btn gray" id="stop" disabled>⏹ 停止</button>
  <button type="button" class="link" id="dl">⬇ 导出 TXT</button>
</div>
</form>

<div class="progress" id="pg">
  <div class="ptext" id="pt">准备中…</div>
  <div class="pbar"><div class="pfill" id="pf"></div></div>
</div>

<div id="res" style="display:none">
  <div class="rhead"><h3>📋 搜索结果（按距离排序）</h3><span class="stats" id="st"></span></div>
  <div class="wrap"><table>
    <thead><tr><th>#</th><th>坐标</th><th>山贼</th><th>距离</th><th>兵种</th><th>掉落</th></tr></thead>
    <tbody id="tb"></tbody></table></div>
</div>

</div></div>
<script>
const TROOPS=["民兵","弩兵","弓兵","轻骑兵","弩车","冲城车","轻步兵","近卫兵","重步兵","弩骑兵","重骑兵","铁骑兵","投石车","重弩车","强弩兵","骁骑兵"];
const DROPS=["寶箱","裝備","資源","大批資源","許多資源","很多資源","道具"];
function chips(box,arr,name){document.getElementById(box).innerHTML=arr.map(v=>
 `<label class="chip"><input type="checkbox" name="${name}" value="${v}"><span>${v}</span></label>`).join('');}
chips('lvs',[1,2,3,4,5,6,7,8,9,10],'levels');
chips('dps',DROPS,'drops');
document.getElementById('troopSel').innerHTML=
 '<option value="不限">不限（全部兵种）</option>'
 +'<optgroup label="按大类">'+["步","弓","骑","车"].map(v=>`<option value="${v}">全${v}兵</option>`).join('')+'</optgroup>'
 +'<optgroup label="按具体兵种">'+TROOPS.map(v=>`<option value="${v}">${v}</option>`).join('')+'</optgroup>';

const f=document.getElementById('f'),go=document.getElementById('go'),stop=document.getElementById('stop');
const pg=document.getElementById('pg'),pt=document.getElementById('pt'),pf=document.getElementById('pf');
const res=document.getElementById('res'),st=document.getElementById('st'),tb=document.getElementById('tb');
const sb=document.getElementById('statusBar'),btnLogin=document.getElementById('login'),btnOut=document.getElementById('logout');
const alertBox=document.getElementById('alert'),alertTxt=document.getElementById('alertTxt');
let last=[],online=false,wasOnline=false;

function setStatus(cls,txt){sb.className='status '+cls;sb.textContent=txt;}
function showAlert(msg){
  alertTxt.textContent='🔴 已掉线：'+msg;
  alertBox.classList.add('show');
  if(document.title.indexOf('掉线')<0)document.title='🔴 已掉线 - 山贼筛选工具';
  try{beep();}catch(e){}
}
function hideAlert(){alertBox.classList.remove('show');document.title='普通山贼筛选工具 v2';}
function beep(){
  const a=new(window.AudioContext||window.webkitAudioContext)();
  const o=a.createOscillator(),g=a.createGain();
  o.connect(g);g.connect(a.destination);o.frequency.value=660;o.type='sine';
  g.gain.setValueAtTime(.25,a.currentTime);
  g.gain.exponentialRampToValueAtTime(.001,a.currentTime+.5);
  o.start();o.stop(a.currentTime+.5);
}

async function refreshSession(){
  let d;try{d=await(await fetch('/session')).json();}catch(e){
    setStatus('off','● 无法连接工具后端（程序是否已关闭？）');online=false;go.disabled=true;return;}
  online=d.logged;
  if(d.logged){
    hideAlert();wasOnline=true;
    const hb=d.hb_ago<0?'—':(d.hb_ago+'秒前');
    const re=d.relogin_count>0?`　已自动重连${d.relogin_count}次`:'';
    setStatus('on',`● 在线中 — ${d.area} ${d.host}　在线 ${d.uptime}　心跳 ${hb}${re}`);
  }else{
    const r=d.offline_reason||'未登录';
    if(d.offline_reason&&d.offline_reason!=='主动登出'){
      setStatus('off',`● 已掉线 — ${r}（${d.offline_ago}秒前）`);
      showAlert(r);
    }else{
      setStatus('off','● '+(d.offline_reason==='主动登出'?'已登出':'未登录'));
      hideAlert();
    }
    wasOnline=false;
  }
  go.disabled=!online;
}
refreshSession();setInterval(refreshSession,5000);

document.getElementById('alertClose').onclick=()=>alertBox.classList.remove('show');
document.getElementById('alertLogin').onclick=()=>btnLogin.click();
document.getElementById('ar').onchange=e=>
  fetch('/autorelogin',{method:'POST',body:new URLSearchParams({on:e.target.checked?'1':'0'})});
document.getElementById('chk').onclick=async()=>{
  setStatus('wait','● 检测中…');
  const d=await(await fetch('/check',{method:'POST'})).json();
  await refreshSession();
  if(d.ok)alert('✅ '+d.msg);
};

btnLogin.onclick=async()=>{
  setStatus('wait','● 登录中…');btnLogin.disabled=true;hideAlert();
  const p=new URLSearchParams({user:f.user.value,pwd:f.pwd.value,area:f.area.value});
  const d=await(await fetch('/login',{method:'POST',body:p})).json();
  btnLogin.disabled=false;
  if(d.ok){await refreshSession();}else{setStatus('off','● '+d.msg);}
};
btnOut.onclick=async()=>{await fetch('/logout',{method:'POST'});hideAlert();refreshSession();};

document.getElementById('qa').onclick=async()=>{
  const b=document.getElementById('areaBox');b.style.display='block';b.textContent='查询中…';
  const p=new URLSearchParams({user:f.user.value,pwd:f.pwd.value});
  const r=await fetch('/areas',{method:'POST',body:p});const d=await r.json();
  b.innerHTML=d.ok?('我的区服：<b>'+d.areas.map(a=>a[0]).join(' ｜ ')+'</b>'):('❌ '+d.msg);
};

function pack(){
  const fd=new FormData(f);const o={};
  for(const[k,v]of fd.entries()){o[k]=o[k]?o[k]+','+v:v;}
  ['levels','drops'].forEach(k=>{if(!(k in o))o[k]='';});
  return new URLSearchParams(o);
}

f.onsubmit=async e=>{
  e.preventDefault();
  if(!online){alert('请先点『登录』喵~');return;}
  go.disabled=true;stop.disabled=false;go.textContent='⏳ 搜索中…';
  pg.classList.add('show');res.style.display='none';
  await fetch('/start',{method:'POST',body:pack()});
  const t=setInterval(async()=>{
    const d=await(await fetch('/status')).json();
    pt.textContent=(d.area?('['+d.area+'] '):'')+d.progress;
    pf.style.width=d.total?Math.min(100,d.done/d.total*100)+'%':'0';
    if(d.progress.indexOf('🔴')===0){pt.style.color='#d93025';}else{pt.style.color='#667eea';}
    if(!d.running){clearInterval(t);stop.disabled=true;go.textContent='🚀 开始搜索';show(d.results||[]);refreshSession();}
  },500);
};
stop.onclick=()=>fetch('/stop',{method:'POST'});

function show(d){
  last=d;res.style.display='block';st.textContent=`共 ${d.length} 只符合条件`;
  tb.innerHTML=d.length?d.map((i,n)=>`<tr><td>${n+1}</td>
   <td class="coord" onclick="navigator.clipboard.writeText('${i.x},${i.y}')">(${i.x},${i.y})</td>
   <td>${i.level}级山贼</td>
   <td>${i.distance}</td><td>${i.gens}</td><td>${i.desc}</td></tr>`).join('')
   :'<tr><td colspan="6" style="text-align:center;padding:30px;color:#999">没有符合条件的山贼</td></tr>';
}
document.getElementById('dl').onclick=()=>{
  if(!last.length)return alert('还没有结果喵~');
  const txt=last.map(i=>`(${i.x},${i.y})\t${i.level}级山贼\t距离${i.distance}\t${i.gens}\t${i.desc}`).join('\\n');
  const a=document.createElement('a');
  a.href=URL.createObjectURL(new Blob([txt],{type:'text/plain'}));a.download='记录山贼.txt';a.click();
};
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, ctype, body):
        self.send_response(code)
        self.send_header('Content-type', ctype)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == '/':
            self._send(200, 'text/html; charset=utf-8', HTML.encode('utf-8'))
        elif self.path == '/status':
            self._send(200, 'application/json; charset=utf-8',
                       json.dumps(current_task, ensure_ascii=False).encode('utf-8'))
        elif self.path == '/session':
            up = int(time.time() - SESSION["login_time"]) if SESSION["login_time"] else 0
            off = int(time.time() - SESSION["offline_time"]) if SESSION["offline_time"] else 0
            hb_ago = int(time.time() - SESSION["hb_last"]) if SESSION["hb_last"] else -1
            out = {"logged": SESSION["logged"], "user": SESSION["user"],
                   "area": SESSION["area"], "host": SESSION["host"],
                   "hb_ok": SESSION["hb_ok"],
                   "hb_ago": hb_ago,
                   "hb_fail": SESSION["hb_fail"],
                   "offline_reason": SESSION["offline_reason"],
                   "offline_ago": off,
                   "relogin_count": SESSION["relogin_count"],
                   "auto_relogin": SESSION["auto_relogin"],
                   "uptime": f"{up//3600}时{up%3600//60}分{up%60}秒"}
            self._send(200, 'application/json; charset=utf-8',
                       json.dumps(out, ensure_ascii=False).encode('utf-8'))
        else:
            self.send_error(404)

    def do_POST(self):
        n = int(self.headers.get('Content-Length', 0))
        raw = self.rfile.read(n).decode('utf-8') if n else ''
        p = {k: v[0] for k, v in parse_qs(raw).items()}
        if self.path == '/login':
            try:
                ok, msg, area = 执行登录(p.get('user', '').strip(),
                                        p.get('pwd', '').strip(),
                                        p.get('area', '').strip())
            except Exception as e:
                ok, msg = False, f"登录异常：{e}"
            print(("✅ " if ok else "❌ ") + msg)
            self._send(200, 'application/json; charset=utf-8',
                       json.dumps({"ok": ok, "msg": msg}, ensure_ascii=False).encode('utf-8'))
        elif self.path == '/logout':
            SESSION.update(logged=False, client=None, area="", host="", user="",
                           pwd="", offline_reason="主动登出", offline_time=time.time())
            print("🚪 已登出")
            self._send(200, 'application/json', b'{"ok":true}')
        elif self.path == '/check':
            # 手动立即探活
            if not SESSION["client"]:
                out = {"ok": False, "msg": "尚未登录"}
            else:
                try:
                    with _LOCK:
                        pk = SESSION["client"].send_op(25215, b"\x00")
                    kick = 检查踢下线(pk)
                    if kick:
                        标记掉线(kick)
                        out = {"ok": False, "msg": kick}
                    elif not 会话探活(SESSION["client"].session):
                        标记掉线("通行证探活失败（疑似被顶号）")
                        out = {"ok": False, "msg": SESSION["offline_reason"]}
                    else:
                        SESSION["hb_ok"] = True
                        SESSION["hb_last"] = time.time()
                        SESSION["hb_fail"] = 0
                        out = {"ok": True, "msg": "会话正常，在线中"}
                except Exception as e:
                    标记掉线(f"探活异常：{e}")
                    out = {"ok": False, "msg": SESSION["offline_reason"]}
            self._send(200, 'application/json; charset=utf-8',
                       json.dumps(out, ensure_ascii=False).encode('utf-8'))
        elif self.path == '/autorelogin':
            SESSION["auto_relogin"] = p.get("on", "1") == "1"
            self._send(200, 'application/json', b'{"ok":true}')
        elif self.path == '/start':
            if not current_task["running"]:
                threading.Thread(target=执行筛选任务, args=(p,), daemon=True).start()
            self._send(200, 'application/json', b'{"ok":true}')
        elif self.path == '/stop':
            current_task["running"] = False
            self._send(200, 'application/json', b'{"ok":true}')
        elif self.path == '/areas':
            try:
                s, t, areas = 取区服列表(p.get('user', ''), p.get('pwd', ''))
                out = {"ok": True, "areas": areas} if (s and areas) else {"ok": False, "msg": "登录失败或无区服"}
            except Exception as e:
                out = {"ok": False, "msg": str(e)}
            self._send(200, 'application/json; charset=utf-8',
                       json.dumps(out, ensure_ascii=False).encode('utf-8'))
        else:
            self.send_error(404)

    def log_message(self, *a):
        pass


def start_server(port=8080):
    srv = HTTPServer(('0.0.0.0', port), Handler)
    print("=" * 66)
    print("【普通山贼筛选工具 - WebUI v2】单文件独立版")
    print("=" * 66)
    print(f"\n✅ 服务已启动：http://localhost:{port}")
    print("✅ 只需填 账号 / 密码 / 区服号，自动解析服务器地址")
    print("✅ 支持等级多选、兵种下拉、掉落物多选")
    print("\n按 Ctrl+C 停止\n")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止")
        srv.shutdown()


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8080)
    start_server(ap.parse_args().port)
