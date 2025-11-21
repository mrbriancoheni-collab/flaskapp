# app/account/auto_budget_routes.py
"""
Auto-Budget Adjustment Routes

Provides UI and API endpoints for automatic budget management.
"""

from flask import Blueprint, render_template, request, jsonify, g
from app.auth.session_helpers import login_required
from app.services.auto_budget_service import AutoBudgetService
from app.db_utils import get_db_connection
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
            'send_notifications': data.get('send_notifications', True),
            # Safeguard settings
            'max_daily_change_pct': float(data.get('max_daily_change_pct', 20)),
            'max_weekly_change_pct': float(data.get('max_weekly_change_pct', 40)),
            'enable_gradual_ramp': data.get('enable_gradual_ramp', True),
            'ramp_days': int(data.get('ramp_days', 3)),
            'require_approval_threshold_pct': float(data.get('require_approval_threshold_pct', 30)),
            'enable_rollback': data.get('enable_rollback', False),
            'rollback_window_hours': int(data.get('rollback_window_hours', 24)),
            'rollback_performance_drop_pct': float(data.get('rollback_performance_drop_pct', 20)),
            'alert_threshold_pct': float(data.get('alert_threshold_pct', 15))
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


@auto_budget_bp.route("/api/pending-changes", methods=["GET"])
@login_required
def get_pending_changes():
    """Get pending budget changes awaiting approval."""
    user = g.user
    account_id = user.account_id if user and hasattr(user, 'account_id') else None
    customer_id = request.args.get('customer_id', '')
    status = request.args.get('status', 'pending')

    if not account_id or not customer_id:
        return jsonify({"error": "Missing account_id or customer_id"}), 400

    try:
        db = get_db_connection()
        service = AutoBudgetService(db)

        pending_changes = service.get_pending_changes(account_id, customer_id, status)

        # Convert datetime/Decimal to JSON-serializable
        for change in pending_changes:
            for date_field in ['created_at', 'updated_at', 'approved_at', 'rejected_at', 'expires_at']:
                if date_field in change and isinstance(change[date_field], datetime):
                    change[date_field] = change[date_field].isoformat()
            for decimal_field in ['current_daily_budget', 'proposed_daily_budget', 'change_amount', 'change_pct']:
                if decimal_field in change and hasattr(change[decimal_field], '__float__'):
                    change[decimal_field] = float(change[decimal_field])

        return jsonify({"success": True, "pending_changes": pending_changes})

    except Exception as e:
        logger.error(f"Error getting pending changes: {e}")
        return jsonify({"error": str(e)}), 500


@auto_budget_bp.route("/api/pending-changes/<int:change_id>/approve", methods=["POST"])
@login_required
def approve_pending_change(change_id):
    """Approve a pending budget change."""
    user = g.user
    account_id = user.account_id if user and hasattr(user, 'account_id') else None
    user_id = user.id if user else None

    if not account_id or not user_id:
        return jsonify({"error": "Missing account_id or user_id"}), 400

    try:
        db = get_db_connection()
        service = AutoBudgetService(db)

        success = service.approve_pending_change(change_id, user_id, execute_immediately=True)

        if success:
            return jsonify({"success": True, "message": "Budget change approved and applied"})
        else:
            return jsonify({"error": "Failed to approve change (not found or already processed)"}), 400

    except Exception as e:
        logger.error(f"Error approving pending change: {e}")
        return jsonify({"error": str(e)}), 500


@auto_budget_bp.route("/api/pending-changes/<int:change_id>/reject", methods=["POST"])
@login_required
def reject_pending_change(change_id):
    """Reject a pending budget change."""
    user = g.user
    account_id = user.account_id if user and hasattr(user, 'account_id') else None
    user_id = user.id if user else None

    data = request.get_json() or {}
    rejection_reason = data.get('rejection_reason', 'Manually rejected by user')

    if not account_id or not user_id:
        return jsonify({"error": "Missing account_id or user_id"}), 400

    try:
        db = get_db_connection()
        service = AutoBudgetService(db)

        success = service.reject_pending_change(change_id, user_id, rejection_reason)

        if success:
            return jsonify({"success": True, "message": "Budget change rejected"})
        else:
            return jsonify({"error": "Failed to reject change (not found or already processed)"}), 400

    except Exception as e:
        logger.error(f"Error rejecting pending change: {e}")
        return jsonify({"error": str(e)}), 500
