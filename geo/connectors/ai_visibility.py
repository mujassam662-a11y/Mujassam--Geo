"""AI visibility observations.

Measurement reality (checked 2026-10-12; re-check quarterly, see docs/AI_PLATFORMS.md):
  * ChatGPT Search, Google AI Overviews / AI Mode, Gemini app, Microsoft Copilot, Claude.ai, Perplexity app:
    no public API exposes what the consumer product shows a given user. -> `manual_sample` (a human runs
    the prompt in a clean session and records the answer + citations via CSV/JSON import).
  * Bing Webmaster Tools "AI Performance": aggregate Copilot/Bing AI citations for your site (UI export) -> bing.py.
  * Google Search Console: AI Overviews/AI Mode traffic is folded into Web search totals; no separate citation report.
  * Perplexity Sonar API and Anthropic Messages API + web_search tool return cited URLs. They are API *proxies*,
    not the consumer products; stored with method='api_proxy' and never merged with manual samples in reports.

Nothing here scrapes consumer UIs or bypasses authentication/anti-bot protections.
"""
from __future__ import annotations

import csv
import io
import json
import re
import urllib.parse

from .. import db
from .base import Connector, ConnectorError, REQUIRES_CREDENTIALS, UNSUPPORTED_OR_UNAVAILABLE

PLATFORMS = {
    "chatgpt_search": "manual_sample",
    "google_ai_overviews": "manual_sample",
    "google_ai_mode": "manual_sample",
    "microsoft_copilot": "manual_sample",
    "bing_ai": "official_export",
    "perplexity": "manual_sample",
    "gemini": "manual_sample",
    "claude": "manual_sample",
    "perplexity_api": "api_proxy",
    "claude_api_websearch": "api_proxy",
}
OFFICIAL_DOMAINS = {"mujassam.net", "www.mujassam.net"}
# "مجسّم/مجسم" is also the generic Arabic word for a 3D model/figurine, so a bare Arabic match is NOT a brand
# mention. Arabic counts only with a brand qualifier ("موقع مجسّم", "منصة مجسم" ...) or alongside the domain/Latin name.
BRAND_PATTERNS = [re.compile(p, re.I) for p in (
    r"mujassam",
    r"(?:موقع|منصة|منصّة|خدمة|شركة|متجر|براند)\s+(?:ال)?مجس[ّ]?م(?![ا-ي])",
    r"«\s*مجس[ّ]?م\s*»|\"\s*مجس[ّ]?م\s*\"",
)]
ACCURACY = {"accurate", "partially_accurate", "inaccurate", "not_applicable", "unreviewed"}


def domain_of(url: str) -> str:
    return urllib.parse.urlparse(url if "://" in url else "https://" + url).netloc.lower()


def brand_mentioned(text: str) -> bool:
    return any(p.search(text or "") for p in BRAND_PATTERNS)


def detect_competitors(text: str, urls: list[str], competitors: list[dict]) -> set[str]:
    found = set()
    low = (text or "").lower()
    doms = {domain_of(u) for u in urls}
    for c in competitors:
        names = [n.lower() for n in c.get("names", [c.get("name", "")]) if n]
        cdoms = set(c.get("domains", []))
        if any(n in low for n in names) or any(d == cd or d.endswith("." + cd) for d in doms for cd in cdoms):
            found.add(c["id"])
    return found


def record_observation(conn, obs: dict, competitors: list[dict]) -> int | None:
    """Insert one observation; returns row id, or None if it is a duplicate."""
    platform = obs["platform"]
    if platform not in PLATFORMS:
        raise ValueError(f"Unknown platform {platform}")
    method = obs.get("method") or PLATFORMS[platform]
    if method not in ("manual_sample", "api_proxy", "official_export"):
        raise ValueError("method must be manual_sample | api_proxy | official_export")
    accuracy = obs.get("accuracy", "unreviewed")
    if accuracy not in ACCURACY:
        raise ValueError(f"accuracy must be one of {sorted(ACCURACY)}")
    text = obs.get("response_text", "") or ""
    urls = [u.strip() for u in obs.get("cited_urls", []) if u and u.strip()]
    mentioned = brand_mentioned(text) or any(domain_of(u) in OFFICIAL_DOMAINS for u in urls)
    official = any(domain_of(u) in OFFICIAL_DOMAINS for u in urls)
    key = db.stable_hash([obs["prompt_id"], obs.get("prompt_version", 1), platform, obs["observed_at"], method, text[:2000], sorted(urls)])
    cur = conn.execute(
        "INSERT OR IGNORE INTO visibility_observations(dedup_key,prompt_id,prompt_version,platform,observed_at,method,"
        "response_excerpt,brand_mentioned,official_site_cited,accuracy,accuracy_notes,evidence_ref,observer,sample_note,kind,created_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (key, obs["prompt_id"], obs.get("prompt_version", 1), platform, obs["observed_at"], method, text[:4000],
         int(mentioned), int(official), accuracy, obs.get("accuracy_notes"), obs.get("evidence_ref"),
         obs.get("observer"), obs.get("sample_note"), "observed", db.now_iso()))
    if cur.rowcount == 0:
        conn.commit()
        return None
    oid = cur.lastrowid
    comp_by_domain = {d: c["id"] for c in competitors for d in c.get("domains", [])}
    for pos, u in enumerate(urls, 1):
        d = domain_of(u)
        conn.execute("INSERT OR IGNORE INTO citations(observation_id,url,domain,is_official,competitor_id,position) VALUES(?,?,?,?,?,?)",
                     (oid, u, d, int(d in OFFICIAL_DOMAINS), comp_by_domain.get(d) or comp_by_domain.get(d.removeprefix("www.")), pos))
    for cid in detect_competitors(text, urls, competitors):
        conn.execute("INSERT OR IGNORE INTO competitor_mentions(observation_id,competitor_id) VALUES(?,?)", (oid, cid))
    conn.commit()
    return oid


def import_observations(conn, path_or_text: str, competitors: list[dict], fmt: str | None = None) -> dict:
    """Import manual samples. CSV columns: prompt_id,prompt_version,platform,observed_at,method,response_text,
    cited_urls (space/pipe separated),accuracy,accuracy_notes,evidence_ref,observer,sample_note. JSON: list of objects."""
    text = path_or_text
    if "\n" not in path_or_text and len(path_or_text) < 500:
        with open(path_or_text, encoding="utf-8") as f:
            text = f.read()
        fmt = fmt or ("json" if path_or_text.endswith(".json") else "csv")
    items = json.loads(text) if fmt == "json" else list(csv.DictReader(io.StringIO(text.lstrip("﻿"))))
    added = dup = empty = 0
    for it in items:
        if not (it.get("observed_at") or "").strip() or not (it.get("response_text") or "").strip():
            empty += 1  # unfilled template row: never recorded as an observation
            continue
        if isinstance(it.get("cited_urls"), str):
            it["cited_urls"] = re.split(r"[|\s]+", it["cited_urls"].strip()) if it["cited_urls"].strip() else []
        it["prompt_version"] = int(it.get("prompt_version") or 1)
        if record_observation(conn, it, competitors):
            added += 1
        else:
            dup += 1
    return {"added": added, "duplicates": dup, "skipped_empty": empty}


class PerplexityProxy(Connector):
    """Perplexity Sonar API (https://docs.perplexity.ai). Returns `citations`/`search_results`. Proxy only."""
    name = "perplexity_api"
    required_env = ("PERPLEXITY_API_KEY",)
    docs_url = "https://docs.perplexity.ai/"

    def ask(self, prompt: str) -> dict:
        if self.missing_env():
            raise ConnectorError(REQUIRES_CREDENTIALS, "PERPLEXITY_API_KEY missing")
        r = self.transport.request("POST", "https://api.perplexity.ai/chat/completions",
                                   headers={"Authorization": f"Bearer {self.config.get('PERPLEXITY_API_KEY')}"},
                                   json_body={"model": "sonar", "messages": [{"role": "user", "content": prompt}]})
        self.classify_http(r, "Perplexity chat/completions")
        d = r.json() or {}
        text = ((d.get("choices") or [{}])[0].get("message") or {}).get("content", "")
        urls = d.get("citations") or [s.get("url") for s in d.get("search_results", []) if s.get("url")]
        return {"response_text": text, "cited_urls": urls}

    def _probe(self):
        self.ask("ping")
        return "Sonar request succeeded"


class ClaudeWebSearchProxy(Connector):
    """Anthropic Messages API with the server-side web_search tool. Proxy only (not claude.ai)."""
    name = "claude_api_websearch"
    required_env = ("ANTHROPIC_API_KEY",)
    docs_url = "https://docs.claude.com/en/docs/agents-and-tools/tool-use/web-search-tool"
    model = "claude-sonnet-5-5"

    def ask(self, prompt: str) -> dict:
        if self.missing_env():
            raise ConnectorError(REQUIRES_CREDENTIALS, "ANTHROPIC_API_KEY missing")
        r = self.transport.request("POST", "https://api.anthropic.com/v1/messages",
                                   headers={"x-api-key": self.config.get("ANTHROPIC_API_KEY"), "anthropic-version": "2023-06-01"},
                                   json_body={"model": self.model, "max_tokens": 1024,
                                              "tools": [{"type": "web_search_20250305", "name": "web_search", "max_uses": 3}],
                                              "messages": [{"role": "user", "content": prompt}]})
        self.classify_http(r, "Anthropic messages")
        d = r.json() or {}
        text, urls = [], []
        for block in d.get("content", []):
            if block.get("type") == "text":
                text.append(block.get("text", ""))
                urls += [c.get("url") for c in block.get("citations", []) or [] if c.get("url")]
        return {"response_text": "\n".join(text), "cited_urls": list(dict.fromkeys(urls))}

    def _probe(self):
        r = self.transport.request("GET", "https://api.anthropic.com/v1/models",
                                   headers={"x-api-key": self.config.get("ANTHROPIC_API_KEY"), "anthropic-version": "2023-06-01"})
        self.classify_http(r, "Anthropic models")
        return "Models endpoint reachable with key"


def run_api_proxies(conn, config, prompts: list[dict], competitors: list[dict], transport=None) -> dict:
    """Run the active prompt set through configured proxies. Skips (honestly) when no key is set."""
    summary = {}
    for cls in (PerplexityProxy, ClaudeWebSearchProxy):
        c = cls(config, conn, transport)
        if c.missing_env():
            db.set_health(conn, c.name, REQUIRES_CREDENTIALS, "optional proxy; key not set")
            summary[c.name] = "skipped: REQUIRES_CREDENTIALS"
            continue
        n = 0
        for p in prompts:
            res = c.ask(p["text"])
            if record_observation(conn, {"prompt_id": p["id"], "prompt_version": p["version"], "platform": c.name,
                                         "observed_at": db.now_iso()[:10], "method": "api_proxy", **res,
                                         "sample_note": "API proxy; not the consumer product"}, competitors):
                n += 1
        db.set_health(conn, c.name, "CONNECTED_AND_TESTED", f"{n} observations recorded", success=True)
        summary[c.name] = n
    for platform, method in PLATFORMS.items():
        if method == "manual_sample":
            db.set_health(conn, f"ai:{platform}", UNSUPPORTED_OR_UNAVAILABLE,
                          "No public visibility API; measured by controlled manual sampling (CSV import)")
    return summary
