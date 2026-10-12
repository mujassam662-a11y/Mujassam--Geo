"""Approval gates. Anything outward-facing or hard to undo requires a recorded human approval."""
from __future__ import annotations

from . import db

REQUIRES_APPROVAL = {
    "publish_content": "Publishing new content on the live website",
    "change_pricing": "Changing prices, discounts, inventory claims or delivery promises",
    "send_email": "Sending emails",
    "contact_external": "Contacting customers or partners / external outreach",
    "change_policy": "Changing legal or privacy policies",
    "delete_production_data": "Deleting production data",
    "change_credentials": "Changing credentials or access permissions",
    "deploy_production": "Deploying production changes",
    "advertise_material": "Advertising a new material or capability",
}
AUTONOMOUS = {"analyze", "crawl_public", "research_competitors", "draft", "update_internal_reports",
              "update_fact_registry_internal", "run_tests", "prepare_branch", "reprioritize_backlog"}

CATEGORY_TO_ACTION = {
    "fact_conflict": "publish_content", "policy_conflict": "change_policy", "pricing_trust": "change_pricing",
    "policy_freshness": "change_policy", "privacy_vs_analytics": "change_policy", "trust_claims": "publish_content",
    "contact": "publish_content", "structured_data": "deploy_production", "content_gap": "publish_content",
    "content_quality": "publish_content", "sitemap": "deploy_production", "rtl": "deploy_production",
    "language_coverage": "publish_content", "ip_risk": "publish_content", "outreach": "contact_external",
    "materials": "advertise_material",
}


class ApprovalRequired(Exception):
    pass


def action_for_category(category: str) -> str | None:
    return CATEGORY_TO_ACTION.get(category)


def require(conn, action: str, target: str) -> None:
    if action in AUTONOMOUS:
        return
    if action not in REQUIRES_APPROVAL:
        raise ApprovalRequired(f"Unknown action '{action}' treated as requiring approval")
    row = conn.execute("SELECT approved_by FROM approvals WHERE action=? AND target=? ORDER BY id DESC LIMIT 1",
                       (action, target)).fetchone()
    if not row:
        raise ApprovalRequired(f"{REQUIRES_APPROVAL[action]} requires recorded approval (target={target})")


def approve(conn, action: str, target: str, by: str, note: str = ""):
    if not by.strip():
        raise ValueError("approver name required")
    conn.execute("INSERT INTO approvals(action,target,approved_by,note,at) VALUES(?,?,?,?,?)", (action, target, by, note, db.now_iso()))
    conn.commit()
