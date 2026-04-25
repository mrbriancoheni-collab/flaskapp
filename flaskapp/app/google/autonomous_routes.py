# app/google/autonomous_routes.py
"""
Autonomous Mode Control Panel — lets users configure goals and constraints
that drive the entire agent system (growth_mode, target_cpl, budget, geo, services).

Routes
------
GET  /account/google/autonomous          → control panel page
POST /account/google/autonomous/settings → save settings (JSON response)
GET  /account/google/autonomous/feed     → last-N executed AI actions (JSON)
GET  /account/google/autonomous/summary  → 7-day impact summary (JSON)
"""
import json
from datetime import datetime, timedelta

from flask import Blueprint, render_template, jsonify, request, current_app
from sqlalchemy import text

from app import db
from app.auth.utils import login_required, current_account_id

autonomous_bp = Blueprint(
    "autonomous_bp",
    __name__,
    url_prefix="/account/google/autonomous",
)

# ── Settings keys this module owns ────────────────────────────────────────────

AUTONOMOUS_KEYS = [
    "autonomous_mode_enabled",
    "autonomy_level",
    "growth_mode",
    "target_cpl",
    "monthly_budget",
    "services_priority",
    "geo_targets",
]

DEFAULTS = {
    "autonomous_mode_enabled": "0",
    "autonomy_level": "2",
    "growth_mode": "balanced",
    "target_cpl": "80",
    "monthly_budget": "1500",
    "services_priority": "",
    "geo_targets": "",
}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _get_settings(account_id: int) -> dict:
    """Read autonomous settings from account_settings table."""
    try:
        keys_placeholder = ", ".join(f"'{k}'" for k in AUTONOMOUS_KEYS)
        sql = text(f"""
            SELECT setting_key, setting_value
            FROM account_settings
            WHERE account_id = :aid
              AND setting_key IN ({keys_placeholder})
        """)
        with db.engine.connect() as conn:
            rows = conn.execute(sql, {"aid": account_id})
            stored = {r.setting_key: r.setting_value for r in rows}
    except Exception:
        stored = {}

    return {k: stored.get(k, DEFAULTS[k]) for k in AUTONOMOUS_KEYS}


def _save_setting(account_id: int, key: str, value: str) -> None:
    """Upsert a single key into account_settings."""
    sql = text("""
        INSERT INTO account_settings (account_id, setting_key, setting_value)
        VALUES (:aid, :key, :val)
        ON DUPLICATE KEY UPDATE setting_value = VALUES(setting_value)
    """)
    try:
        with db.engine.begin() as conn:
            conn.execute(sql, {"aid": account_id, "key": key, "val": value})
    except Exception as exc:
        err = str(exc).lower()
        if "doesn't exist" in err or "no such table" in err:
            # Create table on first use
            with db.engine.begin() as conn:
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS account_settings (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        account_id INT NOT NULL,
                        setting_key VARCHAR(100) NOT NULL,
                        setting_value TEXT,
                        UNIQUE KEY uq_account_setting (account_id, setting_key)
                    )
                """))
                conn.execute(sql, {"aid": account_id, "key": key, "val": value})
        else:
            raise


def _get_7day_summary(account_id: int) -> dict:
    """
    Aggregate executed AI actions from the last 7 days.
    Returns counts by action_type, total savings, total leads.
    """
    cutoff = datetime.utcnow() - timedelta(days=7)
    try:
        sql = text("""
            SELECT
                action_type,
                COUNT(*)                          AS cnt,
                COALESCE(SUM(estimated_monthly_savings), 0) AS savings
            FROM ai_actions
            WHERE account_id = :aid
              AND status      = 'executed'
              AND executed_at >= :cutoff
            GROUP BY action_type
        """)
        with db.engine.connect() as conn:
            rows = conn.execute(sql, {"aid": account_id, "cutoff": cutoff}).fetchall()
    except Exception:
        rows = []

    total_actions = sum(r.cnt for r in rows)
    total_savings = sum(r.savings for r in rows)
    by_type = {r.action_type: {"count": r.cnt, "savings": round(r.savings, 2)} for r in rows}

    # Leads: check CustomerImpact if available
    additional_leads = 0
    try:
        lead_sql = text("""
            SELECT COALESCE(SUM(additional_leads), 0) AS leads
            FROM customer_impact
            WHERE account_id = :aid
              AND recorded_at >= :cutoff
        """)
        with db.engine.connect() as conn:
            row = conn.execute(lead_sql, {"aid": account_id, "cutoff": cutoff}).first()
            if row:
                additional_leads = int(row.leads)
    except Exception:
        pass

    return {
        "total_actions": total_actions,
        "total_savings": round(total_savings, 2),
        "additional_leads": additional_leads,
        "by_type": by_type,
        "period_days": 7,
    }


def _get_recent_feed(account_id: int, limit: int = 10) -> list:
    """Return the most recent executed AI actions as feed items."""
    try:
        sql = text("""
            SELECT id, action_type, title, description,
                   estimated_monthly_savings, executed_at, campaign_name
            FROM ai_actions
            WHERE account_id = :aid
              AND status      = 'executed'
            ORDER BY executed_at DESC
            LIMIT :lim
        """)
        with db.engine.connect() as conn:
            rows = conn.execute(sql, {"aid": account_id, "lim": limit}).fetchall()
    except Exception:
        rows = []

    feed = []
    for r in rows:
        feed.append({
            "id": r.id,
            "action_type": r.action_type,
            "title": r.title,
            "description": r.description,
            "savings": round(r.estimated_monthly_savings or 0, 2),
            "executed_at": r.executed_at.isoformat() if r.executed_at else None,
            "campaign_name": r.campaign_name,
        })
    return feed


# ── Routes ─────────────────────────────────────────────────────────────────────

@autonomous_bp.route("/", methods=["GET"])
@login_required
def control_panel():
    account_id = current_account_id()
    settings = _get_settings(account_id)
    summary = _get_7day_summary(account_id)
    feed = _get_recent_feed(account_id, limit=10)

    return render_template(
        "google/autonomous_control_panel.html",
        settings=settings,
        summary=summary,
        feed=feed,
    )


@autonomous_bp.route("/settings", methods=["POST"])
@login_required
def save_settings():
    account_id = current_account_id()
    data = request.get_json(silent=True) or {}

    allowed = set(AUTONOMOUS_KEYS)
    saved = {}
    errors = {}

    for key, value in data.items():
        if key not in allowed:
            continue
        try:
            _save_setting(account_id, key, str(value))
            saved[key] = value
        except Exception as exc:
            current_app.logger.warning("Failed to save setting %s: %s", key, exc)
            errors[key] = str(exc)

    if errors:
        first_error = next(iter(errors.values()), "unknown error")
        return jsonify({"ok": False, "error": first_error, "saved": saved, "errors": errors}), 500
    return jsonify({"ok": True, "saved": saved})


@autonomous_bp.route("/feed", methods=["GET"])
@login_required
def feed_json():
    account_id = current_account_id()
    limit = min(int(request.args.get("limit", 20)), 100)
    return jsonify(_get_recent_feed(account_id, limit=limit))


@autonomous_bp.route("/summary", methods=["GET"])
@login_required
def summary_json():
    account_id = current_account_id()
    return jsonify(_get_7day_summary(account_id))
