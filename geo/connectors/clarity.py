"""Microsoft Clarity Data Export API connector.

Docs (verified 2026-10-12): https://learn.microsoft.com/en-us/clarity/clarity-data-export-api
GET https://www.clarity.ms/export-data/api/v1/project-live-insights
  Authorization: Bearer <token>; numOfDays in {1,2,3}; up to 3 dimensions;
  10 requests / project / day; max 1000 rows, no pagination; UTC.

Consequences implemented here:
  * History cannot be backfilled beyond 72h -> we collect daily (numOfDays=1) and persist every window.
  * A local daily request budget (default 6 of 10) leaves headroom for manual runs.
  * Overlapping windows are detected and flagged so totals are never double-counted.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .. import db
from .base import Connector, ConnectorError, FAILED_WITH_EVIDENCE, REQUIRES_CREDENTIALS
from .ga4 import store_snapshot

ENDPOINT = "https://www.clarity.ms/export-data/api/v1/project-live-insights"
VALID_DIMENSIONS = {"Browser", "Device", "Country/Region", "OS", "Source", "Medium", "Campaign", "Channel", "URL"}
DAILY_PLAN = [("URL",), ("Device",), ("Channel",), ("URL", "Device")]
API_DAILY_LIMIT = 10
LOCAL_DAILY_BUDGET = 6


class ClarityConnector(Connector):
    name = "clarity"
    required_env = ("CLARITY_API_TOKEN",)
    docs_url = "https://learn.microsoft.com/en-us/clarity/clarity-data-export-api"

    def _headers(self):
        return {"Authorization": f"Bearer {self.config.get('CLARITY_API_TOKEN')}", "Content-Type": "application/json"}

    def requests_used_today(self) -> int:
        if self.conn is None:
            return 0
        today = datetime.now(timezone.utc).date().isoformat()
        r = self.conn.execute("SELECT COUNT(*) c FROM task_runs WHERE task='clarity_request' AND started_at LIKE ?",
                              (today + "%",)).fetchone()
        return r["c"]

    def _count_request(self, status: str, detail: str):
        if self.conn is not None:
            ts = db.now_iso()
            self.conn.execute("INSERT INTO task_runs(cadence,task,started_at,finished_at,status,detail) VALUES(?,?,?,?,?,?)",
                              ("adhoc", "clarity_request", ts, ts, status, detail))
            self.conn.commit()

    def fetch(self, num_days: int = 1, dimensions: tuple[str, ...] = ()) -> list:
        if num_days not in (1, 2, 3):
            raise ValueError("Clarity numOfDays must be 1, 2 or 3")
        if len(dimensions) > 3 or any(d not in VALID_DIMENSIONS for d in dimensions):
            raise ValueError(f"Invalid Clarity dimensions: {dimensions}")
        if self.requests_used_today() >= LOCAL_DAILY_BUDGET:
            raise ConnectorError(FAILED_WITH_EVIDENCE, f"Local Clarity budget of {LOCAL_DAILY_BUDGET}/day reached "
                                                       f"(API hard limit {API_DAILY_LIMIT}); skipped to protect quota")
        params = {"numOfDays": str(num_days)}
        for i, d in enumerate(dimensions, 1):
            params[f"dimension{i}"] = d
        resp = self.transport.request("GET", ENDPOINT, headers=self._headers(), params=params)
        self._count_request(str(resp.status), ",".join(dimensions))
        self.classify_http(resp, "Clarity project-live-insights")
        data = resp.json()
        if not isinstance(data, list):
            raise ConnectorError(FAILED_WITH_EVIDENCE, f"Unexpected Clarity response shape: {type(data).__name__}")
        return data

    def _probe(self) -> str:
        data = self.fetch(1, ())
        return f"project-live-insights succeeded; {len(data)} metric groups returned"

    def sync(self) -> int:
        if self.missing_env():
            raise ConnectorError(REQUIRES_CREDENTIALS, "Clarity not configured")
        fetched_at = datetime.now(timezone.utc).replace(microsecond=0)
        n = 0
        for dims in DAILY_PLAN:
            if self.requests_used_today() >= LOCAL_DAILY_BUDGET:
                break
            data = self.fetch(1, dims)
            n += record_window(self.conn, fetched_at, 1, dims, data)
        db.set_health(self.conn, self.name, "CONNECTED_AND_TESTED", f"synced {n} windows", success=True)
        return n


def record_window(conn, fetched_at: datetime, num_days: int, dims, data) -> int:
    start = (fetched_at - timedelta(days=num_days)).isoformat()
    end = fetched_at.isoformat()
    dims_key = ",".join(dims) or "none"
    prev = conn.execute("SELECT window_end FROM clarity_windows WHERE dims_key=? ORDER BY window_end DESC LIMIT 1",
                        (dims_key,)).fetchone()
    overlaps = 1 if prev and prev["window_end"] > start else 0
    h = db.stable_hash(data)
    cur = conn.execute("INSERT OR IGNORE INTO clarity_windows(fetched_at,num_days,window_start,window_end,dims_key,payload_hash,overlaps_previous) "
                       "VALUES(?,?,?,?,?,?,?)", (end, num_days, start, end, dims_key, h, overlaps))
    conn.commit()
    if cur.rowcount == 0:
        return 0
    store_snapshot(conn, "clarity", "live_insights", start, end, list(dims) or ["none"], data)
    return 1


def flatten_metrics(data: list) -> dict:
    """{metricName: [information rows]} with numeric strings converted."""
    out = {}
    for group in data or []:
        rows = []
        for info in group.get("information", []) or []:
            rows.append({k: _num(v) for k, v in info.items()})
        out[group.get("metricName", "unknown")] = rows
    return out


def _num(v):
    if isinstance(v, str):
        try:
            f = float(v)
            return int(f) if f.is_integer() else f
        except ValueError:
            return v
    return v
