"""SQLite 历史趋势存储（v0.4）。

每次审计落一行 run + 每节点一行 result，供 HTML 报告生成跨次趋势视图。
标准库 sqlite3，单文件存放在报告输出目录（默认 node-audit-report/history.db）。
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs(
  run_id TEXT PRIMARY KEY,
  mode TEXT,
  controller TEXT,
  created_at TEXT
);
CREATE TABLE IF NOT EXISTS results(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT,
  node_name TEXT,
  node_type TEXT,
  exit_ip TEXT,
  country_code TEXT,
  city TEXT,
  isp TEXT,
  asn TEXT,
  hosting INTEGER,
  ptr TEXT,
  rdap_org TEXT,
  rtt_min INTEGER,
  rtt_gstatic INTEGER,
  rtt_cloudflare INTEGER,
  speed_mbps REAL,
  speed_partial INTEGER,
  geo_match TEXT,
  rtt_suspect INTEGER,
  risk_pct INTEGER,
  scam_score INTEGER,
  verdict TEXT,
  notes TEXT,
  services TEXT,
  deep TEXT,
  error TEXT,
  created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_results_node ON results(node_name, created_at);
CREATE INDEX IF NOT EXISTS idx_results_run ON results(run_id);
"""


def connect(db_path) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.executescript(_SCHEMA)
    return conn


def save_run(reports, meta: dict, db_path) -> None:
    """写入一次审计（run 行 + 每节点 result 行）。重复 run_id 会整体替换。"""
    conn = connect(db_path)
    try:
        with conn:
            conn.execute(
                "INSERT OR REPLACE INTO runs(run_id, mode, controller, created_at) VALUES(?,?,?,?)",
                (meta["run_id"], meta.get("mode"), meta.get("controller"), meta["generated_at"]),
            )
            conn.execute("DELETE FROM results WHERE run_id=?", (meta["run_id"],))
            for r in reports:
                p0 = (r.deep.ping0 if r.deep else None) or {}
                sc = (r.deep.scamalytics if r.deep else None) or {}
                conn.execute(
                    """INSERT INTO results(
                       run_id, node_name, node_type, exit_ip, country_code, city,
                       isp, asn, hosting, ptr, rdap_org,
                       rtt_min, rtt_gstatic, rtt_cloudflare,
                       speed_mbps, speed_partial, geo_match, rtt_suspect,
                       risk_pct, scam_score, verdict, notes, services, deep, error, created_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        meta["run_id"], r.name, r.node_type, r.exit_ip,
                        r.country_code, r.city, r.isp, r.asn,
                        None if r.hosting is None else int(r.hosting),
                        r.ptr, r.rdap_org,
                        r.rtt_min, r.rtt.get("gstatic"), r.rtt.get("cloudflare"),
                        r.speed_mbps, int(bool(r.speed_partial)),
                        r.geo_match, None if r.rtt_suspect is None else int(r.rtt_suspect),
                        p0.get("risk_pct"), sc.get("score"),
                        r.verdict, json.dumps(r.notes, ensure_ascii=False),
                        json.dumps(r.services, ensure_ascii=False),
                        json.dumps(r.deep.to_dict() if r.deep else None, ensure_ascii=False),
                        r.error, meta["generated_at"],
                    ),
                )
    finally:
        conn.close()


def load_trend(db_path, runs_limit: int = 10):
    """取最近 runs_limit 次审计的跨次数据。

    返回 (runs, rows)：
      runs = [run_id, ...] 按时间从旧到新；
      rows = [{"node": 节点名,
               "cells": {run_id: {"rtt": int|None, "speed": float|None,
                                  "verdict": str, "exit_ip": str}}}]
    """
    conn = connect(db_path)
    try:
        runs = [row[0] for row in conn.execute(
            "SELECT run_id FROM runs ORDER BY created_at DESC, rowid DESC LIMIT ?",
            (runs_limit,),
        )][::-1]
        if not runs:
            return [], []
        marks = ",".join("?" * len(runs))
        rows_map: dict[str, dict] = {}
        for row in conn.execute(
            f"""SELECT node_name, run_id, rtt_min, speed_mbps, verdict, exit_ip
                FROM results WHERE run_id IN ({marks})""",
            runs,
        ):
            name, run_id, rtt, speed, verdict, exit_ip = row
            rows_map.setdefault(name, {"node": name, "cells": {}})
            rows_map[name]["cells"][run_id] = {
                "rtt": rtt, "speed": speed, "verdict": verdict, "exit_ip": exit_ip,
            }
        rows = sorted(rows_map.values(), key=lambda x: x["node"])
        return runs, rows
    finally:
        conn.close()
