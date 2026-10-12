"""GEO Orchestrator (Agent 1): runs daily / weekly / monthly pipelines.

* Independent fetches run in parallel (thread pool); analysis runs after.
* Every task is logged in `task_runs` with status ok | skipped | failed and a redacted detail.
* A task whose input hash equals the last successful run is skipped (no duplicate work on unchanged data).
* Agent conclusions are challenged: recommendations without evidence or from hypotheses get lower confidence,
  and contradicting recommendations on the same URL are flagged for human review.
"""
from __future__ import annotations

import json
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

from . import analysis, backlog, db, email_identity, registry
from .config import Config, ROOT
from .connectors import all_connectors
from .connectors.ai_visibility import run_api_proxies
from .connectors.base import ConnectorError
from .connectors.clarity import ClarityConnector
from .connectors.crawler import SiteCrawler, analyze_crawl
from .connectors.ga4 import GA4Connector
from .connectors.gsc import GSCConnector
from .connectors.bing import BingConnector

CADENCES = {"daily": 1, "weekly": 7, "monthly": 30}


class Orchestrator:
    def __init__(self, config: Config | None = None, conn=None, transport=None):
        self.config = config or Config.from_env()
        self.conn = conn or db.connect(self.config.db_path)
        self.transport = transport
        self.log: list[dict] = []

    # ---------- task plumbing ----------
    def _run(self, cadence: str, task: str, fn, input_obj=None):
        ih = db.stable_hash(input_obj) if input_obj is not None else None
        if ih:
            last = self.conn.execute("SELECT input_hash FROM task_runs WHERE task=? AND status='ok' ORDER BY id DESC LIMIT 1", (task,)).fetchone()
            if last and last["input_hash"] == ih:
                return self._record(cadence, task, "skipped", "input unchanged since last successful run", ih)
        started = db.now_iso()
        try:
            result = fn()
            return self._record(cadence, task, "ok", json.dumps(result, ensure_ascii=False, default=str)[:2000], ih, started)
        except ConnectorError as e:
            status = "skipped" if e.status in ("REQUIRES_CREDENTIALS", "UNSUPPORTED_OR_UNAVAILABLE") else "failed"
            return self._record(cadence, task, status, f"{e.status}: {e.detail}", ih, started)
        except Exception as e:
            return self._record(cadence, task, "failed", f"{type(e).__name__}: {e}\n{traceback.format_exc(limit=3)}", ih, started)

    def _record(self, cadence, task, status, detail, ih=None, started=None):
        detail = self.config.redact(detail)
        ts = db.now_iso()
        self.conn.execute("INSERT INTO task_runs(cadence,task,started_at,finished_at,status,detail,input_hash) VALUES(?,?,?,?,?,?,?)",
                          (cadence, task, started or ts, ts, status, detail, ih))
        self.conn.commit()
        entry = {"task": task, "status": status, "detail": detail[:300]}
        self.log.append(entry)
        return entry

    # ---------- shared steps ----------
    def bootstrap(self, cadence="daily"):
        self._run(cadence, "sync_facts", lambda: registry.sync_facts(self.conn))
        self._run(cadence, "sync_prompts", lambda: registry.sync_prompts(self.conn))
        self._run(cadence, "sync_competitors", lambda: len(registry.sync_competitors(self.conn)))
        self._run(cadence, "sync_materials", lambda: registry.sync_materials(self.conn))
        self._run(cadence, "sync_experiments", self._sync_experiments)
        self._run(cadence, "email_identity_scan", lambda: email_identity.scan(self.conn, self.config))

    def _sync_experiments(self):
        data = json.loads((ROOT / "data" / "experiments.json").read_text(encoding="utf-8"))
        for e in data["experiments"]:
            self.conn.execute("INSERT INTO experiments(id,data,status,updated_at) VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data",
                              (e["id"], json.dumps(e, ensure_ascii=False), e["status"], db.now_iso()))
        self.conn.commit()
        return len(data["experiments"])

    def validate_integrations(self, cadence="daily"):
        def check():
            res = {}
            for c in all_connectors(self.config, self.conn, self.transport):
                res[c.name] = c.test()[0]
            return res
        return self._run(cadence, "validate_integrations", check)

    def import_initial_audit(self, cadence="adhoc"):
        def do():
            a = json.loads((ROOT / "data" / "initial_audit.json").read_text(encoding="utf-8"))
            return self.store_audit(a["run_id"], a["method"], a["scope"], a["findings"], a["started_at"], a.get("notes"))
        return self._run(cadence, "import_initial_audit", do)

    def store_audit(self, run_id, method, scope, findings, started_at=None, notes=None) -> dict:
        self.conn.execute("INSERT OR REPLACE INTO audit_runs(id,started_at,finished_at,method,scope,status,notes) VALUES(?,?,?,?,?,?,?)",
                          (run_id, started_at or db.now_iso(), db.now_iso(), method, scope, "complete", notes))
        created = 0
        for f in findings:
            key = db.stable_hash([f["category"], f["title"], sorted(f["urls"])])
            self.conn.execute(
                "INSERT OR IGNORE INTO audit_findings(dedup_key,run_id,agent,category,severity,status,title,urls,evidence,recommendation,verification,observed_at,kind) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (key, run_id, f["agent"], f["category"], f["severity"], f["status"], f["title"], json.dumps(f["urls"]),
                 f["evidence"] if isinstance(f["evidence"], str) else json.dumps(f["evidence"], ensure_ascii=False),
                 f.get("recommendation"), f.get("verification"), started_at or db.now_iso(),
                 "observed" if f["status"] in ("confirmed", "pass") else ("hypothesis" if f["status"] == "hypothesis" else "observed")))
            rec = backlog.from_finding(f)
            if rec and backlog.upsert(self.conn, rec) == "created":
                created += 1
        self.conn.commit()
        self.challenge_backlog()
        return {"findings": len(findings), "recommendations_created": created}

    def challenge_backlog(self) -> list[dict]:
        """Orchestrator review: demote evidence-free items; flag contradictory recommendations on one URL."""
        flags = []
        recs = backlog.ranked(self.conn, 500)
        by_url = {}
        for r in recs:
            ev = r["evidence"]
            if not ev.get("evidence"):
                self.conn.execute("UPDATE recommendations SET confidence=1, priority=priority/2 WHERE id=?", (r["id"],))
                flags.append({"rec": r["id"], "issue": "no evidence; demoted"})
            for u in ev.get("urls", []):
                by_url.setdefault(u, []).append(r)
        for u, items in by_url.items():
            cats = {i["category"] for i in items}
            if {"content_gap", "content_quality"} <= cats and any(i["agent"] == "technical_discoverability" for i in items):
                flags.append({"url": u, "issue": "multiple agents propose changes to the same page; sequence them"})
        self.conn.commit()
        return flags

    # ---------- pipelines ----------
    def run(self, cadence: str, today: date | None = None, crawl: bool = True) -> list[dict]:
        if cadence not in CADENCES:
            raise ValueError(cadence)
        self.log = []
        today = today or datetime.now(timezone.utc).date()
        self.bootstrap(cadence)
        self.validate_integrations(cadence)
        lag_end = (today - timedelta(days=3)).isoformat()  # GSC/GA4 finalisation lag
        win_start = (today - timedelta(days=3 + CADENCES[cadence] - 1)).isoformat()

        fetches = {
            "ga4_sync": lambda c: GA4Connector(self.config, c, self.transport).sync(win_start, lag_end),
            "gsc_sync": lambda c: GSCConnector(self.config, c, self.transport).sync(win_start, lag_end),
            "clarity_sync": lambda c: ClarityConnector(self.config, c, self.transport).sync(),
            "bing_sync": lambda c: BingConnector(self.config, c, self.transport).sync(win_start, lag_end),
        }
        self._parallel(cadence, fetches)

        if crawl:
            scope_pages = 30 if cadence == "daily" else None
            self._run(cadence, "technical_crawl", lambda: self._crawl(scope_pages))
        self._run(cadence, "stale_fact_check", lambda: registry.stale_facts(self.conn))
        if cadence in ("weekly", "monthly"):
            prompts = registry.active_prompts(self.conn)
            self._run(cadence, "ai_visibility_api_proxies",
                      lambda: run_api_proxies(self.conn, self.config, prompts, registry.competitor_list(self.conn), self.transport))
        self._run(cadence, "challenge_backlog", self.challenge_backlog)
        from . import reports
        self._run(cadence, "generate_report", lambda: reports.generate(self.conn, cadence, today, self.log))
        return self.log

    def _db_file(self) -> str:
        row = self.conn.execute("PRAGMA database_list").fetchone()
        return row["file"] if row else ""

    def _parallel(self, cadence, tasks: dict):
        """Run independent fetch tasks in parallel. A sqlite connection must not be shared across threads,
        so each worker opens its own connection to the same file (WAL mode). In-memory DBs run sequentially."""
        path = self._db_file()
        if not path:
            for name, fn in tasks.items():
                self._run(cadence, name, lambda fn=fn: fn(self.conn))
            return
        self.conn.execute("PRAGMA journal_mode=WAL")

        def work(item):
            name, fn = item
            c = db.connect(path)
            c.execute("PRAGMA busy_timeout=10000")
            try:
                sub = Orchestrator(self.config, c, self.transport)
                return sub._run(cadence, name, lambda: fn(c))
            finally:
                c.close()

        with ThreadPoolExecutor(max_workers=len(tasks)) as ex:
            self.log.extend(ex.map(work, tasks.items()))

    def _crawl(self, max_pages=None):
        c = SiteCrawler(self.config, self.conn, self.transport, max_pages=max_pages)
        result = c.crawl()
        if not result["pages"]:
            raise ConnectorError("FAILED_WITH_EVIDENCE", f"crawl returned no pages (robots status {result['robots_status']})")
        failed = [p for p in result["pages"].values() if p.error]
        if len(failed) == len(result["pages"]):
            raise ConnectorError("FAILED_WITH_EVIDENCE", "all page fetches failed: " + failed[0].error)
        findings = analyze_crawl(result, self.config.site_url)
        run_id = "crawl-" + db.now_iso()
        stored = self.store_audit(run_id, "direct_http_crawl", f"{len(result['pages'])} pages", findings)
        db.set_health(self.conn, c.name, "CONNECTED_AND_TESTED", f"{len(result['pages'])} pages crawled", success=True)
        return {"pages": len(result["pages"]), **stored}
