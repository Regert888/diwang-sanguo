# -*- coding: utf-8 -*-
"""基础刷新功能 —— 维持角色在线状态。

★ 必须执行，取代原来 _refresh() 里的 _全量刷新() 调用
★ ORDER=0 确保最先执行（其他功能依赖刷新后的数据）
"""
import time
from app.feature import Feature


class RefreshFeature(Feature):
    NAME = "基础刷新"
    TYPE = None          # 不对应配置里的 type，永远启用
    ZONE = None          # 不在任何 zone 里
    INTERVAL = 10        # 10秒一次（原来是 time.sleep(10)）
    ORDER = 0            # 最高优先级
    REQUIRES = ()        # 无依赖
    DAILY = False

    def __init__(self):
        super().__init__()
        self._rfc = 0    # refresh count（轮次计数）

    def should_run(self, now):
        """基础刷新永远执行（覆盖父类的 INTERVAL 检查）"""
        return True

    def run(self, ctx, rows):
        """执行基础刷新（维持在线状态 + 拉取最新数据）"""
        self._rfc += 1

        try:
            # ★ 首轮立即强制取完整包（不等 120 秒），之后每 12 轮强制一次
            强制 = (self._rfc == 1 or self._rfc % 12 == 0)

            # ★ 出征/配兵后 4 秒强制完整刷新（同步武将状态）
            if ctx.bus.poll("full_refresh"):
                强制 = True
                ctx.log("[基础刷新] 触发全量刷新（Bus 请求）")

            ctx.bot._全量刷新(强制完整=强制)
            return True

        except Exception as e:
            ctx.log(f"[基础刷新] 失败: {e}")
            return False
