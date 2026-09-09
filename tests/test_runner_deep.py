from types import SimpleNamespace

from node_audit.core import runner as r
from node_audit.core.models import NodeReport


def _opts(**kw):
    ns = SimpleNamespace(
        deep="auto",
        services=[],
        skip_speed=True,
        delay_fn=lambda name: {"gstatic": 20},
        ipqs_key=None,
        abuseipdb_key=None,
        speed_bytes=1,
        heavy_speed_bytes=1,
        speed_max_seconds=1,
    )
    for k, v in kw.items():
        setattr(ns, k, v)
    return ns


def test_dc_auto_runs_ippure_skips_ping0():
    orig = {
        k: getattr(r, k)
        for k in (
            "check_identity", "check_ippure", "check_ping0", "check_iplark",
            "check_scamalytics", "check_ptr", "check_rdap",
        )
    }
    calls = []

    def ident(_proxy):
        return {
            "query": "1.1.1.1", "query6": None, "country": "JP", "countryCode": "JP",
            "city": "Tokyo", "isp": "Amazon", "org": "Amazon", "as": "AS16509",
            "asname": "AMAZON", "hosting": True, "proxy": False,
        }

    r.check_identity = ident
    r.check_ippure = lambda p: calls.append("ippure") or {"available": True, "fraud_score": 31}
    r.check_ping0 = lambda *a, **k: calls.append("ping0") or {}
    r.check_iplark = lambda *a, **k: calls.append("iplark") or {}
    r.check_scamalytics = lambda *a, **k: calls.append("scam") or {}
    r.check_ptr = lambda *a, **k: None
    r.check_rdap = lambda *a, **k: None
    try:
        logs = []
        rep = r._audit_one("日本专线", "ss", "http://127.0.0.1:1", _opts(), log=logs.append)
        assert "ippure" in calls
        assert "ping0" not in calls
        assert "iplark" not in calls
        assert "scam" not in calls
        assert isinstance(rep, NodeReport)
        assert "风控31%" in rep.verdict
        assert any("机房仅 IPPure" in x for x in logs)
    finally:
        for k, v in orig.items():
            setattr(r, k, v)
