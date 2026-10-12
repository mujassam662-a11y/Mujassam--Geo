# نظام ذكاء GEO لمجسّم (Mujassam GEO Intelligence System)

نظام متعدد الوكلاء لقياس وتحسين ظهور مجسّم (mujassam.net) واستشهاد مساعدات الذكاء الاصطناعي به، مبني على أدلة حقيقية فقط.

## التشغيل السريع
```bash
cp .env.example .env            # املأ ما يتوفر لديك من مفاتيح
python3 -m geo init             # إنشاء قاعدة البيانات وتحميل الحقائق والأسئلة والمنافسين والتدقيق الأولي
python3 -m geo status           # اختبار حقيقي لكل تكامل
python3 -m geo run daily        # الدورة اليومية + تقرير في reports/daily/
python3 -m geo dashboard        # اللوحة على http://127.0.0.1:8765/
python3 -m unittest discover -s tests
```

## المكوّنات
| المكوّن | المكان |
|---|---|
| 11 وكيلًا (Claude Code agents) | `.claude/agents/` |
| 19 مهارة (Skills) | `.claude/skills/` |
| المنسّق المركزي | `geo/orchestrator.py` |
| الموصلات: GA4، Search Console، Clarity، Bing، الزاحف، AI | `geo/connectors/` |
| مخزن الأدلة (SQLite) | `geo/db.py` → `var/geo.sqlite3` |
| سجل الحقائق، الخامات، قاعدة المعرفة التصنيعية | `geo/registry.py`, `data/` |
| قائمة الإجراءات والموافقات | `geo/backlog.py`, `geo/safety.py` |
| سلامة هوية البريد | `geo/email_identity.py` |
| اللوحة العربية RTL | `geo/dashboard.py` |
| التقارير اليومية/الأسبوعية/الشهرية | `geo/reports.py` → `reports/` |
| الجدولة (cron + n8n) | `automation/` |
| التوثيق | `docs/` |
| التقرير الأولي | `reports/initial/INITIAL_REPORT.md` |

إعداد التكاملات: `docs/SETUP_INTEGRATIONS.md` · التشغيل اليومي والموافقات: `docs/OPERATIONS.md` · قياس منصات الذكاء الاصطناعي: `docs/AI_PLATFORMS.md`.
