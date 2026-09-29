# app/wp/orphan_pages.py
"""
Orphan Page Detector.

A page is "orphaned" when no other published page on the site contains a
hyperlink pointing to it. Orphans receive no internal PageRank and are often
missed by crawlers after the initial sitemap crawl.

Algorithm:
  1. Fetch all published posts & pages (up to MAX_POSTS).
  2. Extract every href from every post's content HTML.
  3. Build a set of "linked-to" normalised URLs.
  4. Any published URL not in that set is an orphan.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Set
from urllib.parse import urljoin, urlparse


MAX_POSTS = 200
_HREF_RE = re.compile(r'href=["\']([^"\'#?]+)["\']', re.IGNORECASE)


def _normalise(url: str, base: str = "") -> str:
    url = url.strip().rstrip("/")
    if url.startswith("/"):
        parsed = urlparse(base)
        url = f"{parsed.scheme}://{parsed.netloc}{url}"
    return url.lower()


def detect_orphans(posts: List[Dict], base_url: str) -> Dict[str, Any]:
    """
    Analyse posts/pages for orphaned URLs.

    Args:
        posts:    raw WP REST API post objects (combined posts + pages)
        base_url: site base URL for resolving relative links

    Returns dict with:
        orphans:       list of orphaned post dicts
        linked:        list of posts that have at least one inbound link
        orphan_count:  int
        total:         int
        inlink_map:    {url: [linking_page_urls]} for linked pages
    """
    all_posts = posts[:MAX_POSTS]
    base = base_url.rstrip("/")
    site_host = urlparse(base).netloc.lower()

    # Build URL → post map
    url_map: Dict[str, Dict] = {}
    for p in all_posts:
        raw_url = (p.get("link") or "").rstrip("/")
        if not raw_url:
            continue
        norm = _normalise(raw_url)
        title = re.sub(r"<[^>]+>", "", p.get("title", {}).get("rendered", raw_url))
        url_map[norm] = {
            "id": p.get("id"),
            "title": title,
            "url": raw_url,
            "type": p.get("type", "post"),
        }

    # Build inlink map: for each target URL, which source URLs link to it
    inlink_map: Dict[str, List[str]] = {url: [] for url in url_map}

    for p in all_posts:
        source_url = _normalise((p.get("link") or "").rstrip("/"))
        content_html = p.get("content", {}).get("rendered", "") or ""
        hrefs = _HREF_RE.findall(content_html)

        for href in hrefs:
            target = href.strip().rstrip("/")
            # Only consider internal links
            if target.startswith("http") and urlparse(target).netloc.lower() != site_host:
                continue
            norm_target = _normalise(target, base)
            if norm_target in inlink_map and norm_target != source_url:
                if source_url not in inlink_map[norm_target]:
                    inlink_map[norm_target].append(source_url)

    orphans: List[Dict] = []
    linked: List[Dict] = []

    for norm_url, post in url_map.items():
        inlinks = inlink_map.get(norm_url, [])
        entry = {**post, "inlink_count": len(inlinks), "inlinks": inlinks[:5]}
        if len(inlinks) == 0:
            orphans.append(entry)
        else:
            linked.append(entry)

    orphans.sort(key=lambda x: x["title"])
    linked.sort(key=lambda x: -x["inlink_count"])

    total = len(url_map)
    pct_orphaned = round(len(orphans) / total * 100) if total else 0

    return {
        "orphans": orphans,
        "linked": linked,
        "orphan_count": len(orphans),
        "linked_count": len(linked),
        "total": total,
        "pct_orphaned": pct_orphaned,
    }
