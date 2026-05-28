# app/services/google_ads_offline_conversions.py
"""
Offline Conversion Import service — CallRail integration.

Handles:
  A. handle_callrail_webhook  — ingest phone call events from CallRail
  B. upload_pending_conversions — push pending rows to Google Ads API
  C. get_import_stats          — dashboard summary stats
  D. validate_callrail_signature — HMAC-SHA256 webhook validation
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone, date, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_DEFAULT_CONVERSION_NAME = "Phone Call Lead"

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _parse_callrail_time(raw: Optional[str]) -> Optional[datetime]:
    """
    Parse CallRail's start_time field.
    Format example: "2024-01-15 14:30:00 -0500"
    Returns a UTC-aware datetime or None.
    """
    if not raw:
        return None
    # Try with offset
    for fmt in (
        "%Y-%m-%d %H:%M:%S %z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S",
    ):
        try:
            parsed = datetime.strptime(raw.strip(), fmt)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            continue
    logger.warning("Could not parse CallRail time %r", raw)
    return None


def _format_gads_datetime(dt_obj: datetime) -> str:
    """
    Format datetime for Google Ads API: 'yyyy-MM-dd HH:mm:ss+00:00'
    """
    utc = dt_obj.astimezone(timezone.utc)
    return utc.strftime("%Y-%m-%d %H:%M:%S+00:00")


def _normalize_phone(phone: str) -> Optional[str]:
    """
    Normalise a raw phone string to E.164 (+1XXXXXXXXXX for US numbers).
    Returns None if the number cannot be normalised.
    """
    import re as _re
    if not phone:
        return None
    digits = _re.sub(r"\D", "", phone)
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits[0] == "1":
        return f"+{digits}"
    return None


# ─────────────────────────────────────────────────────────────────────────────
# A. Handle CallRail Webhook
# ─────────────────────────────────────────────────────────────────────────────

def handle_callrail_webhook(payload: dict, account_id: int) -> dict:
    """
    Ingest a CallRail call event.

    Qualifying criteria:
      - answered == True OR duration >= 30
      - utm_source == "google"
      - gclid present and non-empty

    Returns {"accepted": True, "record_id": N}
          or {"accepted": False, "reason": "..."}
    """
    from app import db
    from app.models_ads import OfflineConversionImport

    # ── Qualification checks ─────────────────────────────────────────────────
    answered = payload.get("answered", False)
    duration = payload.get("duration") or 0
    try:
        duration = int(duration)
    except (TypeError, ValueError):
        duration = 0

    if not answered and duration < 30:
        return {"accepted": False, "reason": "Call not answered and duration < 30s"}

    utm_source = (payload.get("utm_source") or "").lower().strip()
    if utm_source != "google":
        return {"accepted": False, "reason": f"utm_source is '{utm_source}', expected 'google'"}

    gclid = (payload.get("gclid") or "").strip()
    if not gclid:
        return {"accepted": False, "reason": "No gclid in payload"}

    external_id = str(payload.get("id") or "").strip()

    # ── Duplicate check ──────────────────────────────────────────────────────
    if external_id:
        existing = OfflineConversionImport.query.filter_by(
            account_id=account_id,
            external_id=external_id,
        ).first()
        if existing:
            return {"accepted": False, "reason": f"Duplicate: external_id {external_id!r} already exists"}

    # ── Parse conversion time ────────────────────────────────────────────────
    conversion_time = _parse_callrail_time(payload.get("start_time"))

    # ── Conversion value ─────────────────────────────────────────────────────
    raw_value = payload.get("value")
    try:
        conversion_value = float(raw_value) if raw_value is not None else 0.0
    except (TypeError, ValueError):
        conversion_value = 0.0

    # ── Build and persist record ─────────────────────────────────────────────
    record = OfflineConversionImport(
        account_id=account_id,
        source="callrail",
        external_id=external_id or None,
        gclid=gclid,
        conversion_name=_DEFAULT_CONVERSION_NAME,
        conversion_time=conversion_time,
        conversion_value=conversion_value,
        currency_code="USD",
        status="pending",
    )
    db.session.add(record)
    try:
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        logger.exception("DB error saving CallRail webhook for account %s", account_id)
        return {"accepted": False, "reason": f"DB error: {exc}"}

    logger.info("CallRail webhook accepted: record_id=%s gclid=%s account=%s", record.id, gclid, account_id)

    # ── Store phone→GCLID mapping for Skimmer job matching ───────────────────
    customer_phone = (payload.get("customer_phone_number") or payload.get("caller_number") or "").strip()
    if gclid and customer_phone:
        try:
            from app.models_skimmer import PhoneGclidMap
            phone_e164 = _normalize_phone(customer_phone)
            if phone_e164:
                existing_map = PhoneGclidMap.query.filter_by(
                    account_id=account_id, phone_e164=phone_e164
                ).first()
                if existing_map:
                    existing_map.gclid = gclid
                    existing_map.expires_at = datetime.utcnow() + timedelta(days=90)
                else:
                    db.session.add(PhoneGclidMap(
                        account_id=account_id,
                        phone_e164=phone_e164,
                        gclid=gclid,
                        utm_source=payload.get("utm_source"),
                        utm_medium=payload.get("utm_medium"),
                        utm_campaign=payload.get("utm_campaign"),
                        keyword=payload.get("keywords"),
                        expires_at=datetime.utcnow() + timedelta(days=90),
                    ))
                db.session.flush()
                db.session.commit()
        except Exception as _exc:
            logger.warning("Could not upsert PhoneGclidMap for account %s: %s", account_id, _exc)

    return {"accepted": True, "record_id": record.id}


# ─────────────────────────────────────────────────────────────────────────────
# B. Upload pending conversions to Google Ads
# ─────────────────────────────────────────────────────────────────────────────

def upload_pending_conversions(account_id: int) -> dict:
    """
    Push all OfflineConversionImport rows with status='pending' to Google Ads
    via the ConversionUploadService (ClickConversion).

    Returns {"uploaded": N, "failed": N, "errors": [...]}.
    """
    from app import db
    from app.models_ads import OfflineConversionImport, ConversionAction
    from app.google.utils_ads import resolve_ads_context, _get_ads_api_version
    from app.google.token_utils import ensure_access_token

    result: Dict[str, Any] = {"uploaded": 0, "failed": 0, "errors": []}

    # ── Resolve Google Ads credentials ───────────────────────────────────────
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

    # ── Load pending records ─────────────────────────────────────────────────
    pending: List[OfflineConversionImport] = OfflineConversionImport.query.filter_by(
        account_id=account_id,
        status="pending",
    ).all()

    if not pending:
        return result

    # ── Build conversion-action resource-name lookup ─────────────────────────
    # Map name → resource_name (customers/{cid}/conversionActions/{id})
    conv_actions: Dict[str, str] = {}
    for ca in ConversionAction.query.filter_by(account_id=account_id).all():
        if ca.google_conversion_id:
            cid_digits = "".join(c for c in str(customer_id) if c.isdigit())
            resource_name = (
                f"customers/{cid_digits}/conversionActions/{ca.google_conversion_id}"
            )
            conv_actions[ca.name] = resource_name

    # ── Upload each record ───────────────────────────────────────────────────
    import requests

    version = _get_ads_api_version()
    cid_digits = "".join(c for c in str(customer_id) if c.isdigit())
    url = (
        f"https://googleads.googleapis.com/{version}"
        f"/customers/{cid_digits}:uploadClickConversions"
    )

    from app.google.utils_ads import _dev_token
    try:
        dev_token = _dev_token()
    except RuntimeError as exc:
        result["errors"].append(str(exc))
        return result

    headers = {
        "Authorization": f"Bearer {access_token}",
        "developer-token": dev_token,
        "Content-Type": "application/json",
    }
    if login_customer_id:
        login_cid = "".join(c for c in str(login_customer_id) if c.isdigit())
        headers["login-customer-id"] = login_cid

    for record in pending:
        resource_name = conv_actions.get(record.conversion_name)
        if not resource_name:
            # Try to find a close match (case-insensitive)
            name_lower = record.conversion_name.lower()
            for ca_name, ca_rn in conv_actions.items():
                if ca_name.lower() == name_lower:
                    resource_name = ca_rn
                    break

        if not resource_name:
            record.status = "failed"
            record.error_message = (
                f"No ConversionAction found with name '{record.conversion_name}'. "
                "Please sync conversion actions first."
            )
            result["failed"] += 1
            result["errors"].append(record.error_message)
            db.session.flush()
            continue

        if not record.gclid:
            record.status = "failed"
            record.error_message = "Missing gclid"
            result["failed"] += 1
            result["errors"].append(f"Record {record.id}: missing gclid")
            db.session.flush()
            continue

        conversion_time_str = (
            _format_gads_datetime(record.conversion_time)
            if record.conversion_time
            else _format_gads_datetime(datetime.now(timezone.utc))
        )

        payload = {
            "conversions": [
                {
                    "gclid": record.gclid,
                    "conversionAction": resource_name,
                    "conversionDateTime": conversion_time_str,
                    "conversionValue": record.conversion_value or 0.0,
                    "currencyCode": record.currency_code or "USD",
                }
            ],
            "partialFailure": True,
        }

        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=30)
            resp_json = resp.json() if resp.content else {}

            if resp.ok:
                # Check for partial failure errors inside a 200 response
                partial_errors = resp_json.get("partialFailureError")
                if partial_errors:
                    record.status = "failed"
                    record.error_message = json.dumps(partial_errors)
                    record.google_response_json = json.dumps(resp_json)
                    result["failed"] += 1
                    result["errors"].append(f"Record {record.id}: partial failure — {partial_errors}")
                else:
                    record.status = "uploaded"
                    record.google_response_json = json.dumps(resp_json)
                    result["uploaded"] += 1
                    # Update GadsStatsDaily conversion count for that date
                    _credit_stats_daily(account_id, record)
            else:
                error_detail = resp_json.get("error", {}).get("message", resp.text[:500])
                record.status = "failed"
                record.error_message = f"HTTP {resp.status_code}: {error_detail}"
                record.google_response_json = json.dumps(resp_json)
                result["failed"] += 1
                result["errors"].append(f"Record {record.id}: {record.error_message}")

        except Exception as exc:
            record.status = "failed"
            record.error_message = str(exc)
            result["failed"] += 1
            result["errors"].append(f"Record {record.id}: {exc}")
            logger.exception("Upload error for offline conversion record %s", record.id)

        db.session.flush()

    try:
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        logger.exception("DB commit failed after upload_pending_conversions")
        result["errors"].append(f"DB commit error: {exc}")

    return result


def _credit_stats_daily(account_id: int, record) -> None:
    """
    Increment conversions on the GadsStatsDaily campaign row for the same date,
    so our local reporting reflects the imported conversion.
    Best-effort — any failure is logged and swallowed.
    """
    try:
        from app import db
        from app.models_ads import GadsStatsDaily
        if not record.conversion_time:
            return
        conv_date = record.conversion_time.date() if hasattr(record.conversion_time, "date") else None
        if not conv_date:
            return
        # Find the most recent campaign-level stats row for this account on that date
        row = GadsStatsDaily.query.filter_by(
            account_id=account_id,
            entity_type="campaign",
            date=conv_date,
        ).first()
        if row:
            row.conversions = (row.conversions or 0.0) + 1.0
            row.conversion_value = (row.conversion_value or 0.0) + (record.conversion_value or 0.0)
            db.session.flush()
    except Exception as exc:
        logger.warning("_credit_stats_daily failed: %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# C. Import stats for dashboard
# ─────────────────────────────────────────────────────────────────────────────

def get_import_stats(account_id: int) -> dict:
    """
    Returns summary statistics for the offline conversion import UI.
    """
    from app.models_ads import OfflineConversionImport
    from sqlalchemy import func
    from app import db

    today = date.today()
    first_of_month = today.replace(day=1)
    first_of_last_month = (first_of_month - timedelta(days=1)).replace(day=1)

    base_q = OfflineConversionImport.query.filter_by(account_id=account_id)

    total_imports = base_q.count()
    pending_count = base_q.filter_by(status="pending").count()
    uploaded_count = base_q.filter_by(status="uploaded").count()
    failed_count = base_q.filter_by(status="failed").count()

    # Last upload timestamp
    last_uploaded = (
        OfflineConversionImport.query
        .filter_by(account_id=account_id, status="uploaded")
        .order_by(OfflineConversionImport.updated_at.desc())
        .first()
    )
    last_upload_at = last_uploaded.updated_at.isoformat() if last_uploaded else None

    # Total conversion value from uploaded records
    total_conversion_value = (
        db.session.query(func.coalesce(func.sum(OfflineConversionImport.conversion_value), 0.0))
        .filter(
            OfflineConversionImport.account_id == account_id,
            OfflineConversionImport.status == "uploaded",
        )
        .scalar()
    ) or 0.0

    # Calls this month (by created_at)
    calls_this_month = (
        OfflineConversionImport.query
        .filter(
            OfflineConversionImport.account_id == account_id,
            OfflineConversionImport.created_at >= datetime(first_of_month.year, first_of_month.month, 1),
        )
        .count()
    )

    # Calls last month
    calls_last_month = (
        OfflineConversionImport.query
        .filter(
            OfflineConversionImport.account_id == account_id,
            OfflineConversionImport.created_at >= datetime(
                first_of_last_month.year, first_of_last_month.month, 1
            ),
            OfflineConversionImport.created_at < datetime(first_of_month.year, first_of_month.month, 1),
        )
        .count()
    )

    # Most common conversion name
    name_row = (
        db.session.query(
            OfflineConversionImport.conversion_name,
            func.count(OfflineConversionImport.id).label("cnt"),
        )
        .filter_by(account_id=account_id)
        .group_by(OfflineConversionImport.conversion_name)
        .order_by(func.count(OfflineConversionImport.id).desc())
        .first()
    )
    most_common_conversion_name = name_row[0] if name_row else None

    return {
        "total_imports": total_imports,
        "pending_count": pending_count,
        "uploaded_count": uploaded_count,
        "failed_count": failed_count,
        "last_upload_at": last_upload_at,
        "total_conversion_value": float(total_conversion_value),
        "calls_this_month": calls_this_month,
        "calls_last_month": calls_last_month,
        "most_common_conversion_name": most_common_conversion_name,
    }


# ─────────────────────────────────────────────────────────────────────────────
# D. Validate CallRail webhook signature
# ─────────────────────────────────────────────────────────────────────────────

def validate_callrail_signature(
    payload_body: bytes,
    signature: str,
    webhook_secret: str,
) -> bool:
    """
    Validate the X-CallRail-Signature header.
    CallRail signs the raw request body with HMAC-SHA256 using the webhook secret.
    The header value is a hex digest.
    """
    if not signature or not webhook_secret:
        return False
    expected = hmac.new(
        webhook_secret.encode("utf-8"),
        payload_body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature.lower().strip())
