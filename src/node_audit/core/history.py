"""SQLite 历史趋势存储（v0.4 + v0.5 迁移 / 趋势语义 / 订阅隔离）。

每次审计落一行 run + 每节点一行 result，供 HTML 报告生成跨次趋势视图。
标准库 sqlite3，单文件存放在报告输出目录（默认 node-audit-report/history.db）。

schema 用 PRAGMA user_version 编号；旧库打开时按版本逐级 ALTER，
不要依赖 CREATE TABLE IF NOT EXISTS 去加列。

订阅判定：本次节点名集合 vs 各已知订阅「最近一次」节点名集合，
重叠率 = |交集| / min(|本次|, |对方|) ≥ 0.9 → 同一订阅，否则新开时间轴。
换回旧机场时会重新对上原来的 subscription_id。
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path

# 每次改表结构 +1，并在 _MIGRATIONS 里追加对应步骤
SCHEMA_VERSION = 2

# 相对上次：速度下降 ≥ 此比例，或 RTT 翻倍 → 整行标红置顶
SPEED_DROP_THRESHOLD = 0.4
RTT_RISE_MULT = 2.0
# 节点名重叠达到该比例视为同一订阅（换机场会低于此值）
SAME_SUBSCRIPTION_THRESHOLD = 0.9

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs(
  run_id TEXT PRIMARY KEY,
  mode TEXT,
  controller TEXT,
  created_at TEXT,
  subscription_id TEXT
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


def _migrate_v2(conn: sqlite3.Connection) -> None:
    _add_column_if_missing(conn, "runs", "subscription_id", "TEXT")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_runs_sub ON runs(subscription_id, created_at)"
    )
    conn.execute(
        "UPDATE runs SET subscription_id='sub-legacy' "
        "WHERE subscription_id IS NULL OR subscription_id=''"
    )


# version -> list of SQL statements (or callables taking conn).
# v1 即当前建表结果；以后加列写 v2、v3…，用 _add_column_if_missing 以免旧库炸。
_MIGRATIONS: dict[int, list] = {
    1: [],
    2: [_migrate_v2],
}


def _existing_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _add_column_if_missing(conn: sqlite3.Connection, table: str, name: str, decl: str) -> None:
    if name not in _existing_columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")


def _migrate(conn: sqlite3.Connection) -> None:
    """把库升到 SCHEMA_VERSION。user_version=0 视为「建表后尚未编号」的旧库。"""
    ver = conn.execute("PRAGMA user_version").fetchone()[0]
    if ver > SCHEMA_VERSION:
        return
    for target in range(ver + 1, SCHEMA_VERSION + 1):
        for step in _MIGRATIONS.get(target, []):
            if callable(step):
                step(conn)
            else:
                conn.execute(step)
    if ver != SCHEMA_VERSION:
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


def connect(db_path) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.executescript(_SCHEMA)
    _migrate(conn)
    return conn


def node_overlap(a, b) -> float:
    """节点名重叠率：|交集| / min(|A|, |B|)。任一方为空则为 0。"""
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / min(len(sa), len(sb))


def _new_sub_id() -> str:
    return "sub-" + uuid.uuid4().hex[:10]


def resolve_subscription(conn: sqlite3.Connection, names, exclude_run_id: str | None = None,
                         threshold: float = SAME_SUBSCRIPTION_THRESHOLD) -> tuple[str, dict]:
    """把本次节点集合对上已知订阅；达不到阈值则新开一条。

    每个 subscription_id 用它「最近一次」（不含 exclude_run_id）的节点名做代表。
    换回旧机场时能重新对上原来的 id。
    """
    names = set(names)
    info = {"same": False, "match": 0.0, "overlap": 0, "prev_count": 0, "current_count": len(names)}
    if not names:
        return _new_sub_id(), info

    rows = conn.execute(
        "SELECT subscription_id, run_id FROM runs "
        "WHERE subscription_id IS NOT NULL AND subscription_id != '' "
        "ORDER BY created_at DESC, rowid DESC"
    ).fetchall()
    seen: set[str] = set()
    best_id, best_ratio, best_overlap, best_prev = None, -1.0, 0, 0
    for sid, run_id in rows:
        if not sid or sid in seen:
            continue
        if exclude_run_id and run_id == exclude_run_id:
            continue
        seen.add(sid)
        prev = {
            r[0] for r in conn.execute(
                "SELECT DISTINCT node_name FROM results WHERE run_id=?", (run_id,)
            )
        }
        if not prev:
            continue
        overlap = len(names & prev)
        ratio = overlap / min(len(names), len(prev))
        if ratio > best_ratio:
            best_id, best_ratio, best_overlap, best_prev = sid, ratio, overlap, len(prev)

    info["match"] = max(best_ratio, 0.0)
    info["overlap"] = best_overlap
    info["prev_count"] = best_prev
    if best_id is not None and best_ratio >= threshold:
        info["same"] = True
        return best_id, info
    return _new_sub_id(), info


def save_run(reports, meta: dict, db_path) -> dict:
    """写入一次审计。重复 run_id 会整体替换。

    返回订阅判定 dict，并写入 meta["subscription_id"] / meta["subscription"]。
    """
    names = {r.name for r in reports}
    conn = connect(db_path)
    try:
        with conn:
            existing = conn.execute(
                "SELECT subscription_id FROM runs WHERE run_id=?", (meta["run_id"],)
            ).fetchone()
            if existing and existing[0]:
                sid = existing[0]
                info = {
                    "same": True, "match": 1.0,
                    "overlap": len(names), "prev_count": len(names),
                    "current_count": len(names),
                }
            else:
                sid, info = resolve_subscription(
                    conn, names, exclude_run_id=meta.get("run_id")
                )
            meta["subscription_id"] = sid
            meta["subscription"] = info
            conn.execute(
                "INSERT OR REPLACE INTO runs(run_id, mode, controller, created_at, subscription_id) "
                "VALUES(?,?,?,?,?)",
                (meta["run_id"], meta.get("mode"), meta.get("controller"),
                 meta["generated_at"], sid),
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
        return info
    finally:
        conn.close()


def _current_subscription_id(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        "SELECT subscription_id FROM runs ORDER BY created_at DESC, rowid DESC LIMIT 1"
    ).fetchone()
    return row[0] if row and row[0] else None


def _recent_run_ids(conn: sqlite3.Connection, runs_limit: int,
                    subscription_id: str | None) -> list[str]:
    if subscription_id:
        rows = conn.execute(
            "SELECT run_id FROM runs WHERE subscription_id=? "
            "ORDER BY created_at DESC, rowid DESC LIMIT ?",
            (subscription_id, runs_limit),
        )
    else:
        rows = conn.execute(
            "SELECT run_id FROM runs ORDER BY created_at DESC, rowid DESC LIMIT ?",
            (runs_limit,),
        )
    return [r[0] for r in rows][::-1]


def load_trend(db_path, runs_limit: int = 30, subscription_id: str | None = None):
    """取最近 runs_limit 次审计的跨次数据（默认 30，约一个月每日）。

    默认只看当前订阅（最近一次 run 所属）。换机场后旧订阅的 run 不会进趋势。

    返回 (runs, rows)：
      runs = [run_id, ...] 按时间从旧到新；
      rows = [{"node": 节点名,
               "cells": {run_id: {"rtt", "speed", "verdict", "exit_ip", "risk_pct"}}}]
    比较语义（换 IP / Δ / 变慢置顶）由 enrich_trend 附加，不在这里算。
    """
    conn = connect(db_path)
    try:
        if subscription_id is None:
            subscription_id = _current_subscription_id(conn)
        runs = _recent_run_ids(conn, runs_limit, subscription_id)
        if not runs:
            return [], []
        marks = ",".join("?" * len(runs))
        rows_map: dict[str, dict] = {}
        for row in conn.execute(
            f"""SELECT node_name, run_id, rtt_min, speed_mbps, verdict, exit_ip, risk_pct
                FROM results WHERE run_id IN ({marks})""",
            runs,
        ):
            name, run_id, rtt, speed, verdict, exit_ip, risk_pct = row
            rows_map.setdefault(name, {"node": name, "cells": {}})
            rows_map[name]["cells"][run_id] = {
                "rtt": rtt, "speed": speed, "verdict": verdict,
                "exit_ip": exit_ip, "risk_pct": risk_pct,
            }
        rows = sorted(rows_map.values(), key=lambda x: x["node"])
        return runs, rows
    finally:
        conn.close()


def enrich_trend(runs: list, rows: list,
                 speed_drop: float = SPEED_DROP_THRESHOLD,
                 rtt_mult: float = RTT_RISE_MULT) -> list:
    """给每个格子补相对上次的变化，变慢节点整行 degraded=True 并排到最前。

    每个 cell 增加：ip_changed, risk_delta, rtt_delta, speed_delta, slow。
    不修改传入的 cells 字典（复制后再写）。
    """
    enriched = []
    for row in rows:
        new_cells: dict = {}
        prev = None
        last_slow = False
        for run_id in runs:
            src = row["cells"].get(run_id)
            if not src:
                continue
            cell = dict(src)
            cell["ip_changed"] = False
            cell["risk_delta"] = None
            cell["rtt_delta"] = None
            cell["speed_delta"] = None
            cell["slow"] = False
            if prev:
                cur_ip, prev_ip = cell.get("exit_ip"), prev.get("exit_ip")
                if cur_ip and prev_ip and cur_ip != prev_ip:
                    cell["ip_changed"] = True
                if cell.get("risk_pct") is not None and prev.get("risk_pct") is not None:
                    cell["risk_delta"] = cell["risk_pct"] - prev["risk_pct"]
                if cell.get("rtt") is not None and prev.get("rtt") is not None:
                    cell["rtt_delta"] = cell["rtt"] - prev["rtt"]
                if cell.get("speed") is not None and prev.get("speed") is not None:
                    cell["speed_delta"] = round(cell["speed"] - prev["speed"], 1)
                slow = False
                prev_speed, cur_speed = prev.get("speed"), cell.get("speed")
                if prev_speed and cur_speed is not None and prev_speed > 0:
                    if cur_speed <= prev_speed * (1 - speed_drop):
                        slow = True
                prev_rtt, cur_rtt = prev.get("rtt"), cell.get("rtt")
                if prev_rtt and cur_rtt is not None and prev_rtt > 0:
                    if cur_rtt >= prev_rtt * rtt_mult:
                        slow = True
                cell["slow"] = slow
                last_slow = slow
            new_cells[run_id] = cell
            prev = cell
        enriched.append({
            "node": row["node"],
            "cells": new_cells,
            "degraded": last_slow,
        })
    enriched.sort(key=lambda r: (not r["degraded"], r["node"]))
    return enriched


def _empty_dashboard() -> dict:
    return {
        "meta": {"run_id": "", "generated_at": "", "controller": "", "mode": ""},
        "kpis": {"nodes": 0, "ok": 0, "residential": 0, "datacenter": 0,
                 "slow": 0, "ip_rotated": 0, "failed": 0},
        "runs": [],
        "nodes": [],
    }


def _parse_json(s, default):
    if not s:
        return default
    try:
        return json.loads(s)
    except (TypeError, json.JSONDecodeError):
        return default


def load_dashboard(db_path, runs_limit: int = 30) -> dict:
    """控制台用的完整 payload：KPI + 历次 runs + 每节点 latest/series。"""
    from .filters import region_from_name

    conn = connect(db_path)
    try:
        sub_id = _current_subscription_id(conn)
        if sub_id:
            run_rows = conn.execute(
                "SELECT run_id, mode, controller, created_at, subscription_id FROM runs "
                "WHERE subscription_id=? ORDER BY created_at DESC, rowid DESC LIMIT ?",
                (sub_id, runs_limit),
            ).fetchall()[::-1]
        else:
            run_rows = conn.execute(
                "SELECT run_id, mode, controller, created_at, subscription_id FROM runs "
                "ORDER BY created_at DESC, rowid DESC LIMIT ?",
                (runs_limit,),
            ).fetchall()[::-1]
        if not run_rows:
            return _empty_dashboard()
        runs = [{"id": r[0], "at": r[3]} for r in run_rows]
        run_ids = [r["id"] for r in runs]
        last = run_rows[-1]
        meta = {
            "run_id": last[0],
            "mode": last[1] or "",
            "controller": last[2] or "",
            "generated_at": last[3] or "",
            "subscription_id": last[4] or "",
        }
        marks = ",".join("?" * len(run_ids))
        result_rows = conn.execute(
            f"""SELECT node_name, run_id, rtt_min, speed_mbps, verdict, exit_ip,
                       risk_pct, country_code, city, isp, hosting, geo_match,
                       services, notes, error, node_type
                FROM results WHERE run_id IN ({marks})""",
            run_ids,
        ).fetchall()
    finally:
        conn.close()

    by_node: dict[str, dict] = {}
    trend_rows_map: dict[str, dict] = {}
    for row in result_rows:
        (name, run_id, rtt, speed, verdict, exit_ip, risk_pct,
         cc, city, isp, hosting, geo_match, services, notes, error, ntype) = row
        trend_rows_map.setdefault(name, {"node": name, "cells": {}})
        trend_rows_map[name]["cells"][run_id] = {
            "rtt": rtt, "speed": speed, "verdict": verdict,
            "exit_ip": exit_ip, "risk_pct": risk_pct,
        }
        snaps = by_node.setdefault(name, {})
        hosting_b = None if hosting is None else bool(hosting)
        snaps[run_id] = {
            "exit_ip": exit_ip,
            "country": cc,
            "city": city,
            "isp": isp,
            "rtt": rtt,
            "speed": speed,
            "risk_pct": risk_pct,
            "hosting": hosting_b,
            "geo_match": geo_match,
            "services": _parse_json(services, {}),
            "notes": _parse_json(notes, []),
            "error": error,
            "verdict": verdict or "",
            "node_type": ntype or "",
        }

    enriched = enrich_trend(run_ids, list(trend_rows_map.values()))
    nodes = []
    for row in enriched:
        name = row["node"]
        snaps = by_node.get(name, {})
        series = {"rtt": [], "speed": [], "risk": [], "ip": []}
        latest = None
        latest_id = None
        for rid in run_ids:
            snap = snaps.get(rid)
            series["rtt"].append(None if not snap else snap.get("rtt"))
            series["speed"].append(None if not snap else snap.get("speed"))
            series["risk"].append(None if not snap else snap.get("risk_pct"))
            series["ip"].append(None if not snap else snap.get("exit_ip"))
            if snap:
                latest = snap
                latest_id = rid
        cell = row["cells"].get(latest_id or "", {})
        ip_rotated = bool(cell.get("ip_changed"))
        _, region = region_from_name(name)
        in_latest_run = run_ids[-1] in snaps
        nodes.append({
            "name": name,
            "region": region or "",
            "verdict": (latest or {}).get("verdict") or "",
            "degraded": bool(row.get("degraded")),
            "ip_rotated": ip_rotated,
            "in_latest": in_latest_run,
            "latest": latest or {},
            "series": series,
        })

    latest_id = run_ids[-1]
    in_latest = [n for n in nodes if n.get("in_latest")]
    nodes.sort(key=lambda n: (not n.get("in_latest"), not n.get("degraded"), n["name"]))

    def _is_res(n):
        h = (n.get("latest") or {}).get("hosting")
        if h is False:
            return True
        return "家宽" in (n.get("verdict") or "")

    def _is_dc(n):
        h = (n.get("latest") or {}).get("hosting")
        v = n.get("verdict") or ""
        if h is True:
            return True
        return "机房" in v or "IDC" in v

    pool = in_latest or nodes
    kpis = {
        "nodes": len(pool),
        "ok": sum(1 for n in pool if not (n.get("latest") or {}).get("error")),
        "residential": sum(1 for n in pool if _is_res(n)),
        "datacenter": sum(1 for n in pool if _is_dc(n)),
        "slow": sum(1 for n in pool if n.get("degraded")),
        "ip_rotated": sum(1 for n in pool if n.get("ip_rotated")),
        "failed": sum(1 for n in pool if (n.get("latest") or {}).get("error")),
    }
    return {"meta": meta, "kpis": kpis, "runs": runs, "nodes": nodes}
