# app/webhooks/marketing_webhooks.py
"""
Marketing channel webhook receivers.

Routes
------
POST /api/webhooks/twilio/call      — Twilio Voice status callback
POST /api/webhooks/angi             — Angi/HomeAdvisor lead push
POST /api/webhooks/thumbtack        — Thumbtack lead push
POST /api/webhooks/nextdoor         — Nextdoor lead/click notification
POST /api/webhooks/generic-lead     — Generic lead intake (JSON or form)
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from flask import Blueprint, request, jsonify, current_app

from app import db
from app.models_calls import CallEvent, CallTrackingNumber
from app.models_tooling import LeadIngest

# Optional marketing models — may not be migrated yet
try:
    from app.models_marketing import AggregatorAccount, AggregatorLead
    _marketing_models_available = True
except Exception:  # pragma: no cover
    _marketing_models_available = False
    AggregatorAccount = None  # type: ignore[assignment,misc]
    AggregatorLead = None     # type: ignore[assignment,misc]

# Optional LeadAttribution — also lives in models_marketing
try:
    from app.models_marketing import LeadAttribution  # type: ignore[attr-defined]
    _lead_attribution_available = True
except Exception:
    _lead_attribution_available = False
    LeadAttribution = None  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)

marketing_webhooks_bp = Blueprint(
    "marketing_webhooks_bp",
    __name__,
    url_prefix="/api/webhooks",
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DEFAULT_QUALIFIED_SECS = 60


def _normalize_e164(phone: Optional[str]) -> Optional[str]:
    """Best-effort normalization to E.164 format (+1XXXXXXXXXX for US numbers)."""
    if not phone:
        return phone
    digits = "".join(ch for ch in phone if ch.isdigit())
    if phone.startswith("+"):
        return "+" + digits
    if len(digits) == 10:
        return "+1" + digits
    if len(digits) == 11 and digits.startswith("1"):
        return "+" + digits
    # Return as-is if we can't confidently normalize
    return phone


def _upsert_aggregator_lead(
    *,
    platform: str,
    external_lead_id: Optional[str],
    account_id: Optional[int],
    aggregator_account_id: Optional[int],
    name: Optional[str],
    phone: Optional[str],
    email: Optional[str],
    service_requested: Optional[str],
    city: Optional[str],
    zip_code: Optional[str],
    lead_cost_cents: Optional[int],
    status: str = "new",
    raw_data: Optional[dict] = None,
) -> Optional[object]:
    """
    Insert or update an AggregatorLead record.
    Returns the lead object or None if marketing models are not available.
    """
    if not _marketing_models_available:
        current_app.logger.warning(
            "AggregatorLead model not available — skipping lead persist for platform=%s", platform
        )
        return None

    lead = None
    if external_lead_id:
        lead = AggregatorLead.query.filter_by(
            platform=platform, external_lead_id=str(external_lead_id)
        ).first()

    if lead is None:
        lead = AggregatorLead()
        db.session.add(lead)

    lead.platform = platform
    lead.external_lead_id = str(external_lead_id) if external_lead_id else None
    if account_id is not None:
        lead.account_id = account_id
    if aggregator_account_id is not None:
        lead.aggregator_account_id = aggregator_account_id
    lead.name = name
    lead.phone = phone
    lead.email = email
    lead.service_requested = service_requested
    lead.city = city
    lead.zip_code = zip_code
    if lead_cost_cents is not None:
        lead.lead_cost_cents = lead_cost_cents
    lead.status = status
    if raw_data is not None:
        lead.raw_data = raw_data
    if not lead.occurred_at:
        lead.occurred_at = datetime.utcnow()

    db.session.commit()
    return lead


def _lookup_aggregator_account(platform: str, secret: str) -> Optional[object]:
    """
    Return the first AggregatorAccount matching platform + webhook_secret.
    Returns None if models aren't available or no match found.
    """
    if not _marketing_models_available:
        return None
    return AggregatorAccount.query.filter_by(
        platform=platform, webhook_secret=secret, is_active=True
    ).first()


# ---------------------------------------------------------------------------
# Route 1 — Twilio Voice webhook
# ---------------------------------------------------------------------------

@marketing_webhooks_bp.route("/twilio/call", methods=["POST"])
def twilio_call_webhook():
    """
    Twilio Voice status callback.

    Twilio POSTs application/x-www-form-urlencoded data on every call-status
    change (initiated, ringing, in-progress, completed, busy, no-answer, failed).
    """
    try:
        data = request.form.to_dict()
        current_app.logger.info(
            "Twilio call webhook received: CallSid=%s Status=%s",
            data.get("CallSid"),
            data.get("CallStatus"),
        )

        call_sid = data.get("CallSid", "").strip()
        caller_phone = data.get("From", "").strip() or None
        tracking_phone_raw = data.get("To", "").strip() or None
        call_status = data.get("CallStatus", "").strip() or None
        parent_call_sid = data.get("ParentCallSid", "").strip() or None

        duration_raw = data.get("CallDuration", "").strip()
        duration_secs: Optional[int] = int(duration_raw) if duration_raw.isdigit() else None

        caller_city = data.get("CallerCity") or data.get("FromCity") or None
        caller_state = data.get("CallerState") or data.get("FromState") or None
        caller_zip = data.get("CallerZip") or data.get("FromZip") or None

        if not call_sid:
            current_app.logger.warning("Twilio webhook missing CallSid — ignoring")
            return _twiml_response(), 200

        tracking_phone = _normalize_e164(tracking_phone_raw)

        # Look up the tracking number
        tracking_number: Optional[CallTrackingNumber] = None
        if tracking_phone:
            tracking_number = CallTrackingNumber.query.filter_by(
                phone_number=tracking_phone, is_active=True
            ).first()
            if not tracking_number:
                # Try without is_active filter as fallback
                tracking_number = CallTrackingNumber.query.filter_by(
                    phone_number=tracking_phone
                ).first()

        account_id: Optional[int] = tracking_number.account_id if tracking_number else None

        # Determine qualification threshold
        qual_threshold = _DEFAULT_QUALIFIED_SECS
        if tracking_number and tracking_number.qualified_duration_secs:
            qual_threshold = tracking_number.qualified_duration_secs

        is_qualified = bool(duration_secs is not None and duration_secs >= qual_threshold)

        # Upsert CallEvent by call_sid
        event: Optional[CallEvent] = CallEvent.query.filter_by(call_sid=call_sid).first()
        is_new = event is None
        if is_new:
            event = CallEvent(call_sid=call_sid)
            db.session.add(event)

        # account_id must be non-null per model; use 0 as sentinel when unknown
        if account_id is not None:
            event.account_id = account_id
        elif is_new:
            event.account_id = 0  # will be updated once we know the account

        event.parent_call_sid = parent_call_sid
        event.from_number = _normalize_e164(caller_phone)
        event.to_number = tracking_phone
        if tracking_number:
            event.tracking_number_id = tracking_number.id
            event.campaign_id = tracking_number.campaign_id
            event.campaign_name = tracking_number.campaign_name
        if call_status:
            event.call_status = call_status
        if duration_secs is not None:
            event.call_duration = duration_secs
            event.is_qualified_lead = is_qualified
        if caller_city:
            event.caller_city = caller_city
        if caller_state:
            event.caller_state = caller_state
        if caller_zip:
            event.caller_zip = caller_zip
        if is_new:
            event.call_started_at = datetime.utcnow()
        if call_status == "completed" and not event.call_ended_at:
            event.call_ended_at = datetime.utcnow()

        event.raw_payload = data

        db.session.commit()

        # Phone-number attribution for completed calls
        if call_status == "completed" and event.id and caller_phone and _lead_attribution_available:
            try:
                normalized_caller = _normalize_e164(caller_phone)
                attribution = LeadAttribution.query.filter_by(  # type: ignore[union-attr]
                    phone=normalized_caller
                ).filter(
                    LeadAttribution.call_event_id.is_(None)  # type: ignore[union-attr]
                ).first()
                if attribution:
                    attribution.call_event_id = event.id
                    db.session.commit()
                    current_app.logger.info(
                        "Phone attribution updated: LeadAttribution id=%s → CallEvent id=%s",
                        attribution.id, event.id,
                    )
            except Exception as attr_err:
                current_app.logger.warning("Phone attribution lookup failed: %s", attr_err)

        current_app.logger.info(
            "CallEvent upserted: call_sid=%s account_id=%s status=%s duration=%s qualified=%s",
            call_sid, account_id, call_status, duration_secs, is_qualified,
        )

        return _twiml_response(), 200, {"Content-Type": "text/xml"}

    except Exception as exc:
        current_app.logger.exception("Unhandled error in twilio_call_webhook: %s", exc)
        # Still return valid TwiML so Twilio doesn't retry indefinitely
        return _twiml_response(), 500, {"Content-Type": "text/xml"}


def _twiml_response() -> str:
    return '<?xml version="1.0" encoding="UTF-8"?><Response><Say>Thank you for calling!</Say></Response>'


# ---------------------------------------------------------------------------
# Route 2 — Angi / HomeAdvisor webhook
# ---------------------------------------------------------------------------

@marketing_webhooks_bp.route("/angi", methods=["POST"])
def angi_webhook():
    """
    Angi/HomeAdvisor inbound lead webhook.

    Authentication: X-Angi-Secret header must match an active AggregatorAccount
    with platform='angi'.
    """
    try:
        secret = request.headers.get("X-Angi-Secret", "").strip()
        if not secret:
            current_app.logger.warning("Angi webhook: missing X-Angi-Secret header")
            return jsonify({"error": "unauthorized"}), 401

        agg_account = _lookup_aggregator_account("angi", secret)
        if agg_account is None:
            current_app.logger.warning("Angi webhook: no matching AggregatorAccount for secret")
            return jsonify({"error": "unauthorized"}), 401

        body = request.get_json(force=True, silent=True) or {}
        current_app.logger.info(
            "Angi webhook received: external_id=%s account_id=%s",
            body.get("id"),
            agg_account.account_id,
        )

        external_lead_id = body.get("id")
        contact = body.get("contact") or {}
        location = body.get("location") or {}

        first_name = (contact.get("first_name") or "").strip()
        last_name = (contact.get("last_name") or "").strip()
        name = " ".join(filter(None, [first_name, last_name])) or None

        phone = _normalize_e164(contact.get("phone"))
        email = contact.get("email")
        service_requested = body.get("service_requested")
        city = location.get("city")
        zip_code = location.get("postal_code")

        # lead_price is in dollars; store as cents
        lead_price_raw = body.get("lead_price")
        lead_cost_cents: Optional[int] = None
        if lead_price_raw is not None:
            try:
                lead_cost_cents = int(float(lead_price_raw) * 100)
            except (TypeError, ValueError):
                pass

        lead = _upsert_aggregator_lead(
            platform="angi",
            external_lead_id=external_lead_id,
            account_id=agg_account.account_id,
            aggregator_account_id=agg_account.id,
            name=name,
            phone=phone,
            email=email,
            service_requested=service_requested,
            city=city,
            zip_code=zip_code,
            lead_cost_cents=lead_cost_cents,
            raw_data=body,
        )

        current_app.logger.info(
            "Angi lead upserted: external_id=%s lead_id=%s",
            external_lead_id,
            lead.id if lead else None,
        )
        return jsonify({"status": "ok"}), 200

    except Exception as exc:
        current_app.logger.exception("Unhandled error in angi_webhook: %s", exc)
        return jsonify({"error": "internal_server_error"}), 500


# ---------------------------------------------------------------------------
# Route 3 — Thumbtack webhook
# ---------------------------------------------------------------------------

@marketing_webhooks_bp.route("/thumbtack", methods=["POST"])
def thumbtack_webhook():
    """
    Thumbtack inbound lead webhook.

    Authentication: X-Thumbtack-Secret header must match an active
    AggregatorAccount with platform='thumbtack'.
    """
    try:
        secret = request.headers.get("X-Thumbtack-Secret", "").strip()
        if not secret:
            current_app.logger.warning("Thumbtack webhook: missing X-Thumbtack-Secret header")
            return jsonify({"error": "unauthorized"}), 401

        agg_account = _lookup_aggregator_account("thumbtack", secret)
        if agg_account is None:
            current_app.logger.warning("Thumbtack webhook: no matching AggregatorAccount for secret")
            return jsonify({"error": "unauthorized"}), 401

        body = request.get_json(force=True, silent=True) or {}
        current_app.logger.info(
            "Thumbtack webhook received: leadId=%s account_id=%s",
            body.get("leadId"),
            agg_account.account_id,
        )

        external_lead_id = body.get("leadId")
        customer = body.get("customer") or {}
        location = body.get("location") or {}

        name = customer.get("name")
        phone = _normalize_e164(customer.get("phone"))
        email = customer.get("email")
        service_requested = body.get("category")
        city = location.get("city")
        zip_code = location.get("zipCode")

        # leadPrice is in dollars
        lead_price_raw = body.get("leadPrice")
        lead_cost_cents: Optional[int] = None
        if lead_price_raw is not None:
            try:
                lead_cost_cents = int(float(lead_price_raw) * 100)
            except (TypeError, ValueError):
                pass

        lead = _upsert_aggregator_lead(
            platform="thumbtack",
            external_lead_id=external_lead_id,
            account_id=agg_account.account_id,
            aggregator_account_id=agg_account.id,
            name=name,
            phone=phone,
            email=email,
            service_requested=service_requested,
            city=city,
            zip_code=zip_code,
            lead_cost_cents=lead_cost_cents,
            raw_data=body,
        )

        current_app.logger.info(
            "Thumbtack lead upserted: leadId=%s lead_id=%s",
            external_lead_id,
            lead.id if lead else None,
        )
        return jsonify({"status": "ok"}), 200

    except Exception as exc:
        current_app.logger.exception("Unhandled error in thumbtack_webhook: %s", exc)
        return jsonify({"error": "internal_server_error"}), 500


# ---------------------------------------------------------------------------
# Route 4 — Nextdoor webhook
# ---------------------------------------------------------------------------

@marketing_webhooks_bp.route("/nextdoor", methods=["POST"])
def nextdoor_webhook():
    """
    Nextdoor lead/click notification.

    No authentication for now — Nextdoor does not yet have a standardized
    webhook signature mechanism.
    """
    try:
        body = request.get_json(force=True, silent=True) or {}
        current_app.logger.info(
            "Nextdoor webhook received: lead_id=%s", body.get("lead_id")
        )

        external_lead_id = body.get("lead_id")
        name = body.get("name")
        phone = _normalize_e164(body.get("phone"))
        email = body.get("email")
        service_requested = body.get("service")
        city = body.get("city")

        # account_id not provided by Nextdoor; left as None for now
        lead = _upsert_aggregator_lead(
            platform="nextdoor",
            external_lead_id=external_lead_id,
            account_id=None,
            aggregator_account_id=None,
            name=name,
            phone=phone,
            email=email,
            service_requested=service_requested,
            city=city,
            zip_code=None,
            lead_cost_cents=None,
            raw_data=body,
        )

        current_app.logger.info(
            "Nextdoor lead upserted: lead_id=%s db_id=%s",
            external_lead_id,
            lead.id if lead else None,
        )
        return jsonify({"status": "ok"}), 200

    except Exception as exc:
        current_app.logger.exception("Unhandled error in nextdoor_webhook: %s", exc)
        return jsonify({"error": "internal_server_error"}), 500


# ---------------------------------------------------------------------------
# Route 5 — Generic lead intake
# ---------------------------------------------------------------------------

@marketing_webhooks_bp.route("/generic-lead", methods=["POST"])
def generic_lead_webhook():
    """
    Generic lead intake endpoint.  Accepts JSON or form-encoded data.

    Query parameters
    ----------------
    account_id  : int   (required) — target account
    source      : str   (optional, default "unknown") — e.g. "direct_mail"
    channel_id  : int   (optional) — used to create a LeadAttribution entry
    """
    try:
        account_id_raw = request.args.get("account_id", "").strip()
        source = request.args.get("source", "unknown").strip() or "unknown"
        channel_id_raw = request.args.get("channel_id", "").strip()

        if not account_id_raw:
            return jsonify({"error": "account_id query parameter is required"}), 400

        try:
            account_id = int(account_id_raw)
        except ValueError:
            return jsonify({"error": "account_id must be an integer"}), 400

        channel_id: Optional[int] = None
        if channel_id_raw:
            try:
                channel_id = int(channel_id_raw)
            except ValueError:
                pass  # invalid channel_id — ignore gracefully

        # Accept JSON or form data
        if request.is_json:
            body = request.get_json(force=True, silent=True) or {}
        else:
            body = request.form.to_dict()

        current_app.logger.info(
            "Generic lead webhook received: account_id=%s source=%s channel_id=%s",
            account_id, source, channel_id,
        )

        external_id = (
            body.get("id")
            or body.get("external_id")
            or body.get("lead_id")
            or None
        )
        name = body.get("name") or body.get("full_name") or None
        phone = _normalize_e164(body.get("phone") or body.get("phone_number") or None)
        email = body.get("email") or None
        city = body.get("city") or None
        occurred_at_raw = body.get("occurred_at") or body.get("created_at") or None

        occurred_at: Optional[datetime] = None
        if occurred_at_raw:
            try:
                occurred_at = datetime.fromisoformat(str(occurred_at_raw).replace("Z", "+00:00"))
            except (ValueError, TypeError):
                pass

        # Upsert LeadIngest
        lead_ingest: Optional[LeadIngest] = None
        if external_id:
            lead_ingest = LeadIngest.query.filter_by(
                account_id=account_id,
                source=source,
                external_id=str(external_id),
            ).first()

        is_new_ingest = lead_ingest is None
        if is_new_ingest:
            lead_ingest = LeadIngest(account_id=account_id, source=source)
            db.session.add(lead_ingest)

        lead_ingest.external_id = str(external_id) if external_id else lead_ingest.external_id
        lead_ingest.name = name or lead_ingest.name
        lead_ingest.phone = phone or lead_ingest.phone
        lead_ingest.email = email or lead_ingest.email
        lead_ingest.city = city or lead_ingest.city
        lead_ingest.occurred_at = occurred_at or lead_ingest.occurred_at or datetime.utcnow()
        lead_ingest.raw = body

        db.session.commit()

        current_app.logger.info(
            "LeadIngest upserted: id=%s account_id=%s source=%s new=%s",
            lead_ingest.id, account_id, source, is_new_ingest,
        )

        # Optional LeadAttribution entry when channel_id is provided
        if channel_id is not None and _lead_attribution_available:
            try:
                existing_attr = LeadAttribution.query.filter_by(  # type: ignore[union-attr]
                    lead_ingest_id=lead_ingest.id,
                    channel_id=channel_id,
                ).first()
                if not existing_attr:
                    attribution = LeadAttribution(  # type: ignore[call-arg]
                        account_id=account_id,
                        lead_ingest_id=lead_ingest.id,
                        channel_id=channel_id,
                        phone=phone,
                    )
                    db.session.add(attribution)
                    db.session.commit()
                    current_app.logger.info(
                        "LeadAttribution created: lead_ingest_id=%s channel_id=%s",
                        lead_ingest.id, channel_id,
                    )
            except Exception as attr_err:
                current_app.logger.warning(
                    "LeadAttribution creation failed: %s", attr_err
                )

        return jsonify({"status": "ok", "lead_id": lead_ingest.id}), 200

    except Exception as exc:
        current_app.logger.exception("Unhandled error in generic_lead_webhook: %s", exc)
        return jsonify({"error": "internal_server_error"}), 500
