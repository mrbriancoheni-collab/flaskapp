# app/services/fbads_sync.py
"""
Facebook Ads Daily Sync Service.

Pulls campaigns, adsets, ads, and last-30-day insights from the Meta
Marketing API and upserts them into local DB tables (FBCampaign, FBAdSet,
FBAd, FBDailyInsight).  Designed to be called from a background job once
per day per connected account.

Pull order:
  1. Campaigns
  2. Ad sets
  3. Ads
  4. Daily insights (last 30 days, campaign-level time_increment=1)
"""
from __future__ import annotations

import logging
from datetime import datetime, date
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

GRAPH = "https://graph.facebook.com/v20.0"

# ------------------------------------------------------------------
# helpers
# ------------------------------------------------------------------

def _int(v: Any, default: int = 0) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return default


def _paginate(url: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Fetch all pages of a Graph API list response."""
    items: List[Dict[str, Any]] = []
    while url:
        try:
            resp = requests.get(url, params=params, timeout=60)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.warning("FB API request failed (%s): %s", url, exc)
            break

        error = data.get("error")
        if error:
            logger.warning("FB API error: %s", error)
            break

        items.extend(data.get("data") or [])

        # Follow pagination cursor
        paging = data.get("paging") or {}
        next_url = paging.get("next")
        if next_url:
            url = next_url
            params = {}  # next URL already contains all params
        else:
            break

    return items


def _parse_datetime(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S+0000"):
        try:
            dt = datetime.strptime(s, fmt)
            # Store as naive UTC
            return dt.replace(tzinfo=None)
        except ValueError:
            pass
    return None


def _parse_actions(actions: List[Dict[str, Any]], *action_types: str) -> int:
    """Sum values for specific action types from the 'actions' array."""
    total = 0
    for action in actions:
        if action.get("action_type") in action_types:
            total += _int(action.get("value", 0))
    return total


# ------------------------------------------------------------------
# public entry point
# ------------------------------------------------------------------

def sync_fb_account(account_id: int) -> None:
    """
    Pull campaigns, adsets, ads, and last-30-day insights from Meta API
    into local DB tables for the given app account_id.

    Expects that a valid non-expired token exists in the facebook_tokens
    table (written by the OAuth flow in app/fbads/__init__.py).
    """
    from app import db
    from sqlalchemy import text

    # ---- 1. Fetch token + expiry ----------------------------------------
    try:
        with db.engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT access_token, expires_at, account_id as fb_account_id "
                    "FROM facebook_tokens WHERE account_id = :aid LIMIT 1"
                ),
                {"aid": account_id},
            ).fetchone()
    except Exception as exc:
        logger.warning("sync_fb_account(%s): could not query token — %s", account_id, exc)
        return

    if not row:
        logger.info("sync_fb_account(%s): no FB token found, skipping", account_id)
        return

    access_token, expires_at, _fb_aid = row[0], row[1], row[2]

    if expires_at and expires_at < datetime.utcnow():
        logger.warning(
            "sync_fb_account(%s): FB token expired at %s, skipping", account_id, expires_at
        )
        return

    # ---- 2. Resolve ad account ID from facebook_selected_accounts --------
    try:
        with db.engine.connect() as conn:
            sel_row = conn.execute(
                text(
                    "SELECT ad_account_id FROM facebook_selected_accounts "
                    "WHERE account_id = :aid LIMIT 1"
                ),
                {"aid": account_id},
            ).fetchone()
    except Exception as exc:
        logger.warning("sync_fb_account(%s): could not query selected account — %s", account_id, exc)
        return

    if not sel_row:
        logger.info(
            "sync_fb_account(%s): no selected ad account, skipping", account_id
        )
        return

    ad_account_id = sel_row[0]  # e.g. "act_123456789"
    logger.info(
        "sync_fb_account(%s): syncing ad account %s", account_id, ad_account_id
    )

    _sync_campaigns(account_id, ad_account_id, access_token, db)
    _sync_adsets(account_id, ad_account_id, access_token, db)
    _sync_ads(account_id, ad_account_id, access_token, db)
    _sync_insights(account_id, ad_account_id, access_token, db)

    logger.info("sync_fb_account(%s): sync complete", account_id)


# ------------------------------------------------------------------
# private sync helpers
# ------------------------------------------------------------------

def _sync_campaigns(
    account_id: int, ad_account_id: str, token: str, db: Any
) -> None:
    from app.models_fbads import FBCampaign

    logger.info("sync_fb_account(%s): fetching campaigns", account_id)
    items = _paginate(
        f"{GRAPH}/{ad_account_id}/campaigns",
        {
            "access_token": token,
            "fields": "id,name,status,objective,daily_budget,lifetime_budget,start_time,stop_time",
            "limit": 200,
        },
    )
    logger.info("sync_fb_account(%s): got %d campaigns", account_id, len(items))

    now = datetime.utcnow()
    for item in items:
        try:
            fb_id = item["id"]
            existing = FBCampaign.query.filter_by(
                account_id=account_id, fb_campaign_id=fb_id
            ).first()
            if existing:
                existing.name = item.get("name")
                existing.status = item.get("status")
                existing.objective = item.get("objective")
                existing.daily_budget = _int(item.get("daily_budget")) or None
                existing.lifetime_budget = _int(item.get("lifetime_budget")) or None
                existing.start_time = _parse_datetime(item.get("start_time"))
                existing.stop_time = _parse_datetime(item.get("stop_time"))
                existing.synced_at = now
            else:
                db.session.add(FBCampaign(
                    account_id=account_id,
                    fb_campaign_id=fb_id,
                    name=item.get("name"),
                    status=item.get("status"),
                    objective=item.get("objective"),
                    daily_budget=_int(item.get("daily_budget")) or None,
                    lifetime_budget=_int(item.get("lifetime_budget")) or None,
                    start_time=_parse_datetime(item.get("start_time")),
                    stop_time=_parse_datetime(item.get("stop_time")),
                    synced_at=now,
                ))
        except Exception as exc:
            logger.warning("sync_fb_account(%s): error upserting campaign %s — %s", account_id, item.get("id"), exc)
            db.session.rollback()
            continue

    try:
        db.session.commit()
    except Exception as exc:
        logger.error("sync_fb_account(%s): commit failed for campaigns — %s", account_id, exc)
        db.session.rollback()


def _sync_adsets(
    account_id: int, ad_account_id: str, token: str, db: Any
) -> None:
    from app.models_fbads import FBAdSet

    logger.info("sync_fb_account(%s): fetching adsets", account_id)
    items = _paginate(
        f"{GRAPH}/{ad_account_id}/adsets",
        {
            "access_token": token,
            "fields": "id,name,status,campaign_id,daily_budget,bid_amount",
            "limit": 200,
        },
    )
    logger.info("sync_fb_account(%s): got %d adsets", account_id, len(items))

    now = datetime.utcnow()
    for item in items:
        try:
            fb_id = item["id"]
            existing = FBAdSet.query.filter_by(
                account_id=account_id, fb_adset_id=fb_id
            ).first()
            if existing:
                existing.name = item.get("name")
                existing.status = item.get("status")
                existing.fb_campaign_id = item.get("campaign_id")
                existing.daily_budget = _int(item.get("daily_budget")) or None
                existing.bid_amount = _int(item.get("bid_amount")) or None
                existing.synced_at = now
            else:
                db.session.add(FBAdSet(
                    account_id=account_id,
                    fb_adset_id=fb_id,
                    name=item.get("name"),
                    status=item.get("status"),
                    fb_campaign_id=item.get("campaign_id"),
                    daily_budget=_int(item.get("daily_budget")) or None,
                    bid_amount=_int(item.get("bid_amount")) or None,
                    synced_at=now,
                ))
        except Exception as exc:
            logger.warning("sync_fb_account(%s): error upserting adset %s — %s", account_id, item.get("id"), exc)
            db.session.rollback()
            continue

    try:
        db.session.commit()
    except Exception as exc:
        logger.error("sync_fb_account(%s): commit failed for adsets — %s", account_id, exc)
        db.session.rollback()


def _sync_ads(
    account_id: int, ad_account_id: str, token: str, db: Any
) -> None:
    from app.models_fbads import FBAd

    logger.info("sync_fb_account(%s): fetching ads", account_id)
    items = _paginate(
        f"{GRAPH}/{ad_account_id}/ads",
        {
            "access_token": token,
            "fields": "id,name,status,adset_id,campaign_id",
            "limit": 200,
        },
    )
    logger.info("sync_fb_account(%s): got %d ads", account_id, len(items))

    now = datetime.utcnow()
    for item in items:
        try:
            fb_id = item["id"]
            existing = FBAd.query.filter_by(
                account_id=account_id, fb_ad_id=fb_id
            ).first()
            if existing:
                existing.name = item.get("name")
                existing.status = item.get("status")
                existing.fb_adset_id = item.get("adset_id")
                existing.fb_campaign_id = item.get("campaign_id")
                existing.synced_at = now
            else:
                db.session.add(FBAd(
                    account_id=account_id,
                    fb_ad_id=fb_id,
                    name=item.get("name"),
                    status=item.get("status"),
                    fb_adset_id=item.get("adset_id"),
                    fb_campaign_id=item.get("campaign_id"),
                    synced_at=now,
                ))
        except Exception as exc:
            logger.warning("sync_fb_account(%s): error upserting ad %s — %s", account_id, item.get("id"), exc)
            db.session.rollback()
            continue

    try:
        db.session.commit()
    except Exception as exc:
        logger.error("sync_fb_account(%s): commit failed for ads — %s", account_id, exc)
        db.session.rollback()


def _sync_insights(
    account_id: int, ad_account_id: str, token: str, db: Any
) -> None:
    from app.models_fbads import FBDailyInsight

    logger.info("sync_fb_account(%s): fetching insights (last 30 days)", account_id)
    items = _paginate(
        f"{GRAPH}/{ad_account_id}/insights",
        {
            "access_token": token,
            "fields": "campaign_id,spend,impressions,clicks,actions,cpm,cpc,ctr",
            "time_increment": 1,
            "date_preset": "last_30d",
            "level": "campaign",
            "limit": 500,
        },
    )
    logger.info("sync_fb_account(%s): got %d insight rows", account_id, len(items))

    for item in items:
        try:
            fb_campaign_id = item.get("campaign_id")
            raw_date = item.get("date_start")  # "YYYY-MM-DD"
            if not raw_date:
                continue
            insight_date = date.fromisoformat(raw_date)

            actions_list: List[Dict[str, Any]] = item.get("actions") or []
            leads = _parse_actions(
                actions_list,
                "offsite_conversion.fb_pixel_lead",
                "lead",
            )
            conversions = _parse_actions(
                actions_list,
                "offsite_conversion.fb_pixel_purchase",
                "purchase",
                "offsite_conversion",
            )

            existing = FBDailyInsight.query.filter_by(
                account_id=account_id,
                fb_campaign_id=fb_campaign_id,
                date=insight_date,
            ).first()

            if existing:
                existing.spend = item.get("spend")
                existing.impressions = _int(item.get("impressions")) or None
                existing.clicks = _int(item.get("clicks")) or None
                existing.conversions = conversions or None
                existing.leads = leads or None
                existing.cpm = item.get("cpm")
                existing.cpc = item.get("cpc")
                existing.ctr = item.get("ctr")
            else:
                db.session.add(FBDailyInsight(
                    account_id=account_id,
                    fb_campaign_id=fb_campaign_id,
                    date=insight_date,
                    spend=item.get("spend"),
                    impressions=_int(item.get("impressions")) or None,
                    clicks=_int(item.get("clicks")) or None,
                    conversions=conversions or None,
                    leads=leads or None,
                    cpm=item.get("cpm"),
                    cpc=item.get("cpc"),
                    ctr=item.get("ctr"),
                ))
        except Exception as exc:
            logger.warning(
                "sync_fb_account(%s): error upserting insight row %s — %s",
                account_id, item, exc
            )
            db.session.rollback()
            continue

    try:
        db.session.commit()
    except Exception as exc:
        logger.error("sync_fb_account(%s): commit failed for insights — %s", account_id, exc)
        db.session.rollback()
