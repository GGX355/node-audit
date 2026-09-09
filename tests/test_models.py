from node_audit.core.models import DeepCheck, NodeReport, build_verdict


def _rep(**kw) -> NodeReport:
    rep = NodeReport(name="测试节点", node_type="AnyTLS")
    for k, v in kw.items():
        setattr(rep, k, v)
    return rep


def test_hosting_true_is_datacenter():
    rep = _rep(region_code="JP", region_cn="日本", country_code="JP",
               hosting=True, rtt_min=80)
    verdict, notes = build_verdict(rep)
    assert verdict == "机房"
    assert rep.geo_match == "match"
    assert notes == []


def test_datacenter_ippure_appends_risk():
    rep = _rep(region_code="JP", region_cn="日本", country_code="JP",
               hosting=True, rtt_min=80,
               deep=DeepCheck(ippure={"available": True, "fraud_score": 31}))
    verdict, notes = build_verdict(rep)
    assert verdict == "机房·风控31%"


def test_residential_with_ping0_family():
    rep = _rep(region_code="TW", region_cn="台湾", country_code="TW",
               hosting=False,
               deep=DeepCheck(ping0={"available": True, "ip_type": "家庭宽带 IP",
                                     "native": "原生 IP", "risk_pct": 7}))
    verdict, notes = build_verdict(rep)
    assert verdict == "疑似真家宽·原生·风控7%"


def test_residential_ippure_fills_when_ping0_empty():
    rep = _rep(region_code="TW", region_cn="台湾", country_code="TW",
               hosting=False,
               deep=DeepCheck(ippure={"available": True, "is_residential": True,
                                      "is_broadcast": False, "fraud_score": 12}))
    verdict, notes = build_verdict(rep)
    assert verdict.startswith("疑似真家宽")
    assert "原生" in verdict
    assert "风控12%" in verdict
    assert not any("均不可用" in n for n in notes)


def test_ipapi_miss_but_ping0_idc():
    # ip-api 的 hosting 字段失灵（报住宅）但 ping0 细分出 IDC
    rep = _rep(region_code="KR", region_cn="韩国", country_code="KR",
               hosting=False,
               deep=DeepCheck(ping0={"available": True, "ip_type": "IDC机房 IP",
                                     "native": "原生 IP", "risk_pct": 96}))
    verdict, notes = build_verdict(rep)
    assert verdict.startswith("疑似IDC")


def test_geo_mismatch_note():
    rep = _rep(region_code="US", region_cn="美国", country_code="HK",
               hosting=True)
    verdict, notes = build_verdict(rep)
    assert rep.geo_match == "mismatch"
    assert any("名称标注美国" in n and "HK" in n for n in notes)


def test_rtt_region_suspect():
    rep = _rep(region_code="KR", region_cn="韩国", country_code="KR",
               hosting=True, rtt_min=391)
    verdict, notes = build_verdict(rep)
    assert any("落地存疑" in n for n in notes)


def test_rtt_ok_no_note():
    rep = _rep(region_code="HK", region_cn="香港", country_code="HK",
               hosting=True, rtt_min=54)
    verdict, notes = build_verdict(rep)
    assert not any("落地存疑" in n for n in notes)


def test_ipqs_and_abuseipdb_notes():
    rep = _rep(hosting=False,
               deep=DeepCheck(ping0={"available": True, "ip_type": "家庭宽带 IP"},
                              ipqs={"available": True, "fraud_score": 86,
                                    "proxy": True, "vpn": False, "tor": False},
                              abuseipdb={"available": True, "score": 75, "reports": 12}))
    verdict, notes = build_verdict(rep)
    assert any("IPQS 高风险(86)" in n for n in notes)
    assert any("IPQS 标记 proxy/vpn/tor" in n for n in notes)
    assert any("AbuseIPDB 滥用置信度 75%" in n for n in notes)


def test_exit_label_dual_and_single():
    assert _rep(exit_ip="1.1.1.1", exit_ip6="2001:db8::1").exit_label() == "1.1.1.1 / 2001:db8::1"
    assert _rep(exit_ip="1.1.1.1").exit_label() == "1.1.1.1"
    assert _rep(exit_ip6="2001:db8::1").exit_label() == "2001:db8::1"
    assert _rep().exit_label() == "-"


def test_error_report():
    verdict, notes = build_verdict(_rep(error="超时"))
    assert verdict == "失败"


def test_speed_partial_note():
    rep = _rep(region_code="JP", region_cn="日本", country_code="JP",
               hosting=True, speed_partial=True)
    verdict, notes = build_verdict(rep)
    assert any("部分数据" in n for n in notes)
