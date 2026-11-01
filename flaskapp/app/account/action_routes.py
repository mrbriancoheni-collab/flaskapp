# app/account/action_routes.py
"""
Action approval queue routes — attaches to account_bp.

Routes:
  GET  /account/actions              — render the action queue page
  POST /account/actions/<id>/approve — approve (mark executed)
  POST /account/actions/<id>/skip    — skip (mark rejected)
  GET  /account/actions/count.json   — JSON pending count for dashboard badge
"""
from __future__ import annotations

import logging
from datetime import datetime

from flask import g, jsonify, redirect, render_template, url_for
from sqlalchemy import text

from app import db
from app.account import account_bp
from app.auth.utils import login_required, current_account_id

logger = logging.getLogger(__name__)


def _get_action_or_403(action_id: int, account_id: int):
    """
    Fetch an agent_decisions row, verifying ownership.
    Returns the row dict or None if not found / wrong account.
    """
    try:
        with db.engine.connect() as conn:
            row = conn.execute(text("""
                SELECT id, account_id, status, decision_type
                FROM agent_decisions
                WHERE id = :action_id
                LIMIT 1
            """), {"action_id": action_id}).fetchone()

        if not row:
            return None
        if int(row[1]) != int(account_id):
            logger.warning(
                "Action ownership mismatch: action %s belongs to account %s, "
                "requested by account %s",
                action_id, row[1], account_id,
            )
            return None
        return dict(row._mapping)
    except Exception as e:
        logger.error("_get_action_or_403 error: %s", e)
        return None


@account_bp.route("/actions", methods=["GET"], endpoint="action_queue")
@login_required
def action_queue():
    from app.services.action_generator import generate_pending_actions, get_sample_actions

    aid = current_account_id()
    if not aid:
        return redirect(url_for("auth_bp.login"))

    # Generate new actions from rules (no-op if metrics absent)
    generate_pending_actions(aid)

    # Fetch current pending queue
    is_sample = False
    try:
        with db.engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT id, decision_type, title, description, risk_level,
                       expected_monthly_savings, expected_monthly_leads,
                       expected_improvement_pct, confidence, campaign_id,
                       ad_group_id, created_at
                FROM agent_decisions
                WHERE account_id    = :aid
                  AND status        = 'pending'
                  AND requires_approval = TRUE
                ORDER BY created_at DESC
                LIMIT 20
            """), {"aid": aid}).fetchall()
        actions = [dict(r._mapping) for r in rows]
    except Exception as e:
        logger.error("action_queue fetch error: %s", e)
        actions = []

    if not actions:
        actions = get_sample_actions(aid)
        is_sample = True

    return render_template(
        "account/action_queue.html",
        actions=actions,
        is_sample=is_sample,
        user=g.user,
    )


@account_bp.route("/actions/<int:action_id>/approve", methods=["POST"], endpoint="action_approve")
@login_required
def action_approve(action_id: int):
    aid = current_account_id()
    if not aid:
        return jsonify({"success": False, "message": "Not authenticated"}), 401

    # Sample actions have negative IDs — silently succeed (UI demo)
    if action_id < 0:
        return jsonify({"success": True, "message": "Action approved"})

    row = _get_action_or_403(action_id, aid)
    if not row:
        return jsonify({"success": False, "message": "Action not found"}), 404

    try:
        with db.engine.connect() as conn:
            conn.execute(text("""
                UPDATE agent_decisions
                SET status = 'approved', executed_at = :now
                WHERE id = :action_id
            """), {"now": datetime.utcnow(), "action_id": action_id})
            conn.commit()
        return jsonify({"success": True, "message": "Action approved"})
    except Exception as e:
        logger.error("action_approve DB error: %s", e)
        return jsonify({"success": False, "message": "Database error"}), 500


@account_bp.route("/actions/<int:action_id>/skip", methods=["POST"], endpoint="action_skip")
@login_required
def action_skip(action_id: int):
    aid = current_account_id()
    if not aid:
        return jsonify({"success": False, "message": "Not authenticated"}), 401

    if action_id < 0:
        return jsonify({"success": True, "message": "Action skipped"})

    row = _get_action_or_403(action_id, aid)
    if not row:
        return jsonify({"success": False, "message": "Action not found"}), 404

    try:
        with db.engine.connect() as conn:
            conn.execute(text("""
                UPDATE agent_decisions
                SET status = 'rejected'
                WHERE id = :action_id
            """), {"action_id": action_id})
            conn.commit()
        return jsonify({"success": True, "message": "Action skipped"})
    except Exception as e:
        logger.error("action_skip DB error: %s", e)
        return jsonify({"success": False, "message": "Database error"}), 500


@account_bp.route("/actions/count.json", methods=["GET"], endpoint="action_count")
@login_required
def action_count():
    aid = current_account_id()
    if not aid:
        return jsonify({"count": 0})
    try:
        with db.engine.connect() as conn:
            result = conn.execute(text("""
                SELECT COUNT(*) FROM agent_decisions
                WHERE account_id      = :aid
                  AND status          = 'pending'
                  AND requires_approval = TRUE
            """), {"aid": aid}).scalar()
        return jsonify({"count": int(result or 0)})
    except Exception as e:
        logger.error("action_count error: %s", e)
        return jsonify({"count": 0})
