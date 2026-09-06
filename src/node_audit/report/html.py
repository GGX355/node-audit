"""自包含 HTML 报告（v0.4）：本次审计结果 + 跨次趋势视图。

纯标准库（内联 CSS，无外部资源、无 JS），单文件可直接分享/存档。
"""
from __future__ import annotations

import html
from collections import Counter
from pathlib import Path

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
.dc{color:#b3261e;font-weight:600}.res{color:#1a7f37;font-weight:600}
.ok{color:#1a7f37}.bad{color:#b3261e}.warn{color:#b26a00}
.trend{overflow-x:auto}
.small{font-size:12px;color:#5b6b7b}
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


def render_html(reports, meta: dict, trend: tuple) -> str:
    """reports: [NodeReport]；meta: 含 run_id/generated_at/controller/mode；
    trend: (runs, rows) 来自 history.load_trend（含本次）。"""
    runs, rows = trend
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
            _e(r.exit_ip or "-"),
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

    # 跨次趋势：每个节点一行，每个 run 一列（RTT / 速度 / 出口IP / 判定）
    if runs:
        parts.append("<h2>历史趋势（含本次）</h2>")
        parts.append(f"<p class='small'>最近 {len(runs)} 次审计，旧 → 新。"
                     "RTT 单位 ms；未测 = 该次未覆盖此节点。同一节点出口 IP 变化（家宽轮换）直接可见。</p>")
        parts.append("<div class='trend'><table><tr><th>节点</th>")
        for run_id in runs:
            parts.append(f"<th>{_e(run_id)}</th>")
        parts.append("</tr>")
        for row in rows:
            parts.append(f"<tr><td>{_e(row['node'])}</td>")
            for run_id in runs:
                cell = row["cells"].get(run_id)
                if not cell:
                    parts.append("<td class='small'>未测</td>")
                    continue
                bits = []
                if cell.get("rtt") is not None:
                    bits.append(f"RTT {cell['rtt']}")
                if cell.get("speed") is not None:
                    bits.append(f"{cell['speed']}Mbps")
                if cell.get("exit_ip"):
                    bits.append(_e(cell["exit_ip"]))
                v = cell.get("verdict") or "-"
                bits.append(f"<span class='{_verdict_class(v)}'>{_e(v)}</span>")
                parts.append("<td>" + "<br>".join(bits) + "</td>")
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
