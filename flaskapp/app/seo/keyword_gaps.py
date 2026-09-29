# app/seo/keyword_gaps.py
"""
Keyword Gap & Content Opportunity Engine — Phase 4.

Pulls extended GSC data (up to 100 queries/pages, query×page cross-dimension)
and surfaces five opportunity categories:

  Quick Wins        — Positions 4–20 with solid impressions; small push to top 3
  Content Gaps      — High impressions / low CTR; page exists but underperforms
  Missing Content   — High impressions / near-zero clicks; no page targets this query
  Cannibalization   — Multiple pages ranking for the same query
  Declining Pages   — Pages whose clicks dropped ≥20% vs the previous equal period

Also clusters all queries by keyword root (first 2 words) so you can see
topic demand at a glance.

Auth reuses the google module's existing helpers; no new credentials needed.
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

GSC_QUERY_URL = (
    "https://searchconsole.googleapis.com/webmasters/v3/sites/{site}/searchAnalytics/query"
)


# ─────────────────────────────────────────────────────────────────────────────
# GSC fetching
# ─────────────────────────────────────────────────────────────────────────────

def _gsc_fetch(
    aid: int,
    site_url: str,
    start: str,
    end: str,
    dimensions: List[str],
    row_limit: int = 100,
    order_by: Optional[List[Dict]] = None,
) -> List[Dict]:
    """
    Low-level GSC Search Analytics query.  Reuses auth helpers from app.google.
    Returns the raw rows list (each row has 'keys' + metric floats).
    """
    import requests
    from app.google import _gsc_user_access_token

    token = _gsc_user_access_token(aid)
    if not token:
        return []

    encoded_site = quote(site_url, safe="")
    url = GSC_QUERY_URL.format(site=encoded_site)

    payload: Dict[str, Any] = {
        "startDate": start,
        "endDate":   end,
        "dimensions": dimensions,
        "rowLimit":   row_limit,
    }
    if order_by:
        payload["orderBy"] = order_by  # type: ignore[assignment]

    try:
        r = requests.post(
            url,
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json"},
            json=payload,
            timeout=20,
        )
        if r.status_code == 401:
            # Try once more after a forced refresh
            from app.google import _refresh_gsc_user_access_token, _get_gsc_user_tokens
            tokens = _get_gsc_user_tokens(aid)
            if tokens:
                refreshed = _refresh_gsc_user_access_token(tokens)
                if refreshed:
                    token = refreshed.get("access_token", "")
                    r = requests.post(
                        url,
                        headers={"Authorization": f"Bearer {token}",
                                 "Content-Type": "application/json"},
                        json=payload,
                        timeout=20,
                    )
        if r.status_code == 200:
            return r.json().get("rows", [])
    except Exception:
        pass
    return []


def _rows_to_dicts(rows: List[Dict], dimensions: List[str]) -> List[Dict]:
    """Convert raw GSC rows to clean dicts keyed by dimension name + metrics."""
    out = []
    for row in rows:
        keys = row.get("keys", [])
        d = {dim: keys[i] if i < len(keys) else ""
             for i, dim in enumerate(dimensions)}
        d["clicks"]      = int(row.get("clicks", 0))
        d["impressions"] = int(row.get("impressions", 0))
        d["ctr"]         = round(row.get("ctr", 0) * 100, 2)   # as %
        d["position"]    = round(row.get("position", 0), 1)
        out.append(d)
    return out


def _date_range(days_ago_start: int, days_ago_end: int) -> Tuple[str, str]:
    today = date.today()
    return (
        (today - timedelta(days=days_ago_start)).isoformat(),
        (today - timedelta(days=days_ago_end)).isoformat(),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Analysis functions
# ─────────────────────────────────────────────────────────────────────────────

def _quick_wins(queries: List[Dict]) -> List[Dict]:
    """
    Positions 4–20 with ≥50 impressions.
    Sort by estimated opportunity: impressions × (1 - ctr/100).
    """
    wins = [
        q for q in queries
        if 4.0 <= q["position"] <= 20.0 and q["impressions"] >= 50
    ]
    for w in wins:
        # Rough clicks-at-position-1 estimate using avg CTR ~28%
        estimated_top3_clicks = int(w["impressions"] * 0.18)
        w["opportunity"]   = estimated_top3_clicks - w["clicks"]
        w["gap_label"]     = (
            "Top 3 push"  if w["position"] <= 10 else
            "Page 2 → 1"
        )
    wins.sort(key=lambda x: x["opportunity"], reverse=True)
    return wins[:20]


def _content_gaps(queries: List[Dict]) -> List[Dict]:
    """
    Queries with ≥100 impressions AND CTR < 3% AND position ≤ 20.
    These pages rank but don't earn clicks — title/meta or content intent mismatch.
    """
    gaps = [
        q for q in queries
        if q["impressions"] >= 100
        and q["ctr"] < 3.0
        and q["position"] <= 20.0
    ]
    for g in gaps:
        if g["ctr"] < 0.5:
            g["gap_severity"] = "critical"
            g["gap_fix"]      = "Title/meta may be completely mismatched to search intent."
        elif g["ctr"] < 1.5:
            g["gap_severity"] = "high"
            g["gap_fix"]      = "Rewrite title tag and meta description to match searcher intent."
        else:
            g["gap_severity"] = "medium"
            g["gap_fix"]      = "A/B test a more compelling title. Add the query phrase to your meta description."
    gaps.sort(key=lambda x: x["impressions"], reverse=True)
    return gaps[:20]


def _missing_content(queries: List[Dict]) -> List[Dict]:
    """
    Queries with ≥200 impressions AND position > 20 (OR clicks == 0).
    Search demand exists but no page is ranking — create dedicated content.
    """
    missing = [
        q for q in queries
        if q["impressions"] >= 200 and (q["position"] > 20 or q["clicks"] == 0)
    ]
    missing.sort(key=lambda x: x["impressions"], reverse=True)
    return missing[:15]


def _cannibalization(qp_rows: List[Dict]) -> List[Dict]:
    """
    From query×page data, find queries where 2+ different pages appear.
    """
    by_query: Dict[str, List[Dict]] = defaultdict(list)
    for row in qp_rows:
        by_query[row["query"]].append(row)

    cannibal = []
    for query, pages in by_query.items():
        if len(pages) < 2:
            continue
        total_impressions = sum(p["impressions"] for p in pages)
        if total_impressions < 50:
            continue
        pages_sorted = sorted(pages, key=lambda p: p["clicks"], reverse=True)
        cannibal.append({
            "query":   query,
            "pages":   pages_sorted,
            "n_pages": len(pages_sorted),
            "total_impressions": total_impressions,
            "recommended_canonical": pages_sorted[0]["page"],
        })
    cannibal.sort(key=lambda x: x["total_impressions"], reverse=True)
    return cannibal[:10]


def _declining_pages(
    current: List[Dict],
    previous: List[Dict],
    min_current_clicks: int = 5,
    min_decline_pct: float = 20.0,
) -> List[Dict]:
    """Compare two equal-length periods for each page. Flag ≥20% click decline."""
    prev_map = {p["page"]: p for p in previous}
    declining = []
    for cur in current:
        page = cur["page"]
        prev = prev_map.get(page)
        if not prev:
            continue
        if prev["clicks"] < min_current_clicks:
            continue
        if prev["clicks"] == 0:
            continue
        change_pct = (cur["clicks"] - prev["clicks"]) / prev["clicks"] * 100
        if change_pct <= -min_decline_pct:
            declining.append({
                "page":            page,
                "current_clicks":  cur["clicks"],
                "prev_clicks":     prev["clicks"],
                "current_pos":     cur["position"],
                "prev_pos":        prev["position"],
                "change_pct":      round(change_pct, 1),
                "pos_change":      round(cur["position"] - prev["position"], 1),
                "impressions":     cur["impressions"],
            })
    declining.sort(key=lambda x: x["change_pct"])
    return declining[:15]


def _cluster_keywords(queries: List[Dict]) -> List[Dict]:
    """
    Group queries by their first two words (the 'topic root').
    Returns clusters sorted by total impressions descending.
    """
    by_root: Dict[str, List[Dict]] = defaultdict(list)
    for q in queries:
        words = q["query"].lower().split()
        root  = " ".join(words[:2]) if len(words) >= 2 else words[0] if words else "other"
        by_root[root].append(q)

    clusters = []
    for root, qs in by_root.items():
        if len(qs) < 2:
            continue  # only show clusters with 2+ queries
        total_impr  = sum(q["impressions"] for q in qs)
        total_clicks = sum(q["clicks"] for q in qs)
        avg_pos     = (sum(q["position"] * q["impressions"] for q in qs)
                       / total_impr if total_impr else 0)
        best = max(qs, key=lambda q: q["clicks"])
        clusters.append({
            "root":             root,
            "queries":          sorted(qs, key=lambda q: q["impressions"], reverse=True),
            "n_queries":        len(qs),
            "total_impressions": total_impr,
            "total_clicks":     total_clicks,
            "avg_position":     round(avg_pos, 1),
            "best_query":       best["query"],
        })
    clusters.sort(key=lambda c: c["total_impressions"], reverse=True)
    return clusters[:15]


# ─────────────────────────────────────────────────────────────────────────────
# Public entry-point
# ─────────────────────────────────────────────────────────────────────────────

def run_keyword_gap_analysis(aid: int, site_url: str) -> Dict[str, Any]:
    """
    Run the full keyword gap analysis.

    Returns:
        {
          site_url, period_label,
          quick_wins, content_gaps, missing_content,
          cannibalization, declining_pages, clusters,
          summary: {total_opportunity_impressions, quick_wins_count,
                    content_gaps_count, missing_count,
                    cannibalization_count, declining_count},
          error
        }
    """
    result: Dict[str, Any] = {
        "site_url":    site_url,
        "period_label": "",
        "quick_wins":      [],
        "content_gaps":    [],
        "missing_content": [],
        "cannibalization": [],
        "declining_pages": [],
        "clusters":        [],
        "summary":         {},
        "error":           None,
    }

    if not site_url:
        result["error"] = "No GSC site selected."
        return result

    # ── date ranges ────────────────────────────────────────────────────────
    cur_end,  cur_start  = _date_range(3, 30)    # most recent 28 days (3-day lag)
    prev_end, prev_start = _date_range(31, 58)   # previous 28 days

    result["period_label"] = f"{cur_start} → {cur_end}"

    # ── fetch current queries (100 rows) ───────────────────────────────────
    raw_q = _gsc_fetch(aid, site_url, cur_start, cur_end,
                       dimensions=["query"], row_limit=100)
    if not raw_q:
        result["error"] = (
            "No GSC data returned. Make sure Google Search Console is connected "
            "and the site has search traffic."
        )
        return result

    queries = _rows_to_dicts(raw_q, ["query"])

    # ── fetch current pages (50 rows) ──────────────────────────────────────
    raw_p_cur = _gsc_fetch(aid, site_url, cur_start, cur_end,
                           dimensions=["page"], row_limit=50)
    pages_current = _rows_to_dicts(raw_p_cur, ["page"])

    # ── fetch previous pages for decline detection ─────────────────────────
    raw_p_prev = _gsc_fetch(aid, site_url, prev_start, prev_end,
                            dimensions=["page"], row_limit=50)
    pages_previous = _rows_to_dicts(raw_p_prev, ["page"])

    # ── fetch query × page for cannibalization (50 rows) ──────────────────
    raw_qp = _gsc_fetch(aid, site_url, cur_start, cur_end,
                        dimensions=["query", "page"], row_limit=50)
    qp_rows = _rows_to_dicts(raw_qp, ["query", "page"])

    # ── run analyses ───────────────────────────────────────────────────────
    result["quick_wins"]      = _quick_wins(queries)
    result["content_gaps"]    = _content_gaps(queries)
    result["missing_content"] = _missing_content(queries)
    result["cannibalization"]  = _cannibalization(qp_rows)
    result["declining_pages"]  = _declining_pages(pages_current, pages_previous)
    result["clusters"]         = _cluster_keywords(queries)

    # ── summary ────────────────────────────────────────────────────────────
    opp_impressions = sum(q["impressions"] for q in result["quick_wins"])
    result["summary"] = {
        "total_queries":            len(queries),
        "opportunity_impressions":  opp_impressions,
        "quick_wins_count":         len(result["quick_wins"]),
        "content_gaps_count":       len(result["content_gaps"]),
        "missing_count":            len(result["missing_content"]),
        "cannibalization_count":    len(result["cannibalization"]),
        "declining_count":          len(result["declining_pages"]),
        "clusters_count":           len(result["clusters"]),
    }
    return result
