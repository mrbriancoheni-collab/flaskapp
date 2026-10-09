"""
Campaign health triage — daily per-campaign action classification.

Distinct from google_ads_health_score.py (account-level grade) and
google_ads_digest.py (weekly narrative). This surfaces the 2-4 specific
campaigns that need a human decision TODAY, with the action to take.

Status values and what they mean:
  ON_TRACK           — spending normally, CPL stable, no action needed
  DELIVERY_PROBLEM   — budget utilization <50%, campaign is underdelivering
  TEST_LOWER_BID     — budget fully consumed, CPL stable/improving → try reducing bid
  EFFICIENCY_DEGRADING — CPL rose >20% week-over-week, needs investigation
  LP_MISMATCH        — CTR ≥5% but conversion rate <1.5% → landing page issue
  PAUSED             — campaign is paused or removed
  NO_DATA            — enabled but no spend in last 7 days
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

log = logging.getLogger(__name__)

# ── Thresholds ────────────────────────────────────────────────────────────────
DELIVERY_LOW_THRESHOLD   = 50.0   # % budget utilization — below this = underdelivering
DELIVERY_FULL_THRESHOLD  = 92.0   # % — above this = fully delivering
CPL_DEGRADING_THRESHOLD  = 20.0   # % CPL increase week-over-week = degrading
CTR_HIGH_THRESHOLD       = 5.0    # % CTR — high CTR
CONV_RATE_LOW_THRESHOLD  = 1.5    # % conv rate — if CTR is high but CVR is low = LP issue

# Display priority (lower = shown first on dashboard)
STATUS_PRIORITY = {
    "EFFICIENCY_DEGRADING": 1,
    "DELIVERY_PROBLEM":     2,
    "LP_MISMATCH":          3,
    "TEST_LOWER_BID":       4,
    "ON_TRACK":             5,
    "NO_DATA":              6,
    "PAUSED":               7,
}

STATUS_META = {
    "ON_TRACK": {
        "emoji": "🟢",
        "label": "On Track",
        "color": "green",
        "action": "No action needed.",
    },
    "DELIVERY_PROBLEM": {
        "emoji": "🔴",
        "label": "Delivery Problem",
        "color": "red",
        "action": "Campaign is spending <50% of daily budget. Check bids, Quality Score, ad schedule, and keyword match types.",
    },
    "TEST_LOWER_BID": {
        "emoji": "🟡",
        "label": "Test Lower Bid",
        "color": "yellow",
        "action": "Hitting budget cap with stable CPL. Test a 10–15% bid reduction — you may get the same leads at lower cost.",
    },
    "EFFICIENCY_DEGRADING": {
        "emoji": "⚠️",
        "label": "Efficiency Degrading",
        "color": "orange",
        "action": "CPL increased >20% vs last week. Check for new competitors, Quality Score drops, and add fresh negative keywords.",
    },
    "LP_MISMATCH": {
        "emoji": "🚀",
        "label": "Landing Page Mismatch",
        "color": "blue",
        "action": "High CTR but low conversion rate — your ads attract clicks but the landing page isn't converting. Review page relevance and CTA.",
    },
    "PAUSED": {
        "emoji": "⏸",
        "label": "Paused",
        "color": "gray",
        "action": "Campaign is paused or removed.",
    },
    "NO_DATA": {
        "emoji": "💤",
        "label": "No Recent Data",
        "color": "gray",
        "action": "Campaign is enabled but recorded no spend in the last 7 days. Check campaign status in Google Ads.",
    },
}


def _pct(num: float | None, denom: float | None) -> float | None:
    if num is None or denom is None or denom == 0:
        return None
    return round(num / denom * 100, 2)


def _pct_change(current: float | None, prior: float | None) -> float | None:
    if current is None or prior is None or prior <= 0:
        return None
    return round((current - prior) / prior * 100, 1)


def _classify(
    status: str,
    budget_util_pct: float | None,
    cpl_trend_pct: float | None,
    avg_ctr_pct: float | None,
    conv_rate_pct: float | None,
    has_spend: bool,
) -> str:
    if status in ("paused", "removed"):
        return "PAUSED"
    if not has_spend:
        return "NO_DATA"

    # Efficiency degrading takes priority over delivery issues
    if cpl_trend_pct is not None and cpl_trend_pct >= CPL_DEGRADING_THRESHOLD:
        return "EFFICIENCY_DEGRADING"

    if budget_util_pct is not None and budget_util_pct < DELIVERY_LOW_THRESHOLD:
        return "DELIVERY_PROBLEM"

    # LP mismatch: great CTR but poor conversion
    if (avg_ctr_pct is not None and avg_ctr_pct >= CTR_HIGH_THRESHOLD
            and conv_rate_pct is not None and conv_rate_pct < CONV_RATE_LOW_THRESHOLD):
        return "LP_MISMATCH"

    # Full delivery with stable CPL → room to test lower bids
    if (budget_util_pct is not None and budget_util_pct >= DELIVERY_FULL_THRESHOLD
            and (cpl_trend_pct is None or cpl_trend_pct < 10)):
        return "TEST_LOWER_BID"

    return "ON_TRACK"


def run_triage(account_id: int, days: int = 7) -> dict[str, Any]:
    """
    Classify every active campaign for an account.

    Returns:
        {
            "account_id": int,
            "period_days": int,
            "campaigns": [ {...campaign triage dict...}, ... ],
            "summary": {
                "total": int,
                "needs_action": int,
                "by_status": {status: count},
            },
            "actions_needed": [ {...campaigns that aren't ON_TRACK or PAUSED...} ],
        }
    """
    from app import db
    from sqlalchemy import text

    today = date.today()
    this_start  = today - timedelta(days=days)
    prior_start = today - timedelta(days=days * 2)
    prior_end   = this_start

    # ── Fetch all campaigns for this account ──────────────────────────────────
    campaigns = db.session.execute(text("""
        SELECT id, name, status, daily_budget_cents, bid_strategy, target_cpa_micros
        FROM ads_campaigns
        WHERE account_id = :aid
          AND status NOT IN ('removed')
        ORDER BY name
    """), {"aid": account_id}).mappings().all()

    if not campaigns:
        return {
            "account_id": account_id,
            "period_days": days,
            "campaigns": [],
            "summary": {"total": 0, "needs_action": 0, "by_status": {}},
            "actions_needed": [],
        }

    campaign_ids = [c["id"] for c in campaigns]

    # ── Fetch stats for this period ───────────────────────────────────────────
    def _fetch_stats(start: date, end: date) -> dict[int, dict]:
        rows = db.session.execute(text("""
            SELECT entity_id,
                   SUM(cost_micros)/1000000.0  AS spend,
                   SUM(clicks)                 AS clicks,
                   SUM(impressions)            AS impressions,
                   SUM(conversions)            AS conversions,
                   AVG(NULLIF(quality_score,0)) AS avg_qs
            FROM gads_stats_daily
            WHERE entity_type = 'campaign'
              AND entity_id IN :ids
              AND date >= :start AND date < :end
            GROUP BY entity_id
        """), {"ids": tuple(campaign_ids) if len(campaign_ids) > 1 else (campaign_ids[0], campaign_ids[0]),
               "start": start, "end": end}).mappings().all()
        return {r["entity_id"]: dict(r) for r in rows}

    this_stats  = _fetch_stats(this_start, today)
    prior_stats = _fetch_stats(prior_start, prior_end)

    # ── Classify each campaign ────────────────────────────────────────────────
    results = []
    for c in campaigns:
        cid = c["id"]
        this  = this_stats.get(cid, {})
        prior = prior_stats.get(cid, {})

        spend_this   = float(this.get("spend")       or 0)
        clicks_this  = int(this.get("clicks")        or 0)
        impr_this    = int(this.get("impressions")   or 0)
        conv_this    = float(this.get("conversions") or 0)
        avg_qs       = float(this.get("avg_qs")      or 0) or None

        spend_prior  = float(prior.get("spend")       or 0)
        conv_prior   = float(prior.get("conversions") or 0)

        has_spend = spend_this > 0.01

        # Budget utilization: average daily spend vs daily budget
        daily_budget = (c["daily_budget_cents"] or 0) / 100.0
        if daily_budget > 0 and has_spend:
            avg_daily_spend = spend_this / days
            budget_util_pct = round(avg_daily_spend / daily_budget * 100, 1)
        else:
            budget_util_pct = None

        cpl_this   = round(spend_this / conv_this, 2) if conv_this > 0 else None
        cpl_prior  = round(spend_prior / conv_prior, 2) if conv_prior > 0 else None
        cpl_trend  = _pct_change(cpl_this, cpl_prior)

        avg_ctr_pct  = _pct(clicks_this, impr_this)
        conv_rate_pct = _pct(conv_this, clicks_this)

        status_key = _classify(
            c["status"],
            budget_util_pct,
            cpl_trend,
            avg_ctr_pct,
            conv_rate_pct,
            has_spend,
        )
        meta = STATUS_META[status_key]

        result = {
            "campaign_id":      cid,
            "name":             c["name"],
            "status":           c["status"],
            "bid_strategy":     c["bid_strategy"],
            "daily_budget":     daily_budget,
            # This period metrics
            "spend":            round(spend_this, 2),
            "clicks":           clicks_this,
            "impressions":      impr_this,
            "conversions":      round(conv_this, 1),
            "cpl":              cpl_this,
            "cpl_prior":        cpl_prior,
            "cpl_trend_pct":    cpl_trend,
            "avg_ctr_pct":      avg_ctr_pct,
            "conv_rate_pct":    conv_rate_pct,
            "avg_qs":           round(avg_qs, 1) if avg_qs else None,
            "budget_util_pct":  budget_util_pct,
            # Classification
            "triage_status":    status_key,
            "priority":         STATUS_PRIORITY[status_key],
            "emoji":            meta["emoji"],
            "status_label":     meta["label"],
            "status_color":     meta["color"],
            "recommended_action": meta["action"],
        }
        results.append(result)

    results.sort(key=lambda r: (r["priority"], r["name"]))

    by_status: dict[str, int] = {}
    for r in results:
        by_status[r["triage_status"]] = by_status.get(r["triage_status"], 0) + 1

    no_action = {"ON_TRACK", "PAUSED", "NO_DATA"}
    actions_needed = [r for r in results if r["triage_status"] not in no_action]

    return {
        "account_id":   account_id,
        "period_days":  days,
        "as_of":        today.isoformat(),
        "campaigns":    results,
        "summary": {
            "total":        len(results),
            "needs_action": len(actions_needed),
            "by_status":    by_status,
        },
        "actions_needed": actions_needed,
    }


def triage_summary_text(triage: dict[str, Any]) -> str:
    """One-paragraph plain-English summary for the daily digest."""
    actions = triage["actions_needed"]
    total   = triage["summary"]["total"]

    if not actions:
        return f"All {total} campaigns are on track. No action needed today."

    lines = [f"{len(actions)} of {total} campaigns need attention:\n"]
    for c in actions[:5]:  # cap at 5 in the digest
        trend = ""
        if c["cpl_trend_pct"] is not None:
            direction = "up" if c["cpl_trend_pct"] > 0 else "down"
            trend = f" (CPL {direction} {abs(c['cpl_trend_pct']):.0f}%)"
        cpl_str = f"${c['cpl']:.0f}/lead" if c["cpl"] else "no conversions"
        lines.append(
            f"  {c['emoji']} {c['name']}: {c['status_label']}{trend}. "
            f"{cpl_str}. → {c['recommended_action']}"
        )
    if len(actions) > 5:
        lines.append(f"  … and {len(actions) - 5} more.")
    return "\n".join(lines)
