# app/wp/internal_links.py
"""
Internal Linking Engine.

Scans published WP posts and finds topically related pages to link from
a given source post. Suggestions are ranked by keyword overlap score.
The insert step finds the first unlinked occurrence of the anchor phrase
in the source HTML and wraps it in <a href="...">.
"""
from __future__ import annotations

import html as _html
import re
from typing import Any, Dict, List, Set

_STOPS = {
    "a","an","the","and","or","but","in","on","at","to","for","of","with",
    "is","are","was","were","be","been","has","have","had","do","does","did",
    "not","no","by","from","as","this","that","these","those","its","it","i",
    "we","you","he","she","they","our","your","their","will","can","may","how",
    "what","when","where","who","which","all","more","up","if","so","than","then",
    "into","out","about","over","after","before","just","also","each","both",
    "get","got","use","used","using","make","made","need","want","know","see",
    "one","two","three","first","second","new","old","good","best","great",
}


def _tokens(text: str) -> List[str]:
    return [w for w in re.findall(r"[a-z]{3,}", text.lower()) if w not in _STOPS]


def _strip_tags(html: str) -> str:
    return re.sub(r"<[^>]+>", " ", html)


def _score(source_tokens: Set[str], cand_title: str, cand_body: str) -> float:
    ct = set(_tokens(cand_title))
    cb = set(_tokens(_strip_tags(cand_body)))
    return len(source_tokens & ct) * 3 + len(source_tokens & cb) * 0.4


def _already_linked(html: str, url: str) -> bool:
    return url.rstrip("/") in html


def _best_anchor(title: str, source_tokens: Set[str]) -> str:
    """Pick a 2-3 word anchor that overlaps with source content, else full title."""
    words = title.split()
    for size in (3, 2):
        for i in range(len(words) - size + 1):
            chunk = words[i : i + size]
            phrase = " ".join(chunk)
            if any(w.lower() in source_tokens for w in chunk):
                return phrase
    return title[:60]


def find_link_opportunities(
    source_id: int,
    source_html: str,
    source_title: str,
    all_posts: List[Dict],
    max_suggestions: int = 10,
) -> List[Dict[str, Any]]:
    """
    Return ranked internal link suggestions for a source post.
    Each item: {post_id, title, url, anchor_text, score, already_in_content}
    """
    source_text = source_title + " " + _strip_tags(source_html)
    source_tokens = set(_tokens(source_text))

    results = []
    for post in all_posts:
        pid = post.get("id")
        if pid == source_id:
            continue
        url   = (post.get("link") or "").rstrip("/")
        title = _html.unescape(post.get("title", {}).get("rendered", "") or "")
        body  = post.get("content", {}).get("rendered", "") or ""

        if not url or not title:
            continue

        already = _already_linked(source_html, url)
        score   = _score(source_tokens, title, body)
        if score < 1.0:
            continue

        anchor = _best_anchor(title, source_tokens)
        results.append({
            "post_id":    pid,
            "title":      title,
            "url":        url,
            "anchor_text": anchor,
            "score":      round(score, 1),
            "already_linked": already,
        })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:max_suggestions]


def insert_links(source_html: str, suggestions: List[Dict]) -> tuple[str, int]:
    """
    Insert selected internal links into HTML.
    Finds first unlinked occurrence of anchor text (case-insensitive)
    and wraps it. Skips if already inside an <a> tag.
    Returns (modified_html, count_inserted).
    """
    inserted = 0
    html = source_html

    for s in suggestions:
        anchor = re.escape(s["anchor_text"])
        url    = s["url"]
        # Split on existing <a>…</a> blocks; only replace in non-link segments
        parts = re.split(r"(<a\b[^>]*>.*?</a>)", html, flags=re.DOTALL | re.IGNORECASE)
        new_parts: List[str] = []
        replaced = False

        for part in parts:
            if replaced or re.match(r"<a\b", part, re.IGNORECASE):
                new_parts.append(part)
                continue
            new_part, n = re.subn(
                r"(?<![\"'>=/\w])" + anchor + r"(?![\"'<\w/])",
                f'<a href="{url}">{s["anchor_text"]}</a>',
                part, count=1, flags=re.IGNORECASE,
            )
            if n:
                replaced = True
                inserted += 1
            new_parts.append(new_part)

        html = "".join(new_parts)

    return html, inserted
