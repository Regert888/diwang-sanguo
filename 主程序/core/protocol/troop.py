"""部队/配兵解析：op 4646 应答，实时包部队刷新"""
import struct

_兵种表 = ["—", "步兵", "弓兵", "骑兵", "器械", "弩兵", "水军", "禁卫"]

def 解析配兵应答(packets):
    """解析 op 4646（配兵）应答包列表（op=33318）。

    真机应答结构（17字节，已实测）：
        [byte 结果 01=成功]
        [long 武将ID]
        [short 兵种seq][short 旧数量]     ← 配兵前的值（ffff 表示无）
        [short 兵种seq][short 新数量]     ← 配兵后的值
        [byte][int]

    返回：{"ok": True/False, "genId": ..., "oldSeq": ..., "oldCount": ...,
           "newSeq": ..., "newCount": ..., "raw": ...}
    """
    for p in packets or []:
        if p.get("op") != 33318 or not p.get("data"):
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

def 解析部队实时(pkt_data, cached_gen_ids=None):
    """从实时包（op 41232）提取部队状态 {genId: (兵种seq, 数量)}。

    ★ 为什么需要 cached_gen_ids：
      实时包只有 A4 记录（无 genId 前缀），需要按顺序配对。
      这个函数复用 generals.py 的解析逻辑，提取 A4 里的部队字段。

    A4 字段含义（DEX `La0/a;->A4`）：
      ma = 兵种 seq (short)
      na = 兵力数量 (short)
    """
    from .generals import 解析武将列表

    gens, _ = 解析武将列表(pkt_data, cached_gen_ids or [])
    troops = {}
    for g in gens:
        gid = g.get("genId")
        seq = g.get("ma", 0)      # 兵种seq
        cnt = g.get("na", 0)      # 兵力
        if gid and seq >= 0:
            troops[gid] = (seq, cnt)

    return troops

def 格式化部队(troops):
    """部队字典 → 前端展示格式 [{"genId": ..., "seq": ..., "count": ..., "typeName": ...}]"""
    out = []
    for gid, (seq, cnt) in troops.items():
        type_name = _兵种表[seq] if 0 <= seq < len(_兵种表) else f"未知({seq})"
        out.append({
            "genId": gid,
            "seq": seq,
            "count": cnt,
            "typeName": type_name
        })
    return out
