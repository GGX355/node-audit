"""自包含表格 HTML 报告（归档用）。日常入口是控制台 latest.html（dashboard.py）。"""
from __future__ import annotations

import html
import shutil
from collections import Counter
from pathlib import Path

from ..core.history import enrich_trend
from .output import _svc_md_text


def _e(v) -> str:
    return html.escape(str(v if v is not None else "-"), quote=True)


_CSS = """
body{font-family:"Microsoft YaHei",system-ui,sans-serif;margin:0;background:#f5f6f8;color:#1c2733}
.wrap{max-width:1200px;margin:0 auto;padding:24px}
h1{font-size:22px} h2{font-size:17px;margin:28px 0 10px}
.meta{color:#5b6b7b;font-size:13px}
.cards{display:flex;gap:12px;flex-wrap:wrap;margin:14px 0}
.card{background:#fff;border-radius:8px;padding:12px 18px;box-shadow:0 1px 3px rgba(0,0,0,.08)}
.card .num{font-size:24px;font-weight:700}
.card .lbl{font-size:12px;color:#5b6b7b}
table{border-collapse:collapse;width:100%;background:#fff;font-size:13px;box-shadow:0 1px 3px rgba(0,0,0,.08)}
th,td{border:1px solid #e3e8ee;padding:6px 9px;text-align:left;vertical-align:top}
th{background:#eef2f6;white-space:nowrap}
tr:hover td{background:#f4f8fd}
tr.degraded td{background:#fdecea}
tr.degraded:hover td{background:#f8d7da}
.dc{color:#b3261e;font-weight:600}.res{color:#1a7f37;font-weight:600}
.ok{color:#1a7f37}.bad{color:#b3261e}.warn{color:#b26a00}
.trend{overflow-x:auto}
.small{font-size:12px;color:#5b6b7b}
.chg{display:inline-block;margin-left:4px;padding:0 5px;border-radius:3px;background:#fff3cd;color:#7a5b00;font-size:11px}
.delta{font-size:11px;margin-left:4px}
footer{margin-top:26px;color:#8a99a8;font-size:12px}
"""


def _verdict_class(verdict: str) -> str:
    if "家宽" in verdict:
        return "res"
    if "机房" in verdict or "IDC" in verdict:
        return "dc"
    return ""


def _status_class(status: str) -> str:
    return {"ok": "ok", "full": "ok", "captcha": "warn", "original": "warn",
            "blocked": "bad", "none": "bad"}.get(status, "")


def _fmt_delta(n, *, bad_when_up: bool) -> str:
    """n>0 为升。bad_when_up=True 用于 RTT/风控（升=坏）；False 用于速度（降=坏）。"""
    if n is None or n == 0:
        return ""
    sign = "+" if n > 0 else ""
    bad = (n > 0) if bad_when_up else (n < 0)
    cls = "bad" if bad else "ok"
    return f" <span class='delta {cls}'>{sign}{n}</span>"


def _trend_cell_html(cell: dict | None) -> str:
    if not cell:
        return "<td class='small'>未测</td>"
    bits = []
    if cell.get("rtt") is not None:
        bits.append(f"RTT {cell['rtt']}{_fmt_delta(cell.get('rtt_delta'), bad_when_up=True)}")
    if cell.get("speed") is not None:
        bits.append(f"{cell['speed']}Mbps{_fmt_delta(cell.get('speed_delta'), bad_when_up=False)}")
    if cell.get("exit_ip"):
        ip = _e(cell["exit_ip"])
        if cell.get("ip4_changed") or (cell.get("ip_changed") and not cell.get("exit_ip6")
                                       and not cell.get("ip6_changed")):
            ip += "<span class='chg'>换</span>"
        bits.append(ip)
    if cell.get("exit_ip6"):
        ip6 = _e(cell["exit_ip6"])
        if cell.get("ip6_changed"):
            ip6 += "<span class='chg'>换</span>"
        bits.append(ip6)
    if cell.get("risk_pct") is not None:
        bits.append(f"风控 {cell['risk_pct']}%{_fmt_delta(cell.get('risk_delta'), bad_when_up=True)}")
    v = cell.get("verdict") or "-"
    bits.append(f"<span class='{_verdict_class(v)}'>{_e(v)}</span>")
    return "<td>" + "<br>".join(bits) + "</td>"


def render_html(reports, meta: dict, trend: tuple) -> str:
    """reports: [NodeReport]；meta: 含 run_id/generated_at/controller/mode；
    trend: (runs, rows) 来自 history.load_trend（含本次）。"""
    runs, rows = trend
    rows = enrich_trend(runs, rows)
    counts = Counter(r.verdict for r in reports)
    ok_count = sum(1 for r in reports if not r.error)
    speeds = [r.speed_mbps for r in reports if r.speed_mbps is not None]
    rtts = [r.rtt_min for r in reports if r.rtt_min is not None]

    parts = [
        "<!doctype html><html lang='zh'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width,initial-scale=1'>",
        f"<title>node-audit 报告 {_e(meta.get('run_id', ''))}</title>",
        f"<style>{_CSS}</style></head><body><div class='wrap'>",
        "<h1>node-audit 节点质量审计报告</h1>",
        f"<div class='meta'>run {_e(meta.get('run_id', '-'))} · "
        f"生成 {_e(meta.get('generated_at', '-'))} · 模式 {_e(meta.get('mode', '-'))}<br>",
        f"控制器 {_e(meta.get('controller', ''))}</div>",
        "<div class='cards'>",
        f"<div class='card'><div class='num'>{len(reports)}</div><div class='lbl'>节点</div></div>",
        f"<div class='card'><div class='num'>{ok_count}</div><div class='lbl'>成功检测</div></div>",
        f"<div class='card'><div class='num'>{counts.get('机房', 0) + sum(v for k, v in counts.items() if 'IDC' in k)}</div><div class='lbl'>机房/疑似IDC</div></div>",
        f"<div class='card'><div class='num'>{sum(v for k, v in counts.items() if '家宽' in k)}</div><div class='lbl'>疑似真家宽</div></div>",
        f"<div class='card'><div class='num'>{max(speeds) if speeds else '-'}</div><div class='lbl'>峰值速度 Mbps</div></div>",
        f"<div class='card'><div class='num'>{min(rtts) if rtts else '-'}</div><div class='lbl'>最低 RTT ms</div></div>",
        "</div>",
        "<h2>判定分布</h2><table><tr><th>判定</th><th>节点数</th></tr>",
        "".join(f"<tr><td>{_e(k)}</td><td>{v}</td></tr>" for k, v in counts.most_common()),
        "</table>",
        "<h2>本次明细</h2><table>",
        "<tr><th>节点</th><th>预期</th><th>出口IP</th><th>归属</th><th>ISP</th><th>类型</th>"
        "<th>RTT(ms)</th><th>速度 Mbps</th><th>一致性</th><th>服务</th><th>判定</th><th>备注</th></tr>",
    ]
    for r in reports:
        svc = _svc_md_text(r)
        cells = [
            _e(r.name),
            _e(r.region_cn or "-"),
            "<br>".join(p for p in (_e(r.exit_ip) if r.exit_ip else "",
                                    _e(r.exit_ip6) if r.exit_ip6 else "") if p) or "-",
            _e(f"{r.country_code or '-'} {r.city or ''}".strip()),
            _e(r.isp or "-"),
            "<span class='dc'>机房</span>" if r.hosting is True
            else "<span class='res'>住宅</span>" if r.hosting is False else "-",
            _e(r.rtt_min if r.rtt_min is not None else "-"),
            _e(r.speed_mbps if r.speed_mbps is not None else "-"),
            _e({"match": "✓", "mismatch": "✗", "unknown": "?"}.get(r.geo_match, "?")),
            _e(svc),
            f"<span class='{_verdict_class(r.verdict)}'>{_e(r.verdict)}</span>",
            _e("；".join(r.notes) if r.notes else (r.error or "-")),
        ]
        parts.append("<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
    parts.append("</table>")

    # 跨次趋势：每个节点一行，每个 run 一列；变慢行置顶标红
    if runs:
        n_slow = sum(1 for row in rows if row.get("degraded"))
        parts.append("<h2>历史趋势（含本次）</h2>")
        parts.append(
            f"<p class='small'>最近 {len(runs)} 次审计，旧 → 新。"
            "「换」= 相对上次 v4 或 v6 出口变了（两个地址分别标）；风控 / RTT / 速度旁为相对上次的 Δ "
            "（红=变差，绿=变好）。速度下降 ≥40% 或 RTT 翻倍的节点整行标红并置顶"
            f"{f'（本次 {n_slow} 个）' if n_slow else ''}。"
            "未测 = 该次未覆盖此节点。</p>"
        )
        parts.append("<div class='trend'><table><tr><th>节点</th>")
        for run_id in runs:
            parts.append(f"<th>{_e(run_id)}</th>")
        parts.append("</tr>")
        for row in rows:
            tr_cls = " class='degraded'" if row.get("degraded") else ""
            parts.append(f"<tr{tr_cls}><td>{_e(row['node'])}</td>")
            for run_id in runs:
                parts.append(_trend_cell_html(row["cells"].get(run_id)))
            parts.append("</tr>")
        parts.append("</table></div>")
    else:
        parts.append("<h2>历史趋势</h2><p class='small'>暂无历史数据（本次已开始记录，"
                     "再次审计后此处会出现跨次对比）。</p>")

    parts.append("<footer>由 node-audit 生成 · 仅用于检测自有订阅节点质量</footer>")
    parts.append("</div></body></html>")
    return "".join(parts)


def write_html(reports, meta: dict, path, trend: tuple) -> None:
    Path(path).write_text(render_html(reports, meta, trend), encoding="utf-8")


def publish_latest(html_path) -> Path:
    """把本次 HTML 复制为同目录 latest.html（覆盖）。Windows 不用 symlink。"""
    src = Path(html_path)
    dest = src.parent / "latest.html"
    shutil.copyfile(src, dest)
    return dest
