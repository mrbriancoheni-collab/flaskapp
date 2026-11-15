"""
Campaign Mix Snapshot Service (enhancement 10).

Takes a weekly snapshot of the campaign-type distribution for one account
and stores it in gads_campaign_mix_snapshots.  Used for:
  - Trend charts showing how the mix is changing over time
  - Optimizer alerts when a high-ROI type is absent or under-represented
  - Digest type-breakdown history

The APScheduler weekly digest trigger should call take_mix_snapshot() after
calling generate_weekly_digest().
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import text

log = logging.getLogger(__name__)

# Types that the optimizer will flag as missing when spend is 0
HIGH_ROI_TYPES = {"SHOPPING", "PERFORMANCE_MAX"}
# iROAS benchmarks: Shopping 2.1×, PMax 1.8× — both higher than Search 1.7×

MISSING_TYPE_THRESHOLD_WEEKS = 4  # flag if absent for this many consecutive weeks


def take_mix_snapshot(account_id: int, week_start: Optional[date] = None) -> Dict[str, Any]:
    """
    Compute the campaign-type spend distribution for the last 7 days and
    upsert into gads_campaign_mix_snapshots.

    Returns summary dict with per-type rows and any high-ROI-type absence alert.
    """
    from app import db

    if week_start is None:
        week_start = date.today() - timedelta(days=7)
    week_end = week_start + timedelta(days=7)

    result: Dict[str, Any] = {
        "account_id": account_id,
        "week_start": week_start.isoformat(),
        "rows": [],
        "missing_high_roi_types": [],
        "errors": [],
    }

    try:
        rows = db.session.execute(text("""
            SELECT COALESCE(ac.campaign_type, 'UNKNOWN') AS campaign_type,
                   COUNT(DISTINCT ac.id)                 AS campaign_count,
                   SUM(gs.cost_micros) / 1000000.0       AS spend,
                   SUM(gs.conversions)                   AS conversions
            FROM gads_stats_daily gs
            JOIN ads_campaigns ac ON ac.id = gs.entity_id AND ac.account_id = :aid
            WHERE gs.entity_type = 'campaign'
              AND gs.date >= :s AND gs.date < :e
            GROUP BY COALESCE(ac.campaign_type, 'UNKNOWN')
        """), {"aid": account_id, "s": str(week_start), "e": str(week_end)}).mappings().all()

        if not rows:
            result["errors"].append("No campaign stats for the period")
            return result

        total_spend = sum(float(r["spend"] or 0) for r in rows)

        type_rows: List[Dict[str, Any]] = []
        seen_types = set()
        for r in rows:
            spend = float(r["spend"] or 0)
            ct = r["campaign_type"]
            seen_types.add(ct)
            spend_pct = round(spend / total_spend * 100, 2) if total_spend > 0 else 0.0
            type_rows.append({
                "campaign_type": ct,
                "campaign_count": int(r["campaign_count"] or 0),
                "spend": round(spend, 4),
                "spend_pct": spend_pct,
                "conversions": float(r["conversions"] or 0),
            })

        # Upsert each row into the snapshot table
        for row in type_rows:
            try:
                db.session.execute(text("""
                    INSERT INTO gads_campaign_mix_snapshots
                        (account_id, week_start, campaign_type, campaign_count,
                         spend, spend_pct, conversions)
                    VALUES (:aid, :ws, :ct, :cc, :sp, :spct, :conv)
                    ON DUPLICATE KEY UPDATE
                        campaign_count = VALUES(campaign_count),
                        spend          = VALUES(spend),
                        spend_pct      = VALUES(spend_pct),
                        conversions    = VALUES(conversions)
                """), {
                    "aid":  account_id,
                    "ws":   str(week_start),
                    "ct":   row["campaign_type"],
                    "cc":   row["campaign_count"],
                    "sp":   row["spend"],
                    "spct": row["spend_pct"],
                    "conv": row["conversions"],
                })
            except Exception as exc:
                log.warning("mix snapshot upsert failed for type %s: %s", row["campaign_type"], exc)
                db.session.rollback()

        db.session.commit()
        result["rows"] = type_rows

        # Flag high-ROI types that are absent
        for ht in HIGH_ROI_TYPES:
            if ht not in seen_types:
                result["missing_high_roi_types"].append(ht)

    except Exception as exc:
        db.session.rollback()
        log.warning("take_mix_snapshot failed for account %d: %s", account_id, exc)
        result["errors"].append(str(exc))

    return result


def get_mix_history(account_id: int, weeks: int = 8) -> List[Dict[str, Any]]:
    """
    Return the last `weeks` weeks of mix snapshots for an account,
    sorted oldest first, as a list of {week_start, by_type: [{...}]}.
    """
    from app import db
    try:
        cutoff = date.today() - timedelta(weeks=weeks)
        rows = db.session.execute(text("""
            SELECT week_start, campaign_type, campaign_count,
                   spend, spend_pct, conversions
            FROM gads_campaign_mix_snapshots
            WHERE account_id = :aid AND week_start >= :cutoff
            ORDER BY week_start ASC, spend DESC
        """), {"aid": account_id, "cutoff": str(cutoff)}).mappings().all()

        # Group by week
        weeks_map: Dict[Any, List[Dict[str, Any]]] = {}
        for r in rows:
            ws = str(r["week_start"])
            if ws not in weeks_map:
                weeks_map[ws] = []
            weeks_map[ws].append({
                "campaign_type": r["campaign_type"],
                "campaign_count": int(r["campaign_count"] or 0),
                "spend": float(r["spend"] or 0),
                "spend_pct": float(r["spend_pct"] or 0),
                "conversions": float(r["conversions"] or 0),
            })

        return [{"week_start": ws, "by_type": by_type} for ws, by_type in sorted(weeks_map.items())]
    except Exception:
        db.session.rollback()
        return []
