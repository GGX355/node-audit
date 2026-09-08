"""自动发现本机 Clash/mihomo 控制器（Clash Verge Rev 优先，兼容非 Rev / Clash Meta）。

运行时配置通常是 <数据目录>/clash-verge.yaml 或 config.yaml，其中包含：
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
    app_label: str = ""
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
            label = self.app_label or "Clash"
            cfg = f"配置文件 {Path(self.config_path).name}（{label}）"
        else:
            cfg = "配置文件未找到（使用默认值）"
        return f"{chan} | mixed-port {self.mixed_port} | {sec} | {cfg}"


def runtime_config_dirs() -> list[tuple[str, Path]]:
    """(app_label, data_dir) 优先级：Verge Rev → Verge → Clash Meta / mihomo / Clash。"""
    home = Path.home()
    if sys.platform == "win32":
        appdata = Path(os.environ.get("APPDATA", ""))
        return [
            ("Clash Verge Rev", appdata / "io.github.clash-verge-rev.clash-verge-rev"),
            ("Clash Verge", appdata / "io.github.clash-verge.clash-verge"),
            ("Clash Verge Rev", appdata / "clash-verge-rev"),
            ("Clash Verge", appdata / "clash-verge"),
            ("Clash Meta", appdata / "clash-meta"),
            ("mihomo", appdata / "mihomo"),
            ("Clash", home / ".config" / "clash"),
            ("Clash", appdata / "clash"),
        ]
    if sys.platform == "darwin":
        supp = home / "Library" / "Application Support"
        return [
            ("Clash Verge Rev", supp / "io.github.clash-verge-rev.clash-verge-rev"),
            ("Clash Verge", supp / "io.github.clash-verge.clash-verge"),
            ("Clash", home / ".config" / "clash"),
            ("mihomo", home / ".config" / "mihomo"),
        ]
    return [
        ("Clash Verge Rev", home / ".config" / "io.github.clash-verge-rev.clash-verge-rev"),
        ("Clash Verge", home / ".config" / "io.github.clash-verge.clash-verge"),
        ("Clash Verge Rev", home / ".local" / "share" / "io.github.clash-verge-rev.clash-verge-rev"),
        ("Clash", home / ".config" / "clash"),
        ("mihomo", home / ".config" / "mihomo"),
    ]


_RUNTIME_FILES = ("clash-verge.yaml", "config.yaml")


def find_runtime_config() -> Path | None:
    found = find_runtime_config_labeled()
    return found[0] if found else None


def find_runtime_config_labeled() -> tuple[Path, str] | None:
    """返回 (配置路径, 应用名)；Rev 优先，找不到返回 None。"""
    for label, d in runtime_config_dirs():
        for name in _RUNTIME_FILES:
            p = d / name
            if p.is_file():
                return p, label
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
    labeled = find_runtime_config_labeled()
    text = ""
    if labeled:
        cfg, label = labeled
        disc.config_path = str(cfg)
        disc.app_label = label
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
