"""
Autopilot settings — control what RevForge applies automatically.

Routes:
  GET  /account/autopilot  — show settings
  POST /account/autopilot  — save settings
"""
from __future__ import annotations

import logging
from datetime import datetime

from flask import flash, redirect, render_template, request, url_for
from sqlalchemy import text

from app import db
from app.auth.utils import login_required
from app.account import account_bp

log = logging.getLogger(__name__)

try:
    from app.services.event_tracker import log_event as _log_event
except ImportError:
    _log_event = None


def _log(event_type: str, aid: int, props: dict) -> None:
    if _log_event:
        try:
            _log_event(event_type, account_id=aid, properties=props)
        except Exception as e:
            log.debug("event_tracker unavailable: %s", e)


def _get_settings(aid: int) -> dict:
    """Load account_settings keys for autopilot."""
    out = {"autopilot_enabled": "0", "autopilot_goal": "lower_cpl", "budget_change_limit": "100"}
    try:
        with db.engine.connect() as conn:
            rows = conn.execute(
                text("SELECT key, value FROM account_settings WHERE account_id = :aid AND key IN ('autopilot_enabled','autopilot_goal','budget_change_limit')"),
                {"aid": aid},
            ).fetchall()
            for row in rows:
                out[row[0]] = row[1]
    except Exception as e:
        log.warning("Could not load account_settings: %s", e)
    return out


def _upsert_setting(conn, aid: int, key: str, value: str) -> None:
    conn.execute(
        text("""
            INSERT INTO account_settings (account_id, key, value)
            VALUES (:aid, :key, :val)
            ON CONFLICT (account_id, key) DO UPDATE SET value = EXCLUDED.value
        """),
        {"aid": aid, "key": key, "val": value},
    )


def _get_agent_config(aid: int) -> dict:
    """Load merged agent config (account-level overrides global defaults)."""
    out = {"auto_execute_threshold": 0.99, "enabled": True}
    try:
        with db.engine.connect() as conn:
            # Prefer account-level; fall back to global (account_id IS NULL)
            row = conn.execute(
                text("""
                    SELECT auto_execute_threshold, enabled
                    FROM agent_configurations
                    WHERE (account_id = :aid OR account_id IS NULL)
                      AND agent_id = 'campaign_manager'
                    ORDER BY account_id DESC NULLS LAST
                    LIMIT 1
                """),
                {"aid": aid},
            ).fetchone()
            if row:
                out["auto_execute_threshold"] = float(row[0] or 0.99)
                out["enabled"] = bool(row[1])
    except Exception as e:
        log.warning("Could not load agent_configurations: %s", e)
    return out


@account_bp.route("/autopilot", methods=["GET"], endpoint="autopilot_settings")
@login_required
def autopilot_settings():
    from app.account import current_account_id
    aid = current_account_id()
    settings = _get_settings(aid)
    agent_cfg = _get_agent_config(aid)

    threshold = agent_cfg["auto_execute_threshold"]
    auto_low = threshold <= 0.95
    auto_medium = threshold <= 0.80

    return render_template(
        "account/autopilot.html",
        autopilot_enabled=settings["autopilot_enabled"] == "1",
        auto_low=auto_low,
        auto_medium=auto_medium,
        goal=settings["autopilot_goal"],
        budget_limit=settings.get("budget_change_limit", "100"),
    )


@account_bp.route("/autopilot", methods=["POST"], endpoint="autopilot_save")
@login_required
def autopilot_save():
    from app.account import current_account_id
    aid = current_account_id()

    autopilot_enabled = "1" if request.form.get("autopilot_enabled") else "0"
    auto_low = bool(request.form.get("auto_execute_low"))
    auto_medium = bool(request.form.get("auto_execute_medium"))
    goal = request.form.get("goal", "lower_cpl")
    if goal not in ("lower_cpl", "more_leads", "stop_waste", "improve_quality"):
        goal = "lower_cpl"

    try:
        budget_limit = min(500, max(0, int(request.form.get("budget_change_limit", 100))))
    except (ValueError, TypeError):
        budget_limit = 100

    # Threshold: low+medium → 0.80, low only → 0.95, neither → 0.99
    if auto_low and auto_medium:
        threshold = 0.80
    elif auto_low:
        threshold = 0.95
    else:
        threshold = 0.99

    try:
        with db.engine.connect() as conn:
            with conn.begin():
                _upsert_setting(conn, aid, "autopilot_enabled", autopilot_enabled)
                _upsert_setting(conn, aid, "autopilot_goal", goal)
                _upsert_setting(conn, aid, "budget_change_limit", str(budget_limit))
                _upsert_setting(conn, aid, "autopilot_saved_at", datetime.utcnow().isoformat())

                # Upsert all agent configs for this account
                agents = [
                    "campaign_manager", "budget_guardian", "keyword_optimizer",
                    "negative_keyword_agent", "ad_copy_agent", "quality_score_agent",
                ]
                for agent_id in agents:
                    conn.execute(
                        text("""
                            INSERT INTO agent_configurations
                              (account_id, agent_id, agent_type, enabled, auto_execute_threshold)
                            VALUES (:aid, :agent_id, :agent_type, :enabled, :threshold)
                            ON CONFLICT (agent_id, account_id) DO UPDATE
                              SET enabled = EXCLUDED.enabled,
                                  auto_execute_threshold = EXCLUDED.auto_execute_threshold,
                                  updated_at = NOW()
                        """),
                        {
                            "aid": aid,
                            "agent_id": agent_id,
                            "agent_type": agent_id.replace("_", " ").title().replace(" ", "") + "Agent",
                            "enabled": autopilot_enabled == "1",
                            "threshold": threshold,
                        },
                    )

        flash("Autopilot settings saved.", "success")
        _log("autopilot_saved", aid, {
            "enabled": autopilot_enabled,
            "threshold": threshold,
            "goal": goal,
            "budget_limit": budget_limit,
        })
    except Exception as e:
        log.exception("autopilot_save failed: %s", e)
        flash("Could not save settings. Please try again.", "error")

    return redirect(url_for("account_bp.autopilot_settings"))
