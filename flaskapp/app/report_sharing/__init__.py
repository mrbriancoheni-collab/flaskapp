# app/report_sharing/__init__.py
"""
Report Sharing Module
Enables one-click PDF report generation and sharing.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from flask import (
    Blueprint,
    current_app,
    render_template,
    jsonify,
    request,
    redirect,
    url_for,
    flash,
)
from sqlalchemy import text

from app import db
from app.auth.utils import login_required, current_account_id, is_paid_account

report_sharing_bp = Blueprint("report_sharing_bp", __name__, url_prefix="/account/reports")


def _generate_share_token() -> str:
    """Generate a secure share token."""
    return secrets.token_urlsafe(32)


def _get_performance_summary(aid: int) -> Dict[str, Any]:
    """Get performance summary for the report."""
    summary = {
        "period": "Last 30 Days",
        "generated_at": datetime.now().isoformat(),
        "metrics": {}
    }

    try:
        with db.engine.connect() as conn:
            # Google Ads metrics
            ads_row = conn.execute(
                text("""
                    SELECT
                        SUM(cost_micros) / 1000000 as cost,
                        SUM(clicks) as clicks,
                        SUM(impressions) as impressions,
                        SUM(conversions) as conversions
                    FROM google_ads_campaigns
                    WHERE account_id = :aid
                      AND status = 'ENABLED'
                """),
                {"aid": aid}
            ).mappings().first()

            if ads_row:
                cost = float(ads_row.get("cost") or 0)
                clicks = int(ads_row.get("clicks") or 0)
                conversions = float(ads_row.get("conversions") or 0)

                summary["metrics"]["google_ads"] = {
                    "cost": cost,
                    "clicks": clicks,
                    "impressions": int(ads_row.get("impressions") or 0),
                    "conversions": conversions,
                    "ctr": (clicks / int(ads_row.get("impressions") or 1)) * 100,
                    "cpa": cost / conversions if conversions > 0 else 0
                }

            # GMB metrics
            gmb_row = conn.execute(
                text("""
                    SELECT
                        COUNT(*) as total_reviews,
                        AVG(star_rating) as avg_rating,
                        SUM(CASE WHEN reply_text IS NOT NULL THEN 1 ELSE 0 END) as replied
                    FROM gmb_reviews
                    WHERE account_id = :aid
                """),
                {"aid": aid}
            ).mappings().first()

            if gmb_row:
                total = int(gmb_row.get("total_reviews") or 0)
                replied = int(gmb_row.get("replied") or 0)
                summary["metrics"]["gmb"] = {
                    "total_reviews": total,
                    "avg_rating": float(gmb_row.get("avg_rating") or 0),
                    "response_rate": (replied / total * 100) if total > 0 else 0
                }

    except Exception as e:
        current_app.logger.error(f"Error getting performance summary: {e}")

    return summary


def create_shared_report(aid: int, title: str = "Monthly Performance Report") -> Optional[str]:
    """Create a shared report and return the share token."""
    token = _generate_share_token()
    expires_at = datetime.now() + timedelta(days=30)

    try:
        with db.engine.connect() as conn:
            conn.execute(
                text("""
                    INSERT INTO shared_reports (account_id, token, title, expires_at, created_at)
                    VALUES (:aid, :token, :title, :expires_at, NOW())
                """),
                {"aid": aid, "token": token, "title": title, "expires_at": expires_at}
            )
            conn.commit()
        return token
    except Exception as e:
        current_app.logger.error(f"Error creating shared report: {e}")
        return None


def get_shared_report(token: str) -> Optional[Dict[str, Any]]:
    """Get a shared report by token."""
    try:
        with db.engine.connect() as conn:
            row = conn.execute(
                text("""
                    SELECT sr.*, a.business_name
                    FROM shared_reports sr
                    JOIN accounts a ON sr.account_id = a.id
                    WHERE sr.token = :token
                      AND sr.expires_at > NOW()
                """),
                {"token": token}
            ).mappings().first()

            if row:
                report = dict(row)
                report["summary"] = _get_performance_summary(row["account_id"])
                return report
    except Exception as e:
        current_app.logger.error(f"Error getting shared report: {e}")
    return None


# -------------------- Routes --------------------

@report_sharing_bp.route("/share", methods=["GET"])
@login_required
def share_index():
    """Report sharing page."""
    aid = current_account_id()
    if not aid:
        return redirect(url_for("account_bp.dashboard"))

    summary = _get_performance_summary(aid)

    # Get existing shared reports
    shared_reports = []
    try:
        with db.engine.connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT id, token, title, expires_at, created_at, view_count
                    FROM shared_reports
                    WHERE account_id = :aid
                      AND expires_at > NOW()
                    ORDER BY created_at DESC
                    LIMIT 10
                """),
                {"aid": aid}
            ).mappings().all()
            shared_reports = [dict(r) for r in rows]
    except Exception:
        pass

    return render_template(
        "report_sharing/index.html",
        summary=summary,
        shared_reports=shared_reports,
        is_paid=is_paid_account()
    )


@report_sharing_bp.route("/share/create", methods=["POST"])
@login_required
def create_share():
    """Create a new shared report."""
    aid = current_account_id()
    if not aid:
        return jsonify({"error": "Account not found"}), 404

    title = request.form.get("title", "Monthly Performance Report")
    token = create_shared_report(aid, title)

    if token:
        share_url = url_for("report_sharing_bp.view_shared", token=token, _external=True)
        flash("Report link created! Share it with your team or clients.", "success")
        return redirect(url_for("report_sharing_bp.share_index"))
    else:
        flash("Failed to create share link. Please try again.", "error")
        return redirect(url_for("report_sharing_bp.share_index"))


@report_sharing_bp.route("/shared/<token>", methods=["GET"])
def view_shared(token: str):
    """View a shared report (no login required)."""
    report = get_shared_report(token)

    if not report:
        return render_template("report_sharing/expired.html"), 404

    # Increment view count
    try:
        with db.engine.connect() as conn:
            conn.execute(
                text("UPDATE shared_reports SET view_count = view_count + 1 WHERE token = :token"),
                {"token": token}
            )
            conn.commit()
    except Exception:
        pass

    return render_template(
        "report_sharing/shared_view.html",
        report=report
    )


@report_sharing_bp.route("/api/summary", methods=["GET"])
@login_required
def api_summary():
    """Get performance summary via API."""
    aid = current_account_id()
    if not aid:
        return jsonify({"error": "Account not found"}), 404

    summary = _get_performance_summary(aid)
    return jsonify(summary)
