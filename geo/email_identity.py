"""Email identity and integration safety (Agent 11).

Classifies every discovered email account. Only VERIFIED_MUJASSAM accounts may be used for brand activity,
and sending stays disabled unless the owner explicitly authorised it (env flags + recorded approval).
"""
from __future__ import annotations

import json

from . import db

VERIFIED = "VERIFIED_MUJASSAM"
LIKELY = "LIKELY_MUJASSAM"
UNKNOWN = "UNKNOWN_OWNERSHIP"
UNRELATED = "UNRELATED_OR_PERSONAL"
UNAVAILABLE = "ACCESS_UNAVAILABLE"
CLASSES = (VERIFIED, LIKELY, UNKNOWN, UNRELATED, UNAVAILABLE)

PUBLIC_CONTACT = "mujassam662@gmail.com"  # published on mujassam.net/contact (observed 2026-10-12); not proof of token ownership
BRAND_DOMAINS = ("mujassam.net",)


def mask(account: str) -> str:
    if "@" not in account:
        return account[:2] + "***"
    local, dom = account.split("@", 1)
    return (local[:3] + "***@" + dom) if len(local) > 3 else ("***@" + dom)


def classify(account: str, accessible: bool = True, owner_confirmed: bool = False) -> tuple[str, list[str]]:
    a = account.strip().lower()
    ev = []
    if not accessible:
        return UNAVAILABLE, ["account listed in config but could not be accessed/inspected"]
    if owner_confirmed:
        return VERIFIED, ["owner confirmed in writing (recorded approval)"]
    if any(a.endswith("@" + d) for d in BRAND_DOMAINS):
        ev.append("address on brand domain mujassam.net (domain ownership not independently verified here)")
        return LIKELY, ev
    if a == PUBLIC_CONTACT:
        ev.append("matches the public contact email on mujassam.net/contact; this does not prove the connected token belongs to the business")
        return LIKELY, ev
    if "mujassam" in a:
        return UNKNOWN, ["contains brand string but not the published address or brand domain"]
    return UNKNOWN, ["no evidence linking this account to Mujassam"]


def scan(conn, config) -> list[dict]:
    """Discover accounts from config (GEO_CONNECTED_EMAIL_ACCOUNTS) and the session user email if exposed."""
    found = []
    for acc in [a for a in config.get("GEO_CONNECTED_EMAIL_ACCOUNTS").split(",") if a.strip()]:
        found.append((acc.strip(), "GEO_CONNECTED_EMAIL_ACCOUNTS"))
    for key in ("CLAUDE_CODE_USER_EMAIL",):
        if config.get(key):
            found.append((config.get(key), f"environment variable {key} (operator identity of the AI session)"))
    out = []
    for acc, where in found:
        prev = conn.execute("SELECT classification, confirmed_by FROM email_identities WHERE account=?", (acc.lower(),)).fetchone()
        if prev and prev["confirmed_by"]:
            cls, ev = prev["classification"], ["previously confirmed by owner"]
        else:
            cls, ev = classify(acc)
        ev.append(f"discovered via {where}")
        conn.execute("INSERT INTO email_identities(account,classification,evidence,confirmed_by,updated_at) VALUES(?,?,?,?,?) "
                     "ON CONFLICT(account) DO UPDATE SET classification=excluded.classification, evidence=excluded.evidence, updated_at=excluded.updated_at",
                     (acc.lower(), cls, json.dumps(ev, ensure_ascii=False), prev["confirmed_by"] if prev else None, db.now_iso()))
        out.append({"account": mask(acc), "classification": cls, "evidence": ev})
    conn.commit()
    return out


def confirm(conn, account: str, classification: str, confirmed_by: str):
    if classification not in CLASSES:
        raise ValueError(classification)
    conn.execute("INSERT INTO email_identities(account,classification,evidence,confirmed_by,updated_at) VALUES(?,?,?,?,?) "
                 "ON CONFLICT(account) DO UPDATE SET classification=excluded.classification, confirmed_by=excluded.confirmed_by, updated_at=excluded.updated_at",
                 (account.lower(), classification, json.dumps(["owner confirmation"]), confirmed_by, db.now_iso()))
    conn.commit()


class EmailSendBlocked(Exception):
    pass


def assert_can_send(conn, config, account: str) -> None:
    """Raises EmailSendBlocked unless every gate passes. There is deliberately no send implementation here."""
    if not config.flag("GEO_EMAIL_SENDING_ENABLED") or not config.get("GEO_EMAIL_SENDING_AUTHORIZED_BY"):
        raise EmailSendBlocked("Email sending disabled (GEO_EMAIL_SENDING_ENABLED / _AUTHORIZED_BY not set)")
    row = conn.execute("SELECT classification FROM email_identities WHERE account=?", (account.lower(),)).fetchone()
    if not row or row["classification"] != VERIFIED:
        raise EmailSendBlocked(f"{mask(account)} is not VERIFIED_MUJASSAM")
    ok = conn.execute("SELECT 1 FROM approvals WHERE action='send_email' AND target=?", (account.lower(),)).fetchone()
    if not ok:
        raise EmailSendBlocked("No recorded approval for send_email from this account")
