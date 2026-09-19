# -*- coding: utf-8 -*-
"""KingClient 精简传输层 + 协议导出。

★ 本文件只保留：
  1. KingClient 类（连接管理 + 签名传输 + 明文传输）
  2. 向后兼容的协议导出（from .protocol.* import *）

所有业务逻辑（登录流程、轮询、功能模块）已迁移至 app/ 和 features/。
"""
import time
import hmac
import hashlib
import struct
import requests
import random
from typing import List, Tuple, Optional, Dict, Any

from .protocol import *

# ============ KingClient 类 ============

class KingClient:
    """游戏客户端 —— 连接管理 + 两条传输路径。

    ★ 双传输架构（真机抓包实证）：
      · 读操作（5440/5442/5408/...）—— 必须走签名路径（send_ops）
      · 写操作（4646/4649/5410/5120/...）—— 必须走明文路径（send_ops_raw）

    如果混用会导致：配兵/出征/副本扫荡 **无声失效**（服务端不报错，但也不执行）。
    """

    def __init__(self, username: str, password: str, zone_name: str = ""):
        self.username = username
        self.password = password
        self.zone_name = zone_name

        # 连接状态
        self.zone_id = 0
        self.role_id = 0
        self.session_id = ""
        self.http_session = requests.Session()
        self.http_session.headers.update({
            "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 9; MI 8 MIUI/V12.5.3.0.PEAMIXM)",
            "Content-Type": "application/octet-stream",
            "Connection": "Keep-Alive",
        })

        # 地图尺寸（刷黄锚点生成需要）
        self.map_w = 187
        self.map_h = 56

        # 登录流程需要的旧版字段
        self.c_version = "1630107"
        self.c_type = "7054"
        self.channel_id = "0200000000"
        self.game_url = None
        self.play_id = 0
        self.session = None  # 通行证会话字符串
        self.sub_token = None

    # ---- 签名传输（读操作专用）----

    def send_ops(self, ops_list: List[Tuple[int, bytes]]) -> List[Dict[str, Any]]:
        """签名传输 —— 用于扫描山贼、打矿、刷副本列表等【读操作】。

        参数：[(op, payload), ...]
        返回：[{"op": 应答op, "data": bytes}, ...]

        ★ 写操作（配兵/出征/副本扫荡）禁止走这条路径 —— 会无声失效。
        """
        payload = b""
        for op, data in ops_list:
            payload += pack_packet(op, data)

        # 计算签名
        ts = int(time.time() * 1000)
        sign_data = struct.pack(">q", self.role_id) + struct.pack(">q", ts) + payload
        sign = hmac.new(b"youmi", sign_data, hashlib.md5).hexdigest()

        # 封装请求头
        header = struct.pack(">qqq", self.role_id, ts, self.zone_id)
        header += sign.encode("ascii") + b"\x00" * (64 - len(sign))
        header += struct.pack(">i", len(payload))

        try:
            resp = self.http_session.post(
                f"{LOGIN_URL}/game",
                data=header + payload,
                timeout=10
            )
            if resp.status_code != 200:
                return []
            return unpack_packet(resp.content)
        except Exception:
            return []

    # ---- 明文传输（写操作专用）----

    def send_ops_raw(self, ops_list: List[Tuple[int, bytes]]) -> List[Dict[str, Any]]:
        """明文传输 —— 用于配兵、出征、副本扫荡等【写操作】。

        参数：[(op, payload), ...]
        返回：[{"op": 应答op, "data": bytes}, ...]

        ★ 这是写操作的唯一正确路径。签名路径会导致无声失效。
        """
        payload = b""
        for op, data in ops_list:
            payload += pack_packet(op, data)

        # 明文头（无签名）
        header = struct.pack(">qqq", self.role_id, 0, self.zone_id)
        header += b"\x00" * 64
        header += struct.pack(">i", len(payload))

        try:
            resp = self.http_session.post(
                f"{LOGIN_URL}/game",
                data=header + payload,
                timeout=10
            )
            if resp.status_code != 200:
                return []
            return unpack_packet(resp.content)
        except Exception:
            return []

    # ---- 登录流程专用（旧版协议兼容）----

    def _game_post(self, packets, play_id=None):
        """登录用封包（带签名、加密，兼容旧协议）"""
        import urllib.request
        from .protocol.packets import encrypt, md5_sign, _wutf, _wlong, _wbyte, _wshort

        play_id = self.play_id if play_id is None else play_id
        cur = int(time.time() * 1000)
        header = f"{self.c_version}`{self.c_type}`{self.channel_id}"
        body = _wutf(header) + _wlong(cur) + _wbyte(len(packets))

        NO_ENC_OPS = {4096, 4098, 4101, 4118, 4099, 4097}
        for op, data in packets:
            if op not in NO_ENC_OPS:
                data = encrypt(data)
            sig = md5_sign(op, cur, play_id)
            body += _wlong(play_id) + _wlong(0) + _wshort(len(data)) + _wshort(op) + _wutf(sig) + data

        req = urllib.request.Request(self.game_url, data=body, method="POST")
        req.add_header("Content-Type", "application/octet-stream")
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.read()

    @staticmethod
    def _parse_resp(resp):
        """解析响应包（旧版协议）"""
        from .protocol.packets import decrypt

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

    # ---- 便捷登录方法 ----

    def get_server_list(self):
        """获取区服列表"""
        from .protocol.login import 取区服列表
        self.session, self.sub_token, self.areas = 取区服列表(self.username, self.password)
        return self.areas

    def connect_to_server(self, area_name: str = None, area_index: int = 0):
        """连接到指定区服"""
        from .protocol.login import 匹配区服
        if not hasattr(self, 'areas') or not self.areas:
            self.get_server_list()

        if area_name:
            matched = 匹配区服(self.areas, area_name)
            if matched:
                name, host, port = matched
            else:
                raise ValueError(f"未找到区服: {area_name}")
        else:
            if area_index >= len(self.areas):
                raise ValueError(f"区服索引超出范围: {area_index}")
            name, host, port = self.areas[area_index]

        self.game_host = host
        self.game_port = port
        self.game_url = f"http://{host}:{port}/game"
        return name, host, port

    def login(self, zone_name: str = None, zone_index: int = 0, role_index: int = 0):
        """完整登录流程：区服列表 → 连接 → 进入游戏 → 登录角色

        返回: (区服名, 角色ID, 武将列表)
        """
        from .protocol.login import 进入游戏, 会话探活

        # 1. 获取区服并连接
        area_name, host, port = self.connect_to_server(zone_name or self.zone_name, zone_index)

        # 2. 进入游戏（获取 play_id）
        进入游戏(self)
        if not self.play_id:
            raise RuntimeError("进入游戏失败：未获取到 play_id")

        # 3. 登录角色（获取 role_id）
        packets = 会话探活(self, role_index)
        if not self.role_id:
            raise RuntimeError("登录角色失败：未获取到 role_id")

        # 4. 解析武将列表
        generals = []
        for p in packets:
            if p.get("op") == 4098 + 0x7000:
                info = 解析登录包完整(p.get("data", b""))
                generals = info.get("generals", [])
                break

        return area_name, self.role_id, generals


# ============ 便捷封装函数 ============

def 配兵(client: KingClient, 武将ID: int, 兵种seq: int, 数量: int) -> List[Dict]:
    """发送配兵指令（op 4646）→ 返回应答包列表。

    ★ 必须走明文传输（send_ops_raw），签名路径会无声失效。
    """
    payload = struct.pack(">qhh", 武将ID, 兵种seq, 数量)
    return client.send_ops_raw([(4646, payload)])


def 扫描山贼(client: KingClient, 锚点列表: List[Tuple[int, int]]) -> Dict[int, Dict]:
    """扫描山贼（op 5440）→ 返回 {山贼ID: {id, name, lvl, x, y}}。

    ★ 必须走签名传输（send_ops），明文路径无效。
    """
    ops = [(5440, struct.pack(">Bhh", 0, x, y)) for x, y in 锚点列表]
    packets = client.send_ops(ops)

    result = {}
    for p in packets:
        if p.get("op") == 5440 + 0x7000:
            thieves = 解析山贼应答(p.get("data", b""))
            result.update(thieves)
    return result


def 出征打山贼(client: KingClient, 武将ID列表: List[int], 山贼ID: int) -> List[Dict]:
    """出征打山贼（op 5410）→ 返回应答包列表。

    ★ 必须走明文传输（send_ops_raw），签名路径会无声失效。
    """
    payload = struct.pack(">qb", 山贼ID, len(武将ID列表))
    for gid in 武将ID列表:
        payload += struct.pack(">q", gid)
    return client.send_ops_raw([(5410, payload)])


def 副本扫荡(client: KingClient, 副本ID: int) -> List[Dict]:
    """副本扫荡（op 5120）→ 返回应答包列表。

    ★ 必须走明文传输（send_ops_raw），签名路径会无声失效。
    """
    payload = struct.pack(">i", 副本ID)
    return client.send_ops_raw([(5120, payload)])


# ============ 向后兼容导出 ============

__all__ = [
    "KingClient",
    "配兵", "扫描山贼", "出征打山贼", "副本扫荡",
    # 协议解析（从 protocol 模块导出）
    "LOGIN_URL", "VALIDATE_URL", "CHANNEL_ID", "C_VERSION", "C_TYPE",
    "pack_packet", "unpack_packet",
    "取区服列表", "匹配区服", "会话探活", "检查踢下线", "KICK_OPS", "KICK_MSG",
    "解析国家", "解析登录信息", "解析登录包武将", "解析登录包完整", "解析武将列表",
    "解析配兵应答", "解析部队实时", "格式化部队",
    "解析山贼应答", "格式化山贼",
    "解析副本应答",
    "配兵", "扫描山贼", "出征打山贼", "扫描副本", "出征打副本",
]


# ============ 便捷封装函数 ============

def 配兵(client, 武将ID, 兵种seq, 数量):
    """op 4646 配兵"""
    payload = struct.pack(">IHI", int(武将ID), int(兵种seq), int(数量))
    return client.send_ops_raw([(4646, payload)])


def 扫描山贼(client, anchors):
    """op 5440 扫描山贼（一次一个锚点）"""
    from .protocol.thief import 解析山贼应答
    out = {}
    for x, y in anchors:
        payload = struct.pack(">BHH", 0, int(x), int(y))
        pk = client.send_ops_raw([(5440, payload)])
        thieves = 解析山贼应答(pk)
        out.update(thieves)
    return out


def 出征打山贼(client, 武将ID列表, 山贼ID):
    """op 5410 出征打山贼"""
    cnt = len(武将ID列表)
    fmt = ">BI" + "I" * cnt
    payload = struct.pack(fmt, cnt, int(山贼ID), *[int(g) for g in 武将ID列表])
    return client.send_ops_raw([(5410, payload)])


def 扫描副本(client, anchors):
    """op 5442 扫描副本（与山贼同构）"""
    out = {}
    for x, y in anchors:
        payload = struct.pack(">BHH", 0, int(x), int(y))
        pk = client.send_ops_raw([(5442, payload)])
        dungeons = 解析副本应答(pk)
        out.update(dungeons)
    return out


def 出征打副本(client, 武将ID列表, 副本ID):
    """op 5412 出征打副本（与山贼同构）"""
    cnt = len(武将ID列表)
    fmt = ">BI" + "I" * cnt
    payload = struct.pack(fmt, cnt, int(副本ID), *[int(g) for g in 武将ID列表])
    return client.send_ops_raw([(5412, payload)])

