"""自动发现本机 Clash/mihomo 控制器（Clash Verge Rev 优先）。

Verge Rev 的运行时配置位于 <数据目录>/clash-verge.yaml，其中包含：
external-controller（为空字符串 = TCP API 关闭）、external-controller-pipe、
secret、mixed-port。这里不引入 PyYAML，用小范围正则提取这几个键，保持零依赖。
"""
from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Discovery:
    config_path: str | None = None
    transport: str = "pipe"  # "tcp" | "pipe"
    host: str = "127.0.0.1"
    port: int = 9090
    pipe_name: str = "verge-mihomo"
    secret: str = ""
    mixed_port: int = 7890
    notes: list = field(default_factory=list)

    def describe(self) -> str:
        if self.transport == "pipe":
            chan = "\\\\.\\pipe\\" + self.pipe_name
        else:
            chan = f"tcp http://{self.host}:{self.port}"
        sec = "secret 已读取" if self.secret else "secret 无"
        if self.config_path:
            # 只显示文件名，不显示完整路径：报告会被分享，避免泄露本地用户名
            cfg = f"配置文件 {Path(self.config_path).name}（Verge Rev）"
        else:
            cfg = "配置文件未找到（使用默认值）"
        return f"{chan} | mixed-port {self.mixed_port} | {sec} | {cfg}"


def find_runtime_config() -> Path | None:
    if sys.platform == "win32":
        dirs = [Path(os.environ.get("APPDATA", "")) / "io.github.clash-verge-rev.clash-verge-rev"]
    elif sys.platform == "darwin":
        dirs = [Path.home() / "Library/Application Support/io.github.clash-verge-rev.clash-verge-rev"]
    else:
        dirs = [Path.home() / ".config/io.github.clash-verge-rev.clash-verge-rev"]
    for d in dirs:
        for name in ("clash-verge.yaml", "config.yaml"):
            p = d / name
            if p.is_file():
                return p
    return None


def _pick(text: str, pattern: str) -> str | None:
    m = re.search(pattern, text, re.M)
    return m.group(1) if m else None


def _strip_comment(v: str) -> str:
    """去掉 YAML 行内注释（' #' 起始部分），避免把注释收进值里。"""
    return re.split(r"\s+#", v, maxsplit=1)[0].strip()


def _unquote(v: str | None) -> str:
    if v is None:
        return ""
    v = _strip_comment(v)
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
        v = v[1:-1]
    return v


def discover(explicit: dict | None = None) -> Discovery:
    """探测控制器；explicit 可强制覆盖 {"api": "host:port", "pipe": name,
    "secret": str, "mixed_port": int}。"""
    disc = Discovery()
    cfg = find_runtime_config()
    text = ""
    if cfg:
        disc.config_path = str(cfg)
        text = cfg.read_text(encoding="utf-8", errors="replace")

    ec = _unquote(_pick(text, r"^\s*external-controller:\s*(.*?)\s*$"))
    pipe = _unquote(_pick(text, r"^\s*external-controller-pipe:\s*(.*?)\s*$"))
    secret = _unquote(_pick(text, r"^\s*secret:\s*(.*?)\s*$"))
    mp = _unquote(_pick(text, r"^\s*mixed-port:\s*(.*?)\s*$"))

    disc.secret = secret
    if mp.isdigit():
        disc.mixed_port = int(mp)
    if ec:
        host, _, port = ec.rpartition(":")
        disc.transport = "tcp"
        disc.host = host or "127.0.0.1"
        disc.port = int(port) if port.isdigit() else 9090
    elif pipe:
        disc.transport = "pipe"
        disc.pipe_name = re.split(r"[\\/]", pipe)[-1]

    if explicit:
        if explicit.get("pipe"):
            disc.transport = "pipe"
            disc.pipe_name = explicit["pipe"]
        if explicit.get("api"):
            host, _, port = explicit["api"].rpartition(":")
            disc.transport = "tcp"
            disc.host = host or "127.0.0.1"
            disc.port = int(port)
        if explicit.get("secret") is not None:
            disc.secret = explicit["secret"]
        if explicit.get("mixed_port"):
            disc.mixed_port = int(explicit["mixed_port"])
    return disc
