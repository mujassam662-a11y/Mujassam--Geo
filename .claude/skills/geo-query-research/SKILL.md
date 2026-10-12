---
name: geo-query-research
description: Expand the GEO prompt library from real demand: Search Console queries, customer questions, support logs, competitor content. Use when adding or revising prompts.
---

# geo-query-research

## Procedure
1. Pull candidate questions: GSC queries with question words (ازاي، كام، فين، ايه، how, where, which), WhatsApp FAQs supplied by owner, AI answers' follow-up suggestions.
2. Cluster by intent: discovery, pricing, how_to, materials, use_case, prototype, comparison, brand.
3. Keep one representative per cluster per language (ar-EG, ar MSA, en). Avoid near-duplicates.
4. Add to `data/prompts.json` with a new id, version 1, and `source` naming the evidence. Editing text = bump version.
5. Run `python -m geo init` to load.

## Output
JSON entries `{id, version, language, intent, text, source}` + a note of the evidence for each.
