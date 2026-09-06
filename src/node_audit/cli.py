"""node-audit 命令行入口。

用法示例：
  python -m node_audit discover
  python -m node_audit audit --dry-run
  python -m node_audit audit --mode isolated --include "台湾|香港原生" --yes
  python -m node_audit audit --yes --speed-bytes 15MB --deep auto
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

from .clash.api import ClashAPI
from .clash.discover import discover
from .clash.transport import PipeTransport, TcpTransport
from .core.filters import heavy_traffic, is_real_node, rate_multiplier, region_from_name
from .core.isolated import find_core_binary, run_isolated
from .core.runner import run_attach
from .core.services import PROBES, SERVICE_SHORT, STATUS_MARK, STATUS_CN
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


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--api", help="强制使用 TCP 控制器，如 127.0.0.1:9090")
    p.add_argument("--pipe", help="强制使用命名管道，如 verge-mihomo")
    p.add_argument("--secret", help="控制器密钥（默认从 Verge 配置自动读取）")
    p.add_argument("--mixed-port", type=int, default=None,
                   help="mihomo 混合代理端口（默认自动发现，通常 7897）")


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


def cmd_audit(args) -> int:
    disc = discover()
    if args.mixed_port:
        disc.mixed_port = args.mixed_port
    api = ClashAPI(build_transport(disc, args))
    cfg = api.configs()
    proxies = api.proxies()
    all_nodes = [(n, p.get("type", "")) for n, p in proxies.items() if is_real_node(n, p.get("type", ""))]

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
    if not targets:
        print("没有匹配的节点（检查 --include/--exclude 是否过滤过严）。")
        return 1

    print(f"控制器: {disc.describe()}")
    print(f"待测节点: {len(targets)} / {len(all_nodes)}（当前 mode={cfg.get('mode')}）")

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
        if not disc.config_path:
            print("错误: isolated 模式需要读取 Verge 运行时配置，未找到；可改用 attach 模式", file=sys.stderr)
            return 1
        opts = Opts(args, disc.mixed_port)
        opts.runtime_cfg_text = Path(disc.config_path).read_text(encoding="utf-8", errors="replace")
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
    write_json(reports, jpath, meta)
    write_markdown(reports, mpath, meta)

    hpath_str = "-"
    if not args.no_history:
        from .core.history import load_trend, save_run
        db_path = Path(args.db) if args.db else outdir / "history.db"
        save_run(reports, meta, db_path)
        trend = load_trend(db_path)
        from .report.html import write_html
        write_html(reports, meta, hpath, trend)
        hpath_str = str(hpath)

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
            r.exit_ip or "-",
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


def main(argv=None) -> int:
    if sys.platform == "win32":
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                pass

    parser = argparse.ArgumentParser(
        prog="node-audit", description="Clash/mihomo 节点质量审计：IP 身份·纯净度·延迟·测速"
    )
    parser.add_argument("--version", action="version", version="node-audit 0.4.0")
    sub = parser.add_subparsers(dest="command", required=True)

    p_disc = sub.add_parser("discover", help="探测控制器并列出节点（只读，不做任何切换）")
    _add_common(p_disc)
    p_disc.set_defaults(func=cmd_discover)

    p_aud = sub.add_parser("audit", help="对节点批量执行质量审计")
    _add_common(p_aud)
    p_aud.add_argument("--mode", choices=["attach", "isolated"], default="attach",
                       help="attach=接管运行中实例逐节点切换（默认）；isolated=拉起独立内核+每节点独立端口，零干扰")
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
    p_aud.add_argument("--port-base", type=int, default=41000,
                       help="isolated 模式的独立端口起始值（默认 41000）")
    p_aud.add_argument("--core", default=None, help="isolated 模式的 mihomo 内核路径（默认自动查找）")
    p_aud.add_argument("--out", default="node-audit-report", help="报告输出目录（默认 ./node-audit-report）")
    p_aud.add_argument("--db", default=None,
                       help="历史趋势 SQLite 路径（默认 <out>/history.db）")
    p_aud.add_argument("--no-history", action="store_true",
                       help="不写入历史库、不生成 HTML 趋势报告")
    p_aud.add_argument("--dry-run", action="store_true", help="只列出将测的节点，不切换不检测")
    p_aud.add_argument("--yes", "-y", action="store_true", help="跳过切换前的确认提示")
    p_aud.set_defaults(func=cmd_audit)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\n已中断。")
        return 130
    except Exception as e:  # noqa: BLE001
        print(f"错误: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
