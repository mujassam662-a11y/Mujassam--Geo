"""CLI: python -m geo <command>

  init                      create DB, load facts/prompts/competitors/materials/experiments, import initial audit
  status                    integration status (performs real probes; never prints secrets)
  run {daily|weekly|monthly} [--no-crawl]
  audit                     full technical crawl of the public site (direct HTTP)
  report {daily|weekly|monthly}
  dashboard [--port N] [--export FILE]
  import-observations FILE  manual AI-visibility samples (CSV/JSON)
  import-bing-ai FILE --start D --end D [--report ai_cited_pages|ai_grounding_queries]
  import-orders FILE        authorised order export (PII dropped, customer ids hashed)
  import-jobs FILE          manufacturing knowledge-base records
  facts list|approve ID --by NAME [--value V]
  backlog list | backlog move ID STATE --by NAME [--note TXT]
  approve ACTION TARGET --by NAME [--note TXT]
  email scan | email confirm ACCOUNT CLASS --by NAME
  check-draft FILE          publication-safety check of a content draft against the fact registry
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from . import backlog, dashboard, db, email_identity, registry, reports, safety
from .config import Config
from .connectors import all_connectors
from .connectors.ai_visibility import import_observations
from .connectors.bing import import_ai_performance_csv
from .connectors.business_data import import_orders
from .orchestrator import Orchestrator


def main(argv=None):
    ap = argparse.ArgumentParser(prog="geo")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    sub.add_parser("status")
    r = sub.add_parser("run"); r.add_argument("cadence", choices=["daily", "weekly", "monthly"]); r.add_argument("--no-crawl", action="store_true")
    sub.add_parser("audit")
    rp = sub.add_parser("report"); rp.add_argument("cadence", choices=["daily", "weekly", "monthly"])
    d = sub.add_parser("dashboard"); d.add_argument("--port", type=int, default=8765); d.add_argument("--host", default="127.0.0.1"); d.add_argument("--export")
    io_ = sub.add_parser("import-observations"); io_.add_argument("file")
    ib = sub.add_parser("import-bing-ai"); ib.add_argument("file"); ib.add_argument("--start", required=True); ib.add_argument("--end", required=True)
    ib.add_argument("--report", default="ai_cited_pages")
    sub.add_parser("import-orders").add_argument("file")
    sub.add_parser("import-jobs").add_argument("file")
    f = sub.add_parser("facts"); f.add_argument("action", choices=["list", "approve"]); f.add_argument("id", nargs="?")
    f.add_argument("--by"); f.add_argument("--value")
    b = sub.add_parser("backlog"); b.add_argument("action", choices=["list", "move"]); b.add_argument("id", nargs="?"); b.add_argument("state", nargs="?")
    b.add_argument("--by"); b.add_argument("--note", default="")
    a = sub.add_parser("approve"); a.add_argument("action", choices=sorted(safety.REQUIRES_APPROVAL)); a.add_argument("target")
    a.add_argument("--by", required=True); a.add_argument("--note", default="")
    em = sub.add_parser("email"); em.add_argument("action", choices=["scan", "confirm"]); em.add_argument("account", nargs="?")
    em.add_argument("classification", nargs="?"); em.add_argument("--by")
    sub.add_parser("check-draft").add_argument("file")
    args = ap.parse_args(argv)

    cfg = Config.from_env()
    conn = db.connect(cfg.db_path)
    out = None

    if args.cmd == "init":
        o = Orchestrator(cfg, conn)
        o.bootstrap("adhoc")
        o.import_initial_audit()
        out = o.log
    elif args.cmd == "status":
        out = {c.name: dict(zip(("status", "detail"), c.test())) for c in all_connectors(cfg, conn)}
    elif args.cmd == "run":
        out = Orchestrator(cfg, conn).run(args.cadence, crawl=not args.no_crawl)
    elif args.cmd == "audit":
        o = Orchestrator(cfg, conn)
        out = o._run("adhoc", "technical_crawl", lambda: o._crawl(None))
    elif args.cmd == "report":
        out = reports.generate(conn, args.cadence, date.today())
    elif args.cmd == "dashboard":
        if args.export:
            Path(args.export).write_text(dashboard.render(conn), encoding="utf-8")
            out = {"exported": args.export}
        else:
            dashboard.serve(conn, args.host, args.port)
    elif args.cmd == "import-observations":
        registry.sync_competitors(conn)
        out = import_observations(conn, args.file, registry.competitor_list(conn))
    elif args.cmd == "import-bing-ai":
        out = import_ai_performance_csv(conn, Path(args.file).read_text(encoding="utf-8"), args.start, args.end, args.report)
    elif args.cmd == "import-orders":
        out = import_orders(conn, args.file)
    elif args.cmd == "import-jobs":
        out = registry.import_print_jobs(conn, args.file)
    elif args.cmd == "facts":
        if args.action == "list":
            out = db.rows(conn, "SELECT id, status, public_approved, value FROM facts ORDER BY id")
        else:
            if not (args.id and args.by):
                ap.error("facts approve ID --by NAME")
            registry.approve_fact(conn, args.id, args.by, args.value)
            out = {"approved": args.id}
    elif args.cmd == "backlog":
        if args.action == "list":
            out = [{k: r[k] for k in ("id", "priority", "state", "title", "requires_approval")} for r in backlog.ranked(conn, 100)]
        else:
            backlog.transition(conn, args.id, args.state, args.by or "", args.note)
            out = {"moved": args.id, "to": args.state}
    elif args.cmd == "approve":
        safety.approve(conn, args.action, args.target, args.by, args.note)
        out = {"approved": args.action, "target": args.target}
    elif args.cmd == "email":
        if args.action == "scan":
            out = email_identity.scan(conn, cfg)
        else:
            email_identity.confirm(conn, args.account, args.classification, args.by)
            out = {"confirmed": email_identity.mask(args.account), "classification": args.classification}
    elif args.cmd == "check-draft":
        out = registry.check_text_against_facts(conn, Path(args.file).read_text(encoding="utf-8"))
    if out is not None:
        print(cfg.redact(json.dumps(out, ensure_ascii=False, indent=2, default=str)))


if __name__ == "__main__":
    sys.exit(main())
