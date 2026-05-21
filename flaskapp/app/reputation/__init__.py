# app/reputation/__init__.py
"""
Reputation Dashboard — unified view of reviews across Google (GMB) and Yelp,
with AI-powered response drafts.

Routes:
  GET  /account/reputation              — dashboard
  POST /account/reputation/draft        — generate AI response draft (AJAX)
  POST /account/reputation/respond      — submit a response via GMB/Yelp API
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from flask import (
    Blueprint, jsonify, redirect, render_template, request, session, url_for,
)
from sqlalchemy import text

from app import db

log = logging.getLogger(__name__)

reputation_bp = Blueprint("reputation_bp", __name__)

# ── Auth helpers ───────────────────────────────────────────────────────────────

def _current_account_id() -> Optional[int]:
    aid = session.get("account_id") or session.get("aid")
    if aid:
        try:
            return int(aid)
        except Exception:
            pass
    uid = session.get("user_id")
    if not uid:
        return None
    try:
        row = db.session.execute(
            text("SELECT account_id FROM users WHERE id=:id"), {"id": uid}
        ).fetchone()
        return int(row[0]) if row else None
    except Exception:
        return None


def _login_required(f):
    from functools import wraps
    @wraps(f)
    def wrapper(*a, **kw):
        if not _current_account_id():
            return redirect(url_for("auth_bp.login", next=request.path))
        return f(*a, **kw)
    return wrapper


# ── Review aggregation ─────────────────────────────────────────────────────────

SAMPLE_REVIEWS: List[Dict[str, Any]] = [
    {
        "id": "gmb_1", "source": "google", "source_label": "Google",
        "source_icon": "fa-google", "source_color": "blue",
        "author": "Sarah M.", "rating": 5,
        "text": "Absolutely amazing service! They fixed our AC in 2 hours and the technician was super professional.",
        "date": datetime.utcnow() - timedelta(days=2),
        "responded": False, "response": None,
    },
    {
        "id": "gmb_2", "source": "google", "source_label": "Google",
        "source_icon": "fa-google", "source_color": "blue",
        "author": "Tom R.", "rating": 4,
        "text": "Good job overall. Arrived on time and did what they said they would. Pricing was fair.",
        "date": datetime.utcnow() - timedelta(days=5),
        "responded": True,
        "response": "Thanks Tom! Really appreciate you taking the time.",
    },
    {
        "id": "gmb_3", "source": "google", "source_label": "Google",
        "source_icon": "fa-google", "source_color": "blue",
        "author": "Anonymous", "rating": 3,
        "text": "The work was fine but they were 45 minutes late without calling ahead.",
        "date": datetime.utcnow() - timedelta(days=8),
        "responded": False, "response": None,
    },
    {
        "id": "yelp_1", "source": "yelp", "source_label": "Yelp",
        "source_icon": "fa-yelp", "source_color": "red",
        "author": "Jessica L.", "rating": 5,
        "text": "Best HVAC company in the area! Have used them twice now and they never disappoint.",
        "date": datetime.utcnow() - timedelta(days=3),
        "responded": False, "response": None,
    },
    {
        "id": "yelp_2", "source": "yelp", "source_label": "Yelp",
        "source_icon": "fa-yelp", "source_color": "red",
        "author": "Marcus B.", "rating": 2,
        "text": "Charged me for parts I didn't need. Will not be using again.",
        "date": datetime.utcnow() - timedelta(days=12),
        "responded": False, "response": None,
    },
]


def _fetch_gmb_reviews(account_id: int) -> List[Dict[str, Any]]:
    """Fetch GMB reviews from DB or return empty list if not connected."""
    try:
        from app.services.gmb_insights import get_recent_reviews
        raw = get_recent_reviews(account_id) or []
        out = []
        for r in raw:
            out.append({
                "id": f"gmb_{r.get('reviewId', r.get('id', ''))}",
                "source": "google",
                "source_label": "Google",
                "source_icon": "fa-google",
                "source_color": "blue",
                "author": r.get("reviewer", {}).get("displayName", "Anonymous"),
                "rating": {"ONE": 1, "TWO": 2, "THREE": 3, "FOUR": 4, "FIVE": 5}.get(
                    r.get("starRating", ""), 0
                ),
                "text": r.get("comment", ""),
                "date": datetime.fromisoformat(r["createTime"][:19]) if r.get("createTime") else datetime.utcnow(),
                "responded": bool(r.get("reviewReply")),
                "response": (r.get("reviewReply") or {}).get("comment"),
            })
        return out
    except Exception:
        return []


def _fetch_yelp_reviews(account_id: int) -> List[Dict[str, Any]]:
    """Fetch Yelp reviews."""
    try:
        try:
            from app.services.yelp_insights import get_recent_reviews as yelp_reviews
        except ImportError:
            return []
        raw = yelp_reviews(account_id) or []
        out = []
        for r in raw:
            out.append({
                "id": f"yelp_{r.get('id', '')}",
                "source": "yelp",
                "source_label": "Yelp",
                "source_icon": "fa-yelp",
                "source_color": "red",
                "author": r.get("user", {}).get("name", "Anonymous"),
                "rating": r.get("rating", 0),
                "text": r.get("text", ""),
                "date": datetime.fromisoformat(r["time_created"][:19]) if r.get("time_created") else datetime.utcnow(),
                "responded": False,
                "response": None,
            })
        return out
    except Exception:
        return []


def _aggregate_reviews(account_id: int, use_sample: bool = False) -> List[Dict[str, Any]]:
    if use_sample:
        reviews = list(SAMPLE_REVIEWS)
    else:
        reviews = _fetch_gmb_reviews(account_id) + _fetch_yelp_reviews(account_id)
        if not reviews:
            reviews = list(SAMPLE_REVIEWS)

    reviews.sort(key=lambda r: r.get("date") or datetime.min, reverse=True)
    return reviews


def _compute_stats(reviews: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not reviews:
        return {"avg_rating": 0, "total": 0, "unanswered": 0, "by_rating": {}}
    total = len(reviews)
    avg = sum(r["rating"] for r in reviews) / total
    unanswered = sum(1 for r in reviews if not r["responded"])
    by_source = {}
    for r in reviews:
        src = r["source"]
        if src not in by_source:
            by_source[src] = {"count": 0, "total_rating": 0, "label": r["source_label"]}
        by_source[src]["count"] += 1
        by_source[src]["total_rating"] += r["rating"]
    for s in by_source.values():
        s["avg"] = round(s["total_rating"] / s["count"], 1) if s["count"] else 0
    return {
        "avg_rating": round(avg, 1),
        "total": total,
        "unanswered": unanswered,
        "by_source": by_source,
    }


# ── AI response draft ──────────────────────────────────────────────────────────

def _generate_response_draft(review_text: str, rating: int, business_name: str = "us") -> str:
    """Generate an AI review response draft via OpenAI/Claude."""
    try:
        from app.ai_clients import claude_response
        tone = "warm and grateful" if rating >= 4 else "empathetic and solution-focused"
        prompt = (
            f"You are a professional responding to a {rating}-star review for a local home services business. "
            f"Write a concise, {tone} response (2-3 sentences max). "
            f"Do NOT be sycophantic. Address the specific feedback. "
            f"Sign off with 'The {business_name} Team'.\n\n"
            f"Review: {review_text}"
        )
        return claude_response(prompt)
    except Exception:
        # Fallback templates
        if rating >= 4:
            return (
                f"Thank you so much for the kind words! We're thrilled you had a great experience "
                f"and look forward to helping you again in the future. "
                f"— The {business_name} Team"
            )
        return (
            f"We appreciate your honest feedback and are sorry to hear your experience fell short of expectations. "
            f"We'd love the chance to make this right — please reach out to us directly. "
            f"— The {business_name} Team"
        )


# ── Routes ─────────────────────────────────────────────────────────────────────

@reputation_bp.route("/account/reputation")
@_login_required
def dashboard():
    account_id = _current_account_id()
    source_filter = request.args.get("source", "all")
    rating_filter = request.args.get("rating", "all")
    show_unanswered = request.args.get("unanswered") == "1"

    reviews = _aggregate_reviews(account_id)
    is_sample = len(_fetch_gmb_reviews(account_id)) == 0 and len(_fetch_yelp_reviews(account_id)) == 0

    if source_filter != "all":
        reviews = [r for r in reviews if r["source"] == source_filter]
    if rating_filter != "all":
        reviews = [r for r in reviews if str(r["rating"]) == rating_filter]
    if show_unanswered:
        reviews = [r for r in reviews if not r["responded"]]

    stats = _compute_stats(reviews)

    return render_template(
        "reputation/index.html",
        reviews=reviews,
        stats=stats,
        source_filter=source_filter,
        rating_filter=rating_filter,
        show_unanswered=show_unanswered,
        is_sample=is_sample,
    )


@reputation_bp.route("/account/reputation/draft", methods=["POST"])
@_login_required
def draft_response():
    """Generate an AI response draft for a review (AJAX)."""
    data = request.get_json(silent=True) or {}
    review_text = data.get("text", "")
    rating = int(data.get("rating", 5))
    draft = _generate_response_draft(review_text, rating)
    return jsonify({"draft": draft})


@reputation_bp.route("/account/reputation/respond", methods=["POST"])
@_login_required
def respond_to_review():
    """
    Submit a response to a review via GMB or Yelp API.

    Accepts JSON: {"review_id": "...", "source": "google"|"yelp", "response_text": "..."}
    """
    aid = _current_account_id()
    data = request.get_json(silent=True) or {}
    review_id = (data.get("review_id") or "").strip()
    source = (data.get("source") or "").lower()
    response_text = (data.get("response_text") or "").strip()

    if not review_id or not source or not response_text:
        return jsonify({"ok": False, "error": "review_id, source, and response_text are required"}), 400

    if source == "google":
        # GMB API posting is not yet available — inform the user clearly
        return jsonify({
            "ok": False,
            "error": (
                "GMB API posting is not yet available — copy and paste your response "
                "into Google Business Profile directly at https://business.google.com"
            ),
        })
    elif source == "yelp":
        # Yelp Partner API does not permit third-party response posting.
        # Store the draft locally so the user can copy-paste it.
        try:
            from app.models_tooling import ReviewRequest
            local = ReviewRequest(
                account_id=aid,
                channel="email",      # not a real send — used as storage
                recipient="yelp_local",
                status="queued",
                payload={
                    "type": "yelp_response_draft",
                    "review_id": review_id,
                    "response_text": response_text,
                },
            )
            db.session.add(local)
            db.session.commit()
        except Exception:
            log.exception("Failed to store Yelp response draft for account %s", aid)

        return jsonify({
            "ok": False,
            "error": (
                "Yelp's API does not allow third-party review responses. "
                "Your response draft has been saved — please log in to Yelp for Business "
                "and post it directly."
            ),
        })
    else:
        return jsonify({"ok": False, "error": f"Unknown source: {source}"}), 400


# ── Review Request helpers ─────────────────────────────────────────────────────

def _get_business_name(account_id: int) -> str:
    """Return the business name from business_profiles, falling back to a generic default."""
    try:
        from app.models import BusinessProfile
        profile = BusinessProfile.query.filter_by(account_id=account_id).first()
        if profile and profile.business_name:
            return profile.business_name
    except Exception:
        pass
    return "Your Service Team"


def _send_review_request_email(req) -> bool:
    """
    Build and send a branded review-request email to the customer.

    Marks req.status = 'sent' or 'failed' and sets req.sent_at on success.
    Returns True on success, False on failure.
    """
    try:
        from app.services.email_service import send_email

        business_name = _get_business_name(req.account_id)
        customer_name = req.customer_name or "Valued Customer"
        job_type = req.job_type or "your recent service"
        google_url = req.review_link_google or ""
        yelp_url = req.review_link_yelp or ""

        # Build review link buttons
        btn_style = (
            "display:inline-block;padding:12px 24px;border-radius:6px;"
            "font-size:15px;font-weight:600;text-decoration:none;color:#ffffff;"
        )
        google_btn = (
            f'<a href="{google_url}" style="{btn_style}background:#4285F4;" target="_blank">'
            f'&#9733; Review us on Google</a>'
            if google_url else ""
        )
        yelp_btn = (
            f'<a href="{yelp_url}" style="{btn_style}background:#d32323;margin-left:12px;" target="_blank">'
            f'&#9733; Review us on Yelp</a>'
            if yelp_url else ""
        )
        review_buttons = google_btn + yelp_btn

        html_body = f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:24px;color:#1f2937;">
  <h2 style="color:#1f2937;margin-bottom:4px;">How did we do, {customer_name}?</h2>
  <p style="color:#6b7280;margin-top:0;">Thank you for choosing <strong>{business_name}</strong>
     for {job_type}.</p>
  <p>We'd love to hear about your experience! Your feedback helps us continue providing
     excellent service and helps other homeowners find us.</p>
  <p>If you have a moment, please leave us a quick review:</p>
  <div style="text-align:center;margin:32px 0;">
    {review_buttons}
  </div>
  <p style="color:#9ca3af;font-size:13px;">
    It only takes 60 seconds and makes a huge difference for our small business. Thank you!
  </p>
  <hr style="border:none;border-top:1px solid #e5e7eb;margin:24px 0;">
  <p style="color:#9ca3af;font-size:12px;">
    — The {business_name} Team
  </p>
</body>
</html>
"""
        text_body = (
            f"Hi {customer_name},\n\n"
            f"Thank you for choosing {business_name} for {job_type}.\n\n"
            f"We'd love to hear about your experience! Please leave us a quick review:\n"
        )
        if google_url:
            text_body += f"  Google: {google_url}\n"
        if yelp_url:
            text_body += f"  Yelp: {yelp_url}\n"
        text_body += f"\nThank you!\n— The {business_name} Team"

        subject = f"How did we do, {customer_name}?"
        ok = send_email(
            to=req.recipient,
            subject=subject,
            html_body=html_body,
            text_body=text_body,
            from_name=business_name,
        )

        if ok:
            req.status = "sent"
            req.sent_at = datetime.utcnow()
        else:
            req.status = "failed"

        db.session.commit()
        return ok

    except Exception:
        log.exception("_send_review_request_email failed for ReviewRequest id=%s", getattr(req, "id", None))
        try:
            req.status = "failed"
            db.session.commit()
        except Exception:
            pass
        return False


def _auto_queue_review_requests(aid: int) -> int:
    """
    Find all ServiceTitan jobs with status='Completed' in the last 24 hours for this
    account, create a ReviewRequest for any that don't already have one, and send
    the email immediately.

    Returns the count of new requests sent.
    """
    sent_count = 0
    try:
        from app.models import ServiceTitanJob, ServiceTitanCustomer
        from app.models_tooling import ReviewRequest, LeadIntakeConfig

        cutoff = datetime.utcnow() - timedelta(hours=24)

        recent_jobs = (
            ServiceTitanJob.query
            .filter(
                ServiceTitanJob.account_id == aid,
                ServiceTitanJob.job_status == "Completed",
                ServiceTitanJob.completed_date >= cutoff,
            )
            .all()
        )

        if not recent_jobs:
            return 0

        # Load review links from account config
        config = LeadIntakeConfig.query.filter_by(account_id=aid).first()
        google_url = config.review_link_google if config else None
        yelp_url = config.review_link_yelp if config else None

        for job in recent_jobs:
            try:
                # Check if we already sent a review request for this job
                existing = ReviewRequest.query.filter(
                    ReviewRequest.account_id == aid,
                    ReviewRequest.payload.op("->>")(db.literal_column("'st_job_id'")) == str(job.st_job_id),
                ).first()
                if existing:
                    continue

                # Look up the customer
                customer = None
                if job.st_customer_id:
                    customer = ServiceTitanCustomer.query.filter_by(
                        account_id=aid,
                        st_customer_id=job.st_customer_id,
                    ).first()

                if not customer or not customer.email:
                    log.debug(
                        "_auto_queue_review_requests: skipping job %s (no customer email)",
                        job.st_job_id,
                    )
                    continue

                req = ReviewRequest(
                    account_id=aid,
                    channel="email",
                    recipient=customer.email,
                    customer_name=customer.name,
                    job_type=job.job_type_name or "your recent service",
                    status="queued",
                    review_link_google=google_url,
                    review_link_yelp=yelp_url,
                    payload={"st_job_id": str(job.st_job_id)},
                )
                db.session.add(req)
                db.session.flush()  # get req.id before sending

                ok = _send_review_request_email(req)
                if ok:
                    sent_count += 1
                    log.info(
                        "_auto_queue_review_requests: sent review request to %s (job %s)",
                        customer.email, job.st_job_id,
                    )

            except Exception:
                log.exception(
                    "_auto_queue_review_requests: failed for job %s (account %s)",
                    getattr(job, "st_job_id", "?"), aid,
                )

        db.session.commit()

    except Exception:
        log.exception("_auto_queue_review_requests outer failure for account %s", aid)

    return sent_count


# ── Review Request routes ──────────────────────────────────────────────────────

@reputation_bp.route("/account/reputation/requests")
@_login_required
def review_requests_list():
    """List recent ReviewRequest records for the current account."""
    from app.models_tooling import ReviewRequest
    aid = _current_account_id()
    requests_qs = (
        ReviewRequest.query
        .filter_by(account_id=aid)
        .order_by(ReviewRequest.created_at.desc())
        .limit(100)
        .all()
    )
    return jsonify([
        {
            "id": r.id,
            "customer_name": r.customer_name,
            "recipient": r.recipient,
            "job_type": r.job_type,
            "status": r.status,
            "channel": r.channel,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "sent_at": r.sent_at.isoformat() if r.sent_at else None,
        }
        for r in requests_qs
    ])


@reputation_bp.route("/account/reputation/requests/send", methods=["POST"])
@_login_required
def send_review_request():
    """
    Create and immediately send a single review request.

    Accepts form fields: customer_name, email, job_type, google_url, yelp_url
    Returns JSON {"ok": true, "id": <int>}
    """
    from app.models_tooling import ReviewRequest

    aid = _current_account_id()
    customer_name = (request.form.get("customer_name") or "").strip()
    email = (request.form.get("email") or "").strip()
    job_type = (request.form.get("job_type") or "").strip()
    google_url = (request.form.get("google_url") or "").strip() or None
    yelp_url = (request.form.get("yelp_url") or "").strip() or None

    if not email:
        return jsonify({"ok": False, "error": "email is required"}), 400

    try:
        req = ReviewRequest(
            account_id=aid,
            channel="email",
            recipient=email,
            customer_name=customer_name or None,
            job_type=job_type or None,
            status="queued",
            review_link_google=google_url,
            review_link_yelp=yelp_url,
        )
        db.session.add(req)
        db.session.flush()

        _send_review_request_email(req)

        db.session.commit()
        return jsonify({"ok": True, "id": req.id})
    except Exception:
        log.exception("send_review_request failed for account %s", aid)
        return jsonify({"ok": False, "error": "Failed to send review request"}), 500


@reputation_bp.route("/account/reputation/requests/bulk-send", methods=["POST"])
@_login_required
def bulk_send_review_requests():
    """
    Send review requests to all eligible ServiceTitan customers who completed jobs
    in the last 30 days and haven't already received a review request.

    Returns JSON {"ok": true, "sent": <int>}
    """
    aid = _current_account_id()
    sent_count = 0

    try:
        from app.models import ServiceTitanJob, ServiceTitanCustomer
        from app.models_tooling import ReviewRequest, LeadIntakeConfig

        cutoff = datetime.utcnow() - timedelta(days=30)

        recent_jobs = (
            ServiceTitanJob.query
            .filter(
                ServiceTitanJob.account_id == aid,
                ServiceTitanJob.job_status == "Completed",
                ServiceTitanJob.completed_date >= cutoff,
            )
            .all()
        )

        config = LeadIntakeConfig.query.filter_by(account_id=aid).first()
        google_url = config.review_link_google if config else None
        yelp_url = config.review_link_yelp if config else None

        for job in recent_jobs:
            try:
                existing = ReviewRequest.query.filter(
                    ReviewRequest.account_id == aid,
                    ReviewRequest.payload.op("->>")(db.literal_column("'st_job_id'")) == str(job.st_job_id),
                ).first()
                if existing:
                    continue

                customer = None
                if job.st_customer_id:
                    customer = ServiceTitanCustomer.query.filter_by(
                        account_id=aid,
                        st_customer_id=job.st_customer_id,
                    ).first()

                if not customer or not customer.email:
                    continue

                req = ReviewRequest(
                    account_id=aid,
                    channel="email",
                    recipient=customer.email,
                    customer_name=customer.name,
                    job_type=job.job_type_name or "your recent service",
                    status="queued",
                    review_link_google=google_url,
                    review_link_yelp=yelp_url,
                    payload={"st_job_id": str(job.st_job_id)},
                )
                db.session.add(req)
                db.session.flush()

                ok = _send_review_request_email(req)
                if ok:
                    sent_count += 1

            except Exception:
                log.exception("bulk_send: failed for job %s", getattr(job, "st_job_id", "?"))

        db.session.commit()

    except Exception:
        log.exception("bulk_send_review_requests failed for account %s", aid)
        return jsonify({"ok": False, "error": "Bulk send failed"}), 500

    return jsonify({"ok": True, "sent": sent_count})
