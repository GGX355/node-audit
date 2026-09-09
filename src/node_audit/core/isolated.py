"""isolated 模式：临时 mihomo 实例 + 每节点独立入站端口，零干扰。

实现思路：从 Verge / Verge Rev 运行时配置里把 `proxies:` 顶层块**原样文本搬运**
（拼配置时不解析 YAML，零依赖、字节级保真），为每个节点生成一个绑定 127.0.0.1
的 mixed listener 并用 `proxy:` 字段钉住该节点，然后在本机拉起独立内核。
用户正在运行的代理全程不受影响，因此也无需快照/还原。

节点列表可以只从 yaml 的 `proxies:` 解析，不必连接正在跑的控制器（无人值守）。
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
import threading
import time
from pathlib import Path

from .filters import is_real_node
from .runner import _audit_one, run_jobs_ordered


def core_binary_candidates() -> list[Path]:
    """内核搜索路径（显式指定与 PATH 之外），Rev / 非 Rev 都覆盖。"""
    candidates: list[Path] = []
    exe_win = ("verge-mihomo.exe", "clash-meta.exe", "mihomo.exe")
    exe_unix = ("verge-mihomo", "clash-meta", "mihomo")
    if sys.platform == "win32":
        la = Path(os.environ.get("LOCALAPPDATA", ""))
        pf = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        dirs = [
            la / "Programs" / "Clash Verge",
            la / "Programs" / "clash-verge",
            la / "Programs" / "Clash Verge Rev",
            la / "Programs" / "clash-verge-rev",
            pf / "Clash Verge",
            pf / "Clash Verge Rev",
        ]
        for d in dirs:
            for exe in exe_win:
                candidates.append(d / exe)
    elif sys.platform == "darwin":
        for app in ("Clash Verge.app", "Clash Verge Rev.app"):
            mac = Path("/Applications") / app / "Contents" / "MacOS"
            for exe in exe_unix:
                candidates.append(mac / exe)
    else:
        for d in (Path("/usr/lib/clash-verge"), Path("/opt/clash-verge"),
                  Path("/usr/lib/clash-verge-rev"), Path("/opt/clash-verge-rev")):
            for exe in exe_unix:
                candidates.append(d / exe)
    return candidates


def core_names() -> tuple[str, ...]:
    if sys.platform == "win32":
        return ("verge-mihomo.exe", "mihomo.exe", "clash-meta.exe")
    return ("verge-mihomo", "mihomo", "clash-meta")


def core_in_dir(directory: Path) -> Path | None:
    """目录里有 mihomo / verge-mihomo / clash-meta 则返回该文件。"""
    d = Path(directory)
    for name in core_names():
        p = d / name
        if p.is_file():
            return p
    return None


def find_core_binary(explicit: str | None = None) -> str | None:
    """定位 mihomo 内核：显式路径 > exe 旁边 > PATH > Clash Verge 安装目录。"""
    if explicit:
        p = Path(explicit)
        return str(p) if p.is_file() else None
    from ..paths import app_dir
    local = core_in_dir(app_dir())
    if local:
        return str(local)
    for name in ("mihomo", "verge-mihomo", "clash-meta"):
        p = shutil.which(name)
        if p:
            return p
    for c in core_binary_candidates():
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


def _scalar(v: str) -> str:
    """YAML 标量：去掉行内注释与一层引号。"""
    v = re.split(r"\s+#", v, maxsplit=1)[0].strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
        v = v[1:-1]
    return v


def _parse_flow_item(s: str) -> tuple[str, str] | None:
    """`{ name: foo, type: ss, ... }` 单行 flow。"""
    inner = s.strip()
    if inner.startswith("{"):
        inner = inner[1:]
    if "}" in inner:
        inner = inner[: inner.index("}")]
    nm = re.search(r"\bname:\s*([^,}]+)", inner)
    tp = re.search(r"\btype:\s*([^,}]+)", inner)
    if not nm:
        return None
    return _scalar(nm.group(1)), _scalar(tp.group(1)) if tp else ""


def parse_proxy_entries(proxies_block: str) -> list[tuple[str, str]]:
    """从 `proxies:` 块抽出 [(name, type), ...]。只读顶层键，不解析嵌套。

    支持 Verge 常见的块列表（含零缩进 `- `）和简单 `{ name, type }` flow。
    """
    items = re.split(r"(?m)^[ \t]*-[ \t]+", proxies_block)
    out: list[tuple[str, str]] = []
    for item in items[1:]:
        stripped = item.lstrip()
        if stripped.startswith("{"):
            parsed = _parse_flow_item(stripped.split("\n", 1)[0])
            if parsed and parsed[0]:
                out.append(parsed)
            continue
        name = ptype = None
        first_key_line = True
        sibling_indent = None
        for raw in item.splitlines():
            line = raw.rstrip()
            if not line.strip() or line.strip().startswith("#"):
                continue
            indent = len(line) - len(line.lstrip(" \t"))
            if first_key_line:
                # `- name: foo` 被切开后，name 在余下行列 0；后续兄弟键缩进更深
                first_key_line = False
            else:
                if sibling_indent is None:
                    sibling_indent = indent
                if indent != sibling_indent:
                    continue
            m = re.match(r"([A-Za-z0-9_-]+)[ \t]*:[ \t]*(.*)$", line.strip())
            if not m:
                continue
            key, val = m.group(1), m.group(2)
            if key == "name" and name is None:
                name = _scalar(val)
            elif key == "type" and ptype is None:
                ptype = _scalar(val)
        if name:
            out.append((name, ptype or ""))
    return out


def list_nodes_from_runtime(text: str) -> list[tuple[str, str]]:
    """从运行时配置文本列出真实节点，不连控制器。无内联 proxies 则返回空。"""
    block = extract_top_level_block(text, "proxies")
    if not block:
        return []
    return [(n, t) for n, t in parse_proxy_entries(block) if is_real_node(n, t)]


def _alloc_ports(count: int, base: int) -> tuple[list[int], list[socket.socket]]:
    """分配端口并保持 bind，直到内核启动前一刻才释放，缩小 TOCTOU 窗口。"""
    ports: list[int] = []
    holders: list[socket.socket] = []
    p = base
    while len(ports) < count:
        if p > base + 2000:
            for s in holders:
                s.close()
            raise RuntimeError(f"从 {base} 起连续 2000 个端口均不可用")
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("127.0.0.1", p))
        except OSError:
            s.close()
            p += 1
            continue
        ports.append(p)
        holders.append(s)
        p += 1
    return ports, holders


def _close_holders(holders: list[socket.socket]) -> None:
    for s in holders:
        try:
            s.close()
        except OSError:
            pass
    holders.clear()


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
        "ipv6: true",
        "log-level: warning",
        f"external-controller: 127.0.0.1:{ctrl_port}",
        f"secret: {json.dumps(ctrl_secret)}",
        "unified-delay: true",
        "tcp-concurrent: true",
        "dns:",
        "  enable: true",
        "  ipv6: true",
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
                 ctrl_port: int, ctrl_secret: str, log=print,
                 holders: list | None = None):
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
        self._holders: list = list(holders or [])

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
        # 占住端口直到内核即将启动，释放后立刻 Popen，缩小被抢窗口
        _close_holders(self._holders)
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
        _close_holders(self._holders)
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
    holders: list = []
    results: list[NodeReport] = []
    try:
        ports, holders = _alloc_ports(len(names) + 1, opts.port_base)  # 第一个端口留给控制器
        ctrl_port, node_ports = ports[0], ports[1:]
        ctrl_secret = secrets.token_hex(8)
        cfg = build_config(block, names, node_ports, ctrl_port, ctrl_secret)

        workers = max(1, min(8, int(getattr(opts, "workers", 3) or 1)))
        log(f"[isolated] 内核: {core_bin} | 节点端口 {node_ports[0]}-{node_ports[-1]} | 独立实例，不影响当前代理")
        if workers > 1:
            log(f"[isolated] 并行 {workers} 路（ip-api 仍排队，避免免费额度被打爆）")
        with IsolatedCore(core_bin, cfg, node_ports, ctrl_port, ctrl_secret, log,
                          holders=holders) as core:
            raw_delay = make_delay_fn(core.api)
            delay_lock = threading.Lock()

            def delay_fn(name: str) -> dict:
                with delay_lock:
                    return raw_delay(name)

            opts.delay_fn = delay_fn
            port_map = dict(zip(names, node_ports))
            total = len(targets)
            log_lock = threading.Lock()
            done = [0]

            def _job(name, ptype, url):
                def fn():
                    buf: list[str] = []

                    def clog(m=""):
                        buf.append("" if m is None else str(m))

                    rep = _audit_one(name, ptype, url, opts, log=clog)
                    with log_lock:
                        done[0] += 1
                        log(f"[{done[0]}/{total}] {name}")
                        for line in buf:
                            log(line)
                    return rep
                return name, fn

            jobs = [_job(n, t, f"http://127.0.0.1:{port_map[n]}") for n, t in targets]
            results = run_jobs_ordered(jobs, workers, log)
    except KeyboardInterrupt:
        log(f"[isolated] 已中断：返回已完成 {len(results)}/{len(targets)} 个节点的部分报告")
        return results
    finally:
        _close_holders(holders)
    return results
