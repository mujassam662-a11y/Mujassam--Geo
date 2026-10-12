---
name: clarity-behavior-analysis
description: Analyse Microsoft Clarity Data Export snapshots for friction (dead/rage clicks, quick-backs, script errors, scroll depth) by URL and device.
---

# clarity-behavior-analysis

## Constraints (official docs, verified 2026-10-12)
Endpoint project-live-insights; numOfDays 1-3 only; ≤3 dimensions; 10 requests/project/day; ≤1000 rows; UTC.
History accumulates only from daily collection; overlapping windows are flagged in `clarity_windows`.

## Procedure
1. Load latest snapshots (`analysis.latest_snapshot(conn,'clarity','live_insights')`) and `analysis.clarity_summary`.
2. Rank URLs by friction per session, not raw counts; split mobile vs desktop.
3. For each top issue: evidence (metric, window), likely explanation (hypothesis), proposed change, how to verify.

## Output
`[{url, device, metric, value, window, hypothesis, proposal, verify}]` — aggregated only, no recordings or personal data.
