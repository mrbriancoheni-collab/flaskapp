# app/account/budget_groups_routes.py
"""
Budget Groups Routes

Provides UI and API endpoints for managing budget groups and campaign assignments.
"""

from flask import Blueprint, render_template, request, jsonify, g
from app.auth.session_helpers import login_required
from app.services.budget_groups_service import BudgetGroupsService
from app.services.auto_budget_service import AutoBudgetService
from app.db import get_db
from datetime import datetime, date
import logging

logger = logging.getLogger(__name__)

budget_groups_bp = Blueprint("budget_groups", __name__, url_prefix="/account/budget-groups")


@budget_groups_bp.route("/")
@login_required
def dashboard():
    """Budget groups management page."""
    user = g.user
    account_id = user.account_id if user and hasattr(user, 'account_id') else None

    # For now, set customer_id to None - will be retrieved from user's Google Ads connection
    # TODO: Get from user's Google Ads account settings
    customer_id = None

    return render_template("account/budget_groups_dashboard.html", user=user, account_id=account_id, customer_id=customer_id)


# ==================== Budget Groups CRUD ====================

@budget_groups_bp.route("/api/groups", methods=["GET"])
@login_required
def get_groups():
    """Get all budget groups for the account."""
    user = g.user
    account_id = user.account_id if user and hasattr(user, 'account_id') else None
    customer_id = request.args.get('customer_id', '')
    enabled_only = request.args.get('enabled_only', 'false').lower() == 'true'

    if not account_id or not customer_id:
        return jsonify({"error": "Missing account_id or customer_id"}), 400

    try:
        db = get_db()
        service = BudgetGroupsService(db)
        groups = service.get_all_groups(account_id, customer_id, enabled_only)

        return jsonify({"success": True, "groups": groups})

    except Exception as e:
        logger.error(f"Error getting budget groups: {e}")
        return jsonify({"error": str(e)}), 500


@budget_groups_bp.route("/api/groups/<int:group_id>", methods=["GET"])
@login_required
def get_group(group_id):
    """Get a specific budget group."""
    user = g.user
    account_id = user.account_id if user and hasattr(user, 'account_id') else None

    if not account_id:
        return jsonify({"error": "Missing account_id"}), 400

    try:
        db = get_db()
        service = BudgetGroupsService(db)
        group = service.get_group(group_id, account_id)

        if not group:
            return jsonify({"error": "Budget group not found"}), 404

        return jsonify({"success": True, "group": group})

    except Exception as e:
        logger.error(f"Error getting budget group: {e}")
        return jsonify({"error": str(e)}), 500


@budget_groups_bp.route("/api/groups", methods=["POST"])
@login_required
def create_group():
    """Create a new budget group."""
    user = g.user
    account_id = user.account_id if user and hasattr(user, 'account_id') else None

    data = request.get_json()
    customer_id = data.get('customer_id', '')
    name = data.get('name', '')
    monthly_budget_target = float(data.get('monthly_budget_target', 0))

    if not account_id or not customer_id or not name or monthly_budget_target <= 0:
        return jsonify({"error": "Missing required fields"}), 400

    try:
        db = get_db()
        service = BudgetGroupsService(db)

        group_id = service.create_group(
            account_id=account_id,
            customer_id=customer_id,
            name=name,
            monthly_budget_target=monthly_budget_target,
            description=data.get('description'),
            industry=data.get('industry', 'hvac_heating'),
            color=data.get('color', '#3B82F6'),
            min_daily_budget=float(data.get('min_daily_budget', 10)),
            max_daily_budget=float(data.get('max_daily_budget', 1000)),
            enabled=data.get('enabled', True),
            adjustment_frequency=data.get('adjustment_frequency', 'daily'),
            performance_weight=float(data.get('performance_weight', 0.70)),
            seasonality_weight=float(data.get('seasonality_weight', 0.20)),
            capacity_weight=float(data.get('capacity_weight', 0.10)),
            send_notifications=data.get('send_notifications', True)
        )

        if group_id:
            return jsonify({"success": True, "group_id": group_id, "message": "Budget group created successfully"})
        else:
            return jsonify({"error": "Failed to create budget group"}), 500

    except Exception as e:
        logger.error(f"Error creating budget group: {e}")
        return jsonify({"error": str(e)}), 500


@budget_groups_bp.route("/api/groups/<int:group_id>", methods=["PUT"])
@login_required
def update_group(group_id):
    """Update a budget group."""
    user = g.user
    account_id = user.account_id if user and hasattr(user, 'account_id') else None

    if not account_id:
        return jsonify({"error": "Missing account_id"}), 400

    data = request.get_json()

    try:
        db = get_db()
        service = BudgetGroupsService(db)

        # Convert numeric values
        updates = {}
        for key, value in data.items():
            if key in ['monthly_budget_target', 'min_daily_budget', 'max_daily_budget',
                      'performance_weight', 'seasonality_weight', 'capacity_weight']:
                updates[key] = float(value)
            else:
                updates[key] = value

        success = service.update_group(group_id, account_id, updates)

        if success:
            return jsonify({"success": True, "message": "Budget group updated successfully"})
        else:
            return jsonify({"error": "Failed to update budget group"}), 500

    except Exception as e:
        logger.error(f"Error updating budget group: {e}")
        return jsonify({"error": str(e)}), 500


@budget_groups_bp.route("/api/groups/<int:group_id>", methods=["DELETE"])
@login_required
def delete_group(group_id):
    """Delete a budget group."""
    user = g.user
    account_id = user.account_id if user and hasattr(user, 'account_id') else None

    if not account_id:
        return jsonify({"error": "Missing account_id"}), 400

    try:
        db = get_db()
        service = BudgetGroupsService(db)
        success = service.delete_group(group_id, account_id)

        if success:
            return jsonify({"success": True, "message": "Budget group deleted successfully"})
        else:
            return jsonify({"error": "Failed to delete budget group"}), 500

    except Exception as e:
        logger.error(f"Error deleting budget group: {e}")
        return jsonify({"error": str(e)}), 500


# ==================== Campaign Assignments ====================

@budget_groups_bp.route("/api/groups/<int:group_id>/campaigns", methods=["GET"])
@login_required
def get_group_campaigns(group_id):
    """Get all campaigns assigned to a budget group."""
    user = g.user
    account_id = user.account_id if user and hasattr(user, 'account_id') else None

    if not account_id:
        return jsonify({"error": "Missing account_id"}), 400

    try:
        db = get_db()
        service = BudgetGroupsService(db)
        campaigns = service.get_group_campaigns(group_id, account_id)

        return jsonify({"success": True, "campaigns": campaigns})

    except Exception as e:
        logger.error(f"Error getting group campaigns: {e}")
        return jsonify({"error": str(e)}), 500


@budget_groups_bp.route("/api/groups/<int:group_id>/campaigns", methods=["POST"])
@login_required
def assign_campaign(group_id):
    """Assign a campaign to a budget group."""
    user = g.user
    account_id = user.account_id if user and hasattr(user, 'account_id') else None

    data = request.get_json()
    customer_id = data.get('customer_id', '')
    campaign_id = data.get('campaign_id', '')
    campaign_name = data.get('campaign_name', '')

    if not account_id or not customer_id or not campaign_id:
        return jsonify({"error": "Missing required fields"}), 400

    try:
        db = get_db()
        service = BudgetGroupsService(db)

        success = service.assign_campaign(
            group_id=group_id,
            account_id=account_id,
            customer_id=customer_id,
            campaign_id=campaign_id,
            campaign_name=campaign_name
        )

        if success:
            return jsonify({"success": True, "message": "Campaign assigned successfully"})
        else:
            return jsonify({"error": "Failed to assign campaign (may already be assigned to another group)"}), 400

    except Exception as e:
        logger.error(f"Error assigning campaign: {e}")
        return jsonify({"error": str(e)}), 500


@budget_groups_bp.route("/api/groups/<int:group_id>/campaigns/<campaign_id>", methods=["DELETE"])
@login_required
def unassign_campaign(group_id, campaign_id):
    """Remove a campaign from a budget group."""
    user = g.user
    account_id = user.account_id if user and hasattr(user, 'account_id') else None

    if not account_id:
        return jsonify({"error": "Missing account_id"}), 400

    try:
        db = get_db()
        service = BudgetGroupsService(db)
        success = service.unassign_campaign(group_id, account_id, campaign_id)

        if success:
            return jsonify({"success": True, "message": "Campaign unassigned successfully"})
        else:
            return jsonify({"error": "Failed to unassign campaign"}), 500

    except Exception as e:
        logger.error(f"Error unassigning campaign: {e}")
        return jsonify({"error": str(e)}), 500


@budget_groups_bp.route("/api/unassigned-campaigns", methods=["POST"])
@login_required
def get_unassigned_campaigns():
    """Get campaigns not assigned to any budget group."""
    user = g.user
    account_id = user.account_id if user and hasattr(user, 'account_id') else None

    data = request.get_json()
    customer_id = data.get('customer_id', '')
    all_campaigns = data.get('campaigns', [])

    if not account_id or not customer_id:
        return jsonify({"error": "Missing required fields"}), 400

    try:
        db = get_db()
        service = BudgetGroupsService(db)

        unassigned = service.get_unassigned_campaigns(
            account_id=account_id,
            customer_id=customer_id,
            all_campaigns=all_campaigns
        )

        return jsonify({"success": True, "campaigns": unassigned})

    except Exception as e:
        logger.error(f"Error getting unassigned campaigns: {e}")
        return jsonify({"error": str(e)}), 500


# ==================== Budget Calculations ====================

@budget_groups_bp.route("/api/groups/<int:group_id>/calculate-adjustments", methods=["POST"])
@login_required
def calculate_group_adjustments(group_id):
    """Calculate budget adjustments for a specific budget group."""
    user = g.user
    account_id = user.account_id if user and hasattr(user, 'account_id') else None

    data = request.get_json()
    customer_id = data.get('customer_id', '')
    group_campaigns = data.get('campaigns', [])
    seasonality_data = data.get('seasonality_data')
    capacity_utilization = data.get('capacity_utilization')

    if not account_id or not customer_id:
        return jsonify({"error": "Missing required fields"}), 400

    try:
        db = get_db()
        groups_service = BudgetGroupsService(db)
        auto_budget_service = AutoBudgetService(db)

        # Get the budget group
        budget_group = groups_service.get_group(group_id, account_id)
        if not budget_group:
            return jsonify({"error": "Budget group not found"}), 404

        # Calculate adjustments
        adjustments = auto_budget_service.calculate_budget_adjustments_for_group(
            account_id=account_id,
            customer_id=customer_id,
            budget_group=budget_group,
            group_campaigns=group_campaigns,
            seasonality_data=seasonality_data,
            capacity_utilization=capacity_utilization
        )

        return jsonify({"success": True, "adjustments": adjustments})

    except Exception as e:
        logger.error(f"Error calculating group adjustments: {e}")
        return jsonify({"error": str(e)}), 500
