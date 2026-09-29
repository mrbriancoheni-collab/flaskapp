# app/services/google_ads_sync.py
"""
Google Ads Daily Sync Service.

Pulls live performance data from the Google Ads API via GAQL and upserts
into local DB tables (GadsStatsDaily, SearchTerm).  Designed to be called
from a cron endpoint once per day per connected account.

Pull order:
  1. Campaign stats  (impressions, clicks, spend, conversions, IS)
  2. Ad group stats
  3. Keyword stats   (+ Quality Score and sub-scores)
  4. Search term report (last 30 days)

Mapping strategy:
  - google_campaign_id from the API is matched to AdsCampaign.google_campaign_id
    to produce a local entity_id for DB JOINs.
  - Unknown entities (campaigns created directly in Google Ads, never imported)
    are auto-imported as minimal AdsCampaign / AdsAdGroup / AdsKeyword rows.
  - google_entity_id stores the raw Google resource ID alongside entity_id.
"""
from __future__ import annotations

import datetime as dt
import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# QS bucket enum → friendly label mapping
_QS_BUCKET: Dict[str, str] = {
    "BELOW_AVERAGE": "BELOW_AVERAGE",
    "AVERAGE": "AVERAGE",
    "ABOVE_AVERAGE": "ABOVE_AVERAGE",
    "UNKNOWN": None,
    "UNSPECIFIED": None,
}


def _digits(v: Any) -> Optional[str]:
    if v is None:
        return None
    return "".join(c for c in str(v) if c.isdigit()) or None


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


def _qs_bucket(value: Any) -> Optional[str]:
    if not value:
        return None
    s = str(value).upper().replace(" ", "_")
    return _QS_BUCKET.get(s)


def _date_range(days: int) -> Tuple[str, str]:
    end = dt.date.today() - dt.timedelta(days=1)
    start = end - dt.timedelta(days=days - 1)
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


def _upsert_stats(
    session,
    account_id: int,
    entity_type: str,
    google_entity_id: int,
    local_entity_id: int,
    date_obj: dt.date,
    *,
    impressions: int = 0,
    clicks: int = 0,
    cost_micros: int = 0,
    conversions: float = 0.0,
    conversion_value: float = 0.0,
    avg_cpc: Optional[float] = None,
    search_impr_share: Optional[float] = None,
    lost_is_budget: Optional[float] = None,
    lost_is_rank: Optional[float] = None,
    quality_score: Optional[int] = None,
    landing_page_exp: Optional[str] = None,
    ad_relevance: Optional[str] = None,
    expected_ctr: Optional[str] = None,
):
    from app.models_ads import GadsStatsDaily

    row = GadsStatsDaily.query.filter_by(
        account_id=account_id,
        entity_type=entity_type,
        google_entity_id=google_entity_id,
        date=date_obj,
    ).first()

    if row is None:
        # Claim any orphaned row written before account_id column existed
        row = GadsStatsDaily.query.filter(
            GadsStatsDaily.account_id.is_(None),
            GadsStatsDaily.entity_type == entity_type,
            GadsStatsDaily.google_entity_id == google_entity_id,
            GadsStatsDaily.date == date_obj,
        ).first()

    if row is None:
        row = GadsStatsDaily(
            account_id=account_id,
            entity_type=entity_type,
            google_entity_id=google_entity_id,
            entity_id=local_entity_id,
            date=date_obj,
        )
        session.add(row)

    row.entity_id       = local_entity_id
    row.impressions     = impressions
    row.clicks          = clicks
    row.cost_micros     = cost_micros
    row.conversions     = conversions
    row.conversion_value = conversion_value
    row.avg_cpc         = avg_cpc
    row.search_impr_share = search_impr_share
    row.lost_is_budget  = lost_is_budget
    row.lost_is_rank    = lost_is_rank
    row.quality_score   = quality_score
    row.landing_page_exp = landing_page_exp
    row.ad_relevance    = ad_relevance
    row.expected_ctr    = expected_ctr


def _get_or_create_campaign(session, account_id: int, google_cid: int, name: str, status: str) -> int:
    """Return local AdsCampaign.id, creating or updating a row as needed."""
    from app.models_ads import AdsCampaign
    camp = AdsCampaign.query.filter_by(
        account_id=account_id, google_campaign_id=str(google_cid)
    ).first()
    if camp is None:
        camp = AdsCampaign.query.filter(
            AdsCampaign.account_id.is_(None),
            AdsCampaign.google_campaign_id == str(google_cid),
        ).first()
        if camp is not None:
            camp.account_id = account_id
            session.flush()
    if camp is None:
        camp = AdsCampaign(
            account_id=account_id,
            name=name or f"Campaign {google_cid}",
            status=status.lower() if status else "enabled",
            google_campaign_id=str(google_cid),
            daily_budget_cents=0,
        )
        session.add(camp)
        session.flush()
    else:
        if name:
            camp.name = name
        if status:
            camp.status = status.lower()
    return camp.id


def _get_or_create_adgroup(session, campaign_local_id: int, google_agid: int, name: str, status: str) -> int:
    from app.models_ads import AdsAdGroup
    ag = AdsAdGroup.query.filter_by(
        campaign_id=campaign_local_id, google_ad_group_id=str(google_agid)
    ).first()
    if ag is None:
        ag = AdsAdGroup(
            campaign_id=campaign_local_id,
            name=name or f"Ad Group {google_agid}",
            status=status.lower() if status else "enabled",
            google_ad_group_id=str(google_agid),
        )
        session.add(ag)
        session.flush()
    else:
        if name:
            ag.name = name
        if status:
            ag.status = status.lower()
    return ag.id


def _get_or_create_keyword(
    session, adgroup_local_id: int, google_criterion_id: int,
    text: str, match_type: str, status: str,
    max_cpc_micros: Optional[int] = None,
) -> int:
    from app.models_ads import AdsKeyword
    norm_mt = (match_type or "broad").lower()
    norm_status = status.lower() if status else "enabled"

    # Primary lookup: by google_keyword_id
    kw = AdsKeyword.query.filter_by(
        ad_group_id=adgroup_local_id, google_keyword_id=str(google_criterion_id)
    ).first()

    if kw is None and text:
        # Fallback: match by text+match_type (handles manually-created rows with no google_keyword_id)
        kw = AdsKeyword.query.filter_by(
            ad_group_id=adgroup_local_id, text=text, match_type=norm_mt
        ).first()
        if kw is not None:
            kw.google_keyword_id = str(google_criterion_id)

    if kw is None:
        kw = AdsKeyword(
            ad_group_id=adgroup_local_id,
            text=text or "",
            match_type=norm_mt,
            status=norm_status,
            google_keyword_id=str(google_criterion_id),
        )
        if max_cpc_micros:
            kw.max_cpc_cents = max_cpc_micros // 10000
        session.add(kw)
        session.flush()
    else:
        kw.status = norm_status
        if max_cpc_micros:
            kw.max_cpc_cents = max_cpc_micros // 10000
    return kw.id


def sync_structure(account_id: int) -> Dict[str, Any]:
    """
    Pull the full account structure (campaigns, ad groups, keywords, ads, negatives)
    without a date filter so every entity is captured regardless of impression volume.

    This runs before sync_account's date-windowed stats pull so the keywords table
    is populated correctly — including zero-traffic keywords.
    """
    from flask import current_app
    from app import db
    from app.google.utils_ads import resolve_ads_context, google_ads_search
    from app.google.token_utils import ensure_access_token
    from app.google.gaql_queries import (
        CAMPAIGN_STRUCTURE, ADGROUP_STRUCTURE, KEYWORD_STRUCTURE,
        NEGATIVE_KEYWORD_STRUCTURE, AD_STRUCTURE,
    )
    from app.models_ads import AdsCampaign, AdsAdGroup, AdsKeyword, NegativeKeyword, AdsAd

    summary: Dict[str, Any] = {
        "campaigns": 0, "adgroups": 0, "keywords": 0,
        "negatives": 0, "ads": 0, "errors": [],
    }

    try:
        ctx = resolve_ads_context(account_id)
        customer_id = ctx.get("customer_id")
        login_customer_id = ctx.get("login_customer_id")
        if not customer_id:
            summary["errors"].append("No customer_id configured.")
            return summary
        access_token, _ = ensure_access_token(account_id, ("ads", "lsa"))
    except Exception as exc:
        summary["errors"].append(f"Credential error: {exc}")
        return summary

    def _search(q: str) -> List[dict]:
        return google_ads_search(
            access_token=access_token,
            customer_id=customer_id,
            query=q,
            login_customer_id=login_customer_id,
            stream=True,
        )

    # ── Campaigns ────────────────────────────────────────────────────────────
    try:
        for row in _search(CAMPAIGN_STRUCTURE):
            c = row.get("campaign", {})
            gid = _int(c.get("id"))
            if not gid:
                continue
            _get_or_create_campaign(db.session, account_id, gid, c.get("name", ""), c.get("status", "ENABLED"))
            summary["campaigns"] += 1
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        summary["errors"].append(f"Campaign structure: {exc}")
        logger.exception("Campaign structure sync failed for account %s", account_id)

    # ── Ad groups ────────────────────────────────────────────────────────────
    try:
        for row in _search(ADGROUP_STRUCTURE):
            ag = row.get("adGroup", {})
            c = row.get("campaign", {})
            gaid = _int(ag.get("id"))
            gcid = _int(c.get("id"))
            if not gaid or not gcid:
                continue
            camp_local = _get_or_create_campaign(db.session, account_id, gcid, "", "ENABLED")
            _get_or_create_adgroup(db.session, camp_local, gaid, ag.get("name", ""), ag.get("status", "ENABLED"))
            summary["adgroups"] += 1
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        summary["errors"].append(f"Ad group structure: {exc}")
        logger.exception("Ad group structure sync failed for account %s", account_id)

    # ── Keywords ─────────────────────────────────────────────────────────────
    try:
        for row in _search(KEYWORD_STRUCTURE):
            crit = row.get("adGroupCriterion", {})
            c = row.get("campaign", {})
            ag = row.get("adGroup", {})
            gcrid = _int(crit.get("criterionId"))
            gcid = _int(c.get("id"))
            gaid = _int(ag.get("id"))
            if not gcrid or not gaid:
                continue
            kw_data = crit.get("keyword", {})
            camp_local = _get_or_create_campaign(db.session, account_id, gcid, "", "ENABLED")
            ag_local = _get_or_create_adgroup(db.session, camp_local, gaid, "", "ENABLED")
            _get_or_create_keyword(
                db.session, ag_local, gcrid,
                kw_data.get("text", ""),
                kw_data.get("matchType", "BROAD"),
                crit.get("status", "ENABLED"),
                max_cpc_micros=_int(crit.get("effectiveCpcBidMicros")),
            )
            summary["keywords"] += 1
        db.session.commit()
        logger.info("Keyword structure synced: %d keywords", summary["keywords"])
    except Exception as exc:
        db.session.rollback()
        summary["errors"].append(f"Keyword structure: {exc}")
        logger.exception("Keyword structure sync failed for account %s", account_id)

    # ── Negative keywords (campaign-level) ──────────────────────────────────
    try:
        for row in _search(NEGATIVE_KEYWORD_STRUCTURE):
            cc = row.get("campaignCriterion", {})
            c = row.get("campaign", {})
            gcid = _int(c.get("id"))
            if not gcid:
                continue
            kw_data = cc.get("keyword", {})
            term = kw_data.get("text", "").strip()
            if not term:
                continue
            camp_local = _get_or_create_campaign(db.session, account_id, gcid, "", "ENABLED")
            mt = (kw_data.get("matchType") or "EXACT").upper()
            existing = NegativeKeyword.query.filter_by(
                campaign_id=camp_local,
                text=term,
                match_type=mt,
                scope="campaign",
            ).first()
            if not existing:
                db.session.add(NegativeKeyword(
                    campaign_id=camp_local,
                    text=term,
                    match_type=mt,
                    scope="campaign",
                ))
            summary["negatives"] += 1
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        summary["errors"].append(f"Negative keyword structure: {exc}")
        logger.exception("Negative keyword structure sync failed for account %s", account_id)

    # ── Ads (RSA + ETA) ──────────────────────────────────────────────────────
    try:
        for row in _search(AD_STRUCTURE):
            aga = row.get("adGroupAd", {})
            ad_data = aga.get("ad", {})
            c = row.get("campaign", {})
            ag = row.get("adGroup", {})
            google_ad_id = str(_int(ad_data.get("id"))) if ad_data.get("id") else None
            gaid = _int(ag.get("id"))
            gcid = _int(c.get("id"))
            if not google_ad_id or not gaid:
                continue

            camp_local = _get_or_create_campaign(db.session, account_id, gcid, "", "ENABLED")
            ag_local = _get_or_create_adgroup(db.session, camp_local, gaid, "", "ENABLED")

            existing_ad = AdsAd.query.filter_by(
                ad_group_id=ag_local, google_ad_id=google_ad_id
            ).first()

            status = (aga.get("status") or "ENABLED").lower()
            rsa = ad_data.get("responsiveSearchAd", {})
            eta = ad_data.get("expandedTextAd", {})

            # Extract headlines/descriptions (RSA)
            headlines = [h.get("text", "") for h in (rsa.get("headlines") or [])]
            descriptions = [d.get("text", "") for d in (rsa.get("descriptions") or [])]

            final_urls = ad_data.get("finalUrls") or []
            final_url = final_urls[0] if final_urls else ""

            def _trunc(s, n):
                return (s or "")[:n]

            h1 = _trunc(headlines[0] if headlines else eta.get("headlinePart1", ""), 30)
            h2 = _trunc(headlines[1] if len(headlines) > 1 else eta.get("headlinePart2", ""), 30)
            h3 = _trunc(headlines[2] if len(headlines) > 2 else "", 30)
            desc1 = _trunc(descriptions[0] if descriptions else eta.get("description", ""), 90)

            if existing_ad:
                existing_ad.status = status
                if h1:
                    existing_ad.headline1 = h1
                if h2:
                    existing_ad.headline2 = h2
                if h3:
                    existing_ad.headline3 = h3
                if desc1:
                    existing_ad.description1 = desc1
                if final_url:
                    existing_ad.final_url = final_url
            else:
                new_ad = AdsAd(
                    ad_group_id=ag_local,
                    google_ad_id=google_ad_id,
                    status=status,
                    headline1=h1 or "(no headline)",
                    headline2=h2 or None,
                    headline3=h3 or None,
                    description1=desc1 or None,
                    final_url=final_url or "",
                )
                db.session.add(new_ad)
            summary["ads"] += 1
        db.session.commit()
        logger.info("Ad structure synced: %d ads", summary["ads"])
    except Exception as exc:
        db.session.rollback()
        summary["errors"].append(f"Ad structure: {exc}")
        logger.exception("Ad structure sync failed for account %s", account_id)

    return summary


def sync_account(account_id: int, days: int = 30) -> Dict[str, Any]:
    """
    Pull all GAQL data for one account and upsert into GadsStatsDaily.
    Returns a summary dict with counts and any errors.
    """
    from flask import current_app
    from app import db
    from app.google.utils_ads import resolve_ads_context, google_ads_search
    from app.google.token_utils import ensure_access_token
    from app.google.gaql_queries import CAMPAIGN_STATS, ADGROUP_STATS, KEYWORD_STATS
    from app.models_ads import AdsCampaign, GadsStatsDaily
    AdsCampaign.ensure_columns()
    GadsStatsDaily.ensure_columns()

    summary: Dict[str, Any] = {
        "account_id": account_id,
        "campaigns_synced": 0,
        "adgroups_synced": 0,
        "keywords_synced": 0,
        "search_terms_synced": 0,
        "errors": [],
    }

    # ── resolve credentials ──────────────────────────────────────────────────
    try:
        ctx = resolve_ads_context(account_id)
        customer_id = ctx.get("customer_id")
        login_customer_id = ctx.get("login_customer_id")
        if not customer_id:
            summary["errors"].append("No Google Ads customer_id configured for account.")
            return summary

        access_token, _ = ensure_access_token(account_id, ("ads", "lsa"))
    except Exception as exc:
        summary["errors"].append(f"Credential error: {exc}")
        return summary

    start_date, end_date = _date_range(days)

    def _search(query: str) -> List[dict]:
        return google_ads_search(
            access_token=access_token,
            customer_id=customer_id,
            query=query,
            login_customer_id=login_customer_id,
            stream=True,
        )

    # ── Campaign stats ───────────────────────────────────────────────────────
    try:
        query = CAMPAIGN_STATS.format(start=start_date, end=end_date)
        rows = _search(query)

        # We'll get one row per (campaign, date) if segmented — but GAQL without
        # segments.date returns a single aggregate row per campaign.
        # Add date segmentation to get daily rows:
        # Add segments.date to SELECT so we get one row per (campaign, date).
        # Insert before FROM with a comma on the preceding line.
        dated_query = CAMPAIGN_STATS.format(start=start_date, end=end_date).replace(
            "\nFROM campaign",
            ",\n  segments.date\nFROM campaign"
        )
        rows = _search(dated_query)

        for row in rows:
            camp = row.get("campaign", {})
            metrics = row.get("metrics", {})
            seg = row.get("segments", {})

            google_cid = _int(camp.get("id"))
            if not google_cid:
                continue

            date_str = seg.get("date")
            if not date_str:
                continue
            date_obj = dt.date.fromisoformat(date_str)

            name = camp.get("name", "")
            status = camp.get("status", "ENABLED")
            local_id = _get_or_create_campaign(db.session, account_id, google_cid, name, status)

            _upsert_stats(
                db.session, account_id, "campaign", google_cid, local_id, date_obj,
                impressions=_int(metrics.get("impressions")),
                clicks=_int(metrics.get("clicks")),
                cost_micros=_int(metrics.get("costMicros")),
                conversions=_float(metrics.get("conversions")),
                conversion_value=_float(metrics.get("conversionsValue")),
                avg_cpc=_float(metrics.get("averageCpc")) or None,
                search_impr_share=_float(metrics.get("searchImpressionShare")) or None,
                lost_is_budget=_float(metrics.get("searchBudgetLostImpressionShare")) or None,
                lost_is_rank=_float(metrics.get("searchRankLostImpressionShare")) or None,
            )
            summary["campaigns_synced"] += 1

        db.session.commit()
        logger.info("Campaigns synced: %d rows", summary["campaigns_synced"])
    except Exception as exc:
        db.session.rollback()
        summary["errors"].append(f"Campaign sync: {exc}")
        logger.exception("Campaign sync failed for account %s", account_id)

    # ── Ad group stats ───────────────────────────────────────────────────────
    try:
        dated_query = ADGROUP_STATS.format(start=start_date, end=end_date).replace(
            "\nFROM ad_group",
            ",\n  segments.date\nFROM ad_group"
        )
        rows = _search(dated_query)

        for row in rows:
            ag = row.get("adGroup", {})
            camp = row.get("campaign", {})
            metrics = row.get("metrics", {})
            seg = row.get("segments", {})

            google_agid = _int(ag.get("id"))
            google_cid = _int(camp.get("id"))
            if not google_agid or not google_cid:
                continue

            date_str = seg.get("date")
            if not date_str:
                continue
            date_obj = dt.date.fromisoformat(date_str)

            camp_local = _get_or_create_campaign(
                db.session, account_id, google_cid, "", "ENABLED"
            )
            ag_local = _get_or_create_adgroup(
                db.session, camp_local, google_agid,
                ag.get("name", ""), ag.get("status", "ENABLED")
            )

            _upsert_stats(
                db.session, account_id, "ad_group", google_agid, ag_local, date_obj,
                impressions=_int(metrics.get("impressions")),
                clicks=_int(metrics.get("clicks")),
                cost_micros=_int(metrics.get("costMicros")),
                conversions=_float(metrics.get("conversions")),
                avg_cpc=_float(metrics.get("averageCpc")) or None,
            )
            summary["adgroups_synced"] += 1

        db.session.commit()
        logger.info("Ad groups synced: %d rows", summary["adgroups_synced"])
    except Exception as exc:
        db.session.rollback()
        summary["errors"].append(f"Ad group sync: {exc}")
        logger.exception("Ad group sync failed for account %s", account_id)

    # ── Keyword stats (+ Quality Score) ─────────────────────────────────────
    try:
        dated_query = KEYWORD_STATS.format(start=start_date, end=end_date).replace(
            "\nFROM keyword_view",
            ",\n  segments.date\nFROM keyword_view"
        )
        rows = _search(dated_query)

        for row in rows:
            crit = row.get("adGroupCriterion", {})
            camp = row.get("campaign", {})
            ag = row.get("adGroup", {})
            metrics = row.get("metrics", {})
            seg = row.get("segments", {})
            qi = crit.get("qualityInfo", {})

            google_crid = _int(crit.get("criterionId"))
            google_cid = _int(camp.get("id"))
            google_agid = _int(ag.get("id"))
            if not google_crid or not google_agid:
                continue

            date_str = seg.get("date")
            if not date_str:
                continue
            date_obj = dt.date.fromisoformat(date_str)

            camp_local = _get_or_create_campaign(db.session, account_id, google_cid, "", "ENABLED")
            ag_local = _get_or_create_adgroup(db.session, camp_local, google_agid, "", "ENABLED")
            kw = crit.get("keyword", {})
            kw_local = _get_or_create_keyword(
                db.session, ag_local, google_crid,
                kw.get("text", ""), kw.get("matchType", "BROAD"),
                crit.get("status", "ENABLED"),
            )

            _upsert_stats(
                db.session, account_id, "keyword", google_crid, kw_local, date_obj,
                impressions=_int(metrics.get("impressions")),
                clicks=_int(metrics.get("clicks")),
                cost_micros=_int(metrics.get("costMicros")),
                conversions=_float(metrics.get("conversions")),
                avg_cpc=_float(metrics.get("averageCpc")) or None,
                quality_score=_int(qi.get("qualityScore")) or None,
                landing_page_exp=_qs_bucket(qi.get("landingPageExperience")),
                ad_relevance=_qs_bucket(qi.get("adRelevance")),
                expected_ctr=_qs_bucket(qi.get("creativeQualityScore")),
            )
            summary["keywords_synced"] += 1

        db.session.commit()
        logger.info("Keywords synced: %d rows", summary["keywords_synced"])
    except Exception as exc:
        db.session.rollback()
        summary["errors"].append(f"Keyword sync: {exc}")
        logger.exception("Keyword sync failed for account %s", account_id)

    # ── Search terms ─────────────────────────────────────────────────────────
    try:
        result = sync_search_terms(account_id, access_token, customer_id, login_customer_id)
        summary["search_terms_synced"] = result.get("synced", 0)
        if result.get("error"):
            summary["errors"].append(f"Search terms: {result['error']}")
    except Exception as exc:
        summary["errors"].append(f"Search term sync: {exc}")

    return summary


def sync_search_terms(
    account_id: int,
    access_token: Optional[str] = None,
    customer_id: Optional[str] = None,
    login_customer_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Pull the last-30-day search term report and upsert into SearchTerm.
    Existing rows are updated; new rows are inserted.
    Preserves added_as_keyword / added_as_negative flags.
    """
    from app import db
    from app.models_ads import SearchTerm, AdsCampaign, AdsAdGroup
    from app.google.utils_ads import resolve_ads_context, google_ads_search
    from app.google.gaql_queries import SEARCH_TERMS_30D

    if not access_token or not customer_id:
        try:
            from app.google.utils_ads import resolve_ads_context
            from app.google.token_utils import ensure_access_token
            ctx = resolve_ads_context(account_id)
            customer_id = ctx.get("customer_id")
            login_customer_id = ctx.get("login_customer_id")
            access_token, _ = ensure_access_token(account_id, ("ads", "lsa"))
        except Exception as exc:
            return {"synced": 0, "error": str(exc)}

    if not customer_id or not access_token:
        return {"synced": 0, "error": "Missing credentials"}

    try:
        rows = google_ads_search(
            access_token=access_token,
            customer_id=customer_id,
            query=SEARCH_TERMS_30D,
            login_customer_id=login_customer_id,
            stream=True,
        )
    except Exception as exc:
        return {"synced": 0, "error": str(exc)}

    # Build lookup: google_campaign_id → local campaign id
    camp_lookup: Dict[str, int] = {}
    for c in AdsCampaign.query.filter_by(account_id=account_id).all():
        if c.google_campaign_id:
            camp_lookup[_digits(c.google_campaign_id) or ""] = c.id

    ag_lookup: Dict[str, int] = {}
    for ag in (AdsAdGroup.query
               .join(AdsCampaign, AdsCampaign.id == AdsAdGroup.campaign_id)
               .filter(AdsCampaign.account_id == account_id).all()):
        if ag.google_ad_group_id:
            ag_lookup[_digits(ag.google_ad_group_id) or ""] = ag.id

    today = dt.date.today()
    synced = 0

    for row in rows:
        stv = row.get("searchTermView", {})
        camp = row.get("campaign", {})
        ag_data = row.get("adGroup", {})
        metrics = row.get("metrics", {})

        term = stv.get("searchTerm") or ""
        if not term:
            continue

        google_cid = _digits(camp.get("id"))
        google_agid = _digits(ag_data.get("id"))
        camp_local_id = camp_lookup.get(google_cid or "")
        ag_local_id = ag_lookup.get(google_agid or "")

        # Find existing row for this term + ad group (last 30 days)
        existing = SearchTerm.query.filter_by(
            search_term=term,
            campaign_id=camp_local_id,
            ad_group_id=ag_local_id,
            date=today,
        ).first()

        if existing:
            existing.clicks       = _int(metrics.get("clicks"))
            existing.impressions  = _int(metrics.get("impressions"))
            existing.cost_micros  = _int(metrics.get("costMicros"))
            existing.conversions  = _float(metrics.get("conversions"))
        else:
            db.session.add(SearchTerm(
                search_term=term,
                campaign_id=camp_local_id,
                ad_group_id=ag_local_id,
                clicks=_int(metrics.get("clicks")),
                impressions=_int(metrics.get("impressions")),
                cost_micros=_int(metrics.get("costMicros")),
                conversions=_float(metrics.get("conversions")),
                date=today,
            ))
        synced += 1

    try:
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        return {"synced": 0, "error": str(exc)}

    return {"synced": synced}


def sync_conversions(account_id: int) -> Dict[str, Any]:
    """
    Pull conversion actions from Google Ads and upsert into conversion_actions table.
    Returns {"synced": N, "error": str|None}.
    """
    from app import db
    from app.models_ads import ConversionAction
    from app.google.gaql_queries import CONVERSION_ACTIONS

    try:
        from app.google.utils_ads import google_ads_search, resolve_ads_context
        from app.auth.token_utils import ensure_access_token
    except ImportError as exc:
        return {"synced": 0, "error": f"Import error: {exc}"}

    ctx = resolve_ads_context(account_id)
    if not ctx:
        return {"synced": 0, "error": "No Google Ads context"}

    token = ensure_access_token(account_id, ["google_ads"])
    if not token:
        return {"synced": 0, "error": "No access token"}

    rows = google_ads_search(
        customer_id=ctx["customer_id"],
        login_customer_id=ctx.get("login_customer_id"),
        access_token=token,
        query=CONVERSION_ACTIONS,
    )

    synced = 0
    for row in rows:
        ca = row.get("conversionAction", {})
        metrics = row.get("metrics", {})
        vs = ca.get("valueSettings", {})

        gid = _digits(ca.get("id"))
        if not gid:
            continue

        existing = ConversionAction.query.filter_by(
            account_id=account_id,
            google_conversion_id=gid,
        ).first()

        fields = dict(
            name=ca.get("name") or "",
            category=ca.get("category"),
            type_=ca.get("type"),
            status=ca.get("status"),
            counting_type=ca.get("countingType"),
            value_settings_default=_float(vs.get("defaultValue")),
            value_settings_currency=vs.get("currencyCode"),
            include_in_conversions=ca.get("includeInConversionsMetric", True),
            click_through_window_days=_int(ca.get("clickThroughLookbackWindowDays")) or None,
            view_through_window_days=_int(ca.get("viewThroughLookbackWindowDays")) or None,
            conversions_30d=_float(metrics.get("conversions")),
            conversion_value_30d=_float(metrics.get("conversionsValue")),
        )

        if existing:
            for k, v in fields.items():
                setattr(existing, k, v)
        else:
            db.session.add(ConversionAction(
                account_id=account_id,
                google_conversion_id=gid,
                **fields,
            ))
        synced += 1

    try:
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        return {"synced": 0, "error": str(exc)}

    return {"synced": synced}
