# Integration setup

Copy `.env.example` to `.env`, fill the values, then run `python -m geo status`. A connector shows
`CONNECTED_AND_TESTED` only after a real request succeeds. Nothing is simulated.

| Integration | Status on 2026-10-12 | What you need |
|---|---|---|
| Website crawler | FAILED_WITH_EVIDENCE in the build container (proxy denied HTTPS to mujassam.net, CONNECT 403). Expected to work from any normal server or laptop. | Nothing. Run `python -m geo audit`. |
| GA4 Data API | REQUIRES_CREDENTIALS | GA4 property ID + service account |
| Search Console API | REQUIRES_CREDENTIALS | Verified property + service account |
| Microsoft Clarity Data Export | REQUIRES_CREDENTIALS | Project API token |
| Bing Webmaster API | REQUIRES_CREDENTIALS | API key + verified site |
| Bing AI Performance | UNSUPPORTED_OR_UNAVAILABLE by API | Manual export from the Webmaster Tools UI |
| AI assistants (ChatGPT, AI Overviews/AI Mode, Copilot, Perplexity, Gemini, Claude) | UNSUPPORTED_OR_UNAVAILABLE by API | Manual sampling (CSV) |
| Perplexity Sonar / Claude API web search (optional proxies) | REQUIRES_CREDENTIALS | API keys |
| Orders / business data | REQUIRES_PERMISSION | CSV export from the order system |
| Email | Disabled by design | See "Email" below |

## Google: GA4 + Search Console (one service account for both)
1. Google Cloud console > create a project > enable **Google Analytics Data API** and **Google Search Console API**.
2. IAM > Service accounts > create one (no roles needed) > Keys > Add key > JSON. Save it outside git, e.g. `secrets/sa.json`.
3. GA4 > Admin > Property access management > add the service-account email as **Viewer**. Copy the numeric **Property ID** into `GA4_PROPERTY_ID`.
4. Search Console > Settings > Users and permissions > add the service-account email (Restricted is enough).
   Use `GSC_SITE_URL=sc-domain:mujassam.net` for a domain property, or `https://mujassam.net/` for a URL-prefix property.
5. `pip install google-auth requests`, set `GOOGLE_APPLICATION_CREDENTIALS=secrets/sa.json`.
6. `python -m geo status`, which should show `ga4` and `search_console` as CONNECTED_AND_TESTED.
Scopes used: `analytics.readonly`, `webmasters.readonly`. GSC data lags 2-3 days; the pipeline reads windows ending 3 days ago.

After connecting GA4, tell the system which events mean upload, quote and checkout (they are not guessed). Find event names in the
dashboard or with `GA4Connector.event_inventory()`. Confirmed orders come from the order export, not from an event name.

> Privacy note: the live privacy policy says no third-party tracking. Update it (legal review) before enabling GA4 or Clarity collection on the site.

## Microsoft Clarity
Clarity project > Settings > Data Export > Generate new API token (project admin only). Set `CLARITY_API_TOKEN`.
Limits (official docs, checked 2026-10-12): last 1-3 days only, up to 3 dimensions, 10 requests per project per day, 1000 rows.
The system uses up to 6 requests a day (leaving 4 for manual use), runs daily, and keeps history from the first sync onward.
Older history cannot be retrieved through the API; use Clarity's dashboard exports if you need it.

## Bing Webmaster Tools
Bing Webmaster Tools > Settings > API access > API key. Set `BING_WEBMASTER_API_KEY` and `BING_SITE_URL`.
AI Performance (Copilot citations, grounding queries, cited pages): export it from the UI, then
`python -m geo import-bing-ai export.csv --start 2026-09-01 --end 2026-09-30 [--report ai_grounding_queries]`.

## AI visibility manual sampling
See `docs/AI_PLATFORMS.md`. Import with `python -m geo import-observations samples.csv`.

## Orders (for funnel and margin)
Export orders as CSV with columns from `data/knowledge_base/orders.template.csv`, then run `python -m geo import-orders orders.csv`.
Names, phones, emails and addresses are dropped, and customer IDs are hashed. Fill verified costs in
`data/cost_assumptions.template.json` (loader: insert into the `cost_assumptions` table) before margin analysis will run.

## Email
Sending is not implemented and is blocked by `email_identity.assert_can_send` unless all of these are true:
`GEO_EMAIL_SENDING_ENABLED=true`, `GEO_EMAIL_SENDING_AUTHORIZED_BY=<name>`, the account is VERIFIED_MUJASSAM
(`python -m geo email confirm ...`), and `python -m geo approve send_email <account> --by <name>` was recorded.
