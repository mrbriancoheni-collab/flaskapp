"""
Onboarding step 3: goal selection and budget entry.

Routes:
  GET  /onboard/goal  — show goal form
  POST /onboard/goal  — save goal + budget, mark onboarding complete
"""
from __future__ import annotations

import logging

from flask import flash, redirect, render_template, request, url_for
from sqlalchemy import text

from app import db
from app.auth.utils import login_required
from app.onboarding import onboarding_bp

log = logging.getLogger(__name__)

_GOALS = [
    ("lower_cpl",       "Lower CPL",       "Reduce cost per lead",            "fa-arrow-trend-down"),
    ("more_leads",      "More Leads",       "Maximize lead volume",            "fa-chart-line"),
    ("stop_waste",      "Stop Waste",       "Cut wasted ad spend fast",        "fa-scissors"),
    ("improve_quality", "Better Quality",   "Higher-intent, easier-to-close",  "fa-star"),
]


def _upsert(conn, aid: int, key: str, value: str) -> None:
    conn.execute(
        text("""
            INSERT INTO account_settings (account_id, key, value)
            VALUES (:aid, :key, :val)
            ON CONFLICT (account_id, key) DO UPDATE SET value = EXCLUDED.value
        """),
        {"aid": aid, "key": key, "val": value},
    )


@onboarding_bp.route("/goal", methods=["GET"], endpoint="onboarding_goal")
@login_required
def onboarding_goal():
    return render_template("onboard/goal.html", goals=_GOALS)


@onboarding_bp.route("/goal", methods=["POST"], endpoint="onboarding_goal_save")
@login_required
def onboarding_goal_save():
    from app.account import current_account_id
    aid = current_account_id()

    goal = request.form.get("goal", "lower_cpl")
    if goal not in {g[0] for g in _GOALS}:
        goal = "lower_cpl"

    try:
        monthly_budget = min(500_000, max(0, int(request.form.get("monthly_budget", 0))))
    except (ValueError, TypeError):
        monthly_budget = 0

    try:
        target_cpl = min(10_000, max(0, int(request.form.get("target_cpl", 0))))
    except (ValueError, TypeError):
        target_cpl = 0

    try:
        with db.engine.connect() as conn:
            with conn.begin():
                _upsert(conn, aid, "autopilot_goal", goal)
                if monthly_budget:
                    _upsert(conn, aid, "monthly_budget", str(monthly_budget))
                if target_cpl:
                    _upsert(conn, aid, "target_cpl", str(target_cpl))
                # Mark onboarding complete
                conn.execute(
                    text("UPDATE accounts SET onboarding_complete = TRUE WHERE id = :aid"),
                    {"aid": aid},
                )
    except Exception as e:
        log.exception("onboarding_goal_save failed: %s", e)
        flash("Could not save. Please try again.", "error")
        return redirect(url_for("onboarding_bp.onboarding_goal"))

    return redirect(url_for("account_bp.dashboard"))
