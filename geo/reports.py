"""Daily / weekly / monthly Arabic reports (Markdown) built only from stored data.

Missing sources are reported as missing; no numbers are invented. Labels: [مُلاحَظ] observed,
[محسوب] computed, [فرضية] hypothesis.
"""
from __future__ import annotations

import json
from datetime import date, timedelta

from . import analysis, backlog, db, registry
from .config import ROOT

LBL = {"observed": "[مُلاحَظ]", "computed": "[محسوب]", "hypothesis": "[فرضية]", "prediction": "[توقّع]"}
SEV_AR = {"high": "عالية", "medium": "متوسطة", "low": "منخفضة", "info": "معلومة"}
STATUS_AR = {"confirmed": "مؤكَّد", "hypothesis": "فرضية", "unverified_fact": "ادعاء غير مُتحقَّق منه", "pass": "سليم"}


def _period(cadence: str, today: date):
    days = {"daily": 1, "weekly": 7, "monthly": 30}[cadence]
    return (today - timedelta(days=days)).isoformat(), today.isoformat()


def build(conn, cadence: str, today: date, run_log: list | None = None) -> str:
    start, end = _period(cadence, today)
    L = [f"# تقرير GEO {'اليومي' if cadence == 'daily' else 'الأسبوعي' if cadence == 'weekly' else 'الشهري'} — مجسّم",
         f"الفترة: {start} → {end}  ·  وقت الإنشاء: {db.now_iso()}", ""]

    L += ["## حالة التكاملات", "| التكامل | الحالة | آخر نجاح | التفاصيل |", "|---|---|---|---|"]
    for h in db.rows(conn, "SELECT * FROM integration_health ORDER BY name"):
        L.append(f"| {h['name']} | {h['status']} | {h['last_success'] or '—'} | {(h['detail'] or '').replace('|', '/')[:120]} |")
    L.append("")

    vm = analysis.visibility_metrics(conn, start, end, "manual_sample")
    vp = analysis.visibility_metrics(conn, start, end, "api_proxy")
    L += ["## الظهور في محركات الذكاء الاصطناعي " + LBL["computed"]]
    for label, m in (("عينات يدوية", vm), ("واجهات API بديلة (ليست المنتج الاستهلاكي)", vp)):
        if not m["n"]:
            L.append(f"- {label}: لا توجد ملاحظات في هذه الفترة. لا يمكن حساب معدل الظهور.")
        else:
            warn = " ⚠️ عينة صغيرة، النتائج اتجاهية فقط" if m["small_sample"] else ""
            L.append(f"- {label}: n={m['n']} · ذكر العلامة {m['brand_mention_rate']:.0%} · الاستشهاد بالموقع الرسمي "
                     f"{m['official_citation_rate']:.0%} · روابط رسمية فريدة {len(m['unique_official_urls'])}{warn}")
    if cadence == "monthly":
        prev_start = (date.fromisoformat(start) - timedelta(days=30)).isoformat()
        cmp = analysis.compare_periods(vm, analysis.visibility_metrics(conn, prev_start, start, "manual_sample"))
        L.append(f"- مقارنة بالفترة السابقة: {json.dumps(cmp, ensure_ascii=False)}")
    L.append("")

    L += ["## الطلب في البحث (Search Console)"]
    snap = analysis.latest_snapshot(conn, "gsc", "queries")
    if not snap:
        L.append("- غير متاح: Search Console غير متصل. لا توجد بيانات استعلامات.")
    else:
        s = analysis.gsc_summary(snap["payload"])
        L.append(f"- {LBL['observed']} نافذة {snap['window_start']}→{snap['window_end']} · صفوف {s['n_rows']} · حسب نوع العلامة: "
                 f"{json.dumps(s['by_brand_class'], ensure_ascii=False)}")
        for o in analysis.gsc_opportunities(snap["payload"])[:10]:
            L.append(f"  - {LBL['hypothesis']} «{o.get('query')}» ظهور {o['impressions']} · CTR {o['ctr']:.1%} · ترتيب {o['position']:.1f} — {o['why']}")
    L.append("")

    L += ["## سلوك العملاء (GA4 + Clarity)"]
    ga = analysis.latest_snapshot(conn, "ga4", "landing_pages")
    cl = analysis.latest_snapshot(conn, "clarity", "live_insights")
    L.append("- GA4: " + (f"{LBL['observed']} لقطة {ga['window_start']}→{ga['window_end']}، {len(ga['payload'])} صف" if ga else "غير متصل."))
    L.append("- Clarity: " + (f"{LBL['observed']} نافذة حتى {cl['window_end']}" if cl else "غير متصل. واجهة Clarity تعطي آخر 1-3 أيام فقط، فلا يمكن استرجاع تاريخ أقدم."))
    L.append("- قابلية قياس مسار التحويل:")
    for st in analysis.funnel_measurability(conn):
        L.append(f"  - {'✅' if st['measurable'] else '⛔'} {st['step']}: {st['note']}")
    L.append("")

    L += ["## سجل الحقائق والتعارضات"]
    conflicts = db.rows(conn, "SELECT topic, statements FROM fact_conflicts WHERE status='open'")
    L.append(f"- تعارضات مفتوحة: {len(conflicts)}")
    for c in conflicts:
        L.append(f"  - `{c['topic']}`: {json.loads(c['statements'])['value']}")
    stale = registry.stale_facts(conn, today.isoformat())
    L.append(f"- حقائق تحتاج إعادة تحقق: {len(stale)}")
    approved = conn.execute("SELECT COUNT(*) c FROM facts WHERE public_approved=1").fetchone()["c"]
    total = conn.execute("SELECT COUNT(*) c FROM facts").fetchone()["c"]
    L.append(f"- حقائق معتمدة للنشر من المالك: {approved} من {total}")
    L.append("")

    L += ["## أهم الإجراءات المقترحة (مرتبة حسب الأولوية)", "| # | الإجراء | الأولوية | الثقة | يحتاج موافقة | الحالة |", "|---|---|---|---|---|---|"]
    for i, r in enumerate(backlog.ranked(conn, 12 if cadence != "daily" else 5), 1):
        L.append(f"| {i} | {r['title']} | {r['priority']} | {r['confidence']}/5 | {'نعم' if r['requires_approval'] else 'لا'} | {r['state']} |")
    L.append("")

    if cadence == "monthly":
        L += ["## التجارب"]
        for e in db.rows(conn, "SELECT id, status, result FROM experiments"):
            L.append(f"- {e['id']}: {e['status']} {('· ' + e['result']) if e['result'] else ''}")
        m = analysis.margin_analysis(conn)
        L += ["", "## تحليل الهامش " + LBL["computed"], f"- {m.get('message') or json.dumps(m['by_material'], ensure_ascii=False)}", ""]

    if run_log:
        L += ["## سجل التنفيذ", "| المهمة | الحالة | التفاصيل |", "|---|---|---|"]
        for e in run_log:
            L.append(f"| {e['task']} | {e['status']} | {e['detail'][:140].replace('|', '/').replace(chr(10), ' ')} |")
    return "\n".join(L) + "\n"


def generate(conn, cadence: str, today: date, run_log: list | None = None) -> dict:
    start, end = _period(cadence, today)
    text = build(conn, cadence, today, run_log)
    out_dir = ROOT / "reports" / cadence
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{end}.md"
    path.write_text(text, encoding="utf-8")
    conn.execute("INSERT INTO reports(cadence,period_start,period_end,path,generated_at,summary) VALUES(?,?,?,?,?,?)",
                 (cadence, start, end, str(path.relative_to(ROOT)), db.now_iso(), text[:500]))
    conn.commit()
    return {"path": str(path.relative_to(ROOT))}
