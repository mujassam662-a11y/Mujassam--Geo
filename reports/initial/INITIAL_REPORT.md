# Initial execution and test report (2026-10-12)

## 1. Environment inspection
- No Mujassam repository exists. The GitHub account has 3 unrelated private repos: medication-reminder-bot, choroida-support, desktop-tutorial.
  The system was built as a new self-contained codebase at `/mnt/project-files/mujassam-geo` (not pushed anywhere).
- No existing Claude Code agents, Skills, connectors, databases, dashboards, n8n workflows or credentials were found in the environment.
- No GA4, Search Console, Clarity or Bing credentials are present. The only environment identity is the AI session operator's email.
- The build container's network policy blocks direct HTTPS to mujassam.net (proxy CONNECT 403). The live audit was done with a
  web-fetch tool that returns rendered page text. Raw-HTML checks are marked as hypotheses until `python -m geo audit` runs from a normal machine.

## 2. Deliverables status
| # | Deliverable | Status |
|---|---|---|
| 1 | 11 agent definitions | Completed and tested (frontmatter, tools and sections validated by tests) |
| 2 | 19 Skills | Completed and tested (discoverability + structure tests) |
| 3 | Orchestrator | Completed and tested (daily/weekly runs, parallel fetch, skip-unchanged, failure logging) |
| 4 | Connectors (GA4, GSC, Clarity, Bing, crawler, AI proxies) | Implemented and tested against fake HTTP responses (success, 401, 403, 429, network failure). **Not tested against the live APIs: waiting for credentials.** |
| 5 | Persistent evidence storage | Completed and tested (SQLite, dedup, history, freshness) |
| 6 | Arabic RTL dashboard | Completed and tested (render test + browser screenshot at 1280px and 390px, RTL, no horizontal overflow) |
| 7 | Scheduling | cron + importable n8n workflow written; intervals tested. **Not installed on any server** (none available). |
| 8 | Fact registry | Completed: 35 facts from the live site, 8 open conflicts, 0 owner-approved |
| 9 | Manufacturing knowledge base | Implemented (schema, CSV import, permission gate). Empty: no job records supplied |
| 10 | Material availability | Completed: PLA, PETG available_now; ABS unverified (conflict) |
| 11 | Prompt library | Completed: 18 prompts (8 Egyptian Arabic, 4 MSA, 6 English, including brand-accuracy prompts) + 126-row sampling template |
| 12 | Competitor analysis | Implemented; 3 entries (Tashkeel verified active; Printfy3D candidate; Khamsat freelancers) |
| 13 | Reports | Completed and tested; first daily report: `reports/daily/2026-10-12.md` |
| 14 | Initial GEO + technical audit | Done via rendered page text (see §3). Raw-HTML crawl failed in this environment with evidence |
| 15 | Prioritised backlog | Completed: 18 recommendations, all requiring owner approval because they touch the live site |
| 16 | Automated tests | 37 tests, all passing (§5) |
| 17-18 | Operations + integration docs | `docs/OPERATIONS.md`, `docs/SETUP_INTEGRATIONS.md`, `docs/AI_PLATFORMS.md` |
| 19 | This report | Done |

## 3. Integration status (real probes, `python -m geo status`)
| Integration | Status | Evidence |
|---|---|---|
| website_crawler | FAILED_WITH_EVIDENCE | `URLError: Tunnel connection failed: 403 Forbidden` (container network policy, not the website) |
| ga4 | REQUIRES_CREDENTIALS | GA4_PROPERTY_ID + Google credentials missing |
| search_console | REQUIRES_CREDENTIALS | Google credentials missing |
| clarity | REQUIRES_CREDENTIALS | CLARITY_API_TOKEN missing |
| bing_webmaster | REQUIRES_CREDENTIALS | API key missing |
| Bing AI Performance | UNSUPPORTED_OR_UNAVAILABLE (API) | UI export only; CSV importer ready |
| ChatGPT / AI Overviews / AI Mode / Copilot / Perplexity / Gemini / Claude | UNSUPPORTED_OR_UNAVAILABLE (API) | Manual sampling; template ready |
| perplexity_api, claude_api_websearch | REQUIRES_CREDENTIALS | Optional proxies |
| business_orders | REQUIRES_PERMISSION | No order export supplied |
| Email | Sending disabled by design | Session identity classified UNKNOWN_OWNERSHIP |

**AI visibility baseline: not established yet.** No observations exist, so no mention or citation rates are reported.

## 4. Initial audit (live site, 2026-10-12)
Pages read: /, /pricing, /contact, /guide, /resources, /refund-policy, /privacy, /terms, robots.txt, sitemap.xml (8 URLs).

**Confirmed issues**
1. Materials conflict: /pricing lists ABS (10 EGP/g), while the home FAQ says only PLA and PETG. (high)
2. Payment conflict: home/guide say InstaPay or Vodafone Cash; privacy names Paymob, Kashier, Stripe. (high)
3. Cancellation conflict: FAQ says within 1 hour; refund policy says until printing starts. (high)
4. Delivery wording mixes production time ("2 working days") and door delivery ("within two days"). (medium)
5. Layer height: home 0.28/0.16 mm vs guide default 0.2 mm. (low)
6. Resources page says "3 verified sites" but lists six. (low)
7. Contact hours "10:00–18:04" with Friday unlisted. (low)
8. Sitemap lastmod values are identical build timestamps. (low)
9. Policy pages have no "last updated" date. (low)

**Hypotheses (need raw HTML or repeated observation)**
- No JSON-LD structured data on the homepage. A schema draft is ready at `docs/schema-draft.jsonld`; do not deploy it yet.
- html lang/dir not verifiable.
- The "valid today only" 50% discount may be a permanent label (false-urgency and AI-accuracy risk).
- The privacy policy says no third-party tracking, so enabling GA4/Clarity would need a policy update first.
- Content gaps: material guide, worked price examples, real case studies (`reports/initial/content_briefs.md`).
- No English version; licensed characters in the showcase.

**Unverified claims (do not repeat until evidence is supplied)**
- "Companies and makers who worked with us": AUC, GUC, Nile University, Cairo University, Fab Lab Egypt, ITI.
- Three unsourced testimonials.

**Passes**
- robots.txt allows all search and surfacing crawlers on public pages and blocks admin/checkout paths. OAI-SearchBot is
  not named and falls under the allow-all default. GPTBot, ClaudeBot and Bingbot have a 2 s crawl-delay; Bytespider is blocked.
- Canonical, meta robots (index, follow), Open Graph (ar_EG) present on home.
- Allowed by robots ≠ indexed ≠ cited. Indexing needs GSC; citation needs the visibility baseline.

**Competitors (sources dated 2026-10-12)**
- Tashkeel (tashkeel.pro): active marketplace model with partner printers; STL/OBJ/3MF; file-based estimate stated as not final; no public price list.
  Mujassam's published per-gram and per-hour price list is a verifiable differentiator worth stating clearly.

## 5. Tests actually executed
`python3 -m pytest` in `tests/`: **37 passed, 0 failed** (also passes with `python3 -m unittest discover -s tests`).
A defect found and fixed during testing: sharing one SQLite connection across fetch threads raised `InterfaceError`.
The fix gives each worker its own connection (WAL mode), and a regression test covers it.

- test_connectors.py::TestGA4::test_401_and_403_are_classified_and_secret_redacted
- test_connectors.py::TestGA4::test_missing_credentials_reported_not_simulated
- test_connectors.py::TestGA4::test_network_error_is_failed_with_evidence
- test_connectors.py::TestGA4::test_success_parses_rows_and_stores_snapshot
- test_connectors.py::TestGSC::test_paging_and_brand_classes
- test_connectors.py::TestClarity::test_429_is_failure
- test_connectors.py::TestClarity::test_overlapping_windows_flagged_and_duplicates_ignored
- test_connectors.py::TestClarity::test_parameters_validated
- test_connectors.py::TestClarity::test_sync_respects_budget_and_records_windows
- test_connectors.py::TestBing::test_ai_performance_csv_import
- test_connectors.py::TestBing::test_site_not_verified_is_permission_problem
- test_definitions.py::TestAgents::test_eleven_agents_with_valid_frontmatter
- test_definitions.py::TestAgents::test_orchestrator_documents_schema_and_completion
- test_definitions.py::TestSkills::test_all_required_skills_discoverable
- test_definitions.py::TestSkills::test_skill_frontmatter_and_actionable_body
- test_system.py::TestCrawler::test_crawl_and_findings
- test_system.py::TestCrawler::test_parse_html
- test_system.py::TestCrawler::test_robots_matrix_separates_bots
- test_system.py::TestVisibility::test_generic_arabic_word_is_not_brand
- test_system.py::TestVisibility::test_import_dedup_and_metrics
- test_system.py::TestVisibility::test_invalid_platform_rejected
- test_system.py::TestFactsBacklogSafety::test_backlog_state_machine_requires_human_and_approval
- test_system.py::TestFactsBacklogSafety::test_conflicts_and_approval
- test_system.py::TestFactsBacklogSafety::test_draft_check_flags_unverified_claims
- test_system.py::TestFactsBacklogSafety::test_unknown_action_requires_approval
- test_system.py::TestEmailIdentity::test_classification_and_send_block
- test_system.py::TestSecrets::test_env_example_has_placeholders_only_and_gitignore
- test_system.py::TestSecrets::test_no_secret_like_strings_in_repo
- test_system.py::TestSecrets::test_redaction
- test_system.py::TestOrchestratorReportsDashboard::test_daily_run_records_honest_statuses_and_report
- test_system.py::TestOrchestratorReportsDashboard::test_dashboard_rtl_no_fabricated_data_no_secrets
- test_system.py::TestOrchestratorReportsDashboard::test_parallel_fetches_on_file_db
- test_system.py::TestOrchestratorReportsDashboard::test_successful_crawl_pipeline_and_skip_unchanged
- test_system.py::TestBusinessData::test_experiment_verdict_conservative
- test_system.py::TestBusinessData::test_materials_and_knowledge_base
- test_system.py::TestBusinessData::test_orders_import_drops_pii_and_margin_needs_costs
- test_system.py::TestSchedule::test_cron_and_n8n_intervals

## 6. Prioritised backlog (all items need owner approval before any site change)
| Priority | Recommendation | Approval |
|---|---|---|
| 16.67 | ABS listed on pricing page but FAQ says only PLA and PETG are offered | yes |
| 16.67 | Payment methods differ between pages | yes |
| 10.0 | Delivery time wording mixes production and door delivery | yes |
| 7.14 | Cancellation window conflicts (1 hour vs until printing starts) | yes |
| 6.67 | Layer height values differ (0.28/0.16 mm vs default 0.2 mm) | yes |
| 6.67 | Resources page says '3 verified sites' but lists six | yes |
| 6.67 | Opening hours show 18:04 and omit Friday | yes |
| 4.0 | Sitemap lastmod values are build timestamps, not page change dates | yes |
| 4.0 | Privacy, terms and refund pages show no 'last updated' date | yes |
| 3.6 | 'Companies and makers who worked with us' logos have no supporting evidence | yes |
| 2.4 | Testimonials have no verifiable source | yes |
| 2.0 | No JSON-LD structured data detected on homepage | yes |
| 1.71 | 'Valid today only' 50% discount may be a permanent label | yes |
| 1.6 | html lang/dir attributes not verifiable from rendered text | yes |
| 1.6 | Showcase includes licensed characters (Spider-Man, Shaun the Sheep) | yes |
| 1.33 | Privacy policy says no third-party tracking; installing GA4 or Clarity would contradict it | yes |
| 1.33 | No in-depth pages for material choice, worked price examples, or real case studies | yes |
| 0.89 | No English page version, while English prompts are part of the target set | yes |

## 7. What the owner needs to provide
1. Confirmation of the conflicting facts: materials (ABS?), payment methods, cancellation rule, opening hours, discount status, delivery wording.
2. Evidence and permission for the "worked with us" organisations, or removal.
3. GA4 property ID, a Search Console property and a Clarity token (or a service account, see docs/SETUP_INTEGRATIONS.md), and a Bing API key.
4. The mapping of GA4 events to upload / quote / checkout.
5. An order CSV export and verified cost figures, for the funnel and margin analysis.
6. One manual AI-visibility sample round using `data/ai_samples.template.csv`, which establishes the baseline.
7. Email: confirm whether the AI session identity account is a Mujassam account (currently UNKNOWN_OWNERSHIP, not used).
