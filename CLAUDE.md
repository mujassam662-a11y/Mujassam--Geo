# Mujassam GEO system: working rules for Claude Code

- Python 3.11+ standard library only (`geo/`). Run commands as `python3 -m geo ...`. Tests: `python3 -m unittest discover -s tests`.
- Agents live in `.claude/agents/`, Skills in `.claude/skills/`. Start with the `geo-orchestrator` agent.
- Evidence store: `var/geo.sqlite3`. Never edit it by hand; use the CLI.
- Never fabricate metrics, citations, competitor data, customers or business facts. Missing data is reported as missing.
- Public content and schema may use only facts with `public_approved=1`.
- Publishing, pricing/policy changes, outreach, email and deploys require a recorded approval (`python3 -m geo approve`).
- Never print secrets. `.env` is gitignored; `Config.redact` wraps all output.
- In Arabic, "مجسّم" alone is a generic word (a 3D model), so it does not count as a brand mention.
- Historical business figures (AOV 360 EGP, ~300 customers, ~2000 uploads, ~100 orders/month, target 500) are unverified and confidential.
