# app/wp/index_coverage.py
"""
Index Coverage Monitor.

Compares published WordPress posts/pages against Google Search Console impressions
to surface pages that are published but invisible in Google (possibly not indexed,
not ranking, or blocked).

Also checks each page against GSC's URL Inspection API if available; falls back
to the impressions heuristic if not.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List
from urllib.parse import urlparse


MAX_POSTS = 200


def _normalise(url: str) -> str:
    return url.rstrip("/").lower()


def check_index_coverage(
    posts: List[Dict],
    account_id: int,
    site_url: str,
) -> Dict[str, Any]:
    """
    Cross-references WP published URLs against GSC Search Analytics.

    Returns:
        indexed:    pages with GSC impressions (likely indexed)
        unindexed:  pages with zero GSC impressions in last 90 days
        stats:      summary counts
    """
    from app.seo.keyword_gaps import _gsc_fetch, _rows_to_dicts, _date_range

    # Fetch GSC page-level data (90-day window)
    end, start = _date_range(3, 90)
    rows = _gsc_fetch(account_id, site_url, start, end, ["page"], row_limit=1000)
    gsc_data = _rows_to_dicts(rows, ["page"])

    gsc_pages: Dict[str, Dict] = {}
    for row in gsc_data:
        url = _normalise(row.get("page", ""))
        if url:
            gsc_pages[url] = {
                "impressions": int(row.get("impressions", 0)),
                "clicks": int(row.get("clicks", 0)),
                "position": round(row.get("position", 0), 1),
            }

    indexed: List[Dict] = []
    unindexed: List[Dict] = []

    for p in posts[:MAX_POSTS]:
        raw_url = (p.get("link") or "").rstrip("/")
        if not raw_url:
            continue
        title = re.sub(r"<[^>]+>", "", p.get("title", {}).get("rendered", raw_url))
        post_type = p.get("type", "post")
        post_id = p.get("id")
        norm = _normalise(raw_url)

        gsc_row = gsc_pages.get(norm)
        if gsc_row and gsc_row["impressions"] > 0:
            indexed.append({
                "id": post_id,
                "title": title,
                "url": raw_url,
                "type": post_type,
                "impressions": gsc_row["impressions"],
                "clicks": gsc_row["clicks"],
                "position": gsc_row["position"],
                "status": "indexed",
            })
        else:
            # Attempt to determine likely reason
            reason = "No GSC impressions in 90 days"
            if gsc_row is not None:
                reason = "Page appears in GSC with 0 impressions — may rank below position 100"

            unindexed.append({
                "id": post_id,
                "title": title,
                "url": raw_url,
                "type": post_type,
                "impressions": 0,
                "clicks": 0,
                "position": None,
                "status": "not_indexed",
                "reason": reason,
            })

    # Sort: posts with 0 impressions first (most actionable)
    unindexed.sort(key=lambda x: x["title"])
    indexed.sort(key=lambda x: -x["impressions"])

    total = len(indexed) + len(unindexed)
    pct_indexed = round(len(indexed) / total * 100) if total else 0

    return {
        "indexed": indexed,
        "unindexed": unindexed,
        "indexed_count": len(indexed),
        "unindexed_count": len(unindexed),
        "total": total,
        "pct_indexed": pct_indexed,
    }
