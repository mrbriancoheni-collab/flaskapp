"""
Credit Gap Service (Item 4).

Compares ad-platform attributed spend against actual ServiceTitan booked
revenue to surface the "credit gap" — money the ads generated that isn't
being tracked.

Key metrics:
  ad_spend         — Google Ads spend in the period (gads_stats_daily)
  st_revenue       — ServiceTitan completed-job revenue (servicetitan_jobs)
  revenue_gap      — st_revenue - ad_spend (how much revenue was produced per $ spent)
  new_cust_rev     — revenue from first-time customers in the period
  repeat_cust_rev  — revenue from returning customers
  new_cust_pct     — new_cust_rev / st_revenue * 100
  retention_leaning — True when new_cust_pct < NEW_CUSTOMER_PCT_THRESHOLD (35% default)
  unmatched_jobs   — ST jobs with no matching lead_ingest record (untracked source)
  largest_gap_campaign — campaign with the biggest spend but lowest revenue contribution
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text

log = logging.getLogger(__name__)

# Configurable threshold — below this % of new-customer revenue = retention-leaning
NEW_CUSTOMER_PCT_THRESHOLD: float = 35.0


def _fetch_ad_spend(db, aid: int, start: date, end: date) -> Tuple[float, List[Dict[str, Any]]]:
    """Return (total_spend, per_campaign_list)."""
    total = 0.0
    campaigns: List[Dict[str, Any]] = []
    try:
        rows = db.session.execute(text("""
            SELECT ac.id AS campaign_id,
                   ac.name AS campaign_name,
                   COALESCE(SUM(gs.cost_micros), 0) / 1000000.0 AS spend,
                   COALESCE(SUM(gs.conversions), 0)              AS conversions
            FROM gads_stats_daily gs
            JOIN ads_campaigns ac ON ac.id = gs.entity_id AND ac.account_id = :aid
            WHERE gs.entity_type = 'campaign'
              AND gs.date >= :s AND gs.date <= :e
            GROUP BY ac.id, ac.name
            ORDER BY spend DESC
        """), {"aid": aid, "s": str(start), "e": str(end)}).mappings().all()

        for r in rows:
            sp = float(r["spend"] or 0)
            campaigns.append({
                "campaign_id":   r["campaign_id"],
                "campaign_name": r["campaign_name"] or "Unknown",
                "spend":         sp,
                "conversions":   float(r["conversions"] or 0),
            })
            total += sp
    except Exception:
        db.session.rollback()
        log.warning("ad_spend fetch failed for account %d", aid)
    return total, campaigns


def _fetch_st_revenue(db, aid: int, start: date, end: date) -> Dict[str, Any]:
    """
    Pull ServiceTitan booked revenue for the period, split by new vs repeat customer.

    A customer is "new" if they have no completed jobs before `start`.
    """
    result = {
        "total":        0.0,
        "new_cust":     0.0,
        "repeat_cust":  0.0,
        "total_jobs":   0,
        "unmatched_jobs": 0,
        "job_rows":     [],
    }

    try:
        # Completed jobs in period
        job_rows = db.session.execute(text("""
            SELECT j.id, j.st_customer_id, j.job_number,
                   COALESCE(j.total_amount, 0) AS revenue,
                   j.completed_date
            FROM servicetitan_jobs j
            WHERE j.account_id = :aid
              AND j.job_status IN ('Completed', 'completed', 'Done', 'done')
              AND j.completed_date >= :s AND j.completed_date <= :e
        """), {"aid": aid, "s": str(start), "e": str(end)}).mappings().all()

        if not job_rows:
            return result

        # Gather all customer IDs in one query
        cust_ids = list({r["st_customer_id"] for r in job_rows if r["st_customer_id"]})

        if cust_ids:
            # Customers who had a completed job BEFORE the period
            placeholders = ",".join([":c" + str(i) for i in range(len(cust_ids))])
            params = {"aid": aid, "s": str(start)}
            params.update({f"c{i}": cid for i, cid in enumerate(cust_ids)})
            repeat_rows = db.session.execute(text(f"""
                SELECT DISTINCT st_customer_id
                FROM servicetitan_jobs
                WHERE account_id = :aid
                  AND st_customer_id IN ({placeholders})
                  AND job_status IN ('Completed', 'completed', 'Done', 'done')
                  AND completed_date < :s
            """), params).fetchall()
            repeat_customers = {r[0] for r in repeat_rows}
        else:
            repeat_customers = set()

        # Customers who have a lead_ingest match (tracked source)
        if cust_ids:
            # Try to match via phone number stored on the customer record
            matched_rows = db.session.execute(text(f"""
                SELECT DISTINCT stc.st_customer_id
                FROM servicetitan_customers stc
                JOIN lead_ingest li ON li.account_id = :aid
                  AND li.phone IS NOT NULL
                  AND stc.phone IS NOT NULL
                  AND REPLACE(REPLACE(li.phone, '-', ''), ' ', '')
                      = REPLACE(REPLACE(stc.phone, '-', ''), ' ', '')
                WHERE stc.account_id = :aid
                  AND stc.st_customer_id IN ({placeholders})
            """), params).fetchall()
            matched_customers = {r[0] for r in matched_rows}
        else:
            matched_customers = set()

        total = 0.0
        new_rev = 0.0
        repeat_rev = 0.0
        unmatched = 0

        for r in job_rows:
            rev = float(r["revenue"] or 0)
            cid = r["st_customer_id"]
            total += rev
            if cid in repeat_customers:
                repeat_rev += rev
            else:
                new_rev += rev
            if cid not in matched_customers:
                unmatched += 1

        result["total"]           = round(total, 2)
        result["new_cust"]        = round(new_rev, 2)
        result["repeat_cust"]     = round(repeat_rev, 2)
        result["total_jobs"]      = len(job_rows)
        result["unmatched_jobs"]  = unmatched
        result["job_rows"]        = [dict(r) for r in job_rows]

    except Exception:
        db.session.rollback()
        log.warning("st_revenue fetch failed for account %d", aid)

    return result


def _flag_largest_gap(campaigns: List[Dict[str, Any]], st_revenue: float, total_spend: float) -> Optional[Dict[str, Any]]:
    """
    Identify the campaign with the highest spend-to-estimated-revenue gap.

    Without per-campaign ST attribution, we estimate revenue contribution
    proportional to conversions share.  Campaigns with spend but zero
    conversions have 100% of their spend unattributed.
    """
    if not campaigns or total_spend == 0:
        return None

    total_conversions = sum(c["conversions"] for c in campaigns)

    flagged = None
    worst_ratio = float("-inf")

    for c in campaigns:
        if c["spend"] <= 0:
            continue
        if total_conversions > 0:
            attr_rev = st_revenue * (c["conversions"] / total_conversions)
        else:
            attr_rev = 0.0
        gap = c["spend"] - attr_rev
        ratio = gap / c["spend"]  # higher = worse (more spend, less return)
        c["estimated_revenue"] = round(attr_rev, 2)
        c["revenue_gap"]       = round(gap, 2)
        c["gap_ratio"]         = round(ratio, 3)
        if ratio > worst_ratio:
            worst_ratio = ratio
            flagged = c

    return flagged


def build_credit_gap(
    db,
    aid: int,
    start: date,
    end: date,
    new_customer_threshold: float = NEW_CUSTOMER_PCT_THRESHOLD,
) -> Dict[str, Any]:
    """
    Main entry point.  Returns the full credit gap view data dict.
    """
    total_spend, campaigns = _fetch_ad_spend(db, aid, start, end)
    st = _fetch_st_revenue(db, aid, start, end)

    st_revenue     = st["total"]
    new_cust_rev   = st["new_cust"]
    repeat_cust_rev = st["repeat_cust"]
    total_jobs     = st["total_jobs"]
    unmatched_jobs = st["unmatched_jobs"]

    revenue_gap = round(st_revenue - total_spend, 2)

    new_cust_pct = (
        round(new_cust_rev / st_revenue * 100, 1) if st_revenue > 0 else 0.0
    )
    retention_leaning = (
        new_cust_pct < new_customer_threshold and st_revenue > 0
    )

    unmatched_pct = round(unmatched_jobs / total_jobs * 100, 1) if total_jobs > 0 else 0.0

    largest_gap_campaign = _flag_largest_gap(campaigns, st_revenue, total_spend)

    roas = round(st_revenue / total_spend, 2) if total_spend > 0 else None

    return {
        "ad_spend":              round(total_spend, 2),
        "st_revenue":            st_revenue,
        "revenue_gap":           revenue_gap,
        "roas":                  roas,
        "new_cust_rev":          new_cust_rev,
        "repeat_cust_rev":       repeat_cust_rev,
        "new_cust_pct":          new_cust_pct,
        "retention_leaning":     retention_leaning,
        "new_customer_threshold": new_customer_threshold,
        "total_jobs":            total_jobs,
        "unmatched_jobs":        unmatched_jobs,
        "unmatched_pct":         unmatched_pct,
        "campaigns":             campaigns,
        "largest_gap_campaign":  largest_gap_campaign,
        "has_st_data":           st_revenue > 0,
        "has_ad_data":           total_spend > 0,
    }
