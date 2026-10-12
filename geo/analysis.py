"""Computed metrics. Every function returns `kind` and `n` so callers can show sample size and never
present computed or small-sample numbers as observed platform-wide facts."""
from __future__ import annotations

import json
from collections import defaultdict

from . import db

MIN_SAMPLE = 10  # below this a rate is shown with an explicit "small sample" warning


def visibility_metrics(conn, start: str, end: str, method: str | None = None) -> dict:
    where, params = "observed_at >= ? AND observed_at <= ?", [start, end + "T99"]
    if method:
        where += " AND method=?"
        params.append(method)
    obs = db.rows(conn, f"SELECT o.*, p.language, p.intent FROM visibility_observations o LEFT JOIN prompts p "
                        f"ON p.id=o.prompt_id AND p.version=o.prompt_version WHERE {where}", params)
    n = len(obs)
    out = {"kind": "computed", "period": [start, end], "method": method or "all", "n": n,
           "small_sample": n < MIN_SAMPLE, "by_platform": {}, "by_language": {}, "by_intent": {}}
    if not n:
        return out

    def rate(items, key):
        return round(sum(i[key] for i in items) / len(items), 3) if items else None

    out["brand_mention_rate"] = rate(obs, "brand_mentioned")
    out["official_citation_rate"] = rate(obs, "official_site_cited")
    ids = [o["id"] for o in obs]
    q = ",".join("?" * len(ids))
    cites = db.rows(conn, f"SELECT * FROM citations WHERE observation_id IN ({q})", ids)
    off = [c for c in cites if c["is_official"]]
    out["official_citations"] = len(off)
    out["unique_official_urls"] = sorted({c["url"] for c in off})
    reviewed = [o for o in obs if o["accuracy"] not in ("unreviewed", "not_applicable") and o["brand_mentioned"]]
    out["accuracy"] = {"reviewed": len(reviewed),
                       "accurate_rate": rate([{"a": int(o["accuracy"] == "accurate")} for o in reviewed], "a") if reviewed else None}
    comp = db.rows(conn, f"SELECT competitor_id, COUNT(*) c FROM competitor_mentions WHERE observation_id IN ({q}) GROUP BY competitor_id", ids)
    comp_cites = db.rows(conn, f"SELECT competitor_id, COUNT(*) c FROM citations WHERE competitor_id IS NOT NULL AND observation_id IN ({q}) GROUP BY competitor_id", ids)
    out["competitors"] = {"mentions": {r["competitor_id"]: r["c"] for r in comp}, "citations": {r["competitor_id"]: r["c"] for r in comp_cites}}
    top_domains = db.rows(conn, f"SELECT domain, COUNT(*) c FROM citations WHERE observation_id IN ({q}) GROUP BY domain ORDER BY c DESC LIMIT 15", ids)
    out["top_cited_domains"] = top_domains
    for dim, key in (("by_platform", "platform"), ("by_language", "language"), ("by_intent", "intent")):
        groups = defaultdict(list)
        for o in obs:
            groups[o.get(key) or "unknown"].append(o)
        out[dim] = {k: {"n": len(v), "mention_rate": rate(v, "brand_mentioned"), "citation_rate": rate(v, "official_site_cited")}
                    for k, v in groups.items()}
    return out


def compare_periods(cur: dict, prev: dict) -> dict:
    """Comparable only when both periods used the same method and have samples."""
    res = {"kind": "computed", "comparable": bool(cur.get("n") and prev.get("n") and cur["method"] == prev["method"])}
    if not res["comparable"]:
        res["reason"] = "No baseline or different measurement method"
        return res
    for k in ("brand_mention_rate", "official_citation_rate"):
        res[k] = {"current": cur.get(k), "previous": prev.get(k),
                  "delta": round((cur.get(k) or 0) - (prev.get(k) or 0), 3)}
    res["warning"] = "Small samples; treat change as directional only" if cur["small_sample"] or prev["small_sample"] else None
    return res


def latest_snapshot(conn, source: str, report: str) -> dict | None:
    r = conn.execute("SELECT * FROM analytics_snapshots WHERE source=? AND report=? ORDER BY window_end DESC, fetched_at DESC LIMIT 1",
                     (source, report)).fetchone()
    if not r:
        return None
    d = dict(r)
    d["payload"] = json.loads(d["payload"])
    return d


def gsc_opportunities(rows: list[dict], min_impr: int = 50) -> list[dict]:
    """Queries with demonstrated demand but weak CTR or position 5-20. Hypotheses, not conclusions."""
    out = []
    for r in rows:
        impr, ctr, pos = r.get("impressions") or 0, r.get("ctr") or 0, r.get("position") or 0
        if impr >= min_impr and (4 < pos <= 20 or ctr < 0.02):
            out.append({**r, "kind": "hypothesis",
                        "why": "high impressions, low CTR" if ctr < 0.02 else "ranking just off top results",
                        "verify": "Improve the matching page answer/title, then compare same query 28 days later"})
    return sorted(out, key=lambda x: -(x.get("impressions") or 0))[:50]


def gsc_summary(rows: list[dict]) -> dict:
    from .connectors.gsc import brand_class
    agg = defaultdict(lambda: {"clicks": 0, "impressions": 0})
    for r in rows:
        c = r.get("brand_class") or brand_class(r.get("query", ""))
        agg[c]["clicks"] += r.get("clicks") or 0
        agg[c]["impressions"] += r.get("impressions") or 0
    return {"kind": "computed", "n_rows": len(rows), "by_brand_class": dict(agg)}


def clarity_summary(payload: list) -> dict:
    from .connectors.clarity import flatten_metrics
    m = flatten_metrics(payload)
    signals = {}
    for name in ("Dead Click Count", "Rage Click Count", "Quickback Click", "Script Error Count", "Error Click Count", "Excessive Scroll"):
        rows = m.get(name, [])
        top = sorted(rows, key=lambda r: -float(r.get("subTotal") or r.get("sessionsWithMetricPercentage") or 0))[:10]
        signals[name] = top
    return {"kind": "observed", "metrics_present": sorted(m), "friction_signals": signals,
            "traffic": m.get("Traffic", []), "scroll_depth": m.get("Scroll Depth", []), "engagement": m.get("Engagement Time", [])}


FUNNEL = [
    ("landing", "GA4 sessions by landing page", "ga4", "landing_pages"),
    ("service_understanding", "Engaged sessions / scroll depth on home, pricing, guide", "ga4+clarity", "landing_pages"),
    ("upload", "GA4 event for successful file upload (name must be confirmed in event inventory)", "ga4", "events"),
    ("instant_quote", "GA4 event for quote shown", "ga4", "events"),
    ("checkout_payment", "GA4 begin_checkout / payment events", "ga4", "events"),
    ("confirmed_order", "Order CSV export (source of truth), not a GA4 event name", "orders", None),
    ("fulfilment", "Order status export (shipped/delivered)", "orders", None),
    ("repeat_purchase", "Orders grouped by hashed customer id", "orders", None),
]


def funnel_measurability(conn, event_map: dict | None = None) -> list[dict]:
    """Which steps can actually be measured right now, given synced data and an owner-confirmed event map."""
    event_map = event_map or {}
    has = lambda src, rep: conn.execute("SELECT 1 FROM analytics_snapshots WHERE source=? AND report=? LIMIT 1", (src, rep)).fetchone() is not None
    n_orders = conn.execute("SELECT COUNT(*) c FROM orders").fetchone()["c"]
    out = []
    for step, how, src, rep in FUNNEL:
        if src == "orders":
            ok = n_orders > 0
            note = f"{n_orders} orders imported" if ok else "No authorised order export imported"
        elif step in ("upload", "instant_quote", "checkout_payment"):
            ok = has("ga4", "events") and step in event_map
            note = f"event '{event_map.get(step)}' confirmed" if ok else "Needs GA4 data AND owner confirmation of which event means this step"
        else:
            ok = has("ga4", rep)
            note = "GA4 data present" if ok else "GA4 not connected"
        out.append({"step": step, "measure": how, "measurable": ok, "note": note})
    return out


def margin_analysis(conn) -> dict:
    """Contribution per order only when verified cost inputs exist. Never treats revenue as profit."""
    costs = {r["key"]: r["value"] for r in db.rows(conn, "SELECT key, value FROM cost_assumptions WHERE verified=1")}
    orders = db.rows(conn, "SELECT * FROM orders")
    needed = ["machine_cost_egp_per_hour", "labor_cost_egp_per_order", "payment_fee_pct"]
    missing = [k for k in needed if k not in costs]
    if not orders or missing:
        return {"kind": "computed", "status": "insufficient_data", "orders": len(orders), "missing_verified_costs": missing,
                "message": "Margin analysis needs an order export and verified cost inputs; revenue alone is not profit."}
    by_material = defaultdict(lambda: {"orders": 0, "revenue": 0.0, "contribution": 0.0})
    unknown_material_cost = set()
    for o in orders:
        mat_cost = costs.get(f"material_cost_{(o['material'] or '').lower()}_egp_per_g")
        if mat_cost is None:
            unknown_material_cost.add(o["material"])
            continue
        rev = (o["revenue_egp"] or 0) - (o["shipping_egp"] or 0)
        c = rev - mat_cost * (o["weight_g"] or 0) - costs["machine_cost_egp_per_hour"] * (o["print_time_min"] or 0) / 60 \
            - costs["labor_cost_egp_per_order"] - rev * costs["payment_fee_pct"] / 100
        if o["refunded"]:
            c -= rev
        b = by_material[o["material"]]
        b["orders"] += 1
        b["revenue"] += rev
        b["contribution"] += c
    return {"kind": "computed", "status": "ok", "by_material": dict(by_material),
            "excluded_materials_without_cost": sorted(m for m in unknown_material_cost if m),
            "assumptions": costs, "note": "Acquisition cost not included unless provided."}


def experiment_verdict(baseline: float, current: float, n_base: int, n_cur: int, min_n: int = 100, min_lift: float = 0.1) -> dict:
    """Deliberately conservative: below min sample or below min lift => inconclusive."""
    if n_base < min_n or n_cur < min_n:
        return {"verdict": "inconclusive", "reason": f"insufficient sample (need >= {min_n} each, have {n_base}/{n_cur})"}
    if baseline <= 0:
        return {"verdict": "inconclusive", "reason": "zero baseline"}
    lift = (current - baseline) / baseline
    if abs(lift) < min_lift:
        return {"verdict": "inconclusive", "reason": f"lift {lift:.1%} below threshold {min_lift:.0%}", "lift": lift}
    return {"verdict": "improved" if lift > 0 else "worsened", "lift": lift,
            "caveat": "Before/after comparison; seasonality and other changes are not controlled"}
