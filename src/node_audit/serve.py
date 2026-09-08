"""本机控制台 HTTP 服务：只绑 127.0.0.1，零第三方依赖。"""
from __future__ import annotations

import json
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .core.history import _empty_dashboard, load_dashboard
from .report.dashboard import render_dashboard


def _payload(db_path: Path, runs_limit: int) -> dict:
    if db_path.is_file():
        return load_dashboard(db_path, runs_limit)
    return _empty_dashboard()


def make_handler(db_path: Path, runs_limit: int = 30):
    """返回绑定了 db 路径的 BaseHTTPRequestHandler 子类。"""

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def _send(self, code: int, body: bytes, content_type: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path in ("/api/data", "/api/data.json"):
                raw = json.dumps(_payload(db_path, runs_limit), ensure_ascii=False).encode("utf-8")
                self._send(200, raw, "application/json; charset=utf-8")
                return
            if path in ("/", "/index.html", "/latest.html"):
                html = render_dashboard(_payload(db_path, runs_limit)).encode("utf-8")
                self._send(200, html, "text/html; charset=utf-8")
                return
            self.send_error(404, "not found")

    return Handler


def make_server(db_path, port: int = 0, runs_limit: int = 30) -> ThreadingHTTPServer:
    handler = make_handler(Path(db_path), runs_limit)
    return ThreadingHTTPServer(("127.0.0.1", port), handler)


def run_server(out_dir, port: int = 8765, open_browser: bool = False,
               db_path=None, runs_limit: int = 30) -> int:
    out = Path(out_dir)
    db = Path(db_path) if db_path else out / "history.db"
    httpd = make_server(db, port=port, runs_limit=runs_limit)
    host, bound = httpd.server_address
    url = f"http://{host}:{bound}/"
    print(f"控制台 {url}")
    print(f"数据   {db}{'（尚无 history.db，显示空状态）' if not db.is_file() else ''}")
    print("只监听 127.0.0.1 · Ctrl+C 停止")
    if open_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        httpd.server_close()
    return 0
