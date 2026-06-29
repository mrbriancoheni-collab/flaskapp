# app/services/nps_service.py
"""
NPS (satisfaction) pre-screening service.

Sends a 1-question survey after job completion:
  "On a scale of 1-10, how would you rate your experience?"

Score routing:
  >= 7  → happy customer → follow-up email nudges them to leave a Google review
  1-6   → unhappy customer → flagged internally (admin can follow up); review
          request is NOT sent, protecting the public reputation.

This runs in parallel with (not instead of) the existing review_request_service,
unless the account opts in to NPS-gated reviews via LeadIntakeConfig.

Cron: call process_pending_nps_surveys() daily.
"""
from __future__ import annotations

import logging
import os
import secrets
from datetime import datetime
from typing import Optional

from app import db

log = logging.getLogger(__name__)

_SURVEY_SUBJECT = "Quick question about your recent {job_type} service"
_SURVEY_HTML = """\
<p>Hi {name},</p>
<p>Thanks for choosing us for your recent <strong>{job_type}</strong>!
We'd love to know how we did.</p>
<p style="font-size:16px;font-weight:600;margin:24px 0 8px">
  On a scale of 1–10, how would you rate your experience?
</p>
<table style="border-collapse:collapse;margin-bottom:24px">
  <tr>
    {score_buttons}
  </tr>
</table>
<p style="color:#6b7280;font-size:13px">
  Your feedback helps us improve. It only takes one click — no form, no login.
</p>
<p style="color:#6b7280;font-size:13px">— {business_name}</p>
"""
_SCORE_BTN = (
    '<td style="padding:4px">'
    '<a href="{url}" style="display:inline-block;width:36px;height:36px;'
    'line-height:36px;text-align:center;background:{color};color:#fff;'
    'border-radius:50%;text-decoration:none;font-weight:700;font-size:14px">'
    '{score}</a></td>'
)

_THANKYOU_HTML = """\
<!doctype html><html><head><meta charset="utf-8">
<title>Thank you!</title>
<style>body{{font-family:sans-serif;display:flex;align-items:center;justify-content:center;
min-height:100vh;margin:0;background:#f9fafb}}
.card{{max-width:420px;padding:40px;background:#fff;border-radius:16px;
box-shadow:0 4px 24px rgba(0,0,0,.08);text-align:center}}</style>
</head><body><div class="card">
<div style="font-size:48px;margin-bottom:16px">{emoji}</div>
<h2 style="margin:0 0 12px;color:#111827">{heading}</h2>
<p style="color:#6b7280;margin:0 0 24px">{message}</p>
{cta}
</div></body></html>
"""

_CTA_REVIEW = (
    '<a href="{link}" target="_blank" '
    'style="display:inline-block;background:#4f46e5;color:#fff;padding:12px 28px;'
    'border-radius:8px;text-decoration:none;font-weight:600;">Leave a Google Review</a>'
)


def _score_buttons(token: str) -> str:
    try:
        from flask import url_for
        base = url_for("public_bp.nps_respond", token=token, _external=True)
    except Exception:
        base = f"/nps/{token}"

    buttons = []
    for s in range(1, 11):
        color = "#ef4444" if s <= 3 else "#f59e0b" if s <= 6 else "#10b981"
        url = f"{base}?score={s}"
        buttons.append(_SCORE_BTN.format(url=url, color=color, score=s))
    return "".join(buttons)


def _get_account_info(account_id: int) -> tuple[str, str]:
    try:
        from app.models import Account
        acct = Account.query.get(account_id)
        if acct:
            return (acct.name or "Our team"), (getattr(acct, "phone", "") or "")
    except Exception:
        pass
    return "Our team", ""


def queue_nps_survey(
    account_id: int,
    customer_name: Optional[str],
    email: Optional[str],
    job_type: Optional[str] = None,
    google_review_link: Optional[str] = None,
) -> Optional["NpsSurvey"]:
    """Queue an NPS survey for a completed job. Returns the survey record."""
    from app.models_tooling import NpsSurvey

    if not email:
        return None

    token = secrets.token_urlsafe(32)
    survey = NpsSurvey(
        account_id=account_id,
        token=token,
        customer_name=customer_name,
        customer_email=email,
        job_type=job_type,
        review_link_google=google_review_link,
        status="queued",
    )
    db.session.add(survey)
    db.session.commit()
    return survey


def process_pending_nps_surveys(batch: int = 50) -> int:
    """Send queued NPS survey emails. Call daily from cron."""
    from app.models_tooling import NpsSurvey

    now = datetime.utcnow()
    pending = (
        NpsSurvey.query
        .filter_by(status="queued")
        .order_by(NpsSurvey.created_at)
        .limit(batch)
        .all()
    )

    sent = 0
    for survey in pending:
        business_name, _ = _get_account_info(survey.account_id)
        v = dict(
            name=survey.customer_name or "there",
            job_type=survey.job_type or "recent service",
            business_name=business_name,
            score_buttons=_score_buttons(survey.token),
        )
        subject = _SURVEY_SUBJECT.format(**v)
        html = _SURVEY_HTML.format(**v)
        try:
            from app.services.email_service import send_email
            send_email(to_email=survey.customer_email, subject=subject, html_body=html)
            survey.status = "sent"
            survey.sent_at = now
            sent += 1
        except Exception:
            log.exception("NPS survey send failed id=%s", survey.id)
            survey.status = "failed"

    if pending:
        db.session.commit()
    log.info("NPS surveys sent=%s", sent)
    return sent


def record_nps_response(token: str, score: int) -> Optional["NpsSurvey"]:
    """
    Record a customer's NPS score. Called from the public /nps/<token> route.
    Returns the survey record so the route can redirect appropriately.
    """
    from app.models_tooling import NpsSurvey

    survey = NpsSurvey.query.filter_by(token=token).first()
    if not survey or survey.score is not None:
        return survey  # already responded or not found

    survey.score = max(1, min(10, int(score)))
    survey.status = "responded"
    survey.responded_at = datetime.utcnow()
    db.session.commit()

    log.info("NPS response token=%s score=%s account=%s customer=%s",
             token, score, survey.account_id, survey.customer_name)

    # If score >= 7 and we have a Google review link, send a nudge email
    if survey.score >= 7 and survey.review_link_google and survey.customer_email:
        _send_review_nudge(survey)

    return survey


def _send_review_nudge(survey: "NpsSurvey") -> None:
    """Send a 'glad you're happy — please leave a review!' email."""
    business_name, _ = _get_account_info(survey.account_id)
    subject = f"Thanks for the kind words! One more ask..."
    html = (
        f"<p>Hi {survey.customer_name or 'there'},</p>"
        f"<p>We're so glad your <strong>{survey.job_type or 'service'}</strong> "
        f"went well!</p>"
        f"<p>If you have a moment, would you mind sharing that experience "
        f"on Google? It helps other homeowners find us and supports our "
        f"small local business.</p>"
        f'<p><a href="{survey.review_link_google}" '
        f'style="background:#4f46e5;color:#fff;padding:12px 24px;'
        f'border-radius:8px;text-decoration:none;font-weight:600;">'
        f"Leave a Google Review</a></p>"
        f"<p style='color:#6b7280;font-size:13px'>Thanks again — "
        f"{business_name}</p>"
    )
    try:
        from app.services.email_service import send_email
        send_email(to_email=survey.customer_email, subject=subject, html_body=html)
    except Exception:
        log.exception("NPS review nudge email failed survey=%s", survey.id)


def build_response_page(survey: Optional["NpsSurvey"], score: int) -> str:
    """Return a self-contained HTML page for the NPS response landing."""
    if survey is None or survey.score is None:
        return _THANKYOU_HTML.format(
            emoji="🤔", heading="Link not found",
            message="This survey link may have expired.", cta="",
        )

    if score >= 7:
        cta = _CTA_REVIEW.format(link=survey.review_link_google or "#") if survey.review_link_google else ""
        return _THANKYOU_HTML.format(
            emoji="🌟", heading="Thanks so much!",
            message="We're thrilled you had a great experience. "
                    "If you have a moment, we'd love a Google review!",
            cta=cta,
        )
    else:
        return _THANKYOU_HTML.format(
            emoji="💙", heading="Thanks for your honest feedback",
            message="We're sorry we didn't hit the mark. "
                    "Someone from our team will reach out shortly to make it right.",
            cta="",
        )
