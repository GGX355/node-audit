"""审计报告落盘：JSON（完整字段）与 Markdown（人读明细）。"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path


def _svc_md_text(r) -> str:
    """服务探针结果的人读文案，Markdown 与 HTML 共用。"""
    from ..core.services import SERVICE_SHORT, STATUS_CN

    parts = []
    for name, res in (r.services or {}).items():
        cn = STATUS_CN.get(res.get("status"), res.get("status", "?"))
        region = f"({res['region']})" if res.get("region") else ""
        parts.append(f"{SERVICE_SHORT.get(name, name)} {cn}{region}")
    return " / ".join(parts) if parts else "-"


def write_json(reports, path: Path, meta: dict) -> None:
    payload = {
        "meta": meta,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "results": [r.to_dict() for r in reports],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_markdown(reports, path: Path, meta: dict) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    lines = [
        "# node-audit 节点质量审计报告",
        "",
        f"- 生成时间: {meta.get('generated_at', now)}",
        f"- 控制器: {meta.get('controller', '')}",
        f"- 运行模式: {meta.get('mode', '')}",
        f"- 节点数: {len(reports)}",
        "",
        "## 摘要",
        "",
    ]
    for k, v in Counter(r.verdict for r in reports).most_common():
        lines.append(f"- **{k}**: {v}")

    lines += [
        "",
        "## 明细",
        "",
        "| 节点 | 出口IP | 归属 | ISP | ASN | 类型 | PTR | 原生 | RTT(ms) | 速度(Mbps) | 一致性 | 风险 | 服务 | 判定 |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in reports:
        p0 = (r.deep.ping0 if r.deep else None) or {}
        sc = (r.deep.scamalytics if r.deep else None) or {}
        if sc.get("score") is not None:
            risk = str(sc["score"])
        elif p0.get("risk_pct") is not None:
            risk = f"{p0['risk_pct']}%"
        else:
            risk = "-"
        rtt = ",".join(f"{k}:{v}" for k, v in r.rtt.items()) or "-"
        ip_type = "机房" if r.hosting is True else ("住宅候选" if r.hosting is False else "-")
        services = _svc_md_text(r).replace("|", "/")
        verdict = r.verdict + (("（" + "；".join(r.notes) + "）") if r.notes else "")
        cells = [
            r.name.replace("|", "/"),
            r.exit_ip or "-",
            f"{r.country or '-'} {r.city or ''}".strip(),
            (r.isp or "-").replace("|", "/"),
            (r.asn or "-").replace("|", "/"),
            ip_type,
            r.ptr or "-",
            (p0.get("native") or "-").replace(" IP", ""),
            rtt,
            r.speed_mbps if r.speed_mbps is not None else "-",
            r.geo_match,
            risk,
            services.replace("|", "/"),
            verdict,
        ]
        lines.append("| " + " | ".join(str(c) for c in cells) + " |")

    fails = [r for r in reports if r.error]
    if fails:
        lines += ["", "## 失败节点", ""]
        for r in fails:
            lines.append(f"- {r.name}: {r.error}")
    skipped = [r for r in reports if r.speed_skipped and not r.error]
    if skipped:
        lines += ["", "## 测速跳过/失败", ""]
        for r in skipped:
            lines.append(f"- {r.name}: {r.speed_skipped}")

    path.write_text("\n".join(lines), encoding="utf-8")
