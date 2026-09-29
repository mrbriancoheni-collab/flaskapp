# app/services/google_ads_dayparting.py
"""
Dayparting Automation Service for Google Ads.

Three main operations:
  A. sync_hourly_stats    – pull GAQL hourly segmented data for last 14 days
  B. compute_daypart_adjustments – analyse CVR by hour-of-week, return proposed modifiers
  C. apply_daypart_adjustments   – push AdSchedule criteria to Google Ads + persist locally
"""
from __future__ import annotations

import datetime as dt
import logging
from collections import defaultdict
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Day-of-week name map: Python weekday() 0=Monday … 6=Sunday
_DOW_NAMES = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"]


def _int(v: Any, default: int = 0) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return default


def _float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return default


def _digits(v: Any) -> Optional[str]:
    if v is None:
        return None
    return "".join(c for c in str(v) if c.isdigit()) or None


# ─────────────────────────────────────────────────────────────────────────────
# A. Sync hourly stats
# ─────────────────────────────────────────────────────────────────────────────

_HOURLY_GAQL = """
SELECT campaign.id, campaign.name, segments.date, segments.hour,
       metrics.impressions, metrics.clicks, metrics.cost_micros, metrics.conversions
FROM campaign
WHERE segments.date DURING LAST_14_DAYS
  AND campaign.status = 'ENABLED'
""".strip()


def sync_hourly_stats(account_id: int) -> Dict[str, Any]:
    """
    Pull hourly segmented campaign stats for the last 14 days from Google Ads
    and upsert into GadsHourlyStats.

    Returns {"synced": N, "errors": []}.
    """
    from app import db
    from app.models_ads import GadsHourlyStats, AdsCampaign
    from app.google.utils_ads import resolve_ads_context, google_ads_search
    from app.google.token_utils import ensure_access_token

    summary: Dict[str, Any] = {"synced": 0, "errors": []}

    # ── resolve credentials ─────────────────────────────────────────────────
    try:
        ctx = resolve_ads_context(account_id)
        customer_id = ctx.get("customer_id")
        login_customer_id = ctx.get("login_customer_id")
        if not customer_id:
            summary["errors"].append("No Google Ads customer_id configured for this account.")
            return summary

        access_token, _ = ensure_access_token(account_id, ("ads", "lsa"))
        if not access_token:
            summary["errors"].append("Could not obtain a valid access token.")
            return summary
    except Exception as exc:
        summary["errors"].append(f"Credential error: {exc}")
        return summary

    # ── run query ───────────────────────────────────────────────────────────
    try:
        rows = google_ads_search(
            access_token=access_token,
            customer_id=customer_id,
            query=_HOURLY_GAQL,
            login_customer_id=login_customer_id,
            stream=True,
        )
    except Exception as exc:
        summary["errors"].append(f"API query failed: {exc}")
        return summary

    # Build campaign lookup: google_campaign_id (str) -> local AdsCampaign.id
    camp_lookup: Dict[str, int] = {}
    for c in AdsCampaign.query.filter_by(account_id=account_id).all():
        if c.google_campaign_id:
            key = _digits(c.google_campaign_id) or ""
            if key:
                camp_lookup[key] = c.id

    # ── upsert rows ─────────────────────────────────────────────────────────
    try:
        for row in rows:
            camp = row.get("campaign", {})
            metrics = row.get("metrics", {})
            seg = row.get("segments", {})

            google_cid = _int(camp.get("id"))
            if not google_cid:
                continue

            date_str = seg.get("date")
            hour = _int(seg.get("hour"))
            if not date_str:
                continue

            date_obj = dt.date.fromisoformat(date_str)

            # Resolve or create local campaign
            camp_key = str(google_cid)
            local_camp_id = camp_lookup.get(camp_key)
            if local_camp_id is None:
                # Auto-create minimal campaign row so we can FK into it
                from app.models_ads import AdsCampaign
                new_camp = AdsCampaign(
                    account_id=account_id,
                    name=camp.get("name") or f"Campaign {google_cid}",
                    status="enabled",
                    google_campaign_id=camp_key,
                    daily_budget_cents=0,
                )
                db.session.add(new_camp)
                db.session.flush()
                camp_lookup[camp_key] = new_camp.id
                local_camp_id = new_camp.id

            # Upsert GadsHourlyStats
            existing = GadsHourlyStats.query.filter_by(
                account_id=account_id,
                entity_type="campaign",
                google_entity_id=google_cid,
                date=date_obj,
                hour=hour,
            ).first()

            if existing is None:
                existing = GadsHourlyStats(
                    account_id=account_id,
                    entity_type="campaign",
                    google_entity_id=google_cid,
                    entity_id=local_camp_id,
                    date=date_obj,
                    hour=hour,
                )
                db.session.add(existing)

            existing.entity_id = local_camp_id
            existing.impressions = _int(metrics.get("impressions"))
            existing.clicks = _int(metrics.get("clicks"))
            existing.cost_micros = _int(metrics.get("costMicros"))
            existing.conversions = _float(metrics.get("conversions"))

            summary["synced"] += 1

        db.session.commit()
        logger.info("Hourly stats synced: %d rows for account %s", summary["synced"], account_id)
    except Exception as exc:
        db.session.rollback()
        summary["errors"].append(f"DB upsert failed: {exc}")
        logger.exception("sync_hourly_stats: DB error for account %s", account_id)

    return summary


# ─────────────────────────────────────────────────────────────────────────────
# B. Compute bid adjustments
# ─────────────────────────────────────────────────────────────────────────────

def compute_daypart_adjustments(account_id: int) -> List[Dict[str, Any]]:
    """
    Analyse GadsHourlyStats to find conversion probability by hour-of-week (0-167).

    For each campaign:
      - Calculate CVR per (day_of_week, hour) bucket
      - Normalise against account-wide average CVR
      - Emit adjustments where |modifier - 1.0| > 0.1

    Returns list of dicts:
      {campaign_id, campaign_name, day_of_week, hour, bid_modifier, cvr, avg_cvr, impressions}
    """
    from app.models_ads import GadsHourlyStats, AdsCampaign

    # Fetch all hourly rows for this account
    all_rows = (
        GadsHourlyStats.query
        .filter_by(account_id=account_id, entity_type="campaign")
        .all()
    )

    if not all_rows:
        return []

    # Build campaign name lookup
    camp_names: Dict[int, str] = {}
    for c in AdsCampaign.query.filter_by(account_id=account_id).all():
        camp_names[c.id] = c.name

    # Aggregate: campaign_id -> (dow, hour) -> {clicks, conversions, impressions}
    # dow comes from the date's weekday() (0=Mon … 6=Sun)
    Bucket = Dict[str, float]
    agg: Dict[int, Dict[tuple, Bucket]] = defaultdict(lambda: defaultdict(
        lambda: {"clicks": 0.0, "conversions": 0.0, "impressions": 0.0}
    ))

    for stat in all_rows:
        dow = stat.date.weekday()  # 0=Mon … 6=Sun
        key = (dow, stat.hour)
        bucket = agg[stat.entity_id][key]
        bucket["clicks"] += stat.clicks or 0
        bucket["conversions"] += stat.conversions or 0
        bucket["impressions"] += stat.impressions or 0

    results: List[Dict[str, Any]] = []

    for camp_id, slots in agg.items():
        # Compute overall average CVR for this campaign
        total_clicks = sum(b["clicks"] for b in slots.values())
        total_convs = sum(b["conversions"] for b in slots.values())

        if total_clicks < 1:
            continue  # not enough data

        avg_cvr = total_convs / total_clicks if total_clicks > 0 else 0.0

        for (dow, hour), bucket in slots.items():
            clicks = bucket["clicks"]
            convs = bucket["conversions"]
            impressions = bucket["impressions"]

            # Need at least a handful of clicks in this slot to be meaningful
            if clicks < 1:
                continue

            slot_cvr = convs / clicks if clicks > 0 else 0.0

            # Normalise: if avg is 0, treat all slots as neutral
            if avg_cvr > 0:
                normalized = slot_cvr / avg_cvr
            else:
                normalized = 1.0

            # Cap modifier: -90% … +100%
            bid_modifier = min(max(normalized, 0.1), 2.0)

            # Only emit meaningful changes
            if abs(bid_modifier - 1.0) <= 0.1:
                continue

            results.append({
                "campaign_id": camp_id,
                "campaign_name": camp_names.get(camp_id, f"Campaign {camp_id}"),
                "day_of_week": dow,
                "hour": hour,
                "bid_modifier": round(bid_modifier, 4),
                "cvr": round(slot_cvr, 6),
                "avg_cvr": round(avg_cvr, 6),
                "impressions": int(impressions),
            })

    # Sort for stable output: campaign → day → hour
    results.sort(key=lambda r: (r["campaign_id"], r["day_of_week"], r["hour"]))
    return results


# ─────────────────────────────────────────────────────────────────────────────
# C. Apply bid adjustments
# ─────────────────────────────────────────────────────────────────────────────

def apply_daypart_adjustments(
    account_id: int,
    adjustments: List[Dict[str, Any]],
    client=None,
) -> Dict[str, Any]:
    """
    Push AdSchedule bid adjustments to Google Ads CampaignCriterionService
    and persist to DaypartBidAdjustment.

    If no client is supplied (sandbox/test), records are still saved with applied_at=None.

    Returns {"applied": N, "errors": []}.
    """
    from app import db
    from app.models_ads import AdsCampaign, DaypartBidAdjustment

    result: Dict[str, Any] = {"applied": 0, "errors": []}
    now = dt.datetime.utcnow()

    # ── try to build a Google Ads client if one wasn't supplied ────────────
    campaign_criterion_service = None
    ads_client = client

    if ads_client is None:
        try:
            from app.google.utils_ads import resolve_ads_context, client_from_refresh
            from app.google.token_utils import ensure_access_token

            ctx = resolve_ads_context(account_id)
            customer_id = ctx.get("customer_id")
            login_customer_id = ctx.get("login_customer_id")

            if customer_id:
                _, refresh_token = ensure_access_token(account_id, ("ads", "lsa"))
                if refresh_token:
                    ads_client = client_from_refresh(refresh_token, login_customer_id)
        except Exception as exc:
            logger.warning("apply_daypart_adjustments: could not build client: %s", exc)
            ads_client = None

    if ads_client is not None:
        try:
            campaign_criterion_service = ads_client.get_service("CampaignCriterionService")
        except Exception as exc:
            logger.warning("apply_daypart_adjustments: CampaignCriterionService unavailable: %s", exc)
            campaign_criterion_service = None

    # Build campaign resource-name lookup
    camp_resource: Dict[int, str] = {}
    if ads_client is not None:
        try:
            from app.google.utils_ads import resolve_ads_context
            ctx = resolve_ads_context(account_id)
            customer_id = ctx.get("customer_id")
            if customer_id:
                from app.google.utils_ads import _digits_only
                cid = _digits_only(customer_id)
                for c in AdsCampaign.query.filter_by(account_id=account_id).all():
                    if c.google_campaign_id:
                        gid = _digits_only(c.google_campaign_id)
                        if gid:
                            # Google Ads resource name format
                            camp_resource[c.id] = f"customers/{cid}/campaigns/{gid}"
        except Exception as exc:
            logger.warning("apply_daypart_adjustments: resource name build failed: %s", exc)

    for adj in adjustments:
        camp_id = adj.get("campaign_id")
        dow = adj.get("day_of_week")
        hour = adj.get("hour")
        modifier = adj.get("bid_modifier", 1.0)

        if camp_id is None or dow is None or hour is None:
            result["errors"].append(f"Invalid adjustment entry: {adj}")
            continue

        applied_at = None

        # ── push to Google Ads API ──────────────────────────────────────────
        if campaign_criterion_service is not None and camp_id in camp_resource:
            try:
                resource_name = camp_resource[camp_id]
                day_name = _DOW_NAMES[dow % 7]

                # Build mutate operation
                criterion_op = ads_client.get_type("CampaignCriterionOperation")
                criterion = criterion_op.create

                criterion.campaign = resource_name
                criterion.ad_schedule.day_of_week = getattr(
                    ads_client.enums.DayOfWeekEnum, day_name
                )
                criterion.ad_schedule.start_hour = hour
                criterion.ad_schedule.end_hour = min(hour + 1, 24)
                criterion.ad_schedule.start_minute = (
                    ads_client.enums.MinuteOfHourEnum.ZERO
                )
                criterion.ad_schedule.end_minute = (
                    ads_client.enums.MinuteOfHourEnum.ZERO
                )
                criterion.bid_modifier = float(modifier)

                campaign_criterion_service.mutate_campaign_criteria(
                    customer_id=_digits_only_str(resource_name),
                    operations=[criterion_op],
                )
                applied_at = now
            except Exception as exc:
                err_msg = f"API mutate failed for campaign {camp_id} dow={dow} hour={hour}: {exc}"
                logger.warning(err_msg)
                result["errors"].append(err_msg)
                # Still save to DB with applied_at=None so user can see it
                applied_at = None

        # ── persist to DB ───────────────────────────────────────────────────
        try:
            existing = DaypartBidAdjustment.query.filter_by(
                campaign_id=camp_id,
                day_of_week=dow,
                hour=hour,
            ).first()

            camp = AdsCampaign.query.get(camp_id)
            google_cid = camp.google_campaign_id if camp else None

            if existing is None:
                existing = DaypartBidAdjustment(
                    account_id=account_id,
                    campaign_id=camp_id,
                    google_campaign_id=google_cid,
                    day_of_week=dow,
                    hour=hour,
                    bid_modifier=modifier,
                    data_source="auto",
                    applied_at=applied_at,
                )
                db.session.add(existing)
            else:
                existing.bid_modifier = modifier
                existing.data_source = "auto"
                existing.applied_at = applied_at
                existing.updated_at = now

            result["applied"] += 1
        except Exception as exc:
            err_msg = f"DB save failed for campaign {camp_id} dow={dow} hour={hour}: {exc}"
            logger.warning(err_msg)
            result["errors"].append(err_msg)

    try:
        db.session.commit()
        logger.info(
            "apply_daypart_adjustments: %d adjustments saved for account %s",
            result["applied"], account_id
        )
    except Exception as exc:
        db.session.rollback()
        result["errors"].append(f"Final commit failed: {exc}")
        logger.exception("apply_daypart_adjustments: commit error for account %s", account_id)

    return result


def _digits_only_str(resource_name: str) -> str:
    """Extract customer ID digits from a resource name like 'customers/1234/campaigns/5678'."""
    parts = resource_name.split("/")
    if len(parts) >= 2 and parts[0] == "customers":
        return "".join(c for c in parts[1] if c.isdigit())
    return ""
