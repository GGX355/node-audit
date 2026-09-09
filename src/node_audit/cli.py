"""node-audit 命令行入口。

用法示例：
  python -m node_audit discover
  python -m node_audit audit --dry-run
  python -m node_audit audit --mode isolated --include "台湾|香港原生" --yes
  python -m node_audit audit --yes --speed-bytes 15MB --deep auto
  python -m node_audit serve --open
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import webbrowser
from collections import Counter
from datetime import datetime
from pathlib import Path

from . import __version__
from .clash.api import ClashAPI
from .clash.discover import discover
from .clash.transport import PipeTransport, TcpTransport
from .core.filters import heavy_traffic, is_real_node, rate_multiplier, region_from_name
from .core.isolated import find_core_binary, list_nodes_from_runtime, run_isolated
from .core.runner import run_attach
from .core.services import PROBES, SERVICE_SHORT, STATUS_MARK
from .report.output import write_json, write_markdown
from .report.table import render


def _parse_size(s: str) -> int:
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(KB|MB|GB)?", s, re.I)
    if not m:
        raise argparse.ArgumentTypeError(f"无法解析大小: {s}")
    factor = {"KB": 1e3, "MB": 1e6, "GB": 1e9}.get((m.group(2) or "").upper(), 1)
    return int(float(m.group(1)) * factor)


def _parse_services(s: str):
    """"all" / "none" / 逗号分隔的服务名。"""
    s = (s or "").strip().lower()
    if s in ("none", "off"):
        return []
    if s in ("all", ""):
        return sorted(PROBES)
    names = [x.strip() for x in s.split(",") if x.strip()]
    bad = [x for x in names if x not in PROBES]
    if bad:
        raise argparse.ArgumentTypeError(
            f"未知服务: {','.join(bad)}（可用: {','.join(sorted(PROBES))}、all、none）")
    return names


class Opts:
    """runner 所需的运行参数（与 argparse 解耦）。"""

    def __init__(self, args, mixed_port: int):
        self.proxy_url = f"http://127.0.0.1:{mixed_port}"
        self.speed_bytes = args.speed_bytes
        self.heavy_speed_bytes = min(args.speed_bytes, 2_000_000)
        self.speed_max_seconds = args.speed_max_seconds
        self.skip_speed = args.skip_speed
        self.deep = args.deep
        self.services = args.services
        self.ipqs_key = args.ipqs_key
        self.abuseipdb_key = args.abuseipdb_key
        self.port_base = args.port_base
        self.workers = max(1, min(8, int(getattr(args, "workers", 3) or 1)))
        self.runtime_cfg_text: str | None = None
        self.delay_fn = None  # 延迟测量函数（attach/isolated 各自注入）


def build_transport(disc, args):
    secret = args.secret if args.secret is not None else disc.secret
    if args.pipe:
        return PipeTransport(args.pipe, secret)
    if args.api:
        api = re.sub(r"^https?://", "", args.api)
        host, _, port = api.rpartition(":")
        return TcpTransport(host or "127.0.0.1", int(port), secret)
    if disc.transport == "pipe":
        return PipeTransport(disc.pipe_name, secret)
    return TcpTransport(disc.host, disc.port, secret)


class Tee:
    """同时写控制台和日志文件。"""

    def __init__(self, *streams):
        self.streams = streams

    def write(self, data):
        for s in self.streams:
            try:
                s.write(data)
                s.flush()
            except Exception:  # noqa: BLE001
                pass

    def flush(self):
        for s in self.streams:
            try:
                s.flush()
            except Exception:  # noqa: BLE001
                pass

    def isatty(self):
        return any(getattr(s, "isatty", lambda: False)() for s in self.streams)

    @property
    def encoding(self):
        for s in self.streams:
            enc = getattr(s, "encoding", None)
            if enc:
                return enc
        return "utf-8"

    def reconfigure(self, **kwargs):
        for s in self.streams:
            fn = getattr(s, "reconfigure", None)
            if fn:
                try:
                    fn(**kwargs)
                except Exception:  # noqa: BLE001
                    pass


def normalize_argv(argv: list[str] | None) -> list[str]:
    """无参数（双击 exe / 直接 python -m node_audit）→ run。"""
    if argv is None:
        argv = sys.argv[1:]
    argv = list(argv)
    if not argv:
        return ["run"]
    return argv


def _interactive() -> bool:
    try:
        return bool(sys.stdin) and sys.stdin.isatty()
    except Exception:  # noqa: BLE001
        return False


def _pause_if_window() -> None:
    """双击 exe 时窗口会一闪而过，停一下让人看完。"""
    from .paths import is_frozen
    if not is_frozen() or not _interactive():
        return
    try:
        input("\n按 Enter 关闭窗口...")
    except EOFError:
        pass


def _open_html(path: Path) -> bool:
    if not path.is_file():
        return False
    webbrowser.open(path.resolve().as_uri())
    return True


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--api", help="强制使用 TCP 控制器，如 127.0.0.1:9090")
    p.add_argument("--pipe", help="强制使用命名管道，如 verge-mihomo")
    p.add_argument("--secret", help="控制器密钥（默认从 Verge 配置自动读取）")
    p.add_argument("--mixed-port", type=int, default=None,
                   help="mihomo 混合代理端口（默认自动发现，通常 7897）")


def cmd_serve(args) -> int:
    from .serve import run_server
    return run_server(args.out, port=args.port, open_browser=args.open,
                      db_path=args.db, runs_limit=args.trend_runs)


def cmd_discover(args) -> int:
    disc = discover()
    if args.mixed_port:
        disc.mixed_port = args.mixed_port
    print("控制器:", disc.describe())
    api = ClashAPI(build_transport(disc, args))
    print("内核:", api.version())
    proxies = api.proxies()
    real = [(n, p.get("type", "")) for n, p in proxies.items() if is_real_node(n, p.get("type", ""))]
    print(f"真实节点: {len(real)} 个 / 全部条目: {len(proxies)} 条")
    print("代理组:")
    for n, p in proxies.items():
        if p.get("type") in ("Selector", "URLTest", "Fallback", "LoadBalance"):
            print(f"  {n} [{p.get('type')}] -> {p.get('now')}")
    return 0


def _filter_targets(all_nodes, args):
    inc = re.compile(args.include) if args.include else None
    exc = re.compile(args.exclude) if args.exclude else None
    targets = []
    for n, t in all_nodes:
        if inc and not inc.search(n):
            continue
        if exc and exc.search(n):
            continue
        targets.append((n, t))
    if args.limit:
        targets = targets[: args.limit]
    return targets


def _nodes_via_api(disc, args):
    api = ClashAPI(build_transport(disc, args))
    cfg = api.configs()
    proxies = api.proxies()
    all_nodes = [(n, p.get("type", "")) for n, p in proxies.items()
                 if is_real_node(n, p.get("type", ""))]
    return api, cfg.get("mode"), all_nodes


def cmd_audit(args) -> int:
    disc = discover()
    if args.mixed_port:
        disc.mixed_port = args.mixed_port

    runtime_text = None
    if disc.config_path:
        runtime_text = Path(disc.config_path).read_text(encoding="utf-8", errors="replace")

    api = None
    cfg_mode = None
    source_note = ""
    all_nodes: list = []

    # isolated：优先从 yaml 列节点，不强制连接正在跑的控制器（无人值守）
    if args.mode == "isolated" and runtime_text:
        yaml_nodes = list_nodes_from_runtime(runtime_text)
        if yaml_nodes:
            all_nodes = yaml_nodes
            source_note = "节点列表来自运行时配置（未连接控制器）"
            cfg_mode = "n/a"
        else:
            source_note = "运行时配置无内联 proxies，回退到控制器"

    if not all_nodes:
        try:
            api, cfg_mode, all_nodes = _nodes_via_api(disc, args)
        except Exception as e:  # noqa: BLE001
            if args.mode == "isolated":
                print(f"错误: 无法列出节点（yaml 无 proxies 且控制器不可用）: "
                      f"{type(e).__name__}: {e}", file=sys.stderr)
                return 1
            raise

    targets = _filter_targets(all_nodes, args)
    if not targets:
        print("没有匹配的节点（检查 --include/--exclude 是否过滤过严）。")
        return 1

    print(f"控制器: {disc.describe()}")
    if source_note:
        print(f"         {source_note}")
    print(f"待测节点: {len(targets)} / {len(all_nodes)}（当前 mode={cfg_mode}）")

    if args.dry_run:
        for n, t in targets:
            code, cn = region_from_name(n)
            tags = [f"[{t}]", f"预期={cn or '?'}"]
            if rate_multiplier(n):
                tags.append(f"倍率={rate_multiplier(n):g}")
            if heavy_traffic(n):
                tags.append("⚠勿跑大流量")
            print("  - " + "  ".join([n, *tags]))
        print("(dry-run：未做任何切换)")
        return 0

    if args.mode == "isolated":
        core = find_core_binary(args.core)
        if not core:
            print("错误: 未找到 mihomo 内核（可用 --core 指定路径）", file=sys.stderr)
            return 1
        if not disc.config_path or not runtime_text:
            print("错误: isolated 模式需要读取 Verge 运行时配置，未找到；可改用 attach 模式", file=sys.stderr)
            return 1
        opts = Opts(args, disc.mixed_port)
        opts.runtime_cfg_text = runtime_text
        print("[isolated] 将在本机拉起独立内核实例，你正在使用的代理不受影响。")
        reports = run_isolated(targets, opts, core, log=print)
    else:
        est_min = max(1, len(targets) * 25 // 60)
        print(f"⚠  即将进入 global 模式逐节点切换，期间你的全部流量会经由被测节点（预计 ~{est_min} 分钟）。")
        if not args.yes:
            try:
                ans = input("继续? [y/N] ").strip().lower()
            except EOFError:
                print("\n非交互环境无法确认：已取消（自动化场景请加 --yes）。")
                return 1
            if ans not in ("y", "yes"):
                print("已取消。")
                return 1
        opts = Opts(args, disc.mixed_port)
        reports = run_attach(api, targets, opts, log=print)

    _emit(reports, disc, args)
    return 0


def _emit(reports, disc, args) -> None:
    now = datetime.now().strftime("%Y%m%d-%H%M%S")
    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    jpath = outdir / f"audit-{now}.json"
    mpath = outdir / f"audit-{now}.md"
    hpath = outdir / f"audit-{now}.html"
    meta = {"controller": disc.describe(), "mode": args.mode,
            "run_id": now,
            "generated_at": datetime.now().isoformat(timespec="seconds")}
    cfg_name = getattr(args, "config_name", None)
    if cfg_name:
        meta["config_name"] = str(cfg_name).strip()
    write_json(reports, jpath, meta)
    write_markdown(reports, mpath, meta)

    hpath_str = "-"
    if not args.no_history:
        from .core.history import load_dashboard, load_trend, save_run
        db_path = Path(args.db) if args.db else outdir / "history.db"
        sub = save_run(reports, meta, db_path)
        name = sub.get("name") or "配置"
        if sub.get("same"):
            print(f"配置: {name}（同一套，节点重叠 {sub['match']:.0%}，"
                  f"{sub['overlap']}/{sub['prev_count']}）")
        elif sub.get("prev_count"):
            print(f"配置: 新建 {name}（与已知最高重叠 {sub['match']:.0%}，已分开存）")
        else:
            print(f"配置: 首次记录 → {name}")
        trend = load_trend(db_path, runs_limit=args.trend_runs)
        from .report.html import write_html
        from .report.dashboard import write_dashboard
        write_html(reports, meta, hpath, trend)
        latest = write_dashboard(load_dashboard(db_path, args.trend_runs), outdir / "latest.html")
        hpath_str = f"{hpath}\n      {latest}"

    geo_mark = {"match": "✓", "mismatch": "✗", "unknown": "?"}

    def _services_short(rep) -> str:
        if not rep.services:
            return "-"
        parts = []
        for name, res in rep.services.items():
            mark = STATUS_MARK.get(res.get("status"), "?")
            parts.append(f"{SERVICE_SHORT.get(name, name[:3].upper())}{mark}")
        return " ".join(parts)

    rows = []
    for r in reports:
        rows.append([
            r.name, r.region_cn or "-",
            r.exit_label(),
            f"{r.country_code or '-'} {r.city or ''}".strip(),
            (r.isp or "-")[:24],
            "机房" if r.hosting is True else ("住宅" if r.hosting is False else "-"),
            r.rtt_min if r.rtt_min is not None else "-",
            r.speed_mbps if r.speed_mbps is not None else "-",
            geo_mark.get(r.geo_match, "?"),
            _services_short(r),
            r.verdict,
        ])
    print()
    print(render(rows, ["节点", "预期", "出口IP", "归属", "ISP", "类型", "RTT", "Mbps", "一致", "服务", "判定"]))
    print()
    print("判定分布:", dict(Counter(r.verdict for r in reports)))
    print(f"报告: {jpath}")
    print(f"      {mpath}")
    if hpath_str != "-":
        print(f"      {hpath_str}")
        print(f"历史: {Path(args.db) if args.db else outdir / 'history.db'}")


def _audit_ns_from_settings(settings) -> argparse.Namespace:
    from .paths import default_out_dir
    return argparse.Namespace(
        api=None, pipe=None, secret=None, mixed_port=None,
        mode=settings.mode,
        include=settings.include,
        exclude=settings.exclude,
        limit=settings.limit,
        speed_bytes=_parse_size(settings.speed_bytes),
        speed_max_seconds=settings.speed_max_seconds,
        skip_speed=settings.skip_speed,
        deep=settings.deep,
        services=_parse_services(settings.services),
        ipqs_key=settings.ipqs_key or os.environ.get("NODE_AUDIT_IPQS_KEY"),
        abuseipdb_key=settings.abuseipdb_key or os.environ.get("NODE_AUDIT_ABUSEIPDB_KEY"),
        port_base=41000,
        workers=getattr(settings, "workers", 3),
        core=None,
        out=settings.out or str(default_out_dir()),
        db=None,
        trend_runs=30,
        no_history=False,
        dry_run=False,
        yes=True,
        config_name=getattr(settings, "config_name", None),
    )


def _print_banner(ini: Path, outdir: Path, log_path: Path, created_ini: bool) -> None:
    from .paths import app_dir
    from .core.isolated import find_core_binary
    from .clash.discover import discover as _discover

    print(f"======== node-audit {__version__} ========")
    print("一键审计 · isolated 零干扰（不切换你正在用的代理）")
    print(f"程序目录: {app_dir()}")
    print(f"设置文件: {ini}" + ("  （已新写，下次可改）" if created_ini else ""))
    print(f"报告目录: {outdir}")
    print(f"本次日志: {log_path}")
    disc = _discover()
    core = find_core_binary()
    print(f"Clash:    {disc.describe()}")
    print(f"内核:     {core or '未找到 verge-mihomo / mihomo'}")
    print()


def _menu(has_report: bool) -> str:
    print("请选择：")
    print("  1) 开始全量审计（推荐，约十几～二十分钟）")
    print("  2) 打开上次报告" + ("" if has_report else "  ← 还没有，需要先跑过 1"))
    print("  3) 只列出将测的节点，不真正测")
    print("  4) 打开使用说明")
    print("  Q) 退出")
    try:
        raw = input("选择 [1]: ").strip().lower()
    except EOFError:
        return "q"
    if raw in ("", "1"):
        return "1"
    if raw in ("2", "3", "4", "h", "help", "q"):
        return "4" if raw in ("h", "help") else raw
    print(f"不认识「{raw}」，请重新选择。")
    return "retry"


def _run_audit_once(ns, settings, log_path: Path, latest_html: Path) -> int:
    if ns.dry_run:
        print("模式: 只列表（dry-run）")
    else:
        print("开始全量审计。窗口请开着，中途可 Ctrl+C 保留已测部分。")
    print()
    rc = cmd_audit(ns)
    if rc == 0 and not ns.dry_run and settings.open_report:
        if _open_html(latest_html):
            print(f"已打开报告 {latest_html}")
        else:
            print(f"审计结束。请打开 {latest_html}")
    print(f"完整日志: {log_path}")
    return rc


def cmd_help(_args=None) -> int:
    """写出并打开使用说明.html（exe 旁边，或当前目录）。"""
    from .guide import write_guide
    from .paths import app_dir, is_frozen
    dest = app_dir() / "使用说明.html"
    write_guide(dest)
    print(f"使用说明: {dest}")
    if is_frozen() or _interactive():
        if _open_html(dest):
            print("已在浏览器打开。控制台里也可点右上角「说明」，或按 ?")
    return 0


def cmd_run(args) -> int:
    """双击 / 无参数入口：菜单 + 读 ini + 打日志 + 跑完打开报告。"""
    from .guide import write_guide
    from .paths import app_dir, default_ini_path, default_out_dir, is_frozen
    from .settings import load_settings, write_template_if_missing

    ini = Path(args.ini) if getattr(args, "ini", None) else default_ini_path()
    created = write_template_if_missing(ini)
    settings = load_settings(ini)
    if getattr(args, "no_open", False):
        settings.open_report = False

    ns = _audit_ns_from_settings(settings)
    outdir = Path(ns.out)
    outdir.mkdir(parents=True, exist_ok=True)
    write_guide(outdir / "使用说明.html")
    if is_frozen():
        write_guide(app_dir() / "使用说明.html")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_path = outdir / f"audit-{stamp}.log"
    latest_log = outdir / "latest.log"
    latest_html = outdir / "latest.html"

    skip_menu = bool(getattr(args, "yes", False)) or not _interactive()
    orig_out, orig_err = sys.stdout, sys.stderr
    logf = log_path.open("w", encoding="utf-8")
    sys.stdout = Tee(orig_out, logf)
    sys.stderr = Tee(orig_err, logf)
    rc = 1
    try:
        _print_banner(ini, outdir, log_path, created)
        if skip_menu:
            print("非交互 / --yes：直接开始全量审计。")
            print()
            return _run_audit_once(ns, settings, log_path, latest_html)

        rc = 0
        while True:
            choice = _menu(latest_html.is_file())
            if choice == "retry":
                continue
            if choice == "q":
                print("已退出。")
                return rc
            if choice == "2":
                if _open_html(latest_html):
                    print(f"已打开 {latest_html}")
                    print("报告在浏览器里。本窗口还在，可继续选 1 开始审计。")
                else:
                    print("还没有 latest.html。请先选 1 跑一次审计。")
                continue
            if choice == "4":
                cmd_help(args)
                print("本窗口还在，可继续选择。")
                continue
            ns.dry_run = choice == "3"
            print(f"日志同时写入 {log_path}")
            rc = _run_audit_once(ns, settings, log_path, latest_html)
            ns.dry_run = False
            print("可继续选择：1 再测 / 2 看报告 / 4 说明 / Q 退出。")
    finally:
        sys.stdout = orig_out
        sys.stderr = orig_err
        try:
            logf.flush()
            logf.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            latest_log.write_bytes(log_path.read_bytes())
        except Exception:  # noqa: BLE001
            pass


def main(argv=None) -> int:
    if sys.platform == "win32":
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                pass

    argv = normalize_argv(argv)
    one_click = argv == ["run"] or (argv[:1] == ["run"] and not any(
        a in ("-h", "--help") for a in argv
    ))

    parser = argparse.ArgumentParser(
        prog="node-audit", description="Clash/mihomo 节点质量审计：IP 身份·纯净度·延迟·测速。"
        "无参数 = 一键 run（双击 exe 也会进这里）。"
    )
    parser.add_argument("--version", action="version", version=f"node-audit {__version__}")
    sub = parser.add_subparsers(dest="command")

    p_disc = sub.add_parser("discover", help="探测控制器并列出节点（只读，不做任何切换）")
    _add_common(p_disc)
    p_disc.set_defaults(func=cmd_discover)

    p_aud = sub.add_parser("audit", help="对节点批量执行质量审计")
    _add_common(p_aud)
    p_aud.add_argument("--mode", choices=["attach", "isolated"], default="isolated",
                       help="isolated=独立内核零干扰（默认，推荐）；attach=接管运行中实例"
                            "逐节点切换（期间你的全部流量会随节点跳转，涉及登录态账号时慎用）")
    p_aud.add_argument("--include", help="只测名称匹配此正则的节点")
    p_aud.add_argument("--exclude", help="排除名称匹配此正则的节点")
    p_aud.add_argument("--limit", type=int, default=None, help="最多测前 N 个节点")
    p_aud.add_argument("--speed-bytes", type=_parse_size, default="10MB",
                       help="测速下载量（如 10MB / 2MB，默认 10MB；“勿跑大流量”节点自动降为 2MB）")
    p_aud.add_argument("--speed-max-seconds", type=int, default=60,
                       help="单节点测速时限秒数，到时按已收字节计算部分速度（默认 60）")
    p_aud.add_argument("--skip-speed", action="store_true", help="跳过测速")
    p_aud.add_argument("--deep", choices=["auto", "off", "all"], default="auto",
                       help="深检：auto=仅住宅候选节点 / off / all（默认 auto）")
    p_aud.add_argument("--services", type=_parse_services, default=_parse_services("all"),
                       metavar="LIST",
                       help="服务风控探针：all / none / 逗号分隔（openai,netflix,tiktok；默认 all）")
    p_aud.add_argument("--ipqs-key", default=os.environ.get("NODE_AUDIT_IPQS_KEY"),
                       help="IPQualityScore API key（或环境变量 NODE_AUDIT_IPQS_KEY）")
    p_aud.add_argument("--abuseipdb-key", default=os.environ.get("NODE_AUDIT_ABUSEIPDB_KEY"),
                       help="AbuseIPDB API key（或环境变量 NODE_AUDIT_ABUSEIPDB_KEY）")
    p_aud.add_argument("--workers", type=int, default=3,
                       help="isolated 同时测几个节点（默认 3，最大 8；attach 忽略）")
    p_aud.add_argument("--port-base", type=int, default=41000,
                       help="isolated 模式的独立端口起始值（默认 41000）")
    p_aud.add_argument("--core", default=None, help="isolated 模式的 mihomo 内核路径（默认自动查找）")
    p_aud.add_argument("--out", default="node-audit-report", help="报告输出目录（默认 ./node-audit-report）")
    p_aud.add_argument("--db", default=None,
                       help="历史趋势 SQLite 路径（默认 <out>/history.db）")
    p_aud.add_argument("--trend-runs", type=int, default=30,
                       help="HTML 趋势表保留最近 N 次审计（默认 30，约一个月每日）")
    p_aud.add_argument("--no-history", action="store_true",
                       help="不写入历史库、不生成 HTML 趋势报告")
    p_aud.add_argument("--dry-run", action="store_true", help="只列出将测的节点，不切换不检测")
    p_aud.add_argument("--config-name", default=None,
                       help="给这次匹配到的配置起名（如 家里 / 公司）；默认自动叫 配置1、配置2")
    p_aud.add_argument("--yes", "-y", action="store_true", help="跳过切换前的确认提示")
    p_aud.set_defaults(func=cmd_audit)

    p_run = sub.add_parser("run", help="一键审计：读 node-audit.ini，写日志，跑完打开报告（双击 exe 默认进这里）")
    p_run.add_argument("--ini", default=None, help="设置文件路径（默认程序目录/当前目录的 node-audit.ini）")
    p_run.add_argument("--no-open", action="store_true", help="结束后不要自动打开 latest.html")
    p_run.add_argument("--yes", "-y", action="store_true",
                       help="跳过菜单，直接全量审计（计划任务用）")
    p_run.set_defaults(func=cmd_run)

    p_help = sub.add_parser("help", help="打开使用说明（浏览器）")
    p_help.set_defaults(func=cmd_help)

    p_srv = sub.add_parser("serve", help="在本机打开控制台页面（只监听 127.0.0.1）")
    p_srv.add_argument("--out", default="node-audit-report", help="报告目录（默认 ./node-audit-report）")
    p_srv.add_argument("--db", default=None, help="history.db 路径（默认 <out>/history.db）")
    p_srv.add_argument("--port", type=int, default=8765, help="端口（默认 8765）")
    p_srv.add_argument("--trend-runs", type=int, default=30, help="趋势窗口（默认 30）")
    p_srv.add_argument("--open", action="store_true", help="启动后用系统浏览器打开")
    p_srv.set_defaults(func=cmd_serve)

    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        args = parser.parse_args(["run"])
        one_click = True
    try:
        rc = args.func(args)
        return rc
    except KeyboardInterrupt:
        print("\n已中断。已测完的部分报告仍会保留。")
        return 130
    except Exception as e:  # noqa: BLE001
        print(f"错误: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    finally:
        if one_click:
            _pause_if_window()
