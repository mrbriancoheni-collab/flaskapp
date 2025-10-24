# app/agents/analyzer.py
"""
Lightweight on-page analyzer used by /account/wp/analyze.

- Fetches a URL with a sane User-Agent + timeout
- Parses title, meta description, H1/H2s, canonical, robots, images (alt), links
- Builds a concise "analysis" (findings + recommendations) plus a ready-to-publish HTML draft
- Returns dict with: h1, title, excerpt, draft_html, findings, recommendations

Install deps:
  pip install beautifulsoup4 requests
"""

from __future__ import annotations

import re
import textwrap
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


# ----------------------------
# Config
# ----------------------------
DEFAULT_TIMEOUT = 12  # seconds
USER_AGENT = (
    "Mozilla/5.0 (compatible; ContentAnalyzerBot/1.0; +https://example.com/bot) "
    "Safari/537.36"
)


@dataclass
class PageSignals:
    url: str
    final_url: str
    status_code: int
    title: str
    meta_desc: str
    canonical: str
    robots_meta: str
    h1: str
    h2: List[str]
    word_count: int
    images: List[Tuple[str, str]]  # (src, alt)
    links_internal: int
    links_external: int


# ----------------------------
# Public API
# ----------------------------

def analyze_url(url: str) -> Dict:
    """
    Main entrypoint used by the WP analyze route.
    Returns: dict with keys: h1, title, excerpt, draft_html, findings, recommendations
    """
    html, final_url, status = _fetch(url)
    if not html:
        # Return a safe fallback payload so the caller can still queue a job
        title = f"Unable to fetch: {url} (HTTP {status or '—'})"
        return {
            "h1": title,
            "title": title,
            "excerpt": "Fetch failed. Please verify the URL is publicly accessible.",
            "draft_html": _render_failure_html(url, status),
            "findings": ["Fetch failed or non-HTML response."],
            "recommendations": ["Verify the URL is public and returns text/html."],
        }

    soup = BeautifulSoup(html, "html.parser")
    signals = _extract_signals(url, final_url, status, soup)
    findings, recommendations = _evaluate(signals)
    excerpt = _make_excerpt(signals, findings)

    draft_html = _render_draft(signals, findings, recommendations)

    return {
        "h1": signals.h1 or signals.title or _hostname(url),
        "title": signals.title or signals.h1 or _hostname(url),
        "excerpt": excerpt,
        "draft_html": draft_html,
        "findings": findings,
        "recommendations": recommendations,
    }


# ----------------------------
# Fetch + Parse
# ----------------------------

def _fetch(url: str) -> Tuple[Optional[str], str, Optional[int]]:
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
            allow_redirects=True,
            timeout=DEFAULT_TIMEOUT,
        )
        ctype = (resp.headers.get("Content-Type") or "").lower()
        if "text/html" not in ctype and "application/xhtml+xml" not in ctype:
            return None, resp.url, resp.status_code
        return resp.text, resp.url, resp.status_code
    except Exception:
        return None, url, None


def _extract_signals(url: str, final_url: str, status_code: int, soup: BeautifulSoup) -> PageSignals:
    title = _clean_text(soup.title.string) if soup.title and soup.title.string else ""
    meta_desc = _meta(soup, "description")
    canonical = _link_rel(soup, "canonical")
    robots_meta = _meta(soup, "robots")

    h1 = ""
    h1_el = soup.find("h1")
    if h1_el:
        h1 = _clean_text(h1_el.get_text(" ", strip=True))

    h2 = [_clean_text(h.get_text(" ", strip=True)) for h in soup.find_all("h2")]

    text_nodes = soup.get_text(" ", strip=True)
    word_count = len([w for w in re.split(r"\s+", text_nodes) if w])

    imgs = []
    for img in soup.find_all("img"):
        src = (img.get("src") or "").strip()
        alt = _clean_text(img.get("alt") or "")
        if src:
            imgs.append((src, alt))

    host = urlparse(final_url or url).netloc
    internal = external = 0
    for a in soup.find_all("a"):
        href = (a.get("href") or "").strip()
        if not href:
            continue
        if href.startswith("#") or href.startswith("mailto:") or href.startswith("tel:"):
            continue
        absolute = urljoin(final_url or url, href)
        if urlparse(absolute).netloc == host:
            internal += 1
        else:
            external += 1

    return PageSignals(
        url=url,
        final_url=final_url,
        status_code=status_code,
        title=title,
        meta_desc=meta_desc,
        canonical=canonical,
        robots_meta=robots_meta,
        h1=h1,
        h2=h2,
        word_count=word_count,
        images=imgs,
        links_internal=internal,
        links_external=external,
    )


# ----------------------------
# Heuristics / Findings
# ----------------------------

def _evaluate(sig: PageSignals) -> Tuple[List[str], List[str]]:
    findings: List[str] = []
    recs: List[str] = []

    # Title
    if not sig.title:
        findings.append("Missing <title> tag.")
        recs.append("Add a concise, keyword-focused <title> (~50–60 chars).")
    elif len(sig.title) > 65:
        findings.append(f"Title appears long ({len(sig.title)} chars).")
        recs.append("Shorten <title> to ~50–60 chars; lead with primary keyword.")

    # Meta description
    if not sig.meta_desc:
        findings.append("Missing meta description.")
        recs.append("Add a compelling meta description (~150–160 chars) with a CTA.")
    elif len(sig.meta_desc) > 175:
        findings.append("Meta description appears long.")
        recs.append("Trim meta description to ~150–160 chars and include value prop + CTA.")

    # H1
    if not sig.h1:
        findings.append("Missing H1.")
        recs.append("Add a single, descriptive H1 aligned to the page’s primary intent.")
    elif len(sig.h1) > 80:
        findings.append("H1 looks verbose.")
        recs.append("Tighten H1; keep it descriptive but scannable (< ~70–80 chars).")

    # Word count (very rough heuristic)
    if sig.word_count < 300:
        findings.append(f"Low on-page copy ({sig.word_count} words).")
        recs.append("Add substantive content: intro, key sections (H2s), FAQs, and a clear CTA.")

    # Images / alts
    if sig.images:
        missing_alt = sum(1 for _, alt in sig.images if not alt)
        if missing_alt:
            findings.append(f"{missing_alt} image(s) missing alt text.")
            recs.append("Add descriptive, concise alt text to all meaningful images.")
    else:
        findings.append("No images detected.")
        recs.append("Add at least one relevant image with descriptive alt text.")

    # Canonical
    if not sig.canonical:
        findings.append("No canonical link rel found.")
        recs.append("Add a <link rel='canonical'> to the preferred URL to avoid duplication signals.")

    # Robots meta
    if "noindex" in (sig.robots_meta or "").lower():
        findings.append("Page has robots noindex.")
        recs.append("Remove noindex if this page should appear in search.")

    # Links balance (very rough)
    if sig.links_internal < 2:
        findings.append("Low internal links from this page.")
        recs.append("Add internal links to relevant pages/services to aid crawl and topical depth.")

    # AEO (Answer Engine Optimization) cues
    if not _has_faq_like_content(sig):
        findings.append("No explicit Q&A/FAQ sections.")
        recs.append("Add an FAQ block with 3–5 customer questions in natural language (JSON-LD optional).")

    return findings, recs


def _has_faq_like_content(sig: PageSignals) -> bool:
    # Very lightweight heuristic: presence of question marks in headings or body
    if any("?" in h for h in sig.h2):
        return True
    return False


# ----------------------------
# Outputs
# ----------------------------

def _make_excerpt(sig: PageSignals, findings: List[str]) -> str:
    base = sig.h1 or sig.title or _hostname(sig.final_url or sig.url)
    top = "; ".join(findings[:3]) if findings else "Opportunities identified for content and on-page improvements."
    return f"{base} — {top}"[:200]


def _render_draft(sig: PageSignals, findings: List[str], recs: List[str]) -> str:
    """
    Render a clean, non-branded draft suitable to post as a “recommendations” draft on WP.
    """
    page_name = sig.h1 or sig.title or _hostname(sig.final_url or sig.url)
    url_safe = sig.final_url or sig.url

    # Executive summary
    bullets_findings = "".join(f"<li>{_escape_html(f)}</li>" for f in findings[:8]) or "<li>No critical issues detected.</li>"
    bullets_recs = "".join(f"<li>{_escape_html(r)}</li>" for r in recs[:8]) or "<li>Looks solid. Consider adding an FAQ and internal links.</li>"

    # Optional FAQ scaffold for AEO
    faq_html = textwrap.dedent("""\
        <section>
          <h2>Frequently Asked Questions</h2>
          <dl>
            <dt>What is the main value of this page?</dt>
            <dd>It addresses a specific customer intent with clear benefits, proof, and next steps.</dd>
            <dt>How can we improve its visibility?</dt>
            <dd>Refine the title/meta, add structured headings (H2–H3), and expand helpful content.</dd>
            <dt>What should we add for AEO?</dt>
            <dd>Include 3–5 real customer Q&As in plain language; mark up with FAQPage JSON-LD if appropriate.</dd>
          </dl>
        </section>
    """)

    html = f"""
<article>
  <header>
    <p><strong>URL:</strong> <a href="{_escape_attr(url_safe)}" rel="noopener nofollow">{_escape_html(url_safe)}</a></p>
    <h1>Improvement Plan: {_escape_html(page_name)}</h1>
    <p><em>Status:</em> HTTP {sig.status_code} • Words: {sig.word_count} • Internal links: {sig.links_internal} • External links: {sig.links_external}</p>
  </header>

  <section>
    <h2>Executive Summary</h2>
    <p>This draft highlights opportunities to strengthen on-page SEO and AEO for the page above.</p>
    <ul>{bullets_findings}</ul>
  </section>

  <section>
    <h2>Recommended Changes</h2>
    <ul>{bullets_recs}</ul>
  </section>

  <section>
    <h2>Suggested Outline (Example)</h2>
    <ol>
      <li>Clear H1 reflecting primary search intent</li>
      <li>Intro paragraph summarizing benefits and what the visitor can do next</li>
      <li>Key sections (H2) that cover the topic comprehensively</li>
      <li>Proof &amp; trust (testimonials, stats, certifications)</li>
      <li>FAQ (3–5 real customer questions answered concisely)</li>
      <li>Primary call-to-action</li>
    </ol>
  </section>

  {faq_html}
</article>
    """.strip()

    return html


def _render_failure_html(url: str, status: Optional[int]) -> str:
    code = status if status is not None else "unknown"
    return f"""
<article>
  <h1>Analysis Failed</h1>
  <p>We couldn't fetch <code>{_escape_html(url)}</code> (HTTP {code}). Please ensure the URL is public and try again.</p>
</article>
    """.strip()


# ----------------------------
# Utilities
# ----------------------------

def _meta(soup: BeautifulSoup, name: str) -> str:
    el = soup.find("meta", attrs={"name": name})
    if el and el.has_attr("content"):
        return _clean_text(el["content"])
    # Also check OpenGraph as fallback for description
    if name == "description":
        og = soup.find("meta", attrs={"property": "og:description"})
        if og and og.has_attr("content"):
            return _clean_text(og["content"])
    return ""


def _link_rel(soup: BeautifulSoup, rel: str) -> str:
    # rel may be a list in HTML; Jinja/BeautifulSoup handle both patterns
    el = soup.find("link", attrs={"rel": lambda r: r and rel in r})
    if not el:
        el = soup.find("link", rel=rel)
    href = (el.get("href") or "").strip() if el else ""
    return href


def _clean_text(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"\s+", " ", s)
    return s


def _hostname(u: str) -> str:
    try:
        return urlparse(u).hostname or u
    except Exception:
        return u


def _escape_html(s: str) -> str:
    return (
        (s or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _escape_attr(s: str) -> str:
    return _escape_html(s).replace('"', "&quot;")
