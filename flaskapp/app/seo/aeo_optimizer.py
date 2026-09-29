# app/seo/aeo_optimizer.py
"""
AI Overview (AEO) Optimizer.

Fetches a page and scores it against 12 signals that influence Google AI Overview
inclusion: concise answer up front, question-format headings, lists, tables,
structured data, E-E-A-T signals, reading level, word count, etc.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import requests

TIMEOUT = 10
UA = "FieldSprout-AEO/1.0"


def _fetch(url: str) -> Optional[str]:
    try:
        r = requests.get(url, timeout=TIMEOUT, headers={"User-Agent": UA})
        if r.status_code == 200:
            return r.text
    except Exception:
        pass
    return None


def _strip_tags(html: str) -> str:
    return re.sub(r"<[^>]+>", " ", html)


def _word_count(text: str) -> int:
    return len(text.split())


def _check(label: str, status: str, detail: str, tip: str = "", weight: int = 1) -> Dict:
    return {"label": label, "status": status, "detail": detail, "tip": tip, "weight": weight}


def audit_aeo(url: str) -> Dict[str, Any]:
    html = _fetch(url)
    if not html:
        return {"error": f"Could not fetch {url}"}

    text = _strip_tags(html)
    words = _word_count(text)
    checks: List[Dict] = []

    # 1. Concise answer in first 100 words
    # Find content between first H1 and next heading
    body_match = re.search(r"<body[^>]*>(.*)</body>", html, re.DOTALL | re.IGNORECASE)
    body_html = body_match.group(1) if body_match else html

    # First paragraph after H1
    first_para_match = re.search(
        r"<h1[^>]*>.*?</h1>\s*(?:<[^>]+>\s*)*<p[^>]*>(.*?)</p>",
        body_html, re.DOTALL | re.IGNORECASE
    )
    first_para_text = _strip_tags(first_para_match.group(1)).strip() if first_para_match else ""
    first_para_words = _word_count(first_para_text)

    if 30 <= first_para_words <= 120:
        checks.append(_check(
            "Concise opening answer",
            "pass",
            f"First paragraph is {first_para_words} words — ideal for AI Overview extraction.",
            weight=3
        ))
    elif first_para_words > 0:
        checks.append(_check(
            "Concise opening answer",
            "warn",
            f"First paragraph is {first_para_words} words — {'too short' if first_para_words < 30 else 'too long'} for AI Overview.",
            "Aim for a 40-80 word direct answer immediately below the H1.",
            weight=3
        ))
    else:
        checks.append(_check(
            "Concise opening answer",
            "fail",
            "No clear opening paragraph found after the H1.",
            "Add a 40-80 word direct answer immediately below the H1 heading.",
            weight=3
        ))

    # 2. Question-format headings (H2/H3)
    headings = re.findall(r"<h[23][^>]*>(.*?)</h[23]>", html, re.DOTALL | re.IGNORECASE)
    heading_texts = [_strip_tags(h).strip() for h in headings]
    question_headings = [h for h in heading_texts if h.endswith("?") or
                         any(h.lower().startswith(w) for w in
                             ("what", "how", "why", "when", "where", "who", "which", "is ", "are ", "can ", "does "))]
    if len(question_headings) >= 2:
        checks.append(_check(
            "Question-format headings",
            "pass",
            f"{len(question_headings)} of {len(heading_texts)} H2/H3s are question-format — great for PAA and AI Overviews.",
            weight=2
        ))
    elif len(heading_texts) > 0:
        checks.append(_check(
            "Question-format headings",
            "warn",
            f"Only {len(question_headings)} of {len(heading_texts)} H2/H3s use question format.",
            "Rewrite at least 2-3 subheadings as questions your audience would search (e.g. 'What is X?' 'How does Y work?').",
            weight=2
        ))
    else:
        checks.append(_check(
            "Question-format headings",
            "fail",
            "No H2/H3 headings found.",
            "Add structured H2/H3 headings — AI Overviews pull from well-structured content.",
            weight=2
        ))

    # 3. Ordered or unordered lists
    list_count = len(re.findall(r"<(?:ul|ol)[^>]*>", html, re.IGNORECASE))
    list_items = len(re.findall(r"<li[^>]*>", html, re.IGNORECASE))
    if list_count >= 2 and list_items >= 5:
        checks.append(_check("List content (ul/ol)", "pass",
                             f"{list_count} lists with {list_items} total items.", weight=2))
    elif list_count >= 1:
        checks.append(_check("List content (ul/ol)", "warn",
                             f"Only {list_count} list with {list_items} items.",
                             "Add numbered or bulleted lists — AI Overviews frequently cite list-format answers.",
                             weight=2))
    else:
        checks.append(_check("List content (ul/ol)", "fail",
                             "No lists found.",
                             "Add at least one ordered or unordered list — especially for 'best X' or 'how to' content.",
                             weight=2))

    # 4. Tables
    table_count = len(re.findall(r"<table[^>]*>", html, re.IGNORECASE))
    if table_count >= 1:
        checks.append(_check("Comparison tables", "pass",
                             f"{table_count} table(s) found — high AI Overview extraction value.", weight=1))
    else:
        checks.append(_check("Comparison tables", "warn",
                             "No tables found.",
                             "Add a comparison or data table for queries with 'vs', 'compare', or 'cost' intent.",
                             weight=1))

    # 5. FAQ schema
    has_faq_schema = bool(re.search(r'"@type"\s*:\s*"FAQPage"', html, re.IGNORECASE))
    if has_faq_schema:
        checks.append(_check("FAQ schema (FAQPage)", "pass",
                             "FAQPage JSON-LD found — maximises PAA and AI Overview slots.", weight=2))
    else:
        checks.append(_check("FAQ schema (FAQPage)", "warn",
                             "No FAQPage schema found.",
                             "Add FAQ schema with 3-5 Q&A pairs using JSON-LD — it directly feeds Google's AI Overview.",
                             weight=2))

    # 6. Article / WebPage schema
    has_article = bool(re.search(r'"@type"\s*:\s*"(?:Article|BlogPosting|WebPage)"', html, re.IGNORECASE))
    if has_article:
        checks.append(_check("Article / WebPage schema", "pass",
                             "Article or WebPage structured data found.", weight=1))
    else:
        checks.append(_check("Article / WebPage schema", "warn",
                             "No Article or WebPage schema found.",
                             "Add Article JSON-LD with author, datePublished, and headline fields.",
                             weight=1))

    # 7. Author byline (E-E-A-T Experience signal)
    has_author = bool(re.search(
        r'(class|itemprop)=["\'][^"\']*author[^"\']*["\']|"author"\s*:\s*\{',
        html, re.IGNORECASE
    ))
    if has_author:
        checks.append(_check("Author byline (E-E-A-T)", "pass",
                             "Author markup detected — Google uses this for E-E-A-T scoring.", weight=2))
    else:
        checks.append(_check("Author byline (E-E-A-T)", "fail",
                             "No author markup found.",
                             "Add a visible author byline with a link to an author bio page — critical for YMYL and AI Overview inclusion.",
                             weight=2))

    # 8. Date published / updated
    has_date = bool(re.search(
        r'(datePublished|dateModified|published|itemprop=["\']date)',
        html, re.IGNORECASE
    ))
    if has_date:
        checks.append(_check("Date freshness signals", "pass",
                             "Publication or modification date markup found.", weight=1))
    else:
        checks.append(_check("Date freshness signals", "warn",
                             "No publication date markup found.",
                             "Add datePublished and dateModified in your Article schema — AI Overviews prefer fresh, dated content.",
                             weight=1))

    # 9. Word count (depth signal)
    if words >= 1000:
        checks.append(_check("Content depth (word count)", "pass",
                             f"{words:,} words — sufficient depth for comprehensive topic coverage.",
                             weight=1))
    elif words >= 500:
        checks.append(_check("Content depth (word count)", "warn",
                             f"Only {words:,} words — consider expanding.",
                             "AI Overviews tend to cite pages with ≥1,000 words of substantive content.",
                             weight=1))
    else:
        checks.append(_check("Content depth (word count)", "fail",
                             f"Only {words:,} words — too thin for AI Overview inclusion.",
                             "Expand to at least 800-1,200 words covering the topic comprehensively.",
                             weight=1))

    # 10. Outbound citations / external links (authority signal)
    ext_links = re.findall(r'href=["\']https?://(?!' + re.escape(urlparse(url).netloc) + r')[^"\']+["\']',
                           html, re.IGNORECASE)
    unique_ext = len(set(ext_links))
    if unique_ext >= 3:
        checks.append(_check("External citations", "pass",
                             f"{unique_ext} external links found — demonstrates research and authority.",
                             weight=1))
    elif unique_ext >= 1:
        checks.append(_check("External citations", "warn",
                             f"Only {unique_ext} external link(s).",
                             "Cite 3-5 authoritative sources (.gov, .edu, Wikipedia, industry studies) — AI systems value sourced claims.",
                             weight=1))
    else:
        checks.append(_check("External citations", "fail",
                             "No external citations found.",
                             "Add links to authoritative external sources to support your claims.",
                             weight=1))

    # 11. Title tag length (35-60 chars ideal for AI snippet headlines)
    title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    title_text = _strip_tags(title_match.group(1)).strip() if title_match else ""
    title_len = len(title_text)
    if 35 <= title_len <= 65:
        checks.append(_check("Title tag length", "pass",
                             f"Title is {title_len} characters — optimal range.", weight=1))
    elif title_len > 0:
        checks.append(_check("Title tag length", "warn",
                             f"Title is {title_len} chars ({'too short' if title_len < 35 else 'may be truncated'}).",
                             "Keep the title 40-60 characters with the primary keyword near the front.",
                             weight=1))
    else:
        checks.append(_check("Title tag length", "fail", "No title tag found.", weight=1))

    # 12. Meta description (summarisation hint)
    meta_desc_match = re.search(
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']',
        html, re.IGNORECASE
    )
    meta_desc = meta_desc_match.group(1).strip() if meta_desc_match else ""
    if 100 <= len(meta_desc) <= 160:
        checks.append(_check("Meta description", "pass",
                             f"Meta description is {len(meta_desc)} characters.", weight=1))
    elif meta_desc:
        checks.append(_check("Meta description", "warn",
                             f"Meta description is {len(meta_desc)} chars ({'too short' if len(meta_desc) < 100 else 'may be truncated'}).",
                             "Write a 130-155 char meta description — Google often uses it as the AI Overview sub-heading.",
                             weight=1))
    else:
        checks.append(_check("Meta description", "fail",
                             "No meta description.",
                             "Add a 130-155 character meta description summarising the page's direct answer.",
                             weight=1))

    # Score
    total_weight = sum(c["weight"] for c in checks)
    pass_weight = sum(c["weight"] for c in checks if c["status"] == "pass")
    score = round(pass_weight / total_weight * 100) if total_weight else 0

    pass_count = sum(1 for c in checks if c["status"] == "pass")
    warn_count = sum(1 for c in checks if c["status"] == "warn")
    fail_count = sum(1 for c in checks if c["status"] == "fail")

    return {
        "url": url,
        "score": score,
        "checks": checks,
        "pass_count": pass_count,
        "warn_count": warn_count,
        "fail_count": fail_count,
        "word_count": words,
        "title": title_text,
    }
