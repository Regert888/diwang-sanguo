# -*- coding: utf-8 -*-
"""健康检查路由"""
from routes.router import router
import time


@router.get("/api/health")
def health_check(query_params):
    """健康检查接口 - 返回服务器状态"""
    return {
        "status": "healthy",
        "service": "帝王三国自动化服务",
        "version": "2.0",
        "timestamp": int(time.time() * 1000)
    }
