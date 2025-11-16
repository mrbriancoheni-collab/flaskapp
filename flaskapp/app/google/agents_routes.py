# app/google/agents_routes.py
"""
Routes for AI Agent management - Approval Queue and Dashboard.
"""
from flask import Blueprint, render_template, jsonify, request, flash, redirect, url_for
from sqlalchemy import text
from datetime import datetime

from app import db
from app.auth.utils import login_required, current_account_id

agents_bp = Blueprint("agents_bp", __name__, url_prefix="/account/google/ads/agents")


@agents_bp.route("/approvals")
@login_required
def approval_queue():
    """
    Approval Queue - View and approve/reject high-risk agent decisions.
    """
    account_id = current_account_id()

    # Fetch pending decisions requiring approval
    query = text("""
        SELECT
            id, agent_id, agent_type, decision_type,
            title, description, reasoning,
            campaign_id, ad_group_id,
            risk_level, confidence,
            expected_monthly_savings, expected_monthly_leads, expected_improvement_pct,
            created_at, expires_at
        FROM agent_decisions
        WHERE account_id = :account_id
          AND status = 'pending'
          AND requires_approval = TRUE
        ORDER BY
            CASE risk_level
                WHEN 'critical' THEN 1
                WHEN 'high' THEN 2
                WHEN 'medium' THEN 3
                ELSE 4
            END,
            created_at DESC
    """)

    with db.engine.connect() as conn:
        result = conn.execute(query, {"account_id": account_id})
        pending_decisions = [dict(row._mapping) for row in result]

    # Group by risk level for better UI
    decisions_by_risk = {
        'critical': [],
        'high': [],
        'medium': [],
        'low': []
    }

    for decision in pending_decisions:
        risk_level = decision['risk_level']
        decisions_by_risk[risk_level].append(decision)

    return render_template(
        "google/agents_approval_queue.html",
        pending_decisions=pending_decisions,
        decisions_by_risk=decisions_by_risk,
        total_pending=len(pending_decisions)
    )


@agents_bp.route("/dashboard")
@login_required
def dashboard():
    """
    Agent Performance Dashboard - View agent performance metrics and stats.
    """
    account_id = current_account_id()

    # Get agent performance stats
    stats_query = text("""
        SELECT
            agent_type,
            COUNT(*) as total_decisions,
            SUM(CASE WHEN status = 'executed' THEN 1 ELSE 0 END) as executed_count,
            SUM(CASE WHEN status = 'approved' OR status = 'executed' THEN 1 ELSE 0 END) as approved_count,
            SUM(CASE WHEN status = 'rejected' THEN 1 ELSE 0 END) as rejected_count,
            AVG(confidence) as avg_confidence,
            AVG(prediction_accuracy) as avg_accuracy,
            SUM(expected_monthly_savings) as total_expected_savings,
            SUM(expected_monthly_leads) as total_expected_leads
        FROM agent_decisions
        WHERE account_id = :account_id
        GROUP BY agent_type
        ORDER BY total_decisions DESC
    """)

    # Get recent activity
    recent_query = text("""
        SELECT
            id, agent_id, agent_type, decision_type,
            title, status, confidence, prediction_accuracy,
            expected_monthly_savings, expected_monthly_leads,
            created_at, executed_at
        FROM agent_decisions
        WHERE account_id = :account_id
        ORDER BY created_at DESC
        LIMIT 20
    """)

    # Get auto-execution stats
    auto_exec_query = text("""
        SELECT
            decision_type,
            COUNT(*) as count,
            AVG(confidence) as avg_confidence,
            SUM(expected_monthly_savings) as total_savings
        FROM agent_decisions
        WHERE account_id = :account_id
          AND requires_approval = FALSE
          AND status = 'executed'
        GROUP BY decision_type
        ORDER BY count DESC
        LIMIT 10
    """)

    with db.engine.connect() as conn:
        agent_stats = [dict(row._mapping) for row in conn.execute(stats_query, {"account_id": account_id})]
        recent_activity = [dict(row._mapping) for row in conn.execute(recent_query, {"account_id": account_id})]
        auto_exec_stats = [dict(row._mapping) for row in conn.execute(auto_exec_query, {"account_id": account_id})]

    # Calculate overall metrics
    total_decisions = sum(s['total_decisions'] for s in agent_stats)
    total_executed = sum(s['executed_count'] for s in agent_stats)
    total_savings = sum(s['total_expected_savings'] or 0 for s in agent_stats)
    total_leads = sum(s['total_expected_leads'] or 0 for s in agent_stats)

    return render_template(
        "google/agents_dashboard.html",
        agent_stats=agent_stats,
        recent_activity=recent_activity,
        auto_exec_stats=auto_exec_stats,
        total_decisions=total_decisions,
        total_executed=total_executed,
        total_savings=total_savings,
        total_leads=total_leads
    )


@agents_bp.route("/api/decisions/<int:decision_id>/approve", methods=["POST"])
@login_required
def approve_decision(decision_id):
    """Approve a pending agent decision."""
    account_id = current_account_id()

    query = text("""
        UPDATE agent_decisions
        SET status = 'approved',
            updated_at = NOW()
        WHERE id = :decision_id
          AND account_id = :account_id
          AND status = 'pending'
    """)

    with db.engine.begin() as conn:
        result = conn.execute(query, {"decision_id": decision_id, "account_id": account_id})

        if result.rowcount == 0:
            return jsonify({"success": False, "error": "Decision not found or already processed"}), 404

    # TODO: Trigger execution via agent executor

    return jsonify({"success": True, "message": "Decision approved"})


@agents_bp.route("/api/decisions/<int:decision_id>/reject", methods=["POST"])
@login_required
def reject_decision(decision_id):
    """Reject a pending agent decision."""
    account_id = current_account_id()

    reason = request.json.get("reason", "User rejected") if request.is_json else "User rejected"

    query = text("""
        UPDATE agent_decisions
        SET status = 'rejected',
            execution_result = :reason,
            updated_at = NOW()
        WHERE id = :decision_id
          AND account_id = :account_id
          AND status = 'pending'
    """)

    with db.engine.begin() as conn:
        result = conn.execute(query, {
            "decision_id": decision_id,
            "account_id": account_id,
            "reason": reason
        })

        if result.rowcount == 0:
            return jsonify({"success": False, "error": "Decision not found or already processed"}), 404

    return jsonify({"success": True, "message": "Decision rejected"})


@agents_bp.route("/api/decisions/<int:decision_id>")
@login_required
def get_decision(decision_id):
    """Get details for a specific decision."""
    account_id = current_account_id()

    query = text("""
        SELECT *
        FROM agent_decisions
        WHERE id = :decision_id
          AND account_id = :account_id
    """)

    with db.engine.connect() as conn:
        result = conn.execute(query, {"decision_id": decision_id, "account_id": account_id})
        row = result.first()

        if not row:
            return jsonify({"error": "Decision not found"}), 404

        return jsonify(dict(row._mapping))
