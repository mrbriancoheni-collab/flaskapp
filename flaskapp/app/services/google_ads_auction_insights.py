# app/services/google_ads_auction_insights.py
"""
Google Ads Auction Insights Sync & Analysis Service.

Three public entry points:
  sync_auction_insights(account_id)         – pull from API, upsert DB
  get_competitor_summary(account_id)        – aggregate + plain-English insights
  auto_respond_to_impression_loss(account_id) – generate OptimizerRecommendation
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


def _gaql_search(account_id: int, query: str) -> List[dict]:
    """Run a GAQL query and return rows as plain dicts."""
    ctx = _resolve_ads_context(account_id)
    if not ctx:
        return []

    customer_id = ctx.get("customer_id")
    login_customer_id = ctx.get("login_customer_id")
    if not customer_id:
        return []

    try:
        from app.google.utils_ads import google_ads_search
        from app.google.token_utils import ensure_access_token
        access_token, _ = ensure_access_token(account_id, ("ads", "lsa"))
        rows = google_ads_search(
            access_token=access_token,
            customer_id=customer_id,
            query=query,
            login_customer_id=login_customer_id,
            stream=True,
        )
        return rows or []
    except Exception as exc:
        logger.info("Auction insights GAQL failed: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Task A – sync_auction_insights
# ---------------------------------------------------------------------------

_AUCTION_GAQL = """
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
    Pull auction insights from Google Ads and upsert into AuctionInsight table.

    Uniqueness key: (account_id, campaign_id, date, domain).
    Returns {"synced": N, "errors": []}.
    """
    from app import db
    from app.models_ads import AuctionInsight, AdsCampaign

    result: Dict[str, Any] = {"synced": 0, "errors": []}

    try:
        AuctionInsight.ensure_columns()
    except Exception:
        pass

    rows = _gaql_search(account_id, _AUCTION_GAQL)
    if not rows:
        result["errors"].append(
            "No auction insight rows returned — Google Ads may not be connected "
            "or campaigns haven't run long enough to generate auction data."
        )
        return result

    # Build a map of google_campaign_id → local AdsCampaign.id
    campaign_id_map: Dict[int, Optional[int]] = {}

    for row in rows:
        try:
            camp = row.get("campaign", {})
            seg = row.get("segments", {})
            ai = row.get("auction_insight", {})
            metrics = row.get("metrics", {})

            google_cid = int(camp.get("id") or 0)
            date_str = seg.get("date", "")
            domain = ai.get("domain") or row.get("domain", "")

            if not google_cid or not date_str or not domain:
                continue

            try:
                date_obj = dt.date.fromisoformat(date_str)
            except ValueError:
                continue

            # Resolve local campaign id (cached per sync run)
            if google_cid not in campaign_id_map:
                local_camp = AdsCampaign.query.filter_by(
                    account_id=account_id,
                    google_campaign_id=google_cid,
                ).first()
                campaign_id_map[google_cid] = local_camp.id if local_camp else None

            local_camp_id = campaign_id_map[google_cid]

            impression_share = _float(
                metrics.get("auction_insight_search_impression_share")
            )
            overlap_rate = _float(
                metrics.get("auction_insight_search_overlap_rate")
            )
            position_above_rate = _float(
                metrics.get("auction_insight_search_position_above_rate")
            )
            top_of_page_rate = _float(
                metrics.get("auction_insight_search_top_impression_percentage")
            )
            abs_top_of_page_rate = _float(
                metrics.get(
                    "auction_insight_search_absolute_top_impression_percentage"
                )
            )
            outranking_share = _float(
                metrics.get("auction_insight_search_outranking_share")
            )

            existing = AuctionInsight.query.filter_by(
                account_id=account_id,
                campaign_id=local_camp_id,
                date=date_obj,
                domain=domain,
            ).first()

            if existing:
                existing.impression_share = impression_share
                existing.overlap_rate = overlap_rate
                existing.position_above_rate = position_above_rate
                existing.top_of_page_rate = top_of_page_rate
                existing.abs_top_of_page_rate = abs_top_of_page_rate
                existing.outranking_share = outranking_share
            else:
                db.session.add(
                    AuctionInsight(
                        account_id=account_id,
                        campaign_id=local_camp_id,
                        date=date_obj,
                        domain=domain,
                        impression_share=impression_share,
                        overlap_rate=overlap_rate,
                        position_above_rate=position_above_rate,
                        top_of_page_rate=top_of_page_rate,
                        abs_top_of_page_rate=abs_top_of_page_rate,
                        outranking_share=outranking_share,
                    )
                )

            result["synced"] += 1

        except Exception as exc:
            logger.exception("Error processing auction insight row: %s", exc)
            result["errors"].append(str(exc))

    try:
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        logger.error("DB commit failed in sync_auction_insights: %s", exc)
        result["errors"].append(f"DB commit error: {exc}")
        result["synced"] = 0

    return result


# ---------------------------------------------------------------------------
# Task B – get_competitor_summary
# ---------------------------------------------------------------------------

def _plain_english_insight(
    domain: str,
    their_is: float,
    your_is: float,
    overlap_rate: float,
    position_above_rate: float,
    outranking_share: float,
) -> str:
    """Generate a single plain-English sentence about this competitor."""
    gap = their_is - your_is

    if gap >= 0.20:
        approx_fraction = (
            "1 in 3 searches" if gap < 0.35
            else "more than 1 in 2 searches"
        )
        above_pct = round(position_above_rate * 100)
        return (
            f"You're being outbid by {domain} on {approx_fraction} — "
            f"they appear above you about {above_pct}% of the time."
        )

    if overlap_rate >= 0.70:
        return (
            f"{domain} is competing directly with you on most of your keywords — "
            f"your ads appear together {round(overlap_rate * 100)}% of the time."
        )

    if outranking_share >= 0.50:
        return (
            f"You're beating {domain} more than half the time — keep it up."
        )

    if gap <= -0.15:
        return (
            f"You're ahead of {domain} by a healthy margin. "
            f"Focus on maintaining your quality score to stay on top."
        )

    return (
        f"{domain} is a nearby competitor — you both show up for similar searches "
        f"about {round(overlap_rate * 100)}% of the time."
    )


def get_competitor_summary(account_id: int) -> Dict[str, Any]:
    """
    Aggregate AuctionInsight rows for the account and return a structured summary.

    Returns:
      {
        "your_avg_impression_share": float,
        "competitors": [
          {
            "domain": str,
            "their_impression_share": float,
            "your_impression_share": float,
            "overlap_rate": float,
            "position_above_rate": float,
            "outranking_share": float,
            "insight": str,
          }, ...
        ],
        "top_opportunity": str,
        "last_synced": datetime | None,
      }
    """
    from app.models_ads import AuctionInsight
    from sqlalchemy import func

    cutoff = dt.date.today() - dt.timedelta(days=30)

    rows = (
        AuctionInsight.query
        .filter(
            AuctionInsight.account_id == account_id,
            AuctionInsight.date >= cutoff,
        )
        .all()
    )

    if not rows:
        return {
            "your_avg_impression_share": 0.0,
            "competitors": [],
            "top_opportunity": (
                "No auction data yet. Click \"Sync Latest Data\" to pull your "
                "latest auction insights from Google Ads."
            ),
            "last_synced": None,
        }

    # Account-level avg impression share is NOT stored per-competitor row;
    # we approximate it as the average across ALL rows for this account (all domains).
    # In practice the caller should store their own IS separately. For now we use
    # the median of outranking_share as a proxy for "your" position.
    # Better: the impression_share on rows where domain == "you" / own domain.
    # Since Google Ads doesn't include the account's own IS in this table directly,
    # we compute it as (1 - mean competitor IS) as a rough proxy, capped sanely.
    all_competitor_is = [r.impression_share or 0.0 for r in rows]
    mean_competitor_is = sum(all_competitor_is) / len(all_competitor_is) if all_competitor_is else 0.5
    your_avg_is = max(0.05, min(0.95, 1.0 - mean_competitor_is))

    # Aggregate by domain
    domain_data: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        d = r.domain
        if d not in domain_data:
            domain_data[d] = {
                "is_sum": 0.0,
                "overlap_sum": 0.0,
                "above_sum": 0.0,
                "outranking_sum": 0.0,
                "count": 0,
            }
        bucket = domain_data[d]
        bucket["is_sum"] += r.impression_share or 0.0
        bucket["overlap_sum"] += r.overlap_rate or 0.0
        bucket["above_sum"] += r.position_above_rate or 0.0
        bucket["outranking_sum"] += r.outranking_share or 0.0
        bucket["count"] += 1

    # Build sorted competitor list — top 5 by avg IS
    competitors_raw = []
    for domain, data in domain_data.items():
        n = data["count"]
        avg_is = data["is_sum"] / n
        competitors_raw.append(
            {
                "domain": domain,
                "their_impression_share": round(avg_is, 4),
                "your_impression_share": round(your_avg_is, 4),
                "overlap_rate": round(data["overlap_sum"] / n, 4),
                "position_above_rate": round(data["above_sum"] / n, 4),
                "outranking_share": round(data["outranking_sum"] / n, 4),
            }
        )

    competitors_raw.sort(key=lambda x: x["their_impression_share"], reverse=True)
    top5 = competitors_raw[:5]

    # Attach plain-English insight
    competitors = []
    for c in top5:
        insight = _plain_english_insight(
            domain=c["domain"],
            their_is=c["their_impression_share"],
            your_is=your_avg_is,
            overlap_rate=c["overlap_rate"],
            position_above_rate=c["position_above_rate"],
            outranking_share=c["outranking_share"],
        )
        competitors.append({**c, "insight": insight})

    # Top opportunity
    biggest_threat = top5[0] if top5 else None
    if biggest_threat and (biggest_threat["their_impression_share"] - your_avg_is) >= 0.20:
        gap_pct = round((biggest_threat["their_impression_share"] - your_avg_is) * 100)
        # Rough dollar estimate: ~$10/day per 5% IS gap is a common rule of thumb
        budget_bump = round((gap_pct / 5) * 10)
        top_opportunity = (
            f"Increase your daily budget by ~${budget_bump}/day to close the "
            f"{gap_pct}% impression share gap with {biggest_threat['domain']}."
        )
    elif biggest_threat:
        top_opportunity = (
            f"Your impression share is competitive. Focus on ad quality and "
            f"landing page relevance to pull ahead of {biggest_threat['domain']}."
        )
    else:
        top_opportunity = "No significant competitors detected in the last 30 days."

    last_synced = max((r.created_at for r in rows), default=None)

    return {
        "your_avg_impression_share": round(your_avg_is, 4),
        "competitors": competitors,
        "top_opportunity": top_opportunity,
        "last_synced": last_synced.isoformat() if last_synced else None,
    }


# ---------------------------------------------------------------------------
# Task C – auto_respond_to_impression_loss
# ---------------------------------------------------------------------------

def auto_respond_to_impression_loss(account_id: int) -> Dict[str, Any]:
    """
    Detect competitor impression share gains vs our drops and fire an
    OptimizerRecommendation if thresholds are exceeded.

    Compares last-7-days vs previous-7-days for each competitor.
    Threshold: competitor gained >10% IS while our IS dropped >5%.

    Returns {"recommendations_created": N, "details": [...], "errors": []}.
    """
    from app import db
    from app.models_ads import AuctionInsight, OptimizerRecommendation

    result: Dict[str, Any] = {
        "recommendations_created": 0,
        "details": [],
        "errors": [],
    }

    today = dt.date.today()
    recent_start = today - dt.timedelta(days=7)
    prev_start = today - dt.timedelta(days=14)
    prev_end = today - dt.timedelta(days=8)

    def _avg_is(start: dt.date, end: dt.date) -> Dict[str, float]:
        """Return {domain: avg_impression_share} for a date window."""
        rows = (
            AuctionInsight.query
            .filter(
                AuctionInsight.account_id == account_id,
                AuctionInsight.date >= start,
                AuctionInsight.date <= end,
            )
            .all()
        )
        domain_buckets: Dict[str, list] = {}
        for r in rows:
            domain_buckets.setdefault(r.domain, []).append(r.impression_share or 0.0)
        return {
            d: sum(vals) / len(vals)
            for d, vals in domain_buckets.items()
        }

    recent_is = _avg_is(recent_start, today)
    prev_is = _avg_is(prev_start, prev_end)

    if not recent_is:
        result["errors"].append(
            "No auction insight data for the last 7 days. Run a sync first."
        )
        return result

    # Our impression share proxy (same method as get_competitor_summary)
    recent_vals = list(recent_is.values())
    prev_vals = list(prev_is.values())

    our_recent_is = max(0.05, 1.0 - (sum(recent_vals) / len(recent_vals))) if recent_vals else 0.5
    our_prev_is = max(0.05, 1.0 - (sum(prev_vals) / len(prev_vals))) if prev_vals else 0.5

    our_drop = our_prev_is - our_recent_is  # positive means we dropped

    for domain, their_recent in recent_is.items():
        their_prev = prev_is.get(domain, their_recent)
        their_gain = their_recent - their_prev  # positive means they gained

        if their_gain > 0.10 and our_drop > 0.05:
            # Generate a recommendation
            our_drop_pct = round(our_drop * 100, 1)
            their_gain_pct = round(their_gain * 100, 1)

            title = (
                f"Competitor {domain} is gaining ground — "
                f"your impression share dropped {our_drop_pct}% this week"
            )

            # Dollar estimate: ~$10/day per 5% IS gap
            gap_pct = round((their_recent - our_recent_is) * 100)
            budget_cents = max(500, round((gap_pct / 5) * 10 * 100))  # in cents

            details = (
                f"{domain} increased their impression share by {their_gain_pct}% "
                f"over the past week while yours fell {our_drop_pct}%. "
                f"They're now showing up {round(their_recent * 100)}% of the time "
                f"versus your {round(our_recent_is * 100)}%. "
                f"Increasing your daily budget by approximately "
                f"${budget_cents // 100}/day could recover the lost ground."
            )

            suggested_action = {
                "action": "increase_budget",
                "amount_cents": budget_cents,
                "reasoning": (
                    f"{domain} gained {their_gain_pct}% impression share this week. "
                    f"Adding ${budget_cents // 100}/day to your top campaigns should "
                    f"restore competitive parity."
                ),
            }

            rec = OptimizerRecommendation(
                account_id=account_id,
                scope_type="account",
                scope_id=account_id,
                category="competitive_response",
                title=title,
                details=details,
                expected_impact=f"Recover ~{our_drop_pct}% impression share",
                severity=2,
                suggested_action_json=json.dumps(suggested_action),
                status="open",
            )
            db.session.add(rec)

            result["recommendations_created"] += 1
            result["details"].append(
                {
                    "domain": domain,
                    "their_gain_pct": their_gain_pct,
                    "our_drop_pct": our_drop_pct,
                    "budget_increase_usd": budget_cents // 100,
                }
            )

    try:
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        logger.error("DB commit failed in auto_respond_to_impression_loss: %s", exc)
        result["errors"].append(f"DB commit error: {exc}")
        result["recommendations_created"] = 0

    return result
