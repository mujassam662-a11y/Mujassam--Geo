"""Polite public-site crawler for technical discoverability audits.

Respects robots.txt for its own user agent, applies a crawl delay, stays on the site host,
and never logs in or submits forms. Evidence for every finding is kept (URL, status, timestamp).
"""
from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.robotparser
from dataclasses import dataclass, field
from html.parser import HTMLParser
from xml.etree import ElementTree

from .base import Connector

AI_AND_SEARCH_AGENTS = {
    # Agent token: purpose (verified against vendor docs; see docs/CRAWLERS.md)
    "OAI-SearchBot": "OpenAI - ChatGPT search results (surfacing/citation)",
    "ChatGPT-User": "OpenAI - user-initiated fetches inside ChatGPT",
    "GPTBot": "OpenAI - model training crawl (separate from search)",
    "Googlebot": "Google Search (incl. AI Overviews / AI Mode surfacing)",
    "Google-Extended": "Google - Gemini training/grounding control token (not a separate crawler)",
    "Bingbot": "Bing / Microsoft Copilot grounding",
    "ClaudeBot": "Anthropic - training crawl",
    "Claude-SearchBot": "Anthropic - search indexing for Claude answers",
    "Claude-User": "Anthropic - user-initiated fetches",
    "PerplexityBot": "Perplexity - search indexing",
    "Perplexity-User": "Perplexity - user-initiated fetches",
    "Applebot": "Apple search / Siri",
    "CCBot": "Common Crawl",
}


@dataclass
class PageResult:
    url: str
    final_url: str = ""
    status: int = 0
    redirect_chain: list = field(default_factory=list)
    content_type: str = ""
    title: str = ""
    meta_description: str = ""
    meta_robots: str = ""
    x_robots_tag: str = ""
    canonical: str = ""
    html_lang: str = ""
    html_dir: str = ""
    h1: list = field(default_factory=list)
    headings: list = field(default_factory=list)
    hreflang: list = field(default_factory=list)
    jsonld_types: list = field(default_factory=list)
    jsonld_errors: int = 0
    internal_links: list = field(default_factory=list)
    external_links: list = field(default_factory=list)
    images: list = field(default_factory=list)
    images_missing_alt: int = 0
    text_chars: int = 0
    scripts: list = field(default_factory=list)
    error: str = ""
    fetched_at: str = ""


class _Parser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.r = PageResult(url="")
        self._in = None
        self._buf = []
        self._jsonld = []
        self._text = 0
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "html":
            self.r.html_lang, self.r.html_dir = a.get("lang", ""), a.get("dir", "")
        elif tag == "title":
            self._in, self._buf = "title", []
        elif tag in ("h1", "h2", "h3"):
            self._in, self._buf = tag, []
        elif tag == "meta":
            name = (a.get("name") or a.get("property") or "").lower()
            if name == "description":
                self.r.meta_description = a.get("content", "")
            elif name in ("robots", "googlebot"):
                self.r.meta_robots = (self.r.meta_robots + " " + a.get("content", "")).strip()
        elif tag == "link":
            rel = a.get("rel", "").lower()
            if rel == "canonical":
                self.r.canonical = a.get("href", "")
            elif rel == "alternate" and a.get("hreflang"):
                self.r.hreflang.append((a["hreflang"], a.get("href", "")))
        elif tag == "a" and a.get("href"):
            self.r.internal_links.append(a["href"])
        elif tag == "img":
            self.r.images.append(a.get("src", ""))
            if not a.get("alt", "").strip():
                self.r.images_missing_alt += 1
        elif tag == "script":
            if a.get("type", "").lower() == "application/ld+json":
                self._in, self._buf = "jsonld", []
            else:
                self._skip += 1
                if a.get("src"):
                    self.r.scripts.append(a["src"])
        elif tag == "style":
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._in != "jsonld" and self._skip:
            self._skip -= 1
        if self._in and tag == ("script" if self._in == "jsonld" else self._in):
            txt = "".join(self._buf).strip()
            if self._in == "title":
                self.r.title = txt
            elif self._in == "jsonld":
                self._jsonld.append(txt)
            else:
                self.r.headings.append((self._in, txt))
                if self._in == "h1":
                    self.r.h1.append(txt)
            self._in = None

    def handle_data(self, data):
        if self._in:
            self._buf.append(data)
        if not self._skip and self._in != "jsonld":
            self._text += len(data.strip())

    def finish(self):
        self.r.text_chars = self._text
        for block in self._jsonld:
            try:
                self.r.jsonld_types.extend(_ld_types(json.loads(block)))
            except json.JSONDecodeError:
                self.r.jsonld_errors += 1
        return self.r


def _ld_types(obj):
    out = []
    if isinstance(obj, list):
        for o in obj:
            out += _ld_types(o)
    elif isinstance(obj, dict):
        t = obj.get("@type")
        if t:
            out += t if isinstance(t, list) else [t]
        for o in obj.get("@graph", []) or []:
            out += _ld_types(o)
    return out


def parse_html(html: str) -> PageResult:
    p = _Parser()
    p.feed(html)
    return p.finish()


def parse_sitemap(xml_text: str) -> tuple[list[str], list[str]]:
    """Returns (page_urls, child_sitemaps)."""
    root = ElementTree.fromstring(xml_text.encode())
    ns = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
    pages = [e.text.strip() for e in root.iter(f"{ns}loc") if e.text] if root.tag == f"{ns}urlset" else []
    children = [e.text.strip() for e in root.iter(f"{ns}loc") if e.text] if root.tag == f"{ns}sitemapindex" else []
    return pages, children


def robots_matrix(robots_txt: str, urls: list[str]) -> dict:
    """For each crawler token: which audited URLs robots.txt allows. 'Allowed' != indexed != cited."""
    rp = urllib.robotparser.RobotFileParser()
    rp.parse(robots_txt.splitlines())
    out = {}
    for agent, purpose in AI_AND_SEARCH_AGENTS.items():
        allowed = [u for u in urls if rp.can_fetch(agent, u)]
        out[agent] = {"purpose": purpose, "allowed": len(allowed), "blocked": [u for u in urls if u not in allowed],
                      "crawl_delay": rp.crawl_delay(agent)}
    return out


class SiteCrawler(Connector):
    name = "website_crawler"
    required_env = ()
    docs_url = "docs/SETUP_INTEGRATIONS.md#website-crawler"

    def __init__(self, config, conn=None, transport=None, delay: float | None = None, max_pages: int | None = None):
        super().__init__(config, conn, transport)
        self.base = config.site_url
        self.host = urllib.parse.urlparse(self.base).netloc
        self.delay = float(config.get("GEO_CRAWL_DELAY_SECONDS", "2")) if delay is None else delay
        self.max_pages = int(config.get("GEO_CRAWL_MAX_PAGES", "200")) if max_pages is None else max_pages
        self.robots_txt = ""
        self._rp = None

    def _probe(self) -> str:
        r = self.transport.request("GET", urllib.parse.urljoin(self.base, "/robots.txt"))
        self.classify_http(r, "GET robots.txt")
        return f"robots.txt reachable (HTTP {r.status})"

    def fetch(self, url: str) -> PageResult:
        from .. import db
        res = PageResult(url=url, fetched_at=db.now_iso())
        current, chain = url, []
        try:
            for _ in range(6):
                r = self.transport.request("GET", current, follow_redirects=False)
                if r.status in (301, 302, 303, 307, 308) and r.headers.get("location"):
                    chain.append((current, r.status))
                    current = urllib.parse.urljoin(current, r.headers["location"])
                    continue
                break
        except Exception as e:
            res.error = f"{type(e).__name__}: {e}"
            return res
        res.status, res.final_url, res.redirect_chain = r.status, current, chain
        res.content_type = r.headers.get("content-type", "")
        res.x_robots_tag = r.headers.get("x-robots-tag", "")
        if "html" in res.content_type:
            parsed = parse_html(r.text)
            parsed.url, parsed.final_url, parsed.status = url, current, r.status
            parsed.redirect_chain, parsed.content_type, parsed.x_robots_tag = chain, res.content_type, res.x_robots_tag
            parsed.fetched_at = res.fetched_at
            norm = []
            for href in parsed.internal_links:
                absu = urllib.parse.urljoin(current, href.split("#")[0])
                (norm if urllib.parse.urlparse(absu).netloc == self.host else parsed.external_links).append(absu)
            parsed.internal_links = sorted(set(u for u in norm if u.startswith("http")))
            return parsed
        return res

    def crawl(self) -> dict:
        robots = self.transport.request("GET", urllib.parse.urljoin(self.base, "/robots.txt"))
        self.robots_txt = robots.text if robots.status == 200 else ""
        self._rp = urllib.robotparser.RobotFileParser()
        self._rp.parse(self.robots_txt.splitlines())
        sitemap_urls, sitemaps = [], [urllib.parse.urljoin(self.base, "/sitemap.xml")]
        sitemaps += [l.split(":", 1)[1].strip() for l in self.robots_txt.splitlines() if l.lower().startswith("sitemap:")]
        seen_sm = set()
        while sitemaps:
            sm = sitemaps.pop()
            if sm in seen_sm:
                continue
            seen_sm.add(sm)
            r = self.transport.request("GET", sm)
            if r.status == 200:
                try:
                    pages, children = parse_sitemap(r.text)
                    sitemap_urls += pages
                    sitemaps += children
                except ElementTree.ParseError:
                    pass
        queue, seen, pages = [self.base] + sitemap_urls, set(), {}
        ua = self.transport.user_agent
        while queue and len(pages) < self.max_pages:
            url = queue.pop(0)
            key = url.rstrip("/")
            if key in seen:
                continue
            seen.add(key)
            if not self._rp.can_fetch(ua, url):
                continue
            pr = self.fetch(url)
            pages[url] = pr
            for link in pr.internal_links:
                if link.rstrip("/") not in seen:
                    queue.append(link)
            if self.delay:
                time.sleep(self.delay)
        return {"robots_txt": self.robots_txt, "robots_status": robots.status, "sitemap_urls": sorted(set(sitemap_urls)),
                "pages": pages, "robots_matrix": robots_matrix(self.robots_txt, list(pages) or [self.base])}


def analyze_crawl(result: dict, base: str) -> list[dict]:
    """Turn a crawl into reproducible findings (status: confirmed). Each finding is evidence-backed."""
    findings = []
    pages: dict[str, PageResult] = result["pages"]

    def add(cat, sev, title, urls, evidence, rec, verify):
        findings.append({"agent": "technical_discoverability", "category": cat, "severity": sev, "status": "confirmed",
                         "title": title, "urls": urls, "evidence": evidence, "recommendation": rec,
                         "verification": verify, "kind": "observed"})

    if result.get("robots_status") != 200:
        add("robots", "high", "robots.txt not reachable", [urllib.parse.urljoin(base, "/robots.txt")],
            f"HTTP {result.get('robots_status')}", "Serve a valid robots.txt", "curl -I <site>/robots.txt returns 200")
    linked_to = set()
    titles: dict[str, list] = {}
    for url, p in pages.items():
        linked_to.update(l.rstrip("/") for l in p.internal_links)
        if p.error:
            add("fetch", "high", "Page fetch failed", [url], p.error, "Investigate server/CDN response", "Re-run crawl")
            continue
        if p.status >= 400:
            add("status", "high", f"HTTP {p.status}", [url], f"status={p.status}", "Fix or redirect the URL", "Status 200 or 301 to live page")
        if len(p.redirect_chain) > 1:
            add("redirects", "medium", "Redirect chain", [url], json.dumps(p.redirect_chain), "Point links to final URL", "Single hop")
        if "html" not in p.content_type:
            continue
        if not p.title:
            add("titles", "medium", "Missing <title>", [url], "no title element", "Add a descriptive Arabic title", "Re-crawl")
        else:
            titles.setdefault(p.title, []).append(url)
        if not p.meta_description:
            add("descriptions", "low", "Missing meta description", [url], "none", "Add a page-specific description", "Re-crawl")
        if len(p.h1) != 1:
            add("headings", "low", f"{len(p.h1)} H1 elements", [url], json.dumps(p.h1, ensure_ascii=False), "Use exactly one H1", "Re-crawl")
        if "noindex" in (p.meta_robots + " " + p.x_robots_tag).lower():
            add("indexability", "high", "Page is noindex", [url], p.meta_robots or p.x_robots_tag,
                "Remove noindex if the page should be discoverable", "Re-crawl + GSC URL Inspection")
        if not p.canonical:
            add("canonical", "low", "No canonical tag", [url], "none", "Add self-referencing canonical", "Re-crawl")
        elif p.canonical.rstrip("/") != (p.final_url or url).rstrip("/").split("?")[0]:
            add("canonical", "medium", "Canonical points elsewhere", [url], f"canonical={p.canonical}",
                "Confirm canonical target is intended", "Re-crawl")
        if p.html_lang[:2] != "ar":
            add("rtl", "medium", "html lang is not Arabic", [url], f"lang='{p.html_lang}'", "Set lang='ar' (or ar-EG)", "Re-crawl")
        if p.html_dir.lower() != "rtl":
            add("rtl", "low", "html dir is not rtl", [url], f"dir='{p.html_dir}'", "Set dir='rtl' on <html>", "Re-crawl")
        if p.jsonld_errors:
            add("structured_data", "medium", "Invalid JSON-LD", [url], f"{p.jsonld_errors} blocks failed to parse", "Fix JSON syntax", "Rich Results Test")
        if p.text_chars < 300:
            add("rendering", "medium", "Very little server-rendered text", [url], f"{p.text_chars} visible chars in raw HTML",
                "Ensure key content is server-rendered for crawlers that do not run JS", "curl page and grep key sentences")
        if p.images_missing_alt:
            add("accessibility", "low", "Images without alt text", [url], f"{p.images_missing_alt} images", "Add Arabic alt text", "Re-crawl")
    if pages and not any("Organization" in p.jsonld_types or "LocalBusiness" in p.jsonld_types for p in pages.values()):
        add("structured_data", "medium", "No Organization/LocalBusiness JSON-LD found on any crawled page", [base],
            "jsonld types: " + json.dumps(sorted({t for p in pages.values() for t in p.jsonld_types})),
            "Add Organization (+ LocalBusiness if the pickup office is public) using only verified facts", "Rich Results Test / Schema validator")
    for title, urls in titles.items():
        if len(urls) > 1:
            add("duplicates", "low", "Duplicate title", urls, title, "Make titles unique", "Re-crawl")
    sm = {u.rstrip("/") for u in result.get("sitemap_urls", [])}
    for u in sm:
        if u not in linked_to and u != base.rstrip("/"):
            add("internal_links", "low", "Sitemap URL not linked internally (possible orphan)", [u], "no inbound internal link found",
                "Link from relevant pages", "Re-crawl")
    for agent, info in result.get("robots_matrix", {}).items():
        if info["blocked"] and agent in ("OAI-SearchBot", "Googlebot", "Bingbot", "Claude-SearchBot", "PerplexityBot"):
            add("ai_crawlers", "high", f"robots.txt blocks {agent} on some public pages", info["blocked"][:20],
                f"{agent}: {info['purpose']}", "Allow search/surfacing bots on public pages (training bots are a separate choice)",
                "Re-run robots matrix")
    return findings
