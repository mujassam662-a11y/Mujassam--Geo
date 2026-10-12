---
name: geo-site-audit
description: Run a full GEO audit of mujassam.net combining technical crawl, fact consistency, content answers and AI visibility baseline. Use when asked for an audit or after a major site change.
---

# geo-site-audit

## Procedure
1. `python -m geo status` and note live vs missing sources.
2. `python -m geo audit` (technical crawl). If the network blocks the site, record FAILED_WITH_EVIDENCE and fall back to WebFetch page reads; mark raw-HTML checks as hypotheses.
3. Re-read every page in the sitemap for business facts; compare with `python -m geo facts list` (skill: brand-entity-consistency).
4. Review answers to the prompt library intents (skill: content-evidence-review).
5. Confirm the AI visibility baseline exists; if not, schedule a manual sample (skill: ai-visibility-monitoring).
6. Store findings; rank backlog; produce report (skill: geo-report-generation).

## Output
Findings JSON (see technical-discoverability-audit), separated into: confirmed defects · hypotheses · unverified facts · passes.
Plus a short Arabic summary with the top 5 actions and decisions needed from the owner.
