# -*- coding: utf-8 -*-
"""Feature 基类 —— 插件化任务系统。

每个功能 = 一个 Feature 子类 = 一个文件。
调度器自动发现并按 ORDER 排序执行。
"""
import time
from typing import Dict, Any, List, Optional


class Ctx:
    """Feature.run() 的执行上下文 —— 统一访问 bot 状态和配置。"""

    def __init__(self, bot, cfg, gcfg=None):
        self.bot = bot              # BotSession 实例
        self.client = bot.client    # KingClient 实例
        self.cfg = cfg              # 完整配置 (configs.json)
        self.gcfg = gcfg or {}      # 全局配置（GLOBAL_KEY 对应的对象）
        self.cooldowns = bot._cooldowns  # Cooldowns 实例
        self.bus = bot._bus         # Bus 实例

    def log(self, msg):
        """写日志"""
        self.bot.log(msg)

    def 兵种seq(self, name):
        """兵种名 → seq"""
        for seq, n in (self.bot._兵种名表 or {}).items():
            if n == name:
                return int(seq)
        return None


class Cooldowns:
    """冷却计时器 —— 取代散落的 _pb_last / _sh_last 等。

    TTL=900s 自动清理过期条目，避免内存泄漏。
    """

    def __init__(self, ttl=900):
        self._data: Dict[str, float] = {}
        self._ttl = ttl
        self._last_clean = time.time()

    def get(self, key: str, default=0) -> float:
        """获取上次时间戳"""
        self._maybe_clean()
        return self._data.get(key, default)

    def set(self, key: str, ts: float = None):
        """设置时间戳（默认当前时间）"""
        self._data[key] = ts if ts is not None else time.time()

    def check(self, key: str, interval: float) -> bool:
        """检查是否超过冷却时间（True=可执行）"""
        now = time.time()
        last = self.get(key, 0)
        return now - last >= interval

    def _maybe_clean(self):
        """每 TTL 清理一次过期条目"""
        now = time.time()
        if now - self._last_clean < self._ttl:
            return
        cutoff = now - self._ttl
        self._data = {k: v for k, v in self._data.items() if v >= cutoff}
        self._last_clean = now


class Bus:
    """事件总线 —— 取代 _force_full_at 等强制刷新标记。"""

    def __init__(self):
        self._requests: Dict[str, float] = {}

    def request(self, event: str, delay: float = 0):
        """请求一个事件（delay 秒后触发）"""
        self._requests[event] = time.time() + delay

    def poll(self, event: str) -> bool:
        """检查事件是否到期（True=应该触发，并清除标记）"""
        ts = self._requests.get(event)
        if ts is None:
            return False
        if time.time() >= ts:
            del self._requests[event]
            return True
        return False


class Feature:
    """Feature 基类。

    子类必须定义：
      NAME: str           # 日志前缀
      TYPE: str           # 对应 config 的 type 字段
      ZONE: str | None    # "zone1" / "zone2" / "zone3" / None
      INTERVAL: int       # 执行间隔（秒）
      ORDER: int          # tick 内排序

    可选定义：
      GLOBAL_KEY: str     # 全局配置键（→ ctx.gcfg）
      DAILY: bool         # zone1 语义：每天最多成功一次
      REQUIRES: tuple     # 前置条件（如 ("generals",)）
    """

    NAME = "未命名功能"
    TYPE = ""
    ZONE = None
    GLOBAL_KEY = None
    INTERVAL = 10
    ORDER = 50
    DAILY = False
    REQUIRES = ()

    def run(self, ctx: Ctx, rows: List[Dict[str, Any]]) -> bool:
        """执行功能逻辑。

        Args:
            ctx: 执行上下文
            rows: 该 TYPE 的所有配置行（已过滤 ZONE）

        Returns:
            True = 完成了一次工作（用于 DAILY 计数）
            False = 无工作或失败
        """
        raise NotImplementedError

    @classmethod
    def rows(cls, cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
        """从配置中提取该功能的所有配置行。"""
        if cls.ZONE is None:
            return []
        zone = cfg.get(cls.ZONE) or []
        return [z for z in zone if isinstance(z, dict) and z.get("type") == cls.TYPE]


# 功能注册表（由 features/__init__.py 自动填充）
REGISTRY: List[type] = []
