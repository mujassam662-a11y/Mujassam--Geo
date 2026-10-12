---
name: email-identity-verification
description: Classify connected email identities and block brand use or sending until ownership and authorisation are confirmed.
---

# email-identity-verification

## Classes
VERIFIED_MUJASSAM · LIKELY_MUJASSAM · UNKNOWN_OWNERSHIP · UNRELATED_OR_PERSONAL · ACCESS_UNAVAILABLE

## Procedure
1. `python -m geo email scan` (masked output).
2. For each non-verified account ask the owner: "Is <masked account> a Mujassam business account authorised for <use>? yes/no".
3. On written yes: `python -m geo email confirm <account> VERIFIED_MUJASSAM --by <owner>`.
4. Sending remains blocked unless env flags + approval exist (`email_identity.assert_can_send`).

## Output
`[{account_masked, classification, evidence:[...], question_for_owner?}]`
