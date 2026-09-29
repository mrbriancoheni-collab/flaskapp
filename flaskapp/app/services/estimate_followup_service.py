# app/services/estimate_followup_service.py
"""
Estimate follow-up service.

Sends automated follow-up emails/SMS when a customer hasn't responded
to a quote/estimate.

Schedule (relative to estimate.sent_at):
  Day 0 — estimate sent → immediate "we sent you an estimate" confirmation (optional)
  Day 2 — no response   → first follow-up nudge
  Day 5 — still no response → final follow-up with urgency

Templates are built-in (work with no setup). Accounts can override via
LeadIntakeConfig if custom fields are added in the future.

Cron: call process_pending_estimate_followups() daily from cron_tasks.run_daily.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from typing import Optional

from app import db

log = logging.getLogger(__name__)

# ── Built-in email templates ─────────────────────────────────────────────────

_FOLLOWUP_1_SUBJECT = "Quick follow-up on your {job_type} estimate"
_FOLLOWUP_1_HTML = """\
<p>Hi {name},</p>
<p>Just a quick note — we sent you an estimate for <strong>{job_type}</strong>
{amount_line} a couple of days ago and wanted to make sure it landed.</p>
<p>If you have any questions or would like to adjust the scope, we're happy to chat.
Just reply to this email or give us a call{phone_line}.</p>
<p>We'd love to help!</p>
<p style="color:#6b7280;font-size:13px">— {business_name}</p>
"""
_FOLLOWUP_1_SMS = (
    "Hi {name}, just following up on your {job_type} estimate. "
    "Any questions? Reply or call us anytime{phone_line}."
)

_FOLLOWUP_2_SUBJECT = "One last follow-up on your estimate"
_FOLLOWUP_2_HTML = """\
<p>Hi {name},</p>
<p>This is our final follow-up regarding the <strong>{job_type}</strong> estimate
{amount_line} we prepared for you.</p>
{expires_line}
<p>If the timing isn't right, no problem — we're here whenever you're ready.
Just reply or call us{phone_line}.</p>
<p style="color:#6b7280;font-size:13px">— {business_name}</p>
"""
_FOLLOWUP_2_SMS = (
    "Hi {name}, final follow-up on your {job_type} estimate. "
    "We'd love to earn your business — reply or call us{phone_line}."
)


def _build_vars(estimate, business_name: str, business_phone: str) -> dict:
    name = estimate.customer_name or "there"
    job_type = estimate.job_type or "recent service"
    amount = estimate.amount_dollars
    amount_line = f"(${amount:,.0f})" if amount else ""
    phone_line = f" at {business_phone}" if business_phone else ""

    expires_line = ""
    if estimate.expires_at and estimate.expires_at > datetime.utcnow():
        expires_line = (
            f'<p>Your estimate is valid until '
            f'<strong>{estimate.expires_at.strftime("%B %d, %Y")}</strong>.</p>'
        )

    return dict(
        name=name,
        job_type=job_type,
        amount_line=amount_line,
        phone_line=phone_line,
        expires_line=expires_line,
        business_name=business_name,
    )


def _get_account_info(account_id: int) -> tuple[str, str]:
    """Return (business_name, phone) for the account."""
    try:
        from app.models import Account
        acct = Account.query.get(account_id)
        if acct:
            return (acct.name or "Our team"), (getattr(acct, "phone", "") or "")
    except Exception:
        pass
    return "Our team", ""


def _send_email(estimate, subject: str, html_body: str) -> bool:
    if not estimate.customer_email:
        return False
    try:
        from app.services.email_service import send_email
        send_email(
            to_email=estimate.customer_email,
            subject=subject,
            html_body=html_body,
        )
        return True
    except Exception:
        log.exception("estimate follow-up email failed estimate=%s", estimate.id)
        return False


def _send_sms(estimate, body: str) -> bool:
    if not estimate.customer_phone:
        return False
    sid = os.getenv("TWILIO_ACCOUNT_SID")
    tok = os.getenv("TWILIO_AUTH_TOKEN")
    frm = os.getenv("TWILIO_FROM_NUMBER")
    if not (sid and tok and frm):
        log.info("SMS (simulated) to %s: %s", estimate.customer_phone, body)
        return True
    try:
        import requests as _req
        _req.post(
            f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
            data={"From": frm, "To": estimate.customer_phone, "Body": body},
            auth=(sid, tok),
            timeout=10,
        ).raise_for_status()
        return True
    except Exception:
        log.exception("estimate follow-up SMS failed estimate=%s", estimate.id)
        return False


def _send_followup(estimate, template_html: str, template_sms: str,
                   subject: str, business_name: str, business_phone: str) -> bool:
    v = _build_vars(estimate, business_name, business_phone)
    sent = False
    if estimate.customer_email:
        sent = _send_email(estimate, subject.format(**v), template_html.format(**v))
    if estimate.customer_phone:
        sent = _send_sms(estimate, template_sms.format(**v)) or sent
    return sent


# ── Public API ────────────────────────────────────────────────────────────────

def queue_estimate_followup(account_id: int, estimate) -> None:
    """
    Called by crm_normalizer.on_estimate_sent immediately after an estimate
    is logged.  No queue table needed — follow_up_*_sent_at on CRMEstimate
    tracks what has been sent.  The actual sends happen in the daily cron.
    """
    log.info("estimate queued for follow-up account=%s estimate=%s customer=%s",
             account_id, estimate.id, estimate.customer_name)


def process_pending_estimate_followups(batch: int = 100) -> int:
    """
    Send follow-up emails/SMS for estimates that haven't received a response.
    Call daily from cron_tasks.run_daily.
    Returns the number of messages sent.
    """
    from app.models_crm import CRMEstimate

    now = datetime.utcnow()
    sent_count = 0

    # ── Follow-up 1: 2 days after sent, no response ───────────────────────
    day2_cutoff = now - timedelta(days=2)
    followup1_due = CRMEstimate.query.filter(
        CRMEstimate.status == "sent",
        CRMEstimate.sent_at <= day2_cutoff,
        CRMEstimate.follow_up_1_sent_at.is_(None),
    ).limit(batch).all()

    for estimate in followup1_due:
        business_name, business_phone = _get_account_info(estimate.account_id)
        ok = _send_followup(
            estimate,
            _FOLLOWUP_1_HTML,
            _FOLLOWUP_1_SMS,
            _FOLLOWUP_1_SUBJECT,
            business_name,
            business_phone,
        )
        estimate.follow_up_1_sent_at = now
        sent_count += 1 if ok else 0

    if followup1_due:
        db.session.commit()

    # ── Follow-up 2: 3 days after follow-up 1 (day 5 total), still no response
    day5_cutoff = now - timedelta(days=3)
    followup2_due = CRMEstimate.query.filter(
        CRMEstimate.status == "sent",
        CRMEstimate.follow_up_1_sent_at <= day5_cutoff,
        CRMEstimate.follow_up_2_sent_at.is_(None),
    ).limit(batch).all()

    for estimate in followup2_due:
        business_name, business_phone = _get_account_info(estimate.account_id)
        ok = _send_followup(
            estimate,
            _FOLLOWUP_2_HTML,
            _FOLLOWUP_2_SMS,
            _FOLLOWUP_2_SUBJECT,
            business_name,
            business_phone,
        )
        estimate.follow_up_2_sent_at = now
        sent_count += 1 if ok else 0

    if followup2_due:
        db.session.commit()

    log.info("estimate follow-ups sent=%s", sent_count)
    return sent_count
