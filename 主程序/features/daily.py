# -*- coding: utf-8 -*-
"""zone1 日常任务 —— 每天最多成功执行一次。

★ 为什么单独成模块：这类功能会越加越多（配置里已有 7 个 type），
  全塞进 server.py 会让那个文件继续膨胀。这里一个 type 一行表项，
  新增只改 TASKS 字典，不动调度和路由。

★ 载荷约定：明文传输的长度字段写的是 len(payload) - 2，
  因为载荷开头固定有 2 字节 0x0000 前缀（见 组装配兵包 的注释）。
  所以「无载荷」的 op 要发 b"\\x00\\x00"，不能发 b""
  （否则长度字段算出 -2 → 0xFFFE）。

操作码来源：apk_work/sent_ops.json（DEX 逆向产物，含 req_op + 语义名 + 方法签名）
"""

RESP_DELTA = 0x7000          # 多数 op 的响应 = 请求 op + 28672
NOTICE_OP = 33076            # 通用文字提示包（req 4404，处理器 u(Ljava/lang/String;)）

# ★ 实测重要发现：并非所有 op 都按 req+0x7000 回应答。
#   签到(25090) 成功时服务端回的是 33076 文字包「簽到獲得豪華大禮」，
#   而不是 53762。所以判定成功要同时认【预期应答】和【文字提示】两种形式。

# type -> (op, 载荷, 中文名)
TASKS = {
    "DAILY_SIGNIN": (25090, b"\x00\x00", "签到"),          # qiandao,      无载荷
    "SALARY":       (25442, b"\x00\x00", "俸禄"),          # REQ_HOUSE_REWARD, 无载荷
    "AUTO_REWARD":  (25411, b"\x00\x00", "礼部领奖"),       # Req_libutaskAward, 无载荷
    "AUTO_DONATE":  (5130,  b"\x00\x00", "捐献"),          # reqCountryDonateIntegral, 无载荷
}

# 尚未逆向出可用操作码，UI 里可以勾但后端暂不执行：
#   ARENA_BONUS      竞技场 —— 是多 op 流程(25186 榜单→25192 阵容→25198 开打)，不是单包
#   VIP_ADD_LOYALTY  VIP加忠
#   SORT_EQUIP       整理装备
UNSUPPORTED = {
    "ARENA_BONUS": "竞技场需多步流程(25186/25192/25198)，待逆向",
    "VIP_ADD_LOYALTY": "操作码待逆向",
    "SORT_EQUIP": "操作码待逆向",
}


def 待办(cfg, today):
    """挑出今天还没跑、且已启用的 zone1 任务。返回 [(type, op, payload, 名称)]"""
    out = []
    for row in (cfg.get("zone1") or []):
        if not isinstance(row, dict) or not row.get("enabled"):
            continue
        t = row.get("type")
        if t in UNSUPPORTED or t not in TASKS:
            continue
        if row.get("lastRunDate") == today:      # 今天已跑过
            continue
        op, pl, name = TASKS[t]
        out.append((t, op, pl, name))
    return out


def _读文本(data):
    """尽力从响应数据里抠出可读文字。

    服务端的通用提示包（op 4404 → 33076，处理器签名是 u(Ljava/lang/String;)）
    带的就是一段文字，把它读出来才知道被拒的真正原因。
    """
    if not data:
        return ""
    import struct

    def 像正经文字(s):
        s = (s or "").strip()
        if len(s) < 2:
            return False
        good = sum(1 for ch in s if ch.isprintable() and (ch.isascii() or "一" <= ch <= "鿿"))
        return good >= len(s) * 0.8      # 八成以上是可读字符才算数

    # 优先按 writeUTF：2 字节长度 + utf8。可能有前导字节，逐个偏移试。
    for off in range(0, min(len(data), 10)):
        try:
            n = struct.unpack_from(">H", data, off)[0]
        except Exception:
            break
        if not (0 < n <= len(data) - off - 2):
            continue
        try:
            s = data[off + 2:off + 2 + n].decode("utf-8")
        except Exception:
            continue
        if 像正经文字(s):
            return s.strip()

    # 兜底：扫出最长的一段可读文字。utf-8 优先，成功就返回 ——
    # 不能取「两种编码里最长的」，否则 GBK 会把 utf-8 字节解成更长的乱码。
    for enc in ("utf-8", "gbk"):
        try:
            s = data.decode(enc, "ignore")
        except Exception:
            continue
        best, cur = "", ""
        for ch in s:
            if ch.isprintable() and (ch.isascii() or "一" <= ch <= "鿿"):
                cur += ch
            else:
                if len(cur) > len(best):
                    best = cur
                cur = ""
        if len(cur) > len(best):
            best = cur
        best = best.strip()
        if 像正经文字(best):
            return best
    return ""


def 执行(client, cfg, today, log):
    """执行今天待办的日常任务。

    返回成功的 type 列表 —— 调用方据此写 lastRunDate。
    每个任务独立 try，一个失败不影响其它。
    """
    做完 = []
    for t, op, pl, name in 待办(cfg, today):
        try:
            pk = client.send_ops([(op, pl)])
        except Exception as e:
            log("[日常] %s 发包失败: %s" % (name, e))
            continue

        want = op + RESP_DELTA
        hit_正常应答 = any(p.get("op") == want for p in (pk or []))

        # 读服务端文字提示 —— 很多 op 不走标准应答，而是回 33076 文字包
        说明 = ""
        hit_文字提示 = False
        for p in (pk or []):
            if p.get("op") == NOTICE_OP:
                s = _读文本(p.get("data"))
                if s:
                    说明 = s[:80]
                    # 繁体「獲得」「成功」「完成」等视为成功标志
                    if any(w in s for w in ("獲得", "成功", "完成", "领取", "領取")):
                        hit_文字提示 = True
                    break

        if hit_正常应答 or hit_文字提示:
            提示 = ("｜%s" % 说明) if 说明 else ""
            log("[日常] ✓ %s 完成%s" % (name, 提示))
            做完.append(t)
        else:
            got = [p.get("op") for p in (pk or [])]
            提示 = ("｜服务端: %s" % 说明) if 说明 else ""
            log("[日常] ✗ %s 无预期应答（期望%d，实得%s）%s" % (
                name, want, got or "无包", 提示))
    return 做完


def 未支持提示(cfg):
    """UI 里勾了但后端还做不了的，返回提示文案列表（只提示一次由调用方控制）。"""
    out = []
    for row in (cfg.get("zone1") or []):
        if isinstance(row, dict) and row.get("enabled"):
            why = UNSUPPORTED.get(row.get("type"))
            if why:
                out.append("%s：%s" % (row.get("type"), why))
    return out
