# app/social_calendar/__init__.py
"""
Unified Social Media Calendar blueprint.
Covers Facebook, Instagram, YouTube, and LinkedIn.
URL prefix: /account/social-calendar
"""
from __future__ import annotations

import logging
from datetime import date, datetime

from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from flask_login import login_required

from app import db
from app.auth.utils import current_account_id
from app.models_social_calendar import SocialCalendarPost

logger = logging.getLogger(__name__)

social_calendar_bp = Blueprint(
    "social_calendar_bp",
    __name__,
    url_prefix="/account/social-calendar",
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _get_year_month():
    """Return (year, month) from query params, defaulting to today."""
    today = date.today()
    try:
        year = int(request.args.get("year", today.year))
    except (ValueError, TypeError):
        year = today.year
    try:
        month = int(request.args.get("month", today.month))
    except (ValueError, TypeError):
        month = today.month
    # Clamp month to 1-12
    month = max(1, min(12, month))
    return year, month


# ---------------------------------------------------------------------------
# Index — unified monthly calendar
# ---------------------------------------------------------------------------

@social_calendar_bp.route("/")
@login_required
def index():
    """Unified social media calendar — monthly grid + upcoming list."""
    account_id = current_account_id()
    if not account_id:
        flash("Unable to determine account.", "error")
        return redirect(url_for("account_bp.dashboard"))

    platform = request.args.get("platform", "").strip().lower() or None
    year, month = _get_year_month()

    # All posts for the selected month
    posts = SocialCalendarPost.get_for_account(
        account_id,
        platform=platform,
        year=year,
        month=month,
    )

    # Upcoming posts (for the list below the calendar)
    upcoming = SocialCalendarPost.get_upcoming(account_id, platform=platform, limit=30)

    # Build a dict keyed by day number for the calendar grid
    posts_by_day: dict[int, list[dict]] = {}
    for p in posts:
        day = p.scheduled_date.day
        posts_by_day.setdefault(day, []).append(p.to_dict())

    # Calendar grid data: first weekday of the month (0=Mon…6=Sun) and days in month
    import calendar
    first_weekday, days_in_month = calendar.monthrange(year, month)
    # Convert to Sunday-first (Sun=0)
    first_weekday_sun = (first_weekday + 1) % 7

    # Previous / next month navigation
    if month == 1:
        prev_year, prev_month = year - 1, 12
    else:
        prev_year, prev_month = year, month - 1

    if month == 12:
        next_year, next_month = year + 1, 1
    else:
        next_year, next_month = year, month + 1

    month_name = datetime(year, month, 1).strftime("%B")

    return render_template(
        "social_calendar/index.html",
        platform=platform or "all",
        year=year,
        month=month,
        month_name=month_name,
        days_in_month=days_in_month,
        first_weekday_sun=first_weekday_sun,
        posts_by_day=posts_by_day,
        upcoming=upcoming,
        today=date.today(),
        prev_year=prev_year,
        prev_month=prev_month,
        next_year=next_year,
        next_month=next_month,
        post_types=SocialCalendarPost.POST_TYPES,
        char_limits=SocialCalendarPost.CHAR_LIMITS,
    )


# ---------------------------------------------------------------------------
# API — posts as JSON (for AJAX calendar refresh)
# ---------------------------------------------------------------------------

@social_calendar_bp.route("/api/posts")
@login_required
def api_posts():
    """Return posts as JSON. Accepts ?platform=&year=&month="""
    account_id = current_account_id()
    if not account_id:
        return jsonify({"error": "Unable to determine account"}), 400

    platform = request.args.get("platform", "").strip().lower() or None
    year, month = _get_year_month()

    try:
        posts = SocialCalendarPost.get_for_account(
            account_id,
            platform=platform,
            year=year,
            month=month,
        )
        return jsonify({"posts": [p.to_dict() for p in posts], "count": len(posts)})
    except Exception:
        logger.exception("Error fetching social calendar posts")
        return jsonify({"error": "Server error"}), 500


# ---------------------------------------------------------------------------
# Add post
# ---------------------------------------------------------------------------

@social_calendar_bp.route("/post/add", methods=["POST"])
@login_required
def post_add():
    """Create a new social calendar post. Returns JSON."""
    account_id = current_account_id()
    if not account_id:
        return jsonify({"error": "Unable to determine account"}), 400

    try:
        data = request.get_json(silent=True) or request.form

        platform = (data.get("platform") or "").strip().lower()
        if platform not in ("facebook", "instagram", "youtube", "linkedin"):
            return jsonify({"error": "Invalid platform"}), 400

        scheduled_date_str = (data.get("scheduled_date") or "").strip()
        if not scheduled_date_str:
            return jsonify({"error": "Scheduled date is required"}), 400

        try:
            scheduled_date = datetime.strptime(scheduled_date_str, "%Y-%m-%d").date()
        except ValueError:
            return jsonify({"error": "Invalid date format. Use YYYY-MM-DD"}), 400

        post = SocialCalendarPost(
            account_id=account_id,
            platform=platform,
            scheduled_date=scheduled_date,
            scheduled_time=(data.get("scheduled_time") or "09:00").strip(),
            post_type=(data.get("post_type") or "").strip() or None,
            copy_text=(data.get("copy_text") or "").strip() or None,
            title=(data.get("title") or "").strip() or None,
            link=(data.get("link") or "").strip() or None,
            campaign=(data.get("campaign") or "").strip() or None,
            creative_url=(data.get("creative_url") or "").strip() or None,
            post_owner=(data.get("post_owner") or "").strip() or None,
            status=(data.get("status") or "pending").strip(),
        )
        db.session.add(post)
        db.session.commit()

        return jsonify({"success": True, "post": post.to_dict()})

    except Exception:
        db.session.rollback()
        logger.exception("Error creating social calendar post")
        return jsonify({"error": "Server error"}), 500


# ---------------------------------------------------------------------------
# Update post
# ---------------------------------------------------------------------------

@social_calendar_bp.route("/post/<int:post_id>/update", methods=["POST"])
@login_required
def post_update(post_id):
    """Update an existing social calendar post. Returns JSON."""
    account_id = current_account_id()
    if not account_id:
        return jsonify({"error": "Unable to determine account"}), 400

    try:
        post = SocialCalendarPost.query.filter_by(id=post_id, account_id=account_id).first()
        if not post:
            return jsonify({"error": "Post not found"}), 404

        data = request.get_json(silent=True) or request.form

        if "platform" in data:
            platform = (data["platform"] or "").strip().lower()
            if platform not in ("facebook", "instagram", "youtube", "linkedin"):
                return jsonify({"error": "Invalid platform"}), 400
            post.platform = platform

        if "scheduled_date" in data:
            try:
                post.scheduled_date = datetime.strptime(data["scheduled_date"], "%Y-%m-%d").date()
            except ValueError:
                return jsonify({"error": "Invalid date format. Use YYYY-MM-DD"}), 400

        for field in ("scheduled_time", "post_type", "copy_text", "title", "link",
                      "campaign", "creative_url", "post_owner", "status"):
            if field in data:
                setattr(post, field, (data[field] or "").strip() or None)

        db.session.commit()
        return jsonify({"success": True, "post": post.to_dict()})

    except Exception:
        db.session.rollback()
        logger.exception("Error updating social calendar post")
        return jsonify({"error": "Server error"}), 500


# ---------------------------------------------------------------------------
# Delete post
# ---------------------------------------------------------------------------

@social_calendar_bp.route("/post/<int:post_id>/delete", methods=["POST"])
@login_required
def post_delete(post_id):
    """Delete a social calendar post. Returns JSON."""
    account_id = current_account_id()
    if not account_id:
        return jsonify({"error": "Unable to determine account"}), 400

    try:
        post = SocialCalendarPost.query.filter_by(id=post_id, account_id=account_id).first()
        if not post:
            return jsonify({"error": "Post not found"}), 404

        db.session.delete(post)
        db.session.commit()
        return jsonify({"success": True})

    except Exception:
        db.session.rollback()
        logger.exception("Error deleting social calendar post")
        return jsonify({"error": "Server error"}), 500
