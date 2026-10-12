"""Google Analytics 4 Data API (v1beta) connector.

Docs: https://developers.google.com/analytics/devguides/reporting/data/v1
Endpoint: POST https://analyticsdata.googleapis.com/v1beta/properties/{id}:runReport
Metadata: GET  https://analyticsdata.googleapis.com/v1beta/properties/{id}/metadata  (used to inspect real event config)
"""
from __future__ import annotations

from .. import db
from .base import Connector, ConnectorError, REQUIRES_CREDENTIALS
from .google_auth import GA4_SCOPE, get_access_token, has_google_credentials

BASE = "https://analyticsdata.googleapis.com/v1beta"

# Reports collected on each sync. Event names are NOT assumed to mean orders; see event_inventory().
REPORTS = {
    "landing_pages": {"dimensions": ["date", "landingPagePlusQueryString"],
                      "metrics": ["sessions", "engagedSessions", "keyEvents", "totalRevenue"]},
    "acquisition": {"dimensions": ["date", "sessionSource", "sessionMedium", "sessionCampaignName"],
                    "metrics": ["sessions", "engagedSessions", "keyEvents", "totalRevenue"]},
    "devices": {"dimensions": ["date", "deviceCategory"], "metrics": ["sessions", "engagementRate", "keyEvents"]},
    "geo": {"dimensions": ["date", "region"], "metrics": ["sessions", "keyEvents"]},
    "events": {"dimensions": ["date", "eventName", "isKeyEvent"], "metrics": ["eventCount", "totalUsers"]},
}


class GA4Connector(Connector):
    name = "ga4"
    required_env = ("GA4_PROPERTY_ID",)
    docs_url = "https://developers.google.com/analytics/devguides/reporting/data/v1"

    def missing_env(self):
        missing = super().missing_env()
        if not has_google_credentials(self.config):
            missing.append("GOOGLE_APPLICATION_CREDENTIALS|GOOGLE_ACCESS_TOKEN")
        return missing

    def _headers(self):
        return {"Authorization": f"Bearer {get_access_token(self.config, GA4_SCOPE)}"}

    def _prop(self):
        return f"properties/{self.config.get('GA4_PROPERTY_ID')}"

    def _probe(self) -> str:
        resp = self.transport.request("POST", f"{BASE}/{self._prop()}:runReport", headers=self._headers(),
                                      json_body={"dateRanges": [{"startDate": "yesterday", "endDate": "yesterday"}],
                                                 "metrics": [{"name": "sessions"}], "limit": 1})
        self.classify_http(resp, "GA4 runReport")
        return "runReport succeeded for yesterday (sessions)."

    def run_report(self, start: str, end: str, dimensions: list[str], metrics: list[str], limit: int = 10000) -> list[dict]:
        body = {"dateRanges": [{"startDate": start, "endDate": end}],
                "dimensions": [{"name": d} for d in dimensions], "metrics": [{"name": m} for m in metrics],
                "limit": limit}
        resp = self.transport.request("POST", f"{BASE}/{self._prop()}:runReport", headers=self._headers(), json_body=body)
        self.classify_http(resp, "GA4 runReport")
        data = resp.json() or {}
        out = []
        for r in data.get("rows", []) or []:
            rec = {d: v.get("value") for d, v in zip(dimensions, r.get("dimensionValues", []))}
            rec.update({m: _num(v.get("value")) for m, v in zip(metrics, r.get("metricValues", []))})
            out.append(rec)
        return out

    def event_inventory(self) -> dict:
        """Real event/key-event configuration so analysts do not guess what an event means."""
        resp = self.transport.request("GET", f"{BASE}/{self._prop()}/metadata", headers=self._headers())
        self.classify_http(resp, "GA4 metadata")
        meta = resp.json() or {}
        return {"metrics": [m.get("apiName") for m in meta.get("metrics", [])],
                "custom_dimensions": [d.get("apiName") for d in meta.get("dimensions", []) if d.get("customDefinition")]}

    def sync(self, start: str, end: str) -> int:
        if self.missing_env():
            raise ConnectorError(REQUIRES_CREDENTIALS, "GA4 not configured")
        n = 0
        for report, spec in REPORTS.items():
            data = self.run_report(start, end, spec["dimensions"], spec["metrics"])
            n += store_snapshot(self.conn, "ga4", report, start, end, spec["dimensions"], data)
        db.set_health(self.conn, self.name, "CONNECTED_AND_TESTED", f"synced {start}..{end}", success=True)
        return n


def _num(v):
    try:
        f = float(v)
        return int(f) if f.is_integer() else f
    except (TypeError, ValueError):
        return v


def store_snapshot(conn, source, report, start, end, dims, payload) -> int:
    """Insert-or-replace one snapshot per (source, report, window, dims). Returns 1 if new/changed, 0 if identical."""
    dims_key = ",".join(dims)
    h = db.stable_hash(payload)
    prev = conn.execute("SELECT payload_hash FROM analytics_snapshots WHERE source=? AND report=? AND window_start=? "
                        "AND window_end=? AND dims_key=?", (source, report, start, end, dims_key)).fetchone()
    if prev and prev["payload_hash"] == h:
        return 0
    import json
    conn.execute("INSERT INTO analytics_snapshots(source,report,window_start,window_end,dims_key,payload,payload_hash,fetched_at) "
                 "VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(source,report,window_start,window_end,dims_key) DO UPDATE SET "
                 "payload=excluded.payload, payload_hash=excluded.payload_hash, fetched_at=excluded.fetched_at",
                 (source, report, start, end, dims_key, json.dumps(payload, ensure_ascii=False), h, db.now_iso()))
    conn.commit()
    return 1
