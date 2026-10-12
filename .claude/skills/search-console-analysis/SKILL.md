---
name: search-console-analysis
description: Analyse Google Search Console data: queries, pages, CTR, position, branded vs non-branded, opportunities and indexing.
---

# search-console-analysis

## Procedure
1. Use final data only (`dataState: final`), windows ending ≥3 days ago.
2. Brand split with `brand_class`: branded / ambiguous (bare "مجسم" is a generic word) / non_branded.
3. Opportunities: impressions ≥ 50 and (position 5-20 or CTR < 2%) -> hypotheses with the page to improve.
4. New questions: queries containing question words not yet in the prompt library -> skill geo-query-research.
5. Indexing: URL Inspection for money pages (home, pricing, guide) weekly; respect quota (2000/day/property).

## Output
Tables with window dates; every recommendation tagged hypothesis + verification (same query, next 28-day window).
