# -*- coding: utf-8 -*-
"""账号会话 —— 一个账号一个实例，持有连接、状态和调度器。

这是 Feature 系统的宿主：Scheduler 通过 Ctx 访问这里的 client / 配置 /
原子数据。原 BotSession 拆解后，「定时跑任务」这部分职责落在这里。

生命周期：
    Session(account) → login() → start() → ... → stop()
"""
import json
import os
import time
import threading

from app.feature import Cooldowns, Bus
from app.scheduler import Scheduler
from app.state import SessionState

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIGS_FILE = os.path.join(BASE, "configs.json")

# 状态码（沿用旧 BotSession 约定，前端依赖这些值）
STOPPED = 0
RUNNING = 1
STARTING = 2
NEED_VERIFY = 5


class Session:
    """单账号运行会话。"""

    def __init__(self, account):
        self.acct_id = account["id"]
        self.user = account["gameUsername"]
        self.pwd = account["gamePassword"]
        self.server_name = account.get("serverName", "")
        self.server_key = account.get("serverKey", "")
        self.role_index = int(account.get("characterIndex", 0) or 0)

        self.client = None
        self.status = STOPPED
        self.running = False
        self.last_error = ""
        self.start_time = 0
        self.logs = []

        # ---- 原子数据（投影的唯一来源）----
        self.character = {}
        self._武将原始A4 = []
        self._部队表 = {}
        self._伤兵表 = {}
        self._兵种名表 = self._载入兵种名表()

        # ---- Feature 基础设施 ----
        self._cooldowns = Cooldowns()
        self._bus = Bus()
        self._state = SessionState()

        # ---- 功能写入区 ----
        self._army_action = None

        self._scheduler = None
        self._thread = None

    # ================= 投影（前端读这两个）=================

    @property
    def generals(self):
        from app.presenters import build_generals
        return build_generals(self._武将原始A4, self._部队表, self._兵种名表)

    @property
    def troops(self):
        from app.presenters import build_troops
        return build_troops(self._伤兵表, self._兵种名表)

    # ================= 基础设施 =================

    def log(self, msg):
        self.logs.append("[%s] %s" % (time.strftime("%H:%M:%S"), msg))
        if len(self.logs) > 300:
            self.logs = self.logs[-300:]

    def _read_config(self):
        """读该账号的 zone1/zone2/zone3 配置。"""
        try:
            with open(CONFIGS_FILE, encoding="utf-8") as f:
                return (json.load(f) or {}).get(str(self.acct_id), {})
        except Exception:
            return {}

    def _write_config(self, cfg):
        """整份替换该账号的配置（daily 写 lastRunDate 用）。"""
        try:
            with open(CONFIGS_FILE, encoding="utf-8") as f:
                all_cfg = json.load(f) or {}
        except Exception:
            all_cfg = {}
        all_cfg[str(self.acct_id)] = cfg
        tmp = CONFIGS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(all_cfg, f, ensure_ascii=False, indent=1)
        os.replace(tmp, CONFIGS_FILE)

    @staticmethod
    def _载入兵种名表():
        try:
            p = os.path.join(BASE, "兵种名表.json")
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    # ================= 登录 =================

    def login(self):
        """登录游戏，成功返回 True。"""
        from core.king_client import KingClient, 取区服列表, 匹配区服
        from core.protocol.login import enter_game, game_login

        self.status = STARTING
        try:
            self.log("正在获取区服列表…")
            session, sub, areas = 取区服列表(self.user, self.pwd)
            if not areas:
                return self._失败("账号或密码错误")

            # serverKey 优先，失败再退 serverName —— 两者都匹配不到就报错，
            # 不能静默兜底到 areas[0]（那会连到完全不相干的区服）
            匹配 = (匹配区服(areas, self.server_key)
                    or 匹配区服(areas, self.server_name))
            if not 匹配:
                return self._失败("找不到区服：%s / %s（共 %d 个可选）" % (
                    self.server_key, self.server_name, len(areas)))
            name, host, port = 匹配
            self.server_name = name
            self.log("目标区服：%s（%s:%s）" % (name, host, port))

            c = KingClient()
            # ★ 真机抓包确认：路径是 /kingWapServer/HttpClient，不是 /game
            c.game_url = "http://%s:%s/kingWapServer/HttpClient" % (host, port)
            c.session = session
            c.sub_token = sub
            c.play_id = 0

            pk = enter_game(c)
            if pk:
                c.play_id = pk[0].get("play", 0)
            if not c.play_id:
                return self._失败("未获取到 play_id")

            c.login_packets = game_login(c, role_index=self.role_index)
            self.client = c
            self.log("登录成功，play_id=%s" % c.play_id)

            self._首次拉取()
            return True

        except Exception as e:
            return self._失败("登录失败: %s" % e)

    def _失败(self, msg):
        self.status = STOPPED
        self.running = False
        self.last_error = msg
        self.log("[失败] %s" % msg)
        return False

    def _首次拉取(self):
        """登录后立刻填充角色信息和武将，避免首屏空白。"""
        try:
            self.character = self.client.取角色全部信息()
            self.log("君主：%s　等级：%s" % (
                self.character.get("charName", "?"),
                self.character.get("level", "?")))
        except Exception as e:
            self.log("[警告] 角色信息读取失败：%s" % e)

        try:
            from core.king_client import 解析武将列表
            for p in (self.client.login_packets or []):
                if p.get("op") == 32772 and p.get("data"):
                    raw = 解析武将列表(p["data"])
                    if raw:
                        self._武将原始A4 = raw
                        self.log("解析到 %d 个武将" % len(raw))
                    break
        except Exception as e:
            self.log("[调试] 武将解析失败: %s" % e)

    # ================= 调度 =================

    def start(self):
        """启动 Feature 调度（后台线程）。"""
        if self._thread and self._thread.is_alive():
            self.log("[警告] 会话已在运行，忽略重复启动")
            return

        from app.feature import REGISTRY
        import features  # noqa: F401  触发自动发现

        self.running = True
        self.status = RUNNING
        self.start_time = time.time()

        # 每账号独立实例化 —— 共享实例会让冷却/计数器跨账号污染
        self._scheduler = Scheduler(self, [cls() for cls in REGISTRY])
        self._thread = threading.Thread(
            target=self._scheduler.tick,
            name="sched-%s" % self.acct_id,
            daemon=True,
        )
        self._thread.start()
        self.log("[调度] 已启动 %d 个功能" % len(self._scheduler.features))

    def stop(self):
        self.running = False
        self.status = STOPPED
        if self._scheduler:
            self._scheduler.stop()
        self.log("[调度] 已停止")

    @property
    def uptime(self):
        return int(time.time() - self.start_time) if self.start_time else 0


# ================= 会话注册表 =================

_sessions = {}
_lock = threading.Lock()


def get(acct_id):
    """取会话，不存在返回 None。"""
    return _sessions.get(int(acct_id))


def create(account):
    """创建会话（同 id 已存在则先停掉旧的）。"""
    aid = int(account["id"])
    with _lock:
        旧 = _sessions.get(aid)
        if 旧:
            旧.stop()
        s = Session(account)
        _sessions[aid] = s
        return s


def all_sessions():
    return dict(_sessions)
