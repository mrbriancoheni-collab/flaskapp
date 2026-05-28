# app/services/google_ads_call_view_sync.py
"""
Google Ads Call View Sync.
Pulls call extension data from Google Ads API and stores caller phone → GCLID
mappings in PhoneGclidMap for Skimmer job attribution without CallRail.

Because Google Ads Call View exposes only caller area code + country code in the
basic `call_view` resource, this service first attempts `call_detail_view` which
can expose the full caller phone number when call recording / call reporting is
enabled.  If the full number is unavailable, the call is logged but skipped for
phone storage.

Synthetic GCLID key format stored in PhoneGclidMap:
    "CALL_VIEW:{google_campaign_id}:{call_date}"

When SkimmerJob matching resolves a job via one of these synthetic keys the
match_method is recorded as "call_view".  Google Ads offline conversion uploads
for call-view matches should use uploadCallConversions (not uploadClickConversions)
because there is no real GCLID available.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_CALL_DETAIL_GAQL = """
SELECT
  call_detail_view.call_tracking_display_type,
  call_detail_view.type,
  call_detail_view.status,
  call_detail_view.duration_seconds,
  call_detail_view.start_call_date_time,
  call_detail_view.caller_phone_number,
  call_detail_view.resource_name,
  campaign.id,
  campaign.name,
  segments.ad_network_type,
  segments.date
FROM call_detail_view
WHERE segments.date DURING LAST_30_DAYS
  AND call_detail_view.status = 'RECEIVED'
  AND call_detail_view.duration_seconds >= 30
"""

_CALL_VIEW_FALLBACK_GAQL = """
SELECT
  call_view.caller_area_code,
  call_view.caller_country_code,
  call_view.start_call_date_time,
  call_view.end_call_date_time,
  call_view.duration_seconds,
  call_view.status,
  call_view.type,
  call_view.resource_name,
  campaign.id,
  campaign.name,
  segments.date
FROM call_view
WHERE segments.date DURING LAST_30_DAYS
  AND call_view.status = 'RECEIVED'
  AND call_view.duration_seconds >= 30
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize_phone(phone: str) -> Optional[str]:
    """
    Normalise a raw phone string to E.164 (+1XXXXXXXXXX for US numbers).
    Returns None if the number cannot be normalised.
    """
    if not phone:
        return None
    digits = re.sub(r"\D", "", phone)
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits[0] == "1":
        return f"+{digits}"
    return None


def _synthetic_gclid(campaign_id: Any, call_date: str) -> str:
    """Build a synthetic GCLID-like key for call-view entries stored in PhoneGclidMap."""
    return f"CALL_VIEW:{campaign_id}:{call_date}"


# ---------------------------------------------------------------------------
# Main sync function
# ---------------------------------------------------------------------------

def sync_call_view(account_id: int, days: int = 30) -> Dict[str, Any]:
    """
    Pull Google Ads Call View / Call Detail View data for one account and
    upsert caller phone numbers into PhoneGclidMap with synthetic GCLID keys.

    Returns:
        {
            "synced": <total call rows examined>,
            "phones_stored": <PhoneGclidMap rows upserted>,
            "skipped_no_number": <rows with no usable phone number>,
            "errors": [<error strings>],
        }
    """
    from flask import current_app
    from app import db
    from app.google.utils_ads import resolve_ads_context, google_ads_search
    from app.google.token_utils import ensure_access_token
    from app.models_skimmer import PhoneGclidMap

    PhoneGclidMap.ensure_columns()

    result: Dict[str, Any] = {
        "synced": 0,
        "phones_stored": 0,
        "skipped_no_number": 0,
        "errors": [],
    }

    # ── Resolve credentials ──────────────────────────────────────────────────
    try:
        ctx = resolve_ads_context(account_id)
        customer_id = ctx.get("customer_id")
        login_customer_id = ctx.get("login_customer_id")
        if not customer_id:
            result["errors"].append("No Google Ads customer_id configured for account.")
            return result

        access_token, _ = ensure_access_token(account_id, ("ads", "lsa"))
    except Exception as exc:
        result["errors"].append(f"Credential error: {exc}")
        return result

    def _search(query: str) -> List[dict]:
        return google_ads_search(
            access_token=access_token,
            customer_id=customer_id,
            query=query,
            login_customer_id=login_customer_id,
            stream=True,
        )

    # ── Attempt call_detail_view first (has full caller phone when available) ─
    rows: List[dict] = []
    using_detail_view = True
    try:
        rows = _search(_CALL_DETAIL_GAQL)
        logger.info("call_detail_view returned %d rows for account %s", len(rows), account_id)
    except Exception as exc:
        logger.warning(
            "call_detail_view query failed for account %s, falling back to call_view: %s",
            account_id, exc,
        )
        using_detail_view = False
        try:
            rows = _search(_CALL_VIEW_FALLBACK_GAQL)
            logger.info("call_view fallback returned %d rows for account %s", len(rows), account_id)
        except Exception as exc2:
            result["errors"].append(f"Both call_detail_view and call_view queries failed: {exc2}")
            return result

    # ── Process rows ─────────────────────────────────────────────────────────
    now = datetime.utcnow()

    for row in rows:
        result["synced"] += 1
        try:
            campaign = row.get("campaign", {})
            seg = row.get("segments", {})
            campaign_id = campaign.get("id") or "unknown"
            campaign_name = campaign.get("name") or f"Campaign {campaign_id}"
            call_date = seg.get("date") or now.strftime("%Y-%m-%d")

            if using_detail_view:
                call_detail = row.get("callDetailView", {})
                raw_phone = call_detail.get("callerPhoneNumber") or ""
            else:
                # Fallback: call_view only exposes area code — not a full number.
                call_view_data = row.get("callView", {})
                area_code = call_view_data.get("callerAreaCode") or ""
                country_code = call_view_data.get("callerCountryCode") or "US"
                raw_phone = ""  # Cannot reconstruct full number from area code alone
                if area_code:
                    logger.debug(
                        "call_view fallback: area_code=%s country=%s campaign=%s date=%s — "
                        "full number unavailable, skipping phone storage",
                        area_code, country_code, campaign_id, call_date,
                    )

            phone_e164 = _normalize_phone(raw_phone)
            if not phone_e164:
                result["skipped_no_number"] += 1
                continue

            synthetic_key = _synthetic_gclid(campaign_id, call_date)

            # Upsert into PhoneGclidMap (insert or update if phone already known)
            try:
                existing = PhoneGclidMap.query.filter_by(
                    account_id=account_id,
                    phone_e164=phone_e164,
                ).first()

                if existing is None:
                    mapping = PhoneGclidMap(
                        account_id=account_id,
                        phone_e164=phone_e164,
                        gclid=synthetic_key,
                        utm_source="google",
                        utm_medium="cpc",
                        utm_campaign=campaign_name,
                    )
                    db.session.add(mapping)
                else:
                    # Only overwrite with a call_view key if there is no real GCLID already.
                    # Real GCLIDs never start with "CALL_VIEW:", so preserve them.
                    if existing.gclid.startswith("CALL_VIEW:"):
                        existing.gclid = synthetic_key
                        existing.utm_campaign = campaign_name

                result["phones_stored"] += 1
                logger.debug(
                    "Stored call_view phone %s → %s for account %s",
                    phone_e164, synthetic_key, account_id,
                )
            except Exception as exc:
                logger.warning(
                    "Failed to upsert PhoneGclidMap for phone %s account %s: %s",
                    phone_e164, account_id, exc,
                )
                result["errors"].append(f"DB upsert error for phone {phone_e164}: {exc}")

        except Exception as exc:
            logger.warning("Error processing call_view row for account %s: %s", account_id, exc)
            result["errors"].append(f"Row processing error: {exc}")

    # ── Commit ────────────────────────────────────────────────────────────────
    try:
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        logger.exception("DB commit failed in sync_call_view account %s", account_id)
        result["errors"].append(f"DB commit error: {exc}")

    logger.info(
        "sync_call_view account=%s synced=%d phones_stored=%d skipped_no_number=%d errors=%d",
        account_id,
        result["synced"],
        result["phones_stored"],
        result["skipped_no_number"],
        len(result["errors"]),
    )
    return result
