"""Bing Webmaster Tools API connector (+ AI Performance CSV import).

API docs: https://learn.microsoft.com/en-us/bingwebmaster/getting-access
JSON endpoint: https://ssl.bing.com/webmaster/api.svc/json/<Method>?apikey=...&siteUrl=...

AI Performance report (Copilot / Bing AI citations, grounding queries, cited pages) exists in the
Webmaster Tools UI (public coverage dated 2026). No public API for it was found when this was built
(2026-10-12), so it is UNSUPPORTED_OR_UNAVAILABLE via API and ingested from the UI's spreadsheet export.
"""
from __future__ import annotations

import csv
import io

from .. import db
from .base import Connector, ConnectorError, REQUIRES_CREDENTIALS
from .ga4 import store_snapshot

BASE = "https://ssl.bing.com/webmaster/api.svc/json"


class BingConnector(Connector):
    name = "bing_webmaster"
    required_env = ("BING_WEBMASTER_API_KEY", "BING_SITE_URL")
    docs_url = "https://learn.microsoft.com/en-us/bingwebmaster/getting-access"

    def _call(self, method: str, **params):
        params = {"apikey": self.config.get("BING_WEBMASTER_API_KEY"), **params}
        resp = self.transport.request("GET", f"{BASE}/{method}", params=params)
        self.classify_http(resp, f"Bing {method}")
        data = resp.json() or {}
        return data.get("d", data)

    def _probe(self) -> str:
        sites = self._call("GetUserSites") or []
        urls = [s.get("Url") for s in sites if isinstance(s, dict)]
        target = self.config.get("BING_SITE_URL").rstrip("/")
        if not any((u or "").rstrip("/") == target for u in urls):
            raise ConnectorError("REQUIRES_PERMISSION", f"API key works but {target} is not a verified site on this account")
        return f"GetUserSites succeeded; {target} verified"

    def sync(self, start: str, end: str) -> int:
        if self.missing_env():
            raise ConnectorError(REQUIRES_CREDENTIALS, "Bing not configured")
        site = self.config.get("BING_SITE_URL")
        n = 0
        for method in ("GetQueryStats", "GetPageStats", "GetRankAndTrafficStats", "GetCrawlIssues"):
            n += store_snapshot(self.conn, "bing", method, start, end, ["site"], self._call(method, siteUrl=site))
        db.set_health(self.conn, self.name, "CONNECTED_AND_TESTED", f"synced {n} reports", success=True)
        return n


def import_ai_performance_csv(conn, text: str, period_start: str, period_end: str, report: str = "ai_cited_pages") -> int:
    """Import a spreadsheet exported from Bing WMT > AI Performance (cited pages or grounding queries tab)."""
    rows = list(csv.DictReader(io.StringIO(text.lstrip("﻿"))))
    if not rows:
        raise ValueError("Empty AI Performance export")
    n = store_snapshot(conn, "bing", report, period_start, period_end, list(rows[0].keys()), rows)
    # No API exists, so the status stays UNSUPPORTED via API; the import timestamp is tracked as last_success.
    db.set_health(conn, "bing_ai_performance", "UNSUPPORTED_OR_UNAVAILABLE",
                  f"No public API. Manual UI export imported: {len(rows)} rows ({period_start}..{period_end})", success=True)
    return len(rows)
