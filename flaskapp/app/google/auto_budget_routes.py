# app/google/auto_budget_routes.py
"""
Auto-Budget Adjustment Routes - Dashboard and API endpoints for automatic budget management.
"""
from flask import Blueprint, render_template, jsonify, request
from sqlalchemy import text
from datetime import datetime, date, timedelta

from app import db
from app.auth.utils import login_required, current_account_id
from app.services.auto_budget_adjustment_service import (
    auto_adjust_campaign_budgets,
    get_adjustment_history,
    get_budget_status,
    send_budget_adjustment_notification
)
from app.services.capacity_tracking_service import (
    update_daily_capacity,
    log_booking,
    get_capacity_status,
    get_capacity_recommendations
)

auto_budget_bp = Blueprint("auto_budget_bp", __name__, url_prefix="/account/google/ads/auto-budget")


@auto_budget_bp.route("/")
@login_required
def auto_budget_dashboard():
    """
    Auto-Budget Management Dashboard - View settings, status, and adjustment history.
    """
    account_id = current_account_id()

    # Get auto-budget settings
    settings_query = text("""
        SELECT * FROM auto_budget_settings
        WHERE account_id = :account_id
    """)

    with db.engine.connect() as conn:
        result = conn.execute(settings_query, {"account_id": account_id})
        settings = result.first()

        if settings:
            settings = dict(settings._mapping)
        else:
            # Default settings
            settings = {
                "enabled": False,
                "total_monthly_budget_cents": 0,
                "min_daily_budget_cents": 1000,
                "max_daily_budget_cents": 100000,
                "max_adjustment_pct": 50.00,
                "enable_weather_adjustments": True,
                "enable_capacity_adjustments": True,
                "enable_competitive_adjustments": True,
                "enable_seasonality_adjustments": True,
                "notification_enabled": True
            }

    # Get campaigns
    campaigns_query = text("""
        SELECT id, name, daily_budget_cents, google_campaign_id
        FROM ads_campaigns
        WHERE account_id = :account_id
        ORDER BY name
    """)

    with db.engine.connect() as conn:
        result = conn.execute(campaigns_query, {"account_id": account_id})
        campaigns = [dict(row._mapping) for row in result]

    # Get recent adjustment history
    history = get_adjustment_history(account_id, days=30)

    # Get budget status
    budget_status = get_budget_status(account_id)

    return render_template(
        "google/auto_budget_dashboard.html",
        settings=settings,
        campaigns=campaigns,
        history=history,
        budget_status=budget_status
    )


@auto_budget_bp.route("/api/settings", methods=["GET", "POST"])
@login_required
def manage_settings():
    """Get or update auto-budget settings."""
    account_id = current_account_id()

    if request.method == "GET":
        query = text("SELECT * FROM auto_budget_settings WHERE account_id = :account_id")
        with db.engine.connect() as conn:
            result = conn.execute(query, {"account_id": account_id})
            settings = result.first()

            if settings:
                return jsonify({"success": True, "settings": dict(settings._mapping)})
            else:
                return jsonify({"success": False, "error": "No settings found"}), 404

    elif request.method == "POST":
        data = request.get_json()

        # Upsert settings
        query = text("""
            INSERT INTO auto_budget_settings
                (account_id, enabled, total_monthly_budget_cents, min_daily_budget_cents,
                 max_daily_budget_cents, max_adjustment_pct, min_adjustment_pct,
                 enable_weather_adjustments, enable_capacity_adjustments,
                 enable_competitive_adjustments, enable_seasonality_adjustments,
                 adjustment_frequency, notification_enabled)
            VALUES
                (:account_id, :enabled, :monthly_budget, :min_daily, :max_daily,
                 :max_pct, :min_pct, :weather, :capacity, :competitive, :seasonality,
                 :frequency, :notifications)
            ON DUPLICATE KEY UPDATE
                enabled = :enabled,
                total_monthly_budget_cents = :monthly_budget,
                min_daily_budget_cents = :min_daily,
                max_daily_budget_cents = :max_daily,
                max_adjustment_pct = :max_pct,
                min_adjustment_pct = :min_pct,
                enable_weather_adjustments = :weather,
                enable_capacity_adjustments = :capacity,
                enable_competitive_adjustments = :competitive,
                enable_seasonality_adjustments = :seasonality,
                adjustment_frequency = :frequency,
                notification_enabled = :notifications,
                updated_at = NOW()
        """)

        try:
            with db.engine.begin() as conn:
                conn.execute(query, {
                    "account_id": account_id,
                    "enabled": data.get("enabled", False),
                    "monthly_budget": data.get("total_monthly_budget_cents", 0),
                    "min_daily": data.get("min_daily_budget_cents", 1000),
                    "max_daily": data.get("max_daily_budget_cents", 100000),
                    "max_pct": data.get("max_adjustment_pct", 50.00),
                    "min_pct": data.get("min_adjustment_pct", 5.00),
                    "weather": data.get("enable_weather_adjustments", True),
                    "capacity": data.get("enable_capacity_adjustments", True),
                    "competitive": data.get("enable_competitive_adjustments", True),
                    "seasonality": data.get("enable_seasonality_adjustments", True),
                    "frequency": data.get("adjustment_frequency", "daily"),
                    "notifications": data.get("notification_enabled", True)
                })

            return jsonify({"success": True})

        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500


@auto_budget_bp.route("/api/adjust", methods=["POST"])
@login_required
def trigger_adjustment():
    """Manually trigger auto-budget adjustment."""
    account_id = current_account_id()
    data = request.get_json()

    # Get settings
    settings_query = text("SELECT * FROM auto_budget_settings WHERE account_id = :account_id")
    with db.engine.connect() as conn:
        result = conn.execute(settings_query, {"account_id": account_id})
        settings = result.first()

        if not settings:
            return jsonify({"success": False, "error": "Auto-budget not configured"}), 400

        settings = dict(settings._mapping)

    # Get campaigns
    campaigns_query = text("""
        SELECT id, name, daily_budget_cents, google_campaign_id, google_customer_id
        FROM ads_campaigns
        WHERE account_id = :account_id
    """)

    with db.engine.connect() as conn:
        result = conn.execute(campaigns_query, {"account_id": account_id})
        campaigns = [dict(row._mapping) for row in result]

    try:
        # Run auto-adjustment
        result = auto_adjust_campaign_budgets(
            account_id=account_id,
            total_monthly_budget=settings['total_monthly_budget_cents'] / 100,
            campaigns=campaigns,
            service_type=data.get('service_type', 'hvac_ac'),
            enable_notifications=settings['notification_enabled']
        )

        return jsonify(result)

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@auto_budget_bp.route("/api/history", methods=["GET"])
@login_required
def get_adjustment_history_api():
    """Get budget adjustment history."""
    account_id = current_account_id()
    days = request.args.get('days', 30, type=int)
    campaign_id = request.args.get('campaign_id', type=int)

    try:
        history = get_adjustment_history(account_id, days, campaign_id)
        return jsonify({"success": True, "history": history})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@auto_budget_bp.route("/api/status", methods=["GET"])
@login_required
def get_budget_status_api():
    """Get current budget status (spend MTD, remaining, pacing)."""
    account_id = current_account_id()

    try:
        status = get_budget_status(account_id)
        return jsonify({"success": True, "status": status})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@auto_budget_bp.route("/api/notifications", methods=["GET"])
@login_required
def get_notifications():
    """Get user notifications."""
    account_id = current_account_id()
    unread_only = request.args.get('unread_only', 'false').lower() == 'true'

    query_parts = ["SELECT * FROM user_notifications WHERE account_id = :account_id"]
    params = {"account_id": account_id}

    if unread_only:
        query_parts.append("AND is_read = FALSE")

    query_parts.append("ORDER BY created_at DESC LIMIT 50")
    query = text(" ".join(query_parts))

    with db.engine.connect() as conn:
        result = conn.execute(query, params)
        notifications = [dict(row._mapping) for row in result]

    return jsonify({"success": True, "notifications": notifications})


@auto_budget_bp.route("/api/notifications/<int:notification_id>/mark-read", methods=["POST"])
@login_required
def mark_notification_read(notification_id):
    """Mark a notification as read."""
    account_id = current_account_id()

    query = text("""
        UPDATE user_notifications
        SET is_read = TRUE, read_at = NOW()
        WHERE id = :notification_id AND account_id = :account_id
    """)

    try:
        with db.engine.begin() as conn:
            conn.execute(query, {
                "notification_id": notification_id,
                "account_id": account_id
            })

        return jsonify({"success": True})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# Capacity Tracking Routes
# ============================================================================

@auto_budget_bp.route("/capacity")
@login_required
def capacity_dashboard():
    """Capacity Tracking Dashboard - Manage tech capacity and bookings."""
    account_id = current_account_id()

    # Get capacity status for next 7 days
    capacity_status = get_capacity_status(account_id, days=7)

    # Get recent bookings
    bookings_query = text("""
        SELECT * FROM capacity_bookings
        WHERE account_id = :account_id
          AND booking_date >= CURDATE()
        ORDER BY booking_date, booking_time
        LIMIT 50
    """)

    with db.engine.connect() as conn:
        result = conn.execute(bookings_query, {"account_id": account_id})
        bookings = [dict(row._mapping) for row in result]

    # Get capacity recommendations
    recommendations = get_capacity_recommendations(account_id)

    return render_template(
        "google/capacity_dashboard.html",
        capacity_status=capacity_status,
        bookings=bookings,
        recommendations=recommendations
    )


@auto_budget_bp.route("/api/capacity/update", methods=["POST"])
@login_required
def update_capacity():
    """Update daily capacity (techs and slots)."""
    account_id = current_account_id()
    data = request.get_json()

    try:
        result = update_daily_capacity(
            account_id=account_id,
            service_type=data.get('service_type', 'hvac_ac'),
            target_date=datetime.strptime(data['date'], '%Y-%m-%d').date(),
            total_techs=data['total_techs'],
            slots_per_tech=data.get('slots_per_tech', 4),
            booked_slots=data.get('booked_slots')
        )

        return jsonify(result)

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@auto_budget_bp.route("/api/capacity/booking", methods=["POST"])
@login_required
def create_booking():
    """Log a new booking."""
    account_id = current_account_id()
    data = request.get_json()

    try:
        result = log_booking(
            account_id=account_id,
            service_type=data.get('service_type', 'hvac_ac'),
            booking_date=datetime.strptime(data['booking_date'], '%Y-%m-%d').date(),
            booking_time=data.get('booking_time'),
            customer_name=data.get('customer_name'),
            source=data.get('source', 'google_ads'),
            campaign_id=data.get('campaign_id'),
            job_type=data.get('job_type'),
            estimated_value_cents=data.get('estimated_value_cents')
        )

        return jsonify(result)

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@auto_budget_bp.route("/api/capacity/status", methods=["GET"])
@login_required
def get_capacity_status_api():
    """Get capacity status for date range."""
    account_id = current_account_id()
    days = request.args.get('days', 7, type=int)
    service_type = request.args.get('service_type')

    try:
        status = get_capacity_status(account_id, days, service_type)
        return jsonify({"success": True, "capacity": status})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
