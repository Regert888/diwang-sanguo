"""帝王三国协议核心（精简版，从 v3 提取）"""
import struct, time, hashlib, urllib.request, threading

SALT = "FIC1atsuf30"
CHANNEL_ID = "0200000000"
C_VERSION = "1630107"
C_TYPE = "7054"
LOGIN_URL = "http://pass.dwsg.gameme5.com:8192/common/area/list.action"
VALIDATE_URL = "http://pass.dwsg.gameme5.com:8192/system/user/validate.action"
GAME_PATH = "/kingWapServer/HttpClient"
NO_ENC_OPS = {4096, 4098, 4101, 4118, 4099, 4097}
TARGET_ALL = "1,2,3,5,11,12,13,14,15,16,17,18,19,20,21,31,32,33,34,41,91"
KEY_RAW = bytes.fromhex("f33c2d941b8bef9e2cdcf7ee32bd3d18" "898c7c61a98389551a8f2b19a8fbeeeb")

def _wutf(s): b = s.encode("utf-8"); return struct.pack(">H", len(b)) + b
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
        if not line.strip(): continue
        parts = line.split("`")
        if len(parts) >= 4:
            name, url_str = parts[2], parts[3]
            if url_str.startswith("http://"): url_str = url_str[7:]
            url_str = url_str.split("/")[0]
            if ":" in url_str:
                host, port_str = url_str.split(":")[0], url_str.split(":")[1]
                port = int(port_str) if port_str.isdigit() else 25511
            else:
                host, port = url_str, 25511
            if host: areas.append((name, host, port))
    return session, sub_token, areas

def 匹配区服(areas, area_key):
    key = str(area_key).strip().replace("区", "").replace("區", "")
    for name, host, port in areas:
        n = name.replace("区", "").replace("區", "")
        if n == key: return name, host, port
    for name, host, port in areas:
        if key and key in name: return name, host, port
    return None

def 会话探活(session):
    try:
        url = f"{VALIDATE_URL}?session={session}&target=1,10"
        with urllib.request.urlopen(url, timeout=10) as r:
            txt = r.read().decode("utf-8", "replace").strip()
        parts = txt.split("`")
        return len(parts) >= 2 and parts[0] and len(parts[0]) > 8
    except: return False


KICK_OPS = {-1, -3, -4, -5}
KICK_MSG = {-1: "账号异常（可能已被顶号）",
            -3: "账号异常（会话失效）",
            -4: "账号异常（被服务端断开）",
            -5: "服务端要求退出游戏"}

def 检查踢下线(packets):
    for p in packets or []:
        if p["signed"] in KICK_OPS:
            return KICK_MSG.get(p["signed"], f"账号异常(op={p['signed']})")
    return None


# ====== 角色信息解析 ======
OP_角色资源 = 4128      # 铜钱/粮食/人口/资源点/宝藏
OP_角色状态 = 5128      # 加点返回：铜钱/粮食/等级/经验

def _扫中文串(data):
    """扫描 2 字节长度前缀 + UTF-8 字符串"""
    out, i, n = [], 0, len(data)
    while i < n - 2:
        ln = struct.unpack_from(">H", data, i)[0]
        if 2 <= ln <= 60 and i + 2 + ln <= n:
            try:
                s = data[i+2:i+2+ln].decode("utf-8")
            except Exception:
                i += 1; continue
            if s and all(0x20 <= ord(c) for c in s):
                out.append((i, ln, s))
                i += 2 + ln
                continue
        i += 1
    return out

# 第一串常是「登錄成功」这类状态串，需要跳过
_状态串 = ("登錄成功", "登录成功", "登入成功")

def 解析国家(packets):
    """从 loginBaseinfo(4099) 响应提取国家名（中文串里第 3 条：状态/角色名/国家）"""
    for p in packets or []:
        d = p.get("data") or b""
        if not (30 <= len(d) <= 300): continue
        strs = _扫中文串(d)
        if len(strs) >= 3:
            return strs[2][2]
    return ""

def 解析登录信息(packets):
    """从 gameLogin(4100) 响应提取 君主名 / 等级 / 国家"""
    info = {"charName": "", "level": 0, "kingdom": ""}
    # 优先取 gameLogin(op 4100 → resp 32772)，否则取最长包（公告包会干扰）
    cands = [p for p in (packets or []) if (p.get("data") or b"")]
    cands.sort(key=lambda p: (p["op"] == 32772, len(p["data"])), reverse=True)
    for p in cands:
        d = p["data"]
        if len(d) < 24: continue
        strs = [x for x in _扫中文串(d) if x[2] not in _状态串 and len(x[2]) <= 20]
        if not strs: continue
        off, ln, name = strs[0]
        info["charName"] = name
        # 等级 = 角色名之后紧跟的 1 字节（实测：嗷嗷嗷 → 07 = 7级）
        tail = off + 2 + ln
        if tail < len(d):
            info["level"] = d[tail]
        for off2, _, s2 in strs[1:]:       # 国家 = 名字之后第一条中文串
            if off2 > off:
                info["kingdom"] = s2
                break
        break
    return info


def 解析登录包武将(pkt_data):
    """从 gameLogin(4100) 包扫描中文串，识别武将名 + 技能描述"""
    def 纯中文(s):
        return s and all("\u4e00" <= ch <= "\u9fff" for ch in s)

    names = []
    for o in range(len(pkt_data) - 2):
        ln = struct.unpack_from(">H", pkt_data, o)[0]
        if 2 <= ln <= 50 and o + 2 + ln <= len(pkt_data):
            try:
                s = pkt_data[o + 2:o + 2 + ln].decode("utf-8")
            except Exception:
                continue
            if s:
                names.append((o, s))
    known = {}
    for idx, (off, sv) in enumerate(names):
        if not 纯中文(sv):
            continue
        if len(sv) < 2 or len(sv) > 4:
            continue
        if sv in ("洛陽", "大漢", "漢") or "基地" in sv:
            continue
        desc = ""
        for off2, sv2 in reversed(names[:idx]):
            if off2 >= off or off2 < off - 60:
                continue
            # 描述必须是干净可打印、且含中文
            if len(sv2) >= 5 and all(ch >= " " for ch in sv2) \
                    and any("\u4e00" <= c <= "\u9fff" for c in sv2):
                desc = sv2
                break
        known[off] = {"name": sv, "desc": desc}
    return [known[k] for k in sorted(known)]



def 解析登录包完整(pkt_data):
    """完整解析 gameLogin(4100) 包 —— 依据客户端 DEX `LscriptPages/data/f;->u` 字段序列。

    起点固定为包偏移 10（已用实测真值反查锁定）：
        @10  long  f->a        (角色序号)
        @18  utf   f->b        角色名
        @29  byte  f->c        等级
        @30  long  f->d        铜钱
        @38  long  f->e        粮食
        @46  long  f->f
        @54  byte  f->g
        @55  short f->h
        @57  byte  f->x
        @58  long  f->i
        @66  long  f->j
        @74  long  f->k
        @82  long  (丢弃)
        @90  byte  f->l
        @91  int   f->m        产钱/时
        @95  int   f->n        产粮/时
        @99  long  f->o
        @107 long  f->p
        @115 long  f->q        人口已用
        @123 long  f->r        人口上限
        @131 byte  f->s
        @132 byte  f->t
        @133 byte  f->u        资源点当前
        @134 byte  f->v        资源点上限
    """
    p = 10
    out = {}

    def rl():
        nonlocal p
        v = struct.unpack_from(">q", pkt_data, p)[0]; p += 8; return v

    def ri():
        nonlocal p
        v = struct.unpack_from(">i", pkt_data, p)[0]; p += 4; return v

    def rs():
        nonlocal p
        v = struct.unpack_from(">h", pkt_data, p)[0]; p += 2; return v

    def rb():
        nonlocal p
        v = struct.unpack_from(">b", pkt_data, p)[0]; p += 1; return v

    def ru():
        nonlocal p
        ln = struct.unpack_from(">H", pkt_data, p)[0]; p += 2
        v = pkt_data[p:p + ln].decode("utf-8", "ignore"); p += ln; return v

    try:
        out["roleSeq"] = rl()
        out["charName"] = ru()
        out["level"] = rb()
        out["copper"] = rl()
        out["food"] = rl()
        out["_f"] = rl()
        out["_g"] = rb()
        out["_h"] = rs()
        out["_x"] = rb()
        out["_i"] = rl()
        out["_j"] = rl()
        out["_k"] = rl()
        rl()                      # 丢弃
        out["_l"] = rb()
        out["resCur"] = None      # 占位，避免误用
        out["yieldCoin"] = ri()   # 产钱
        out["yieldFood"] = ri()   # 产粮
        rl(); rl()
        out["popUsed"] = rl()
        out["popMax"] = rl()
        rb(); rb()
        out["resCur"] = rb()      # 资源点当前
        out["resMax"] = rb()      # 资源点上限
    except Exception as e:
        out["_err"] = str(e)
    return out



# A4 字段序列（来自 DEX `La0/a;->A4`）—— 每条武将记录
_A4序列 = [
    ("name", "utf"), ("ea", "short"), ("fa", "byte"), ("ga", "byte"),
    ("ha", "short"), ("ia", "short"), ("ja", "byte"), ("ka", "int"),
    ("la", "int"), ("ma", "short"), ("na", "short"), ("oa", "short"),
    ("pa", "short"), ("qa", "short"), ("ra", "short"), ("sa", "short"),
    ("ta", "short"), ("ua", "short"), ("va", "int"), ("wa", "byte"),
    ("xa", "byte"), ("za", "short"), ("Aa", "short"), ("Ba", "byte"),
    ("Ca", "short"), ("Da", "short"), ("Ea", "long"), ("Fa", "long"),
    ("Ja", "int"), ("Ka", "int"), ("La", "short"), ("Ma", "short"),
    ("Na", "long"), ("Oa", "byte"), ("Vs", "short"), ("Pa", "short"),
    ("Qa", "long"), ("Ra", "byte"), ("Sa", "short"), ("Ta", "short"),
]

_兵种表 = ["—", "步兵", "弓兵", "骑兵", "器械", "弩兵", "水军", "禁卫"]


def _读A4(data, p):
    """从 p 开始按 A4 序列读一条武将记录，返回 (字典, 新偏移)"""
    out = {}
    for name, tp in _A4序列:
        if tp == "utf":
            ln = struct.unpack_from(">H", data, p)[0]; p += 2
            v = data[p:p + ln].decode("utf-8", "ignore"); p += ln
        elif tp == "short":
            v = struct.unpack_from(">h", data, p)[0]; p += 2
        elif tp == "byte":
            v = data[p]; p += 1
        elif tp == "int":
            v = struct.unpack_from(">i", data, p)[0]; p += 4
        else:  # long
            v = struct.unpack_from(">q", data, p)[0]; p += 8
        out[name] = v
    return out, p



def 解析部队(pkt_data, gen_ids):
    """从登录包/实时包解析 武将→(兵种seq, 数量)。

    ★ 两种真实排布（真机数据验证，都支持）：
        A) [int64 武将ID][byte 兵种seq][int32 数量]
        B) [int64 武将ID][int32 0][int32 武将ID][byte 兵种seq][int32 数量]
    实测: 328区弓1(A) / 318区長孫懿然(B) / 霸图18区b3(A) 全部命中。

    ⚠️ 铁律：seq 范围必须是 1..15（0 表示"未配兵"）！
       若放宽到 0，会匹配到大量垃圾位置（如 318区勇1 的 00 0da6 00 → 894464）。
    兵种seq → 名字 查 兵种名表.json（0民兵 1弩兵 2弓兵 3輕騎兵 ... 15驍騎兵）。
    同一武将多条时取数量最大的那条。
    """
    out = {}
    n = len(pkt_data)
    for o in range(n - 20):
        gid = struct.unpack_from(">q", pkt_data, o)[0]
        if gid not in gen_ids:
            continue
        # 模式A: seq 在 +8
        for off, need_id_dup in ((8, False), (16, True)):
            if need_id_dup:
                if struct.unpack_from(">i", pkt_data, o + 8)[0] != 0:
                    continue
                if struct.unpack_from(">i", pkt_data, o + 12)[0] != (gid & 0xFFFFFFFF):
                    continue
            seq = pkt_data[o + off]
            if not (1 <= seq <= 15):      # ★ 0 = 未配兵，必须排除
                continue
            cnt = struct.unpack_from(">i", pkt_data, o + off + 1)[0]
            if cnt < 0 or cnt > 200000:
                continue
            if gid not in out or cnt > out[gid][1]:
                out[gid] = (seq, cnt)
    return out

def 真机发(client, op, payload):
    """按【真机格式】发包（明文载荷 + 长度=载荷长-2 + 无签名）。

    ⚠️ 关键教训（真机抓包对比得出）：
      我们原来的 _game_post 会给载荷【加密+加32字节签名】、长度写 len(data)。
      读操作（12560/4128/4356）这样发能work；
      但**写操作**（配兵 4646/4649/4656）服务端会【静默忽略】！
      真机抓包证实：写操作的载荷是【明文】、长度字段 = 载荷长-2、【没有签名】。
      按真机格式发，配兵立即生效（已实测：呂時亮 0→2→0）。
    """
    body = _wutf("%s`%s`%s" % (client.c_version, client.c_type, client.channel_id))
    body += _wlong(int(time.time() * 1000)) + _wbyte(1)
    body += _wlong(client.play_id) + _wlong(0)
    body += _wshort(len(payload) - 2) + _wshort(op) + payload
    req = urllib.request.Request(client.game_url, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req, timeout=25) as r:
        return client._parse_resp(r.read())


def 组装配兵包(武将ID, 兵种seq, 数量):
    """op 4646 (generalWithSoldier) 载荷，共 17 字节（真机抓包验证）：

        [short 0x0000]          ← 固定前缀 2 字节
        [long  武将ID]           ← 如 328区弓1 = 0x02EEF7F1
        [byte  0]               ← 固定 0
        [short 兵种seq]          ← 0-15，见 兵种名表.json（3=輕騎兵）
        [int   数量]             ← 自定义数量；0 = 取消配兵

    验证记录：328区 呂時亮(0x02F17B93) + seq3 + 2 → 统兵 0→2 ✅
              同武将 + seq3 + 0 → 统兵 2→0 ✅（取消配兵）
    """
    return (b"\x00\x00"
            + struct.pack(">q", int(武将ID))
            + b"\x00"
            + struct.pack(">H", int(兵种seq))
            + struct.pack(">I", int(数量)))


def 配兵(client, 武将ID, 兵种seq, 数量):
    """配兵 / 取消配兵（数量=0 即取消）。返回响应包列表（应答 op = 33318）。"""
    return 真机发(client, 4646, 组装配兵包(武将ID, 兵种seq, 数量))


def 解析配兵应答(pk):
    """解析 op 4646 的应答（op=33318）。真机应答结构（17字节，已实测）：

        [byte 结果 01=成功]
        [long 武将ID]
        [short 兵种seq][short 旧数量]     ← 配兵前的值（ffff 表示无）
        [short 兵种seq][short 新数量]     ← 配兵后的值
        [byte][int]

    所以从应答就能直接拿到「旧值 → 新值」，不必等刷新。
    """
    for p in pk or []:
        if p["op"] - 28672 != 4646 or not p.get("data"):
            continue
        d = p["data"]
        r = {"ok": bool(d) and d[0] == 1, "genId": 0, "oldSeq": None, "oldCount": None,
             "newSeq": None, "newCount": None, "raw": d.hex()}
        if len(d) >= 17:
            r["genId"] = struct.unpack_from(">q", d, 1)[0]
            os_, oc = struct.unpack_from(">HH", d, 9)
            ns, nc = struct.unpack_from(">HH", d, 13)
            if os_ != 0xFFFF:
                r["oldSeq"], r["oldCount"] = os_, oc
            if ns != 0xFFFF:
                r["newSeq"], r["newCount"] = ns, nc
            else:
                r["newCount"] = 0
        return r
    return {"ok": False, "raw": "", "msg": "无应答"}




def 解析山贼响应(data):
    """解析 op 5440 响应 (op=34112)，返回 (w, h, [山贼字典])。
    字段: id, name, A, lvl, x, y, desc, E, F, drops, gens
    """
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
        n1 = u8()
        e["drops"] = [(u8(), i16(), u8()) for _ in range(n1)]
        n2 = u8()
        e["gens"] = [dict(nm=utf(), s1=i16(), s2=i16(),
                          b1=u8(), b2=u8(), b3=u8(), i1=i32()) for _ in range(n2)]
        out.append(e)
    return w, h, out


def 扫描山贼(client, 坐标列表, batch_size=120):
    """批量扫描山贼（op 5440）。返回 {id: 山贼字典}。"""
    found = {}
    for i in range(0, len(坐标列表), batch_size):
        chunk = 坐标列表[i:i + batch_size]
        body = _wutf("%s`%s`%s" % (client.c_version, client.c_type, client.channel_id))
        body += _wlong(int(time.time() * 1000)) + _wbyte(len(chunk))
        for (x, y) in chunk:
            pl = struct.pack(">hhh", 0, x, y)
            body += _wlong(client.play_id) + _wlong(0) + _wshort(len(pl) - 2) + _wshort(5440) + pl
        import urllib.request
        req = urllib.request.Request(client.game_url, data=body, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        pk = client._parse_resp(urllib.request.urlopen(req, timeout=25).read())
        for q in pk:
            if q["op"] != 34112:
                continue
            try:
                w, h, lst = 解析山贼响应(q["data"])
                if w > 0 and h > 0:
                    client.map_w, client.map_h = w, h   # ★ 记录本区地图尺寸
                for e in lst:
                    found[e["id"]] = e
            except Exception:
                pass
    return found


def _发_pkt(client, op, payload, batch=1):
    """真机格式发单个包"""
    body = _wutf("%s`%s`%s" % (client.c_version, client.c_type, client.channel_id))
    body += _wlong(int(time.time() * 1000)) + _wbyte(batch)
    body += _wlong(client.play_id) + _wlong(0) + _wshort(len(payload) - 2) + _wshort(op) + payload
    import urllib.request
    req = urllib.request.Request(client.game_url, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    return client._parse_resp(urllib.request.urlopen(req, timeout=25).read())


def 出征打山贼(client, genIds, thief_id, a_type=3):
    """op 5410 expedition。

    ★ 必须用 _发_pkt（带 \\x00\\x00 前缀的真机格式）。
    send_op_raw 和 send_op 都会被服务端静默忽略（实测确认）。

    5410 载荷: [00 00][byte type=3][byte N][long×N genId][long thiefId][long -1][00 00 00]
    5408 载荷: [00 00][byte type=3][byte N][long genId][long thiefId]
    """
    pl = b"\x00\x00" + struct.pack(">BB", a_type, len(genIds))
    for g in genIds:
        pl += struct.pack(">q", int(g))
    pl += struct.pack(">q", int(thief_id))
    pl += struct.pack(">q", -1)
    pl += b"\x00\x00\x00"
    result = _发_pkt(client, 5410, pl)

    # 5408 前置（真机后发）
    前置 = b"\x00\x00" + struct.pack(">BB", a_type, 1)
    前置 += struct.pack(">q", int(genIds[0]))
    前置 += struct.pack(">q", int(thief_id))
    try:
        _发_pkt(client, 5408, 前置)
    except Exception:
        pass

    return result


# === Restored from backup ===
class KingClient:
    def __init__(self, user, pwd, game_host=None, game_port=25511):
        self.user, self.pwd = user, pwd
        self.channel_id, self.c_version, self.c_type = CHANNEL_ID, C_VERSION, C_TYPE
        self.game_url = f"http://{game_host}:{game_port}{GAME_PATH}" if game_host else None
        self.session = None
        self.sub_token = None
        self.play_id = 0

    def 取角色全部信息(self):
        """从已缓存的 login_packets 解析角色完整信息。
        login_packets 来自 game_login()（op 4100 → 响应 op 32772）。
        国家来自 enter_packets（op 4099 → 响应 op 32771）。
        """
        pk = getattr(self, "login_packets", None) or []
        out = {}
        for p in pk:
            if p.get("op") == 32772 and p.get("data"):
                try:
                    out = 解析登录包完整(p["data"])
                except Exception:
                    pass
                break
        # 国家从 enter_game(4099) 响应提取
        if not out.get("kingdom"):
            enter_pk = getattr(self, "enter_packets", None) or []
            out["kingdom"] = 解析国家(enter_pk)
        # 备用：从 login_packets 中文串扫描
        if not out.get("kingdom"):
            info = 解析登录信息(pk)
            out["kingdom"] = info.get("kingdom", "")
        return out

    def 取角色资源(self):
        """获取角色资源（铜钱/粮食/人口）op 4128 → 响应 op 32800
        结构：8+8+4+4+8+8+8+8 = 56 字节（协议逆向确认）
        """
        pk = self.send_op(4128, b"")
        for p in pk or []:
            if p["op"] == 32800 and p.get("data"):
                d = p["data"]
                if len(d) < 56:
                    continue
                try:
                    o = 0
                    def _rl():
                        nonlocal o; v = struct.unpack_from(">q", d, o)[0]; o += 8; return v
                    def _ri():
                        nonlocal o; v = struct.unpack_from(">i", d, o)[0]; o += 4; return v
                    copper = _rl()    # 铜钱
                    food = _rl()      # 粮食
                    yieldCoin = _ri() # 总产钱
                    yieldFood = _ri() # 总产粮
                    popUsed = _rl()   # 人口占用
                    popMax = _rl()    # 人口上限
                    gold = _rl()      # 黄金
                    silver = _rl()    # 白银
                    return {"copper": copper, "food": food,
                            "yieldCoin": yieldCoin, "yieldFood": yieldFood,
                            "popUsed": popUsed, "popMax": popMax,
                            "gold": gold, "silver": silver}
                except Exception:
                    pass
        return {}

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
        packets = self._parse_resp(resp)
        self.enter_packets = packets          # ★ 存起来给 解析国家 用
        for p in packets:
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

def 进入游戏(user, pwd, host, port, session, sub):
    """登录游戏服务器"""
    try:
        client = KingClient(user, pwd, game_host=host, game_port=int(port))
        client.session = session
        client.sub_token = sub or ''
        if not client.enter_game():
            return None, '进入游戏失败'
        try:
            client.login_packets = client.game_login()
        except:
            client.login_packets = []
        return client, 'ok'
    except Exception as e:
        return None, str(e)


def 拉全部山贼(client, batch_size=120):
    """拉取本区全部山贼（分页协议全图扫描）。

    op 5440 载荷 (short, short, short) = (0, 页内序号x, 页行号y)。
    x=0~4, y=0,1,2... 每页最多 8 个山贼。
    按行(y)递增批量请求，直到整批返回 0 个新山贼为止。
    ★ 旧代码错误地用地图尺寸 (250×62=15500) 当分页边界，导致：
      · 15500 次请求 → 3 分钟延迟
      · 同一批山贼重复返回 124000 次（不同 ID）
    """
    found = {}
    PAGE_X = 5
    rows_per_batch = max(1, batch_size // PAGE_X)
    y_start = 0
    while True:
        pts = [(x, y_start + r) for r in range(rows_per_batch) for x in range(PAGE_X)]
        body = _wutf('%s`%s`%s' % (client.c_version, client.c_type, client.channel_id))
        body += _wlong(int(time.time() * 1000)) + _wbyte(len(pts))
        for (px, py) in pts:
            pl = struct.pack('>hhh', 0, px, py)
            body += _wlong(client.play_id) + _wlong(0) + _wshort(len(pl) - 2) + _wshort(5440) + pl
        import urllib.request as _u
        req = _u.Request(client.game_url, data=body, method='POST')
        req.add_header('Content-Type', 'application/x-www-form-urlencoded')
        pk = client._parse_resp(_u.urlopen(req, timeout=25).read())
        before = len(found)
        for q in pk:
            if q['op'] != 34112: continue
            try:
                w2, h2, lst = 解析山贼响应(q['data'])
                if w2 > 0 and h2 > 0: client.map_w, client.map_h = w2, h2
                for e in lst: found[e['id']] = e
            except Exception: pass
        if len(found) == before:
            break
        y_start += rows_per_batch
        if y_start > 2000:
            break
    return found

def 解析角色资源(data):
    """解析角色资源包 (op 4128)"""
    return data  # stub for import compatibility


# ====== genId 缓存（登录包提取一次，实时包复用）======
_cached_gen_ids = []       # 按顺序的武将 ID 列表


def 解析武将列表(pkt_data):
    """从登录包或实时包提取武将。

    ★ 两种数据源，格式不同：
      A) 登录包（op 32772）：每条武将前有 [long genId][A4 序列]
      B) 实时包（op 41232 首包）：只有 A4 序列，无 genId
         → 需要从登录包缓存的 genId 列表按顺序配对

    先尝试模式A（扫描 genId+A4），成功则缓存 genId 列表；
    失败则尝试模式B（只扫 A4 记录，用缓存 genId 配对）。
    """
    global _cached_gen_ids

    # ---- 模式 A：登录包格式（genId 在 A4 前 8 字节）----
    result_a = _解析_模式A(pkt_data)
    if result_a:
        _cached_gen_ids = [g["genId"] for g in result_a]
        return result_a

    # ---- 模式 B：实时包格式（纯 A4 记录，用缓存 genId 配对）----
    if _cached_gen_ids:
        result_b = _解析_模式B(pkt_data, _cached_gen_ids)
        if result_b:
            return result_b

    return []


def _解析_模式A(pkt_data):
    """模式A：登录包 — 扫描 [long genId][A4(首字段=UTF武将名)] 结构"""
    def 纯中文(s):
        return s and all("一" <= ch <= "鿿" or ch.isdigit() for ch in s)

    found, seen = [], set()
    for o in range(11, len(pkt_data) - 3):
        ln = struct.unpack_from(">H", pkt_data, o)[0]
        if not (2 <= ln <= 16) or o + 2 + ln > len(pkt_data):
            continue
        try:
            nm = pkt_data[o + 2:o + 2 + ln].decode("utf-8")
        except Exception:
            continue
        if not 纯中文(nm) or len(nm) < 2:
            continue
        idoff = o - 8
        if idoff < 0:
            continue
        gid = struct.unpack_from(">q", pkt_data, idoff)[0]
        if not (1000 < gid < 2 ** 55):
            continue
        if gid in seen:
            continue
        try:
            g, _ = _读A4(pkt_data, o)
        except Exception:
            continue
        if g.get("name") != nm:
            continue
        seen.add(gid)
        g["genId"] = gid
        found.append(g)
    return found


def _解析_模式B(pkt_data, gen_ids):
    """模式B：实时包 — 扫描纯 A4 记录，按顺序与缓存 genId 配对。

    实时包特征：首包 1800+ 字节含武将 A4 记录（无 genId 前缀）。
    增量包 130-160 字节不含武将，会自然失败返回 []。
    """
    def 纯中文(s):
        return s and all("一" <= ch <= "鿿" or ch.isdigit() for ch in s)

    # 先找所有可能的 A4 记录起始位置（UTF 中文名开头）
    candidates = []
    for o in range(4, len(pkt_data) - 3):
        ln = struct.unpack_from(">H", pkt_data, o)[0]
        if not (2 <= ln <= 16) or o + 2 + ln > len(pkt_data):
            continue
        try:
            nm = pkt_data[o + 2:o + 2 + ln].decode("utf-8")
        except Exception:
            continue
        if not 纯中文(nm) or len(nm) < 2:
            continue
        try:
            g, end = _读A4(pkt_data, o)
        except Exception:
            continue
        if g.get("name") != nm:
            continue
        candidates.append((o, g, end))

    # 去重：A4 记录不重叠（后一条起点 >= 前一条终点）
    records = []
    last_end = 0
    for o, g, end in candidates:
        if o >= last_end:
            records.append(g)
            last_end = end

    # 按顺序配对 genId
    if not records or len(records) > len(gen_ids) * 2:
        return []   # 数量差太多说明解析错了

    found = []
    for i, g in enumerate(records):
        if i < len(gen_ids):
            g["genId"] = gen_ids[i]
        else:
            g["genId"] = i + 1     # 兜底
        found.append(g)
    return found


# ====== 伤兵解析（DEX q;->a0 逆向确认）======

def 解析伤兵(pkt_data):
    """从登录包/4368包扫描伤兵数据。

    DEX q;->a0 格式（实测确认 @895 fiefId=29 轻骑兵23伤兵）：
        long  fiefId（封地索引，小整数如 28/29）
        byte  N1（健康兵种类数）
        N1 × { byte(兵种seq) + int(数量) }
        byte  N2（伤兵种类数）
        N2 × { byte(兵种seq) + int(数量) }

    返回 {fiefId: {"healthy": [(seq,cnt)], "wounded": [(seq,cnt)]}}
    """
    result = {}
    n = len(pkt_data)
    o = 0
    while o < n - 20:
        # 找合理的 fiefId（小整数 1~1000）+ N1 < 10
        fid = struct.unpack_from(">q", pkt_data, o)[0]
        if not (1 <= fid <= 1000):
            o += 1
            continue
        pos = o + 8
        if pos >= n:
            break
        n1 = pkt_data[pos]; pos += 1
        if not (0 < n1 < 10):
            o += 1
            continue
        # 验证 N1 个 {byte(<=15), int(>=0, <200000)} 结构
        healthy = []
        valid = True
        for _ in range(n1):
            if pos + 5 > n:
                valid = False; break
            st = pkt_data[pos]
            ct = struct.unpack_from(">i", pkt_data, pos + 1)[0]
            if st > 15 or ct < 0 or ct > 200000:
                valid = False; break
            healthy.append((st, ct))
            pos += 5
        if not valid:
            o += 1
            continue
        # N2 伤兵
        if pos >= n:
            o += 1
            continue
        n2 = pkt_data[pos]; pos += 1
        if n2 > 10:
            o += 1
            continue
        wounded = []
        for _ in range(n2):
            if pos + 5 > n:
                break
            st = pkt_data[pos]
            ct = struct.unpack_from(">i", pkt_data, pos + 1)[0]
            if st > 15 or ct < 0 or ct > 200000:
                break
            wounded.append((st, ct))
            pos += 5
        if healthy or wounded:
            result[fid] = {"healthy": healthy, "wounded": wounded}
        o = pos  # 跳到下一个块
    return result


def 刷新伤兵(client):
    """使用 op 4657 查询所有封地的伤兵数据。

    遍历 client.封地列表，对每个封地发送 op 4657 查询，解析响应包里的伤兵数据。
    响应格式（从 s.har 逆向）：偏移41=封地ID(8B), 49=N1健康兵, 50+=[seq(1B)+cnt(4B)]×N1, X=N2伤兵, X+1+=[seq(1B)+cnt(4B)]×N2

    返回 {fiefId: {"healthy": [(seq,cnt)], "wounded": [(seq,cnt)]}}
    """
    import sys
    result = {}

    fiefs = getattr(client, '封地列表', [])
    if not fiefs:
        print(f"[伤兵] 封地列表为空，无法查询", file=sys.stderr)
        return {}

    print(f"[伤兵] 开始查询 {len(fiefs)} 个封地的伤兵数据", file=sys.stderr)

    for fief in fiefs:
        fief_id = fief.get('fiefId') or fief.get('id')
        if not fief_id:
            continue

        # 发送 op 4657 查询这个封地的伤兵（soldier_type=-1 表示全部兵种）
        payload = (struct.pack(">q", int(fief_id))
                   + struct.pack(">h", -1)  # 全部兵种
                   + struct.pack(">i", 0))   # cure_type=0 铜钱治疗
        pk = 真机发(client, 4657, b"\x00\x00" + payload)

        resp_op = 4657 + 0x7000  # 33329
        for p in pk or []:
            if p.get("op") != resp_op or not p.get("data"):
                continue

            d = p["data"]
            if len(d) < 50:
                continue

            try:
                parsed_fief_id = struct.unpack_from(">q", d, 41)[0]
                n1_healthy = d[49]

                o = 50
                healthy = []
                for _ in range(n1_healthy):
                    if o + 5 > len(d):
                        break
                    seq = d[o]
                    cnt = struct.unpack_from(">I", d, o + 1)[0]
                    healthy.append((seq, cnt))
                    o += 5

                if o >= len(d):
                    continue

                n2_wounded = d[o]
                o += 1

                wounded = []
                for _ in range(n2_wounded):
                    if o + 5 > len(d):
                        break
                    seq = d[o]
                    cnt = struct.unpack_from(">I", d, o + 1)[0]
                    wounded.append((seq, cnt))
                    o += 5

                result[parsed_fief_id] = {"healthy": healthy, "wounded": wounded}

                total_wounded = sum(cnt for _, cnt in wounded)
                print(f"[伤兵] 封地 {parsed_fief_id}: 健康{len(healthy)}种, 伤兵{len(wounded)}种(共{total_wounded})", file=sys.stderr)

            except Exception as e:
                print(f"[伤兵] 解析封地 {fief_id} 响应失败: {e}", file=sys.stderr)
                continue

    print(f"[伤兵] 查询完成，共 {len(result)} 个封地有数据", file=sys.stderr)
    return result


def 查询伤兵(client, gen_id, soldier_type=-1, cure_type=0):
    """op 4657 reqHurtSoldierCurePreInfo — 查询伤兵信息 + 治疗费用。

    DEX sender q;->l1 签名 (J I I)V：
        writeLong(ID)           ← genId 或 fiefId
        writeShort(兵种索引)     ← -1=全部, >=0=特定兵种
        writeInt(治疗方式)       ← 0=铜钱, 1=黄金（推测）

    DEX handler q;->m1 响应：
        readLong()              ← 未知
        readShort() → type      ← <0 = 全部治疗, >=0 = 单兵种
        readLong() → copperCost
        readLong() → goldCost
    """
    payload = (struct.pack(">q", int(gen_id))
               + struct.pack(">h", int(soldier_type))
               + struct.pack(">i", int(cure_type)))
    pk = 真机发(client, 4657, b"\x00\x00" + payload)
    resp_op = 4657 + 0x7000   # 33329
    for p in pk or []:
        if p.get("op") != resp_op or not p.get("data"):
            continue
        d = p["data"]
        if len(d) < 26:
            continue
        try:
            o = 0
            _unk = struct.unpack_from(">q", d, o)[0]; o += 8
            typ = struct.unpack_from(">h", d, o)[0]; o += 2
            copper_cost = struct.unpack_from(">q", d, o)[0]; o += 8
            gold_cost = struct.unpack_from(">q", d, o)[0]; o += 8
            return {"type": typ, "copperCost": copper_cost, "goldCost": gold_cost,
                    "genId": int(gen_id), "raw": d.hex()}
        except Exception:
            continue
    return None


def 治疗伤兵(client, fief_id, soldier_type=0, count=-1, cure_byte=0):
    """op 4656 治疗伤兵（真机抓包验证 2024-09）。

    载荷（16B + 前缀 00 00 = 18B）：
        [00 00][long fiefId][byte cureType][short soldierSeq][int count][byte 0x00]
        ★ 末尾 0x00 必须带，否则服务端静默忽略（同配兵教训）。
        ★ count=-1 表示全部治疗。

    响应：[short code][long ?][long ?][long fiefId][byte N][N × {byte seq, int cnt}]
        code: 0=成功, -1=铜钱不足, -2=失败, -3=黄金不足
    """
    payload = (struct.pack(">q", int(fief_id))
               + struct.pack(">b", int(cure_byte))
               + struct.pack(">h", int(soldier_type))
               + struct.pack(">i", int(count))
               + b"\x00")
    pk = _发_pkt(client, 4656, b"\x00\x00" + payload)
    resp_op = 4656 + 0x7000   # 33328
    for p in pk or []:
        if p.get("op") != resp_op or not p.get("data"):
            continue
        d = p["data"]
        if len(d) < 2:
            continue
        code = struct.unpack_from(">h", d, 0)[0]
        msg = {0: "成功", -1: "铜钱不足", -2: "治疗失败", -3: "黄金不足"}.get(code, f"错误{code}")
        return {"ok": code == 0, "code": code, "msg": msg, "raw": d.hex()}
    return {"ok": False, "code": -99, "msg": "无响应", "raw": ""}


def 解析宝藏(packets):
    """解析 op 4356 响应 → {"gold", "silver", "treasures": [{id, count, expire}]}

    响应结构（角色协议.md §5 确认）：
        long(8B)  黄金 Ga
        long(8B)  白银 Ha
        short(2B) N 条目数
        N × { short(2B 宝藏ID) + short(2B 个数) + long(8B 到期时间) } = 12B/条
    """
    resp_op = 4356 + 0x7000   # 33028
    for p in (packets or []):
        d = p.get("data") if isinstance(p, dict) else None
        if not d or (isinstance(p, dict) and p.get("op") != resp_op):
            continue
        if len(d) < 18:
            continue
        try:
            gold = struct.unpack_from(">q", d, 0)[0]
            silver = struct.unpack_from(">q", d, 8)[0]
            n = struct.unpack_from(">H", d, 16)[0]
            items = []
            o = 18
            for _ in range(n):
                if o + 12 > len(d):
                    break
                tid = struct.unpack_from(">H", d, o)[0]
                cnt = struct.unpack_from(">H", d, o + 2)[0]
                exp = struct.unpack_from(">q", d, o + 4)[0]
                items.append({"id": tid, "count": cnt, "expire": exp})
                o += 12
            return {"gold": gold, "silver": silver, "treasures": items}
        except Exception:
            continue
    return {"gold": 0, "silver": 0, "treasures": []}
