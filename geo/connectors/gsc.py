"""Google Search Console API connector.

Docs: https://developers.google.com/webmaster-tools/v1/searchanalytics/query
Search Analytics: POST https://www.googleapis.com/webmasters/v3/sites/{siteUrl}/searchAnalytics/query
URL Inspection:   POST https://searchconsole.googleapis.com/v1/urlInspection/index:inspect
Data lags ~2-3 days; rowLimit max 25000 per request (paged with startRow).
"""
from __future__ import annotations

import urllib.parse

from .. import db
from .base import Connector, ConnectorError, REQUIRES_CREDENTIALS
from .ga4 import store_snapshot
from .google_auth import GSC_SCOPE, get_access_token, has_google_credentials

LATIN_BRAND = ("mujassam", "mujasam", "mogasam", "megasam", "mogassam")
# Arabic "مجسم" is a generic noun (3D model / figurine), so it alone is "ambiguous", not branded.
ARABIC_BRAND_QUALIFIED = ("موقع مجسم", "منصه مجسم", "منصة مجسم", "مجسم نت", "مجسم دوت نت")


def brand_class(query: str) -> str:
    q = (query or "").lower().replace("ّ", "")
    if any(t in q for t in LATIN_BRAND) or any(t in q for t in ARABIC_BRAND_QUALIFIED):
        return "branded"
    if "مجسم" in q and len(q.split()) <= 2:
        return "ambiguous"
    return "non_branded"


def is_branded(query: str) -> bool:
    return brand_class(query) == "branded"


class GSCConnector(Connector):
    name = "search_console"
    required_env = ("GSC_SITE_URL",)
    docs_url = "https://developers.google.com/webmaster-tools/v1/searchanalytics/query"

    def missing_env(self):
        missing = super().missing_env()
        if not has_google_credentials(self.config):
            missing.append("GOOGLE_APPLICATION_CREDENTIALS|GOOGLE_ACCESS_TOKEN")
        return missing

    def _headers(self):
        return {"Authorization": f"Bearer {get_access_token(self.config, GSC_SCOPE)}"}

    def _site(self):
        return urllib.parse.quote(self.config.get("GSC_SITE_URL"), safe="")

    def _probe(self) -> str:
        resp = self.transport.request("GET", f"https://www.googleapis.com/webmasters/v3/sites/{self._site()}",
                                      headers=self._headers())
        self.classify_http(resp, "GSC sites.get")
        level = (resp.json() or {}).get("permissionLevel", "unknown")
        return f"sites.get succeeded; permissionLevel={level}"

    def query(self, start: str, end: str, dimensions: list[str], row_limit: int = 25000, max_rows: int = 100000) -> list[dict]:
        out, start_row = [], 0
        while start_row < max_rows:
            body = {"startDate": start, "endDate": end, "dimensions": dimensions,
                    "rowLimit": row_limit, "startRow": start_row, "dataState": "final"}
            resp = self.transport.request("POST", f"https://www.googleapis.com/webmasters/v3/sites/{self._site()}/searchAnalytics/query",
                                          headers=self._headers(), json_body=body)
            self.classify_http(resp, "GSC searchAnalytics.query")
            batch = (resp.json() or {}).get("rows", []) or []
            for r in batch:
                rec = dict(zip(dimensions, r.get("keys", [])))
                rec.update({k: r.get(k) for k in ("clicks", "impressions", "ctr", "position")})
                if "query" in rec:
                    rec["brand_class"] = brand_class(rec["query"])
                out.append(rec)
            if len(batch) < row_limit:
                break
            start_row += row_limit
        return out

    def inspect_url(self, url: str) -> dict:
        resp = self.transport.request("POST", "https://searchconsole.googleapis.com/v1/urlInspection/index:inspect",
                                      headers=self._headers(),
                                      json_body={"inspectionUrl": url, "siteUrl": self.config.get("GSC_SITE_URL")})
        self.classify_http(resp, "GSC urlInspection")
        return (resp.json() or {}).get("inspectionResult", {})

    def sync(self, start: str, end: str) -> int:
        if self.missing_env():
            raise ConnectorError(REQUIRES_CREDENTIALS, "Search Console not configured")
        n = 0
        for report, dims in {"queries": ["date", "query"], "pages": ["date", "page"],
                             "query_page": ["query", "page"], "devices": ["date", "device"],
                             "countries": ["date", "country"]}.items():
            n += store_snapshot(self.conn, "gsc", report, start, end, dims, self.query(start, end, dims))
        db.set_health(self.conn, self.name, "CONNECTED_AND_TESTED", f"synced {start}..{end}", success=True)
        return n
