"""Data access layer. SQLite for prototype; swap to BigQuery for scale."""
import os
import re
import sqlite3
import datetime as dt

DB_PATH = os.environ.get("JANSETU_DB", os.path.join(os.path.dirname(__file__), "..", "jansetu.db"))

SCHEMA_DOC = """Table: wards
  ward TEXT PRIMARY KEY, lat REAL, lng REAL, population INTEGER,
  sc_st_pct REAL (percent SC/ST population), schools INTEGER, phcs INTEGER

Table: mplads_funds
  year TEXT ('2026-27'), allocated_lakh REAL, sanctioned_lakh REAL,
  spent_lakh REAL, sc_st_spent_lakh REAL  -- amounts in Rs lakh

Table: grievances
  id INTEGER PRIMARY KEY
  created_date TEXT (YYYY-MM-DD)
  ward TEXT
  category TEXT  -- 'Water Supply','Drainage & Sewage','Roads & Potholes','Streetlights','Garbage Collection','Electricity','Public Health','Stray Animals','Encroachment','Public Transport'
  department TEXT -- 'Jal Board','Municipal Corporation','PWD','Electricity Board','District Health Office','Transport Dept'
  description TEXT
  severity TEXT  -- 'low','medium','high'
  source TEXT    -- 'phone','walk-in','app-photo','app-voice','letter'
  status TEXT    -- 'open','in_progress','resolved'
  resolved_date TEXT or NULL
  upvotes INTEGER
  lat REAL, lng REAL
Tables can be JOINed on ward. SQLite dialect. Use date('now', '-30 days') style date arithmetic."""

_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|attach|detach|pragma|replace|"
    r"vacuum|reindex|analyze|begin|commit|rollback|savepoint|load_extension)\b", re.I)


def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ---- Optional BigQuery backend for the NL->SQL analytics path ----
# Activate with: USE_BIGQUERY=1 BQ_PROJECT=<project> BQ_DATASET=jansetu
# (after loading data with scripts/load_bigquery.py). Falls back to SQLite
# automatically if the client or query fails — same graceful-degradation
# philosophy as the AI layer.
USE_BIGQUERY = os.environ.get("USE_BIGQUERY", "") == "1"
BQ_PROJECT = os.environ.get("BQ_PROJECT", "")
BQ_DATASET = os.environ.get("BQ_DATASET", "jansetu")
_bq_client = None
if USE_BIGQUERY and BQ_PROJECT:
    try:
        from google.cloud import bigquery as _bigquery
        _bq_client = _bigquery.Client(project=BQ_PROJECT)
    except Exception:
        _bq_client = None


def _validate(sql):
    stripped = sql.strip().rstrip(";")
    if not stripped.lower().startswith(("select", "with")):
        raise ValueError("Only SELECT queries are allowed")
    if _FORBIDDEN.search(stripped):
        raise ValueError("Query contains forbidden keywords")
    if ";" in stripped:
        raise ValueError("Multiple statements not allowed")
    return stripped


def _bq_run(stripped, limit):
    """Run on BigQuery, mapping bare table names to the dataset."""
    for t in ("grievances", "wards", "mplads_funds"):
        stripped = re.sub(rf"\b{t}\b", f"`{BQ_PROJECT}.{BQ_DATASET}.{t}`", stripped)
    rows = [dict(r) for r in _bq_client.query(stripped).result(max_results=limit)]
    cols = list(rows[0].keys()) if rows else []
    return cols, rows


def run_query(sql, limit=200):
    stripped = _validate(sql)
    if _bq_client is not None:
        try:
            return _bq_run(stripped, limit)
        except Exception:
            pass  # fall back to SQLite below
    conn = _conn()
    try:
        cur = conn.execute(stripped)
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchmany(limit)]
        return cols, rows
    finally:
        conn.close()


def insert_grievance(ward, category, department, description, severity, source, lat=None, lng=None):
    conn = _conn()
    try:
        if lat is None:
            w = conn.execute("SELECT lat, lng FROM wards WHERE ward=?", (ward,)).fetchone()
            if w:
                lat, lng = w["lat"], w["lng"]
        cur = conn.execute(
            """INSERT INTO grievances (created_date, ward, category, department,
               description, severity, source, status, resolved_date, upvotes, lat, lng)
               VALUES (?,?,?,?,?,?,?,'open',NULL,0,?,?)""",
            (dt.date.today().isoformat(), ward, category, department, description,
             severity, source, lat, lng))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def hotspots(days=60):
    conn = _conn()
    try:
        wards = [dict(r) for r in conn.execute(f"""
            SELECT w.ward, w.lat, w.lng, w.population, w.sc_st_pct, w.schools, w.phcs,
                   COUNT(g.id) AS open_count,
                   SUM(CASE WHEN g.severity='high' THEN 1 ELSE 0 END) AS high_count,
                   (SELECT category FROM grievances g2 WHERE g2.ward=w.ward
                    AND g2.status!='resolved' GROUP BY category
                    ORDER BY COUNT(*) DESC LIMIT 1) AS top_category
            FROM wards w LEFT JOIN grievances g
              ON g.ward=w.ward AND g.status!='resolved'
              AND g.created_date >= date('now','-{days} days')
            GROUP BY w.ward""").fetchall()]
        points = [dict(r) for r in conn.execute(f"""
            SELECT lat, lng, category, severity FROM grievances
            WHERE status!='resolved' AND created_date >= date('now','-{days} days')
              AND lat IS NOT NULL LIMIT 1500""").fetchall()]
        return {"wards": wards, "points": points}
    finally:
        conn.close()


def fund_status():
    conn = _conn()
    try:
        years = [dict(r) for r in conn.execute("SELECT * FROM mplads_funds ORDER BY year").fetchall()]
        cur = years[-1] if years else {}
        unspent = round(cur.get("allocated_lakh", 0) - cur.get("spent_lakh", 0), 1)
        spent = cur.get("spent_lakh", 0) or 1
        sc_st_pct_of_spend = round(100.0 * cur.get("sc_st_spent_lakh", 0) / spent, 1)
        # Corrective amount: extra SC/ST-area spend needed to reach 22.5% of
        # the full-year allocation (the practical target for compliance).
        alloc = cur.get("allocated_lakh", 0)
        sc_st_gap_lakh = round(max(0.0, 0.225 * alloc - cur.get("sc_st_spent_lakh", 0)), 1)
        return {"years": years, "current_year": cur.get("year"),
                "unspent_lakh": unspent,
                "unsanctioned_lakh": round(cur.get("allocated_lakh", 0) - cur.get("sanctioned_lakh", 0), 1),
                "sc_st_pct_of_spend": sc_st_pct_of_spend,
                "sc_st_mandate_pct": 22.5,
                "sc_st_compliant": sc_st_pct_of_spend >= 22.5,
                "sc_st_gap_lakh": sc_st_gap_lakh,
                "sc_st_wards": [dict(r) for r in conn.execute(
                    "SELECT ward, sc_st_pct, population FROM wards WHERE sc_st_pct >= 25 ORDER BY sc_st_pct DESC").fetchall()]}
    finally:
        conn.close()


def detect_anomalies(window_days=21, baseline_days=180, z_threshold=2.5):
    conn = _conn()
    try:
        rows = conn.execute(f"""
            WITH recent AS (
              SELECT ward, category, COUNT(*)*1.0/{window_days} AS rate
              FROM grievances WHERE created_date >= date('now','-{window_days} days')
              GROUP BY ward, category),
            base AS (
              SELECT ward, category, COUNT(*)*1.0/{baseline_days} AS rate
              FROM grievances
              WHERE created_date < date('now','-{window_days} days')
                AND created_date >= date('now','-{baseline_days + window_days} days')
              GROUP BY ward, category)
            SELECT r.ward, r.category, r.rate AS recent_rate,
                   MAX(COALESCE(b.rate, 0.05), 0.05) AS base_rate,
                   r.rate / MAX(COALESCE(b.rate, 0.05), 0.05) AS ratio
            FROM recent r LEFT JOIN base b USING (ward, category)
            WHERE r.rate / MAX(COALESCE(b.rate, 0.05), 0.05) >= {z_threshold}
              AND r.rate * {window_days} >= 8
            ORDER BY ratio DESC LIMIT 10""").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def summary_stats():
    conn = _conn()
    try:
        q = lambda sql: [dict(r) for r in conn.execute(sql).fetchall()]
        return {
            "total_open": conn.execute("SELECT COUNT(*) FROM grievances WHERE status!='resolved'").fetchone()[0],
            "last_30_days": conn.execute("SELECT COUNT(*) FROM grievances WHERE created_date>=date('now','-30 days')").fetchone()[0],
            "by_category": q("""SELECT category, COUNT(*) AS n FROM grievances
                                WHERE created_date>=date('now','-30 days') GROUP BY 1 ORDER BY 2 DESC"""),
            "by_ward": q("""SELECT ward, COUNT(*) AS n FROM grievances
                            WHERE status!='resolved' GROUP BY 1 ORDER BY 2 DESC"""),
            "trend": q("""SELECT strftime('%Y-%m', created_date) AS month, COUNT(*) AS n
                          FROM grievances WHERE created_date>=date('now','-365 days')
                          GROUP BY 1 ORDER BY 1"""),
            "dept_performance": q("""SELECT department,
                          ROUND(AVG(julianday(resolved_date)-julianday(created_date)),1) AS avg_days,
                          COUNT(*) AS resolved FROM grievances WHERE status='resolved'
                          AND created_date>=date('now','-180 days') GROUP BY 1 ORDER BY 2"""),
        }
    finally:
        conn.close()
