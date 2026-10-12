"""SQLite evidence store. Stdlib only; one file, append-friendly, de-duplicated by natural keys.

Every evidence-bearing row carries `kind` in {observed, computed, prediction, hypothesis}
so reports can never blur measured facts with guesses.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

EVIDENCE_KINDS = ("observed", "computed", "prediction", "hypothesis")

SCHEMA = """
CREATE TABLE IF NOT EXISTS prompts (
  id TEXT NOT NULL, version INTEGER NOT NULL, text TEXT NOT NULL, language TEXT NOT NULL,
  intent TEXT NOT NULL, source TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL, PRIMARY KEY (id, version)
);
CREATE TABLE IF NOT EXISTS visibility_observations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  dedup_key TEXT UNIQUE NOT NULL,
  prompt_id TEXT NOT NULL, prompt_version INTEGER NOT NULL, platform TEXT NOT NULL,
  observed_at TEXT NOT NULL, method TEXT NOT NULL,          -- manual_sample | api_proxy | official_export
  response_excerpt TEXT, brand_mentioned INTEGER NOT NULL, official_site_cited INTEGER NOT NULL,
  accuracy TEXT,                                              -- accurate | partially_accurate | inaccurate | not_applicable | unreviewed
  accuracy_notes TEXT, evidence_ref TEXT, observer TEXT, sample_note TEXT,
  kind TEXT NOT NULL DEFAULT 'observed', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS citations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  observation_id INTEGER NOT NULL REFERENCES visibility_observations(id),
  url TEXT NOT NULL, domain TEXT NOT NULL, is_official INTEGER NOT NULL, competitor_id TEXT,
  position INTEGER, UNIQUE (observation_id, url)
);
CREATE TABLE IF NOT EXISTS competitor_mentions (
  observation_id INTEGER NOT NULL REFERENCES visibility_observations(id),
  competitor_id TEXT NOT NULL, PRIMARY KEY (observation_id, competitor_id)
);
CREATE TABLE IF NOT EXISTS competitors (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, domains TEXT NOT NULL, status TEXT NOT NULL,
  data TEXT NOT NULL, sources TEXT NOT NULL, verified_at TEXT
);
CREATE TABLE IF NOT EXISTS audit_runs (
  id TEXT PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT, method TEXT NOT NULL,
  scope TEXT NOT NULL, status TEXT NOT NULL, notes TEXT
);
CREATE TABLE IF NOT EXISTS audit_findings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  dedup_key TEXT NOT NULL, run_id TEXT NOT NULL REFERENCES audit_runs(id),
  agent TEXT NOT NULL, category TEXT NOT NULL, severity TEXT NOT NULL,
  status TEXT NOT NULL,                        -- confirmed | hypothesis | unverified_fact | pass
  title TEXT NOT NULL, urls TEXT NOT NULL, evidence TEXT NOT NULL, recommendation TEXT,
  verification TEXT, observed_at TEXT NOT NULL, kind TEXT NOT NULL,
  UNIQUE (run_id, dedup_key)
);
CREATE TABLE IF NOT EXISTS facts (
  id TEXT PRIMARY KEY, claim TEXT NOT NULL, value TEXT NOT NULL, category TEXT NOT NULL,
  source TEXT NOT NULL, evidence TEXT NOT NULL, verified_at TEXT, confidence TEXT NOT NULL,
  public_approved INTEGER NOT NULL DEFAULT 0, revalidate_by TEXT, revalidate_condition TEXT,
  status TEXT NOT NULL, affected_urls TEXT NOT NULL DEFAULT '[]', updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS fact_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT, fact_id TEXT NOT NULL, old_value TEXT, new_value TEXT,
  changed_at TEXT NOT NULL, reason TEXT
);
CREATE TABLE IF NOT EXISTS fact_conflicts (
  id INTEGER PRIMARY KEY AUTOINCREMENT, dedup_key TEXT UNIQUE NOT NULL, topic TEXT NOT NULL,
  statements TEXT NOT NULL, status TEXT NOT NULL, resolution TEXT, detected_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS analytics_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL, report TEXT NOT NULL,
  window_start TEXT NOT NULL, window_end TEXT NOT NULL, dims_key TEXT NOT NULL,
  payload TEXT NOT NULL, payload_hash TEXT NOT NULL, fetched_at TEXT NOT NULL,
  UNIQUE (source, report, window_start, window_end, dims_key)
);
CREATE TABLE IF NOT EXISTS clarity_windows (
  id INTEGER PRIMARY KEY AUTOINCREMENT, fetched_at TEXT NOT NULL, num_days INTEGER NOT NULL,
  window_start TEXT NOT NULL, window_end TEXT NOT NULL, dims_key TEXT NOT NULL,
  payload_hash TEXT NOT NULL, overlaps_previous INTEGER NOT NULL,
  UNIQUE (window_start, window_end, dims_key)
);
CREATE TABLE IF NOT EXISTS recommendations (
  id TEXT PRIMARY KEY, title TEXT NOT NULL, agent TEXT NOT NULL, category TEXT NOT NULL,
  evidence TEXT NOT NULL, explanation TEXT, impact INTEGER NOT NULL, confidence INTEGER NOT NULL,
  effort INTEGER NOT NULL, risk INTEGER NOT NULL, priority REAL NOT NULL,
  requires_approval INTEGER NOT NULL, approval_reason TEXT, dependencies TEXT NOT NULL DEFAULT '[]',
  state TEXT NOT NULL, verification_plan TEXT, verification_result TEXT,
  evidence_hash TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS recommendation_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, rec_id TEXT NOT NULL, from_state TEXT, to_state TEXT NOT NULL,
  actor TEXT NOT NULL, note TEXT, at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS experiments (
  id TEXT PRIMARY KEY, data TEXT NOT NULL, status TEXT NOT NULL, result TEXT, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS integration_health (
  name TEXT PRIMARY KEY, status TEXT NOT NULL, detail TEXT, last_checked TEXT NOT NULL,
  last_success TEXT, last_error TEXT
);
CREATE TABLE IF NOT EXISTS task_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT, cadence TEXT NOT NULL, task TEXT NOT NULL,
  started_at TEXT NOT NULL, finished_at TEXT, status TEXT NOT NULL, detail TEXT, input_hash TEXT
);
CREATE TABLE IF NOT EXISTS reports (
  id INTEGER PRIMARY KEY AUTOINCREMENT, cadence TEXT NOT NULL, period_start TEXT NOT NULL,
  period_end TEXT NOT NULL, path TEXT NOT NULL, generated_at TEXT NOT NULL, summary TEXT
);
CREATE TABLE IF NOT EXISTS email_identities (
  account TEXT PRIMARY KEY, classification TEXT NOT NULL, evidence TEXT NOT NULL,
  confirmed_by TEXT, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS materials (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, availability TEXT NOT NULL, data TEXT NOT NULL,
  source TEXT NOT NULL, verified_at TEXT, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS print_jobs (
  id TEXT PRIMARY KEY, use_case TEXT, material TEXT, technology TEXT, model_traits TEXT,
  sliced_weight_g REAL, print_time_min REAL, issues TEXT, improvements TEXT, result TEXT,
  evidence_refs TEXT, publication_permission TEXT NOT NULL, confidentiality TEXT, recorded_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS orders (
  id TEXT PRIMARY KEY, created_at TEXT NOT NULL, revenue_egp REAL, material TEXT, weight_g REAL,
  print_time_min REAL, discount_egp REAL, shipping_egp REAL, refunded INTEGER, reprint INTEGER,
  channel TEXT, landing_page TEXT, customer_hash TEXT, source_file TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cost_assumptions (
  key TEXT PRIMARY KEY, value REAL NOT NULL, unit TEXT NOT NULL, source TEXT NOT NULL,
  verified INTEGER NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS approvals (
  id INTEGER PRIMARY KEY AUTOINCREMENT, action TEXT NOT NULL, target TEXT NOT NULL,
  approved_by TEXT NOT NULL, note TEXT, at TEXT NOT NULL
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def stable_hash(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def connect(path: Path | str) -> sqlite3.Connection:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


def rows(conn, sql: str, params=()) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def set_health(conn, name: str, status: str, detail: str = "", success: bool = False, error: str | None = None):
    ts = now_iso()
    prev = conn.execute("SELECT last_success, last_error FROM integration_health WHERE name=?", (name,)).fetchone()
    last_success = ts if success else (prev["last_success"] if prev else None)
    last_error = error if error is not None else (prev["last_error"] if prev else None)
    conn.execute(
        "INSERT INTO integration_health(name,status,detail,last_checked,last_success,last_error) VALUES(?,?,?,?,?,?) "
        "ON CONFLICT(name) DO UPDATE SET status=excluded.status, detail=excluded.detail, last_checked=excluded.last_checked, "
        "last_success=excluded.last_success, last_error=excluded.last_error",
        (name, status, detail, ts, last_success, last_error),
    )
    conn.commit()
