# -*- coding: utf-8 -*-
"""协议模块 — 拆分自 king_client.py，按功能组织

导出所有协议函数供 server.py 和 features/ 使用
"""
from .login import 进入游戏

__all__ = ["进入游戏"]
