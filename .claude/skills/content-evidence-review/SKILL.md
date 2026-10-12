---
name: content-evidence-review
description: Review a page or draft for answer quality and factual support before publication. Use for any Mujassam content.
---

# content-evidence-review

## Procedure
1. Identify the customer question the page answers; is the answer in the first 2-3 sentences?
2. Every factual claim -> registry fact id (approved) or knowledge-base job id (permissioned). Unsupported -> remove or mark [needs evidence].
3. `python -m geo check-draft draft.md` must return [].
4. Check uniqueness vs existing pages; no near-duplicates.
5. Internal links: to /pricing, upload, relevant guide; from at least two related pages.

## Output
`{page, question, answer_first: bool, unsupported_claims: [], conflicts: [], duplicates: [], internal_links: {in:[], out:[]}, verdict: ready|revise}`
