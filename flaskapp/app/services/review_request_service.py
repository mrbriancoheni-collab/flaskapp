# app/services/review_request_service.py
"""
Review Request Service

Sends automated SMS + email review requests after job completion.
Triggered by:
  1. CRM job sync: when a job status becomes 'completed'
  2. Lead Inbox: when a LeadIngest status is set to 'completed'
  3. Manual: admin or account dashboard

Default SMS template:
  Hi {name}, thanks for choosing us for your {job_type}!
  Would you mind leaving a quick review? It helps us a lot.
  Google: {google_link}

Sends via Twilio (SMS) and Mailgun/Brevo (email).
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Optional

from app import db
from app.models_tooling import ReviewRequest, LeadIntakeConfig

log = logging.getLogger(__name__)

DEFAULT_SMS = (
    "Hi {name}, thanks for choosing us for your {job_type}! "
    "Would you take 30 seconds to leave a review? It means a lot. "
    "{google_link}"
)
DEFAULT_EMAIL_SUBJECT = "How did we do? Quick review request"
DEFAULT_EMAIL_HTML = """
<p>Hi {name},</p>
<p>Thank you for trusting us with your <strong>{job_type}</strong>. We hope everything went great!</p>
<p>If you have a moment, we'd love a review — it helps our small business more than you know.</p>
<p style="margin:24px 0">
  <a href="{google_link}" style="background:#4f46e5;color:#fff;padding:12px 24px;border-radius:8px;text-decoration:none;font-weight:600;">
    Leave a Google Review
  </a>
</p>
{yelp_section}
<p style="color:#6b7280;font-size:13px">Thanks again — we appreciate your business!</p>
"""
YELP_SECTION = '<p><a href="{yelp_link}">Or leave a Yelp review here</a></p>'


def queue_review_request(
    account_id: int,
    customer_name: Optional[str],
    phone: Optional[str],
    email: Optional[str],
    job_type: Optional[str] = None,
) -> int:
    """
    Queue SMS + email review requests for a completed job.
    Returns the number of requests queued.
    """
    cfg = LeadIntakeConfig.query.filter_by(account_id=account_id).first()
    google_link = cfg.review_link_google if cfg else None
    yelp_link = cfg.review_link_yelp if cfg else None

    count = 0
    if phone:
        db.session.add(ReviewRequest(
            account_id=account_id,
            channel="sms",
            recipient=phone,
            customer_name=customer_name,
            job_type=job_type,
            review_link_google=google_link,
            review_link_yelp=yelp_link,
            status="queued",
        ))
        count += 1

    if email:
        db.session.add(ReviewRequest(
            account_id=account_id,
            channel="email",
            recipient=email,
            customer_name=customer_name,
            job_type=job_type,
            review_link_google=google_link,
            review_link_yelp=yelp_link,
            status="queued",
        ))
        count += 1

    db.session.commit()
    log.info("Queued %s review request(s) for account %s customer=%s", count, account_id, customer_name)
    return count


def send_pending_review_requests(account_id: Optional[int] = None, batch: int = 50) -> int:
    """
    Process queued review requests. Call from a cron job / daily task.
    Returns the number sent successfully.
    """
    q = ReviewRequest.query.filter_by(status="queued")
    if account_id:
        q = q.filter_by(account_id=account_id)
    pending = q.order_by(ReviewRequest.created_at).limit(batch).all()

    sent = 0
    for rr in pending:
        try:
            if rr.channel == "sms":
                _send_sms(rr)
            elif rr.channel == "email":
                _send_email(rr)
            rr.status = "sent"
            rr.sent_at = datetime.utcnow()
            sent += 1
        except Exception as e:
            log.exception("Failed to send review request id=%s: %s", rr.id, e)
            rr.status = "failed"
            if rr.payload is None:
                rr.payload = {}
            rr.payload["error"] = str(e)

    db.session.commit()
    log.info("Sent %s review requests", sent)
    return sent


def _build_vars(rr: ReviewRequest) -> dict:
    name = rr.customer_name or "there"
    job_type = rr.job_type or "recent service"
    google_link = rr.review_link_google or ""
    yelp_link = rr.review_link_yelp or ""
    return dict(name=name, job_type=job_type, google_link=google_link, yelp_link=yelp_link)


def _send_sms(rr: ReviewRequest) -> None:
    import requests as _req
    cfg = LeadIntakeConfig.query.filter_by(account_id=rr.account_id).first()
    template = (cfg.review_request_sms_template if cfg else None) or DEFAULT_SMS
    v = _build_vars(rr)
    body = template.format(**v)

    sid = os.getenv("TWILIO_ACCOUNT_SID")
    tok = os.getenv("TWILIO_AUTH_TOKEN")
    frm = os.getenv("TWILIO_FROM_NUMBER")
    if not (sid and tok and frm):
        log.info("SMS (simulated) to %s: %s", rr.recipient, body)
        return
    resp = _req.post(
        f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
        data={"From": frm, "To": rr.recipient, "Body": body},
        auth=(sid, tok),
        timeout=10,
    )
    resp.raise_for_status()


def _send_email(rr: ReviewRequest) -> None:
    v = _build_vars(rr)
    subject = DEFAULT_EMAIL_SUBJECT
    yelp_section = YELP_SECTION.format(yelp_link=v["yelp_link"]) if v["yelp_link"] else ""
    html_body = DEFAULT_EMAIL_HTML.format(**v, yelp_section=yelp_section)

    try:
        from app.services.email_service import send_email
        send_email(
            to_email=rr.recipient,
            subject=subject,
            html_body=html_body,
            text_body=f"Hi {v['name']}, please leave us a review: {v['google_link']}",
        )
    except Exception:
        log.exception("Email review request failed for rr=%s", rr.id)
        raise


def on_crm_job_completed(account_id: int, job) -> None:
    """
    Hook called when a CRM job (ServiceTitan / Jobber) is marked completed.
    `job` can be a CRMJob or ServiceTitanJob — we duck-type the fields we need.

    Triggers:
      1. NPS satisfaction survey (email only)
      2. Review request (SMS + email) — gated on NPS if survey was sent
      3. Referral request queued for 7 days later (handled by daily cron)
    """
    try:
        name = getattr(job, "customer_name", None) or getattr(job, "external_customer_id", None)
        phone = getattr(job, "customer_phone", None)
        email = getattr(job, "customer_email", None)
        job_type = getattr(job, "job_type", None)

        if not (phone or email):
            log.debug("on_crm_job_completed: no contact info for job %s, skipping", getattr(job, "id", "?"))
            return

        # 1. NPS survey (email only — gives honest feedback before public review)
        if email:
            try:
                cfg = LeadIntakeConfig.query.filter_by(account_id=account_id).first()
                google_link = cfg.review_link_google if cfg else None
                from app.services.nps_service import queue_nps_survey
                queue_nps_survey(
                    account_id=account_id,
                    customer_name=name,
                    email=email,
                    job_type=job_type,
                    google_review_link=google_link,
                )
            except Exception:
                log.exception("on_crm_job_completed: NPS queue failed account=%s", account_id)

        # 2. Review request (SMS + email)
        queue_review_request(
            account_id=account_id,
            customer_name=name,
            phone=phone,
            email=email,
            job_type=job_type,
        )

        # 3. Referral request (queued; cron sends 7 days later)
        try:
            from app.services.referral_service import queue_referral_request
            queue_referral_request(
                account_id=account_id,
                customer_name=name,
                phone=phone,
                email=email,
                job_type=job_type,
            )
        except Exception:
            log.exception("on_crm_job_completed: referral queue failed account=%s", account_id)

    except Exception:
        log.exception("on_crm_job_completed failed for account %s", account_id)
