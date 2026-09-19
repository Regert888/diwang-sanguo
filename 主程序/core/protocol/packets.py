"""协议基础：打包函数、加解密"""
import struct, hashlib

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

def _wutf(s):
    """UTF-8 字符串 → 2字节长度前缀 + UTF-8 字节"""
    b = s.encode("utf-8")
    return struct.pack(">H", len(b)) + b

def _wlong(v):
    """long (8字节大端)"""
    return struct.pack(">q", v)

def _wshort(v):
    """short (2字节大端)"""
    return struct.pack(">H", v & 0xFFFF)

def _wbyte(v):
    """byte (1字节)"""
    return struct.pack(">B", v & 0xFF)

def md5_sign(op, cur_time, play_id):
    """签名路：MD5(op + time + playId + SALT)"""
    return hashlib.md5((str(op + cur_time + play_id) + SALT).encode()).hexdigest().lower()

def enc_key():
    """加密密钥 = KEY_RAW - SALT(UTF-8)"""
    wu = _wutf(SALT)
    return bytes((KEY_RAW[i] - wu[i % len(wu)]) & 0xFF for i in range(len(KEY_RAW)))

def encrypt(data, key=None):
    """加密：data + key"""
    key = key or enc_key()
    return bytes((data[i] + key[i % len(key)]) & 0xFF for i in range(len(data)))

def decrypt(data, key=None):
    """解密：data - key"""
    key = key or enc_key()
    return bytes((data[i] - key[i % len(key)]) & 0xFF for i in range(len(data)))


def pack_packet(op: int, data: bytes) -> bytes:
    """打包单个数据包：[short op][int len][data]"""
    return struct.pack(">Hi", op, len(data)) + data


def unpack_packet(raw: bytes) -> list:
    """解包响应：返回 [{"op": int, "data": bytes}, ...]"""
    packets = []
    offset = 0
    while offset + 6 <= len(raw):
        op, ln = struct.unpack_from(">Hi", raw, offset)
        offset += 6
        if offset + ln > len(raw):
            break
        data = raw[offset:offset + ln]
        packets.append({"op": op, "data": data})
        offset += ln
    return packets
