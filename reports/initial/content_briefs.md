# Content briefs (proposals, written 2026-10-12)

All briefs need demand confirmation from Search Console and owner-approved facts before drafting. Fix the existing-page conflicts first (backlog).

## 1. Material guide: PLA vs PETG (vs ABS if confirmed)
- **Audience:** engineering students, makers, small businesses choosing a material
- **Customer question:** "إيه أفضل خامة لقطعة ميكانيكية حسب الاستخدام؟" / "PLA ولا PETG؟"
- **GEO intent:** materials (prompts eg-material-mech, msa-pla-petg)
- **Value beyond existing content:** the homepage section and guide are short, and availability conflicts. One accurate page with price per gram, colours, limits and "when not to use".
- **Evidence needed:** owner-confirmed materials list and prices (facts materials.offered, pricing.*), knowledge-base jobs showing real use (permissioned)
- **Title / outline:** "PLA ولا PETG؟ تختار خامة الطباعة إزاي (بالأسعار)"; H2: الفرق في سطر · استخدامات كل خامة · حدود كل خامة · السعر لكل جرام والألوان · أمثلة من شغلنا · أسئلة
- **URL / links:** /materials. Linked from home #use-cases, /guide and /pricing; links out to upload and /pricing.
- **Verify:** registry facts approved; no property claims beyond the site's own qualitative statements unless tested.
- **Outcome / metrics:** fewer wrong-material orders, citation on material prompts, GSC clicks to /materials.

## 2. How the instant price is calculated (worked examples)
- **Audience:** first-time customers comparing prices
- **Question:** "إزاي أحسب تكلفة الطباعة ثلاثية الأبعاد قبل ما أطلب؟" / "كام سعر طباعة 3D في مصر؟"
- **Value:** the formula exists on /pricing, but there are no worked, real examples with discount, packaging and shipping shown separately.
- **Evidence:** 3 to 5 real anonymised quotes (weight, minutes, material) from the knowledge base; the confirmed discount status
- **Outline:** المعادلة · 3 أمثلة حقيقية · إيه اللي بيغيّر السعر (سُمك الطبقة، الحشو، الدعامات) · الشحن · صلاحية التسعيرة 7 أيام
- **URL:** section on /pricing (preferred over a new page)
- **Metrics:** quote→checkout rate (experiment exp-price-breakdown), pricing-prompt citations

## 3. Graduation-project printing guide
- **Audience:** engineering students
- **Question:** "محتاج أطبع قطعة ميكانيكية لمشروع تخرجي، أروح لمين؟"
- **Value:** none exists. Practical tolerances, file prep, timing before deadlines, with real (permissioned) student-project examples.
- **Evidence:** knowledge-base jobs with publication_permission; owner-confirmed turnaround
- **URL:** /graduation-projects. Links: /guide, /materials, upload.
- **Metrics:** use_case prompt mentions, uploads from this landing page

## 4. File preparation checklist (STL/3MF/STEP)
- **Question:** "فين أقدر أطبع ملف STL في مصر؟" + "ملفي مش بيتسعّر ليه؟"
- **Value:** expands /guide with the real accepted formats, the 40 MB limit, thin walls, and common failures from real jobs.
- **Evidence:** support questions from WhatsApp (owner-supplied, anonymised), upload error logs if available
- **URL:** extend /guide (no new page)
