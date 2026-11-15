from flask import jsonify
from flask_login import login_required, current_user
from app.extensions import db
from sqlalchemy import text
from app.account import account_bp


@account_bp.route("/proactive-card.json", endpoint="proactive_card_json")
@login_required
def proactive_card_json():
    aid = current_user.account_id
    try:
        with db.engine.connect() as conn:
            row = conn.execute(
                text("""
                    SELECT id, action_type, action_description, expected_monthly_savings,
                           risk_level, status, created_at
                    FROM agent_decisions
                    WHERE account_id = :aid
                      AND status = 'pending'
                      AND requires_approval = TRUE
                    ORDER BY expected_monthly_savings DESC NULLS LAST, created_at DESC
                    LIMIT 1
                """),
                {"aid": aid},
            ).fetchone()
    except Exception:
        return jsonify({"card": None})

    if row is None:
        return jsonify({"card": None})

    card = {
        "id": row[0],
        "action_type": row[1],
        "description": row[2],
        "expected_savings": float(row[3]) if row[3] is not None else None,
        "risk_level": row[4],
        "status": row[5],
    }
    return jsonify({"card": card})
