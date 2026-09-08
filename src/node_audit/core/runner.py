"""审计调度。

- run_attach:    接管运行中的实例，切 global 轮巡节点（v0.1 行为），
                 状态还原同时挂在 finally 与 atexit 上，硬杀进程也会尽力还原。
- run_isolated:  拉起独立 mihomo 实例 + 每节点独立端口（core/isolated.py），
                 全程不触碰用户正在运行的代理。
两者共用 _audit_one -> _check_node 这条检查管线。
"""
from __future__ import annotations

import atexit
import time

from .checks import (LATENCY_PROBE_TARGETS, check_abuseipdb, check_identity,
                     check_iplark, check_ippure, check_ipqs, check_ping0,
                     check_ptr, check_rdap, check_scamalytics, measure_latency,
                     speed_test)
from .filters import heavy_traffic, rate_multiplier, region_from_name
from .models import DeepCheck, NodeReport, build_verdict


def make_delay_fn(api, timeout_ms: int = 5000):
    """用内核的 delay API 测延迟（在核心内部发起，含连接复用、口径统一）。

    attach（用户实例的控制器）与 isolated（临时实例的控制器）共用，
    比从客户端发探针请求更能反映纯网络延迟。
    """
    def delay_fn(name: str) -> dict:
        out: dict[str, int] = {}
        for label, url in LATENCY_PROBE_TARGETS:
            try:
                res = api.proxy_delay(name, url, timeout_ms)
                # 单节点接口返回 {"delay": N}；组接口才返回 {节点名: N}
                v = res.get("delay", res.get(name))
                if isinstance(v, (int, float)):
                    out[label] = int(v)
            except Exception:  # noqa: BLE001
                continue
        return out
    return delay_fn


def _audit_one(name: str, ptype: str, proxy_url: str, opts, log=print) -> NodeReport:
    """对单个节点执行完整检查管线，返回带判定的报告。"""
    rep = NodeReport(name=name, node_type=ptype)
    rep.region_code, rep.region_cn = region_from_name(name)
    rep.rate = rate_multiplier(name)
    rep.heavy = heavy_traffic(name)
    try:
        _check_node(rep, proxy_url, opts, log)
    except Exception as e:  # noqa: BLE001
        rep.error = f"{type(e).__name__}: {e}"
        log(f"    错误  {rep.error}")
    verdict, notes = build_verdict(rep)
    rep.verdict = verdict
    rep.notes.extend(notes)
    if rep.notes:
        log("    备注  " + "；".join(rep.notes))
    return rep


def _check_node(rep: NodeReport, proxy: str, opts, log=print) -> None:
    identity = None
    for _ in (1, 2):  # 瞬时失败重试一次
        identity = check_identity(proxy)
        if identity:
            break
        time.sleep(1.0)
    if not identity:
        rep.error = "无法通过该节点获取出口 IP（v4 ip-api 与 v6 ipify 均失败）"
        log(f"    错误  {rep.error}")
        return
    rep.exit_ip = identity.get("query")
    rep.exit_ip6 = identity.get("query6")
    rep.country = identity.get("country")
    rep.country_code = identity.get("countryCode")
    rep.city = identity.get("city")
    rep.isp = identity.get("isp")
    rep.org = identity.get("org")
    rep.asn = identity.get("as")
    rep.asname = identity.get("asname")
    rep.hosting = identity.get("hosting")
    rep.proxy_flag = identity.get("proxy")
    log(f"    出口  {rep.exit_label()} {rep.country}/{rep.city} | {rep.isp} | {rep.asn}")
    if rep.exit_ip and rep.exit_ip6:
        if identity.get("identity_source") == "ipwho.is":
            other, tag = identity.get("v4") or {}, "v4"
            other_ip = rep.exit_ip
        else:
            other, tag = identity.get("v6") or {}, "v6"
            other_ip = rep.exit_ip6
        extra = [x for x in (
            other.get("countryCode") or other.get("country"),
            other.get("isp"),
        ) if x]
        suffix = f"（{' '.join(str(x) for x in extra)}）" if extra else ""
        rep.notes.append(f"同时有 {tag} 出口 {other_ip}{suffix}")

    primary_ip = rep.exit_ip or rep.exit_ip6
    rep.ptr = check_ptr(primary_ip, proxy)
    if not rep.ptr and rep.exit_ip and rep.exit_ip6:
        rep.ptr = check_ptr(rep.exit_ip6, proxy)
    log(f"    PTR   {rep.ptr or '无'}")

    rd = check_rdap(primary_ip, proxy)
    if rd:
        rep.rdap_org = rd.get("org")
        rep.rdap_name = rd.get("name")
        rep.rdap_date = rd.get("date")

    if opts.delay_fn is not None:
        rep.rtt = opts.delay_fn(rep.name)
    else:
        rep.rtt = measure_latency(proxy)
    vals = [v for v in rep.rtt.values() if v]
    rep.rtt_min = min(vals) if vals else None
    log(f"    延迟  {rep.rtt}")

    if opts.skip_speed:
        rep.speed_skipped = "参数 --skip-speed"
    else:
        nbytes = opts.speed_bytes
        if rep.heavy:  # "勿跑大流量"节点降级为小文件
            nbytes = min(nbytes, opts.heavy_speed_bytes)
            log(f"    测速  该节点标注勿跑大流量，改用 {nbytes // 1_000_000}MB 小文件")
        sp = speed_test(proxy, nbytes, max_seconds=opts.speed_max_seconds)
        if sp.get("ok"):
            rep.speed_mbps = sp["mbps"]
            rep.speed_bytes = sp["bytes"]
            rep.speed_seconds = sp["seconds"]
            rep.speed_partial = sp.get("partial", False)
            tag = "（部分数据）" if rep.speed_partial else ""
            log(f"    速度  {rep.speed_mbps} Mbps（{sp['bytes'] // 1_000_000}MB / {sp['seconds']}s）{tag}")
        else:
            rep.speed_skipped = sp.get("reason") or "测速失败"
            log(f"    速度  失败: {rep.speed_skipped}")

    if opts.services:
        from .services import PROBES, SERVICE_SHORT
        for name in opts.services:
            probe = PROBES.get(name)
            if probe is None:
                continue
            res = probe(proxy)
            rep.services[name] = res
            short = SERVICE_SHORT.get(name, name[:3].upper())
            region = f"({res['region']})" if res.get("region") else ""
            log(f"    服务  {short}: {res['status']}{region}")

    if opts.deep == "off":
        return
    if not ((rep.hosting is False) or opts.deep == "all"):
        log("    深检  跳过（机房 IP）")
        return

    deep = DeepCheck()
    deep.ippure = check_ippure(proxy)
    deep.iplark = check_iplark(proxy)
    deep.ping0 = check_ping0(primary_ip, proxy)
    deep.scamalytics = check_scamalytics(primary_ip, proxy)
    if opts.ipqs_key:
        deep.ipqs = check_ipqs(primary_ip, opts.ipqs_key, proxy)
    if opts.abuseipdb_key:
        deep.abuseipdb = check_abuseipdb(primary_ip, opts.abuseipdb_key, proxy)
    rep.deep = deep

    p0 = deep.ping0 or {}
    sc = deep.scamalytics or {}
    ipu = deep.ippure or {}
    lk = deep.iplark or {}
    ipqs = deep.ipqs or {}
    ab = deep.abuseipdb or {}
    extra = []
    if ipu.get("fraud_score") is not None:
        extra.append(f"ippure={ipu['fraud_score']}")
    if lk.get("trust_score") is not None:
        extra.append(f"iplark信任={lk['trust_score']}")
    if ipqs.get("fraud_score") is not None:
        extra.append(f"ipqs={ipqs['fraud_score']}")
    if ab.get("score") is not None:
        extra.append(f"abuse={ab['score']}%")
    log(
        "    深检  ping0: "
        f"{p0.get('ip_type') or '?'}/{p0.get('native') or '?'}/风控{p0.get('risk_pct') if p0.get('risk_pct') is not None else '?'}%"
        f" | scamalytics: {sc.get('score') if sc.get('score') is not None else '不可用'}"
        + (" | " + " ".join(extra) if extra else "")
    )


def run_attach(api, targets: list, opts, log=print) -> list:
    """attach 模式：接管运行中实例，切 global 轮巡。完成后恢复原状态。"""
    if opts.delay_fn is None:
        opts.delay_fn = make_delay_fn(api)
    configs = api.configs()
    global_now = (api.proxies().get("GLOBAL") or {}).get("now")
    orig_mode = configs.get("mode")
    log(f"当前状态: mode={orig_mode}, GLOBAL→{global_now}")

    state = {"restored": False}

    def restore(when: str):
        if state["restored"]:
            return
        state["restored"] = True
        try:
            cur = (api.proxies().get("GLOBAL") or {}).get("now")
            if global_now and cur != global_now:
                api.select_proxy("GLOBAL", global_now)
            if orig_mode and api.configs().get("mode") != orig_mode:
                api.patch_configs({"mode": orig_mode})
            log(f"[还原:{when}] 已恢复 mode={orig_mode}, GLOBAL→{global_now}")
        except Exception as e:  # noqa: BLE001
            log(f"[还原:{when}][警告] 状态还原失败，请手动在面板里检查: {e}")

    def safety():  # 进程退出兜底（硬杀/异常退出路径）
        if not state["restored"]:
            try:
                cur = (api.proxies().get("GLOBAL") or {}).get("now")
                if global_now and cur != global_now:
                    api.select_proxy("GLOBAL", global_now)
                if orig_mode and api.configs().get("mode") != orig_mode:
                    api.patch_configs({"mode": orig_mode})
            except Exception:  # noqa: BLE001
                pass

    atexit.register(safety)
    results: list[NodeReport] = []
    try:
        # 注意：切换动作必须在 try 内，保证任何时点 Ctrl+C 都会走还原
        api.patch_configs({"mode": "global"})
        time.sleep(0.8)
        total = len(targets)
        for idx, (name, ptype) in enumerate(targets, 1):
            log(f"[{idx}/{total}] {name}")
            api.select_proxy("GLOBAL", name)
            time.sleep(1.0)  # 让新连接走新出口
            results.append(_audit_one(name, ptype, opts.proxy_url, opts, log))
    except KeyboardInterrupt:
        restore("中断")
        log(f"已中断：返回已完成 {len(results)}/{len(targets)} 个节点的部分报告")
        return results
    finally:
        restore("结束")
        atexit.unregister(safety)
    return results
