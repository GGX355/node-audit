"""mihomo RESTful API 封装（仅暴露本工具用到的端点）。"""
from __future__ import annotations

import json
from urllib.parse import quote, urlencode


class ControllerError(RuntimeError):
    """控制器返回了非预期状态。"""


class ClashAPI:
    def __init__(self, transport):
        self.transport = transport

    def _call(self, method: str, path: str, body=None, timeout: float = 30) -> bytes:
        status, data = self.transport.request(method, path, body=body, timeout=timeout)
        if status >= 400:
            raise ControllerError(f"{method} {path} -> HTTP {status}: {data[:200]!r}")
        return data

    def _get_json(self, path: str, timeout: float = 30):
        return json.loads(self._call("GET", path, timeout=timeout).decode() or b"{}")

    def version(self) -> dict:
        return self._get_json("/version")

    def configs(self) -> dict:
        return self._get_json("/configs")

    def patch_configs(self, body: dict) -> None:
        """修改运行时配置，如 {"mode": "global"}。"""
        self._call("PATCH", "/configs", body=body)

    def proxies(self) -> dict:
        """全部代理条目：{name: {type, now, history, ...}}。"""
        return self._get_json("/proxies").get("proxies", {})

    def select_proxy(self, group: str, name: str) -> None:
        """在 selector 组里切换选中节点。"""
        self._call("PUT", f"/proxies/{quote(group, safe='')}", body={"name": name})

    def group_delay(self, group: str, url: str, timeout_ms: int = 5000) -> dict:
        """批量测试组内所有节点的延迟，返回 {name: ms 或 {message: 错误}}。"""
        qs = urlencode({"url": url, "timeout": timeout_ms})
        return self._get_json(
            f"/group/{quote(group, safe='')}/delay?{qs}", timeout=timeout_ms / 1000 + 20
        )

    def proxy_delay(self, name: str, url: str, timeout_ms: int = 5000) -> dict:
        qs = urlencode({"url": url, "timeout": timeout_ms})
        return self._get_json(
            f"/proxies/{quote(name, safe='')}/delay?{qs}", timeout=timeout_ms / 1000 + 15
        )
