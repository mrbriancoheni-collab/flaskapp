# app/services/invoice_followup_service.py
"""
Invoice payment follow-up service.

Sends a polite payment reminder 7 days after a job is invoiced,
if the job is not yet marked paid or cancelled.

Follow-up state is stored in CRMJob.payload["invoice_followup_sent"] so
no additional DB migration is required.

Cron: call process_pending_invoice_followups() daily from cron_tasks.run_daily.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from typing import Optional

from app import db

log = logging.getLogger(__name__)

_EMAIL_SUBJECT = "Invoice reminder — {job_type} service"
_EMAIL_HTML = """\
<p>Hi {name},</p>
<p>We hope your recent <strong>{job_type}</strong> went smoothly!</p>
<p>We wanted to send a friendly reminder that invoice #{invoice_id} for
<strong>${amount}</strong> is still outstanding.</p>
<p>If you have any questions about the invoice or would like to discuss
payment options, please don't hesitate to reach out — we're happy to help.</p>
<p>Thanks so much for your business!</p>
<p style="color:#6b7280;font-size:13px">— {business_name}</p>
"""
_SMS = (
    "Hi {name}, just a friendly reminder about your {job_type} invoice "
    "(${amount}). Please reach out if you have any questions — {business_name}. "
    "Reply STOP to opt out."
)


def _get_account_info(account_id: int) -> tuple[str, str]:
    try:
        from app.models import Account
        acct = Account.query.get(account_id)
        if acct:
            return (acct.name or "Our team"), (getattr(acct, "phone", "") or "")
    except Exception:
        pass
    return "Our team", ""


def send_invoice_followup(account_id: int, job: "CRMJob") -> bool:
    """
    Send a payment reminder for a single invoiced job.
    Returns True if at least one message was sent.
    """
    from app.models_crm import CRMJob

    business_name, _ = _get_account_info(account_id)
    name = getattr(job, "customer_name", None) or "there"
    job_type = getattr(job, "job_type", None) or "service"
    email = getattr(job, "customer_email", None)
    phone = getattr(job, "customer_phone", None)
    amount = f"{getattr(job, 'invoiced_amount_cents', 0) / 100:.2f}" if hasattr(job, "invoiced_amount_cents") else "0.00"
    invoice_id = getattr(job, "external_job_id", None) or str(job.id)

    v = dict(
        name=name,
        job_type=job_type,
        invoice_id=invoice_id,
        amount=amount,
        business_name=business_name,
    )

    sent = False

    if email:
        try:
            from app.services.email_service import send_email
            send_email(
                to_email=email,
                subject=_EMAIL_SUBJECT.format(**v),
                html_body=_EMAIL_HTML.format(**v),
            )
            sent = True
        except Exception:
            log.exception("invoice_followup email failed job=%s", job.id)

    if phone:
        try:
            sid = os.getenv("TWILIO_ACCOUNT_SID")
            tok = os.getenv("TWILIO_AUTH_TOKEN")
            frm = os.getenv("TWILIO_FROM_NUMBER")
            body = _SMS.format(**v)
            if sid and tok and frm:
                import requests as _req
                _req.post(
                    f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
                    data={"From": frm, "To": phone, "Body": body},
                    auth=(sid, tok), timeout=10,
                ).raise_for_status()
            else:
                log.info("SMS (simulated) invoice reminder to %s: %s", phone, body)
            sent = True
        except Exception:
            log.exception("invoice_followup SMS failed job=%s", job.id)

    if sent:
        payload = job.payload or {}
        payload["invoice_followup_sent"] = datetime.utcnow().isoformat()
        job.payload = payload
        db.session.commit()
        log.info("invoice_followup sent account=%s job=%s customer=%s", account_id, job.id, name)

    return sent


def process_pending_invoice_followups(followup_days: int = 7, batch: int = 50) -> int:
    """
    Find jobs invoiced >= followup_days ago, not yet paid/cancelled, and no
    follow-up sent yet. Sends a payment reminder. Returns number of jobs contacted.

    Called daily from cron_tasks.run_daily.
    """
    from app.models_crm import CRMJob
    from sqlalchemy import cast, String

    cutoff = datetime.utcnow() - timedelta(days=followup_days)

    candidates = (
        CRMJob.query
        .filter(
            CRMJob.invoiced_at.isnot(None),
            CRMJob.invoiced_at <= cutoff,
            CRMJob.job_status.notin_(["paid", "cancelled"]),
        )
        .limit(batch * 3)
        .all()
    )

    sent = 0
    for job in candidates:
        if sent >= batch:
            break
        payload = job.payload or {}
        if payload.get("invoice_followup_sent"):
            continue
        try:
            ok = send_invoice_followup(job.account_id, job)
            if ok:
                sent += 1
        except Exception:
            log.exception("invoice_followup failed for job=%s", job.id)

    log.info("invoice_followup: sent=%s", sent)
    return sent
