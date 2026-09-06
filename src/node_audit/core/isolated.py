"""isolated 模式：临时 mihomo 实例 + 每节点独立入站端口，零干扰。

实现思路：从 Verge Rev 运行时配置里把 `proxies:` 顶层块**原样文本搬运**
（不解析 YAML，零依赖、字节级保真），为每个节点生成一个绑定 127.0.0.1
的 mixed listener 并用 `proxy:` 字段钉住该节点，然后在本机拉起独立内核。
用户正在运行的代理全程不受影响，因此也无需快照/还原。
"""
from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from .runner import _audit_one


def find_core_binary(explicit: str | None = None) -> str | None:
    """定位 mihomo 内核：显式指定 > PATH > Clash Verge 安装目录。"""
    if explicit:
        return explicit if Path(explicit).is_file() else None
    for name in ("mihomo", "verge-mihomo"):
        p = shutil.which(name)
        if p:
            return p
    candidates: list[Path] = []
    if sys.platform == "win32":
        la = Path(os.environ.get("LOCALAPPDATA", ""))
        candidates += [
            la / "Programs" / "Clash Verge" / "verge-mihomo.exe",
            la / "Programs" / "clash-verge" / "verge-mihomo.exe",
            Path("C:/Program Files/Clash Verge/verge-mihomo.exe"),
            Path("C:/Program Files/Clash Verge Rev/verge-mihomo.exe"),
        ]
    elif sys.platform == "darwin":
        candidates += [
            Path("/Applications/Clash Verge.app/Contents/MacOS/verge-mihomo"),
            Path("/Applications/Clash Verge Rev.app/Contents/MacOS/verge-mihomo"),
        ]
    else:
        candidates += [
            Path("/usr/lib/clash-verge/verge-mihomo"),
            Path("/opt/clash-verge/verge-mihomo"),
        ]
    for c in candidates:
        if c.is_file():
            return str(c)
    return None


def extract_top_level_block(text: str, key: str) -> str | None:
    """从 YAML 文本中原样切出某个顶层键的整块（含键头行）。

    块在下一个顶层键行（零缩进的 `key:`）或文件尾结束。列表项（`- `开头，
    可为零缩进，见 Verge 实际生成的配置）不算新块；只匹配零缩进的键头，
    因此不会误伤嵌套结构。兼容 LF / CRLF 行尾。
    """
    m = re.search(
        rf"^{re.escape(key)}:[ \t]*(?:#[^\n\r]*)?\r?\n"
        rf"(.*?)(?=^[A-Za-z_][A-Za-z0-9_.-]*:(?:\r?\n|[ \t#])|\Z)",
        text, re.S | re.M,
    )
    return m.group(0) if m else None


def _alloc_ports(count: int, base: int) -> list[int]:
    ports: list[int] = []
    p = base
    while len(ports) < count:
        if p > base + 2000:
            raise RuntimeError(f"从 {base} 起连续 2000 个端口均不可用")
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", p))
                ports.append(p)
            except OSError:
                pass
        p += 1
    return ports


def build_config(proxies_block: str, names: list[str], ports: list[int],
                 ctrl_port: int, ctrl_secret: str) -> str:
    """拼装临时内核配置：最小骨架 + 原样 proxies 块 + 每节点 listener。

    listeners 只绑定 127.0.0.1（不向局域网开放），`proxy:` 字段把该端口的
    全部流量钉死到对应节点，因此 rules 不会影响检查路径。
    external-controller 同样只绑 127.0.0.1，随机 secret，专供本工具测延迟。
    """
    listeners = ["listeners:"]
    for i, (name, port) in enumerate(zip(names, ports)):
        listeners.append(f"  - name: audit-{i}")
        listeners.append("    type: mixed")
        listeners.append(f"    port: {port}")
        listeners.append("    listen: 127.0.0.1")
        # JSON 字符串转义与 YAML 双引号标量兼容，且能安全处理 |、emoji 等字符
        listeners.append(f"    proxy: {json.dumps(name, ensure_ascii=False)}")
    parts = [
        "mode: rule",
        "ipv6: false",
        "log-level: warning",
        f"external-controller: 127.0.0.1:{ctrl_port}",
        f"secret: {json.dumps(ctrl_secret)}",
        "unified-delay: true",
        "tcp-concurrent: true",
        "dns:",
        "  enable: true",
        "  ipv6: false",
        "  nameserver:",
        "    - https://doh.pub/dns-query",
        "    - https://dns.alidns.com/dns-query",
        "rules:",
        "  - MATCH,DIRECT",
        proxies_block.rstrip(),
        "\n".join(listeners),
    ]
    return "\n\n".join(parts) + "\n"


class IsolatedCore:
    """独立内核进程的生命周期管理（配置文件/日志/启停均放在临时目录）。"""

    def __init__(self, core_bin: str, config_text: str, ports: list[int],
                 ctrl_port: int, ctrl_secret: str, log=print):
        self.core_bin = core_bin
        self.config_text = config_text
        self.ports = ports
        self.ctrl_port = ctrl_port
        self.ctrl_secret = ctrl_secret
        self.log = log
        self.proc: subprocess.Popen | None = None
        self.api = None  # 内核控制器客户端，start 成功后可用
        self._tmpdir: str | None = None
        self._errfh = None

    def __enter__(self) -> "IsolatedCore":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.stop()
        return False

    def _probe(self) -> bool:
        if self.api is not None:
            try:
                self.api.version()
            except Exception:
                return False
        for port in self.ports:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                    pass
            except OSError:
                return False
        return True

    def start(self) -> None:
        # 不用 TemporaryDirectory：Windows 上内核进程释放文件句柄有延迟，
        # cleanup() 可能抛 PermissionError 并掩盖审计结果；改用 rmtree(ignore_errors)
        self._tmpdir = tempfile.mkdtemp(prefix="node-audit-")
        cfgpath = Path(self._tmpdir) / "audit-config.yaml"
        cfgpath.write_text(self.config_text, encoding="utf-8")
        errpath = Path(self._tmpdir) / "core-stderr.log"
        self._errfh = open(errpath, "wb")
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self.proc = subprocess.Popen(
            [self.core_bin, "-d", self._tmpdir, "-f", str(cfgpath)],
            stdout=subprocess.DEVNULL, stderr=self._errfh,
            creationflags=flags if sys.platform == "win32" else 0,
        )
        deadline = time.time() + 25
        # 先等控制器可用，再走 version+listeners 探活
        ctrl_deadline = time.time() + 25
        from ..clash.api import ClashAPI
        from ..clash.transport import TcpTransport
        while time.time() < ctrl_deadline:
            if self.proc.poll() is not None:
                tail = errpath.read_text(errors="replace")[-500:] if errpath.exists() else ""
                raise RuntimeError(f"内核进程退出(code={self.proc.returncode})：{tail}")
            try:
                self.api = ClashAPI(TcpTransport("127.0.0.1", self.ctrl_port, self.ctrl_secret))
                self.api.version()
                break
            except Exception:
                self.api = None
                time.sleep(0.3)
        if self.api is None:
            raise RuntimeError("独立内核控制器 25 秒内未就绪（查看临时目录 core-stderr.log）")
        while time.time() < deadline:
            if self.proc.poll() is not None:
                tail = errpath.read_text(errors="replace")[-500:] if errpath.exists() else ""
                raise RuntimeError(f"内核进程退出(code={self.proc.returncode})：{tail}")
            if self._probe():
                self.log(f"[isolated] 内核就绪（pid={self.proc.pid}），{len(self.ports)} 个独立端口待测")
                return
            time.sleep(0.3)
        raise RuntimeError("独立内核 listener 25 秒内未就绪（查看临时目录 core-stderr.log）")

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        if self._errfh:
            self._errfh.close()
            self._errfh = None
        if self._tmpdir:
            # 句柄释放可能滞后于进程退出，清理失败不抛错（留给系统临时目录自然回收）
            shutil.rmtree(self._tmpdir, ignore_errors=True)
            self._tmpdir = None


def run_isolated(targets: list, opts, core_bin: str, log=print) -> list:
    """isolated 模式入口：每个节点走自己的端口，管线与 attach 完全一致。"""
    from .runner import make_delay_fn

    block = extract_top_level_block(opts.runtime_cfg_text or "", "proxies")
    if not block or block.count("\n") < 2:
        raise RuntimeError(
            "运行时配置中没有内联 proxies 块（订阅可能走 proxy-providers），"
            "isolated 模式暂不支持，请改用 attach 模式"
        )
    names = [n for n, _ in targets]
    ports = _alloc_ports(len(names) + 1, opts.port_base)  # 第一个端口留给控制器
    ctrl_port, node_ports = ports[0], ports[1:]
    ctrl_secret = secrets.token_hex(8)
    cfg = build_config(block, names, node_ports, ctrl_port, ctrl_secret)

    log(f"[isolated] 内核: {core_bin} | 节点端口 {node_ports[0]}-{node_ports[-1]} | 独立实例，不影响当前代理")
    results: list[NodeReport] = []
    try:
        with IsolatedCore(core_bin, cfg, node_ports, ctrl_port, ctrl_secret, log) as core:
            opts.delay_fn = make_delay_fn(core.api)
            port_map = dict(zip(names, node_ports))
            total = len(targets)
            for idx, (name, ptype) in enumerate(targets, 1):
                log(f"[{idx}/{total}] {name}")
                results.append(
                    _audit_one(name, ptype, f"http://127.0.0.1:{port_map[name]}", opts, log)
                )
    except KeyboardInterrupt:
        log("[isolated] 已中断，内核实例已关闭")
        raise
    return results
