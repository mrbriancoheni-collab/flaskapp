# app/seo/cannibalization.py
"""
Keyword Cannibalization Detector.

Uses GSC Search Analytics (page × query) to find keywords where multiple
pages compete, diluting rankings and click-through rates.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List


def detect_cannibalization(
    account_id: int,
    site_url: str,
    min_impressions: int = 20,
    top_n: int = 50,
) -> Dict[str, Any]:
    """
    Returns a dict with:
      - conflicts: list of {keyword, pages: [{url, position, impressions, clicks}], severity}
      - total_keywords_checked: int
      - conflict_count: int
    """
    from app.seo.keyword_gaps import _gsc_fetch, _rows_to_dicts, _date_range

    end, start = _date_range(3, 56)  # last 56 days
    rows = _gsc_fetch(account_id, site_url, start, end,
                      ["query", "page"], row_limit=500)
    data = _rows_to_dicts(rows, ["query", "page"])

    # Group by query
    query_map: Dict[str, List[Dict]] = defaultdict(list)
    for row in data:
        query = row.get("query", "").strip().lower()
        page = row.get("page", "")
        impr = int(row.get("impressions", 0))
        if not query or not page or impr < min_impressions:
            continue
        query_map[query].append({
            "url": page,
            "position": round(row.get("position", 99), 1),
            "impressions": impr,
            "clicks": int(row.get("clicks", 0)),
            "ctr": round(row.get("ctr", 0) * 100, 1),
        })

    # Find queries with 2+ pages
    conflicts = []
    for query, pages in query_map.items():
        if len(pages) < 2:
            continue
        # Sort by impressions desc
        pages.sort(key=lambda p: p["impressions"], reverse=True)

        # Determine severity
        positions = [p["position"] for p in pages]
        top_pos = min(positions)
        if top_pos <= 10 and len([p for p in positions if p <= 20]) >= 2:
            severity = "high"
        elif top_pos <= 20:
            severity = "medium"
        else:
            severity = "low"

        # Total lost clicks estimate: impressions of page 2 * avg CTR drop
        runner_up_impr = sum(p["impressions"] for p in pages[1:])
        lost_clicks_est = round(runner_up_impr * 0.08)

        conflicts.append({
            "keyword": query,
            "pages": pages[:5],
            "severity": severity,
            "page_count": len(pages),
            "top_position": top_pos,
            "total_impressions": sum(p["impressions"] for p in pages),
            "lost_clicks_est": lost_clicks_est,
        })

    # Sort: high severity first, then by total impressions
    sev_order = {"high": 0, "medium": 1, "low": 2}
    conflicts.sort(key=lambda c: (sev_order[c["severity"]], -c["total_impressions"]))
    conflicts = conflicts[:top_n]

    high = sum(1 for c in conflicts if c["severity"] == "high")
    medium = sum(1 for c in conflicts if c["severity"] == "medium")
    low = sum(1 for c in conflicts if c["severity"] == "low")

    return {
        "conflicts": conflicts,
        "conflict_count": len(conflicts),
        "total_keywords_checked": len(query_map),
        "high_count": high,
        "medium_count": medium,
        "low_count": low,
    }
