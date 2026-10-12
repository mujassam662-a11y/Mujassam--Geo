---
name: material-availability-intelligence
description: Maintain verified material availability, prices, colours and limits; flag affected pages when they change.
---

# material-availability-intelligence

## States
available_now · temporarily_unavailable · planned · unverified

## Procedure
1. Update `data/materials.json` from the owner's inventory or pricing engine (source + verified_at).
2. `python -m geo init` -> change events list affected pages (/pricing, home materials + FAQ, /guide, facts).
3. Only `registry.advertisable_materials(conn)` may be advertised; new materials need `approve advertise_material`.

## Output
`[{material, from, to, affected:[...], action_needed}]`
