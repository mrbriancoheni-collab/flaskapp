# app/account/auto_budget_routes.py
"""
Auto-Budget Adjustment Routes

Provides UI and API endpoints for automatic budget management.
"""

from flask import Blueprint, render_template, request, jsonify, g
from app.auth.session_helpers import login_required
from app.services.auto_budget_service import AutoBudgetService
from app.db import get_db_connection
from datetime import datetime, timedelta, date
import logging

logger = logging.getLogger(__name__)

auto_budget_bp = Blueprint("auto_budget", __name__, url_prefix="/account/auto-budget")


@auto_budget_bp.route("/")
@login_required
def dashboard():
    """Auto-budget dashboard page."""
    user = g.user
    account_id = user.account_id if user and hasattr(user, 'account_id') else None

    # Check if budget groups exist
    budget_groups_count = 0
    customer_id = None
    if account_id:
        try:
            db = get_db_connection()
            cursor = db.cursor(dictionary=True)

            # Get customer_id from first campaign
            cursor.execute(
                "SELECT google_customer_id FROM ads_campaigns WHERE account_id = %s AND google_customer_id IS NOT NULL LIMIT 1",
                (account_id,)
            )
            row = cursor.fetchone()
            if row:
                customer_id = row['google_customer_id']

            # Count budget groups for this account/customer
            if customer_id:
                cursor.execute(
                    "SELECT COUNT(*) as count FROM budget_groups WHERE account_id = %s AND customer_id = %s",
                    (account_id, customer_id)
                )
                result = cursor.fetchone()
                budget_groups_count = result['count'] if result else 0

            cursor.close()
            db.close()
        except Exception as e:
            logger.error(f"Error checking budget groups: {e}")

    return render_template(
        "account/auto_budget_dashboard.html",
        user=user,
        account_id=account_id,
        customer_id=customer_id,
        budget_groups_count=budget_groups_count
    )


@auto_budget_bp.route("/api/settings", methods=["GET"])
@login_required
def get_settings():
    """Get auto-budget settings for the account."""
    user = g.user
    account_id = user.account_id if user and hasattr(user, 'account_id') else None
    customer_id = request.args.get('customer_id', '')

    if not account_id or not customer_id:
        return jsonify({"error": "Missing account_id or customer_id"}), 400

    try:
        db = get_db_connection()
        service = AutoBudgetService(db)
        settings = service.get_settings(account_id, customer_id)

        if settings:
            # Convert Decimal to float for JSON
            for key, value in settings.items():
                if hasattr(value, '__float__'):
                    settings[key] = float(value)

        return jsonify({"success": True, "settings": settings})

    except Exception as e:
        logger.error(f"Error getting settings: {e}")
        return jsonify({"error": str(e)}), 500


@auto_budget_bp.route("/api/settings", methods=["POST"])
@login_required
def save_settings():
    """Save auto-budget settings."""
    user = g.user
    account_id = user.account_id if user and hasattr(user, 'account_id') else None

    data = request.get_json()
    customer_id = data.get('customer_id', '')

    if not account_id or not customer_id:
        return jsonify({"error": "Missing account_id or customer_id"}), 400

    try:
        db = get_db_connection()
        service = AutoBudgetService(db)

        settings = {
            'enabled': data.get('enabled', False),
            'monthly_budget_target': float(data.get('monthly_budget_target', 0)),
            'min_daily_budget': float(data.get('min_daily_budget', 10)),
            'max_daily_budget': float(data.get('max_daily_budget', 1000)),
            'adjustment_frequency': data.get('adjustment_frequency', 'daily'),
            'performance_weight': float(data.get('performance_weight', 0.70)),
            'seasonality_weight': float(data.get('seasonality_weight', 0.20)),
            'capacity_weight': float(data.get('capacity_weight', 0.10)),
            'send_notifications': data.get('send_notifications', True)
        }

        success = service.save_settings(account_id, customer_id, settings)

        if success:
            return jsonify({"success": True, "message": "Settings saved successfully"})
        else:
            return jsonify({"error": "Failed to save settings"}), 500

    except Exception as e:
        logger.error(f"Error saving settings: {e}")
        return jsonify({"error": str(e)}), 500


@auto_budget_bp.route("/api/calculate-adjustments", methods=["POST"])
@login_required
def calculate_adjustments():
    """Calculate recommended budget adjustments."""
    user = g.user
    account_id = user.account_id if user and hasattr(user, 'account_id') else None

    data = request.get_json()
    customer_id = data.get('customer_id', '')
    campaigns = data.get('campaigns', [])
    seasonality_data = data.get('seasonality_data')
    capacity_utilization = data.get('capacity_utilization')

    if not account_id or not customer_id:
        return jsonify({"error": "Missing account_id or customer_id"}), 400

    try:
        db = get_db_connection()
        service = AutoBudgetService(db)

        adjustments = service.calculate_budget_adjustments(
            account_id,
            customer_id,
            campaigns,
            seasonality_data,
            capacity_utilization
        )

        return jsonify({"success": True, "adjustments": adjustments})

    except Exception as e:
        logger.error(f"Error calculating adjustments: {e}")
        return jsonify({"error": str(e)}), 500


@auto_budget_bp.route("/api/history", methods=["GET"])
@login_required
def get_history():
    """Get budget change history."""
    user = g.user
    account_id = user.account_id if user and hasattr(user, 'account_id') else None
    customer_id = request.args.get('customer_id', '')
    limit = int(request.args.get('limit', 100))

    if not account_id or not customer_id:
        return jsonify({"error": "Missing account_id or customer_id"}), 400

    try:
        db = get_db_connection()
        service = AutoBudgetService(db)

        changes = service.get_budget_change_history(account_id, customer_id, limit)

        # Convert datetime/Decimal to JSON-serializable
        for change in changes:
            if 'created_at' in change and isinstance(change['created_at'], datetime):
                change['created_at'] = change['created_at'].isoformat()
            for key in ['old_budget', 'new_budget', 'change_amount', 'change_pct',
                        'projected_monthly_spend', 'actual_monthly_spend', 'confidence_score']:
                if key in change and hasattr(change[key], '__float__'):
                    change[key] = float(change[key])

        return jsonify({"success": True, "history": changes})

    except Exception as e:
        logger.error(f"Error getting history: {e}")
        return jsonify({"error": str(e)}), 500


@auto_budget_bp.route("/api/log-change", methods=["POST"])
@login_required
def log_change():
    """Log a budget change."""
    user = g.user
    account_id = user.account_id if user and hasattr(user, 'account_id') else None

    data = request.get_json()

    if not account_id:
        return jsonify({"error": "Missing account_id"}), 400

    try:
        db = get_db_connection()
        service = AutoBudgetService(db)

        success = service.log_budget_change(
            account_id=account_id,
            customer_id=data.get('customer_id', ''),
            campaign_id=data.get('campaign_id', ''),
            campaign_name=data.get('campaign_name', ''),
            change_type=data.get('change_type', 'decrease'),
            old_budget=float(data.get('old_budget', 0)),
            new_budget=float(data.get('new_budget', 0)),
            reason=data.get('reason', ''),
            triggered_by=data.get('triggered_by', 'auto'),
            agent_id=data.get('agent_id'),
            confidence_score=float(data.get('confidence_score')) if data.get('confidence_score') else None
        )

        if success:
            return jsonify({"success": True, "message": "Change logged successfully"})
        else:
            return jsonify({"error": "Failed to log change"}), 500

    except Exception as e:
        logger.error(f"Error logging change: {e}")
        return jsonify({"error": str(e)}), 500


@auto_budget_bp.route("/api/notifications", methods=["GET"])
@login_required
def get_notifications():
    """Get notifications for the user."""
    user = g.user
    account_id = user.account_id if user and hasattr(user, 'account_id') else None
    user_id = user.id if user else None
    unread_only = request.args.get('unread_only', 'false').lower() == 'true'
    limit = int(request.args.get('limit', 50))

    if not account_id:
        return jsonify({"error": "Missing account_id"}), 400

    try:
        db = get_db_connection()
        service = AutoBudgetService(db)

        notifications = service.get_notifications(account_id, user_id, unread_only, limit)

        # Convert datetime to JSON-serializable
        for notif in notifications:
            for date_field in ['created_at', 'read_at', 'dismissed_at']:
                if date_field in notif and isinstance(notif[date_field], datetime):
                    notif[date_field] = notif[date_field].isoformat()

        return jsonify({"success": True, "notifications": notifications})

    except Exception as e:
        logger.error(f"Error getting notifications: {e}")
        return jsonify({"error": str(e)}), 500


@auto_budget_bp.route("/api/create-notification", methods=["POST"])
@login_required
def create_notification():
    """Create a notification."""
    user = g.user
    account_id = user.account_id if user and hasattr(user, 'account_id') else None

    data = request.get_json()

    if not account_id:
        return jsonify({"error": "Missing account_id"}), 400

    try:
        db = get_db_connection()
        service = AutoBudgetService(db)

        success = service.create_notification(
            account_id=account_id,
            user_id=data.get('user_id'),
            notification_type=data.get('notification_type', 'budget_change'),
            severity=data.get('severity', 'info'),
            title=data.get('title', ''),
            message=data.get('message', ''),
            action_url=data.get('action_url'),
            related_entity_type=data.get('related_entity_type'),
            related_entity_id=data.get('related_entity_id'),
            metadata=data.get('metadata')
        )

        if success:
            return jsonify({"success": True, "message": "Notification created"})
        else:
            return jsonify({"error": "Failed to create notification"}), 500

    except Exception as e:
        logger.error(f"Error creating notification: {e}")
        return jsonify({"error": str(e)}), 500
