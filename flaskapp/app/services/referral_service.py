# app/services/referral_service.py
"""
Referral request service.

Sends a referral ask 7 days after a completed job (after the review request
has already gone out). Tracks sends in referral_requests table so they're
never duplicated.

Cron: call process_pending_referral_requests() daily from cron_tasks.run_daily.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from typing import Optional

from app import db

log = logging.getLogger(__name__)

_EMAIL_SUBJECT = "Know anyone who could use our help?"
_EMAIL_HTML = """\
<p>Hi {name},</p>
<p>We hope your recent <strong>{job_type}</strong> went smoothly!</p>
<p>We wanted to ask — if you know a neighbor, friend, or family member
who needs help with {job_type} (or any of our services), we'd love an
introduction. Referrals from customers like you mean the world to a small
local business.</p>
<p>Just forward this email, share our number{phone_line}, or mention our name.
That's it — no codes or forms needed.</p>
<p>Thanks so much for your support!</p>
<p style="color:#6b7280;font-size:13px">— {business_name}</p>
<p style="color:#9ca3af;font-size:11px">
  <a href="{unsubscribe_url}" style="color:#9ca3af;">Unsubscribe</a>
</p>
"""
_SMS = (
    "Hi {name}! If you know anyone who needs {job_type} help, we'd appreciate "
    "the referral. Just mention our name. Thank you! — {business_name} "
    "(Reply STOP to opt out)"
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


def queue_referral_request(
    account_id: int,
    customer_name: Optional[str],
    phone: Optional[str],
    email: Optional[str],
    job_type: Optional[str] = None,
) -> int:
    """
    Queue referral requests for a completed job customer.
    Called from on_crm_job_completed (review_request_service) or directly.
    Returns number of items queued.
    """
    from app.models_tooling import ReferralRequest

    count = 0
    if email:
        db.session.add(ReferralRequest(
            account_id=account_id, channel="email", recipient=email,
            customer_name=customer_name, job_type=job_type, status="queued",
        ))
        count += 1
    if phone:
        db.session.add(ReferralRequest(
            account_id=account_id, channel="sms", recipient=phone,
            customer_name=customer_name, job_type=job_type, status="queued",
        ))
        count += 1
    if count:
        db.session.commit()
    return count


def process_pending_referral_requests(batch: int = 50) -> int:
    """
    Send queued referral requests. Called daily from cron.
    Returns number sent.
    """
    from app.models_tooling import ReferralRequest

    now = datetime.utcnow()
    pending = (
        ReferralRequest.query
        .filter_by(status="queued")
        .order_by(ReferralRequest.created_at)
        .limit(batch)
        .all()
    )

    sent = 0
    for rr in pending:
        business_name, business_phone = _get_account_info(rr.account_id)
        phone_line = f" at {business_phone}" if business_phone else ""
        v = dict(
            name=rr.customer_name or "there",
            job_type=rr.job_type or "our services",
            business_name=business_name,
            phone_line=phone_line,
            unsubscribe_url=_unsubscribe_url(rr.recipient if rr.channel == "email" else ""),
        )
        try:
            if rr.channel == "email":
                from app.services.email_service import send_email
                send_email(
                    to_email=rr.recipient,
                    subject=_EMAIL_SUBJECT,
                    html_body=_EMAIL_HTML.format(**v),
                )
            else:
                sid = os.getenv("TWILIO_ACCOUNT_SID")
                tok = os.getenv("TWILIO_AUTH_TOKEN")
                frm = os.getenv("TWILIO_FROM_NUMBER")
                if sid and tok and frm:
                    import requests as _req
                    _req.post(
                        f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
                        data={"From": frm, "To": rr.recipient, "Body": _SMS.format(**v)},
                        auth=(sid, tok), timeout=10,
                    ).raise_for_status()
                else:
                    log.info("SMS (simulated) to %s", rr.recipient)
            rr.status = "sent"
            rr.sent_at = now
            sent += 1
        except Exception:
            log.exception("referral request failed id=%s", rr.id)
            rr.status = "failed"

    if pending:
        db.session.commit()
    log.info("referral requests sent=%s", sent)
    return sent
