import json
import unittest
from datetime import datetime, timezone

from helpers import FakeTransport, make_config, mem_db

from geo.connectors.base import (CONNECTED_AND_TESTED, FAILED_WITH_EVIDENCE, REQUIRES_CREDENTIALS,
                                 REQUIRES_PERMISSION, ConnectorError)
from geo.connectors.bing import BingConnector, import_ai_performance_csv
from geo.connectors.clarity import ClarityConnector, LOCAL_DAILY_BUDGET, record_window
from geo.connectors.ga4 import GA4Connector
from geo.connectors.gsc import GSCConnector, brand_class

GA = "https://analyticsdata.googleapis.com/v1beta/properties/123"


class TestGA4(unittest.TestCase):
    def setUp(self):
        self.conn = mem_db()
        self.cfg = make_config(GA4_PROPERTY_ID="123", GOOGLE_ACCESS_TOKEN="ya29.secret-token-value")

    def test_missing_credentials_reported_not_simulated(self):
        c = GA4Connector(make_config(), self.conn, FakeTransport())
        status, detail = c.test()
        self.assertEqual(status, REQUIRES_CREDENTIALS)
        self.assertEqual(c.transport.calls, [], "no request may be made without credentials")
        row = self.conn.execute("SELECT status, last_success FROM integration_health WHERE name='ga4'").fetchone()
        self.assertEqual(row["status"], REQUIRES_CREDENTIALS)
        self.assertIsNone(row["last_success"])

    def test_success_parses_rows_and_stores_snapshot(self):
        body = {"rows": [{"dimensionValues": [{"value": "20261001"}, {"value": "/pricing"}],
                          "metricValues": [{"value": "12"}, {"value": "7"}, {"value": "1"}, {"value": "0"}]}]}
        t = FakeTransport().add("POST", GA + ":runReport", 200, body)
        c = GA4Connector(self.cfg, self.conn, t)
        self.assertEqual(c.test()[0], CONNECTED_AND_TESTED)
        n = c.sync("2026-10-01", "2026-10-07")
        self.assertEqual(n, 5)
        snap = self.conn.execute("SELECT payload FROM analytics_snapshots WHERE report='landing_pages'").fetchone()
        self.assertEqual(json.loads(snap["payload"])[0]["sessions"], 12)
        self.assertEqual(c.sync("2026-10-01", "2026-10-07"), 0, "identical re-sync must not duplicate")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) c FROM analytics_snapshots").fetchone()["c"], 5)

    def test_401_and_403_are_classified_and_secret_redacted(self):
        t = FakeTransport().add("POST", GA + ":runReport", 401, {"error": "bad token ya29.secret-token-value"})
        status, detail = GA4Connector(self.cfg, self.conn, t).test()
        self.assertEqual(status, REQUIRES_CREDENTIALS)
        self.assertNotIn("secret-token-value", detail)
        t = FakeTransport().add("POST", GA + ":runReport", 403, {"error": "no access"})
        self.assertEqual(GA4Connector(self.cfg, self.conn, t).test()[0], REQUIRES_PERMISSION)

    def test_network_error_is_failed_with_evidence(self):
        t = FakeTransport(default=OSError("Tunnel connection failed: 403"))
        status, detail = GA4Connector(self.cfg, self.conn, t).test()
        self.assertEqual(status, FAILED_WITH_EVIDENCE)
        self.assertIn("Tunnel", detail)


class TestGSC(unittest.TestCase):
    def test_paging_and_brand_classes(self):
        conn = mem_db()
        cfg = make_config(GSC_SITE_URL="sc-domain:mujassam.net", GOOGLE_ACCESS_TOKEN="ya29.tok-123456")
        page = lambda n, q: {"rows": [{"keys": [q], "clicks": 1, "impressions": 10, "ctr": 0.1, "position": 3}] * n}
        t = FakeTransport()
        calls = {"n": 0}

        def req(method, url, headers=None, params=None, json_body=None, **k):
            calls["n"] += 1
            from geo.connectors.base import HttpResponse
            rows = page(2, "mujassam") if json_body["startRow"] == 0 else page(1, "مجسم")
            return HttpResponse(200, json.dumps(rows).encode())
        t.request = req
        rows = GSCConnector(cfg, conn, t).query("2026-10-01", "2026-10-07", ["query"], row_limit=2)
        self.assertEqual(len(rows), 3)
        self.assertEqual(calls["n"], 2)
        self.assertEqual(rows[0]["brand_class"], "branded")
        self.assertEqual(rows[2]["brand_class"], "ambiguous")
        self.assertEqual(brand_class("طباعة مجسمات ثلاثية الابعاد"), "non_branded")


class TestClarity(unittest.TestCase):
    def setUp(self):
        self.conn = mem_db()
        self.cfg = make_config(CLARITY_API_TOKEN="clarity-token-abcdef")

    def test_parameters_validated(self):
        c = ClarityConnector(self.cfg, self.conn, FakeTransport())
        with self.assertRaises(ValueError):
            c.fetch(7)
        with self.assertRaises(ValueError):
            c.fetch(1, ("URL", "Device", "OS", "Browser"))
        with self.assertRaises(ValueError):
            c.fetch(1, ("Landing",))

    def test_sync_respects_budget_and_records_windows(self):
        body = [{"metricName": "Traffic", "information": [{"totalSessionCount": "10", "URL": "https://mujassam.net/"}]}]
        t = FakeTransport().add("GET", "https://www.clarity.ms/export-data/api/v1/project-live-insights", 200, body)
        c = ClarityConnector(self.cfg, self.conn, t)
        self.assertGreater(c.sync(), 0)
        for _ in range(10):
            try:
                c.fetch(1, ("OS",))
            except ConnectorError as e:
                self.assertIn("budget", e.detail)
                break
        self.assertLessEqual(len(t.calls), LOCAL_DAILY_BUDGET)
        self.assertEqual(t.calls[0]["headers"]["Authorization"], "Bearer clarity-token-abcdef")

    def test_overlapping_windows_flagged_and_duplicates_ignored(self):
        t0 = datetime(2026, 10, 10, 6, tzinfo=timezone.utc)
        t1 = datetime(2026, 10, 10, 18, tzinfo=timezone.utc)
        self.assertEqual(record_window(self.conn, t0, 1, ("URL",), [{"metricName": "Traffic", "information": []}]), 1)
        self.assertEqual(record_window(self.conn, t0, 1, ("URL",), [{"metricName": "Traffic", "information": []}]), 0)
        record_window(self.conn, t1, 1, ("URL",), [{"metricName": "Traffic", "information": [{"x": "1"}]}])
        flags = [r["overlaps_previous"] for r in self.conn.execute("SELECT overlaps_previous FROM clarity_windows ORDER BY id")]
        self.assertEqual(flags, [0, 1])

    def test_429_is_failure(self):
        t = FakeTransport().add("GET", "https://www.clarity.ms", 429, {"message": "Exceeded daily limit"})
        self.assertEqual(ClarityConnector(self.cfg, self.conn, t).test()[0], FAILED_WITH_EVIDENCE)


class TestBing(unittest.TestCase):
    def test_site_not_verified_is_permission_problem(self):
        cfg = make_config(BING_WEBMASTER_API_KEY="bingkey123456", BING_SITE_URL="https://mujassam.net/")
        t = FakeTransport().add("GET", "https://ssl.bing.com/webmaster/api.svc/json/GetUserSites", 200, {"d": [{"Url": "https://other.com/"}]})
        self.assertEqual(BingConnector(cfg, mem_db(), t).test()[0], REQUIRES_PERMISSION)
        self.assertNotIn("bingkey123456", json.dumps(t.calls[0]["headers"]))

    def test_ai_performance_csv_import(self):
        conn = mem_db()
        n = import_ai_performance_csv(conn, "﻿Page,Citations\nhttps://mujassam.net/pricing,4\n", "2026-09-01", "2026-09-30")
        self.assertEqual(n, 1)
        h = conn.execute("SELECT status, last_success FROM integration_health WHERE name='bing_ai_performance'").fetchone()
        self.assertEqual(h["status"], "UNSUPPORTED_OR_UNAVAILABLE")
        self.assertIsNotNone(h["last_success"])


if __name__ == "__main__":
    unittest.main()
