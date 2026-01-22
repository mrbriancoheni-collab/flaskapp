# app/google/budget_routes.py
"""
Campaign Budget Management - Segment campaigns into budget-controlled groups.
"""
from flask import Blueprint, render_template, jsonify, request, flash, redirect, url_for
from sqlalchemy import text
from datetime import datetime, date
import calendar

from app import db
from app.auth.utils import login_required, current_account_id

budget_bp = Blueprint("budget_bp", __name__, url_prefix="/account/google/ads/budget")


@budget_bp.route("/")
@login_required
def budget_groups():
    """
    Budget Groups Management - Main page for creating and managing campaign budget groups.
    """
    account_id = current_account_id()
    budget_groups_list = []
    campaigns = []
    assigned_campaigns = []
    unassigned_campaigns = []
    current_month = date.today().replace(day=1)
    setup_required = False

    try:
        # Fetch all budget groups for this account
        groups_query = text("""
            SELECT
                cbg.id,
                cbg.name,
                cbg.description,
                cbg.target_location,
                cbg.location_type,
                cbg.location_radius_miles,
                cbg.location_criteria_ids,
                cbg.monthly_budget_cents,
                cbg.daily_budget_cents,
                cbg.status,
                cbg.priority,
                cbg.auto_pause_on_overspend,
                cbg.alert_threshold_pct,
                cbg.created_at,
                COUNT(cba.campaign_id) as campaign_count
            FROM campaign_budget_groups cbg
            LEFT JOIN campaign_budget_assignments cba ON cbg.id = cba.budget_group_id
            WHERE cbg.account_id = :account_id
            GROUP BY cbg.id
            ORDER BY cbg.priority DESC, cbg.name
        """)

        # Fetch all campaigns for this account with their assignments
        campaigns_query = text("""
            SELECT
                c.id,
                c.name,
                c.status,
                c.daily_budget_cents,
                c.google_campaign_id,
                cba.budget_group_id,
                cbg.name as group_name
            FROM ads_campaigns c
            LEFT JOIN campaign_budget_assignments cba ON c.id = cba.campaign_id
            LEFT JOIN campaign_budget_groups cbg ON cba.budget_group_id = cbg.id
            WHERE c.account_id = :account_id
            ORDER BY c.name
        """)

        # Get current month spend per group
        spend_query = text("""
            SELECT
                budget_group_id,
                total_spend_cents,
                budget_status
            FROM campaign_budget_group_spend
            WHERE period_month = :period_month
        """)

        with db.engine.connect() as conn:
            groups_result = conn.execute(groups_query, {"account_id": account_id})
            budget_groups_list = [dict(row._mapping) for row in groups_result]

            campaigns_result = conn.execute(campaigns_query, {"account_id": account_id})
            campaigns = [dict(row._mapping) for row in campaigns_result]

            spend_result = conn.execute(spend_query, {"period_month": current_month})
            spend_data = {row.budget_group_id: dict(row._mapping) for row in spend_result}

        # Enrich groups with spend data
        for group in budget_groups_list:
            spend = spend_data.get(group['id'], {})
            group['current_spend_cents'] = spend.get('total_spend_cents', 0)
            group['budget_status'] = spend.get('budget_status', 'active')
            group['spend_pct'] = (group['current_spend_cents'] / group['monthly_budget_cents'] * 100) if group['monthly_budget_cents'] > 0 else 0

        # Separate assigned and unassigned campaigns
        assigned_campaigns = [c for c in campaigns if c['budget_group_id'] is not None]
        unassigned_campaigns = [c for c in campaigns if c['budget_group_id'] is None]

    except Exception as e:
        # Database tables may not exist yet
        import logging
        logging.error(f"Budget groups query failed: {e}")
        setup_required = True

    return render_template(
        "google/budget_groups.html",
        budget_groups=budget_groups_list,
        campaigns=campaigns,
        assigned_campaigns=assigned_campaigns,
        unassigned_campaigns=unassigned_campaigns,
        current_month=current_month,
        setup_required=setup_required
    )


@budget_bp.route("/api/groups", methods=["POST"])
@login_required
def create_group():
    """Create a new budget group."""
    account_id = current_account_id()
    data = request.get_json()

    name = data.get('name', '').strip()
    description = data.get('description', '').strip()
    target_location = data.get('target_location', '').strip() or None
    location_type = data.get('location_type', None)
    location_radius_miles = data.get('location_radius_miles', None)
    location_criteria_ids = data.get('location_criteria_ids', '').strip() or None
    monthly_budget = data.get('monthly_budget', 0)  # In dollars
    priority = data.get('priority', 0)
    auto_pause = data.get('auto_pause_on_overspend', True)
    alert_threshold = data.get('alert_threshold_pct', 0.80)

    if not name:
        return jsonify({"success": False, "error": "Group name is required"}), 400

    if monthly_budget <= 0:
        return jsonify({"success": False, "error": "Monthly budget must be greater than 0"}), 400

    monthly_budget_cents = int(monthly_budget * 100)

    insert_query = text("""
        INSERT INTO campaign_budget_groups
            (account_id, name, description, target_location, location_type,
             location_radius_miles, location_criteria_ids, monthly_budget_cents, priority,
             auto_pause_on_overspend, alert_threshold_pct)
        VALUES
            (:account_id, :name, :description, :target_location, :location_type,
             :location_radius_miles, :location_criteria_ids, :monthly_budget_cents, :priority,
             :auto_pause, :alert_threshold)
    """)

    with db.engine.begin() as conn:
        result = conn.execute(insert_query, {
            "account_id": account_id,
            "name": name,
            "description": description,
            "target_location": target_location,
            "location_type": location_type,
            "location_radius_miles": location_radius_miles,
            "location_criteria_ids": location_criteria_ids,
            "monthly_budget_cents": monthly_budget_cents,
            "priority": priority,
            "auto_pause": auto_pause,
            "alert_threshold": alert_threshold
        })
        group_id = result.lastrowid

    return jsonify({
        "success": True,
        "message": f"Budget group '{name}' created successfully",
        "group_id": group_id
    })


@budget_bp.route("/api/groups/<int:group_id>", methods=["PUT"])
@login_required
def update_group(group_id):
    """Update an existing budget group."""
    account_id = current_account_id()
    data = request.get_json()

    name = data.get('name', '').strip()
    description = data.get('description', '').strip()
    target_location = data.get('target_location', '').strip() or None
    location_type = data.get('location_type', None)
    location_radius_miles = data.get('location_radius_miles', None)
    location_criteria_ids = data.get('location_criteria_ids', '').strip() or None
    monthly_budget = data.get('monthly_budget', 0)
    priority = data.get('priority', 0)
    status = data.get('status', 'active')
    auto_pause = data.get('auto_pause_on_overspend', True)
    alert_threshold = data.get('alert_threshold_pct', 0.80)

    if not name:
        return jsonify({"success": False, "error": "Group name is required"}), 400

    monthly_budget_cents = int(monthly_budget * 100)

    update_query = text("""
        UPDATE campaign_budget_groups
        SET name = :name,
            description = :description,
            target_location = :target_location,
            location_type = :location_type,
            location_radius_miles = :location_radius_miles,
            location_criteria_ids = :location_criteria_ids,
            monthly_budget_cents = :monthly_budget_cents,
            priority = :priority,
            status = :status,
            auto_pause_on_overspend = :auto_pause,
            alert_threshold_pct = :alert_threshold
        WHERE id = :group_id AND account_id = :account_id
    """)

    with db.engine.begin() as conn:
        result = conn.execute(update_query, {
            "group_id": group_id,
            "account_id": account_id,
            "name": name,
            "description": description,
            "target_location": target_location,
            "location_type": location_type,
            "location_radius_miles": location_radius_miles,
            "location_criteria_ids": location_criteria_ids,
            "monthly_budget_cents": monthly_budget_cents,
            "priority": priority,
            "status": status,
            "auto_pause": auto_pause,
            "alert_threshold": alert_threshold
        })

        if result.rowcount == 0:
            return jsonify({"success": False, "error": "Group not found"}), 404

    return jsonify({"success": True, "message": f"Budget group updated successfully"})


@budget_bp.route("/api/groups/<int:group_id>", methods=["DELETE"])
@login_required
def delete_group(group_id):
    """Delete a budget group (unassigns all campaigns first)."""
    account_id = current_account_id()

    # Verify ownership and delete
    delete_query = text("""
        DELETE FROM campaign_budget_groups
        WHERE id = :group_id AND account_id = :account_id
    """)

    with db.engine.begin() as conn:
        result = conn.execute(delete_query, {
            "group_id": group_id,
            "account_id": account_id
        })

        if result.rowcount == 0:
            return jsonify({"success": False, "error": "Group not found"}), 404

    return jsonify({"success": True, "message": "Budget group deleted successfully"})


@budget_bp.route("/api/groups/<int:group_id>/assign", methods=["POST"])
@login_required
def assign_campaigns(group_id):
    """Assign campaigns to a budget group."""
    account_id = current_account_id()
    data = request.get_json()
    campaign_ids = data.get('campaign_ids', [])

    if not campaign_ids:
        return jsonify({"success": False, "error": "No campaigns selected"}), 400

    # Verify group ownership
    verify_query = text("""
        SELECT id FROM campaign_budget_groups
        WHERE id = :group_id AND account_id = :account_id
    """)

    with db.engine.begin() as conn:
        result = conn.execute(verify_query, {
            "group_id": group_id,
            "account_id": account_id
        })

        if not result.first():
            return jsonify({"success": False, "error": "Budget group not found"}), 404

        # Remove existing assignments for these campaigns
        delete_query = text("""
            DELETE FROM campaign_budget_assignments
            WHERE campaign_id IN :campaign_ids
        """)
        conn.execute(delete_query, {"campaign_ids": tuple(campaign_ids)})

        # Create new assignments
        for campaign_id in campaign_ids:
            insert_query = text("""
                INSERT INTO campaign_budget_assignments (campaign_id, budget_group_id)
                VALUES (:campaign_id, :group_id)
            """)
            conn.execute(insert_query, {
                "campaign_id": campaign_id,
                "group_id": group_id
            })

    return jsonify({
        "success": True,
        "message": f"{len(campaign_ids)} campaign(s) assigned to budget group"
    })


@budget_bp.route("/api/campaigns/<int:campaign_id>/unassign", methods=["POST"])
@login_required
def unassign_campaign(campaign_id):
    """Remove a campaign from its budget group."""
    account_id = current_account_id()

    # Verify campaign ownership via account_id
    verify_query = text("""
        SELECT id FROM ads_campaigns
        WHERE id = :campaign_id AND account_id = :account_id
    """)

    with db.engine.begin() as conn:
        result = conn.execute(verify_query, {
            "campaign_id": campaign_id,
            "account_id": account_id
        })

        if not result.first():
            return jsonify({"success": False, "error": "Campaign not found"}), 404

        # Delete assignment
        delete_query = text("""
            DELETE FROM campaign_budget_assignments
            WHERE campaign_id = :campaign_id
        """)
        conn.execute(delete_query, {"campaign_id": campaign_id})

    return jsonify({"success": True, "message": "Campaign unassigned from budget group"})


@budget_bp.route("/api/groups/<int:group_id>/spend")
@login_required
def get_group_spend(group_id):
    """Get spend history for a budget group."""
    account_id = current_account_id()

    # Verify ownership
    verify_query = text("""
        SELECT id FROM campaign_budget_groups
        WHERE id = :group_id AND account_id = :account_id
    """)

    with db.engine.connect() as conn:
        result = conn.execute(verify_query, {
            "group_id": group_id,
            "account_id": account_id
        })

        if not result.first():
            return jsonify({"success": False, "error": "Budget group not found"}), 404

        # Get last 12 months of spend
        spend_query = text("""
            SELECT
                period_month,
                total_spend_cents,
                total_impressions,
                total_clicks,
                total_conversions,
                budget_status
            FROM campaign_budget_group_spend
            WHERE budget_group_id = :group_id
            ORDER BY period_month DESC
            LIMIT 12
        """)

        spend_result = conn.execute(spend_query, {"group_id": group_id})
        spend_history = [dict(row._mapping) for row in spend_result]

    return jsonify({"success": True, "spend_history": spend_history})


@budget_bp.route("/api/groups/<int:group_id>/locations")
@login_required
def get_location_performance(group_id):
    """Get location-based performance breakdown for a budget group."""
    account_id = current_account_id()

    # Verify ownership
    verify_query = text("""
        SELECT id, target_location, location_type
        FROM campaign_budget_groups
        WHERE id = :group_id AND account_id = :account_id
    """)

    with db.engine.connect() as conn:
        result = conn.execute(verify_query, {
            "group_id": group_id,
            "account_id": account_id
        })
        group = result.first()

        if not group:
            return jsonify({"success": False, "error": "Budget group not found"}), 404

        group = dict(group._mapping)

        # Get current month location performance
        current_month = date.today().replace(day=1)
        location_query = text("""
            SELECT
                location_name,
                spend_cents,
                impressions,
                clicks,
                conversions,
                calls,
                ctr,
                cpc_cents,
                cpl_cents,
                conversion_rate,
                pacing_status
            FROM budget_group_location_performance
            WHERE budget_group_id = :group_id
              AND period_month = :period_month
            ORDER BY spend_cents DESC
        """)

        location_result = conn.execute(location_query, {
            "group_id": group_id,
            "period_month": current_month
        })
        locations = [dict(row._mapping) for row in location_result]

    return jsonify({
        "success": True,
        "group": group,
        "locations": locations,
        "period": current_month.strftime('%Y-%m')
    })


@budget_bp.route("/api/campaigns/by-location", methods=["POST"])
@login_required
def filter_campaigns_by_location():
    """Filter campaigns by their location targeting."""
    account_id = current_account_id()
    data = request.get_json()

    location_name = data.get('location_name', '').strip()
    if not location_name:
        return jsonify({"success": False, "error": "Location name required"}), 400

    # Find campaigns targeting this location
    query = text("""
        SELECT DISTINCT
            c.id,
            c.name,
            c.status,
            c.daily_budget_cents,
            c.google_campaign_id,
            cba.budget_group_id,
            cbg.name as group_name
        FROM ads_campaigns c
        LEFT JOIN campaign_location_targets clt ON c.id = clt.campaign_id
        LEFT JOIN campaign_budget_assignments cba ON c.id = cba.campaign_id
        LEFT JOIN campaign_budget_groups cbg ON cba.budget_group_id = cbg.id
        WHERE c.account_id = :account_id
          AND (
            clt.location_name LIKE :location_pattern
            OR clt.canonical_name LIKE :location_pattern
          )
          AND clt.target_type = 'included'
        ORDER BY c.name
    """)

    with db.engine.connect() as conn:
        result = conn.execute(query, {
            "account_id": account_id,
            "location_pattern": f"%{location_name}%"
        })
        campaigns = [dict(row._mapping) for row in result]

    return jsonify({
        "success": True,
        "location": location_name,
        "campaigns": campaigns,
        "count": len(campaigns)
    })


@budget_bp.route("/api/location-rules", methods=["POST"])
@login_required
def create_location_rule():
    """Create a location-specific budget rule."""
    account_id = current_account_id()
    data = request.get_json()

    budget_group_id = data.get('budget_group_id')
    location_name = data.get('location_name', '').strip()
    monthly_budget = data.get('monthly_budget', 0)
    priority = data.get('priority', 0)
    max_cpl_cents = data.get('max_cpl_cents', None)
    auto_pause = data.get('auto_pause_on_threshold', False)

    if not location_name or not budget_group_id:
        return jsonify({"success": False, "error": "Location name and budget group required"}), 400

    if monthly_budget <= 0:
        return jsonify({"success": False, "error": "Monthly budget must be greater than 0"}), 400

    # Verify group ownership
    verify_query = text("""
        SELECT id FROM campaign_budget_groups
        WHERE id = :group_id AND account_id = :account_id
    """)

    monthly_budget_cents = int(monthly_budget * 100)
    max_cpl_cents = int(max_cpl_cents * 100) if max_cpl_cents else None

    with db.engine.begin() as conn:
        result = conn.execute(verify_query, {
            "group_id": budget_group_id,
            "account_id": account_id
        })

        if not result.first():
            return jsonify({"success": False, "error": "Budget group not found"}), 404

        # Insert location rule
        insert_query = text("""
            INSERT INTO budget_group_location_rules
                (budget_group_id, location_name, monthly_budget_cents, priority,
                 max_cpl_cents, auto_pause_on_threshold)
            VALUES
                (:group_id, :location_name, :monthly_budget_cents, :priority,
                 :max_cpl_cents, :auto_pause)
            ON DUPLICATE KEY UPDATE
                monthly_budget_cents = VALUES(monthly_budget_cents),
                priority = VALUES(priority),
                max_cpl_cents = VALUES(max_cpl_cents),
                auto_pause_on_threshold = VALUES(auto_pause_on_threshold)
        """)

        conn.execute(insert_query, {
            "group_id": budget_group_id,
            "location_name": location_name,
            "monthly_budget_cents": monthly_budget_cents,
            "priority": priority,
            "max_cpl_cents": max_cpl_cents,
            "auto_pause": auto_pause
        })

    return jsonify({
        "success": True,
        "message": f"Location rule created for {location_name}"
    })


@budget_bp.route("/api/location-alerts/<int:group_id>", methods=["GET"])
@login_required
def get_location_alerts(group_id):
    """Get location-specific alerts for a budget group."""
    account_id = current_account_id()

    # Verify ownership
    verify_query = text("""
        SELECT id FROM campaign_budget_groups
        WHERE id = :group_id AND account_id = :account_id
    """)

    with db.engine.connect() as conn:
        result = conn.execute(verify_query, {
            "group_id": group_id,
            "account_id": account_id
        })

        if not result.first():
            return jsonify({"success": False, "error": "Budget group not found"}), 404

        # Get unacknowledged alerts
        alerts_query = text("""
            SELECT
                id,
                location_name,
                alert_type,
                severity,
                message,
                current_value,
                threshold_value,
                action_taken,
                alert_date
            FROM budget_group_location_alerts
            WHERE budget_group_id = :group_id
              AND is_acknowledged = FALSE
            ORDER BY severity DESC, alert_date DESC
            LIMIT 50
        """)

        alert_result = conn.execute(alerts_query, {"group_id": group_id})
        alerts = [dict(row._mapping) for row in alert_result]

    return jsonify({
        "success": True,
        "alerts": alerts
    })
