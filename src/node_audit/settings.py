"""node-audit.ini：双击 exe 时读的简单设置。标准库 configparser，无第三方依赖。"""
from __future__ import annotations

from configparser import ConfigParser
from dataclasses import dataclass
from pathlib import Path

INI_TEMPLATE = """# node-audit 设置（UTF-8）。不懂就保持默认，双击 exe 选 1 即可。
# 改完保存，下次双击生效。行首加 # 表示注释，不算设置。

[audit]
# isolated = 零干扰（推荐）。attach = 会切换你正在用的代理，一般别改。
mode = isolated

# 只测名称匹配的节点，例如 台湾|香港原生。留空 = 全量。
include =
exclude =
# 最多测前 N 个。留空 = 不限制。
limit =

# 测速下载量。名称含「勿跑大流量」的节点会自动降到 2MB。
speed_bytes = 10MB
speed_max_seconds = 60
skip_speed = false

# auto = 只对住宅候选做网页深检；off = 不做；all = 每个节点都做。
deep = auto
# all / none / openai,netflix,tiktok
services = all

# 可选官方风控 API（没有就留空，不影响主流程）。
ipqs_key =
abuseipdb_key =

[output]
# 留空 = 程序旁边的 node-audit-report 文件夹
dir =
# 审计结束后是否自动打开 latest.html
open_report = true
"""


@dataclass
class Settings:
    mode: str = "isolated"
    include: str | None = None
    exclude: str | None = None
    limit: int | None = None
    speed_bytes: str = "10MB"
    speed_max_seconds: int = 60
    skip_speed: bool = False
    deep: str = "auto"
    services: str = "all"
    ipqs_key: str | None = None
    abuseipdb_key: str | None = None
    out: str | None = None
    open_report: bool = True


def _blank(v: str | None) -> str | None:
    if v is None:
        return None
    v = v.strip()
    return v or None


def _as_bool(v: str | None, default: bool) -> bool:
    if v is None or not str(v).strip():
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def write_template_if_missing(path: Path) -> bool:
    """没有 ini 就写一份带注释的模板。返回是否新写。"""
    if path.is_file():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(INI_TEMPLATE, encoding="utf-8-sig")
    return True


def load_settings(path: Path | None) -> Settings:
    s = Settings()
    if not path or not path.is_file():
        return s
    cp = ConfigParser(interpolation=None)
    cp.read(path, encoding="utf-8-sig")
    a = cp["audit"] if cp.has_section("audit") else {}
    o = cp["output"] if cp.has_section("output") else {}

    mode = _blank(a.get("mode") if hasattr(a, "get") else None)
    if mode in ("isolated", "attach"):
        s.mode = mode
    s.include = _blank(a.get("include") if hasattr(a, "get") else None)
    s.exclude = _blank(a.get("exclude") if hasattr(a, "get") else None)
    lim = _blank(a.get("limit") if hasattr(a, "get") else None)
    if lim and lim.isdigit():
        s.limit = int(lim)
    speed = _blank(a.get("speed_bytes") if hasattr(a, "get") else None)
    if speed:
        s.speed_bytes = speed
    try:
        sms = _blank(a.get("speed_max_seconds") if hasattr(a, "get") else None)
        if sms:
            s.speed_max_seconds = int(sms)
    except ValueError:
        pass
    s.skip_speed = _as_bool(a.get("skip_speed") if hasattr(a, "get") else None, False)
    deep = _blank(a.get("deep") if hasattr(a, "get") else None)
    if deep in ("auto", "off", "all"):
        s.deep = deep
    services = _blank(a.get("services") if hasattr(a, "get") else None)
    if services:
        s.services = services
    s.ipqs_key = _blank(a.get("ipqs_key") if hasattr(a, "get") else None)
    s.abuseipdb_key = _blank(a.get("abuseipdb_key") if hasattr(a, "get") else None)
    s.out = _blank(o.get("dir") if hasattr(o, "get") else None)
    s.open_report = _as_bool(o.get("open_report") if hasattr(o, "get") else None, True)
    return s
