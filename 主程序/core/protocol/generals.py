"""武将解析：登录包、实时包、A4序列"""
import struct

# 第一串常是「登錄成功」这类状态串，需要跳过
_状态串 = ("登錄成功", "登录成功", "登入成功")

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

# genId 缓存（登录包提取一次，实时包复用）—— 改为函数参数传递，避免全局状态
# _cached_gen_ids = []  # 这个会移到 SessionState 里

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
        return s and all("一" <= ch <= "鿿" for ch in s)

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
                    and any("一" <= c <= "鿿" for c in sv2):
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
        ...
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

def _武将记录合法(g):
    """A4 记录的值域合法性校验。

    ★ 为什么需要：模式A/B 原本只校验「名字是纯中文且≥2字」，
      但这只约束了 A4 的第一个字段。包里任何一段字节只要碰巧
      长得像「短中文串」，后面的偏移就会被当成体力/忠诚读出来。

      实测踩坑（2026-09-16）：全量刷新后武将从 3 个变 7 个，多出来的
      首条是 name=「嗷嗷嗷」(君主名，3 字，过得了中文过滤)
      genId=1051、体力=-13056、maxHp=0、忠诚=0。
      早期「假武将 金/时」加的 len(nm)<2 过滤挡不住 3 个字的名字。

      名字能伪造，但一整组【互相自洽的数值】伪造不了 —— 改用值域校验。

    字段含义（A4 序列逆向确认）：ja=等级 ra=体力 sa=体力上限 wa=忠诚
    """
    try:
        lv = int(g.get("ja", 0) or 0)
        hp = int(g.get("ra", 0) or 0)
        hp_max = int(g.get("sa", 0) or 0)
        loy = int(g.get("wa", 0) or 0)
    except (TypeError, ValueError):
        return False
    if hp_max <= 0 or hp_max > 100000:      # 真武将必有体力上限；越界记录常读出 0
        return False
    if hp < 0 or hp > hp_max * 2:           # 负体力 = 按错误偏移读的 short
        return False
    if not (1 <= lv <= 500):
        return False
    if not (0 <= loy <= 100):               # 忠诚是百分比
        return False
    return True

def 解析武将列表(pkt_data, cached_gen_ids=None):
    """从登录包或实时包提取武将。

    ★ 两种数据源，格式不同：
      A) 登录包（op 32772）：每条武将前有 [long genId][A4 序列]
      B) 实时包（op 41232 首包）：只有 A4 序列，无 genId
         → 需要从登录包缓存的 genId 列表按顺序配对

    先尝试模式A（扫描 genId+A4），成功则缓存 genId 列表；
    失败则尝试模式B（只扫 A4 记录，用缓存 genId 配对）。

    返回 (武将列表, 新的cached_gen_ids)
    """
    cached_gen_ids = cached_gen_ids or []

    # ---- 模式 A：登录包格式（genId 在 A4 前 8 字节）----
    result_a = _解析_模式A(pkt_data)
    if result_a:
        new_cached = [g["genId"] for g in result_a]
        return result_a, new_cached

    # ---- 模式 B：实时包格式（纯 A4 记录，用缓存 genId 配对）----
    if cached_gen_ids:
        result_b = _解析_模式B(pkt_data, cached_gen_ids)
        if result_b:
            return result_b, cached_gen_ids

    return [], cached_gen_ids

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
        if not _武将记录合法(g):       # ★ 值域校验，挡掉越界扫出来的假记录
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
        if not _武将记录合法(g):       # ★ 同模式A，值域校验
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
