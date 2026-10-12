---
name: brand-entity-consistency
description: Check that Mujassam's identity facts are identical across pages, profiles and structured data, and propose schema only from approved facts.
---

# brand-entity-consistency

## Procedure
1. For each fact category (identity, contact, service, materials, pricing, payment, delivery, policy), list every page that states it.
2. Extract the exact wording + URL + date. Mark consistent / conflict / unverified.
3. For conflicts open a backlog item and ask the owner one concrete question (options + recommendation).
4. Schema: draft Organization/WebSite (always), LocalBusiness (only with confirmed public address + hours), Service (real services), BreadcrumbList. Validate with Rich Results Test before proposing.

## Output
`[{fact_id, statements:[{url, text, seen_at}], verdict, owner_question?}]` and `docs/schema-draft.jsonld`.
