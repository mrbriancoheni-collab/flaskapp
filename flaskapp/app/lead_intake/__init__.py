# app/lead_intake/__init__.py
"""
Lead Intake — inbound lead webhooks for Networx, eLocal, and future sources.

Webhook endpoints (CSRF-exempt, signature-validated):
  POST /api/webhooks/networx/lead   — Zapier or Networx Enterprise push
  POST /api/webhooks/elocal/lead    — eLocal data-lead ping/post

Setup UI (authenticated):
  GET  /account/lead-intake/setup   — show webhook URLs + config form
  POST /account/lead-intake/setup   — save LeadIntakeConfig
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
from datetime import datetime
from typing import Optional

from flask import (
    Blueprint, abort, current_app, flash, jsonify, redirect,
    render_template, request, session, url_for,
)
from sqlalchemy import text

from app import db
from app.models_tooling import LeadIngest, LeadIntakeConfig

log = logging.getLogger(__name__)

lead_intake_bp = Blueprint("lead_intake_bp", __name__)


# ── Auth helpers ───────────────────────────────────────────────────────────────

def _current_account_id() -> Optional[int]:
    aid = session.get("account_id") or session.get("aid")
    if aid:
        try:
            return int(aid)
        except Exception:
            pass
    uid = session.get("user_id")
    if not uid:
        return None
    try:
        row = db.session.execute(
            text("SELECT account_id FROM users WHERE id=:id"), {"id": uid}
        ).fetchone()
        return int(row[0]) if row else None
    except Exception:
        return None


def _login_required(f):
    from functools import wraps
    @wraps(f)
    def wrapper(*a, **kw):
        if not _current_account_id():
            return redirect(url_for("auth_bp.login", next=request.path))
        return f(*a, **kw)
    return wrapper


def _get_or_create_config(account_id: int) -> LeadIntakeConfig:
    cfg = LeadIntakeConfig.query.filter_by(account_id=account_id).first()
    if not cfg:
        cfg = LeadIntakeConfig(
            account_id=account_id,
            networx_webhook_secret=secrets.token_hex(24),
        )
        db.session.add(cfg)
        db.session.commit()
    return cfg


# ── Networx webhook ────────────────────────────────────────────────────────────

def _verify_networx_signature(account_id: int, payload: dict) -> bool:
    """
    Verify Zapier / Networx Enterprise HMAC-SHA256 signature if configured.
    When no secret is stored, accept all (suitable for first-time setup).
    """
    cfg = LeadIntakeConfig.query.filter_by(account_id=account_id).first()
    secret = cfg.networx_webhook_secret if cfg else None
    if not secret:
        return True

    sig = request.headers.get("X-Networx-Signature", "")
    if not sig:
        return True  # Zapier doesn't send a sig by default — accept

    expected = hmac.new(
        secret.encode(), request.get_data(), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, sig)


@lead_intake_bp.route("/api/webhooks/networx/lead", methods=["POST"])
def networx_webhook():
    """
    Receive a new Networx lead pushed via Zapier or Enterprise API.

    Expected JSON body (all optional except phone or email):
      {
        "account_id": 123,          -- or resolved from token query param
        "name": "Jane Homeowner",
        "phone": "5125550199",
        "email": "jane@example.com",
        "city": "Austin",
        "service_type": "AC Repair",
        "lead_cost": 45.00,
        "external_id": "NX-789012"
      }
    """
    data = request.get_json(silent=True) or {}

    # Resolve account_id — from payload, query param, or token lookup
    account_id = (
        data.get("account_id")
        or request.args.get("account_id")
        or _account_id_from_token(request.args.get("token"))
    )
    if not account_id:
        log.warning("networx_webhook: could not resolve account_id")
        return jsonify({"ok": False, "error": "account_id required"}), 400

    account_id = int(account_id)

    if not _verify_networx_signature(account_id, data):
        return jsonify({"ok": False, "error": "invalid signature"}), 403

    cfg = LeadIntakeConfig.query.filter_by(account_id=account_id).first()
    lead_cost = data.get("lead_cost") or (float(cfg.networx_default_lead_cost) if cfg and cfg.networx_default_lead_cost else 45.00)

    lead = LeadIngest(
        account_id=account_id,
        source="networx",
        external_id=data.get("external_id"),
        name=data.get("name") or data.get("customer_name"),
        phone=_normalize_phone(data.get("phone")),
        email=data.get("email"),
        city=data.get("city"),
        service_type=data.get("service_type") or data.get("job_type") or data.get("category"),
        lead_cost=lead_cost,
        status="new",
        occurred_at=datetime.utcnow(),
        raw=data,
    )
    db.session.add(lead)
    db.session.commit()

    log.info("Networx lead ingested: account=%s id=%s source=%s", account_id, lead.id, lead.source)

    # Fire missed-call-style immediate SMS follow-up if phone present
    if lead.phone:
        _trigger_lead_followup_sms(account_id, lead)

    return jsonify({"ok": True, "lead_id": lead.id}), 201


# ── eLocal webhook ─────────────────────────────────────────────────────────────

@lead_intake_bp.route("/api/webhooks/elocal/lead", methods=["POST"])
def elocal_webhook():
    """
    Receive an eLocal data-lead (ping/post or direct push).

    eLocal sends JSON POST with TrustedForm and lead details.
    For pay-per-call, call tracking via Twilio is used instead (see telephony).
    """
    data = request.get_json(silent=True) or {}

    account_id = (
        data.get("account_id")
        or request.args.get("account_id")
        or _account_id_from_token(request.args.get("token"))
    )
    if not account_id:
        log.warning("elocal_webhook: could not resolve account_id")
        return jsonify({"ok": False, "error": "account_id required"}), 400

    account_id = int(account_id)
    cfg = LeadIntakeConfig.query.filter_by(account_id=account_id).first()
    lead_cost = data.get("lead_cost") or (float(cfg.elocal_default_lead_cost) if cfg and cfg.elocal_default_lead_cost else 35.00)

    # eLocal field names vary — normalise common variants
    name = (
        data.get("name")
        or data.get("full_name")
        or f"{data.get('first_name', '')} {data.get('last_name', '')}".strip()
        or None
    )

    lead = LeadIngest(
        account_id=account_id,
        source="elocal",
        external_id=data.get("lead_id") or data.get("id"),
        name=name,
        phone=_normalize_phone(data.get("phone") or data.get("phone_number")),
        email=data.get("email") or data.get("email_address"),
        city=data.get("city") or data.get("zip"),
        service_type=data.get("service") or data.get("category") or data.get("job_type"),
        lead_cost=lead_cost,
        status="new",
        occurred_at=datetime.utcnow(),
        raw=data,
    )
    db.session.add(lead)
    db.session.commit()

    log.info("eLocal lead ingested: account=%s id=%s", account_id, lead.id)

    if lead.phone:
        _trigger_lead_followup_sms(account_id, lead)

    return jsonify({"ok": True, "lead_id": lead.id}), 201


# ── Setup UI ───────────────────────────────────────────────────────────────────

@lead_intake_bp.route("/account/lead-intake/setup", methods=["GET", "POST"])
@_login_required
def setup():
    account_id = _current_account_id()
    cfg = _get_or_create_config(account_id)
    base_url = os.getenv("BASE_PUBLIC_URL", "https://app.fieldsprout.io").rstrip("/")

    if request.method == "POST":
        cfg.networx_default_lead_cost = request.form.get("networx_default_lead_cost") or cfg.networx_default_lead_cost
        cfg.elocal_tracking_number = request.form.get("elocal_tracking_number") or cfg.elocal_tracking_number
        cfg.elocal_default_lead_cost = request.form.get("elocal_default_lead_cost") or cfg.elocal_default_lead_cost
        cfg.missed_call_sms_body = request.form.get("missed_call_sms_body") or cfg.missed_call_sms_body
        cfg.review_link_google = request.form.get("review_link_google") or cfg.review_link_google
        cfg.review_link_yelp = request.form.get("review_link_yelp") or cfg.review_link_yelp
        cfg.review_request_sms_template = request.form.get("review_request_sms_template") or cfg.review_request_sms_template

        if request.form.get("rotate_secret"):
            cfg.networx_webhook_secret = secrets.token_hex(24)

        db.session.commit()
        flash("Lead intake settings saved.", "success")
        return redirect(url_for("lead_intake_bp.setup"))

    networx_webhook_url = f"{base_url}/api/webhooks/networx/lead?token={cfg.networx_webhook_secret or ''}"
    elocal_webhook_url = f"{base_url}/api/webhooks/elocal/lead?token={cfg.networx_webhook_secret or ''}"

    return render_template(
        "lead_intake/setup.html",
        cfg=cfg,
        networx_webhook_url=networx_webhook_url,
        elocal_webhook_url=elocal_webhook_url,
    )


@lead_intake_bp.route("/api/lead-intake/rotate-secret", methods=["POST"])
@_login_required
def rotate_secret():
    account_id = _current_account_id()
    cfg = _get_or_create_config(account_id)
    cfg.networx_webhook_secret = secrets.token_hex(24)
    db.session.commit()
    return jsonify({"ok": True, "secret": cfg.networx_webhook_secret})


# ── Lead status update (used by Lead Inbox) ────────────────────────────────────

@lead_intake_bp.route("/api/leads/<int:lead_id>/status", methods=["POST"])
@_login_required
def update_lead_status(lead_id: int):
    account_id = _current_account_id()
    lead = LeadIngest.query.filter_by(id=lead_id, account_id=account_id).first_or_404()
    new_status = request.get_json(silent=True, force=True).get("status", "")

    valid = {"new", "contacted", "booked", "completed", "lost"}
    if new_status not in valid:
        return jsonify({"ok": False, "error": "invalid status"}), 400

    lead.status = new_status
    now = datetime.utcnow()
    if new_status == "contacted" and not lead.contacted_at:
        lead.contacted_at = now
    elif new_status == "booked" and not lead.booked_at:
        lead.booked_at = now
    elif new_status == "completed" and not lead.completed_at:
        lead.completed_at = now
        # Queue a review request when a job is marked complete
        _queue_review_request_for_lead(account_id, lead)

    db.session.commit()
    return jsonify({"ok": True, "status": lead.status})


# ── Helpers ────────────────────────────────────────────────────────────────────

def _normalize_phone(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    digits = "".join(c for c in str(raw) if c.isdigit())
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    return raw


def _account_id_from_token(token: Optional[str]) -> Optional[int]:
    """Resolve account_id from a webhook secret token."""
    if not token:
        return None
    try:
        cfg = LeadIntakeConfig.query.filter_by(networx_webhook_secret=token).first()
        return cfg.account_id if cfg else None
    except Exception:
        return None


def _trigger_lead_followup_sms(account_id: int, lead: LeadIngest) -> None:
    """Send an immediate SMS to the lead (sub-5-min response = 40-50% booking rate)."""
    try:
        cfg = LeadIntakeConfig.query.filter_by(account_id=account_id).first()
        body = (
            (cfg.missed_call_sms_body if cfg else None)
            or os.getenv("LEAD_FOLLOWUP_SMS", "Hi, this is {business} — thanks for reaching out! We'll call you back within a few minutes.")
        )
        _send_sms(lead.phone, body)
    except Exception:
        log.exception("lead followup SMS failed for lead %s", lead.id)


def _send_sms(to: str, body: str) -> None:
    import requests as _req
    sid = os.getenv("TWILIO_ACCOUNT_SID")
    tok = os.getenv("TWILIO_AUTH_TOKEN")
    frm = os.getenv("TWILIO_FROM_NUMBER")
    if not (sid and tok and frm):
        log.info("SMS (simulated) to %s: %s", to, body)
        return
    _req.post(
        f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
        data={"From": frm, "To": to, "Body": body},
        auth=(sid, tok),
        timeout=10,
    )


def _queue_review_request_for_lead(account_id: int, lead: LeadIngest) -> None:
    """Create a queued ReviewRequest when a lead is marked complete."""
    try:
        from app.models_tooling import ReviewRequest
        cfg = LeadIntakeConfig.query.filter_by(account_id=account_id).first()
        if lead.phone:
            db.session.add(ReviewRequest(
                account_id=account_id,
                channel="sms",
                recipient=lead.phone,
                customer_name=lead.name,
                job_type=lead.service_type,
                review_link_google=cfg.review_link_google if cfg else None,
                review_link_yelp=cfg.review_link_yelp if cfg else None,
                status="queued",
            ))
        if lead.email:
            db.session.add(ReviewRequest(
                account_id=account_id,
                channel="email",
                recipient=lead.email,
                customer_name=lead.name,
                job_type=lead.service_type,
                review_link_google=cfg.review_link_google if cfg else None,
                review_link_yelp=cfg.review_link_yelp if cfg else None,
                status="queued",
            ))
        db.session.commit()
        log.info("Queued review request(s) for lead %s account %s", lead.id, account_id)
    except Exception:
        log.exception("Failed to queue review request for lead %s", lead.id)
