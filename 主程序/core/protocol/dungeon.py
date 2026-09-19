"""副本扫荡：op 5120 应答解析"""
import struct

def 解析副本应答(pkt_data):
    """解析 op 5120（副本扫荡）应答。

    成功：返回 {"ok": True, "msg": "扫荡成功", "raw": ...}
    失败：返回 {"ok": False, "msg": 失败原因, "raw": ...}
    空包：返回 {"ok": False, "msg": "无应答（会话失效）", "raw": ""}

    ★ 应答格式（类比配兵 op 4646）：
      成功：首 UTF 字符串含「成功」
      失败：首 UTF 字符串是错误提示（「次数不足」「副本未开启」等）
      空包：0 字节（会话失效）
    """
    if not pkt_data:
        return {"ok": False, "msg": "无应答（会话失效）", "raw": ""}

    if len(pkt_data) < 2:
        return {"ok": False, "msg": "应答过短", "raw": pkt_data.hex()}

    try:
        ln = struct.unpack_from(">H", pkt_data, 0)[0]
        if ln > len(pkt_data) - 2 or ln > 100:
            return {"ok": False, "msg": "格式错误", "raw": pkt_data[:30].hex()}
        msg = pkt_data[2:2 + ln].decode("utf-8", "ignore")
    except Exception:
        return {"ok": False, "msg": "解析失败", "raw": pkt_data[:30].hex()}

    if "成功" in msg:
        return {"ok": True, "msg": msg, "raw": pkt_data.hex()}
    else:
        return {"ok": False, "msg": msg, "raw": pkt_data.hex()}
