# app/services/crm_normalizer.py
"""
CRM event normalizer.

Converts raw webhook payloads (or polling data) from any supported CRM
into CRMEstimate / CRMJob records and fires the appropriate automation hooks.

Supported providers
-------------------
servicetitan  — detected during job-sync polling (no native webhooks)
jobber        — HMAC-SHA256 signed webhooks
housecall_pro — HMAC-SHA256 signed webhooks

Automation hooks (stubs — wire to email/SMS sequences when ready)
-----------------------------------------------------------------
on_estimate_sent(account_id, estimate)    — queue 2-day follow-up
on_estimate_accepted(account_id, estimate) — queue appointment confirmation
on_estimate_rejected(account_id, estimate) — optionally queue win-back
on_appointment_booked(account_id, job)     — queue 24hr reminder
on_invoice_sent(account_id, job)           — queue payment follow-up
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app import db

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_dt(value: Any) -> Optional[datetime]:
    """Parse an ISO-8601 string into a UTC-naive datetime, or return None."""
    if not value:
        return None
    try:
        s = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    except (ValueError, TypeError):
        return None


def _dollars_to_cents(value: Any) -> int:
    try:
        return int(round(float(value) * 100))
    except (ValueError, TypeError):
        return 0


# ---------------------------------------------------------------------------
# Provider-specific parsers  →  normalized dict
# ---------------------------------------------------------------------------

def _parse_jobber_quote(payload: Dict) -> Dict:
    """Parse a Jobber QUOTE_CREATED / QUOTE_UPDATED webhook body."""
    quote = payload.get("data", {}).get("quote", payload.get("quote", {}))
    client = quote.get("client", {})

    phones = client.get("phoneNumbers", [])
    phone = next((p["number"] for p in phones if p.get("primary")), None)
    if not phone and phones:
        phone = phones[0].get("number")

    amounts = quote.get("amounts", {})
    total = amounts.get("total") or amounts.get("subtotal") or 0

    return {
        "external_estimate_id": str(quote.get("id", "")),
        "customer_name": client.get("name"),
        "customer_email": client.get("email"),
        "customer_phone": phone,
        "job_type": (quote.get("jobType") or {}).get("name"),
        "amount_cents": _dollars_to_cents(total),
        "status": _map_jobber_status(quote.get("quoteStatus", "")),
        "sent_at": _parse_dt(quote.get("sentAt")),
        "expires_at": _parse_dt(quote.get("expiresAt")),
        "source_provider": "jobber",
        "raw_data": payload,
    }


def _map_jobber_status(raw: str) -> str:
    mapping = {
        "draft": "draft",
        "sent": "sent",
        "client_viewed": "viewed",
        "changes_requested": "viewed",
        "approved": "accepted",
        "archived": "rejected",
        "converted_to_job": "accepted",
    }
    return mapping.get(raw.lower(), "sent")


def _parse_housecall_estimate(payload: Dict) -> Dict:
    """Parse a HouseCall Pro estimate webhook payload."""
    est = payload.get("estimate", payload)
    customer = est.get("customer", {})

    return {
        "external_estimate_id": str(est.get("id", "")),
        "customer_name": customer.get("name") or (
            f"{customer.get('first_name','')} {customer.get('last_name','')}".strip()
        ),
        "customer_email": customer.get("email"),
        "customer_phone": customer.get("mobile_number") or customer.get("phone"),
        "job_type": est.get("work_status") or est.get("job_type"),
        "amount_cents": _dollars_to_cents(est.get("grand_total") or est.get("total") or 0),
        "status": _map_housecall_status(payload.get("event", "")),
        "sent_at": _parse_dt(est.get("sent_at") or est.get("created_at")),
        "expires_at": _parse_dt(est.get("expires_on")),
        "source_provider": "housecall_pro",
        "raw_data": payload,
    }


def _map_housecall_status(event: str) -> str:
    mapping = {
        "estimate.created": "sent",
        "estimate.sent": "sent",
        "estimate.approved": "accepted",
        "estimate.declined": "rejected",
        "estimate.expired": "expired",
    }
    return mapping.get(event.lower(), "sent")


def _parse_servicetitan_estimate(job_data: Dict) -> Optional[Dict]:
    """
    Detect an estimate inside a ServiceTitan job record (polled, not webhook).
    Returns a normalized dict or None if this job is not an estimate.
    """
    status_raw = (job_data.get("jobStatus") or "").lower()
    # ST estimate statuses vary by account config; common values:
    if status_raw not in ("estimate", "quoted", "proposal"):
        return None

    customer = job_data.get("customer", {})
    contact = job_data.get("contact", customer)

    return {
        "external_estimate_id": str(job_data.get("id", "")),
        "customer_name": contact.get("name") or customer.get("name"),
        "customer_email": contact.get("email") or customer.get("email"),
        "customer_phone": contact.get("phoneNumber") or customer.get("phoneNumber"),
        "job_type": (job_data.get("jobType") or {}).get("name") or job_data.get("jobTypeName"),
        "amount_cents": _dollars_to_cents(job_data.get("total") or 0),
        "status": "sent",
        "sent_at": _parse_dt(job_data.get("createdOn")),
        "source_provider": "servicetitan",
        "raw_data": job_data,
    }


# ---------------------------------------------------------------------------
# Upsert — create or update a CRMEstimate from a normalized dict
# ---------------------------------------------------------------------------

def upsert_estimate(account_id: int, crm_connection_id: Optional[int],
                    normalized: Dict) -> "CRMEstimate":
    """Upsert a CRMEstimate and fire automation hooks on status changes."""
    from app.models_crm import CRMEstimate

    ext_id = normalized.get("external_estimate_id") or None
    estimate = None

    if crm_connection_id and ext_id:
        estimate = CRMEstimate.query.filter_by(
            crm_connection_id=crm_connection_id,
            external_estimate_id=ext_id,
        ).first()

    old_status = estimate.status if estimate else None

    if estimate is None:
        estimate = CRMEstimate(
            account_id=account_id,
            crm_connection_id=crm_connection_id,
            external_estimate_id=ext_id,
        )
        db.session.add(estimate)

    estimate.customer_name  = normalized.get("customer_name") or estimate.customer_name
    estimate.customer_email = normalized.get("customer_email") or estimate.customer_email
    estimate.customer_phone = normalized.get("customer_phone") or estimate.customer_phone
    estimate.job_type       = normalized.get("job_type") or estimate.job_type
    estimate.amount_cents   = normalized.get("amount_cents") or estimate.amount_cents
    estimate.status         = normalized.get("status", estimate.status or "sent")
    estimate.sent_at        = normalized.get("sent_at") or estimate.sent_at
    estimate.expires_at     = normalized.get("expires_at") or estimate.expires_at
    estimate.source_provider = normalized.get("source_provider") or estimate.source_provider
    estimate.raw_data       = normalized.get("raw_data") or estimate.raw_data

    if estimate.status == "viewed" and not estimate.viewed_at:
        estimate.viewed_at = datetime.utcnow()
    if estimate.status in ("accepted", "rejected") and not estimate.responded_at:
        estimate.responded_at = datetime.utcnow()

    db.session.commit()

    # Fire hooks on status transitions
    new_status = estimate.status
    if old_status != new_status:
        _fire_estimate_hook(account_id, estimate, old_status, new_status)

    return estimate


# ---------------------------------------------------------------------------
# Automation hooks
# ---------------------------------------------------------------------------

def _fire_estimate_hook(account_id: int, estimate: "CRMEstimate",
                        old_status: Optional[str], new_status: str) -> None:
    if new_status == "sent" and old_status is None:
        on_estimate_sent(account_id, estimate)
    elif new_status == "accepted":
        on_estimate_accepted(account_id, estimate)
    elif new_status in ("rejected", "expired"):
        on_estimate_rejected(account_id, estimate)


def on_estimate_sent(account_id: int, estimate: "CRMEstimate") -> None:
    """Called when a new estimate is logged — queues follow-up sequence."""
    log.info("estimate_sent account=%s estimate=%s customer=%s amount=$%.2f",
             account_id, estimate.id, estimate.customer_name, estimate.amount_dollars)
    try:
        from app.services.estimate_followup_service import queue_estimate_followup
        queue_estimate_followup(account_id, estimate)
    except Exception:
        log.exception("on_estimate_sent: failed to queue follow-up")


def on_estimate_accepted(account_id: int, estimate: "CRMEstimate") -> None:
    """
    Called when an estimate is accepted.
    TODO: send appointment confirmation SMS/email.
    """
    log.info("estimate_accepted account=%s estimate=%s customer=%s",
             account_id, estimate.id, estimate.customer_name)


def on_estimate_rejected(account_id: int, estimate: "CRMEstimate") -> None:
    """
    Called when an estimate is rejected or expires.
    TODO: optionally enroll in a 30-day win-back sequence.
    """
    log.info("estimate_rejected/expired account=%s estimate=%s status=%s",
             account_id, estimate.id, estimate.status)


def on_appointment_booked(account_id: int, job: "CRMJob") -> None:
    """
    Called when a job gets an appointment_at datetime set.
    The hourly cron sends the 24-hour reminder; this hook just logs for now.
    """
    log.info("appointment_booked account=%s job=%s customer=%s at=%s",
             account_id, getattr(job, "external_job_id", job.id),
             getattr(job, "customer_name", "?"), job.appointment_at)


def on_invoice_sent(account_id: int, job: "CRMJob") -> None:
    """
    Called when a job is marked invoiced.
    TODO: queue payment follow-up if unpaid after 7 days.
    """
    log.info("invoice_sent account=%s job=%s customer=%s",
             account_id, getattr(job, "external_job_id", job.id),
             getattr(job, "customer_name", "?"))


# ---------------------------------------------------------------------------
# Public entry points called by webhook routes
# ---------------------------------------------------------------------------

def handle_jobber_event(account_id: int, crm_connection_id: Optional[int],
                        payload: Dict) -> Optional["CRMEstimate"]:
    """Process a Jobber webhook event. Returns CRMEstimate if applicable."""
    event = payload.get("webHookEvent", "")
    log.debug("jobber event=%s account=%s", event, account_id)

    if "QUOTE" in event.upper():
        normalized = _parse_jobber_quote(payload)
        return upsert_estimate(account_id, crm_connection_id, normalized)

    if "APPOINTMENT" in event.upper() or "JOB" in event.upper():
        _handle_jobber_job(account_id, crm_connection_id, payload)

    return None


def _handle_jobber_job(account_id: int, crm_connection_id: Optional[int],
                       payload: Dict) -> None:
    """Update CRMJob appointment_at from a Jobber JOB/APPOINTMENT event."""
    from app.models_crm import CRMJob, CRMConnection

    job_data = payload.get("data", {}).get("job", payload.get("job", {}))
    ext_id = str(job_data.get("id", ""))
    if not ext_id:
        return

    conn_id = crm_connection_id
    if not conn_id:
        conn = CRMConnection.query.filter_by(account_id=account_id,
                                             provider="jobber").first()
        conn_id = conn.id if conn else None

    if not conn_id:
        return

    job = CRMJob.query.filter_by(crm_connection_id=conn_id,
                                 external_job_id=ext_id).first()
    if not job:
        return

    scheduled = _parse_dt(job_data.get("startAt") or job_data.get("scheduledStart"))
    if scheduled and not job.appointment_at:
        job.appointment_at = scheduled
        db.session.commit()
        on_appointment_booked(account_id, job)


def handle_housecall_event(account_id: int, crm_connection_id: Optional[int],
                           payload: Dict) -> Optional["CRMEstimate"]:
    """Process a HouseCall Pro webhook event."""
    event = payload.get("event", "")
    log.debug("housecall event=%s account=%s", event, account_id)

    if "estimate" in event.lower():
        normalized = _parse_housecall_estimate(payload)
        return upsert_estimate(account_id, crm_connection_id, normalized)

    return None


def handle_servicetitan_job(account_id: int, crm_connection_id: int,
                             job_data: Dict) -> None:
    """
    Called from servicetitan_service._upsert_job for every synced job.
    Creates a CRMEstimate if the job is in estimate status.
    """
    normalized = _parse_servicetitan_estimate(job_data)
    if normalized:
        upsert_estimate(account_id, crm_connection_id, normalized)
