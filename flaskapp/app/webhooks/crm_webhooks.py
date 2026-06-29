# app/webhooks/crm_webhooks.py
"""
CRM inbound webhook receivers.

Routes
------
POST /api/webhooks/crm/jobber          — Jobber HMAC-SHA256 signed events
POST /api/webhooks/crm/housecall_pro   — HouseCall Pro HMAC-SHA256 signed events
POST /api/webhooks/crm/servicetitan    — ServiceTitan event callback (API key auth)
POST /api/webhooks/crm/manual          — Unauthenticated manual estimate entry (admin only)

HMAC verification
-----------------
Jobber:        X-Jobber-Hmac-SHA256 header, secret = JOBBER_WEBHOOK_SECRET env var
HouseCall Pro: X-HCP-Signature header,      secret = HOUSECALL_WEBHOOK_SECRET env var
ServiceTitan:  X-ST-Signature header,       secret = ST_WEBHOOK_SECRET env var
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
from typing import Optional

from flask import Blueprint, request, jsonify, current_app

from app import db

log = logging.getLogger(__name__)

crm_webhooks_bp = Blueprint("crm_webhooks_bp", __name__, url_prefix="/api/webhooks/crm")


# ---------------------------------------------------------------------------
# HMAC helpers
# ---------------------------------------------------------------------------

def _verify_hmac(secret_env: str, header_name: str, *, algo: str = "sha256") -> bool:
    """Return True if the request HMAC signature matches the body."""
    secret = os.getenv(secret_env, "")
    if not secret:
        log.warning("Webhook secret %s not configured — skipping HMAC check", secret_env)
        return True  # allow through in dev; tighten in prod by returning False

    sig_header = request.headers.get(header_name, "")
    # Strip "sha256=" prefix if present
    sig = sig_header.split("=", 1)[-1]

    expected = hmac.new(
        secret.encode(),
        request.data,
        getattr(hashlib, algo),
    ).hexdigest()

    return hmac.compare_digest(expected, sig)


def _lookup_connection(provider: str, account_id: Optional[int] = None):
    """Find a CRMConnection for the given provider, optionally filtered by account."""
    try:
        from app.models_crm import CRMConnection
        q = CRMConnection.query.filter_by(provider=provider, is_active=True)
        if account_id:
            q = q.filter_by(account_id=account_id)
        return q.first()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Jobber
# ---------------------------------------------------------------------------

@crm_webhooks_bp.route("/jobber", methods=["POST"])
def jobber_webhook():
    if not _verify_hmac("JOBBER_WEBHOOK_SECRET", "X-Jobber-Hmac-SHA256"):
        return jsonify(error="Invalid signature"), 401

    payload = request.get_json(silent=True) or {}
    account_id_str = payload.get("accountId") or payload.get("account_id")

    conn = None
    account_id = None

    # Try to resolve account from Jobber's account ID stored in credentials_json
    try:
        from app.models_crm import CRMConnection
        if account_id_str:
            conn = CRMConnection.query.filter(
                CRMConnection.provider == "jobber",
                CRMConnection.is_active == True,
                CRMConnection.credentials_json["jobber_account_id"].as_string() == str(account_id_str),
            ).first()
        if not conn:
            conn = CRMConnection.query.filter_by(provider="jobber", is_active=True).first()
        if conn:
            account_id = conn.account_id
    except Exception:
        pass

    if not account_id:
        log.warning("jobber webhook: could not resolve account for payload account_id=%s", account_id_str)
        return jsonify(ok=True)  # ack to avoid Jobber retries

    try:
        from app.services.crm_normalizer import handle_jobber_event
        handle_jobber_event(account_id, conn.id if conn else None, payload)
    except Exception:
        log.exception("jobber webhook processing failed")

    return jsonify(ok=True)


# ---------------------------------------------------------------------------
# HouseCall Pro
# ---------------------------------------------------------------------------

@crm_webhooks_bp.route("/housecall_pro", methods=["POST"])
def housecall_webhook():
    if not _verify_hmac("HOUSECALL_WEBHOOK_SECRET", "X-HCP-Signature"):
        return jsonify(error="Invalid signature"), 401

    payload = request.get_json(silent=True) or {}

    # HCP sends a company_id we can match against credentials_json
    company_id = str(payload.get("company_id") or "")
    conn = None
    account_id = None
    try:
        from app.models_crm import CRMConnection
        if company_id:
            conn = CRMConnection.query.filter(
                CRMConnection.provider == "housecall_pro",
                CRMConnection.is_active == True,
                CRMConnection.credentials_json["company_id"].as_string() == company_id,
            ).first()
        if not conn:
            conn = CRMConnection.query.filter_by(provider="housecall_pro", is_active=True).first()
        if conn:
            account_id = conn.account_id
    except Exception:
        pass

    if not account_id:
        log.warning("housecall webhook: could not resolve account company_id=%s", company_id)
        return jsonify(ok=True)

    try:
        from app.services.crm_normalizer import handle_housecall_event
        handle_housecall_event(account_id, conn.id if conn else None, payload)
    except Exception:
        log.exception("housecall webhook processing failed")

    return jsonify(ok=True)


# ---------------------------------------------------------------------------
# ServiceTitan (event callback — ST uses polling primarily, but supports callbacks)
# ---------------------------------------------------------------------------

@crm_webhooks_bp.route("/servicetitan", methods=["POST"])
def servicetitan_webhook():
    if not _verify_hmac("ST_WEBHOOK_SECRET", "X-ST-Signature"):
        return jsonify(error="Invalid signature"), 401

    payload = request.get_json(silent=True) or {}
    tenant_id = str(payload.get("tenantId") or "")

    conn = None
    account_id = None
    try:
        from app.models_crm import CRMConnection
        if tenant_id:
            conn = CRMConnection.query.filter_by(
                provider="servicetitan",
                tenant_id=tenant_id,
                is_active=True,
            ).first()
        if not conn:
            conn = CRMConnection.query.filter_by(provider="servicetitan", is_active=True).first()
        if conn:
            account_id = conn.account_id
    except Exception:
        pass

    if not account_id:
        return jsonify(ok=True)

    # ST sends individual job records in the event data
    job_data = payload.get("data") or payload
    if isinstance(job_data, dict):
        try:
            from app.services.crm_normalizer import handle_servicetitan_job
            handle_servicetitan_job(account_id, conn.id, job_data)
        except Exception:
            log.exception("servicetitan webhook processing failed")

    return jsonify(ok=True)


# ---------------------------------------------------------------------------
# Manual estimate entry (called from the in-app form, session-auth protected)
# ---------------------------------------------------------------------------

@crm_webhooks_bp.route("/manual", methods=["POST"])
def manual_estimate():
    """
    Create a CRMEstimate manually — for accounts without a connected CRM.
    Requires a logged-in session (checked via session cookie, not HMAC).
    """
    from flask import g, session
    from app.auth.decorators import login_required_api

    # Minimal auth: must have a session user
    user_id = session.get("user_id")
    if not user_id:
        return jsonify(error="Unauthorized"), 401

    data = request.get_json(silent=True) or request.form.to_dict()
    account_id = data.get("account_id") or session.get("account_id")
    if not account_id:
        return jsonify(error="account_id required"), 400

    try:
        account_id = int(account_id)
    except (ValueError, TypeError):
        return jsonify(error="Invalid account_id"), 400

    normalized = {
        "external_estimate_id": None,
        "customer_name":  data.get("customer_name"),
        "customer_email": data.get("customer_email"),
        "customer_phone": data.get("customer_phone"),
        "job_type":       data.get("job_type"),
        "amount_cents":   int(float(data.get("amount", 0) or 0) * 100),
        "status":         "sent",
        "sent_at":        __import__("datetime").datetime.utcnow(),
        "source_provider": "manual",
    }

    try:
        from app.services.crm_normalizer import upsert_estimate
        estimate = upsert_estimate(account_id, None, normalized)
        return jsonify(ok=True, estimate_id=estimate.id)
    except Exception as e:
        log.exception("manual estimate creation failed")
        return jsonify(error=str(e)), 500
