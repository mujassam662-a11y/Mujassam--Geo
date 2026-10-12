import json
import re
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from helpers import FakeTransport, make_config, mem_db, tmpdir

from geo import analysis, backlog, dashboard, db, email_identity, registry, reports, safety
from geo.config import redact
from geo.connectors.ai_visibility import brand_mentioned, import_observations
from geo.connectors.business_data import import_orders
from geo.connectors.crawler import SiteCrawler, analyze_crawl, parse_html, robots_matrix
from geo.orchestrator import Orchestrator

ROOT = Path(__file__).resolve().parent.parent

HOME = """<!doctype html><html lang="ar" dir="rtl"><head><title>مجسّم — طباعة</title>
<meta name="description" content="وصف"><link rel="canonical" href="https://mujassam.net/">
<script type="application/ld+json">{"@context":"https://schema.org","@type":"Organization","name":"مجسّم"}</script>
<script>var x=1;</script></head><body><h1>حوّل فكرتك</h1><p>""" + "نص " * 200 + """</p>
<a href="/pricing">الأسعار</a><a href="https://wa.me/1">wa</a><img src="a.png"></body></html>"""
PRICING = """<html lang="ar" dir="rtl"><head><title>الأسعار</title></head><body><h1>الأسعار</h1><h1>تاني</h1><p>قصير</p></body></html>"""
ROBOTS = "User-agent: *\nAllow: /\nDisallow: /admin\n\nUser-agent: GPTBot\nCrawl-delay: 2\n\nUser-agent: Bytespider\nDisallow: /\nSitemap: https://mujassam.net/sitemap.xml\n"
SITEMAP = """<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://mujassam.net/</loc></url>
<url><loc>https://mujassam.net/pricing</loc></url><url><loc>https://mujassam.net/orphan</loc></url></urlset>"""


def site_transport():
    t = FakeTransport()
    t.add("GET", "https://mujassam.net/robots.txt", 200, ROBOTS)
    t.add("GET", "https://mujassam.net/sitemap.xml", 200, SITEMAP)
    t.add("GET", "https://mujassam.net/pricing", 200, PRICING, {"content-type": "text/html; charset=utf-8"})
    t.add("GET", "https://mujassam.net/orphan", 404, "nope", {"content-type": "text/html"})
    t.add("GET", "https://mujassam.net/", 200, HOME, {"content-type": "text/html; charset=utf-8"})
    return t


class TestCrawler(unittest.TestCase):
    def test_parse_html(self):
        p = parse_html(HOME)
        self.assertEqual((p.html_lang, p.html_dir), ("ar", "rtl"))
        self.assertEqual(p.jsonld_types, ["Organization"])
        self.assertEqual(p.h1, ["حوّل فكرتك"])
        self.assertEqual(p.images_missing_alt, 1)

    def test_robots_matrix_separates_bots(self):
        m = robots_matrix(ROBOTS, ["https://mujassam.net/", "https://mujassam.net/admin"])
        self.assertEqual(m["OAI-SearchBot"]["allowed"], 1)
        self.assertEqual(m["Bytespider"] if "Bytespider" in m else None, None)
        self.assertEqual(m["GPTBot"]["crawl_delay"], 2)

    def test_crawl_and_findings(self):
        c = SiteCrawler(make_config(), mem_db(), site_transport(), delay=0)
        res = c.crawl()
        self.assertEqual(len(res["pages"]), 3)
        f = analyze_crawl(res, "https://mujassam.net/")
        titles = {x["title"] for x in f}
        self.assertIn("HTTP 404", titles)
        self.assertIn("2 H1 elements", titles)
        self.assertIn("Very little server-rendered text", titles)
        self.assertTrue(all(x["evidence"] is not None and x["urls"] for x in f))
        self.assertFalse(any("blocks OAI-SearchBot" in t for t in titles))


class TestVisibility(unittest.TestCase):
    def setUp(self):
        self.conn = mem_db()
        registry.sync_prompts(self.conn)
        self.comps = registry.sync_competitors(self.conn)

    def test_generic_arabic_word_is_not_brand(self):
        self.assertFalse(brand_mentioned("ممكن تطبع مجسم صغير في أي مكان"))
        self.assertTrue(brand_mentioned("جرّب منصة مجسّم لأنها بتسعّر فوري"))

    def test_import_dedup_and_metrics(self):
        csv = ("prompt_id,prompt_version,platform,observed_at,method,response_text,cited_urls,accuracy\n"
               "eg-print-stl,1,perplexity,2026-10-12,manual_sample,ممكن تجرب Mujassam أو تشكيل,https://mujassam.net/pricing|https://tashkeel.pro/,accurate\n"
               "en-cost,1,chatgpt_search,2026-10-12,manual_sample,Prices vary,https://example.com/x,not_applicable\n")
        r1 = import_observations(self.conn, csv, registry.competitor_list(self.conn), fmt="csv")
        r2 = import_observations(self.conn, csv, registry.competitor_list(self.conn), fmt="csv")
        self.assertEqual(r1, {"added": 2, "duplicates": 0, "skipped_empty": 0})
        self.assertEqual(r2, {"added": 0, "duplicates": 2, "skipped_empty": 0})
        r3 = import_observations(self.conn, str(ROOT / "data" / "ai_samples.template.csv"), [])
        self.assertEqual((r3["added"], r3["skipped_empty"]), (0, 126))
        m = analysis.visibility_metrics(self.conn, "2026-10-01", "2026-10-31")
        self.assertEqual(m["n"], 2)
        self.assertTrue(m["small_sample"])
        self.assertEqual(m["brand_mention_rate"], 0.5)
        self.assertEqual(m["unique_official_urls"], ["https://mujassam.net/pricing"])
        self.assertEqual(m["competitors"]["mentions"].get("tashkeel"), 1)
        self.assertIn("ar-EG", m["by_language"])
        cmp = analysis.compare_periods(m, analysis.visibility_metrics(self.conn, "2026-09-01", "2026-09-30"))
        self.assertFalse(cmp["comparable"])

    def test_invalid_platform_rejected(self):
        with self.assertRaises(ValueError):
            import_observations(self.conn, "prompt_id,platform,observed_at,response_text,cited_urls\nx,myspace,2026-10-01,a,\n", [], fmt="csv")


class TestFactsBacklogSafety(unittest.TestCase):
    def setUp(self):
        self.conn = mem_db()
        registry.sync_facts(self.conn)

    def test_conflicts_and_approval(self):
        open_ = self.conn.execute("SELECT COUNT(*) c FROM fact_conflicts WHERE status='open'").fetchone()["c"]
        seed = json.loads((ROOT / "data" / "facts.seed.json").read_text(encoding="utf-8"))["facts"]
        self.assertEqual(open_, sum(1 for f in seed if f["status"] == "conflicting"))
        approved_in_seed = [f["id"] for f in seed if f["status"] == "owner_verified"]
        self.assertTrue(approved_in_seed)
        self.assertEqual(registry.facts_for_publication(self.conn), [], "seed status alone never grants public approval")
        registry.approve_fact(self.conn, "contact.hours", "owner", "Sat-Thu 10:00-18:00; Friday closed")
        self.assertEqual(self.conn.execute("SELECT status FROM fact_conflicts WHERE topic='contact.hours'").fetchone()["status"], "resolved")
        self.assertEqual(self.conn.execute("SELECT new_value FROM fact_history WHERE fact_id='contact.hours'").fetchone()["new_value"],
                         "Sat-Thu 10:00-18:00; Friday closed")

    def test_draft_check_flags_unverified_claims(self):
        issues = registry.check_text_against_facts(self.conn, "خصم 50% انهارده بس وبنشتغل مع AUC")
        self.assertEqual({i["fact"] for i in issues}, {"pricing.discount", "trust.worked_with"})

    def test_backlog_state_machine_requires_human_and_approval(self):
        a = json.loads((ROOT / "data" / "initial_audit.json").read_text(encoding="utf-8"))
        rec = backlog.from_finding(a["findings"][0])
        self.assertEqual(backlog.upsert(self.conn, rec), "created")
        self.assertEqual(backlog.upsert(self.conn, rec), "unchanged")
        with self.assertRaises(safety.ApprovalRequired):
            backlog.transition(self.conn, rec["id"], "approved", "orchestrator")
        with self.assertRaises(ValueError):
            backlog.transition(self.conn, rec["id"], "verified", "owner")
        backlog.transition(self.conn, rec["id"], "approved", "owner")
        with self.assertRaises(safety.ApprovalRequired):
            backlog.transition(self.conn, rec["id"], "implemented", "dev")
        safety.approve(self.conn, "publish_content", rec["id"], "owner")
        backlog.transition(self.conn, rec["id"], "implemented", "dev")
        with self.assertRaises(ValueError):
            backlog.transition(self.conn, rec["id"], "verified", "dev")
        backlog.transition(self.conn, rec["id"], "verified", "dev", "re-fetched pages; one value")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) c FROM recommendation_events WHERE rec_id=?", (rec["id"],)).fetchone()["c"], 4)

    def test_unknown_action_requires_approval(self):
        with self.assertRaises(safety.ApprovalRequired):
            safety.require(self.conn, "post_on_facebook", "x")
        safety.require(self.conn, "analyze", "x")


class TestEmailIdentity(unittest.TestCase):
    def test_classification_and_send_block(self):
        conn = mem_db()
        self.assertEqual(email_identity.classify("someone@gmail.com")[0], email_identity.UNKNOWN)
        self.assertEqual(email_identity.classify("mujassam662@gmail.com")[0], email_identity.LIKELY)
        self.assertEqual(email_identity.classify("x@y.com", accessible=False)[0], email_identity.UNAVAILABLE)
        cfg = make_config(GEO_CONNECTED_EMAIL_ACCOUNTS="mujassam662@gmail.com,personal.person@gmail.com")
        out = email_identity.scan(conn, cfg)
        self.assertTrue(all("***" in o["account"] for o in out))
        with self.assertRaises(email_identity.EmailSendBlocked):
            email_identity.assert_can_send(conn, cfg, "mujassam662@gmail.com")
        cfg2 = make_config(GEO_EMAIL_SENDING_ENABLED="true", GEO_EMAIL_SENDING_AUTHORIZED_BY="owner")
        with self.assertRaises(email_identity.EmailSendBlocked):
            email_identity.assert_can_send(conn, cfg2, "mujassam662@gmail.com")  # still only LIKELY
        email_identity.confirm(conn, "mujassam662@gmail.com", email_identity.VERIFIED, "owner")
        with self.assertRaises(email_identity.EmailSendBlocked):
            email_identity.assert_can_send(conn, cfg2, "mujassam662@gmail.com")  # no send approval yet
        safety.approve(conn, "send_email", "mujassam662@gmail.com", "owner")
        email_identity.assert_can_send(conn, cfg2, "mujassam662@gmail.com")


class TestSecrets(unittest.TestCase):
    def test_redaction(self):
        s = redact('Authorization: Bearer abcdefghijkl123 {"access_token": "zzzz9999"} key=ya29.AAAbbb sk-ant-1234567890abcdef',
                   ["myknownsecret"])
        for leaked in ("abcdefghijkl123", "zzzz9999", "ya29.AAAbbb", "sk-ant-1234567890abcdef"):
            self.assertNotIn(leaked, s)

    def test_env_example_has_placeholders_only_and_gitignore(self):
        for line in (ROOT / ".env.example").read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                if any(w in k for w in ("TOKEN", "KEY", "CREDENTIALS", "AUTHORIZED_BY", "ACCOUNTS")):
                    self.assertEqual(v, "", f"{k} must be empty in .env.example")
        self.assertIn(".env", (ROOT / ".gitignore").read_text().splitlines())

    def test_no_secret_like_strings_in_repo(self):
        pat = re.compile(r"(ya29\.[A-Za-z0-9_\-]{20,}|sk-ant-[A-Za-z0-9_\-]{20,}|AIza[0-9A-Za-z_\-]{35}|-----BEGIN [A-Z ]*PRIVATE KEY)")
        for p in ROOT.rglob("*"):
            if p.is_file() and p.suffix in {".py", ".json", ".md", ".example", ".csv"} and "tests" not in p.parts:
                self.assertIsNone(pat.search(p.read_text(encoding="utf-8", errors="ignore")), str(p))


class TestOrchestratorReportsDashboard(unittest.TestCase):
    def setUp(self):
        self.conn = mem_db()
        self.out = tmpdir()
        self.patch = mock.patch.object(reports, "ROOT", self.out)
        self.patch.start()
        (self.out / "reports").mkdir()

    def tearDown(self):
        self.patch.stop()

    def test_daily_run_records_honest_statuses_and_report(self):
        t = FakeTransport(default=OSError("Tunnel connection failed: 403 Forbidden"))
        o = Orchestrator(make_config(), self.conn, t)
        o.import_initial_audit()
        log = o.run("daily", today=date(2026, 10, 12))
        by = {e["task"]: e["status"] for e in log}
        for task in ("ga4_sync", "gsc_sync", "clarity_sync", "bing_sync"):
            self.assertEqual(by[task], "skipped", task)
        self.assertEqual(by["technical_crawl"], "failed")
        self.assertEqual(by["generate_report"], "ok")
        failed = self.conn.execute("SELECT COUNT(*) c FROM task_runs WHERE status='failed'").fetchone()["c"]
        self.assertGreaterEqual(failed, 1)
        report = (self.out / "reports" / "daily" / "2026-10-12.md").read_text(encoding="utf-8")
        self.assertIn("غير متصل", report)
        self.assertIn("technical_crawl", report)
        self.assertNotIn("CONNECTED_AND_TESTED", self.conn.execute("SELECT group_concat(status) s FROM integration_health").fetchone()["s"])

    def test_parallel_fetches_on_file_db(self):
        path = self.out / "geo.sqlite3"
        conn = db.connect(path)
        o = Orchestrator(make_config(), conn, FakeTransport(default=OSError("blocked")))
        log = o.run("weekly", today=date(2026, 10, 12), crawl=False)
        fetch = {e["task"]: e["status"] for e in log if e["task"].endswith("_sync")}
        self.assertEqual(fetch, {"ga4_sync": "skipped", "gsc_sync": "skipped", "clarity_sync": "skipped", "bing_sync": "skipped"})
        n = db.connect(path).execute("SELECT COUNT(*) c FROM task_runs WHERE task LIKE '%_sync'").fetchone()["c"]
        self.assertEqual(n, 4)

    def test_successful_crawl_pipeline_and_skip_unchanged(self):
        o = Orchestrator(make_config(), self.conn, site_transport())
        o.bootstrap()
        r = o._run("adhoc", "technical_crawl", lambda: o._crawl(None))
        self.assertEqual(r["status"], "ok")
        self.assertGreater(self.conn.execute("SELECT COUNT(*) c FROM audit_findings").fetchone()["c"], 0)
        first = o._run("adhoc", "demo", lambda: 1, input_obj={"x": 1})
        second = o._run("adhoc", "demo", lambda: 1, input_obj={"x": 1})
        self.assertEqual((first["status"], second["status"]), ("ok", "skipped"))

    def test_dashboard_rtl_no_fabricated_data_no_secrets(self):
        cfg = make_config(CLARITY_API_TOKEN="super-secret-clarity-token", GEO_CONNECTED_EMAIL_ACCOUNTS="private.person@gmail.com")
        o = Orchestrator(cfg, self.conn, FakeTransport(default=OSError("blocked")))
        o.bootstrap()
        o.import_initial_audit()
        o.validate_integrations()
        html = dashboard.render(self.conn)
        self.assertIn('dir="rtl"', html)
        self.assertIn('lang="ar"', html)
        self.assertIn("#FBF6EC", html)  # creamy background
        self.assertIn("#14213D", html)  # navy
        self.assertIn("#E8792B", html)  # orange
        self.assertIn("لم يُسجَّل خط أساس بعد", html)
        self.assertIn("Search Console غير متصل", html)
        self.assertNotIn("super-secret-clarity-token", html)
        self.assertNotIn("private.person@gmail.com", html)  # identities are masked
        self.assertIn("pri***@gmail.com", html)
        self.assertNotIn("بيانات تجريبية", html)
        self.assertIn("بيانات تجريبية", dashboard.render(self.conn, sample_label=True))


class TestBusinessData(unittest.TestCase):
    def test_orders_import_drops_pii_and_margin_needs_costs(self):
        conn = mem_db()
        d = tmpdir() / "orders.csv"
        d.write_text("id,created_at,revenue_egp,material,weight_g,print_time_min,customer_id,phone,name\n"
                     "o1,2026-10-01,200,PLA,40,120,c9,0100000,Ali\n", encoding="utf-8")
        r = import_orders(conn, str(d))
        self.assertEqual(r["added"], 1)
        self.assertEqual(r["pii_columns_dropped"], ["name", "phone"])
        row = dict(conn.execute("SELECT * FROM orders").fetchone())
        self.assertNotIn("0100000", json.dumps(row))
        self.assertNotEqual(row["customer_hash"], "c9")
        self.assertEqual(analysis.margin_analysis(conn)["status"], "insufficient_data")

    def test_experiment_verdict_conservative(self):
        self.assertEqual(analysis.experiment_verdict(0.1, 0.2, 20, 20)["verdict"], "inconclusive")
        self.assertEqual(analysis.experiment_verdict(0.10, 0.105, 500, 500)["verdict"], "inconclusive")
        self.assertEqual(analysis.experiment_verdict(0.10, 0.13, 500, 500)["verdict"], "improved")

    def test_materials_and_knowledge_base(self):
        conn = mem_db()
        registry.sync_materials(conn)
        self.assertEqual(set(registry.advertisable_materials(conn)), {"PLA", "PETG"})
        r = registry.import_print_jobs(conn, str(ROOT / "data" / "knowledge_base" / "print_jobs.template.csv"))
        self.assertEqual(r, {"added": 0, "skipped_examples": 1})


class TestSchedule(unittest.TestCase):
    def test_cron_and_n8n_intervals(self):
        cron = [l for l in (ROOT / "automation" / "crontab.example").read_text().splitlines() if re.match(r"^[0-9*]", l)]
        exprs = {l.split("python3 -m geo run ")[1].split()[0]: " ".join(l.split()[:5]) for l in cron}
        self.assertEqual(exprs, {"daily": "15 6 * * *", "weekly": "0 7 * * 0", "monthly": "0 8 1 * *"})
        n8n = json.loads((ROOT / "automation" / "n8n-workflow.json").read_text())
        n8n_exprs = sorted(n["parameters"]["rule"]["interval"][0]["expression"] for n in n8n["nodes"] if "scheduleTrigger" in n["type"])
        self.assertEqual(n8n_exprs, sorted(exprs.values()))
        self.assertFalse(any("email" in n["type"].lower() or "slack" in n["type"].lower() for n in n8n["nodes"]))


if __name__ == "__main__":
    unittest.main()
