"""Loaders and logic for the fact registry (Agent 10), prompt library, competitors, materials and knowledge base."""
from __future__ import annotations

import csv
import json
from datetime import date, timedelta
from pathlib import Path

from . import db
from .config import ROOT

DATA = ROOT / "data"
REVALIDATE_DAYS = {"pricing": 14, "materials": 14, "payment": 30, "delivery": 30, "policy": 60, "privacy": 60,
                   "contact": 90, "identity": 180, "service": 60, "process": 60, "trust": 30}
AVAILABILITY = ("available_now", "temporarily_unavailable", "planned", "unverified")


def _load(name):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


# ---------- facts ----------
def sync_facts(conn, seed: dict | None = None) -> dict:
    """Upsert seeded facts. Changed values are written to fact_history and their affected URLs flagged.
    Owner approvals (public_approved) are preserved across re-seeding unless the value changed."""
    seed = seed or _load("facts.seed.json")
    added = changed = 0
    changes = []
    for f in seed["facts"]:
        prev = conn.execute("SELECT value, public_approved FROM facts WHERE id=?", (f["id"],)).fetchone()
        urls = [u.strip() for u in f["source"].replace(";", " ").split() if u.startswith("http")]
        reval = (date.today() + timedelta(days=REVALIDATE_DAYS.get(f["category"], 60))).isoformat()
        approved = prev["public_approved"] if prev and prev["value"] == f["value"] else 0
        conn.execute(
            "INSERT INTO facts(id,claim,value,category,source,evidence,verified_at,confidence,public_approved,revalidate_by,"
            "revalidate_condition,status,affected_urls,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
            "claim=excluded.claim,value=excluded.value,category=excluded.category,source=excluded.source,evidence=excluded.evidence,"
            "verified_at=excluded.verified_at,confidence=excluded.confidence,public_approved=excluded.public_approved,"
            "revalidate_by=excluded.revalidate_by,status=excluded.status,affected_urls=excluded.affected_urls,updated_at=excluded.updated_at",
            (f["id"], f["claim"], f["value"], f["category"], f["source"], f.get("notes", f["source"]),
             f.get("verified_at", "2026-10-12"), f["confidence"], approved, reval, f.get("revalidate_condition", "on any site change"),
             f["status"], json.dumps(urls), db.now_iso()))
        if not prev:
            added += 1
        elif prev["value"] != f["value"]:
            changed += 1
            conn.execute("INSERT INTO fact_history(fact_id,old_value,new_value,changed_at,reason) VALUES(?,?,?,?,?)",
                         (f["id"], prev["value"], f["value"], db.now_iso(), "seed update"))
            changes.append({"fact": f["id"], "affected_urls": urls})
        if f["status"] == "conflicting":
            key = db.stable_hash(["fact", f["id"], f["value"]])
            conn.execute("INSERT OR IGNORE INTO fact_conflicts(dedup_key,topic,statements,status,detected_at) VALUES(?,?,?,?,?)",
                         (key, f["id"], json.dumps({"value": f["value"], "sources": f["source"]}, ensure_ascii=False), "open", db.now_iso()))
    conn.commit()
    return {"added": added, "changed": changed, "changes": changes}


def approve_fact(conn, fact_id: str, by: str, verified_value: str | None = None):
    row = conn.execute("SELECT value FROM facts WHERE id=?", (fact_id,)).fetchone()
    if not row:
        raise KeyError(fact_id)
    if verified_value and verified_value != row["value"]:
        conn.execute("INSERT INTO fact_history(fact_id,old_value,new_value,changed_at,reason) VALUES(?,?,?,?,?)",
                     (fact_id, row["value"], verified_value, db.now_iso(), f"owner verification by {by}"))
    conn.execute("UPDATE facts SET public_approved=1, status='owner_verified', confidence='high', value=COALESCE(?, value), "
                 "verified_at=?, updated_at=? WHERE id=?", (verified_value, db.now_iso()[:10], db.now_iso(), fact_id))
    conn.execute("UPDATE fact_conflicts SET status='resolved', resolution=? WHERE topic=? AND status='open'", (f"owner: {by}", fact_id))
    conn.execute("INSERT INTO approvals(action,target,approved_by,note,at) VALUES(?,?,?,?,?)",
                 ("approve_fact", fact_id, by, verified_value or "", db.now_iso()))
    conn.commit()


def stale_facts(conn, today: str | None = None) -> list[dict]:
    today = today or date.today().isoformat()
    return db.rows(conn, "SELECT id, claim, revalidate_by FROM facts WHERE revalidate_by < ? ORDER BY revalidate_by", (today,))


def facts_for_publication(conn) -> list[dict]:
    """Only these may appear in public content or schema."""
    return db.rows(conn, "SELECT id, claim, value FROM facts WHERE public_approved=1 AND status IN ('owner_verified','observed_public')")


def check_text_against_facts(conn, text: str) -> list[dict]:
    """Publication-safety helper: flags conflicting/unverified facts that a draft mentions."""
    issues = []
    low = text.lower()
    watch = {"abs": "materials.offered", "instapay": "payment.methods", "فودافون": "payment.methods", "vodafone": "payment.methods",
             "خصم": "pricing.discount", "discount": "pricing.discount", "يومين": "delivery.turnaround", "2 days": "delivery.turnaround",
             "auc": "trust.worked_with", "nile university": "trust.worked_with", "جامعة القاهرة": "trust.worked_with",
             "ساعة": "policy.cancellation", "18:04": "contact.hours"}
    for token, fid in watch.items():
        if token in low:
            row = conn.execute("SELECT status, public_approved FROM facts WHERE id=?", (fid,)).fetchone()
            if row and (row["status"] in ("conflicting", "unverified") or not row["public_approved"]):
                issues.append({"token": token, "fact": fid, "status": row["status"], "approved": bool(row["public_approved"])})
    return issues


# ---------- prompts ----------
def sync_prompts(conn) -> int:
    n = 0
    for p in _load("prompts.json")["prompts"]:
        cur = conn.execute("INSERT OR IGNORE INTO prompts(id,version,text,language,intent,source,active,created_at) VALUES(?,?,?,?,?,?,1,?)",
                           (p["id"], p["version"], p["text"], p["language"], p["intent"], p["source"], db.now_iso()))
        n += cur.rowcount
        conn.execute("UPDATE prompts SET active=0 WHERE id=? AND version<?", (p["id"], p["version"]))
    conn.commit()
    return n


def active_prompts(conn) -> list[dict]:
    return db.rows(conn, "SELECT * FROM prompts WHERE active=1 ORDER BY language, id")


# ---------- competitors ----------
def sync_competitors(conn) -> list[dict]:
    comps = _load("competitors.json")["competitors"]
    for c in comps:
        conn.execute("INSERT INTO competitors(id,name,domains,status,data,sources,verified_at) VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                     "name=excluded.name,domains=excluded.domains,status=excluded.status,data=excluded.data,sources=excluded.sources,verified_at=excluded.verified_at",
                     (c["id"], c["name"], json.dumps(c["domains"]), c["status"], json.dumps(c["data"], ensure_ascii=False),
                      json.dumps(c["sources"]), c.get("verified_at")))
    conn.commit()
    return comps


def competitor_list(conn) -> list[dict]:
    out = []
    for r in db.rows(conn, "SELECT * FROM competitors"):
        r["domains"] = json.loads(r["domains"])
        r["data"] = json.loads(r["data"])
        r["sources"] = json.loads(r["sources"])
        r["names"] = [r["name"].lower()] + [d.split(".")[0] for d in r["domains"]]
        out.append(r)
    return out


# ---------- materials ----------
def sync_materials(conn) -> list[dict]:
    """Returns change events (availability/price) so affected pages and claims can be re-checked."""
    events = []
    for m in _load("materials.json")["materials"]:
        if m["availability"] not in AVAILABILITY:
            raise ValueError(f"{m['id']}: bad availability {m['availability']}")
        prev = conn.execute("SELECT availability, data FROM materials WHERE id=?", (m["id"],)).fetchone()
        data = json.dumps(m["data"], ensure_ascii=False)
        if prev and (prev["availability"] != m["availability"] or prev["data"] != data):
            events.append({"material": m["id"], "from": prev["availability"], "to": m["availability"],
                           "affected": ["https://mujassam.net/pricing", "https://mujassam.net/#use-cases", "https://mujassam.net/#faq",
                                        "https://mujassam.net/guide", "facts:materials.offered", "facts:pricing.*"]})
        conn.execute("INSERT INTO materials(id,name,availability,data,source,verified_at,updated_at) VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                     "availability=excluded.availability,data=excluded.data,source=excluded.source,verified_at=excluded.verified_at,updated_at=excluded.updated_at",
                     (m["id"], m["name"], m["availability"], data, m["source"], m.get("verified_at"), db.now_iso()))
    conn.commit()
    return events


def advertisable_materials(conn) -> list[str]:
    """Only owner-confirmed, available-now materials may be advertised."""
    return [r["id"] for r in db.rows(conn, "SELECT id FROM materials WHERE availability='available_now' AND verified_at IS NOT NULL")]


# ---------- manufacturing knowledge base ----------
PERMISSIONS = ("none", "internal_only", "anonymised_public", "public_with_photos")


def import_print_jobs(conn, path: str) -> dict:
    added = skipped = 0
    with open(path, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if r["id"].endswith("DELETE-ME"):
                skipped += 1
                continue
            perm = r.get("publication_permission") or "none"
            if perm not in PERMISSIONS:
                raise ValueError(f"{r['id']}: publication_permission must be one of {PERMISSIONS}")
            cur = conn.execute(
                "INSERT OR IGNORE INTO print_jobs(id,use_case,material,technology,model_traits,sliced_weight_g,print_time_min,issues,"
                "improvements,result,evidence_refs,publication_permission,confidentiality,recorded_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (r["id"], r.get("use_case"), r.get("material"), r.get("technology"), r.get("model_traits"),
                 float(r["sliced_weight_g"]) if r.get("sliced_weight_g") else None,
                 float(r["print_time_min"]) if r.get("print_time_min") else None, r.get("issues"), r.get("improvements"),
                 r.get("result"), r.get("evidence_refs"), perm, r.get("confidentiality"), db.now_iso()))
            added += cur.rowcount
    conn.commit()
    return {"added": added, "skipped_examples": skipped}


def publishable_jobs(conn) -> list[dict]:
    return db.rows(conn, "SELECT id,use_case,material,technology,sliced_weight_g,print_time_min,issues,improvements,result "
                         "FROM print_jobs WHERE publication_permission IN ('anonymised_public','public_with_photos')")
