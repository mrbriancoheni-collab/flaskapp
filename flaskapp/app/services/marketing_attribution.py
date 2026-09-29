# app/services/marketing_attribution.py
"""
Marketing Attribution Service

Provides channel-level performance analytics, budget pacing, growth
recommendations, lead-to-job attribution, customer LTV by channel, and
helpers for recording offline spend/leads and ingesting aggregator leads.

All public functions are safe to call even when tables are partially
populated — errors are caught and logged, and safe defaults are returned.
"""
from __future__ import annotations

import calendar
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from app import db

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

# Maps channel_type → AdSpend.source value used in the ad_spend table
_DIGITAL_SOURCE_MAP: Dict[str, str] = {
    "google_ads": "google-ads",
    "lsa": "glsa",
    "facebook": "facebook",
    "yelp": "yelp",
}

_DIGITAL_TYPES = set(_DIGITAL_SOURCE_MAP.keys())


def _safe_div(numerator: Optional[float], denominator: Optional[float]) -> Optional[float]:
    """Return numerator/denominator or None when denominator is zero/None."""
    if not denominator:
        return None
    if numerator is None:
        return None
    return numerator / denominator


def _current_ym() -> tuple[int, int]:
    """Return (year, month) for the current UTC month."""
    now = datetime.utcnow()
    return now.year, now.month


def _lookback_periods(lookback_months: int) -> list[tuple[int, int]]:
    """
    Return a list of (year, month) tuples for the last *lookback_months*
    complete months, newest first.
    """
    now = datetime.utcnow()
    periods: list[tuple[int, int]] = []
    year, month = now.year, now.month
    for _ in range(lookback_months):
        month -= 1
        if month == 0:
            month = 12
            year -= 1
        periods.append((year, month))
    return periods


def _channel_stats_for_period(
    channel,  # MarketingChannel instance
    year: int,
    month: int,
) -> Dict[str, Any]:
    """
    Build a stats dict for one channel for one calendar month.
    Pulls spend from ChannelSpendEntry (falling back to AdSpend for digital
    channels) and leads from ChannelLeadEntry (also counting LeadIngest for
    digital channels).
    """
    from app.models_marketing import ChannelSpendEntry, ChannelLeadEntry
    from app.models_tooling import AdSpend, LeadIngest

    spend_cents: int = 0
    leads: int = 0
    booked: int = 0
    revenue_cents: int = 0

    # --- Spend ---
    try:
        spend_row = (
            ChannelSpendEntry.query
            .filter_by(channel_id=channel.id, period_year=year, period_month=month)
            .first()
        )
        if spend_row:
            spend_cents = spend_row.amount_cents or 0
        elif channel.channel_type in _DIGITAL_TYPES:
            # Fall back to AdSpend table for digital channels
            source = _DIGITAL_SOURCE_MAP[channel.channel_type]
            from sqlalchemy import extract, func as sqlfunc
            ad_row = (
                db.session.query(sqlfunc.sum(AdSpend.amount))
                .filter(
                    AdSpend.account_id == channel.account_id,
                    AdSpend.source == source,
                    extract("year", AdSpend.spend_date) == year,
                    extract("month", AdSpend.spend_date) == month,
                )
                .scalar()
            )
            if ad_row is not None:
                # AdSpend.amount is Numeric(12,2) dollars — convert to cents
                spend_cents = int(float(ad_row) * 100)
    except Exception:
        log.exception("_channel_stats_for_period: spend query failed for channel %s", channel.id)

    # --- Leads ---
    try:
        lead_row = (
            ChannelLeadEntry.query
            .filter_by(channel_id=channel.id, period_year=year, period_month=month)
            .first()
        )
        if lead_row:
            leads = lead_row.lead_count or 0
            booked = lead_row.booked_count or 0
            revenue_cents = lead_row.revenue_cents or 0
        elif channel.channel_type in _DIGITAL_TYPES:
            # Count LeadIngest rows for the month as a fallback
            source = _DIGITAL_SOURCE_MAP[channel.channel_type]
            from sqlalchemy import extract
            month_start = datetime(year, month, 1)
            _, last_day = calendar.monthrange(year, month)
            month_end = datetime(year, month, last_day, 23, 59, 59)
            leads = (
                LeadIngest.query
                .filter(
                    LeadIngest.account_id == channel.account_id,
                    LeadIngest.source == source,
                    LeadIngest.occurred_at >= month_start,
                    LeadIngest.occurred_at <= month_end,
                )
                .count()
            )
    except Exception:
        log.exception("_channel_stats_for_period: lead query failed for channel %s", channel.id)

    # --- Derived metrics ---
    spend_f = float(spend_cents)
    cpl = _safe_div(spend_f, leads)
    cac = _safe_div(spend_f, booked)
    close_rate = _safe_div(booked, leads)
    avg_ticket_cents = int(_safe_div(revenue_cents, booked) or 0)
    roi = _safe_div(revenue_cents, spend_cents) if spend_cents else None

    return {
        "id": channel.id,
        "name": channel.name,
        "channel_type": channel.channel_type,
        "spend_cents": spend_cents,
        "leads": leads,
        "booked": booked,
        "revenue_cents": revenue_cents,
        "cpl": round(cpl, 2) if cpl is not None else None,
        "cac": round(cac, 2) if cac is not None else None,
        "close_rate": round(close_rate, 4) if close_rate is not None else None,
        "avg_ticket_cents": avg_ticket_cents,
        "roi": round(roi, 4) if roi is not None else None,
        "is_active": channel.is_active,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_channel_stats(account_id: int, year: int, month: int) -> List[Dict[str, Any]]:
    """
    Return a list of channel performance dicts for every active
    MarketingChannel belonging to *account_id* in the given month.

    Results are sorted by CAC ascending (lowest CAC first, nulls last).
    """
    from app.models_marketing import MarketingChannel

    try:
        channels = (
            MarketingChannel.query
            .filter_by(account_id=account_id, is_active=True)
            .all()
        )
    except Exception:
        log.exception("get_channel_stats: failed to load channels for account %s", account_id)
        return []

    stats: List[Dict[str, Any]] = []
    for channel in channels:
        try:
            row = _channel_stats_for_period(channel, year, month)
            stats.append(row)
        except Exception:
            log.exception(
                "get_channel_stats: failed for channel %s in %s-%s",
                channel.id, year, month,
            )

    # Sort by CAC asc, nulls last
    stats.sort(key=lambda r: (r["cac"] is None, r["cac"] or 0))
    return stats


def get_all_channel_stats(
    account_id: int,
    lookback_months: int = 3,
) -> List[Dict[str, Any]]:
    """
    Aggregate stats for all active channels across the last *lookback_months*
    complete months.

    Spend, leads, booked, and revenue are summed; CPL/CAC/close_rate/ROI are
    recomputed from the aggregated totals.
    """
    from app.models_marketing import MarketingChannel

    periods = _lookback_periods(lookback_months)
    if not periods:
        return []

    try:
        channels = (
            MarketingChannel.query
            .filter_by(account_id=account_id, is_active=True)
            .all()
        )
    except Exception:
        log.exception("get_all_channel_stats: failed to load channels for account %s", account_id)
        return []

    results: List[Dict[str, Any]] = []
    for channel in channels:
        totals: Dict[str, Any] = {
            "id": channel.id,
            "name": channel.name,
            "channel_type": channel.channel_type,
            "is_active": channel.is_active,
            "spend_cents": 0,
            "leads": 0,
            "booked": 0,
            "revenue_cents": 0,
        }
        for year, month in periods:
            try:
                row = _channel_stats_for_period(channel, year, month)
                totals["spend_cents"] += row["spend_cents"]
                totals["leads"] += row["leads"]
                totals["booked"] += row["booked"]
                totals["revenue_cents"] += row["revenue_cents"]
            except Exception:
                log.exception(
                    "get_all_channel_stats: error for channel %s period %s-%s",
                    channel.id, year, month,
                )

        spend_f = float(totals["spend_cents"])
        totals["cpl"] = round(_safe_div(spend_f, totals["leads"]) or 0, 2) or None
        totals["cac"] = round(_safe_div(spend_f, totals["booked"]) or 0, 2) or None
        totals["close_rate"] = _safe_div(totals["booked"], totals["leads"])
        if totals["close_rate"] is not None:
            totals["close_rate"] = round(totals["close_rate"], 4)
        totals["avg_ticket_cents"] = int(
            _safe_div(totals["revenue_cents"], totals["booked"]) or 0
        )
        totals["roi"] = _safe_div(totals["revenue_cents"], totals["spend_cents"])
        if totals["roi"] is not None:
            totals["roi"] = round(totals["roi"], 4)

        results.append(totals)

    results.sort(key=lambda r: (r["cac"] is None, r["cac"] or 0))
    return results


def get_budget_pacing(account_id: int) -> Dict[str, Any]:
    """
    Return current-month budget pacing for *account_id*.

    Keys returned:
        total_budget_cents, total_spent_cents,
        days_in_month, days_elapsed, pacing_pct, actual_pct,
        status ('on_pace' | 'underspending' | 'overspending'),
        per_channel (list of per-channel breakdowns)
    """
    from app.models_marketing import MarketingBudget, MarketingChannel, ChannelSpendEntry
    from app.models_tooling import AdSpend
    from sqlalchemy import func as sqlfunc, extract

    now = datetime.utcnow()
    year, month = now.year, now.month
    days_in_month = calendar.monthrange(year, month)[1]
    days_elapsed = now.day

    empty: Dict[str, Any] = {
        "total_budget_cents": None,
        "total_spent_cents": 0,
        "days_in_month": days_in_month,
        "days_elapsed": days_elapsed,
        "pacing_pct": round(days_elapsed / days_in_month, 4),
        "actual_pct": None,
        "status": "underspending",
        "per_channel": [],
    }

    try:
        budget_row = (
            MarketingBudget.query
            .filter_by(account_id=account_id, period_year=year, period_month=month)
            .first()
        )
        total_budget_cents: Optional[int] = budget_row.total_budget_cents if budget_row else None

        channels = (
            MarketingChannel.query
            .filter_by(account_id=account_id, is_active=True)
            .all()
        )

        per_channel: List[Dict[str, Any]] = []
        total_spent = 0

        for channel in channels:
            ch_spent = 0
            # Channel spend entry
            spend_row = (
                ChannelSpendEntry.query
                .filter_by(channel_id=channel.id, period_year=year, period_month=month)
                .first()
            )
            if spend_row:
                ch_spent = spend_row.amount_cents or 0
            elif channel.channel_type in _DIGITAL_TYPES:
                source = _DIGITAL_SOURCE_MAP[channel.channel_type]
                ad_total = (
                    db.session.query(sqlfunc.sum(AdSpend.amount))
                    .filter(
                        AdSpend.account_id == account_id,
                        AdSpend.source == source,
                        extract("year", AdSpend.spend_date) == year,
                        extract("month", AdSpend.spend_date) == month,
                    )
                    .scalar()
                )
                if ad_total is not None:
                    ch_spent = int(float(ad_total) * 100)

            total_spent += ch_spent
            pacing_pct = round(days_elapsed / days_in_month, 4)
            channel_budget = channel.monthly_budget_cents
            ch_actual_pct = (
                round(ch_spent / channel_budget, 4) if channel_budget else None
            )
            ch_status = "on_pace"
            if ch_actual_pct is not None:
                if ch_actual_pct < pacing_pct * 0.85:
                    ch_status = "underspending"
                elif ch_actual_pct > pacing_pct * 1.15:
                    ch_status = "overspending"

            per_channel.append({
                "channel_id": channel.id,
                "channel_name": channel.name,
                "channel_type": channel.channel_type,
                "budget_cents": channel_budget,
                "spent_cents": ch_spent,
                "actual_pct": ch_actual_pct,
                "pacing_pct": pacing_pct,
                "status": ch_status,
            })

        pacing_pct = round(days_elapsed / days_in_month, 4)
        actual_pct = (
            round(total_spent / total_budget_cents, 4) if total_budget_cents else None
        )
        status = "on_pace"
        if actual_pct is not None:
            if actual_pct < pacing_pct * 0.85:
                status = "underspending"
            elif actual_pct > pacing_pct * 1.15:
                status = "overspending"

        return {
            "total_budget_cents": total_budget_cents,
            "total_spent_cents": total_spent,
            "days_in_month": days_in_month,
            "days_elapsed": days_elapsed,
            "pacing_pct": pacing_pct,
            "actual_pct": actual_pct,
            "status": status,
            "per_channel": per_channel,
        }

    except Exception:
        log.exception("get_budget_pacing: failed for account %s", account_id)
        return empty


def get_growth_recommendations(account_id: int) -> List[Dict[str, Any]]:
    """
    Rank channels by CAC and return actionable budget recommendations.

    Actions:
    - Lowest-CAC active channels at/under budget  → "Increase budget by 20-30%"
    - Top-2 highest-CAC channels                  → "Reduce budget / review ROI"
    - Active channels with 0 leads in last 30 days → "Review or pause"
    """
    from app.models_marketing import MarketingChannel, ChannelSpendEntry, ChannelLeadEntry

    recommendations: List[Dict[str, Any]] = []

    try:
        all_stats = get_all_channel_stats(account_id, lookback_months=3)
        if not all_stats:
            return []

        # Channels with valid CAC
        with_cac = [s for s in all_stats if s.get("cac") is not None]
        without_cac = [s for s in all_stats if s.get("cac") is None]

        sorted_by_cac = sorted(with_cac, key=lambda r: r["cac"])

        # Current month for budget-cap check
        year, month = _current_ym()
        _, last_day = calendar.monthrange(year, month)
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)

        channels_by_id: Dict[int, Any] = {}
        try:
            channels_by_id = {
                c.id: c
                for c in MarketingChannel.query.filter_by(
                    account_id=account_id, is_active=True
                ).all()
            }
        except Exception:
            log.exception("get_growth_recommendations: channel load failed")

        def _current_spend(channel_id: int) -> int:
            try:
                row = ChannelSpendEntry.query.filter_by(
                    channel_id=channel_id, period_year=year, period_month=month
                ).first()
                return row.amount_cents if row else 0
            except Exception:
                return 0

        # --- Increase recommendations (top half by low CAC) ---
        top_half = sorted_by_cac[: max(1, len(sorted_by_cac) // 2)]
        for stat in top_half:
            ch = channels_by_id.get(stat["id"])
            if not ch:
                continue
            current_spend = _current_spend(ch.id)
            budget_cap = ch.monthly_budget_cents or 0
            at_or_under = (budget_cap == 0) or (current_spend <= budget_cap)
            if at_or_under:
                projected_cac = round(stat["cac"] * 0.85, 2) if stat["cac"] else None
                avg_monthly_leads = round(stat["leads"] / 3, 1) if stat["leads"] else 0
                projected_leads = round(avg_monthly_leads * 1.25, 1)
                recommendations.append({
                    "channel_id": ch.id,
                    "channel_name": ch.name,
                    "channel_type": ch.channel_type,
                    "recommendation": (
                        f"Strong performer — consider increasing budget by 20-30% "
                        f"(current CAC: ${stat['cac']:.0f})"
                    ),
                    "action": "increase_budget",
                    "current_cac": stat["cac"],
                    "projected_cac": projected_cac,
                    "potential_monthly_leads": projected_leads,
                    "priority": "high",
                })

        # --- Reduce/review recommendations (top 2 highest CAC) ---
        bottom_two = sorted_by_cac[-2:] if len(sorted_by_cac) >= 2 else sorted_by_cac[-1:]
        # Avoid overlap with increase set
        increase_ids = {r["channel_id"] for r in recommendations}
        for stat in reversed(bottom_two):
            if stat["id"] in increase_ids:
                continue
            ch = channels_by_id.get(stat["id"])
            if not ch:
                continue
            recommendations.append({
                "channel_id": ch.id,
                "channel_name": ch.name,
                "channel_type": ch.channel_type,
                "recommendation": (
                    f"High CAC — reduce budget or review creative/targeting "
                    f"(current CAC: ${stat['cac']:.0f})"
                ),
                "action": "reduce_budget",
                "current_cac": stat["cac"],
                "projected_cac": None,
                "potential_monthly_leads": None,
                "priority": "medium",
            })

        # --- No-leads-in-30-days channels ---
        active_ids_in_stats = {s["id"] for s in all_stats}
        for ch in channels_by_id.values():
            if ch.id not in active_ids_in_stats:
                continue
            try:
                recent_leads = (
                    ChannelLeadEntry.query
                    .filter(
                        ChannelLeadEntry.channel_id == ch.id,
                        ChannelLeadEntry.period_year == year,
                        ChannelLeadEntry.period_month == month,
                    )
                    .first()
                )
                recent_lead_count = recent_leads.lead_count if recent_leads else 0
                if recent_lead_count == 0:
                    # Skip channels already flagged above
                    already_flagged = any(
                        r["channel_id"] == ch.id for r in recommendations
                    )
                    if already_flagged:
                        continue
                    recommendations.append({
                        "channel_id": ch.id,
                        "channel_name": ch.name,
                        "channel_type": ch.channel_type,
                        "recommendation": "No leads recorded in last 30 days — review or pause",
                        "action": "review_or_pause",
                        "current_cac": None,
                        "projected_cac": None,
                        "potential_monthly_leads": None,
                        "priority": "low",
                    })
            except Exception:
                log.exception(
                    "get_growth_recommendations: lead check failed for channel %s", ch.id
                )

    except Exception:
        log.exception("get_growth_recommendations: failed for account %s", account_id)

    return recommendations


def compute_attribution(account_id: int, days: int = 90) -> Dict[str, Any]:
    """
    Match leads to jobs to revenue using the LeadAttribution table.

    Also performs a best-effort phone-number match: for each CallEvent with a
    campaign_id, tries to find a ServiceTitanCustomer by phone, then checks
    for a ServiceTitanJob.

    Returns:
        total_leads, total_booked, total_revenue_cents, overall_close_rate,
        overall_cac, by_channel (list)
    """
    from app.models_marketing import LeadAttribution

    empty: Dict[str, Any] = {
        "total_leads": 0,
        "total_booked": 0,
        "total_revenue_cents": 0,
        "overall_close_rate": None,
        "overall_cac": None,
        "by_channel": [],
    }

    try:
        since = datetime.utcnow() - timedelta(days=days)

        rows = (
            LeadAttribution.query
            .filter(
                LeadAttribution.account_id == account_id,
                LeadAttribution.created_at >= since,
            )
            .all()
        )

        total_leads = len(rows)
        total_booked = sum(1 for r in rows if r.job_status in ("Completed", "Scheduled"))
        total_revenue = sum(r.revenue_cents or 0 for r in rows)
        total_cost = sum(r.lead_cost_cents or 0 for r in rows)

        # Aggregate by channel
        by_channel_map: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            key = row.channel_name or "unknown"
            if key not in by_channel_map:
                by_channel_map[key] = {
                    "channel_id": row.channel_id,
                    "channel_name": row.channel_name,
                    "channel_type": row.channel_type,
                    "leads": 0,
                    "booked": 0,
                    "revenue_cents": 0,
                    "cost_cents": 0,
                }
            by_channel_map[key]["leads"] += 1
            if row.job_status in ("Completed", "Scheduled"):
                by_channel_map[key]["booked"] += 1
            by_channel_map[key]["revenue_cents"] += row.revenue_cents or 0
            by_channel_map[key]["cost_cents"] += row.lead_cost_cents or 0

        by_channel = []
        for entry in by_channel_map.values():
            entry["close_rate"] = _safe_div(entry["booked"], entry["leads"])
            entry["cac"] = _safe_div(float(entry["cost_cents"]), entry["booked"])
            by_channel.append(entry)

        by_channel.sort(key=lambda r: (r["leads"] is None, -(r["leads"] or 0)))

        # --- Best-effort phone-number match via CallEvent → ServiceTitanJob ---
        try:
            from app.models_calls import CallEvent
            from app.models import ServiceTitanJob

            call_rows = (
                CallEvent.query
                .filter(
                    CallEvent.account_id == account_id,
                    CallEvent.campaign_id.isnot(None),
                    CallEvent.from_number.isnot(None),
                    CallEvent.created_at >= since,
                )
                .all()
            )
            for call in call_rows:
                phone = call.from_number
                if not phone:
                    continue
                # Normalize phone for matching
                digits = "".join(c for c in phone if c.isdigit())
                # Find matching attribution by phone
                existing = LeadAttribution.query.filter(
                    LeadAttribution.account_id == account_id,
                    LeadAttribution.call_event_id == call.id,
                ).first()
                if existing:
                    continue
                # Try to find a ServiceTitanJob via phone match on customer
                try:
                    job = (
                        db.session.query(ServiceTitanJob)
                        .filter(
                            ServiceTitanJob.account_id == account_id,
                        )
                        .join(
                            text("servicetitan_customers sc ON sc.account_id = servicetitan_jobs.account_id "
                                 "AND sc.st_customer_id = servicetitan_jobs.st_customer_id"),
                        )
                        .filter(text(f"REPLACE(REPLACE(REPLACE(sc.phone, '-', ''), ' ', ''), '+', '') LIKE '%{digits[-10:]}%'"))
                        .first()
                    )
                    if job:
                        try:
                            new_attr = LeadAttribution(
                                account_id=account_id,
                                call_event_id=call.id,
                                channel_type="call",
                                phone=phone,
                                st_job_id=job.id,
                                job_status=job.job_status,
                                revenue_cents=int(float(job.total_amount or 0) * 100),
                                lead_occurred_at=call.created_at,
                                job_completed_at=job.completed_date,
                            )
                            db.session.add(new_attr)
                            db.session.commit()
                        except Exception:
                            db.session.rollback()
                            log.debug("compute_attribution: failed to persist call→job attribution")
                except Exception:
                    log.debug("compute_attribution: phone→job join failed, skipping")
        except Exception:
            log.debug("compute_attribution: call-event phone match skipped")

        return {
            "total_leads": total_leads,
            "total_booked": total_booked,
            "total_revenue_cents": total_revenue,
            "overall_close_rate": _safe_div(total_booked, total_leads),
            "overall_cac": _safe_div(float(total_cost), total_booked),
            "by_channel": by_channel,
        }

    except Exception:
        log.exception("compute_attribution: failed for account %s", account_id)
        return empty


def get_ltv_by_channel(account_id: int) -> List[Dict[str, Any]]:
    """
    Compute estimated customer LTV per marketing channel using
    ServiceTitanJob data joined via LeadAttribution.

    LTV = avg_jobs_per_customer_lifetime * avg_revenue_per_job_for_channel

    Returns list of dicts per channel with: channel_name, channel_type,
    avg_first_job_revenue, avg_jobs_per_customer, estimated_ltv, sample_size.
    """
    from app.models_marketing import LeadAttribution
    from app.models import ServiceTitanJob

    results: List[Dict[str, Any]] = []

    try:
        # avg jobs per customer across all jobs for this account
        from sqlalchemy import func as sqlfunc

        avg_jobs_per_customer: float = 1.0
        try:
            subq = (
                db.session.query(
                    ServiceTitanJob.st_customer_id,
                    sqlfunc.count(ServiceTitanJob.id).label("job_count"),
                )
                .filter(
                    ServiceTitanJob.account_id == account_id,
                    ServiceTitanJob.st_customer_id.isnot(None),
                )
                .group_by(ServiceTitanJob.st_customer_id)
                .subquery()
            )
            avg_row = (
                db.session.query(sqlfunc.avg(subq.c.job_count)).scalar()
            )
            if avg_row:
                avg_jobs_per_customer = float(avg_row)
        except Exception:
            log.debug("get_ltv_by_channel: avg jobs per customer query failed, using 1.0")

        # Per-channel avg revenue using LeadAttribution → ServiceTitanJob
        channel_map: Dict[str, Dict[str, Any]] = {}

        attr_rows = (
            LeadAttribution.query
            .filter(
                LeadAttribution.account_id == account_id,
                LeadAttribution.st_job_id.isnot(None),
                LeadAttribution.revenue_cents.isnot(None),
            )
            .all()
        )

        for row in attr_rows:
            key = row.channel_name or "unknown"
            if key not in channel_map:
                channel_map[key] = {
                    "channel_name": row.channel_name or "unknown",
                    "channel_type": row.channel_type,
                    "revenue_sum": 0,
                    "count": 0,
                }
            channel_map[key]["revenue_sum"] += row.revenue_cents or 0
            channel_map[key]["count"] += 1

        for key, entry in channel_map.items():
            sample = entry["count"]
            if sample == 0:
                continue
            avg_first_job_revenue = entry["revenue_sum"] / sample
            estimated_ltv = avg_first_job_revenue * avg_jobs_per_customer
            results.append({
                "channel_name": entry["channel_name"],
                "channel_type": entry["channel_type"],
                "avg_first_job_revenue": round(avg_first_job_revenue, 2),
                "avg_jobs_per_customer": round(avg_jobs_per_customer, 2),
                "estimated_ltv": round(estimated_ltv, 2),
                "sample_size": sample,
            })

        results.sort(key=lambda r: r["estimated_ltv"], reverse=True)

    except Exception:
        log.exception("get_ltv_by_channel: failed for account %s", account_id)

    return results


def record_offline_spend(
    account_id: int,
    channel_id: int,
    year: int,
    month: int,
    amount_dollars: float,
    notes: Optional[str] = None,
) -> Optional[Any]:
    """
    Upsert a ChannelSpendEntry (amount in dollars, stored as cents).
    Returns the upserted ChannelSpendEntry or None on failure.
    """
    from app.models_marketing import ChannelSpendEntry

    amount_cents = int(round(amount_dollars * 100))
    try:
        row = (
            ChannelSpendEntry.query
            .filter_by(channel_id=channel_id, period_year=year, period_month=month)
            .first()
        )
        if row:
            row.amount_cents = amount_cents
            if notes is not None:
                row.notes = notes
        else:
            row = ChannelSpendEntry(
                account_id=account_id,
                channel_id=channel_id,
                period_year=year,
                period_month=month,
                amount_cents=amount_cents,
                notes=notes,
            )
            db.session.add(row)
        db.session.commit()
        return row
    except Exception:
        db.session.rollback()
        log.exception(
            "record_offline_spend: failed for channel %s %s-%s", channel_id, year, month
        )
        return None


def record_offline_leads(
    account_id: int,
    channel_id: int,
    year: int,
    month: int,
    lead_count: int,
    booked_count: int = 0,
    revenue_dollars: float = 0,
    notes: Optional[str] = None,
) -> Optional[Any]:
    """
    Upsert a ChannelLeadEntry (revenue in dollars, stored as cents).
    Returns the upserted ChannelLeadEntry or None on failure.
    """
    from app.models_marketing import ChannelLeadEntry

    revenue_cents = int(round(revenue_dollars * 100))
    try:
        row = (
            ChannelLeadEntry.query
            .filter_by(channel_id=channel_id, period_year=year, period_month=month)
            .first()
        )
        if row:
            row.lead_count = lead_count
            row.booked_count = booked_count
            row.revenue_cents = revenue_cents
            if notes is not None:
                row.notes = notes
        else:
            row = ChannelLeadEntry(
                account_id=account_id,
                channel_id=channel_id,
                period_year=year,
                period_month=month,
                lead_count=lead_count,
                booked_count=booked_count,
                revenue_cents=revenue_cents,
                notes=notes,
            )
            db.session.add(row)
        db.session.commit()
        return row
    except Exception:
        db.session.rollback()
        log.exception(
            "record_offline_leads: failed for channel %s %s-%s", channel_id, year, month
        )
        return None


def ingest_aggregator_lead(
    account_id: int,
    platform: str,
    external_id: str,
    name: Optional[str],
    phone: Optional[str],
    email: Optional[str],
    service: Optional[str],
    city: Optional[str],
    zip_code: Optional[str],
    lead_cost_cents: Optional[int],
    raw_data: Optional[Dict[str, Any]] = None,
) -> Optional[Any]:
    """
    Create an AggregatorLead record and a corresponding LeadAttribution entry.

    Looks up the AggregatorAccount by (account_id, platform). If none exists,
    the AggregatorLead is still created but with a null aggregator_account_id
    (guarded by try/except). Idempotent on (account_id, platform, external_id).

    Returns the AggregatorLead instance or None on failure.
    """
    from app.models_marketing import AggregatorAccount, AggregatorLead, LeadAttribution

    try:
        # Resolve aggregator account
        agg_account = (
            AggregatorAccount.query
            .filter_by(account_id=account_id, platform=platform, is_active=True)
            .first()
        )
        agg_account_id = agg_account.id if agg_account else None

        # Idempotency check
        existing = (
            AggregatorLead.query
            .filter_by(
                account_id=account_id,
                platform=platform,
                external_lead_id=external_id,
            )
            .first()
        )
        if existing:
            log.debug(
                "ingest_aggregator_lead: duplicate external_id=%s platform=%s",
                external_id, platform,
            )
            return existing

        # Determine CPL
        cost = lead_cost_cents
        if cost is None and agg_account and agg_account.cost_per_lead_cents:
            cost = agg_account.cost_per_lead_cents

        lead = AggregatorLead(
            account_id=account_id,
            aggregator_account_id=agg_account_id,
            platform=platform,
            external_lead_id=external_id,
            name=name,
            phone=phone,
            email=email,
            service_requested=service,
            city=city,
            zip_code=zip_code,
            lead_cost_cents=cost,
            status="new",
            raw_data=raw_data,
            occurred_at=datetime.utcnow(),
        )
        db.session.add(lead)
        db.session.flush()  # get lead.id before committing

        # Find the matching MarketingChannel by platform/channel_type for attribution
        from app.models_marketing import MarketingChannel

        channel = (
            MarketingChannel.query
            .filter_by(account_id=account_id, channel_type=platform, is_active=True)
            .first()
        )

        attribution = LeadAttribution(
            account_id=account_id,
            channel_id=channel.id if channel else None,
            channel_type=channel.channel_type if channel else platform,
            channel_name=channel.name if channel else platform,
            aggregator_lead_id=lead.id,
            phone=phone,
            email=email,
            lead_cost_cents=cost,
            lead_occurred_at=lead.occurred_at,
        )
        db.session.add(attribution)
        db.session.commit()
        return lead

    except Exception:
        db.session.rollback()
        log.exception(
            "ingest_aggregator_lead: failed for account=%s platform=%s external_id=%s",
            account_id, platform, external_id,
        )
        return None
