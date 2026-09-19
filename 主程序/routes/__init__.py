"""
路由模块 - API 路由定义
"""
from .router import router
from . import player_routes
from . import tile_routes
from . import army_routes
from . import bot_routes
from . import health_routes

__all__ = ["router"]
