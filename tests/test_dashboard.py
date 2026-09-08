import json
import os
import tempfile

from node_audit.core.history import load_dashboard, save_run
from node_audit.core.models import DeepCheck, NodeReport
from node_audit.report.dashboard import demo_payload, render_dashboard, write_dashboard


def _rep(name, rtt=50, speed=10.0, hosting=False, run_ip="36.227.213.17",
         run_ip6=None, risk=None, error=None):
    r = NodeReport(name=name, node_type="AnyTLS")
    r.region_code, r.region_cn = "TW", "台湾"
    r.exit_ip = run_ip
    r.exit_ip6 = run_ip6
    r.country_code, r.country, r.city = "TW", "Taiwan", "Taipei"
    r.isp, r.asn = "Chunghwa Telecom", "AS3462"
    r.ptr = "36-227-213-17.hinet.net"
    r.rdap_org = "Chunghwa Telecom"
    r.hosting = hosting
    r.rtt = {"gstatic": rtt, "cloudflare": rtt}
    r.rtt_min = rtt
    r.speed_mbps = speed
    r.error = error
    if risk is not None:
        r.deep = DeepCheck(ping0={"available": True, "risk_pct": risk})
        r.verdict = f"疑似真家宽·原生·风控{risk}%"
    else:
        r.verdict = "机房" if hosting else "住宅候选"
    return r


def _meta(run_id, ts):
    return {"run_id": run_id, "mode": "isolated", "controller": "test",
            "generated_at": ts}


def test_load_dashboard_empty():
    with tempfile.TemporaryDirectory() as td:
        db = os.path.join(td, "history.db")
        payload = load_dashboard(db)
        assert payload["nodes"] == []
        assert payload["kpis"]["nodes"] == 0


def test_load_dashboard_kpis_and_series():
    with tempfile.TemporaryDirectory() as td:
        db = os.path.join(td, "history.db")
        save_run(
            [_rep("家宽轮换", rtt=40, speed=50.0, run_ip="36.1.1.1",
                  run_ip6="2001:db8::1", risk=7),
             _rep("机房稳定", rtt=80, speed=90.0, hosting=True, run_ip="52.1.1.1")],
            _meta("run1", "2026-01-01T00:00:00"), db)
        save_run(
            [_rep("家宽轮换", rtt=90, speed=20.0, run_ip="36.2.2.2",
                  run_ip6="2001:db8::2", risk=18),
             _rep("机房稳定", rtt=81, speed=91.0, hosting=True, run_ip="52.1.1.1")],
            _meta("run2", "2026-01-02T00:00:00"), db)
        payload = load_dashboard(db)
        assert payload["meta"]["run_id"] == "run2"
        assert [r["id"] for r in payload["runs"]] == ["run1", "run2"]
        k = payload["kpis"]
        assert k["nodes"] == 2
        assert k["residential"] == 1
        assert k["datacenter"] == 1
        assert k["slow"] == 1
        assert k["ip_rotated"] == 1
        home = next(n for n in payload["nodes"] if n["name"] == "家宽轮换")
        assert home["degraded"] is True
        assert home["ip_rotated"] is True
        assert home["series"]["ip"] == ["36.1.1.1", "36.2.2.2"]
        assert home["series"]["ip6"] == ["2001:db8::1", "2001:db8::2"]
        assert home["series"]["risk"] == [7, 18]
        assert home["latest"]["exit_ip"] == "36.2.2.2"
        assert home["latest"]["exit_ip6"] == "2001:db8::2"
        assert home["latest"]["asn"] == "AS3462"
        assert home["latest"]["ptr"] == "36-227-213-17.hinet.net"
        assert home["latest"]["rdap_org"] == "Chunghwa Telecom"
        assert payload["nodes"][0]["degraded"] is True  # 变慢置顶
        assert home["in_latest"] is True


def test_switch_subscription_isolates_timeline():
    """换订阅后旧节点不进当前控制台（重叠 <90%）。"""
    with tempfile.TemporaryDirectory() as td:
        db = os.path.join(td, "history.db")
        save_run([_rep("旧机场-日本1", hosting=True, run_ip="1.1.1.1")],
                 _meta("run1", "2026-01-01T00:00:00"), db)
        save_run([_rep("新机场-香港1", run_ip="14.0.0.1", risk=4)],
                 _meta("run2", "2026-01-02T00:00:00"), db)
        payload = load_dashboard(db)
        names = {n["name"] for n in payload["nodes"]}
        assert names == {"新机场-香港1"}
        assert payload["kpis"]["nodes"] == 1
        assert payload["nodes"][0]["in_latest"] is True


def test_dashboard_html_landmarks_and_xss():
    payload = demo_payload()
    payload["nodes"][0]["name"] = "<script>alert(1)</script>"
    html = render_dashboard(payload)
    assert "id='na-app'" in html
    assert "id='na-data'" in html
    assert "demo-banner" in html
    assert "function spark" in html
    assert "spark-axis" in html
    assert "function fmtDay" in html
    assert "导出 CSV" in html
    assert "downloadCsv" in html
    assert "出口 v4" in html and "出口 v6" in html
    assert "<b>PTR</b>" in html and "<b>ASN</b>" in html
    assert "series.ip6" in html
    assert "<script>alert(1)</script>" not in html
    assert "\\u003cscript\\u003e" in html
    raw = html.split("id='na-data'>")[1].split("</script>")[0]
    data = json.loads(raw)
    assert data["nodes"][0]["name"] == "<script>alert(1)</script>"


def test_write_dashboard_file():
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "latest.html")
        write_dashboard(demo_payload(), path)
        text = open(path, encoding="utf-8").read()
        assert "node-audit" in text and "台湾家宽-1" in text
