# app/services/keyword_rank_tracker.py
"""
Keyword Ranking History Tracker.

Pulls weekly GSC keyword position data and stores snapshots for trend analysis.
Uses the same GSC auth helpers as app.seo.keyword_gaps.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List, Optional


def snapshot_rankings(account_id: int) -> Dict[str, Any]:
    """
    Pull this week's GSC top-100 keyword positions for the account and store as a snapshot.

    Fetches the last 7 days of data (URL+keyword pairs by impressions) and
    upserts each row into KeywordRankSnapshot with snapshot_date = today.

    Returns {"snapshots": N, "urls": M} on success or {"error": "..."} on failure.
    """
    from app.seo.keyword_gaps import _gsc_fetch, _rows_to_dicts, _date_range
    from app.google import _is_connected, _get_gsc_selected_site
    from app.models_wp import KeywordRankSnapshot
    from app import db

    if not _is_connected(account_id, "gsc"):
        return {"error": "GSC not connected for this account"}

    site_url = _get_gsc_selected_site(account_id)
    if not site_url:
        return {"error": "No GSC site URL configured for this account"}

    # Last 7 days (with GSC's typical 3-day reporting lag)
    end_date, start_date = _date_range(3, 10)

    raw = _gsc_fetch(
        account_id,
        site_url,
        start_date,
        end_date,
        dimensions=["page", "query"],
        row_limit=100,
        order_by=[{"fieldName": "impressions", "sortOrder": "DESCENDING"}],
    )

    if not raw:
        return {"error": "No GSC data returned — site may have no search traffic yet"}

    rows = _rows_to_dicts(raw, ["page", "query"])
    today = date.today()
    snapshots_written = 0
    urls_seen: set = set()

    for row in rows:
        url = (row.get("page") or "").strip()
        keyword = (row.get("query") or "").strip()
        if not url or not keyword:
            continue

        urls_seen.add(url)

        # Upsert: try to find existing row for this account/url/keyword/date
        existing = KeywordRankSnapshot.query.filter_by(
            account_id=account_id,
            url=url,
            keyword=keyword,
            snapshot_date=today,
        ).first()

        position_val = row.get("position")
        ctr_raw = row.get("ctr", 0)
        # keyword_gaps stores ctr as percentage (× 100); store raw fraction (0–1) here
        ctr_val = round(ctr_raw / 100, 6) if ctr_raw else 0

        if existing:
            existing.position = position_val
            existing.impressions = row.get("impressions")
            existing.clicks = row.get("clicks")
            existing.ctr = ctr_val
        else:
            snap = KeywordRankSnapshot(
                account_id=account_id,
                url=url,
                keyword=keyword,
                position=position_val,
                impressions=row.get("impressions"),
                clicks=row.get("clicks"),
                ctr=ctr_val,
                snapshot_date=today,
            )
            db.session.add(snap)
            snapshots_written += 1

    try:
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        return {"error": f"DB commit failed: {exc}"}

    return {
        "snapshots": snapshots_written,
        "urls": len(urls_seen),
    }


def get_ranking_trends(
    account_id: int,
    url: Optional[str] = None,
    days: int = 90,
) -> List[Dict[str, Any]]:
    """
    Return ranking trend data for charting.

    Returns a list of dicts:
        {url, keyword, snapshots: [{date, position, impressions, clicks, ctr}, ...]}

    - Optionally filtered to a single URL.
    - Only includes URL+keyword combos with at least 2 snapshots.
    - Limited to top 20 combos by latest impressions.
    - Snapshots ordered oldest → newest within each combo.
    """
    from app.models_wp import KeywordRankSnapshot
    from sqlalchemy import func

    cutoff = date.today() - timedelta(days=days)

    q = KeywordRankSnapshot.query.filter(
        KeywordRankSnapshot.account_id == account_id,
        KeywordRankSnapshot.snapshot_date >= cutoff,
    )
    if url:
        q = q.filter(KeywordRankSnapshot.url == url)

    all_snaps = q.order_by(
        KeywordRankSnapshot.url,
        KeywordRankSnapshot.keyword,
        KeywordRankSnapshot.snapshot_date,
    ).all()

    # Group by (url, keyword)
    from collections import defaultdict
    grouped: Dict[tuple, list] = defaultdict(list)
    for s in all_snaps:
        grouped[(s.url, s.keyword)].append(s)

    # Filter to combos with at least 2 snapshots
    valid = {k: v for k, v in grouped.items() if len(v) >= 2}

    # Rank by latest snapshot impressions descending
    def _latest_impressions(snaps):
        latest = max(snaps, key=lambda s: s.snapshot_date)
        return latest.impressions or 0

    top_combos = sorted(valid.items(), key=lambda kv: _latest_impressions(kv[1]), reverse=True)[:20]

    result = []
    for (combo_url, keyword), snaps in top_combos:
        snapshots_list = [
            {
                "date": s.snapshot_date.isoformat(),
                "position": float(s.position) if s.position is not None else None,
                "impressions": s.impressions,
                "clicks": s.clicks,
                "ctr": float(s.ctr) if s.ctr is not None else None,
            }
            for s in sorted(snaps, key=lambda s: s.snapshot_date)
        ]
        result.append({
            "url": combo_url,
            "keyword": keyword,
            "snapshots": snapshots_list,
        })

    return result
