"""检查项实现：身份 / PTR / RDAP / 延迟 / 测速 / 深检(网页+官方API)。

所有 HTTP 请求显式走指定代理出口（被测节点的 mixed-port 或 isolated
模式下的独立端口），不读取环境代理变量，保证请求确实经由被测节点。
"""
from __future__ import annotations

import ipaddress
import json
import re
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import quote

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# 多目标延迟探针：基础连通（gstatic）+ 到 Cloudflare 边缘的 RTT
LATENCY_PROBE_TARGETS = [
    ("gstatic", "http://www.gstatic.com/generate_204"),
    ("cloudflare", "https://cp.cloudflare.com/generate_204"),
]


def _opener(proxy: str | None) -> urllib.request.OpenerDirector:
    if proxy:
        handler = urllib.request.ProxyHandler({"http": proxy, "https": proxy})
    else:
        handler = urllib.request.ProxyHandler({})  # 显式禁用环境代理
    return urllib.request.build_opener(handler)


def http_get(url: str, proxy: str | None, timeout: float = 15,
             headers: dict | None = None) -> tuple[int, bytes]:
    req_headers = {"User-Agent": UA, "Accept": "*/*"}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, headers=req_headers)
    try:
        with _opener(proxy).open(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read() or b""


def _strip_text(html: str) -> list[str]:
    """去 script/style 后按标签切行，返回非空行列表（用于宽松页面解析）。"""
    text = re.sub(r"<script.*?</script>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.S | re.I)
    return [t.strip() for t in re.sub(r"<[^>]+>", "\n", text).split("\n") if t.strip()]


def ptr_qname(ip: str | None) -> str | None:
    """PTR 查询名：v4 → in-addr.arpa，v6 → RFC 3596 半字节反转 ip6.arpa。"""
    if not ip:
        return None
    try:
        return ipaddress.ip_address(ip.strip()).reverse_pointer
    except ValueError:
        return None


# 免费 ip-api 约 45 次/分钟。并行审计时必须排队，否则会批量失败。
_ipapi_lock = threading.Lock()
_ipapi_next = 0.0
_IPAPI_GAP = 1.4


def _ipapi_identity(proxy: str, timeout: float) -> dict | None:
    global _ipapi_next
    fields = "query,country,countryCode,city,isp,org,as,asname,proxy,hosting,mobile"
    with _ipapi_lock:
        wait = _ipapi_next - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        try:
            status, data = http_get(f"http://ip-api.com/json/?fields={fields}", proxy, timeout)
            d = json.loads(data.decode()) if status == 200 else None
            return d if d and d.get("query") else None
        except Exception:
            return None
        finally:
            _ipapi_next = time.monotonic() + _IPAPI_GAP


def _ipify4(proxy: str, timeout: float) -> str | None:
    """api.ipify.org：纯 v4。ip-api 被墙/限流时的退路。"""
    try:
        status, data = http_get("https://api.ipify.org", proxy, timeout)
        if status != 200:
            return None
        text = data.decode().strip()
        if text and "." in text and ":" not in text:
            return text
    except Exception:
        pass
    return None


def _ipify6(proxy: str, timeout: float) -> str | None:
    """api64.ipify.org：有 v6 出口则返回含 ':' 的地址，否则是 v4。"""
    try:
        status, data = http_get("https://api64.ipify.org", proxy, timeout)
        if status != 200:
            return None
        text = data.decode().strip()
        if ":" in text:
            return text
    except Exception:
        pass
    return None


def _ipwho_identity(ip: str, proxy: str, timeout: float) -> dict | None:
    """ipwho.is：免费、支持 v6、无 key。hosting 在 security 里，没有就算了。"""
    try:
        status, data = http_get(f"https://ipwho.is/{quote(ip, safe='')}", proxy, timeout)
        if status != 200:
            return None
        d = json.loads(data.decode())
        if d.get("success") is False:
            return None
        conn = d.get("connection") or {}
        sec = d.get("security") or {}
        asn, org = conn.get("asn"), conn.get("org")
        as_str = f"AS{asn}" + (f" {org}" if org else "") if asn else None
        hosting = sec.get("hosting")
        if hosting is None:
            ctype = str(conn.get("type") or conn.get("connection_type") or "").lower()
            if ctype in ("hosting", "datacenter", "cdn"):
                hosting = True
            elif ctype in ("isp", "residential", "cable/dsl", "cable", "dsl", "consumer"):
                hosting = False
        return {
            "query": d.get("ip") or ip,
            "country": d.get("country"),
            "countryCode": d.get("country_code"),
            "city": d.get("city"),
            "isp": conn.get("isp"),
            "org": org,
            "as": as_str,
            "asname": org,
            "proxy": sec.get("proxy"),
            "hosting": hosting,
        }
    except Exception:
        return None


def check_ippure(proxy: str, timeout: float = 15) -> dict:
    """IPPure 公开 JSON：调用者出口的风险分 / 是否住宅 / 是否广播。无验证码。"""
    out = {"available": False, "ip": None, "fraud_score": None,
           "is_residential": None, "is_broadcast": None, "is_datacenter": None,
           "country": None, "country_code": None, "city": None,
           "asn": None, "org": None}
    try:
        status, data = http_get("https://my.ippure.com/v1/info", proxy, timeout)
        if status != 200:
            return out
        d = json.loads(data.decode())
    except Exception:
        return out
    ip = d.get("ip")
    if not ip:
        return out
    res, dc = d.get("isResidential"), d.get("isDataCenter")
    out.update(
        available=True, ip=ip,
        fraud_score=d.get("fraudScore"),
        is_residential=res if isinstance(res, bool) else None,
        is_broadcast=d.get("isBroadcast") if isinstance(d.get("isBroadcast"), bool) else None,
        is_datacenter=dc if isinstance(dc, bool) else None,
        country=d.get("country"),
        country_code=d.get("countryCode"),
        city=d.get("city"),
        asn=d.get("asn"),
        org=d.get("asOrganization"),
    )
    return out


def check_iplark(proxy: str, timeout: float = 15) -> dict:
    """iplark ipdata JSON（/check 页面过简）。访问者 IP 的 trust / 机房 / VPN。"""
    out = {"available": False, "trust_score": None, "is_datacenter": None,
           "is_vpn": None, "is_proxy": None, "ip": None}
    try:
        status, data = http_get(
            "https://iplark.com/ipapi/public/ipinfo?db=ipdata", proxy, timeout)
        if status != 200:
            return out
        d = json.loads(data.decode())
    except Exception:
        return out
    if not isinstance(d, dict):
        return out
    threat = d.get("threat") if isinstance(d.get("threat"), dict) else {}
    out["ip"] = d.get("ip") or d.get("query")
    ts = d.get("trust_score") if d.get("trust_score") is not None else threat.get("trust_score")
    if ts is not None:
        try:
            out["trust_score"] = int(ts)
        except (TypeError, ValueError):
            pass
    for key in ("is_datacenter", "is_vpn", "is_proxy"):
        val = d.get(key)
        if val is None:
            val = threat.get(key)
        if val is not None:
            out[key] = bool(val)
    out["available"] = bool(out["ip"] or out["trust_score"] is not None
                            or out["is_datacenter"] is not None)
    return out


def _identity_from_ippure(ipu: dict) -> dict | None:
    ip = (ipu or {}).get("ip")
    if not ip:
        return None
    v6 = ":" in ip
    hosting = None
    if ipu.get("is_residential") is True:
        hosting = False
    elif ipu.get("is_residential") is False or ipu.get("is_datacenter") is True:
        hosting = True
    asn, org = ipu.get("asn"), ipu.get("org")
    as_str = f"AS{asn}" + (f" {org}" if org else "") if asn else None
    rec = {
        "query": None if v6 else ip,
        "country": ipu.get("country"),
        "countryCode": ipu.get("country_code"),
        "city": ipu.get("city"),
        "isp": org, "org": org, "as": as_str, "asname": org,
        "proxy": None, "hosting": hosting,
    }
    return {
        "query": rec["query"], "query6": ip if v6 else None,
        "v4": None if v6 else rec, "v6": rec if v6 else None,
        "identity_source": "ippure",
        **{k: rec[k] for k in ("country", "countryCode", "city", "isp", "org",
                               "as", "asname", "proxy", "hosting")},
    }


def check_identity(proxy: str, timeout: float = 15) -> dict | None:
    """双栈出口身份。v4 走 ip-api（含 hosting）；v6 走 ipify + ipwho.is。

    返回 None 仅当 v4 与 v6 都拿不到。判定字段优先用带 hosting 的那一侧。
    """
    v4 = _ipapi_identity(proxy, timeout)
    if not v4:
        ip4 = _ipify4(proxy, timeout)
        if ip4:
            v4 = _ipwho_identity(ip4, proxy, timeout) or {"query": ip4}
    v6_addr = _ipify6(proxy, timeout)
    v6 = _ipwho_identity(v6_addr, proxy, timeout) if v6_addr else None
    if v6_addr and not v6:
        v6 = {"query": v6_addr}
    if not v4 and not v6:
        ident = _identity_from_ippure(check_ippure(proxy, timeout))
        return ident
    out = {
        "query": (v4 or {}).get("query"),
        "query6": (v6 or {}).get("query") or v6_addr,
        "v4": v4,
        "v6": v6,
    }
    if v4 and v4.get("hosting") is not None:
        primary, src = v4, "ip-api"
    elif v6 and v6.get("hosting") is not None:
        primary, src = v6, "ipwho.is"
    elif v4:
        primary, src = v4, "ip-api"
    else:
        primary, src = v6, "ipwho.is"
    out["identity_source"] = src
    for k in ("country", "countryCode", "city", "isp", "org", "as", "asname", "proxy", "hosting"):
        out[k] = (primary or {}).get(k)
    return out


def check_ptr(ip: str | None, proxy: str, timeout: float = 10) -> str | None:
    """DNS-over-HTTPS 反查 PTR，不依赖系统 nslookup（跨平台一致）。"""
    name = ptr_qname(ip)
    if not name:
        return None
    for resolver in ("https://cloudflare-dns.com/dns-query", "https://dns.google/resolve"):
        try:
            status, data = http_get(
                f"{resolver}?name={name}&type=PTR", proxy, timeout,
                headers={"Accept": "application/dns-json"},
            )
            if status != 200:
                continue
            for a in json.loads(data.decode()).get("Answer") or []:
                if a.get("type") == 12 and a.get("data"):
                    return a["data"].rstrip(".")
        except Exception:
            continue
    return None


def check_rdap(ip: str | None, proxy: str, timeout: float = 20) -> dict | None:
    """rdap.org 自动引导到正确 RIR，解析注册组织与注册日期。"""
    if not ip:
        return None
    path = quote(ip, safe="") if ":" in ip else ip
    try:
        status, data = http_get(f"https://rdap.org/ip/{path}", proxy, timeout)
        if status != 200:
            return None
        d = json.loads(data.decode())
    except Exception:
        return None
    org = None
    for ent in d.get("entities", []):
        if "registrant" in ent.get("roles", []):
            vcard = ent.get("vcardArray") or []
            for item in (vcard[1] if len(vcard) > 1 else []):
                if item and item[0] == "fn":
                    org = item[3]
                    break
            if org:
                break
    date = None
    for ev in d.get("events", []):
        if ev.get("eventAction") == "registration":
            date = (ev.get("eventDate") or "")[:10]
    return {"org": org or d.get("name"), "name": d.get("name"), "date": date}


def measure_latency(proxy: str, targets=None, timeout: float = 5.0) -> dict:
    """对当前代理出口做多目标延迟测量（HTTP 首字节耗时，单位 ms）。

    attach / isolated 两种模式都用这一条路径，保证口径一致。
    先发一次预热请求：冷启动的独立内核要现场建链（节点握手 + DNS），
    不预热的话首个探针会把建链成本算进延迟，数字虚高。
    """
    targets = targets or LATENCY_PROBE_TARGETS
    try:
        http_get(targets[0][1], proxy, timeout)
    except Exception:
        pass
    out: dict[str, int] = {}
    for label, url in targets:
        t0 = time.perf_counter()
        try:
            status, _ = http_get(url, proxy, timeout)
            if status < 500:
                out[label] = int((time.perf_counter() - t0) * 1000)
        except Exception:
            continue
    return out


def speed_test(proxy: str, nbytes: int, timeout: float = 30,
               max_seconds: float = 60) -> dict:
    """下载测速。主目标 Cloudflare，备选 cachefly。

    两层超时：socket 级 timeout（对端停摆时单次 read 最多挂这么久）+
    max_seconds 总时限（到时按已收字节算部分速度并标记 partial）。
    """
    out = {"ok": False, "mbps": None, "bytes": 0, "seconds": None,
           "partial": False, "target": None, "reason": None}
    mb = max(1, round(nbytes / 1_000_000))
    targets = [
        f"https://speed.cloudflare.com/__down?bytes={nbytes}",
        f"http://cachefly.cachefly.net/{mb}mb.test",
    ]
    for url in targets:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            t0 = time.perf_counter()
            deadline = t0 + max_seconds
            total = 0
            partial = False
            with _opener(proxy).open(req, timeout=timeout) as resp:
                while True:
                    if total > 0 and time.perf_counter() > deadline:
                        partial = True
                        break
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    total += len(chunk)
            dt = time.perf_counter() - t0
            if total > 0 and dt > 0:
                out.update(ok=True, bytes=total, seconds=round(dt, 2),
                           mbps=round(total * 8 / dt / 1e6, 1),
                           partial=partial, target=url)
                return out
        except Exception as e:
            out["reason"] = f"{type(e).__name__}: {e}"[:160]
            continue
    return out


def check_scamalytics(ip: str | None, proxy: str, timeout: float = 20) -> dict:
    """Scamalytics 页面解析（best-effort，反爬导致失败时 available=False）。"""
    out = {"available": False, "score": None, "level": None, "datacenter": None}
    if not ip:
        return out
    try:
        status, data = http_get(
            f"https://scamalytics.com/ip/{ip}", proxy, timeout, headers=_HTML_HEADERS)
    except Exception:
        return out
    if status != 200:
        return out
    lines = _strip_text(data.decode(errors="replace"))
    out["available"] = True
    for i, line in enumerate(lines):
        if line.startswith("Fraud Score") and out["score"] is None:
            m = re.search(r"(\d+)", line)
            if m:
                out["score"] = int(m.group(1))
            elif i + 1 < len(lines) and re.fullmatch(r"\d+", lines[i + 1]):
                out["score"] = int(lines[i + 1])
        if out["level"] is None:
            m = re.search(r"(Very High|High|Elevated|Moderate|Low)\s+Risk", line)
            if m:
                out["level"] = m.group(1)
        if line.rstrip(":") == "Datacenter" and out["datacenter"] is None:
            for nxt in lines[i + 1:i + 3]:
                if nxt in ("Yes", "No"):
                    out["datacenter"] = nxt
                    break
    return out


_HTML_HEADERS = {
    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def check_ping0(ip: str | None, proxy: str, timeout: float = 25) -> dict:
    """ping0.cc 查指定 IP（/ip/{addr}），比扒首页稳：首页 FAQ 会干扰，且常反爬。"""
    out = {"available": False, "ip_type": None, "native": None,
           "risk_pct": None, "risk_level": None}
    urls = []
    if ip:
        urls.append(f"https://ping0.cc/ip/{quote(ip, safe='')}")
    urls.append("https://ping0.cc/")
    html = ""
    for url in urls:
        try:
            status, data = http_get(url, proxy, timeout, headers=_HTML_HEADERS)
        except Exception:
            continue
        if status != 200:
            continue
        html = data.decode(errors="replace")
        if html:
            break
    if not html:
        return out
    lines = _strip_text(html)
    faq = False
    type_words = ("家庭宽带 IP", "家庭宽带IP", "IDC机房 IP", "IDC机房IP")
    native_words = ("原生 IP", "原生IP", "广播 IP", "广播IP")
    for i, line in enumerate(lines):
        if "常见问题" in line or line.startswith("Q") and "识别" in line:
            faq = True
        if faq:
            continue
        if out["ip_type"] is None:
            if line in type_words:
                out["ip_type"] = line
            elif line in ("家庭宽带", "家庭宽带IP"):
                out["ip_type"] = "家庭宽带 IP"
            elif line in ("IDC机房IP", "IDC机房") or line == "IDC机房 IP":
                out["ip_type"] = "IDC机房 IP"
        if out["native"] is None:
            if line in native_words:
                out["native"] = line
            elif line.strip() in ("原生 IP", "原生IP", "原生"):
                out["native"] = "原生 IP"
            elif line.strip() in ("广播 IP", "广播IP", "广播"):
                out["native"] = "广播 IP"
        if out["risk_pct"] is None:
            m = re.fullmatch(r"(\d{1,3})%\s*(.*)", line)
            if m:
                out["risk_pct"] = int(m.group(1))
                rest = m.group(2).strip()
                if rest:
                    out["risk_level"] = rest
                elif i + 1 < len(lines):
                    out["risk_level"] = lines[i + 1]
    out["available"] = bool(out["ip_type"] or out["native"] or out["risk_pct"] is not None)
    return out


def check_ipqs(ip: str | None, api_key: str, proxy: str, timeout: float = 15) -> dict:
    """IPQualityScore 官方 API（免费 key：https://www.ipqualityscore.com）。

    直连本机网络，不把 API key 送进被测节点。`proxy` 保留以兼容调用方，忽略。
    """
    out = {"available": False, "fraud_score": None, "proxy": None,
           "vpn": None, "tor": None}
    if not ip or not api_key:
        return out
    url = (f"https://ipqualityscore.com/api/json/ip/{api_key}/{ip}"
           "?strictness=0&allow_public_access_points=true&fast=true")
    try:
        status, data = http_get(url, None, timeout)  # 直连；key 在 URL 路径里
        if status != 200:
            return out
        d = json.loads(data.decode())
        if not d.get("success", False) and "errors" in d:
            out["reason"] = str(d.get("errors"))[:120]
            return out
        out.update(available=True,
                   fraud_score=d.get("fraud_score"),
                   proxy=d.get("proxy"), vpn=d.get("vpn"), tor=d.get("tor"))
    except Exception:
        pass
    return out


def check_abuseipdb(ip: str | None, api_key: str, proxy: str, timeout: float = 15) -> dict:
    """AbuseIPDB 官方 API（免费 key：https://www.abuseipdb.com，1000 次/天）。"""
    out = {"available": False, "score": None, "reports": None}
    if not ip or not api_key:
        return out
    url = f"https://api.abuseipdb.com/api/v2/check?ipAddress={ip}&maxAgeInDays=90"
    try:
        status, data = http_get(url, proxy, timeout, headers={
            "Key": api_key, "Accept": "application/json",
        })
        if status != 200:
            return out
        d = json.loads(data.decode()).get("data") or {}
        out.update(available=True,
                   score=d.get("abuseConfidenceScore"),
                   reports=d.get("totalReports"))
    except Exception:
        pass
    return out
