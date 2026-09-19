# -*- coding: utf-8 -*-
"""登录协议（从借鉴代码迁移）"""
import struct
import urllib.request
from .packets import _wutf, _wlong, _wbyte, _wshort, LOGIN_URL, VALIDATE_URL, CHANNEL_ID, C_VERSION, C_TYPE, TARGET_ALL

# 踢下线操作码
KICK_OPS = {-1, -3, -4, -5}
KICK_MSG = {
    -1: "账号在其他地方登录",
    -3: "会话失效",
    -4: "服务器维护",
    -5: "账号被封禁"
}


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


def 进入游戏(client):
    """进入游戏（op 4096），旧名保持兼容"""
    return enter_game(client)


def enter_game(client):
    """进入游戏（op 4096）"""
    body = _wlong(client.play_id) + _wutf("") + _wutf(client.session) + _wutf(client.sub_token)
    body += _wshort(0) + _wbyte(0) + _wutf("")
    resp = client._game_post([(4096, body)])
    packets = client._parse_resp(resp)
    return packets


def game_login(client, role_index=0):
    """登录游戏（op 4100）

    role_index: 角色索引（0=第一个角色）
    """
    body = _wlong(client.play_id) + _wbyte(role_index)
    resp = client._game_post([(4100, body)])
    packets = client._parse_resp(resp)

    # 解析角色ID（从响应包提取）
    for p in packets:
        if p.get("op") == 32772:  # gameLogin 响应
            data = p.get("data", b"")
            if len(data) >= 8:
                client.role_id = struct.unpack(">q", data[0:8])[0]
                break

    return packets
