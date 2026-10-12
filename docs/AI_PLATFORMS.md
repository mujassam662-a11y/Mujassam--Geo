# AI platforms: what can be measured (checked 2026-10-12; re-check every quarter)

| Platform | Public visibility/citation API? | Method used |
|---|---|---|
| ChatGPT Search | No | manual_sample |
| Google AI Overviews / AI Mode | No separate report. GSC folds this traffic into Web search totals. | manual_sample + GSC |
| Microsoft Copilot / Bing AI | Aggregate citations in Bing Webmaster Tools "AI Performance" (UI, spreadsheet export). No API found. | official_export + manual_sample |
| Perplexity (app) | No | manual_sample |
| Perplexity Sonar API | Returns citations, but it is not the app | api_proxy (reported separately) |
| Gemini | No | manual_sample |
| Claude.ai | No | manual_sample |
| Claude API + web_search tool | Returns cited URLs, but it is not claude.ai | api_proxy (reported separately) |

## Manual sampling protocol
- Use the same prompt set and versions each period (`data/prompts.json`), on the same weekday.
- Start a new chat, logged out where the product allows, with the location set to Egypt where possible. Note the model or mode label shown.
- Paste the prompt verbatim, wait for the full answer, and save a screenshot as `evidence/<date>/<platform>/<prompt_id>.png`.
- Fill one CSV row per prompt and platform (columns in `.claude/skills/ai-visibility-monitoring/SKILL.md`).
- Review accuracy against the fact registry for answers that mention Mujassam.
- Answers vary run to run. Results describe this sample only.

## Crawlers (robots.txt tokens)
| Token | Purpose |
|---|---|
| OAI-SearchBot | Surfacing in ChatGPT search. Keep allowed for GEO. |
| GPTBot | OpenAI training. A separate choice from search. |
| ChatGPT-User | User-initiated fetches |
| Googlebot | Google Search, including AI Overviews and AI Mode |
| Google-Extended | Control token for Gemini use; not a crawler and does not affect Search |
| Bingbot | Bing and Copilot grounding |
| Claude-SearchBot / ClaudeBot / Claude-User | Anthropic search / training / user fetches |
| PerplexityBot / Perplexity-User | Perplexity indexing / user fetches |

Allowed by robots ≠ indexed ≠ cited. Each is measured separately.
