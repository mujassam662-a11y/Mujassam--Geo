"""Arabic-first RTL dashboard. Stdlib http.server, read-only, binds to 127.0.0.1 by default.

Every number is read from the SQLite store. Empty sources render an explanation, never a placeholder chart.
`python -m geo dashboard --export file.html` writes a static snapshot.
"""
from __future__ import annotations

import html
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import analysis, backlog, db, registry

CSS = """
:root{--bg:#FBF6EC;--card:#FFFDF8;--ink:#14213D;--muted:#5B6478;--accent:#E8792B;--accent-soft:#FBE3CF;--line:#E9E1D2;
--ok:#2F7D4F;--warn:#B7791F;--bad:#B23B3B}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font-family:"IBM Plex Sans Arabic","Noto Sans Arabic",Tahoma,sans-serif;line-height:1.6}
header{background:var(--ink);color:#FBF6EC;padding:18px 24px;display:flex;gap:16px;align-items:center;flex-wrap:wrap}
header h1{margin:0;font-size:1.35rem}header .tag{background:var(--accent);color:#fff;border-radius:999px;padding:2px 12px;font-size:.8rem}
nav{display:flex;gap:6px;flex-wrap:wrap;padding:10px 24px;background:#F3ECDD;border-bottom:1px solid var(--line);position:sticky;top:0}
nav a{color:var(--ink);text-decoration:none;padding:4px 10px;border-radius:8px;font-size:.9rem}nav a:hover{background:var(--accent-soft)}
main{max-width:1200px;margin:0 auto;padding:16px}
section{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px 18px;margin:14px 0}
section h2{margin:0 0 10px;font-size:1.15rem;border-inline-start:4px solid var(--accent);padding-inline-start:10px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px}
.kpi{border:1px solid var(--line);border-radius:12px;padding:10px 12px;background:#fff}
.kpi .v{font-size:1.5rem;font-weight:700}.kpi .l{color:var(--muted);font-size:.85rem}
table{width:100%;border-collapse:collapse;font-size:.88rem}th,td{padding:7px 8px;border-bottom:1px solid var(--line);text-align:start;vertical-align:top}
th{color:var(--muted);font-weight:600}.wrap{overflow-x:auto}
.pill{display:inline-block;border-radius:999px;padding:1px 9px;font-size:.75rem;border:1px solid var(--line);white-space:nowrap}
.s-CONNECTED_AND_TESTED,.st-confirmed,.sev-low{background:#E5F2EA;color:var(--ok)}
.s-REQUIRES_CREDENTIALS,.s-CONFIGURED_NOT_TESTED,.s-REQUIRES_PERMISSION,.st-hypothesis,.sev-medium{background:#FBF0DC;color:var(--warn)}
.s-FAILED_WITH_EVIDENCE,.sev-high,.st-conflicting{background:#F7E1E1;color:var(--bad)}
.s-UNSUPPORTED_OR_UNAVAILABLE,.st-unverified_fact,.st-unverified{background:#ECEEF3;color:var(--muted)}
.empty{color:var(--muted);background:#F6F1E6;border:1px dashed var(--line);border-radius:10px;padding:12px}
.note{color:var(--muted);font-size:.82rem}.ltr{direction:ltr;unicode-bidi:isolate;display:inline-block}
.bar{height:10px;background:var(--accent);border-radius:6px}
@media (max-width:600px){main{padding:8px}section{padding:12px}header h1{font-size:1.1rem}}
"""


def e(x) -> str:
    return html.escape("" if x is None else str(x))


def ltr(x) -> str:
    return f'<span class="ltr">{e(x)}</span>'


def empty(msg: str) -> str:
    return f'<div class="empty">{e(msg)}</div>'


def table(headers, rows_html) -> str:
    if not rows_html:
        return empty("لا توجد بيانات.")
    return '<div class="wrap"><table><thead><tr>' + "".join(f"<th>{h}</th>" for h in headers) + "</tr></thead><tbody>" + \
        "".join("<tr>" + "".join(f"<td dir=\"auto\">{c}</td>" for c in r) + "</tr>" for r in rows_html) + "</tbody></table></div>"


def bars(items: dict) -> str:
    if not items:
        return empty("لا توجد بيانات.")
    mx = max(items.values()) or 1
    return table(["البند", "القيمة", ""], [[ltr(k), e(v), f'<div class="bar" style="width:{int(100 * v / mx)}%"></div>'] for k, v in items.items()])


def render(conn, sample_label: bool = False) -> str:
    health = db.rows(conn, "SELECT * FROM integration_health ORDER BY name")
    findings = db.rows(conn, "SELECT * FROM audit_findings ORDER BY CASE severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 WHEN 'low' THEN 2 ELSE 3 END, id")
    recs = backlog.ranked(conn, 100)
    facts = db.rows(conn, "SELECT * FROM facts ORDER BY CASE status WHEN 'conflicting' THEN 0 WHEN 'unverified' THEN 1 ELSE 2 END, category, id")
    conflicts = conn.execute("SELECT COUNT(*) c FROM fact_conflicts WHERE status='open'").fetchone()["c"]
    first = conn.execute("SELECT MIN(observed_at) a, MAX(observed_at) b FROM visibility_observations").fetchone()
    vm = analysis.visibility_metrics(conn, first["a"] or "2000-01-01", (first["b"] or "2000-01-01")[:10])
    comps = registry.competitor_list(conn)
    mats = db.rows(conn, "SELECT * FROM materials ORDER BY id")
    exps = db.rows(conn, "SELECT * FROM experiments")
    reports = db.rows(conn, "SELECT * FROM reports ORDER BY id DESC LIMIT 6")
    runs = db.rows(conn, "SELECT * FROM task_runs WHERE task!='clarity_request' ORDER BY id DESC LIMIT 15")
    emails = db.rows(conn, "SELECT * FROM email_identities")
    connected = sum(1 for h in health if h["status"] == "CONNECTED_AND_TESTED")
    gsc = analysis.latest_snapshot(conn, "gsc", "queries")
    ga = analysis.latest_snapshot(conn, "ga4", "landing_pages")
    cl = analysis.latest_snapshot(conn, "clarity", "live_insights")
    orders = conn.execute("SELECT COUNT(*) c, SUM(revenue_egp) r FROM orders").fetchone()

    H = [f'<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
         f'<title>لوحة GEO — مجسّم</title><style>{CSS}</style></head><body>',
         '<header><h1>لوحة ذكاء GEO — مجسّم</h1><span class="tag">بيانات حقيقية فقط</span>'
         f'<span class="note" style="color:#E9E1D2">آخر تحديث للعرض: {ltr(db.now_iso())}</span></header>',
         '<nav>' + "".join(f'<a href="#{i}">{t}</a>' for i, t in [("exec", "نظرة تنفيذية"), ("ai", "الظهور في الذكاء الاصطناعي"), ("tech", "الصحة التقنية"),
                                                            ("search", "الطلب في البحث"), ("behavior", "سلوك العملاء"), ("comp", "المنافسون"),
                                                            ("actions", "مركز الإجراءات"), ("facts", "سجل الحقائق"), ("materials", "الخامات"),
                                                            ("integrations", "التكاملات")]) + '</nav><main>']
    if sample_label:
        H.append('<section><strong>⚠️ بيانات تجريبية للتطوير — ليست أرقامًا حقيقية</strong></section>')

    H.append('<section id="exec"><h2>نظرة تنفيذية</h2><div class="grid">')
    for v, l in [(f"{connected}/{len(health)}", "تكاملات متصلة ومختبرة"), (vm["n"], "ملاحظات ظهور AI مسجلة"),
                 (f"{vm['brand_mention_rate']:.0%}" if vm["n"] else "—", "معدل ذكر العلامة (كل العينات)"),
                 (f"{vm['official_citation_rate']:.0%}" if vm["n"] else "—", "معدل الاستشهاد بالموقع"),
                 (sum(1 for f in findings if f["severity"] == "high" and f["status"] != "pass"), "مشكلات عالية الخطورة"),
                 (conflicts, "تعارضات حقائق مفتوحة"),
                 (orders["c"] or "—", "طلبات مستوردة (موثقة)")]:
        H.append(f'<div class="kpi"><div class="v">{e(v)}</div><div class="l">{e(l)}</div></div>')
    H.append('</div><p class="note">الجلسات المؤهلة، رفع التصاميم، عروض الأسعار والإيرادات تظهر هنا فقط بعد ربط GA4 واستيراد الطلبات. '
             'لا يتم عرض أي رقم غير مُقاس.</p>')
    top = [r for r in recs if r["impact"] >= 3][:5]
    H.append("<h3>أعلى الأولويات</h3>" + table(["الإجراء", "الأولوية", "الحالة"], [[e(r["title"]), e(r["priority"]), e(r["state"])] for r in top]) + "</section>")

    H.append('<section id="ai"><h2>الظهور في محركات الذكاء الاصطناعي</h2>')
    if not vm["n"]:
        H.append(empty("لم يُسجَّل خط أساس بعد. شغّل عينة يدوية بمكتبة الأسئلة (data/prompts.json) واستوردها: "
                       "python -m geo import-observations file.csv — ثم ستظهر النتائج حسب المنصة واللغة والنية."))
    else:
        if vm["small_sample"]:
            H.append('<p class="note">⚠️ عينة صغيرة؛ النتائج اتجاهية وليست تمثيلًا شاملًا للمنصة.</p>')
        H.append("<h3>حسب المنصة</h3>" + table(["المنصة", "n", "ذكر", "استشهاد"],
                 [[ltr(k), v["n"], f"{v['mention_rate']:.0%}", f"{v['citation_rate']:.0%}"] for k, v in vm["by_platform"].items()]))
        H.append("<h3>حسب اللغة</h3>" + table(["اللغة", "n", "ذكر", "استشهاد"],
                 [[ltr(k), v["n"], f"{v['mention_rate']:.0%}", f"{v['citation_rate']:.0%}"] for k, v in vm["by_language"].items()]))
        H.append("<h3>أكثر النطاقات استشهادًا</h3>" + bars({d["domain"]: d["c"] for d in vm["top_cited_domains"]}))
        H.append("<h3>المنافسون في الإجابات</h3>" + bars(vm["competitors"]["mentions"]))
    H.append('<p class="note">المنصات الاستهلاكية (ChatGPT Search، AI Overviews، Copilot، Perplexity، Gemini، Claude) لا توفر واجهة عامة لقياس الظهور؛ '
             'القياس عبر عينات يدوية مضبوطة وتقرير Bing AI Performance عند تصديره.</p></section>')

    H.append('<section id="tech"><h2>الصحة التقنية ونتائج التدقيق</h2>')
    H.append(table(["الخطورة", "الحالة", "المشكلة", "الروابط", "الدليل", "الإصلاح المقترح", "التحقق"],
                   [[f'<span class="pill sev-{e(f["severity"])}">{e(f["severity"])}</span>', f'<span class="pill st-{e(f["status"])}">{e(f["status"])}</span>',
                     e(f["title"]), "<br>".join(ltr(u) for u in json.loads(f["urls"])[:3]), e(f["evidence"])[:300], e(f["recommendation"]), e(f["verification"])]
                    for f in findings]))
    H.append('</section>')

    H.append('<section id="search"><h2>الطلب في البحث (Search Console / Bing)</h2>')
    if not gsc:
        H.append(empty("Search Console غير متصل. أضف GOOGLE_APPLICATION_CREDENTIALS و GSC_SITE_URL (انظر docs/SETUP_INTEGRATIONS.md)."))
    else:
        rows = sorted(gsc["payload"], key=lambda r: -(r.get("impressions") or 0))[:25]
        H.append(f'<p class="note">نافذة {ltr(gsc["window_start"])} → {ltr(gsc["window_end"])} · جُلبت {ltr(gsc["fetched_at"])}</p>')
        H.append(table(["الاستعلام", "نقرات", "ظهور", "CTR", "الترتيب"],
                       [[e(r.get("query")), r.get("clicks"), r.get("impressions"), f"{(r.get('ctr') or 0):.1%}", f"{(r.get('position') or 0):.1f}"] for r in rows]))
    H.append('</section>')

    H.append('<section id="behavior"><h2>سلوك العملاء ومسار التحويل</h2>')
    H.append(empty("GA4 غير متصل.") if not ga else f'<p>GA4: لقطة {ltr(ga["window_start"])} → {ltr(ga["window_end"])}، {len(ga["payload"])} صف.</p>')
    if cl:
        cs = analysis.clarity_summary(cl["payload"])
        H.append("<h3>إشارات الاحتكاك (Clarity)</h3>" + table(["المؤشر", "أعلى الصفوف"],
                 [[e(k), e(json.dumps(v[:3], ensure_ascii=False))[:300]] for k, v in cs["friction_signals"].items()]))
    else:
        H.append(empty("Clarity غير متصل. ملاحظة: الواجهة تعيد آخر 1–3 أيام فقط و10 طلبات يوميًا؛ النظام يجمع يوميًا ويحفظ التاريخ."))
    H.append("<h3>ما الذي يمكن قياسه الآن في المسار؟</h3>" + table(["الخطوة", "طريقة القياس", "متاح؟", "ملاحظة"],
             [[e(s["step"]), e(s["measure"]), "✅" if s["measurable"] else "⛔", e(s["note"])] for s in analysis.funnel_measurability(conn)]))
    H.append('</section>')

    H.append('<section id="comp"><h2>ذكاء المنافسين</h2>' + table(["المنافس", "الحالة", "النطاقات", "بيانات مُتحقَّقة", "المصادر"],
             [[e(c["name"]), e(c["status"]), "<br>".join(ltr(d) for d in c["domains"]), e(json.dumps(c["data"], ensure_ascii=False))[:300],
               "<br>".join(e(s) for s in c["sources"])] for c in comps]) + '</section>')

    H.append('<section id="actions"><h2>مركز إجراءات GEO</h2>' + table(
        ["الأولوية", "الإجراء", "الدليل", "الأثر", "الثقة", "الجهد", "يحتاج موافقة", "الحالة", "خطة التحقق", "نتيجة التحقق"],
        [[e(r["priority"]), e(r["title"]), e(r["evidence"].get("evidence", ""))[:220], f"{r['impact']}/5", f"{r['confidence']}/5", f"{r['effort']}/5",
          e(r["approval_reason"] or "لا"), e(r["state"]), e(r["verification_plan"]), e(r["verification_result"] or "—")] for r in recs]))
    H.append("<h3>التجارب المقترحة</h3>" + table(["التجربة", "الفرضية", "المؤشر الأساسي", "الحالة"],
             [[e(x["id"]), e(json.loads(x["data"])["hypothesis"]), e(json.loads(x["data"])["primary_kpi"]), e(x["status"])] for x in exps]) + '</section>')

    H.append('<section id="facts"><h2>سجل حقائق مجسّم</h2><p class="note">لا يُستخدم في المحتوى أو البيانات المنظمة إلا ما اعتمده المالك.</p>' + table(
        ["المعرّف", "الادعاء", "القيمة", "المصدر", "الثقة", "الحالة", "معتمد للنشر", "إعادة التحقق قبل"],
        [[ltr(f["id"]), e(f["claim"]), e(f["value"]), e(f["source"])[:160], e(f["confidence"]), f'<span class="pill st-{e(f["status"])}">{e(f["status"])}</span>',
          "✅" if f["public_approved"] else "—", ltr(f["revalidate_by"])] for f in facts]) + '</section>')

    H.append('<section id="materials"><h2>توافر الخامات</h2>' + table(["الخامة", "التوافر", "البيانات", "المصدر"],
             [[ltr(m["name"]), e(m["availability"]), e(m["data"])[:250], e(m["source"])] for m in mats]) + '</section>')

    H.append('<section id="integrations"><h2>حالة التكاملات</h2>' + table(["التكامل", "الحالة", "آخر فحص", "آخر نجاح", "آخر خطأ / تفاصيل"],
             [[ltr(h["name"]), f'<span class="pill s-{e(h["status"])}">{e(h["status"])}</span>', ltr(h["last_checked"]), ltr(h["last_success"] or "—"),
               e((h["last_error"] or h["detail"] or ""))[:220]] for h in health]))
    H.append("<h3>هويات البريد</h3>" + table(["الحساب", "التصنيف", "الدليل"],
             [[ltr(_mask(m["account"])), e(m["classification"]), e(m["evidence"])[:200]] for m in emails]))
    H.append("<h3>آخر المهام</h3>" + table(["المهمة", "الحالة", "الوقت", "التفاصيل"],
             [[e(r["task"]), e(r["status"]), ltr(r["finished_at"]), e(r["detail"] or "")[:160]] for r in runs]))
    H.append("<h3>التقارير</h3>" + table(["الدورية", "الفترة", "الملف"],
             [[e(r["cadence"]), ltr(f"{r['period_start']} → {r['period_end']}"), ltr(r["path"])] for r in reports]))
    H.append('</section></main></body></html>')
    return "".join(H)


def _mask(a):
    from .email_identity import mask
    return mask(a)


def api_payload(conn, path: str):
    if path == "/api/health":
        return db.rows(conn, "SELECT * FROM integration_health")
    if path == "/api/backlog":
        return backlog.ranked(conn, 200)
    if path == "/api/findings":
        return db.rows(conn, "SELECT * FROM audit_findings")
    if path == "/api/facts":
        return db.rows(conn, "SELECT * FROM facts")
    if path == "/api/visibility":
        return analysis.visibility_metrics(conn, "2000-01-01", "2999-12-31")
    return None


def serve(conn, host="127.0.0.1", port=8765):
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.startswith("/api/"):
                data = api_payload(conn, self.path.split("?")[0])
                body = json.dumps(data, ensure_ascii=False, default=str).encode() if data is not None else b"{}"
                self.send_response(200 if data is not None else 404)
                self.send_header("Content-Type", "application/json; charset=utf-8")
            else:
                body = render(conn).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer((host, port), H)
    print(f"Dashboard: http://{host}:{port}/")
    srv.serve_forever()
