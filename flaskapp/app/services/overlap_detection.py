# app/services/overlap_detection.py
"""
Keyword overlap detection service for the multi-location feature.

Detects keywords that two accounts in the same LocationGroup are both bidding
on (ENABLED keywords in ENABLED ad groups in ENABLED campaigns).  Overlapping
keywords mean the two locations are competing against each other in the auction,
which wastes budget.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from itertools import combinations
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

_GAQL = """
SELECT
  ad_group_criterion.keyword.text,
  ad_group_criterion.keyword.match_type,
  ad_group.id,
  campaign.id
FROM ad_group_criterion
WHERE ad_group_criterion.type = 'KEYWORD'
  AND ad_group_criterion.status = 'ENABLED'
  AND ad_group.status = 'ENABLED'
  AND campaign.status = 'ENABLED'
"""


def _build_client(refresh_token: str, login_customer_id: str | None):
    """Return a GoogleAdsClient using env-supplied credentials."""
    from google.ads.googleads.client import GoogleAdsClient

    cfg = {
        "developer_token": os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN"),
        "client_id": os.getenv("GOOGLE_ADS_CLIENT_ID"),
        "client_secret": os.getenv("GOOGLE_ADS_CLIENT_SECRET"),
        "refresh_token": refresh_token,
        "login_customer_id": login_customer_id,
        "use_proto_plus": True,
    }
    return GoogleAdsClient.load_from_dict(cfg)


def _fetch_keywords(account_id: int) -> Dict[str, List[tuple]]:
    """
    Fetch active keywords for *account_id* via the Google Ads API.

    Returns a dict mapping lowercased keyword text to a list of
    (campaign_id, adgroup_id, match_type) tuples (one per ad group the
    keyword appears in).

    Returns an empty dict if auth is missing or the API call fails.
    """
    from app.models import GoogleAdsAuth

    auth = GoogleAdsAuth.query.filter_by(account_id=account_id).first()
    if not auth:
        logger.warning("overlap_detection: no GoogleAdsAuth for account_id=%s", account_id)
        return {}

    try:
        client = _build_client(auth.refresh_token, auth.manager_customer_id)
        ga_service = client.get_service("GoogleAdsService")
        response = ga_service.search(customer_id=auth.customer_id, query=_GAQL)

        keywords: Dict[str, List[tuple]] = {}
        for row in response:
            kw_text = row.ad_group_criterion.keyword.text.lower()
            match_type = row.ad_group_criterion.keyword.match_type.name  # e.g. "EXACT"
            campaign_id = str(row.campaign.id)
            adgroup_id = str(row.ad_group.id)
            keywords.setdefault(kw_text, []).append((campaign_id, adgroup_id, match_type))

        return keywords

    except Exception as exc:  # noqa: BLE001
        logger.error(
            "overlap_detection: failed to fetch keywords for account_id=%s: %s",
            account_id,
            exc,
        )
        return {}


def detect_overlaps_for_group(group_id: int) -> int:
    """
    Detect keyword overlaps for all account pairs inside *group_id*.

    Queries the Google Ads API for each member account, compares every pair,
    and upserts a KeywordOverlap row for each overlapping keyword.

    Returns the total number of overlaps found (newly inserted + already
    existing rows whose detected_at was refreshed).
    """
    from app import db
    from app.models_multiloc import KeywordOverlap, LocationGroupMember

    members = LocationGroupMember.query.filter_by(group_id=group_id).all()
    if len(members) < 2:
        logger.info("overlap_detection: group_id=%s has fewer than 2 members, skipping", group_id)
        return 0

    # Fetch keywords for every member account (skip accounts that error out)
    account_ids = [m.account_id for m in members]
    kw_by_account: Dict[int, Dict[str, List[tuple]]] = {}
    for acct_id in account_ids:
        kw_by_account[acct_id] = _fetch_keywords(acct_id)

    overlap_count = 0
    now = datetime.utcnow()

    for acct_a, acct_b in combinations(account_ids, 2):
        kws_a = kw_by_account.get(acct_a, {})
        kws_b = kw_by_account.get(acct_b, {})

        shared_keywords = set(kws_a.keys()) & set(kws_b.keys())

        for kw_text in shared_keywords:
            # Use the first occurrence in each account for campaign/adgroup metadata
            campaign_id_a, adgroup_id_a, match_type_a = kws_a[kw_text][0]
            campaign_id_b, adgroup_id_b, match_type_b = kws_b[kw_text][0]
            # Use match_type from account_a (they may differ; log both if needed)
            match_type = match_type_a

            # Upsert: look for an existing row
            existing = KeywordOverlap.query.filter_by(
                group_id=group_id,
                account_id_a=acct_a,
                account_id_b=acct_b,
                keyword_text=kw_text,
                match_type=match_type,
            ).first()

            if existing:
                existing.detected_at = now
                existing.campaign_id_a = campaign_id_a
                existing.adgroup_id_a = adgroup_id_a
                existing.campaign_id_b = campaign_id_b
                existing.adgroup_id_b = adgroup_id_b
            else:
                overlap = KeywordOverlap(
                    group_id=group_id,
                    account_id_a=acct_a,
                    campaign_id_a=campaign_id_a,
                    adgroup_id_a=adgroup_id_a,
                    account_id_b=acct_b,
                    campaign_id_b=campaign_id_b,
                    adgroup_id_b=adgroup_id_b,
                    keyword_text=kw_text,
                    match_type=match_type,
                    detected_at=now,
                )
                db.session.add(overlap)

            overlap_count += 1

    try:
        db.session.commit()
    except Exception as exc:  # noqa: BLE001
        db.session.rollback()
        logger.error("overlap_detection: DB commit failed for group_id=%s: %s", group_id, exc)
        raise

    logger.info(
        "overlap_detection: group_id=%s — %d overlap(s) found across %d account(s)",
        group_id,
        overlap_count,
        len(account_ids),
    )
    return overlap_count


def detect_overlaps_for_all_groups() -> Dict[str, int]:
    """
    Run overlap detection for every LocationGroup.

    Returns a dict mapping group name → overlap count.
    """
    from app.models_multiloc import LocationGroup

    results: Dict[str, int] = {}
    groups = LocationGroup.query.all()

    for group in groups:
        try:
            count = detect_overlaps_for_group(group.id)
            results[group.name] = count
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "overlap_detection: unhandled error for group_id=%s (%s): %s",
                group.id,
                group.name,
                exc,
            )
            results[group.name] = 0

    return results


def get_overlap_summary(group_id: int) -> List[Dict[str, Any]]:
    """
    Return the most recent keyword overlaps for *group_id*.

    Limited to 500 rows, sorted by detected_at descending.
    """
    from app.models_multiloc import KeywordOverlap

    rows = (
        KeywordOverlap.query.filter_by(group_id=group_id)
        .order_by(KeywordOverlap.detected_at.desc())
        .limit(500)
        .all()
    )

    return [
        {
            "keyword_text": r.keyword_text,
            "match_type": r.match_type,
            "account_id_a": r.account_id_a,
            "account_id_b": r.account_id_b,
            "campaign_id_a": r.campaign_id_a,
            "campaign_id_b": r.campaign_id_b,
            "detected_at": r.detected_at,
        }
        for r in rows
    ]
