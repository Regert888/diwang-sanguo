"""
路由器 - 负责请求分发和响应处理
"""
import json
from typing import Callable, Dict, Any, Optional, Tuple
from urllib.parse import parse_qs


class Router:
    """HTTP 路由器"""

    def __init__(self):
        self._routes: Dict[str, Dict[str, Callable]] = {
            "GET": {},
            "POST": {},
            "PUT": {},
            "DELETE": {}
        }

    def route(self, path: str, method: str = "GET"):
        """路由装饰器"""
        def decorator(handler: Callable):
            self._routes[method][path] = handler
            return handler
        return decorator

    def get(self, path: str):
        """GET 路由装饰器"""
        return self.route(path, "GET")

    def post(self, path: str):
        """POST 路由装饰器"""
        return self.route(path, "POST")

    def put(self, path: str):
        """PUT 路由装饰器"""
        return self.route(path, "PUT")

    def delete(self, path: str):
        """DELETE 路由装饰器"""
        return self.route(path, "DELETE")

    def dispatch(self, method: str, path: str, query_params: Dict[str, Any],
                 body: Optional[Dict[str, Any]] = None) -> Tuple[int, Dict[str, Any]]:
        """
        分发请求到对应的处理器

        Returns:
            (status_code, response_data)
        """
        handler = self._routes.get(method, {}).get(path)

        if not handler:
            return 404, {"error": f"Route not found: {method} {path}"}

        try:
            # 调用处理器
            if method in ["POST", "PUT"]:
                result = handler(query_params, body or {})
            else:
                result = handler(query_params)

            # 处理器返回格式：(status, data) 或 data
            if isinstance(result, tuple):
                status, data = result
                return status, data
            else:
                return 200, result

        except Exception as e:
            return 500, {"error": str(e)}


# 全局路由器实例
router = Router()
