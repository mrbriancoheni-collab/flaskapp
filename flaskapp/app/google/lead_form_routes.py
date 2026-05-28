# app/google/lead_form_routes.py
"""
Google Ads Lead Form Extension webhook routes.

Blueprint: lead_form_bp
Prefix:    /webhooks/google  (+ one login-required page under /account/integrations)
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from flask import (
    Blueprint,
    jsonify,
    render_template,
    request,
)

from app import db
from app.auth.utils import login_required, current_account_id

logger = logging.getLogger(__name__)

lead_form_bp = Blueprint("lead_form_bp", __name__)

# Two logical prefixes are needed:
#   /webhooks/google/lead-form/...   (public, no auth)
#   /account/integrations/lead-forms (login required)
# We achieve this by specifying full paths on every route.

# ---------------------------------------------------------------------------
# EmailGclidMap — imported defensively
# ---------------------------------------------------------------------------
try:
    from app.models_skimmer import EmailGclidMap
    HAS_EMAIL_MAP = True
except ImportError:
    HAS_EMAIL_MAP = False


# ---------------------------------------------------------------------------
# Phone normalisation (same logic as gclid_capture_routes)
# ---------------------------------------------------------------------------
import re as _re

def _normalize_phone(raw: str) -> Optional[str]:
    digits = _re.sub(r"\D", "", raw or "")
    if len(digits) == 10:
        return "+1" + digits
    if len(digits) == 11 and digits.startswith("1"):
        return "+" + digits
    return None


# ---------------------------------------------------------------------------
# Upsert helpers
# ---------------------------------------------------------------------------

def _upsert_phone(account_id: int, phone_e164: str, gclid: str) -> None:
    from app.models_skimmer import PhoneGclidMap
    expires = datetime.utcnow() + timedelta(days=90)
    existing = PhoneGclidMap.query.filter_by(
        account_id=account_id, phone_e164=phone_e164
    ).first()
    if existing:
        existing.gclid = gclid
        existing.expires_at = expires
    else:
        db.session.add(PhoneGclidMap(
            account_id=account_id,
            phone_e164=phone_e164,
            gclid=gclid,
            expires_at=expires,
        ))


def _upsert_email(account_id: int, email: str, gclid: str) -> None:
    if not HAS_EMAIL_MAP:
        return
    expires = datetime.utcnow() + timedelta(days=90)
    existing = EmailGclidMap.query.filter_by(
        account_id=account_id, email=email
    ).first()
    if existing:
        existing.gclid = gclid
        existing.expires_at = expires
    else:
        db.session.add(EmailGclidMap(
            account_id=account_id,
            email=email,
            gclid=gclid,
            expires_at=expires,
        ))


# ---------------------------------------------------------------------------
# GET /webhooks/google/lead-form/<account_id>/verify  — Google endpoint check
# ---------------------------------------------------------------------------

@lead_form_bp.get("/lead-form/<int:account_id>/verify")
def lead_form_verify(account_id: int):
    """Google calls this GET to confirm the webhook endpoint is reachable."""
    return "OK", 200


# ---------------------------------------------------------------------------
# POST /webhooks/google/lead-form/<account_id>  — receive lead
# ---------------------------------------------------------------------------

@lead_form_bp.post("/lead-form/<int:account_id>")
def lead_form_webhook(account_id: int):
    """
    Receive a Google Ads Lead Form Extension webhook payload.

    Extracts email, phone, gclid, and campaign_id.
    Skips test leads. Upserts PhoneGclidMap / EmailGclidMap.
    Creates an OfflineConversionImport row with status="pending".
    """
    try:
        payload = request.get_json(force=True) or {}
    except Exception:
        return jsonify({"error": "Invalid JSON payload"}), 400

    # Skip test submissions
    if payload.get("is_test"):
        logger.info("Skipping test lead form submission for account %s", account_id)
        return jsonify({"ok": True, "skipped": "test"}), 200

    # Extract gclid and campaign
    gclid: Optional[str] = (payload.get("gclid") or "").strip() or None
    campaign_id: Optional[str] = str(payload.get("campaign_id") or "").strip() or None

    # Extract user fields from user_column_data list
    email: Optional[str] = None
    phone_e164: Optional[str] = None
    full_name: Optional[str] = None

    user_columns = payload.get("user_column_data") or []
    for col in user_columns:
        col_name = (col.get("column_name") or "").upper()
        val = (col.get("string_value") or "").strip()
        if not val:
            continue
        if col_name == "EMAIL":
            email = val.lower()
        elif col_name == "PHONE_NUMBER":
            phone_e164 = _normalize_phone(val)
        elif col_name == "FULL_NAME":
            full_name = val

    logger.info(
        "Lead form webhook account=%s gclid=%s email=%s phone=%s campaign=%s",
        account_id, gclid, email, phone_e164, campaign_id,
    )

    # Upsert maps if we have a GCLID to associate
    if gclid:
        try:
            if phone_e164:
                _upsert_phone(account_id, phone_e164, gclid)
            if email:
                _upsert_email(account_id, email, gclid)
        except Exception as exc:
            db.session.rollback()
            logger.exception("lead_form_webhook: map upsert failed account=%s", account_id)
            return jsonify({"error": str(exc)}), 500

    # Create OfflineConversionImport record
    try:
        from app.models_ads import OfflineConversionImport
        oci = OfflineConversionImport(
            account_id=account_id,
            source="google_lead_form",
            external_id=str(payload.get("lead_id") or "").strip() or None,
            gclid=gclid,
            conversion_name="Google Lead Form",
            conversion_time=datetime.utcnow(),
            conversion_value=0.0,
            currency_code="USD",
            status="pending",
        )
        db.session.add(oci)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        logger.exception("lead_form_webhook: OfflineConversionImport failed account=%s", account_id)
        return jsonify({"error": str(exc)}), 500

    return jsonify({"ok": True}), 200


# ---------------------------------------------------------------------------
# GET /account/integrations/lead-forms  — login required dashboard
# This route uses a different prefix so we register it directly on the blueprint
# but with an absolute path via the route decorator.
# ---------------------------------------------------------------------------

# We need a second blueprint prefix anchor — use url_prefix="" workaround by
# defining this route with an absolute path on a companion blueprint.
# Since we cannot change __init__.py, we attach it to lead_form_bp using an
# explicit path override via the `endpoint` kwarg and a full absolute route.

@lead_form_bp.get("/../../account/integrations/lead-forms", endpoint="lead_forms_page")
@login_required
def lead_forms_page():
    """Dashboard: shows webhook URL and recent lead form submissions."""
    from app.models_ads import OfflineConversionImport

    aid = current_account_id()
    webhook_url = (
        request.host_url.rstrip("/")
        + f"/webhooks/google/lead-form/{aid}"
    )

    recent_leads = []
    try:
        recent_leads = (
            OfflineConversionImport.query
            .filter_by(account_id=aid, conversion_name="Google Lead Form")
            .order_by(OfflineConversionImport.created_at.desc())
            .limit(20)
            .all()
        )
    except Exception as exc:
        logger.warning("Could not load recent lead form submissions for account %s: %s", aid, exc)

    return render_template(
        "integrations/lead_forms.html",
        webhook_url=webhook_url,
        recent_leads=recent_leads,
        account_id=aid,
    )
