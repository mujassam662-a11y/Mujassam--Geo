"""Order / business data import (authorised CSV exports only).

No direct database access to the production site is configured. The site owner exports orders to CSV
(columns below) and runs `python -m geo import-orders file.csv`. Customer identifiers are hashed on import;
names, phones, emails and addresses are dropped and never stored.
"""
from __future__ import annotations

import csv
import hashlib
import io
from pathlib import Path

from .. import db

COLUMNS = ["id", "created_at", "revenue_egp", "material", "weight_g", "print_time_min", "discount_egp",
           "shipping_egp", "refunded", "reprint", "channel", "landing_page", "customer_id"]
PII_COLUMNS = {"name", "customer_name", "phone", "mobile", "email", "address", "street"}


def _f(v):
    try:
        return float(v) if v not in (None, "") else None
    except ValueError:
        return None


def import_orders(conn, path: str, salt: str = "mujassam-geo") -> dict:
    text = Path(path).read_text(encoding="utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    missing = [c for c in ("id", "created_at", "revenue_egp") if c not in (reader.fieldnames or [])]
    if missing:
        raise ValueError(f"Order CSV missing required columns: {missing}")
    dropped = sorted(PII_COLUMNS & {c.lower() for c in reader.fieldnames or []})
    added = 0
    for r in reader:
        cust = r.get("customer_id") or ""
        cust_hash = hashlib.sha256((salt + cust).encode()).hexdigest()[:16] if cust else None
        cur = conn.execute(
            "INSERT OR IGNORE INTO orders(id,created_at,revenue_egp,material,weight_g,print_time_min,discount_egp,shipping_egp,"
            "refunded,reprint,channel,landing_page,customer_hash,source_file) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (r["id"], r["created_at"], _f(r.get("revenue_egp")), r.get("material"), _f(r.get("weight_g")),
             _f(r.get("print_time_min")), _f(r.get("discount_egp")), _f(r.get("shipping_egp")),
             int(str(r.get("refunded", "0")).lower() in ("1", "true", "yes")),
             int(str(r.get("reprint", "0")).lower() in ("1", "true", "yes")),
             r.get("channel"), r.get("landing_page"), cust_hash, Path(path).name))
        added += cur.rowcount
    conn.commit()
    db.set_health(conn, "business_orders", "CONNECTED_AND_TESTED" if added else "CONFIGURED_NOT_TESTED",
                  f"CSV import: {added} new orders from {Path(path).name}; PII columns dropped: {dropped}", success=bool(added))
    return {"added": added, "pii_columns_dropped": dropped}
