# app/account/revenue_attribution_routes.py
"""
Revenue Attribution dashboard — true cost per booked job.

Route: GET /account/revenue-attribution
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from flask import g, render_template, request
from sqlalchemy import text

from app import db
from app.auth.utils import login_required, current_account_id
from app.account import account_bp

logger = logging.getLogger(__name__)

# ── Benchmark CPL/CPBJ for HVAC (industry default) ────────────────────────────
_INDUSTRY_BOOKING_RATE = 0.30   # 30 % of leads become booked jobs when CRM not connected
_BENCHMARK_CPBJ        = 250.0


def _date_range_from_days(days: int):
    end   = date.today()
    start = end - timedelta(days=days)
    return start, end


def _label_for_days(days: int) -> str:
    return {7: "Last 7 days", 30: "Last 30 days", 90: "Last 90 days"}.get(days, f"Last {days} days")


def _fetch_real_data(aid: int, start: date, end: date):
    """
    Try to pull spend + lead data from google_ads_metrics / lead_ingest tables.
    Returns (metrics_dict, by_campaign_list, crm_connected) or (None, None, False).
    """
    metrics: Optional[Dict[str, Any]] = None
    by_campaign: Optional[List[Dict[str, Any]]] = None
    crm_connected = False

    try:
        with db.engine.connect() as conn:
            # ── Total spend from gads_stats_daily ─────────────────────────────
            spend_row = conn.execute(text("""
                SELECT COALESCE(SUM(gs.cost_micros),0) AS cm
                  FROM gads_stats_daily gs
                  JOIN ads_campaigns ac ON ac.id = gs.entity_id AND ac.account_id = :aid
                 WHERE gs.entity_type = 'campaign'
                   AND gs.date >= :s AND gs.date <= :e
            """), {"aid": aid, "s": start.isoformat(), "e": end.isoformat()}).mappings().first()

            total_spend = float((spend_row["cm"] or 0)) / 1_000_000 if spend_row else 0.0
            if total_spend == 0:
                return None, None, False

            # ── Total leads from lead_ingest ───────────────────────────────────
            leads_row = conn.execute(text("""
                SELECT COUNT(*) AS cnt FROM lead_ingest
                 WHERE account_id = :aid
                   AND occurred_at >= :s AND occurred_at <= :e
            """), {"aid": aid, "s": start.isoformat(), "e": end.isoformat()}).mappings().first()
            total_leads = int((leads_row["cnt"] or 0)) if leads_row else 0

            # ── Check for booked jobs in servicetitan_jobs ─────────────────────
            jobs_row = conn.execute(text("""
                SELECT COUNT(*) AS cnt FROM servicetitan_jobs
                 WHERE account_id = :aid
                   AND completed_date >= :s AND completed_date <= :e
                   AND job_status IN ('Completed','completed')
            """), {"aid": aid, "s": start.isoformat(), "e": end.isoformat()}).mappings().first()
            total_booked = int((jobs_row["cnt"] or 0)) if jobs_row else 0
            crm_connected = total_booked > 0

            if not crm_connected and total_leads > 0:
                # Estimate from industry booking rate
                total_booked = max(1, int(total_leads * _INDUSTRY_BOOKING_RATE))

            cpl    = round(total_spend / total_leads, 2) if total_leads else 0.0
            cpbj   = round(total_spend / total_booked, 2) if total_booked else 0.0
            bk_pct = round(total_booked / total_leads * 100, 1) if total_leads else 0.0

            metrics = {
                "total_spend":          total_spend,
                "total_leads":          total_leads,
                "total_booked_jobs":    total_booked,
                "cost_per_lead":        cpl,
                "cost_per_booked_job":  cpbj,
                "booking_rate_pct":     bk_pct,
            }

            # ── Per-campaign breakdown ─────────────────────────────────────────
            camp_rows = conn.execute(text("""
                SELECT ac.name AS campaign_name,
                       COALESCE(SUM(gs.cost_micros),0) / 1000000.0 AS spend,
                       COALESCE(SUM(gs.conversions),0)              AS leads
                  FROM gads_stats_daily gs
                  JOIN ads_campaigns ac ON ac.id = gs.entity_id AND ac.account_id = :aid
                 WHERE gs.entity_type = 'campaign'
                   AND gs.date >= :s AND gs.date <= :e
                 GROUP BY ac.id, ac.name
                 ORDER BY spend DESC
            """), {"aid": aid, "s": start.isoformat(), "e": end.isoformat()}).mappings().all()

            by_campaign = []
            for r in camp_rows:
                sp = float(r["spend"] or 0)
                ls = int(r["leads"] or 0)
                bj = max(1, int(ls * _INDUSTRY_BOOKING_RATE)) if ls > 0 else 0
                row_cpl  = round(sp / ls, 2)  if ls else None
                row_cpbj = round(sp / bj, 2)  if bj else None
                by_campaign.append({
                    "campaign_name":    r["campaign_name"] or "Unknown",
                    "spend":            sp,
                    "leads":            ls,
                    "booked_jobs":      bj,
                    "cpl":              row_cpl  or 0.0,
                    "cpbj":             row_cpbj,
                    "roas_if_available": None,
                })

    except Exception as exc:
        logger.warning("revenue_attribution data fetch failed: %s", exc)
        return None, None, False

    return metrics, by_campaign, crm_connected


# ── Route ──────────────────────────────────────────────────────────────────────

@account_bp.route("/revenue-attribution", methods=["GET"], endpoint="revenue_attribution")
@login_required
def revenue_attribution():
    aid  = current_account_id()
    days = int(request.args.get("days", 30))
    if days not in (7, 30, 90):
        days = 30

    start, end   = _date_range_from_days(days)
    date_range   = _label_for_days(days)
    metrics      = None
    by_campaign  = None
    crm_connected = False

    if aid:
        metrics, by_campaign, crm_connected = _fetch_real_data(aid, start, end)

    return render_template(
        "account/revenue_attribution.html",
        metrics=metrics,
        by_campaign=by_campaign,
        crm_connected=crm_connected,
        date_range=date_range,
    )
