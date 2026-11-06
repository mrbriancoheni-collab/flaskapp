# app/account/phone_verification_routes.py
"""
Phone number verification via SMS.

Routes:
  GET  /account/phone/verify      — show the 6-digit entry page
  POST /account/phone/send-code   — send a new verification code
  POST /account/phone/verify      — check the code and mark phone verified
"""
from __future__ import annotations

import logging
import os
import random
from datetime import datetime, timedelta
from typing import Optional

from flask import flash, g, redirect, render_template, request, session, url_for

from app import db
from app.auth.utils import login_required
from app.account import account_bp

logger = logging.getLogger(__name__)

_CODE_SESSION_KEY    = "phone_verify_code"
_EXPIRES_SESSION_KEY = "phone_verify_expires"
_CODE_TTL_MINUTES    = 10


# ── Internal helpers ──────────────────────────────────────────────────────────

def _masked_number(phone: Optional[str]) -> str:
    """Return last 4 digits of a phone number for display."""
    if not phone:
        return "****"
    digits = "".join(ch for ch in phone if ch.isdigit())
    return digits[-4:] if len(digits) >= 4 else digits


def _send_sms(to: str, body: str) -> None:
    """
    Send an SMS via Twilio.  Falls back to log-only when credentials are absent
    (dev / CI environments).
    """
    import requests as _req
    sid = os.getenv("TWILIO_ACCOUNT_SID")
    tok = os.getenv("TWILIO_AUTH_TOKEN")
    frm = os.getenv("TWILIO_FROM_NUMBER")
    if not (sid and tok and frm):
        logger.info("SMS (simulated) to %s: %s", to, body)
        return
    try:
        _req.post(
            f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
            data={"From": frm, "To": to, "Body": body},
            auth=(sid, tok),
            timeout=10,
        )
    except Exception as exc:
        logger.warning("Twilio SMS failed: %s", exc)


def _generate_and_send_code(phone: str) -> None:
    """Generate a 6-digit code, store it in the session, and dispatch it via SMS."""
    code = str(random.randint(100000, 999999))
    expires = (datetime.utcnow() + timedelta(minutes=_CODE_TTL_MINUTES)).isoformat()

    session[_CODE_SESSION_KEY]    = code
    session[_EXPIRES_SESSION_KEY] = expires
    session.modified = True

    _send_sms(
        phone,
        f"Your RevForge verification code is: {code}. Valid for {_CODE_TTL_MINUTES} minutes.",
    )


# ── Routes ────────────────────────────────────────────────────────────────────

@account_bp.route("/phone/verify", methods=["GET"], endpoint="verify_phone")
@login_required
def verify_phone_get():
    user = g.user
    phone = getattr(user, "phone_number", None)
    if not phone:
        flash("Add a phone number to your profile first.", "error")
        return redirect(url_for("account_bp.profile"))

    return render_template(
        "account/verify_phone.html",
        phone_number=_masked_number(phone),
        error=None,
    )


@account_bp.route("/phone/send-code", methods=["POST"], endpoint="phone_send_code")
@login_required
def phone_send_code():
    user = g.user
    phone = getattr(user, "phone_number", None)
    if not phone:
        flash("No phone number on file. Please add one first.", "error")
        return redirect(url_for("account_bp.profile"))

    _generate_and_send_code(phone)
    flash("Verification code sent.", "success")
    return redirect(url_for("account_bp.verify_phone"))


@account_bp.route("/phone/verify", methods=["POST"], endpoint="phone_verify")
@login_required
def phone_verify():
    user = g.user
    phone = getattr(user, "phone_number", None)
    if not phone:
        flash("No phone number on file.", "error")
        return redirect(url_for("account_bp.profile"))

    # Assemble code from either the single 'code' field or six individual digit fields
    submitted = request.form.get("code", "").strip()
    if not submitted:
        submitted = "".join(
            request.form.get(f"digit_{i}", "") for i in range(6)
        ).strip()

    stored_code    = session.get(_CODE_SESSION_KEY)
    stored_expires = session.get(_EXPIRES_SESSION_KEY)

    error: Optional[str] = None

    if not stored_code:
        error = "No code was sent. Please request a new one."

    elif stored_expires:
        try:
            exp_dt = datetime.fromisoformat(stored_expires)
            if datetime.utcnow() > exp_dt:
                error = "Your code has expired. Please request a new one."
        except ValueError:
            error = "Session error. Please request a new code."

    if not error and submitted != stored_code:
        error = "Incorrect code. Please try again."

    if error:
        return render_template(
            "account/verify_phone.html",
            phone_number=_masked_number(phone),
            error=error,
        )

    # Code is correct — mark verified
    try:
        user.phone_verified    = True
        user.phone_verified_at = datetime.utcnow()
        db.session.commit()

        # Clean up session keys
        session.pop(_CODE_SESSION_KEY,    None)
        session.pop(_EXPIRES_SESSION_KEY, None)

        flash("Phone number verified successfully.", "success")
    except Exception as exc:
        logger.exception("phone_verify DB update failed: %s", exc)
        db.session.rollback()
        flash("Verification succeeded but we couldn't save it. Please try again.", "error")

    return redirect(url_for("account_bp.profile"))
