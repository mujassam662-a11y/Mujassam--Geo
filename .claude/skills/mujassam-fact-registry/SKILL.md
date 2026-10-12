---
name: mujassam-fact-registry
description: Read, update, approve and check Mujassam public business facts and conflicts.
---

# mujassam-fact-registry

## Commands
- list: `python -m geo facts list`
- approve: `python -m geo facts approve <id> --by <owner> [--value "..."]`
- check a draft: `python -m geo check-draft draft.md`

## Rules
Authority order: owner written confirmation > operational system > legal pages > marketing pages > third parties.
Historical figures (AOV 360 EGP, ~300 customers, ~2000 uploads, ~100 orders/month, target 500) are NOT facts until confirmed from records, and are never published without permission.
When a fact changes, list affected URLs/drafts/reports and open backlog items.
