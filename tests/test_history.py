import os
import tempfile

from node_audit.core.history import load_trend, save_run
from node_audit.core.models import NodeReport
from node_audit.report.html import render_html


def _rep(name, rtt=50, speed=10.0, hosting=False, run_ip="36.227.213.17"):
    r = NodeReport(name=name, node_type="AnyTLS")
    r.region_code, r.region_cn = "TW", "台湾"
    r.exit_ip = run_ip
    r.country_code, r.country, r.city = "TW", "Taiwan", "Taipei"
    r.isp, r.asn = "Chunghwa Telecom", "AS3462"
    r.hosting = hosting
    r.rtt = {"gstatic": rtt, "cloudflare": rtt}
    r.rtt_min = rtt
    r.speed_mbps = speed
    r.speed_bytes = 2_000_000
    r.speed_seconds = 2.0
    r.verdict = "疑似真家宽·原生·风控7%"
    return r


def _meta(run_id, ts):
    return {"run_id": run_id, "mode": "isolated", "controller": "test",
            "generated_at": ts}


def test_history_roundtrip():
    with tempfile.TemporaryDirectory() as td:
        db = os.path.join(td, "history.db")
        save_run([_rep("节点A"), _rep("节点B", rtt=80, hosting=True)],
                 _meta("run1", "2026-01-01T00:00:00"), db)
        save_run([_rep("节点A", rtt=60, speed=20.0, run_ip="36.227.999.999")],
                 _meta("run2", "2026-01-02T00:00:00"), db)
        runs, rows = load_trend(db)
        assert runs == ["run1", "run2"]
        a = next(r for r in rows if r["node"] == "节点A")
        assert a["cells"]["run1"]["rtt"] == 50
        assert a["cells"]["run2"]["rtt"] == 60
        assert a["cells"]["run2"]["speed"] == 20.0
        # 家宽 IP 轮换在趋势里直接可见
        assert a["cells"]["run2"]["exit_ip"] == "36.227.999.999"
        # run2 没测节点B
        b = next(r for r in rows if r["node"] == "节点B")
        assert "run2" not in b["cells"]


def test_trend_limit_orders_old_to_new():
    with tempfile.TemporaryDirectory() as td:
        db = os.path.join(td, "history.db")
        for i, ts in enumerate(["2026-01-01", "2026-01-02", "2026-01-03"], 1):
            save_run([_rep("节点A", rtt=i)], _meta(f"run{i}", ts), db)
        runs, rows = load_trend(db, runs_limit=2)
        assert runs == ["run2", "run3"]
        a = rows[0]
        assert "run1" not in a["cells"]
        assert a["cells"]["run2"]["rtt"] == 2


def test_idempotent_same_run_id():
    with tempfile.TemporaryDirectory() as td:
        db = os.path.join(td, "history.db")
        meta = _meta("run1", "2026-01-01T00:00:00")
        save_run([_rep("节点A", rtt=1)], meta, db)
        save_run([_rep("节点A", rtt=2)], meta, db)  # 同 run_id 重写
        runs, rows = load_trend(db)
        assert runs == ["run1"]
        assert rows[0]["cells"]["run1"]["rtt"] == 2  # 以最后一次为准，不重复累积


def test_html_renders_and_escapes():
    with tempfile.TemporaryDirectory() as td:
        db = os.path.join(td, "history.db")
        evil = "<script>alert(1)</script>"
        reports = [_rep(evil, rtt=55), _rep("节点B", rtt=80, hosting=True)]
        save_run(reports, _meta("run1", "2026-01-01T00:00:00"), db)
        trend = load_trend(db)
        html = render_html(reports, _meta("run1", "2026-01-01T00:00:00"), trend)
        assert "本次明细" in html and "历史趋势（含本次）" in html
        assert "run1" in html
        # 节点名中的 HTML 被转义，不能出现可执行的 <script>
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html
        # 判定着色（span 属性为单引号）
        assert "class='res'" in html and "class='dc'" in html
