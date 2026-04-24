from __future__ import annotations
import hashlib
import hmac
import base64
import os
from typing import Dict, Any
from flask import Blueprint, request, Response, current_app, g

import requests

telephony_bp = Blueprint("telephony_bp", __name__, url_prefix="/telephony")


# ── Twilio helpers ─────────────────────────────────────────────────────────────

def _twilio_creds() -> Dict[str, str] | None:
    sid      = os.getenv("TWILIO_ACCOUNT_SID")
    tok      = os.getenv("TWILIO_AUTH_TOKEN")
    from_num = os.getenv("TWILIO_FROM_NUMBER")
    if sid and tok and from_num:
        return {"sid": sid, "token": tok, "from": from_num}
    return None


def _twiml(xml: str) -> Response:
    return Response(xml, status=200, mimetype="text/xml")


def _validate_twilio_signature() -> bool:
    """
    Validate the X-Twilio-Signature header to confirm the request is from Twilio.
    Returns True (allow) when:
      - TWILIO_AUTH_TOKEN is not configured (dev mode)
      - Signature is valid
    Returns False (reject) when signature is present but invalid.
    """
    auth_token = os.getenv("TWILIO_AUTH_TOKEN", "")
    if not auth_token:
        return True  # dev mode — no validation

    sig = request.headers.get("X-Twilio-Signature", "")
    if not sig:
        # Twilio always sends the header in production; missing = suspicious
        # Allow in development (no HTTPS) to avoid breaking local testing
        if os.getenv("FLASK_ENV") != "production":
            return True
        return False

    # Build the expected signature: HMAC-SHA1 of url + sorted POST params
    url = request.url
    params = request.form.to_dict()
    sorted_params = "".join(f"{k}{v}" for k, v in sorted(params.items()))
    expected_raw = hmac.new(
        auth_token.encode("utf-8"),
        (url + sorted_params).encode("utf-8"),
        hashlib.sha1,
    ).digest()
    expected = base64.b64encode(expected_raw).decode("utf-8")
    return hmac.compare_digest(expected, sig)


def _account_id_from_to_number(to_number: str) -> int | None:
    """Look up the account that owns this tracking number."""
    try:
        from app.models_calls import CallTrackingNumber
        obj = CallTrackingNumber.query.filter_by(
            phone_number=to_number, is_active=True
        ).first()
        return obj.account_id if obj else None
    except Exception:
        return None


def _fallback_account_id() -> int | None:
    """Return the first active account with Google Ads connected (single-tenant fallback)."""
    try:
        from app import db
        from sqlalchemy import text
        sql = text("""
            SELECT a.id FROM accounts a
            JOIN google_oauth_tokens g ON g.account_id = a.id
            WHERE a.status = 'active'
            ORDER BY a.id LIMIT 1
        """)
        with db.engine.connect() as conn:
            row = conn.execute(sql).first()
        return row.id if row else None
    except Exception:
        return None


# ── Routes ─────────────────────────────────────────────────────────────────────

@telephony_bp.route("/twilio/voice", methods=["POST"])
def twilio_voice():
    """
    Inbound call handler.
    Forwards to TWILIO_FORWARD_TO, sets StatusCallback so completion
    is recorded in the database.
    """
    if not _validate_twilio_signature():
        return Response("Forbidden", status=403)

    forward_to = os.getenv("TWILIO_FORWARD_TO")
    base_url   = os.getenv("BASE_PUBLIC_URL", "").rstrip("/")
    status_cb  = f"{base_url}/telephony/twilio/status"

    if not forward_to:
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say voice="alice">Thanks for calling. Please leave a message after the tone.</Say>
  <Record maxLength="120" playBeep="true" action="{status_cb}" method="POST"/>
</Response>""".format(status_cb=status_cb)
        return _twiml(xml)

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Dial action="{status_cb}" method="POST" timeout="20">
    <Number
      statusCallback="{status_cb}"
      statusCallbackEvent="answered completed no-answer busy failed"
      statusCallbackMethod="POST"
    >{forward_to}</Number>
  </Dial>
  <Say voice="alice">Sorry, we couldn't connect your call. Please try again.</Say>
</Response>"""
    return _twiml(xml)


@telephony_bp.route("/twilio/status", methods=["POST"])
def twilio_status():
    """
    Twilio StatusCallback — fires when a call ends (or for intermediate events).

    1. Validate Twilio signature.
    2. Persist the call as a CallEvent (idempotent on CallSid).
    3. Send missed-call SMS if not answered.
    """
    if not _validate_twilio_signature():
        return Response("Forbidden", status=403)

    payload = request.form.to_dict()
    to_number   = payload.get("To") or payload.get("Called", "")
    call_status = (payload.get("CallStatus") or "").lower()

    current_app.logger.info("Twilio status callback: %s → %s", to_number, call_status)

    # Only persist terminal events (avoid double-writes for ringing/in-progress)
    terminal_statuses = {"completed", "no-answer", "busy", "failed", "canceled"}
    if call_status in terminal_statuses:
        account_id = _account_id_from_to_number(to_number) or _fallback_account_id()
        if account_id:
            try:
                from app.services.call_tracking_service import record_call_event
                event_id = record_call_event(account_id, payload)
                current_app.logger.info("Stored CallEvent id=%s for account %d", event_id, account_id)
            except Exception:
                current_app.logger.exception("Failed to store CallEvent")

    # Missed-call SMS follow-up
    if call_status in ("no-answer", "busy", "failed"):
        _send_missed_call_sms(payload)

    return ("", 200)


def _send_missed_call_sms(payload: Dict[str, Any]) -> None:
    """Send an automated SMS when a call isn't answered."""
    creds     = _twilio_creds()
    to_number = payload.get("From") or payload.get("Caller")
    body      = os.getenv(
        "MISSED_CALL_SMS",
        "Sorry we missed your call — text us here and we'll help right away."
    )

    if creds and to_number:
        try:
            sid, tok, from_num = creds["sid"], creds["token"], creds["from"]
            url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
            requests.post(
                url,
                data={"From": from_num, "To": to_number, "Body": body},
                auth=(sid, tok),
                timeout=10,
            )
        except Exception:
            current_app.logger.exception("Missed-call SMS failed")
    else:
        current_app.logger.info("Simulated missed-call SMS to %s: %s", to_number, body)


# ── API: tracking number management ───────────────────────────────────────────

@telephony_bp.route("/tracking-numbers", methods=["GET"])
def list_tracking_numbers():
    """List tracking numbers for the authenticated account."""
    from flask import jsonify
    from app.auth.utils import current_account_id, login_required

    @login_required
    def _inner():
        from app.models_calls import CallTrackingNumber
        account_id = current_account_id()
        nums = CallTrackingNumber.query.filter_by(
            account_id=account_id, is_active=True
        ).all()
        return jsonify([
            {
                "id": n.id,
                "phone_number": n.phone_number,
                "label": n.label,
                "campaign_id": n.campaign_id,
                "campaign_name": n.campaign_name,
                "qualified_duration_secs": n.qualified_duration_secs,
            }
            for n in nums
        ])
    return _inner()


@telephony_bp.route("/tracking-numbers", methods=["POST"])
def create_tracking_number():
    """Create or update a tracking number → campaign mapping."""
    from flask import jsonify, request as req
    from app.auth.utils import current_account_id, login_required

    @login_required
    def _inner():
        data = req.get_json(silent=True) or {}
        account_id = current_account_id()
        from app.services.call_tracking_service import get_or_create_tracking_number
        obj = get_or_create_tracking_number(
            account_id=account_id,
            phone_number=data.get("phone_number", ""),
            label=data.get("label", ""),
            campaign_id=data.get("campaign_id"),
            campaign_name=data.get("campaign_name"),
            qualified_duration_secs=int(data.get("qualified_duration_secs", 60)),
        )
        return jsonify({"ok": True, "id": obj.id})
    return _inner()


@telephony_bp.route("/call-metrics", methods=["GET"])
def call_metrics_api():
    """Return call metrics JSON for the authenticated account."""
    from flask import jsonify
    from app.auth.utils import current_account_id, login_required

    @login_required
    def _inner():
        from app.services.call_tracking_service import get_call_metrics
        account_id = current_account_id()
        days = int(request.args.get("days", 30))
        return jsonify(get_call_metrics(account_id, days=days))
    return _inner()
