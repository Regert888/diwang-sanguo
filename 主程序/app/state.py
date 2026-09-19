# -*- coding: utf-8 -*-
"""会话状态管理 —— 每个账号的可变状态的统一所有者。

★ SessionState 负责：
  1. 武将锁定（claim）：防止多功能同时派遣同一武将
  2. 原子数据访问（未来可扩展为线程安全的 mutator）
"""
import time
import threading


class SessionState:
    """每个 BotSession 的状态容器。

    目前主要功能：武将锁定机制（claim）。
    未来可扩展为线程安全的状态访问层。
    """

    def __init__(self):
        self._claims = {}       # {genId: expire_time}
        self._lock = threading.Lock()

    def claim(self, gids, ttl=120):
        """原子锁定武将（全有或全无）。

        Args:
            gids: 武将ID列表
            ttl: 锁定时长（秒），默认120秒

        Returns:
            bool: True=成功锁定，False=至少一个武将已被占用

        用途：
            防止多功能同时派遣同一武将。例如：
            - 刷黄要派 [1,2,3]
            - 打矿要派 [3,4,5]
            - 同一 tick 内，只有一个能成功 claim(3)
        """
        if not gids:
            return True

        now = time.time()
        expire_at = now + ttl

        with self._lock:
            # 1) 清理过期锁
            self._claims = {g: t for g, t in self._claims.items() if t > now}

            # 2) 检查是否全部空闲
            for gid in gids:
                if gid in self._claims:
                    return False  # 至少一个被占用，全部失败

            # 3) 全有或全无：全部锁定
            for gid in gids:
                self._claims[gid] = expire_at

            return True

    def release(self, gids):
        """提前释放武将锁（可选，通常靠 TTL 自动过期）。

        Args:
            gids: 武将ID列表
        """
        with self._lock:
            for gid in gids:
                self._claims.pop(gid, None)

    def is_claimed(self, gid):
        """检查武将是否被锁定。

        Args:
            gid: 武将ID

        Returns:
            bool: True=已锁定，False=空闲
        """
        now = time.time()
        with self._lock:
            return self._claims.get(gid, 0) > now
