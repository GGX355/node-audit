"""程序目录：打包成 exe 后以 exe 所在文件夹为准，源码运行则以当前工作目录为准。"""
from __future__ import annotations

import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_dir() -> Path:
    """设置文件、报告的默认落点。双击 exe 时就是 exe 旁边。"""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path.cwd()


def default_out_dir() -> Path:
    return app_dir() / "node-audit-report"


def default_ini_path() -> Path:
    return app_dir() / "node-audit.ini"
