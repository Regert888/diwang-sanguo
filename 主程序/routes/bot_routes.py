"""
Bot 路由 —— 账号启停 + 前端轮询。

poll 的数据源是内存里的 Session（实时游戏状态），
不是 db_manager 里的 JSON（那是静态测试数据）。
"""
import json
import os

from routes.router import router
from app import session as sess

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ACCOUNTS_FILE = os.path.join(BASE, "accounts.json")


def _取账号(aid):
    try:
        with open(ACCOUNTS_FILE, encoding="utf-8") as f:
            for a in json.load(f) or []:
                if int(a.get("id", -1)) == int(aid):
                    return a
    except Exception:
        pass
    return None


def _空状态(msg=""):
    """账号未运行时的 21 键占位响应。"""
    return {
        "status": 0, "character": None, "generals": [], "officers": [],
        "troops": [], "items": [], "roleStatuses": [], "roleStatusList": [],
        "convoyCountries": [], "logs": [], "total": 0, "nextIndex": 0,
        "running": False, "uptime": 0, "alarmActive": False, "alarmCount": 0,
        "tasks": [], "worker": "", "lastError": msg, "lastAccessTime": 0,
        "source": "backend",
    }


@router.get("/api/bot/poll")
def poll(query_params):
    """轮询账号实时状态（21 键契约）。

    参数：id（账号）、sinceIndex（日志增量游标）
    """
    aid = query_params.get("id", "1")
    since = int(query_params.get("sinceIndex", 0) or 0)

    s = sess.get(aid)
    if not s:
        return 200, _空状态("会话未启动")

    logs = s.logs[since:] if since < len(s.logs) else []

    return 200, {
        "status": s.status,
        "character": s.character or None,
        "generals": s.generals,
        "officers": [],
        "troops": s.troops,
        "items": [],
        "roleStatuses": [],
        "roleStatusList": [],
        "convoyCountries": [],
        "logs": logs,
        "total": len(s.logs),
        "nextIndex": len(s.logs),
        "running": s.running,
        "uptime": s.uptime,
        "alarmActive": False,
        "alarmCount": 0,
        "tasks": [],
        "worker": "",
        "lastError": s.last_error,
        "lastAccessTime": 0,
        "source": "backend",
    }


@router.post("/api/bot/start")
def start(query_params, body):
    """登录并启动自动化调度。"""
    aid = (body or {}).get("id") or query_params.get("id")
    if not aid:
        return 400, {"error": "缺少账号 id"}

    account = _取账号(aid)
    if not account:
        return 404, {"error": "账号不存在: %s" % aid}

    s = sess.create(account)
    if not s.login():
        return 400, {"error": s.last_error}

    s.start()
    return 200, {"id": int(aid), "status": s.status, "msg": "已启动"}


@router.post("/api/bot/stop")
def stop(query_params, body):
    """停止调度（保留会话数据供查看）。"""
    aid = (body or {}).get("id") or query_params.get("id")
    if not aid:
        return 400, {"error": "缺少账号 id"}

    s = sess.get(aid)
    if not s:
        return 404, {"error": "会话不存在"}

    s.stop()
    return 200, {"id": int(aid), "status": s.status, "msg": "已停止"}


@router.get("/api/bot/list")
def list_sessions(query_params):
    """所有会话概览。"""
    return 200, {
        "sessions": [
            {
                "id": aid,
                "status": s.status,
                "running": s.running,
                "uptime": s.uptime,
                "character": (s.character or {}).get("charName", ""),
                "lastError": s.last_error,
            }
            for aid, s in sess.all_sessions().items()
        ]
    }
