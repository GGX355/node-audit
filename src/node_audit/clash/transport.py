r"""mihomo 外部控制器的 HTTP 传输层。

支持两种通道（按配置自动选择或显式指定）：
- TCP:        external-controller 启用时（如 http://127.0.0.1:9090）
- 命名管道:   Clash Verge Rev (Windows) 默认，\\.\pipe\verge-mihomo

统一使用 HTTP/1.0 + Connection: close，避开 keep-alive 与 chunked 编码，
管道模式下通过工作线程为阻塞式读写提供超时兜底。
"""
from __future__ import annotations

import ctypes
import http.client
import json
import os
import threading
import time


class TransportError(RuntimeError):
    """传输层错误（连接失败 / 超时 / 响应不完整）。"""


class TcpTransport:
    """TCP 通道：external-controller 启用时的标准 HTTP API。"""

    def __init__(self, host: str, port: int, secret: str = ""):
        self.host = host
        self.port = port
        self.secret = secret

    def request(self, method: str, path: str, body=None, timeout: float = 30):
        conn = http.client.HTTPConnection(self.host, self.port, timeout=timeout)
        try:
            headers = {"Authorization": f"Bearer {self.secret}", "Connection": "close"}
            payload = None
            if body is not None:
                payload = json.dumps(body).encode()
                headers["Content-Type"] = "application/json"
            conn.request(method, path, body=payload, headers=headers)
            resp = conn.getresponse()
            return resp.status, resp.read()
        finally:
            conn.close()


class PipeTransport:
    """Windows 命名管道通道。

    mihomo 的管道监听器本质是挂在 \\\\.\\pipe\\<name> 上的 HTTP 服务，
    直接对管道文件读写 HTTP/1.0 报文即可。open() 失败时回退到
    ctypes CreateFileW + msvcrt.open_osfhandle。
    """

    def __init__(self, pipe_name: str, secret: str = ""):
        self.pipe_name = pipe_name
        self.pipe_path = "\\\\.\\pipe\\" + pipe_name
        self.secret = secret

    def _open(self):
        # 管道偶尔繁忙（ERROR_PIPE_BUSY）时短暂等待后重试一次
        for attempt in (1, 2):
            try:
                return open(self.pipe_path, "r+b", buffering=0)
            except OSError:
                if attempt == 1:
                    time.sleep(0.25)
        kernel32 = ctypes.windll.kernel32
        GENERIC_READ = 0x80000000
        GENERIC_WRITE = 0x40000000
        OPEN_EXISTING = 3
        handle = kernel32.CreateFileW(
            self.pipe_path, GENERIC_READ | GENERIC_WRITE, 0, None, OPEN_EXISTING, 0, None
        )
        if handle in (-1, 0xFFFFFFFFFFFFFFFF):
            raise TransportError(f"无法打开命名管道 {self.pipe_path}")
        import msvcrt

        fd = msvcrt.open_osfhandle(handle, os.O_RDWR)
        return os.fdopen(fd, "r+b", buffering=0)

    def _roundtrip(self, method: str, path: str, body) -> tuple:
        payload = b""
        headers = (
            "Host: mihomo\r\n"
            f"Authorization: Bearer {self.secret}\r\n"
            "Connection: close\r\n"
        )
        if body is not None:
            payload = json.dumps(body).encode()
            headers += f"Content-Type: application/json\r\nContent-Length: {len(payload)}\r\n"
        req = f"{method} {path} HTTP/1.0\r\n{headers}\r\n".encode() + payload

        f = self._open()
        try:
            f.write(req)
            data = b""
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                data += chunk
        finally:
            f.close()
        head, _, body_bytes = data.partition(b"\r\n\r\n")
        if not head:
            raise TransportError("管道响应为空")
        status_line = head.split(b"\r\n")[0].decode(errors="replace")
        parts = status_line.split()
        if len(parts) < 2 or not parts[1].isdigit():
            raise TransportError(f"无法解析状态行: {status_line!r}")
        return int(parts[1]), body_bytes

    def request(self, method: str, path: str, body=None, timeout: float = 30):
        # 管道在服务端繁忙时 open()/read() 可能阻塞且无超时，放工作线程兜底。
        result: dict = {}

        def work():
            try:
                result["ret"] = self._roundtrip(method, path, body)
            except Exception as e:  # noqa: BLE001
                result["err"] = e

        t = threading.Thread(target=work, daemon=True)
        t.start()
        t.join(timeout)
        if t.is_alive():
            raise TransportError(f"管道请求超时（>{timeout}s）: {method} {path}")
        if "err" in result:
            raise result["err"]
        return result["ret"]
