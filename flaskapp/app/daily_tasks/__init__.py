# app/daily_tasks/__init__.py
"""
Daily Task Queue Module
Provides a simple "What to do today" task list for busy business owners.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from flask import (
    Blueprint,
    current_app,
    render_template,
    jsonify,
    request,
    session,
)
from sqlalchemy import text

from app import db
from app.auth.utils import login_required, current_account_id, is_paid_account

daily_tasks_bp = Blueprint("daily_tasks_bp", __name__, url_prefix="/account/today")


def _get_pending_reviews(aid: int) -> List[Dict[str, Any]]:
    """Get Google reviews that need a response."""
    try:
        with db.engine.connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT id, reviewer_name, star_rating, comment, create_time
                    FROM gmb_reviews
                    WHERE account_id = :aid
                      AND reply_text IS NULL
                      AND star_rating IS NOT NULL
                    ORDER BY create_time DESC
                    LIMIT 5
                """),
                {"aid": aid}
            ).mappings().all()
            return [dict(r) for r in rows]
    except Exception as e:
        current_app.logger.error(f"Error fetching pending reviews: {e}")
        return []


def _get_budget_status(aid: int) -> Dict[str, Any]:
    """Check budget spend status for the week."""
    try:
        with db.engine.connect() as conn:
            row = conn.execute(
                text("""
                    SELECT
                        SUM(cost_micros) / 1000000 as spent,
                        MAX(daily_budget_micros) * 7 / 1000000 as weekly_budget
                    FROM google_ads_campaigns
                    WHERE account_id = :aid
                      AND status = 'ENABLED'
                """),
                {"aid": aid}
            ).mappings().first()
            if row:
                spent = float(row.get("spent") or 0)
                budget = float(row.get("weekly_budget") or 0)
                return {
                    "spent": spent,
                    "budget": budget,
                    "remaining": max(0, budget - spent),
                    "percent_used": int((spent / budget * 100) if budget > 0 else 0)
                }
    except Exception:
        pass
    return {"spent": 0, "budget": 0, "remaining": 0, "percent_used": 0}


def _get_paused_campaigns(aid: int) -> List[Dict[str, Any]]:
    """Get campaigns that are paused and might need attention."""
    try:
        with db.engine.connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT id, name, status
                    FROM google_ads_campaigns
                    WHERE account_id = :aid
                      AND status = 'PAUSED'
                    LIMIT 5
                """),
                {"aid": aid}
            ).mappings().all()
            return [dict(r) for r in rows]
    except Exception:
        return []


def _get_pending_recommendations(aid: int) -> int:
    """Count pending AI recommendations to review."""
    try:
        with db.engine.connect() as conn:
            row = conn.execute(
                text("""
                    SELECT COUNT(*) as cnt
                    FROM google_ads_recommendations
                    WHERE account_id = :aid
                      AND status = 'PENDING'
                """),
                {"aid": aid}
            ).mappings().first()
            return int(row.get("cnt") or 0) if row else 0
    except Exception:
        return 0


def _has_gmb_connected(aid: int) -> bool:
    """Check if GMB is connected."""
    try:
        with db.engine.connect() as conn:
            row = conn.execute(
                text("SELECT 1 FROM google_oauth_tokens WHERE account_id = :aid AND product = 'gmb' LIMIT 1"),
                {"aid": aid}
            ).first()
            return bool(row)
    except Exception:
        return False


def _has_google_ads_connected(aid: int) -> bool:
    """Check if Google Ads is connected."""
    try:
        with db.engine.connect() as conn:
            row = conn.execute(
                text("SELECT 1 FROM google_oauth_tokens WHERE account_id = :aid AND product = 'ads' LIMIT 1"),
                {"aid": aid}
            ).first()
            return bool(row)
    except Exception:
        return False


def _has_facebook_connected(aid: int) -> bool:
    """Check if Facebook is connected."""
    try:
        with db.engine.connect() as conn:
            row = conn.execute(
                text("SELECT 1 FROM fb_tokens WHERE account_id = :aid LIMIT 1"),
                {"aid": aid}
            ).first()
            return bool(row)
    except Exception:
        return False


def generate_daily_tasks(aid: int) -> List[Dict[str, Any]]:
    """
    Generate a personalized list of 3-5 daily tasks for the business owner.
    Tasks are prioritized by impact and time-sensitivity.
    """
    tasks = []
    today = datetime.now()
    completed_key = f"completed_tasks_{aid}_{today.strftime('%Y-%m-%d')}"
    completed_tasks = session.get(completed_key, [])

    # Task 1: Review replies needed
    if _has_gmb_connected(aid):
        pending_reviews = _get_pending_reviews(aid)
        if pending_reviews and "reviews" not in completed_tasks:
            tasks.append({
                "id": "reviews",
                "icon": "fa-star",
                "icon_color": "text-yellow-500",
                "bg_color": "bg-yellow-50",
                "title": f"Reply to {len(pending_reviews)} new review{'s' if len(pending_reviews) > 1 else ''}",
                "description": "Responding to reviews improves your local ranking and builds trust.",
                "action_url": "/account/gmb/reviews",
                "action_text": "Reply Now",
                "priority": "high",
                "time_estimate": "5 min",
                "impact": "high"
            })

    # Task 2: Budget check
    if _has_google_ads_connected(aid):
        budget = _get_budget_status(aid)
        if budget["percent_used"] >= 80 and "budget" not in completed_tasks:
            tasks.append({
                "id": "budget",
                "icon": "fa-wallet",
                "icon_color": "text-orange-500",
                "bg_color": "bg-orange-50",
                "title": f"Budget {budget['percent_used']}% spent",
                "description": f"${budget['remaining']:.0f} remaining this week. Consider adjusting if needed.",
                "action_url": "/account/google/ads/budget",
                "action_text": "Review Budget",
                "priority": "medium",
                "time_estimate": "3 min",
                "impact": "medium"
            })

        # Task 3: AI recommendations
        rec_count = _get_pending_recommendations(aid)
        if rec_count > 0 and "recommendations" not in completed_tasks:
            tasks.append({
                "id": "recommendations",
                "icon": "fa-lightbulb",
                "icon_color": "text-indigo-500",
                "bg_color": "bg-indigo-50",
                "title": f"Review {rec_count} AI suggestion{'s' if rec_count > 1 else ''}",
                "description": "Our AI found opportunities to improve your campaigns.",
                "action_url": "/account/google/ads/opportunities",
                "action_text": "View Suggestions",
                "priority": "medium",
                "time_estimate": "5 min",
                "impact": "high"
            })

        # Task 4: Paused campaigns
        paused = _get_paused_campaigns(aid)
        if paused and "paused" not in completed_tasks:
            tasks.append({
                "id": "paused",
                "icon": "fa-pause-circle",
                "icon_color": "text-gray-500",
                "bg_color": "bg-gray-50",
                "title": f"{len(paused)} campaign{'s' if len(paused) > 1 else ''} paused",
                "description": "You have campaigns that aren't running. Enable them to get more leads.",
                "action_url": "/account/google/ads",
                "action_text": "Review Campaigns",
                "priority": "low",
                "time_estimate": "2 min",
                "impact": "high"
            })

    # Task 5: Weekly check-in (always show on Mondays or if nothing else)
    if (today.weekday() == 0 or len(tasks) == 0) and "weekly" not in completed_tasks:
        tasks.append({
            "id": "weekly",
            "icon": "fa-chart-line",
            "icon_color": "text-green-500",
            "bg_color": "bg-green-50",
            "title": "Check your weekly performance",
            "description": "See how your marketing performed last week.",
            "action_url": "/account/reports",
            "action_text": "View Report",
            "priority": "low",
            "time_estimate": "5 min",
            "impact": "medium"
        })

    # If no connected services, show setup task
    if not _has_gmb_connected(aid) and not _has_google_ads_connected(aid):
        tasks = [{
            "id": "setup",
            "icon": "fa-plug",
            "icon_color": "text-indigo-600",
            "bg_color": "bg-indigo-50",
            "title": "Connect your first marketing channel",
            "description": "Link Google Ads or Google Business Profile to get started.",
            "action_url": "/account/dashboard",
            "action_text": "Get Started",
            "priority": "high",
            "time_estimate": "5 min",
            "impact": "critical"
        }]

    # Sort by priority
    priority_order = {"high": 0, "medium": 1, "low": 2}
    tasks.sort(key=lambda x: priority_order.get(x.get("priority", "low"), 2))

    return tasks[:5]  # Max 5 tasks


def calculate_health_score(aid: int) -> Dict[str, Any]:
    """
    Calculate a Marketing Health Score (0-100) with component breakdown.
    """
    score = 0
    components = []

    # Component 1: Google Business Profile (25 points)
    gmb_score = 0
    gmb_status = "Not connected"
    if _has_gmb_connected(aid):
        gmb_score = 15  # Base for being connected
        pending = len(_get_pending_reviews(aid))
        if pending == 0:
            gmb_score = 25
            gmb_status = "Excellent"
        elif pending <= 2:
            gmb_score = 20
            gmb_status = f"{pending} need reply"
        else:
            gmb_status = f"{pending} need reply"
    components.append({
        "name": "Google Business",
        "score": gmb_score,
        "max": 25,
        "status": gmb_status,
        "icon": "fa-store",
        "color": "indigo" if gmb_score >= 20 else "yellow" if gmb_score >= 10 else "gray"
    })
    score += gmb_score

    # Component 2: Google Ads (25 points)
    ads_score = 0
    ads_status = "Not connected"
    if _has_google_ads_connected(aid):
        ads_score = 10
        budget = _get_budget_status(aid)
        paused = _get_paused_campaigns(aid)
        if budget["budget"] > 0:
            ads_score += 10
            if len(paused) == 0:
                ads_score += 5
                ads_status = "Active"
            else:
                ads_status = f"{len(paused)} paused"
        else:
            ads_status = "No budget"
    components.append({
        "name": "Google Ads",
        "score": ads_score,
        "max": 25,
        "status": ads_status,
        "icon": "fa-ad",
        "color": "indigo" if ads_score >= 20 else "yellow" if ads_score >= 10 else "gray"
    })
    score += ads_score

    # Component 3: Review Response Rate (25 points)
    review_score = 0
    review_status = "No data"
    try:
        with db.engine.connect() as conn:
            row = conn.execute(
                text("""
                    SELECT
                        COUNT(*) as total,
                        SUM(CASE WHEN reply_text IS NOT NULL THEN 1 ELSE 0 END) as replied
                    FROM gmb_reviews
                    WHERE account_id = :aid
                """),
                {"aid": aid}
            ).mappings().first()
            if row and row.get("total"):
                total = int(row.get("total") or 0)
                replied = int(row.get("replied") or 0)
                rate = (replied / total * 100) if total > 0 else 0
                if rate >= 90:
                    review_score = 25
                    review_status = f"{rate:.0f}%"
                elif rate >= 70:
                    review_score = 20
                    review_status = f"{rate:.0f}%"
                elif rate >= 50:
                    review_score = 15
                    review_status = f"{rate:.0f}%"
                else:
                    review_score = 10
                    review_status = f"{rate:.0f}%"
    except Exception:
        pass
    components.append({
        "name": "Review Rate",
        "score": review_score,
        "max": 25,
        "status": review_status,
        "icon": "fa-comments",
        "color": "green" if review_score >= 20 else "yellow" if review_score >= 10 else "gray"
    })
    score += review_score

    # Component 4: Campaign Performance (25 points)
    perf_score = 0
    perf_status = "No data"
    try:
        with db.engine.connect() as conn:
            row = conn.execute(
                text("""
                    SELECT
                        SUM(conversions) as conversions,
                        SUM(clicks) as clicks,
                        SUM(cost_micros) / 1000000 as cost
                    FROM google_ads_campaigns
                    WHERE account_id = :aid
                      AND status = 'ENABLED'
                """),
                {"aid": aid}
            ).mappings().first()
            if row and row.get("clicks"):
                conversions = float(row.get("conversions") or 0)
                clicks = int(row.get("clicks") or 0)
                cost = float(row.get("cost") or 0)
                if conversions > 0 and cost > 0:
                    cpa = cost / conversions
                    if cpa < 50:
                        perf_score = 25
                        perf_status = f"${cpa:.0f} CPA"
                    elif cpa < 100:
                        perf_score = 20
                        perf_status = f"${cpa:.0f} CPA"
                    elif cpa < 200:
                        perf_score = 15
                        perf_status = f"${cpa:.0f} CPA"
                    else:
                        perf_score = 10
                        perf_status = f"${cpa:.0f} CPA"
                elif clicks > 0:
                    perf_score = 10
                    perf_status = f"{clicks} clicks"
    except Exception:
        pass
    components.append({
        "name": "Performance",
        "score": perf_score,
        "max": 25,
        "status": perf_status,
        "icon": "fa-chart-line",
        "color": "green" if perf_score >= 20 else "yellow" if perf_score >= 10 else "gray"
    })
    score += perf_score

    # Determine grade
    if score >= 90:
        grade = "A"
        grade_color = "text-green-600"
        bg_color = "bg-green-100"
        message = "Excellent! Your marketing is in great shape."
    elif score >= 75:
        grade = "B"
        grade_color = "text-blue-600"
        bg_color = "bg-blue-100"
        message = "Good work! A few improvements could boost results."
    elif score >= 60:
        grade = "C"
        grade_color = "text-yellow-600"
        bg_color = "bg-yellow-100"
        message = "Fair. Focus on the items below to improve."
    elif score >= 40:
        grade = "D"
        grade_color = "text-orange-600"
        bg_color = "bg-orange-100"
        message = "Needs attention. Let's get things back on track."
    else:
        grade = "F"
        grade_color = "text-red-600"
        bg_color = "bg-red-100"
        message = "Critical. Connect your accounts to start improving."

    return {
        "score": score,
        "max_score": 100,
        "grade": grade,
        "grade_color": grade_color,
        "bg_color": bg_color,
        "message": message,
        "components": components
    }


# -------------------- Routes --------------------

@daily_tasks_bp.route("/", methods=["GET"])
@login_required
def index():
    """Daily task queue view."""
    aid = current_account_id()
    if not aid:
        return jsonify({"error": "Account not found"}), 404

    tasks = generate_daily_tasks(aid)
    health = calculate_health_score(aid)

    return render_template(
        "daily_tasks/index.html",
        tasks=tasks,
        health=health,
        is_paid=is_paid_account(),
        today=datetime.now()
    )


@daily_tasks_bp.route("/api/tasks", methods=["GET"])
@login_required
def api_tasks():
    """API endpoint for fetching tasks."""
    aid = current_account_id()
    if not aid:
        return jsonify({"error": "Account not found"}), 404

    tasks = generate_daily_tasks(aid)
    return jsonify({"tasks": tasks})


@daily_tasks_bp.route("/api/health", methods=["GET"])
@login_required
def api_health():
    """API endpoint for health score."""
    aid = current_account_id()
    if not aid:
        return jsonify({"error": "Account not found"}), 404

    health = calculate_health_score(aid)
    return jsonify(health)


@daily_tasks_bp.route("/api/complete/<task_id>", methods=["POST"])
@login_required
def complete_task(task_id: str):
    """Mark a task as completed for today."""
    aid = current_account_id()
    if not aid:
        return jsonify({"error": "Account not found"}), 404

    today = datetime.now()
    completed_key = f"completed_tasks_{aid}_{today.strftime('%Y-%m-%d')}"
    completed = session.get(completed_key, [])
    if task_id not in completed:
        completed.append(task_id)
        session[completed_key] = completed

    return jsonify({"success": True, "completed": completed})


@daily_tasks_bp.route("/api/dismiss/<task_id>", methods=["POST"])
@login_required
def dismiss_task(task_id: str):
    """Dismiss a task for today without completing it."""
    return complete_task(task_id)
