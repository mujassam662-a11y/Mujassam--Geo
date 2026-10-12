---
name: publication-safety-check
description: Gate any outward-facing action (publish, pricing, policy, outreach, email, deploy) behind evidence and recorded approval.
---

# publication-safety-check

## Checklist (all must pass)
1. Every claim maps to an approved fact or permissioned job (`check-draft` returns []).
2. No customer data, files or confidential designs; no licensed characters without rights.
3. No fake urgency, fake reviews, unverified partner logos.
4. Legal/privacy/pricing/delivery changes: owner + legal review noted.
5. Approval recorded: `python -m geo approve <action> <target> --by <name>`.
6. Rollback plan written.

## Output
`{target, action, checks:{...}, approval:{by, at}|null, verdict: blocked|ready}`
