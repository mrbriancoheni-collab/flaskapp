# app/services/reactivation_service.py
"""
Win-back / reactivation campaign service.

Identifies customers who had a completed job but haven't booked again
in 90+ days, and sends a friendly "we miss you" email/SMS.

Cooldown: won't re-contact the same customer for 180 days (tracked in
reactivation_sends table).

Cron: call process_reactivation_campaign() weekly from cron_tasks.run_daily
      (gated to run only on Mondays so it doesn't fire every day).
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from typing import Optional

from app import db

log = logging.getLogger(__name__)

_EMAIL_SUBJECT = "It's been a while — we'd love to help again"
_EMAIL_HTML = """\
<p>Hi {name},</p>
<p>We hope everything is going well! It's been a little while since we helped
you with your <strong>{job_type}</strong>, and we wanted to check in.</p>
<p>If there's anything we can help with — whether it's a follow-up service,
a new project, or just a question — we're always here.</p>
<p>Give us a call{phone_line} or simply reply to this email.</p>
<p>Thanks for being a customer — we appreciate you!</p>
<p style="color:#6b7280;font-size:13px">— {business_name}</p>
<p style="color:#9ca3af;font-size:11px">
  <a href="{unsubscribe_url}" style="color:#9ca3af;">Unsubscribe</a>
</p>
"""
_SMS = (
    "Hi {name}, it's {business_name}! It's been a while since your {job_type}. "
    "We're here if you need us{phone_line}. Reply STOP to opt out."
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


def _unsubscribe_url(email: str) -> str:
    try:
        from flask import url_for
        return url_for("lead_campaigns_bp.unsubscribe", email=email, _external=True)
    except Exception:
        return ""


def _send_email(to_email: str, subject: str, html: str) -> bool:
    try:
        from app.services.email_service import send_email
        send_email(to_email=to_email, subject=subject, html_body=html)
        return True
    except Exception:
        log.exception("reactivation email failed to=%s", to_email)
        return False


def _send_sms(phone: str, body: str) -> bool:
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
            auth=(sid, tok), timeout=10,
        ).raise_for_status()
        return True
    except Exception:
        log.exception("reactivation SMS failed to=%s", phone)
        return False


def process_reactivation_campaign(
    inactive_days: int = 90,
    cooldown_days: int = 180,
    batch: int = 50,
) -> int:
    """
    Find customers inactive for `inactive_days` days and send win-back messages.
    Skips customers contacted within `cooldown_days`.
    Returns number of messages sent.
    """
    from app.models_crm import CRMJob
    from app.models_tooling import ReactivationSend
    from sqlalchemy import func, text

    now = datetime.utcnow()
    inactive_cutoff = now - timedelta(days=inactive_days)
    cooldown_cutoff = now - timedelta(days=cooldown_days)

    # Find the most recent completed job per (account_id, customer_email)
    # where that most recent job is older than inactive_cutoff
    # and customer_email is not null
    try:
        subq = (
            db.session.query(
                CRMJob.account_id,
                CRMJob.account_id.label("acct"),
                func.max(CRMJob.job_date).label("last_job"),
                # pick contact info from the row with the latest job
                func.max(CRMJob.external_customer_id).label("customer_id"),
                # We need customer contact info — duck-type optional columns
                func.max(getattr(CRMJob, "customer_email", CRMJob.external_customer_id)).label("email"),
                func.max(getattr(CRMJob, "customer_phone", CRMJob.external_customer_id)).label("phone"),
                func.max(getattr(CRMJob, "customer_name",  CRMJob.external_customer_id)).label("name"),
                func.max(CRMJob.job_type).label("job_type"),
            )
            .filter(
                CRMJob.job_status == "completed",
                CRMJob.job_date.isnot(None),
            )
            .group_by(CRMJob.account_id, CRMJob.external_customer_id)
            .having(func.max(CRMJob.job_date) <= inactive_cutoff.date())
            .limit(batch * 3)
            .all()
        )
    except Exception:
        log.exception("reactivation: CRMJob query failed")
        return 0

    sent_count = 0
    for row in subq[:batch]:
        account_id = row.account_id
        email = row.email if row.email != row.customer_id else None
        phone = row.phone if row.phone != row.customer_id else None
        name = row.name if row.name != row.customer_id else None
        job_type = row.job_type or "service"

        if not (email or phone):
            continue

        # Cooldown check
        already_sent = ReactivationSend.query.filter(
            ReactivationSend.account_id == account_id,
            ReactivationSend.customer_email == email,
            ReactivationSend.sent_at >= cooldown_cutoff,
        ).first()
        if already_sent:
            continue

        # Suppression check
        if email:
            from app.models_leads import EmailUnsubscribe
            if EmailUnsubscribe.query.filter_by(email=email.lower()).first():
                continue

        business_name, business_phone = _get_account_info(account_id)
        phone_line = f" at {business_phone}" if business_phone else ""
        v = dict(
            name=name or "there",
            job_type=job_type,
            business_name=business_name,
            phone_line=phone_line,
            unsubscribe_url=_unsubscribe_url(email or ""),
        )

        ok = False
        if email:
            ok = _send_email(email, _EMAIL_SUBJECT, _EMAIL_HTML.format(**v)) or ok
        if phone:
            ok = _send_sms(phone, _SMS.format(**v)) or ok

        db.session.add(ReactivationSend(
            account_id=account_id,
            customer_email=email,
            customer_phone=phone,
            customer_name=name,
            sent_at=now,
        ))
        if ok:
            sent_count += 1

    db.session.commit()
    log.info("reactivation messages sent=%s", sent_count)
    return sent_count
