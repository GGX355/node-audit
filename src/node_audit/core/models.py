"""单个节点的审计结果模型与综合判定。"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .filters import RTT_MAX_MS, DEFAULT_RTT_MAX_MS


@dataclass
class DeepCheck:
    """第二阶段深检结果。available=False 表示该数据源本次不可用。"""

    scamalytics: dict | None = None  # {available, score, level, datacenter}
    ping0: dict | None = None        # {available, ip_type, native, risk_pct, risk_level}
    ipqs: dict | None = None         # {available, fraud_score, proxy, vpn, tor}
    abuseipdb: dict | None = None    # {available, score, reports}


@dataclass
class NodeReport:
    name: str
    node_type: str = ""
    region_code: str | None = None
    region_cn: str | None = None
    rate: float | None = None
    heavy: bool = False

    exit_ip: str | None = None
    country: str | None = None
    country_code: str | None = None
    city: str | None = None
    isp: str | None = None
    org: str | None = None
    asn: str | None = None
    asname: str | None = None
    hosting: bool | None = None
    proxy_flag: bool | None = None

    ptr: str | None = None
    rdap_org: str | None = None
    rdap_name: str | None = None
    rdap_date: str | None = None

    rtt: dict = field(default_factory=dict)  # target -> ms
    rtt_min: int | None = None
    rtt_suspect: bool | None = None

    speed_mbps: float | None = None
    speed_bytes: int = 0
    speed_seconds: float | None = None
    speed_partial: bool = False
    speed_skipped: str | None = None

    geo_match: str = "unknown"  # match | mismatch | unknown
    deep: DeepCheck | None = None
    services: dict = field(default_factory=dict)  # service -> {status, region, note}
    verdict: str = ""
    notes: list = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def build_verdict(rep: NodeReport) -> tuple[str, list[str]]:
    """综合判定：机房/住宅、原生/广播、地区一致性、风险提示。"""
    notes: list[str] = []
    if rep.error:
        return "失败", notes

    # 名称地区 vs IP 归属地
    if rep.region_code and rep.country_code:
        if rep.region_code == rep.country_code:
            rep.geo_match = "match"
        else:
            rep.geo_match = "mismatch"
            notes.append(
                f"名称标注{rep.region_cn or rep.region_code}，但实际出口为 {rep.country_code}（{rep.country}）"
            )

    # RTT 与预期地区的物理合理性
    if rep.rtt_min is not None and rep.region_code:
        limit = RTT_MAX_MS.get(rep.region_code, DEFAULT_RTT_MAX_MS)
        rep.rtt_suspect = rep.rtt_min > limit
        if rep.rtt_suspect:
            notes.append(
                f"RTT {rep.rtt_min}ms 超出 {rep.region_cn or rep.region_code} 合理上限 {limit}ms，落地存疑"
            )

    if rep.proxy_flag:
        notes.append("ip-api 标记为 proxy/VPN")

    if rep.speed_partial:
        notes.append("测速达到时限，结果为部分数据")

    # 类型判定（hosting 是生死线）
    if rep.hosting is True:
        verdict = "机房"
    elif rep.hosting is False:
        verdict = "住宅候选"
        deep = rep.deep
        if deep:
            p0 = deep.ping0 or {}
            sc = deep.scamalytics or {}
            if p0.get("ip_type"):
                if "家庭宽带" in p0["ip_type"]:
                    verdict = "疑似真家宽"
                elif "IDC" in p0["ip_type"] or "机房" in p0["ip_type"]:
                    verdict = "疑似IDC"
            if p0.get("native"):
                verdict += "·" + p0["native"].replace(" IP", "")
            if p0.get("risk_pct") is not None:
                verdict += f"·风控{p0['risk_pct']}%"
            if sc.get("datacenter") == "Yes":
                notes.append("Scamalytics 标记 Datacenter")
            ipqs = deep.ipqs or {}
            if ipqs.get("fraud_score") is not None:
                if ipqs["fraud_score"] >= 75:
                    notes.append(f"IPQS 高风险({ipqs['fraud_score']})")
                if ipqs.get("proxy") or ipqs.get("vpn") or ipqs.get("tor"):
                    notes.append("IPQS 标记 proxy/vpn/tor")
            ab = deep.abuseipdb or {}
            if ab.get("score") is not None and ab["score"] >= 50:
                notes.append(f"AbuseIPDB 滥用置信度 {ab['score']}%（举报 {ab.get('reports', '?')} 次）")
            if not p0.get("available") and not sc.get("available"):
                notes.append("网页深检数据源均不可用")
    else:
        verdict = "未知(身份查询失败)"
    return verdict, notes
