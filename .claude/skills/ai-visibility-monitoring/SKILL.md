---
name: ai-visibility-monitoring
description: Measure brand mentions and citations of Mujassam in AI assistants with the versioned prompt library and honest sampling. Use for baselines, weekly runs and period comparisons.
---

# ai-visibility-monitoring

## Procedure
1. Export active prompts: `sqlite3 var/geo.sqlite3 "select id,version,language,text from prompts where active=1"`.
2. For each platform marked manual_sample: new chat, logged out where possible, Egypt locale, paste prompt verbatim, wait for full answer.
3. Record a CSV row per prompt x platform: prompt_id, prompt_version, platform, observed_at (YYYY-MM-DD), method, response_text,
   cited_urls (pipe separated, in order shown), accuracy, accuracy_notes, evidence_ref (screenshot file name), observer, sample_note.
4. `python -m geo import-observations file.csv`; duplicates are skipped.
5. Optional proxies (if keys set) run in the weekly pipeline and are labelled api_proxy.
6. Compare periods only with the same prompt versions and method (`analysis.compare_periods`).

## Output
Table per platform/language/intent: n, mention rate, official citation rate, unique cited Mujassam URLs, competitor mentions; with a small-sample warning when n < 10.

## Rules
Never invent citations; never scrape logged-in UIs; never generalise a sample to "platform-wide".
