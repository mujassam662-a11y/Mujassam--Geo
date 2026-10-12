"""Persistent action backlog with a guarded state machine (Agent 1 + Agent 9).

States: proposed -> approved -> implemented -> verified   (also: rejected, inconclusive)
Items whose category maps to an outward-facing action cannot move to `approved` without a named approver,
and cannot move to `implemented` unless the matching safety approval exists.
"""
from __future__ import annotations

import json

from . import db, safety

STATES = ("proposed", "approved", "implemented", "verified", "rejected", "inconclusive")
TRANSITIONS = {"proposed": {"approved", "rejected"}, "approved": {"implemented", "rejected"},
               "implemented": {"verified", "inconclusive"}, "inconclusive": {"implemented", "rejected"},
               "verified": set(), "rejected": {"proposed"}}
SEVERITY_IMPACT = {"high": 5, "medium": 3, "low": 2, "info": 1}
STATUS_CONFIDENCE = {"confirmed": 5, "unverified_fact": 3, "hypothesis": 2, "pass": 1}


def priority(impact: int, confidence: int, effort: int, risk: int) -> float:
    """Impact x confidence, discounted by effort and risk (all 1..5). Higher = do first."""
    return round(impact * confidence / (effort + 0.5 * risk), 2)


def upsert(conn, rec: dict) -> str:
    """Create or refresh a recommendation. If evidence is unchanged the row is untouched (no duplicate work)."""
    ev_hash = db.stable_hash(rec["evidence"])
    prev = conn.execute("SELECT evidence_hash, state FROM recommendations WHERE id=?", (rec["id"],)).fetchone()
    if prev and prev["evidence_hash"] == ev_hash:
        return "unchanged"
    action = safety.action_for_category(rec["category"])
    p = priority(rec["impact"], rec["confidence"], rec["effort"], rec["risk"])
    ts = db.now_iso()
    if prev:
        conn.execute("UPDATE recommendations SET evidence=?, evidence_hash=?, priority=?, impact=?, confidence=?, effort=?, risk=?, updated_at=? WHERE id=?",
                     (json.dumps(rec["evidence"], ensure_ascii=False), ev_hash, p, rec["impact"], rec["confidence"], rec["effort"], rec["risk"], ts, rec["id"]))
        conn.execute("INSERT INTO recommendation_events(rec_id,from_state,to_state,actor,note,at) VALUES(?,?,?,?,?,?)",
                     (rec["id"], prev["state"], prev["state"], "orchestrator", "evidence changed; re-prioritised", ts))
        conn.commit()
        return "updated"
    conn.execute(
        "INSERT INTO recommendations(id,title,agent,category,evidence,explanation,impact,confidence,effort,risk,priority,requires_approval,"
        "approval_reason,dependencies,state,verification_plan,evidence_hash,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (rec["id"], rec["title"], rec["agent"], rec["category"], json.dumps(rec["evidence"], ensure_ascii=False), rec.get("explanation"),
         rec["impact"], rec["confidence"], rec["effort"], rec["risk"], p, int(action is not None),
         safety.REQUIRES_APPROVAL.get(action) if action else None, json.dumps(rec.get("dependencies", [])), "proposed",
         rec.get("verification_plan"), ev_hash, ts, ts))
    conn.execute("INSERT INTO recommendation_events(rec_id,from_state,to_state,actor,note,at) VALUES(?,?,?,?,?,?)",
                 (rec["id"], None, "proposed", "orchestrator", "created", ts))
    conn.commit()
    return "created"


def transition(conn, rec_id: str, to_state: str, actor: str, note: str = "") -> None:
    row = conn.execute("SELECT state, category, requires_approval FROM recommendations WHERE id=?", (rec_id,)).fetchone()
    if not row:
        raise KeyError(rec_id)
    if to_state not in TRANSITIONS[row["state"]]:
        raise ValueError(f"Illegal transition {row['state']} -> {to_state}")
    if to_state == "approved" and (not actor or actor in ("orchestrator", "agent", "system")):
        raise safety.ApprovalRequired("Approval must be given by a named human")
    if to_state == "implemented" and row["requires_approval"]:
        action = safety.action_for_category(row["category"])
        safety.require(conn, action, rec_id)
    if to_state == "verified" and not note:
        raise ValueError("Verification needs a result note with evidence")
    ts = db.now_iso()
    conn.execute("UPDATE recommendations SET state=?, updated_at=?, verification_result=COALESCE(?, verification_result) WHERE id=?",
                 (to_state, ts, note if to_state in ("verified", "inconclusive") else None, rec_id))
    conn.execute("INSERT INTO recommendation_events(rec_id,from_state,to_state,actor,note,at) VALUES(?,?,?,?,?,?)",
                 (rec_id, row["state"], to_state, actor, note, ts))
    conn.commit()


def from_finding(f: dict) -> dict | None:
    if f["status"] == "pass" or f["severity"] == "info":
        return None
    effort = {"fact_conflict": 1, "policy_conflict": 2, "contact": 1, "content_quality": 1, "structured_data": 2,
              "content_gap": 4, "language_coverage": 4, "trust_claims": 2, "privacy_vs_analytics": 3}.get(f["category"], 2)
    risk = {"policy_conflict": 3, "privacy_vs_analytics": 3, "pricing_trust": 3, "structured_data": 2}.get(f["category"], 1)
    return {"id": "rec-" + db.stable_hash([f["agent"], f["category"], f["title"]])[:10], "title": f["title"], "agent": f["agent"],
            "category": f["category"], "evidence": {"urls": f["urls"], "evidence": f["evidence"], "finding_status": f["status"]},
            "explanation": f.get("recommendation"), "impact": SEVERITY_IMPACT[f["severity"]],
            "confidence": STATUS_CONFIDENCE.get(f["status"], 2), "effort": effort, "risk": risk,
            "verification_plan": f.get("verification")}


def ranked(conn, limit: int = 50) -> list[dict]:
    out = db.rows(conn, "SELECT * FROM recommendations WHERE state NOT IN ('verified','rejected') ORDER BY priority DESC, created_at LIMIT ?", (limit,))
    for r in out:
        r["evidence"] = json.loads(r["evidence"])
        r["dependencies"] = json.loads(r["dependencies"])
    return out
