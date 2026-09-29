# app/services/google_ads_auction_insights.py
"""
Auction Insights Sync + Competitive Intelligence Service.

Pulls auction insight data from the Google Ads API, stores it in the
AuctionInsight table, and provides aggregated competitor summaries and
automated competitive-response recommendations.

Public API:
  sync_auction_insights(account_id)         -> {"synced": N, "errors": []}
  get_competitor_summary(account_id)        -> {your_avg_impression_share, competitors, ...}
  auto_respond_to_impression_loss(account_id) -> {"triggered": bool, ...}
"""
from __future__ import annotations

import datetime as dt
import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return default


def _resolve_ads_context(account_id: int) -> Optional[Dict[str, Any]]:
    try:
        from app.google.utils_ads import resolve_ads_context
        return resolve_ads_context(account_id) or {}
    except Exception as exc:
        logger.debug("resolve_ads_context unavailable: %s", exc)
        return None


def _ads_search(
    account_id: int,
    customer_id: str,
    query: str,
    login_customer_id: Optional[str] = None,
) -> List[dict]:
    try:
        from app.google.utils_ads import google_ads_search
        from app.google.token_utils import ensure_access_token
        access_token, _ = ensure_access_token(account_id, ("ads", "lsa"))
        return google_ads_search(
            access_token=access_token,
            customer_id=customer_id,
            query=query,
            login_customer_id=login_customer_id,
            stream=True,
        ) or []
    except Exception as exc:
        logger.warning("google_ads_search failed: %s", exc)
        return []


# ---------------------------------------------------------------------------
# A. sync_auction_insights
# ---------------------------------------------------------------------------

_AUCTION_INSIGHT_GAQL = """
SELECT
  campaign.id,
  campaign.name,
  segments.date,
  auction_insight.domain,
  metrics.auction_insight_search_impression_share,
  metrics.auction_insight_search_overlap_rate,
  metrics.auction_insight_search_position_above_rate,
  metrics.auction_insight_search_top_impression_percentage,
  metrics.auction_insight_search_absolute_top_impression_percentage,
  metrics.auction_insight_search_outranking_share
FROM auction_insight_performance_view
WHERE segments.date DURING LAST_30_DAYS
ORDER BY metrics.auction_insight_search_impression_share DESC
"""


def sync_auction_insights(account_id: int) -> Dict[str, Any]:
    """
    Pull auction insight data from the Google Ads API and upsert into the
    AuctionInsight table (unique on account_id + campaign_id + date + domain).

    Returns {"synced": N, "errors": []}.
    """
    from app import db
    from app.models_ads import AuctionInsight, AdsCampaign

    result: Dict[str, Any] = {"synced": 0, "errors": []}

    ctx = _resolve_ads_context(account_id)
    if not ctx:
        result["errors"].append("Could not resolve Google Ads credentials.")
        return result

    customer_id = ctx.get("customer_id")
    login_customer_id = ctx.get("login_customer_id")
    if not customer_id:
        result["errors"].append("No Google Ads customer_id configured for this account.")
        return result

    rows = _ads_search(account_id, customer_id, _AUCTION_INSIGHT_GAQL, login_customer_id)

    if not rows:
        result["errors"].append(
            "No auction insight rows returned. "
            "Campaigns may not have enough data yet, or your account has no competitors."
        )
        return result

    # Build a google_campaign_id -> local_campaign_id lookup (avoid N+1 queries)
    campaign_cache: Dict[str, Optional[int]] = {}

    def _local_campaign_id(google_cid: str) -> Optional[int]:
        if google_cid not in campaign_cache:
            camp = AdsCampaign.query.filter_by(
                account_id=account_id,
                google_campaign_id=google_cid,
            ).first()
            campaign_cache[google_cid] = camp.id if camp else None
        return campaign_cache[google_cid]

    synced = 0
    for row in rows:
        try:
            camp_data = row.get("campaign", {})
            metrics = row.get("metrics", {})
            seg = row.get("segments", {})
            # Field key varies by SDK version (camelCase vs snake_case)
            ai_data = row.get("auctionInsight", {}) or row.get("auction_insight", {})

            google_cid = str(camp_data.get("id", ""))
            date_str = seg.get("date")
            domain = ai_data.get("domain") or row.get("domain", "")

            if not google_cid or not date_str or not domain:
                continue

            date_obj = dt.date.fromisoformat(date_str)
            local_cid = _local_campaign_id(google_cid)

            impression_share = _float(
                metrics.get("auctionInsightSearchImpressionShare")
                or metrics.get("auction_insight_search_impression_share")
            )
            overlap_rate = _float(
                metrics.get("auctionInsightSearchOverlapRate")
                or metrics.get("auction_insight_search_overlap_rate")
            )
            position_above_rate = _float(
                metrics.get("auctionInsightSearchPositionAboveRate")
                or metrics.get("auction_insight_search_position_above_rate")
            )
            top_of_page_rate = _float(
                metrics.get("auctionInsightSearchTopImpressionPercentage")
                or metrics.get("auction_insight_search_top_impression_percentage")
            )
            abs_top_of_page_rate = _float(
                metrics.get("auctionInsightSearchAbsoluteTopImpressionPercentage")
                or metrics.get("auction_insight_search_absolute_top_impression_percentage")
            )
            outranking_share = _float(
                metrics.get("auctionInsightSearchOutrankingShare")
                or metrics.get("auction_insight_search_outranking_share")
            )

            # Upsert
            ai_row = AuctionInsight.query.filter_by(
                account_id=account_id,
                campaign_id=local_cid,
                date=date_obj,
                domain=domain,
            ).first()

            if ai_row is None:
                ai_row = AuctionInsight(
                    account_id=account_id,
                    campaign_id=local_cid,
                    date=date_obj,
                    domain=domain,
                )
                db.session.add(ai_row)

            ai_row.impression_share = impression_share
            ai_row.overlap_rate = overlap_rate
            ai_row.position_above_rate = position_above_rate
            ai_row.top_of_page_rate = top_of_page_rate
            ai_row.abs_top_of_page_rate = abs_top_of_page_rate
            ai_row.outranking_share = outranking_share

            synced += 1

        except Exception as exc:
            logger.warning("Error processing auction insight row: %s", exc)
            result["errors"].append(str(exc))

    try:
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        logger.error("DB commit failed during auction insight sync: %s", exc)
        result["errors"].append(f"DB commit error: {exc}")
        synced = 0

    result["synced"] = synced
    return result


# ---------------------------------------------------------------------------
# B. get_competitor_summary
# ---------------------------------------------------------------------------

def _plain_english_insight(
    domain: str,
    their_is: float,
    your_is: float,
    overlap_rate: float,
    position_above_rate: float,
    outranking_share: float,
) -> str:
    """Return a single plain-English sentence describing the competitive situation."""
    gap = their_is - your_is

    if gap >= 0.20:
        above_pct = int(round(position_above_rate * 100))
        return (
            f"You're being outbid by {domain} on roughly 1 in 3 searches — "
            f"they appear above you {above_pct}% of the time."
        )
    if overlap_rate >= 0.70:
        return (
            f"{domain} is competing directly with you on most of your keywords. "
            "They show up alongside your ads very frequently."
        )
    if outranking_share >= 0.50:
        outrank_pct = int(round(outranking_share * 100))
        return (
            f"You're beating {domain} more than half the time — "
            f"you outrank them on {outrank_pct}% of shared searches. Keep it up."
        )
    if gap > 0.05:
        gap_pct = int(round(gap * 100))
        return (
            f"{domain} has a {gap_pct}% higher impression share than you right now. "
            "Consider reviewing your bids or budget to close the gap."
        )
    return (
        f"You and {domain} are fairly evenly matched. "
        "Monitor their impression share for changes week over week."
    )


def _build_top_opportunity(competitors: List[dict], your_is: float) -> str:
    if not competitors:
        return "Sync the latest auction data to see where you have room to grow."

    top = competitors[0]
    their_is = top["their_impression_share"]
    domain = top["domain"]
    gap = their_is - your_is

    if gap >= 0.15:
        gap_pct = int(round(gap * 100))
        daily_estimate = max(10, int(gap_pct * 1.2))
        return (
            f"Increase your daily budget by ~${daily_estimate}/day to close "
            f"the impression share gap with {domain} ({gap_pct}% behind them right now)."
        )
    if gap >= 0.05:
        gap_pct = int(round(gap * 100))
        return (
            f"You're {gap_pct}% behind {domain} in impression share. "
            "Raising your target CPA or tightening keyword match types could help."
        )
    if your_is >= 0.60:
        return (
            "Your impression share is strong. Focus on improving ad quality "
            "and landing page experience to convert more of those impressions."
        )
    return (
        "Review your keyword bids and daily budget to capture more of the "
        "available search traffic in your market."
    )


def get_competitor_summary(account_id: int) -> Dict[str, Any]:
    """
    Aggregate AuctionInsight rows for the last 30 days and return a structured
    competitor summary with plain-English insights.

    Returns:
        {
          "your_avg_impression_share": float,   # e.g. 0.42
          "competitors": [
            {
              "domain": str,
              "their_impression_share": float,
              "your_impression_share": float,
              "overlap_rate": float,
              "position_above_rate": float,
              "outranking_share": float,
              "insight": str,
            },
            ...
          ],
          "top_opportunity": str,
          "last_synced": datetime | None,
        }
    """
    from app.models_ads import AuctionInsight
    from sqlalchemy import func

    cutoff = dt.date.today() - dt.timedelta(days=30)

    # Your average impression share from campaign stats (more reliable than auction rows)
    try:
        from app.models_ads import GadsStatsDaily
        val = (
            GadsStatsDaily.query
            .with_entities(func.avg(GadsStatsDaily.search_impr_share))
            .filter(
                GadsStatsDaily.account_id == account_id,
                GadsStatsDaily.entity_type == "campaign",
                GadsStatsDaily.date >= cutoff,
                GadsStatsDaily.search_impr_share.isnot(None),
            )
            .scalar()
        )
        your_avg_is = float(val or 0.0)
    except Exception:
        your_avg_is = 0.0

    # Top 5 competitors by average impression share over last 30 days
    rows = (
        AuctionInsight.query
        .with_entities(
            AuctionInsight.domain,
            func.avg(AuctionInsight.impression_share).label("avg_is"),
            func.avg(AuctionInsight.overlap_rate).label("avg_overlap"),
            func.avg(AuctionInsight.position_above_rate).label("avg_par"),
            func.avg(AuctionInsight.outranking_share).label("avg_outranking"),
        )
        .filter(
            AuctionInsight.account_id == account_id,
            AuctionInsight.date >= cutoff,
        )
        .group_by(AuctionInsight.domain)
        .order_by(func.avg(AuctionInsight.impression_share).desc())
        .limit(5)
        .all()
    )

    competitors = []
    for r in rows:
        domain = r.domain
        their_is = float(r.avg_is or 0.0)
        overlap = float(r.avg_overlap or 0.0)
        par = float(r.avg_par or 0.0)
        outranking = float(r.avg_outranking or 0.0)

        competitors.append({
            "domain": domain,
            "their_impression_share": round(their_is, 4),
            "your_impression_share": round(your_avg_is, 4),
            "overlap_rate": round(overlap, 4),
            "position_above_rate": round(par, 4),
            "outranking_share": round(outranking, 4),
            "insight": _plain_english_insight(
                domain, their_is, your_avg_is, overlap, par, outranking
            ),
        })

    last_row = (
        AuctionInsight.query
        .filter_by(account_id=account_id)
        .order_by(AuctionInsight.created_at.desc())
        .first()
    )

    return {
        "your_avg_impression_share": round(your_avg_is, 4),
        "competitors": competitors,
        "top_opportunity": _build_top_opportunity(competitors, your_avg_is),
        "last_synced": last_row.created_at if last_row else None,
    }


# ---------------------------------------------------------------------------
# C. auto_respond_to_impression_loss
# ---------------------------------------------------------------------------

def auto_respond_to_impression_loss(account_id: int) -> Dict[str, Any]:
    """
    Check whether a top competitor gained >10% impression share in the last
    7 days vs the previous 7 days, while our own IS dropped >5%.

    If triggered, creates an OptimizerRecommendation (category="competitive_response",
    severity=2).

    Returns {"triggered": bool, "recommendation_id": int|None, "details": str}.
    """
    from app import db
    from app.models_ads import AuctionInsight, OptimizerRecommendation
    from sqlalchemy import func

    today = dt.date.today()
    week_end = today - dt.timedelta(days=1)
    week_start = week_end - dt.timedelta(days=6)
    prev_end = week_start - dt.timedelta(days=1)
    prev_start = prev_end - dt.timedelta(days=6)

    result: Dict[str, Any] = {
        "triggered": False,
        "recommendation_id": None,
        "details": "",
    }

    # --- Fetch our IS for both windows ---
    def _your_avg_is(date_from: dt.date, date_to: dt.date) -> float:
        try:
            from app.models_ads import GadsStatsDaily
            val = (
                GadsStatsDaily.query
                .with_entities(func.avg(GadsStatsDaily.search_impr_share))
                .filter(
                    GadsStatsDaily.account_id == account_id,
                    GadsStatsDaily.entity_type == "campaign",
                    GadsStatsDaily.date.between(date_from, date_to),
                    GadsStatsDaily.search_impr_share.isnot(None),
                )
                .scalar()
            )
            return float(val or 0.0)
        except Exception:
            return 0.0

    your_current = _your_avg_is(week_start, week_end)
    your_previous = _your_avg_is(prev_start, prev_end)
    your_drop = your_previous - your_current  # positive means we dropped

    # --- Fetch competitor IS for both windows ---
    def _comp_is_map(date_from: dt.date, date_to: dt.date) -> Dict[str, float]:
        rows = (
            AuctionInsight.query
            .with_entities(
                AuctionInsight.domain,
                func.avg(AuctionInsight.impression_share).label("avg_is"),
            )
            .filter(
                AuctionInsight.account_id == account_id,
                AuctionInsight.date.between(date_from, date_to),
            )
            .group_by(AuctionInsight.domain)
            .all()
        )
        return {r.domain: float(r.avg_is or 0.0) for r in rows}

    current_comp = _comp_is_map(week_start, week_end)
    previous_comp = _comp_is_map(prev_start, prev_end)

    # Find competitor with the largest IS gain this week
    best_domain: Optional[str] = None
    best_gain: float = 0.0
    best_current_is: float = 0.0
    best_previous_is: float = 0.0

    for domain, current_is in current_comp.items():
        prev_is = previous_comp.get(domain, current_is)
        gain = current_is - prev_is
        if gain > best_gain:
            best_gain = gain
            best_domain = domain
            best_current_is = current_is
            best_previous_is = prev_is

    # Only trigger when: competitor gained >10% AND our IS dropped >5%
    if not best_domain or best_gain < 0.10 or your_drop < 0.05:
        result["details"] = (
            f"No significant competitive threat detected this week. "
            f"Your IS change: {your_drop:+.1%}. "
            f"Top competitor IS gain: {best_gain:.1%}."
        )
        return result

    # --- Build recommendation ---
    your_drop_pct = int(round(your_drop * 100))
    their_gain_pct = int(round(best_gain * 100))
    gap = best_current_is - your_current
    # Rough heuristic: ~$12/day per 10% IS gap
    daily_cents = max(1000, int(gap * 120 * 100))

    title = (
        f"Competitor {best_domain} is gaining ground — "
        f"your impression share dropped {your_drop_pct}% this week"
    )

    details = (
        f"{best_domain} grew their search impression share by {their_gain_pct}% "
        f"this week (from {best_previous_is:.0%} to {best_current_is:.0%}), "
        f"while your impression share fell {your_drop_pct}% "
        f"(from {your_previous:.0%} to {your_current:.0%}). "
        f"Adding approximately ${daily_cents / 100:.0f}/day to your daily budget "
        f"should help you recover the {gap:.0%} impression share gap."
    )

    suggested_action = {
        "action": "increase_budget",
        "amount_cents": daily_cents,
        "reasoning": (
            f"{best_domain} gained {their_gain_pct}% impression share this week. "
            f"Adding ${daily_cents / 100:.0f}/day to your campaigns should close "
            f"the {gap:.0%} impression share gap."
        ),
    }

    try:
        rec = OptimizerRecommendation(
            account_id=account_id,
            scope_type="account",
            scope_id=account_id,
            category="competitive_response",
            title=title,
            details=details,
            severity=2,
            suggested_action_json=json.dumps(suggested_action),
            status="open",
        )
        db.session.add(rec)
        db.session.commit()
        result["triggered"] = True
        result["recommendation_id"] = rec.id
        result["details"] = details
    except Exception as exc:
        db.session.rollback()
        logger.error("Failed to save competitive_response recommendation: %s", exc)
        result["details"] = f"DB error while saving recommendation: {exc}"

    return result
