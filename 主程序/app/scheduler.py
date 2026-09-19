# -*- coding: utf-8 -*-
"""调度器 —— 取代 _refresh() 的统一任务循环。

单一 try/except 取代 4 个手写的异常处理。
Event.wait(1) 取代 time.sleep(10)，让 stop() 真正生效。
"""
import time
import threading
from typing import List
from app.feature import Feature, Ctx, Cooldowns, Bus


class Scheduler:
    """功能调度器。

    每个账号独立实例，避免状态混淆（Bug 3 类问题）。
    """

    def __init__(self, bot, features: List[Feature]):
        self.bot = bot
        self.features = sorted(features, key=lambda f: f.ORDER)  # 按 ORDER 排序
        self._stop_event = threading.Event()
        self._last_run = {}  # {feature_name: timestamp}

    def tick(self):
        """主循环 —— 取代 _refresh()。

        每秒检查一次，按 INTERVAL 决定是否执行。
        """
        while not self._stop_event.is_set():
            try:
                # 1 秒粒度检查，取代 time.sleep(10)
                self._stop_event.wait(1)

                if self._stop_event.is_set():
                    break

                # 检查每个功能是否该执行
                now = time.time()
                for feature in self.features:
                    last = self._last_run.get(feature.NAME, 0)
                    if now - last < feature.INTERVAL:
                        continue

                    # 执行功能
                    try:
                        self._run_feature(feature)
                        self._last_run[feature.NAME] = now
                    except Exception as e:
                        self.bot.log(f"[调度器] {feature.NAME} 异常: {e}")
                        import traceback
                        traceback.print_exc()

            except Exception as e:
                self.bot.log(f"[调度器] tick 异常: {e}")
                import traceback
                traceback.print_exc()

    def _run_feature(self, feature: Feature):
        """执行单个功能。"""
        # 检查前置条件
        for req in feature.REQUIRES:
            if req == "generals":
                if not self.bot.generals:
                    return
            elif req == "logged_in":
                if self.bot.status != 1:
                    return

        # 读取配置
        cfg = self.bot._read_config()
        if not cfg:
            return

        # 全局配置
        gcfg = None
        if feature.GLOBAL_KEY:
            gcfg = cfg.get(feature.GLOBAL_KEY) or {}

        # 提取配置行（RefreshFeature 等特殊功能 ZONE=None，永远执行）
        rows = feature.rows(cfg)
        if not rows and feature.ZONE is not None:
            return

        # 构造上下文
        ctx = Ctx(self.bot, cfg, gcfg)

        # 执行
        result = feature.run(ctx, rows)

        # DAILY 语义：每天最多成功一次
        if result and feature.DAILY:
            # TODO: 实现日期切换逻辑
            pass

    def stop(self):
        """停止调度器。"""
        self._stop_event.set()
