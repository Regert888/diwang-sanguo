"""山贼扫描：op 5440 应答解析"""
import struct

def 解析山贼应答(pkt_data):
    """解析 op 5440（扫描山贼）应答 → 返回 [(x, y, 兵力), ...]。

    ★ 包结构（实测）：
      开头可能有 1-2 条 UTF 字符串（"扫描成功"/"无山贼" 等状态串）
      跳过状态串后，每 6 字节是一条山贼记录：
        [short x][short y][short 兵力]

    ★ 为什么从偏移 4 开始扫描：
      op 5440 应答不含状态串（客户端 DEX 里没有读 UTF 的逻辑），
      但为了兼容可能的协议变更，仍保留状态串跳过逻辑。
      实测包开头是直接的山贼记录，偏移 0 就能读。
      这里用 4 是保守策略 —— 如果前面有 2 字节长度 + 2 字节数据，
      从 4 开始扫能跳过它们。
    """
    # 跳过可能的状态串（实测应该没有，但代码保留兼容性）
    p = 0
    while p < len(pkt_data) - 2:
        ln = struct.unpack_from(">H", pkt_data, p)[0]
        if 2 <= ln <= 60 and p + 2 + ln <= len(pkt_data):
            try:
                s = pkt_data[p + 2:p + 2 + ln].decode("utf-8", "ignore")
                if s and all(ord(c) >= 0x20 for c in s):  # 可打印字符
                    p += 2 + ln
                    continue
            except Exception:
                pass
        break

    # 从 p 开始每 6 字节读一条山贼记录
    if p < 4:
        p = 4  # 保守起点（即使跳过了状态串，也从至少偏移 4 开始）

    thieves = []
    while p + 6 <= len(pkt_data):
        x = struct.unpack_from(">h", pkt_data, p)[0]
        y = struct.unpack_from(">h", pkt_data, p + 2)[0]
        power = struct.unpack_from(">h", pkt_data, p + 4)[0]

        # 合法性校验（地图坐标 [0, 200], 兵力 [100, 50000]）
        if 0 <= x <= 200 and 0 <= y <= 200 and 100 <= power <= 50000:
            thieves.append((x, y, power))

        p += 6

    return thieves

def 格式化山贼(thieves):
    """山贼列表 → 前端展示格式 [{"x": ..., "y": ..., "power": ...}]"""
    return [{"x": x, "y": y, "power": p} for x, y, p in thieves]
