# Operations

## Start
```bash
python3 -m pip install -r requirements.txt   # optional: only google-auth for service accounts
cp .env.example .env                           # fill what you have
python3 -m geo init                            # DB + facts + prompts + competitors + materials + initial audit
python3 -m geo status                          # real connection test for every integration
python3 -m geo run daily                       # full daily pipeline + report in reports/daily/
python3 -m geo dashboard                       # http://127.0.0.1:8765/  (or --export file.html)
python3 -m unittest discover -s tests          # or: cd tests && python3 -m pytest
```

## Schedule
cron: `automation/crontab.example`. n8n (self-hosted, Execute Command enabled): import `automation/n8n-workflow.json`.
Daily 06:15 · weekly Sunday 07:00 · monthly 1st 08:00 (Africa/Cairo).

| Cadence | What runs |
|---|---|
| Daily | load registries, email identity scan, integration tests, incremental GA4/GSC/Clarity/Bing, crawl of up to 30 pages, stale facts, backlog review, report |
| Weekly | same + full crawl + AI-visibility API proxies (if keys are set) + weekly report. Import manual samples the same day. |
| Monthly | same + period comparison, experiments, margin analysis |

Unchanged inputs are skipped (`task_runs.input_hash`). Failures are stored with status `failed` and redacted detail, and are shown in the report and dashboard.

## Approvals (nothing outward-facing happens without them)
```bash
python3 -m geo backlog list
python3 -m geo backlog move <rec-id> approved --by "<owner name>"
python3 -m geo approve publish_content <rec-id> --by "<owner name>"
python3 -m geo backlog move <rec-id> implemented --by dev
python3 -m geo backlog move <rec-id> verified --by dev --note "re-fetched /pricing on 2026-10-20: ABS removed"
python3 -m geo facts approve materials.offered --by "<owner>" --value "PLA, PETG"
```

## Data
SQLite at `var/geo.sqlite3` (gitignored). Back it up. Evidence rows carry `kind` = observed | computed | prediction | hypothesis.

## Claude Code
Agents: `.claude/agents/`. Skills: `.claude/skills/`. Open the folder in Claude Code and ask, for example,
"use the geo-orchestrator agent to run the weekly cycle".
