# app/services/appointment_reminder_service.py
"""
Appointment reminder service.

Sends SMS + email confirmations/reminders for upcoming jobs when
appointment_at is set on a CRMJob.

Schedule:
  T-24h  → reminder SMS + email ("We'll see you tomorrow at 2pm")
  T-0    → (handled by CRM, nothing extra sent)

Cron: call process_pending_appointment_reminders() hourly from cron_tasks.run_hourly.
      The 2-hour send window (23–25h before appointment) prevents double-sends.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta

from app import db

log = logging.getLogger(__name__)

# ── Built-in templates ────────────────────────────────────────────────────────

_REMINDER_EMAIL_SUBJECT = "Appointment reminder: {job_type} tomorrow"
_REMINDER_EMAIL_HTML = """\
<p>Hi {name},</p>
<p>Just a friendly reminder that your <strong>{job_type}</strong> appointment
is scheduled for <strong>{appt_time}</strong>.</p>
<p>If you need to reschedule or have any questions, please reply to this email
or call us{phone_line}.</p>
<p>We look forward to seeing you!</p>
<p style="color:#6b7280;font-size:13px">— {business_name}</p>
"""
_REMINDER_SMS = (
    "Hi {name}, just a reminder: your {job_type} appointment is tomorrow "
    "at {appt_time_short}. Questions? Call us{phone_line}."
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


def _send_reminder_email(email: str, subject: str, html_body: str) -> bool:
    if not email:
        return False
    try:
        from app.services.email_service import send_email
        send_email(to_email=email, subject=subject, html_body=html_body)
        return True
    except Exception:
        log.exception("appointment reminder email failed to=%s", email)
        return False


def _send_reminder_sms(phone: str, body: str) -> bool:
    if not phone:
        return False
    sid = os.getenv("TWILIO_ACCOUNT_SID")
    tok = os.getenv("TWILIO_AUTH_TOKEN")
    frm = os.getenv("TWILIO_FROM_NUMBER")
    if not (sid and tok and frm):
        log.info("SMS (simulated) to %s: %s", phone, body)
        return True
    try:
        import requests as _req
        _req.post(
            f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
            data={"From": frm, "To": phone, "Body": body},
            auth=(sid, tok),
            timeout=10,
        ).raise_for_status()
        return True
    except Exception:
        log.exception("appointment reminder SMS failed to=%s", phone)
        return False


def process_pending_appointment_reminders(batch: int = 50) -> int:
    """
    Send 24-hour reminders for jobs whose appointment_at falls within the
    next 23–25 hour window (a 2-hour send window prevents double-sends
    without requiring a separate flag column).

    Call hourly from cron_tasks.run_hourly.
    Returns the number of reminders sent.
    """
    try:
        from app.models_crm import CRMJob
    except Exception:
        log.debug("CRMJob model not available — skipping appointment reminders")
        return 0

    now = datetime.utcnow()
    window_start = now + timedelta(hours=23)
    window_end   = now + timedelta(hours=25)

    due_jobs = CRMJob.query.filter(
        CRMJob.appointment_at >= window_start,
        CRMJob.appointment_at <= window_end,
        CRMJob.appointment_reminder_sent_at.is_(None),
        CRMJob.job_status.notin_(["cancelled", "completed"]),
    ).limit(batch).all()

    sent_count = 0
    for job in due_jobs:
        business_name, business_phone = _get_account_info(job.account_id)

        name = getattr(job, "customer_name", None) or "there"
        phone = getattr(job, "customer_phone", None)
        email = getattr(job, "customer_email", None)
        job_type = job.job_type or "service"
        phone_line = f" at {business_phone}" if business_phone else ""
        appt_time = job.appointment_at.strftime("%A, %B %d at %-I:%M %p") if job.appointment_at else "your scheduled time"
        appt_time_short = job.appointment_at.strftime("%-I:%M %p") if job.appointment_at else "your scheduled time"

        v = dict(
            name=name,
            job_type=job_type,
            appt_time=appt_time,
            appt_time_short=appt_time_short,
            phone_line=phone_line,
            business_name=business_name,
        )

        ok = False
        if email:
            subject = _REMINDER_EMAIL_SUBJECT.format(**v)
            html = _REMINDER_EMAIL_HTML.format(**v)
            ok = _send_reminder_email(email, subject, html) or ok
        if phone:
            ok = _send_reminder_sms(phone, _REMINDER_SMS.format(**v)) or ok

        job.appointment_reminder_sent_at = now
        if ok:
            sent_count += 1

    if due_jobs:
        db.session.commit()

    log.info("appointment reminders sent=%s", sent_count)
    return sent_count
