# app/google/skimmer_routes.py
"""
Skimmer CRM integration routes.

Blueprint: skimmer_bp
Prefix:    /account/integrations/skimmer
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)

from app import db
from app.auth.utils import login_required, current_account_id

logger = logging.getLogger(__name__)

skimmer_bp = Blueprint(
    "skimmer_bp",
    __name__,
    url_prefix="/account/integrations/skimmer",
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _load_auth(account_id: int):
    """Return SkimmerAuth row or None."""
    from app.models_skimmer import SkimmerAuth
    try:
        return SkimmerAuth.query.filter_by(account_id=account_id).first()
    except Exception as exc:
        logger.warning("Could not load SkimmerAuth for account %s: %s", account_id, exc)
        return None


def _validate_webhook_hmac(secret: str, payload_bytes: bytes, sig_header: str) -> bool:
    """Return True if the Zapier webhook HMAC-SHA256 signature matches."""
    expected = hmac.new(
        secret.encode("utf-8"),
        payload_bytes,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, (sig_header or "").strip())


# ─────────────────────────────────────────────────────────────────────────────
# GET / — Dashboard
# ─────────────────────────────────────────────────────────────────────────────

@skimmer_bp.get("/")
@login_required
def dashboard():
    """Render the Skimmer integration dashboard."""
    from app.models_skimmer import SkimmerAuth, SkimmerJob

    aid = current_account_id()
    auth = _load_auth(aid)

    recent_jobs = []
    try:
        recent_jobs = (
            SkimmerJob.query
            .filter_by(account_id=aid)
            .order_by(SkimmerJob.created_at.desc())
            .limit(20)
            .all()
        )
    except Exception as exc:
        logger.warning("Could not load recent Skimmer jobs for account %s: %s", aid, exc)

    webhook_url = (
        request.host_url.rstrip("/")
        + url_for("skimmer_bp.webhook")
    )

    return render_template(
        "integrations/skimmer.html",
        auth=auth,
        recent_jobs=recent_jobs,
        webhook_url=webhook_url,
    )


# ─────────────────────────────────────────────────────────────────────────────
# POST /save — Save / update SkimmerAuth
# ─────────────────────────────────────────────────────────────────────────────

@skimmer_bp.post("/save")
@login_required
def save():
    """Save (or update) Skimmer API key and settings."""
    from app.models_skimmer import SkimmerAuth
    from app.services.crypto import encrypt

    aid = current_account_id()
    auth = _load_auth(aid)

    api_key_raw = (request.form.get("api_key") or "").strip()
    webhook_secret = (request.form.get("webhook_secret") or "").strip() or None
    delay_hours_raw = request.form.get("review_request_delay_hours", "24")
    review_template = (request.form.get("review_request_template") or "").strip() or None

    try:
        delay_hours = int(delay_hours_raw)
    except (TypeError, ValueError):
        delay_hours = 24

    try:
        if auth is None:
            if not api_key_raw:
                flash("Please enter your Skimmer API key.", "error")
                return redirect(url_for("skimmer_bp.dashboard"))
            auth = SkimmerAuth(account_id=aid)
            db.session.add(auth)

        if api_key_raw:
            auth.api_key_encrypted = encrypt(api_key_raw)

        auth.webhook_secret = webhook_secret
        auth.review_request_delay_hours = delay_hours
        auth.review_request_template = review_template
        db.session.commit()
        flash("Skimmer settings saved.", "success")
    except Exception as exc:
        db.session.rollback()
        logger.exception("Error saving SkimmerAuth for account %s", aid)
        flash(f"Error saving settings: {exc}", "error")

    return redirect(url_for("skimmer_bp.dashboard"))


# ─────────────────────────────────────────────────────────────────────────────
# POST /sync — Trigger full sync
# ─────────────────────────────────────────────────────────────────────────────

@skimmer_bp.post("/sync")
@login_required
def sync():
    """Run a full Skimmer sync and return JSON results."""
    from app.services.skimmer_sync import run_full_sync

    aid = current_account_id()
    try:
        result = run_full_sync(aid)
        return jsonify({"ok": True, "result": result})
    except Exception as exc:
        logger.exception("run_full_sync failed for account %s", aid)
        return jsonify({"ok": False, "error": str(exc)}), 500


# ─────────────────────────────────────────────────────────────────────────────
# GET /jobs.json — Last 50 jobs as JSON
# ─────────────────────────────────────────────────────────────────────────────

@skimmer_bp.get("/jobs.json")
@login_required
def jobs_json():
    """Return the last 50 Skimmer jobs for this account as JSON."""
    from app.models_skimmer import SkimmerJob

    aid = current_account_id()
    try:
        jobs = (
            SkimmerJob.query
            .filter_by(account_id=aid)
            .order_by(SkimmerJob.created_at.desc())
            .limit(50)
            .all()
        )
        rows = [
            {
                "id": j.id,
                "customer_name": j.customer_name,
                "service_type": j.service_type,
                "status": j.status,
                "completed_at": j.completed_at.isoformat() if j.completed_at else None,
                "invoice_total_cents": j.invoice_total_cents,
                "matched_gclid": j.matched_gclid,
                "match_method": getattr(j, "match_method", None),
                "offline_conv_pushed_at": (
                    j.offline_conv_pushed_at.isoformat() if j.offline_conv_pushed_at else None
                ),
                "offline_conv_status": j.offline_conv_status,
                "review_sent_at": j.review_sent_at.isoformat() if j.review_sent_at else None,
            }
            for j in jobs
        ]
        return jsonify(rows)
    except Exception as exc:
        logger.exception("jobs_json failed for account %s", aid)
        return jsonify({"error": str(exc)}), 500


# ─────────────────────────────────────────────────────────────────────────────
# GET /stats.json — Summary stats
# ─────────────────────────────────────────────────────────────────────────────

@skimmer_bp.get("/stats.json")
@login_required
def stats_json():
    """Return summary statistics for the Skimmer integration dashboard."""
    from app.models_skimmer import SkimmerJob
    from sqlalchemy import func

    aid = current_account_id()
    try:
        first_of_month = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        base = SkimmerJob.query.filter_by(account_id=aid)

        total_jobs = base.count()
        matched_jobs = base.filter(SkimmerJob.matched_gclid.isnot(None)).count()
        conversions_pushed = base.filter(SkimmerJob.offline_conv_pushed_at.isnot(None)).count()
        reviews_sent = base.filter(SkimmerJob.review_sent_at.isnot(None)).count()

        # Revenue this calendar month (paid/invoiced jobs)
        month_revenue_row = (
            db.session.query(func.sum(SkimmerJob.invoice_total_cents))
            .filter(
                SkimmerJob.account_id == aid,
                SkimmerJob.status.in_(["completed", "invoiced", "paid"]),
                SkimmerJob.completed_at >= first_of_month,
            )
            .scalar()
        )
        this_month_revenue_cents = int(month_revenue_row or 0)

        return jsonify({
            "total_jobs": total_jobs,
            "matched_jobs": matched_jobs,
            "conversions_pushed": conversions_pushed,
            "reviews_sent": reviews_sent,
            "this_month_revenue_cents": this_month_revenue_cents,
        })
    except Exception as exc:
        logger.exception("stats_json failed for account %s", aid)
        return jsonify({"error": str(exc)}), 500


# ─────────────────────────────────────────────────────────────────────────────
# POST /webhook — Zapier webhook fallback
# ─────────────────────────────────────────────────────────────────────────────

@skimmer_bp.post("/webhook")
def webhook():
    """
    Accept a Zapier webhook with Skimmer job data.

    Validates HMAC-SHA256 signature if webhook_secret is configured on the
    SkimmerAuth row.  The account is identified by the ?account_id= query param
    or the X-Account-Id header.
    """
    from app.models_skimmer import SkimmerAuth, SkimmerJob
    from app.services.skimmer_sync import normalize_phone

    # Resolve account_id from query param or header
    raw_account_id = (
        request.args.get("account_id")
        or request.headers.get("X-Account-Id")
        or ""
    ).strip()

    if not raw_account_id:
        return jsonify({"error": "account_id required"}), 400

    try:
        account_id = int(raw_account_id)
    except ValueError:
        return jsonify({"error": "account_id must be an integer"}), 400

    payload_bytes = request.get_data()

    # Load auth and optionally validate HMAC
    try:
        auth = SkimmerAuth.query.filter_by(account_id=account_id).first()
        if not auth:
            return jsonify({"error": "Account not configured for Skimmer"}), 403

        if auth.webhook_secret:
            sig = request.headers.get("X-Webhook-Signature", "")
            if not sig:
                return jsonify({"error": "Missing X-Webhook-Signature header"}), 401
            if not _validate_webhook_hmac(auth.webhook_secret, payload_bytes, sig):
                return jsonify({"error": "Invalid webhook signature"}), 403
    except Exception as exc:
        logger.exception("Webhook auth check failed for account %s", account_id)
        return jsonify({"error": str(exc)}), 500

    # Parse payload
    try:
        payload = request.get_json(force=True) or {}
    except Exception:
        return jsonify({"error": "Invalid JSON payload"}), 400

    if not payload:
        return jsonify({"error": "Empty payload"}), 400

    # Build SkimmerJob from payload
    try:
        job_id = str(payload.get("id") or payload.get("work_order_id") or "").strip()
        if not job_id:
            return jsonify({"error": "Missing job id in payload"}), 400

        raw_status = (payload.get("status") or "completed").lower().strip()
        raw_phone = (payload.get("customer_phone") or payload.get("phone") or "").strip()
        phone_e164 = normalize_phone(raw_phone) if raw_phone else None

        # Parse completed_at
        completed_at_raw = payload.get("completed_at") or payload.get("completed_date")
        completed_at: Optional[datetime] = None
        if completed_at_raw:
            import re
            for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                try:
                    completed_at = datetime.strptime(
                        re.sub(r"[Z+].*$", "", str(completed_at_raw)).strip(), fmt
                    )
                    break
                except ValueError:
                    continue

        invoice_raw = payload.get("invoice_total") or payload.get("total")
        invoice_cents: Optional[int] = None
        if invoice_raw is not None:
            try:
                invoice_cents = int(float(invoice_raw) * 100)
            except (TypeError, ValueError):
                pass

        existing = SkimmerJob.query.filter_by(
            account_id=account_id,
            skimmer_job_id=job_id,
        ).first()

        is_new = existing is None
        job = existing or SkimmerJob(account_id=account_id, skimmer_job_id=job_id)

        job.customer_name = payload.get("customer_name")
        job.customer_email = payload.get("customer_email") or payload.get("email")
        job.customer_phone = raw_phone or None
        job.customer_phone_e164 = phone_e164
        job.skimmer_customer_id = str(payload.get("customer_id") or "").strip() or None
        job.service_address = payload.get("service_address") or payload.get("address")
        job.service_type = payload.get("service_type") or payload.get("job_type")
        job.status = raw_status
        if completed_at:
            job.completed_at = completed_at
        if invoice_cents is not None:
            job.invoice_total_cents = invoice_cents
        job.raw_json = json.dumps(payload)

        if is_new:
            db.session.add(job)

        db.session.commit()
        return jsonify({"ok": True, "job_id": job_id, "new": is_new})
    except Exception as exc:
        db.session.rollback()
        logger.exception("Webhook job upsert failed for account %s", account_id)
        return jsonify({"error": str(exc)}), 500


# ─────────────────────────────────────────────────────────────────────────────
# GET /match-stats.json — GCLID match method breakdown
# ─────────────────────────────────────────────────────────────────────────────

@skimmer_bp.get("/match-stats.json")
@login_required
def match_stats_json():
    """
    Return counts for each GCLID capture method and overall match rate.

    JSON schema:
      phone_count     — active PhoneGclidMap rows for this account
      email_count     — active EmailGclidMap rows for this account (0 if model absent)
      call_view_count — SkimmerJob rows matched via call_view
      manual_count    — SkimmerJob rows matched via manual upload
      total_matched   — SkimmerJob rows with a matched_gclid
      total_unmatched — SkimmerJob rows without a matched_gclid
      match_rate      — percentage matched (0-100, rounded to 1 dp)
    """
    from app.models_skimmer import PhoneGclidMap, SkimmerJob
    from sqlalchemy import func

    # EmailGclidMap may not exist yet (parallel agent)
    try:
        from app.models_skimmer import EmailGclidMap
        _has_email = True
    except ImportError:
        _has_email = False

    aid = current_account_id()

    try:
        phone_count = PhoneGclidMap.query.filter_by(account_id=aid).count()
    except Exception:
        phone_count = 0

    try:
        email_count = EmailGclidMap.query.filter_by(account_id=aid).count() if _has_email else 0
    except Exception:
        email_count = 0

    try:
        base = SkimmerJob.query.filter_by(account_id=aid)
        total_jobs = base.count()
        total_matched = base.filter(SkimmerJob.matched_gclid.isnot(None)).count()
        total_unmatched = total_jobs - total_matched

        # match_method counts — only available if column exists
        try:
            call_view_count = base.filter(SkimmerJob.match_method == "call_view").count()
            manual_count = base.filter(SkimmerJob.match_method == "manual").count()
        except Exception:
            call_view_count = 0
            manual_count = 0

        match_rate = round(100 * total_matched / total_jobs, 1) if total_jobs else 0.0
    except Exception as exc:
        logger.warning("match_stats_json failed for account %s: %s", aid, exc)
        return jsonify({"error": str(exc)}), 500

    return jsonify({
        "phone_count": phone_count,
        "email_count": email_count,
        "call_view_count": call_view_count,
        "manual_count": manual_count,
        "total_matched": total_matched,
        "total_unmatched": total_unmatched,
        "match_rate": match_rate,
    })


# ─────────────────────────────────────────────────────────────────────────────
# POST /toggle-reviews — Toggle review requests on/off
# ─────────────────────────────────────────────────────────────────────────────

@skimmer_bp.post("/toggle-reviews")
@login_required
def toggle_reviews():
    """Toggle review_requests_enabled on SkimmerAuth; returns JSON."""
    from app.models_skimmer import SkimmerAuth

    aid = current_account_id()
    try:
        auth = SkimmerAuth.query.filter_by(account_id=aid).first()
        if not auth:
            return jsonify({"error": "Skimmer not configured"}), 404
        auth.review_requests_enabled = not auth.review_requests_enabled
        db.session.commit()
        return jsonify({"ok": True, "review_requests_enabled": auth.review_requests_enabled})
    except Exception as exc:
        db.session.rollback()
        logger.exception("toggle_reviews failed for account %s", aid)
        return jsonify({"error": str(exc)}), 500
