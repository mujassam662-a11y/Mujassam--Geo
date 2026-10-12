---
name: technical-discoverability-audit
description: Procedure and severity standard for crawlability, indexability and AI-crawler access checks on mujassam.net.
---

# technical-discoverability-audit

## Checks (each with URL, evidence, timestamp)
status codes · redirect chains · canonical · meta robots / X-Robots-Tag · robots.txt matrix per bot · sitemap coverage & lastmod ·
orphan pages · broken links/images · titles/descriptions/H1 · duplicate titles · html lang/dir (ar, rtl) · server-rendered text ·
JSON-LD validity/types · images alt · CDN/WAF bot responses · Core Web Vitals (only if measured).

## Severity
high = blocks indexing/crawling of a money page or wrong business info · medium = weakens understanding/trust · low = hygiene · info = pass.

## Three separate outcomes
allowed by robots ≠ indexed ≠ cited. Report each with its own evidence source (robots matrix, GSC/Bing index status, visibility observations).

## Output
Findings in the schema used by `geo/connectors/crawler.py::analyze_crawl`.
