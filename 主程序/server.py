"""
HTTP 服务器主程序
"""
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from urllib.parse import urlparse, parse_qs
from routes import router


class GameHTTPHandler(BaseHTTPRequestHandler):
    """游戏 HTTP 请求处理器"""

    def _set_headers(self, status_code=200):
        """设置响应头"""
        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def _parse_request(self):
        """解析请求"""
        parsed_path = urlparse(self.path)
        path = parsed_path.path

        # 解析查询参数
        query_params = {}
        if parsed_path.query:
            parsed_qs = parse_qs(parsed_path.query)
            # 将列表值转换为单个值
            query_params = {k: v[0] if len(v) == 1 else v for k, v in parsed_qs.items()}

        return path, query_params

    def _read_body(self):
        """读取请求体"""
        content_length = self.headers.get('Content-Length')
        if not content_length:
            return None

        body = self.rfile.read(int(content_length))
        if not body:
            return None

        try:
            return json.loads(body.decode('utf-8'))
        except json.JSONDecodeError:
            return None

    def _send_response(self, status_code, data):
        """发送响应"""
        self._set_headers(status_code)
        response = json.dumps(data, ensure_ascii=False)
        self.wfile.write(response.encode('utf-8'))

    def do_GET(self):
        """处理 GET 请求"""
        path, query_params = self._parse_request()
        status, data = router.dispatch("GET", path, query_params)
        self._send_response(status, data)

    def do_POST(self):
        """处理 POST 请求"""
        path, query_params = self._parse_request()
        body = self._read_body()
        status, data = router.dispatch("POST", path, query_params, body)
        self._send_response(status, data)

    def do_PUT(self):
        """处理 PUT 请求"""
        path, query_params = self._parse_request()
        body = self._read_body()
        status, data = router.dispatch("PUT", path, query_params, body)
        self._send_response(status, data)

    def do_DELETE(self):
        """处理 DELETE 请求"""
        path, query_params = self._parse_request()
        status, data = router.dispatch("DELETE", path, query_params)
        self._send_response(status, data)

    def do_OPTIONS(self):
        """处理 OPTIONS 请求（CORS 预检）"""
        self._set_headers(200)

    def log_message(self, format, *args):
        """自定义日志格式"""
        print(f"[{self.log_date_time_string()}] {format % args}")


def run_server(host='0.0.0.0', port=8080):
    """启动服务器"""
    server_address = (host, port)
    httpd = HTTPServer(server_address, GameHTTPHandler)
    print(f"服务器启动成功: http://{host}:{port}")
    print("按 Ctrl+C 停止服务器")

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n正在关闭服务器...")
        httpd.shutdown()
        print("服务器已关闭")


if __name__ == "__main__":
    run_server()
