import os
import sqlite3
import tempfile
from datetime import datetime, timedelta

from node_audit.core.history import (
    SCHEMA_VERSION,
    _add_column_if_missing,
    connect,
    enrich_trend,
    load_trend,
    node_overlap,
    save_run,
)
from node_audit.core.models import DeepCheck, NodeReport
from node_audit.report.html import publish_latest, render_html, run_label, write_html


def _rep(name, rtt=50, speed=10.0, hosting=False, run_ip="36.227.213.17", run_ip6=None):
    r = NodeReport(name=name, node_type="AnyTLS")
    r.region_code, r.region_cn = "TW", "台湾"
    r.exit_ip = run_ip
    r.exit_ip6 = run_ip6
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
        assert a["cells"]["run2"]["exit_ip6"] is None
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


def test_trend_default_limit_is_30():
    with tempfile.TemporaryDirectory() as td:
        db = os.path.join(td, "history.db")
        base = datetime(2026, 1, 1)
        for i in range(35):
            ts = (base + timedelta(days=i)).isoformat(timespec="seconds")
            save_run([_rep("节点A", rtt=i)], _meta(f"run{i}", ts), db)
        runs, rows = load_trend(db)
        assert len(runs) == 30
        assert runs[0] == "run5" and runs[-1] == "run34"
        assert rows[0]["cells"]["run5"]["rtt"] == 5
        assert "run4" not in rows[0]["cells"]


def test_node_overlap_ratio():
    assert node_overlap(["a", "b", "c"], ["a", "b", "c"]) == 1.0
    assert node_overlap(["n%s" % i for i in range(10)],
                        ["n%s" % i for i in range(9)] + ["x"]) == 0.9
    assert node_overlap(["a"], ["b"]) == 0.0
    assert node_overlap([], ["a"]) == 0.0


def test_same_subscription_at_90_percent():
    with tempfile.TemporaryDirectory() as td:
        db = os.path.join(td, "history.db")
        old = [_rep(f"节点{i}") for i in range(10)]
        info1 = save_run(old, _meta("run1", "2026-01-01T00:00:00"), db)
        assert info1["same"] is False  # 首次
        new = [_rep(f"节点{i}") for i in range(9)] + [_rep("节点新")]
        info2 = save_run(new, _meta("run2", "2026-01-02T00:00:00"), db)
        assert info2["same"] is True
        assert info2["match"] == 0.9
        # 两次应共用 subscription_id
        conn = connect(db)
        try:
            ids = [r[0] for r in conn.execute(
                "SELECT subscription_id FROM runs ORDER BY created_at")]
        finally:
            conn.close()
        assert ids[0] == ids[1]


def test_new_subscription_below_90_percent():
    with tempfile.TemporaryDirectory() as td:
        db = os.path.join(td, "history.db")
        save_run([_rep(f"A-{i}") for i in range(10)],
                 _meta("run1", "2026-01-01T00:00:00"), db)
        info = save_run([_rep(f"B-{i}") for i in range(10)],
                        _meta("run2", "2026-01-02T00:00:00"), db)
        assert info["same"] is False
        assert info["match"] < 0.9
        runs, rows = load_trend(db)
        assert runs == ["run2"]  # 旧订阅的 run1 不进当前趋势
        assert all(r["node"].startswith("B-") for r in rows)


def test_return_to_previous_subscription():
    with tempfile.TemporaryDirectory() as td:
        db = os.path.join(td, "history.db")
        save_run([_rep(f"A-{i}") for i in range(10)],
                 _meta("run1", "2026-01-01T00:00:00"), db)
        save_run([_rep(f"B-{i}") for i in range(10)],
                 _meta("run2", "2026-01-02T00:00:00"), db)
        info = save_run([_rep(f"A-{i}") for i in range(10)],
                        _meta("run3", "2026-01-03T00:00:00"), db)
        assert info["same"] is True
        runs, rows = load_trend(db)
        assert runs == ["run1", "run3"]
        assert "run2" not in runs


def test_idempotent_same_run_id():
    with tempfile.TemporaryDirectory() as td:
        db = os.path.join(td, "history.db")
        meta = _meta("run1", "2026-01-01T00:00:00")
        save_run([_rep("节点A", rtt=1)], meta, db)
        save_run([_rep("节点A", rtt=2)], meta, db)  # 同 run_id 重写
        runs, rows = load_trend(db)
        assert runs == ["run1"]
        assert rows[0]["cells"]["run1"]["rtt"] == 2  # 以最后一次为准，不重复累积


def test_run_label_formats_timestamp_ids():
    assert run_label("20260908-041200") == "09-08 04:12"
    assert run_label("run1") == "run1"
    assert run_label("") == ""


def test_html_trend_headers_use_dates():
    with tempfile.TemporaryDirectory() as td:
        db = os.path.join(td, "history.db")
        rid = "20260908-041200"
        save_run([_rep("节点A")], _meta(rid, "2026-09-08T04:12:00"), db)
        html = render_html([_rep("节点A")], _meta(rid, "2026-09-08T04:12:00"), load_trend(db))
        assert "09-08 04:12" in html
        assert "<th>PTR</th>" in html


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
        assert "<th>PTR</th>" in html
        # 节点名中的 HTML 被转义，不能出现可执行的 <script>
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html
        # 判定着色（span 属性为单引号）
        assert "class='res'" in html and "class='dc'" in html


def test_history_saves_deep_check():
    """住宅节点带 deep 时必须能写入 history（DeepCheck.to_dict），否则没有 HTML。"""
    with tempfile.TemporaryDirectory() as td:
        db = os.path.join(td, "history.db")
        r = _rep("家宽节点")
        r.deep = DeepCheck(
            ping0={"available": True, "ip_type": "家庭宽带 IP",
                   "native": "原生 IP", "risk_pct": 7},
            scamalytics={"available": True, "score": 3, "datacenter": "No"},
        )
        r.verdict = "疑似真家宽·原生·风控7%"
        save_run([r], _meta("run1", "2026-01-01T00:00:00"), db)
        runs, rows = load_trend(db)
        assert runs == ["run1"]
        cell = rows[0]["cells"]["run1"]
        assert cell["risk_pct"] == 7
        assert cell["exit_ip"] == "36.227.213.17"
        conn = connect(db)
        try:
            deep_json = conn.execute(
                "SELECT deep FROM results WHERE node_name=?", ("家宽节点",)
            ).fetchone()[0]
        finally:
            conn.close()
        assert "风控" not in deep_json  # 原始字段在 ping0 里
        assert "risk_pct" in deep_json
        assert "家庭宽带" in deep_json


def test_schema_version_set_on_connect():
    with tempfile.TemporaryDirectory() as td:
        db = os.path.join(td, "history.db")
        conn = connect(db)
        try:
            assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        finally:
            conn.close()


def test_schema_migrates_legacy_user_version_0():
    with tempfile.TemporaryDirectory() as td:
        db = os.path.join(td, "history.db")
        raw = sqlite3.connect(db)
        raw.execute(
            "CREATE TABLE runs(run_id TEXT PRIMARY KEY, mode TEXT, "
            "controller TEXT, created_at TEXT)"
        )
        raw.execute("PRAGMA user_version = 0")
        raw.commit()
        raw.close()
        conn = connect(db)
        try:
            assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
            run_cols = {r[1] for r in conn.execute("PRAGMA table_info(runs)")}
            assert "subscription_id" in run_cols
            cols = {r[1] for r in conn.execute("PRAGMA table_info(results)")}
            assert "risk_pct" in cols and "deep" in cols
            assert "exit_ip6" in cols
            _add_column_if_missing(conn, "results", "foo_extra", "TEXT")
            _add_column_if_missing(conn, "results", "foo_extra", "TEXT")
            cols2 = {r[1] for r in conn.execute("PRAGMA table_info(results)")}
            assert "foo_extra" in cols2
        finally:
            conn.close()


def test_enrich_trend_ip_change_risk_delta_and_slow_sort():
    runs = ["run1", "run2"]
    rows = [
        {"node": "稳定节点", "cells": {
            "run1": {"rtt": 50, "speed": 20.0, "verdict": "机房",
                     "exit_ip": "1.1.1.1", "risk_pct": 5},
            "run2": {"rtt": 55, "speed": 19.0, "verdict": "机房",
                     "exit_ip": "1.1.1.1", "risk_pct": 4},
        }},
        {"node": "家宽轮换且变慢", "cells": {
            "run1": {"rtt": 40, "speed": 50.0, "verdict": "疑似真家宽",
                     "exit_ip": "36.1.1.1", "risk_pct": 7},
            "run2": {"rtt": 90, "speed": 20.0, "verdict": "疑似真家宽",
                     "exit_ip": "36.2.2.2", "risk_pct": 18},
        }},
    ]
    out = enrich_trend(runs, rows)
    assert [r["node"] for r in out] == ["家宽轮换且变慢", "稳定节点"]
    slow = out[0]["cells"]["run2"]
    assert out[0]["degraded"] is True
    assert slow["ip_changed"] is True
    assert slow["risk_delta"] == 11
    assert slow["rtt_delta"] == 50
    assert slow["speed_delta"] == -30.0
    assert slow["slow"] is True  # 速度掉 60% 且 RTT 翻倍有余
    stable = out[1]["cells"]["run2"]
    assert out[1]["degraded"] is False
    assert stable["ip_changed"] is False
    assert stable["risk_delta"] == -1
    assert stable["slow"] is False


def test_schema_v3_adds_exit_ip6_from_v2():
    with tempfile.TemporaryDirectory() as td:
        db = os.path.join(td, "history.db")
        raw = sqlite3.connect(db)
        raw.executescript(
            "CREATE TABLE runs(run_id TEXT PRIMARY KEY, mode TEXT, "
            "controller TEXT, created_at TEXT, subscription_id TEXT);\n"
            "CREATE TABLE results(id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "run_id TEXT, node_name TEXT, exit_ip TEXT, created_at TEXT);\n"
            "PRAGMA user_version = 2;"
        )
        raw.commit()
        raw.close()
        conn = connect(db)
        try:
            assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
            cols = {r[1] for r in conn.execute("PRAGMA table_info(results)")}
            assert "exit_ip6" in cols
        finally:
            conn.close()


def test_history_roundtrip_exit_ip6():
    with tempfile.TemporaryDirectory() as td:
        db = os.path.join(td, "history.db")
        save_run([_rep("双栈", run_ip="1.1.1.1", run_ip6="2001:db8::1")],
                 _meta("run1", "2026-01-01T00:00:00"), db)
        runs, rows = load_trend(db)
        assert rows[0]["cells"]["run1"]["exit_ip6"] == "2001:db8::1"


def test_enrich_trend_v6_change_counts_as_ip_changed():
    runs = ["a", "b"]
    rows = [{"node": "双栈", "cells": {
        "a": {"rtt": 40, "speed": 10.0, "verdict": "机房",
              "exit_ip": "1.1.1.1", "exit_ip6": "2001:db8::1", "risk_pct": None},
        "b": {"rtt": 40, "speed": 10.0, "verdict": "机房",
              "exit_ip": "1.1.1.1", "exit_ip6": "2001:db8::2", "risk_pct": None},
    }}]
    out = enrich_trend(runs, rows)
    cell = out[0]["cells"]["b"]
    assert cell["ip_changed"] is True
    assert cell["ip4_changed"] is False
    assert cell["ip6_changed"] is True


def test_enrich_trend_rtt_double_alone_marks_slow():
    runs = ["a", "b"]
    rows = [{"node": "延迟翻倍", "cells": {
        "a": {"rtt": 80, "speed": 10.0, "verdict": "机房", "exit_ip": "8.8.8.8", "risk_pct": None},
        "b": {"rtt": 160, "speed": 10.0, "verdict": "机房", "exit_ip": "8.8.8.8", "risk_pct": None},
    }}]
    out = enrich_trend(runs, rows)
    assert out[0]["degraded"] is True
    assert out[0]["cells"]["b"]["slow"] is True


def test_html_trend_semantics_and_latest_copy():
    with tempfile.TemporaryDirectory() as td:
        db = os.path.join(td, "history.db")
        r1 = _rep("家宽节点", rtt=40, speed=50.0, run_ip="36.1.1.1")
        r1.deep = DeepCheck(ping0={"available": True, "risk_pct": 7})
        save_run([r1], _meta("run1", "2026-01-01T00:00:00"), db)
        r2 = _rep("家宽节点", rtt=90, speed=20.0, run_ip="36.2.2.2")
        r2.deep = DeepCheck(ping0={"available": True, "risk_pct": 18})
        save_run([r2], _meta("run2", "2026-01-02T00:00:00"), db)
        trend = load_trend(db)
        html = render_html([r2], _meta("run2", "2026-01-02T00:00:00"), trend)
        assert "换" in html
        assert "class='degraded'" in html
        assert "风控 18%" in html
        assert "class='chg'" in html
        hpath = os.path.join(td, "audit-run2.html")
        write_html([r2], _meta("run2", "2026-01-02T00:00:00"), hpath, trend)
        latest = publish_latest(hpath)
        assert latest.name == "latest.html"
        assert latest.read_text(encoding="utf-8") == open(hpath, encoding="utf-8").read()
