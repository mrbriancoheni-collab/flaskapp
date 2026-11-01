"""
Trade profile — business details that inform AI decisions.

Routes:
  GET  /account/trade-profile  — show form
  POST /account/trade-profile  — save
"""
from __future__ import annotations

import logging

from flask import flash, redirect, render_template, request, url_for
from sqlalchemy import text

from app import db
from app.auth.utils import login_required
from app.account import account_bp

log = logging.getLogger(__name__)

_TRADES = [
    "hvac", "plumbing", "electrical", "roofing", "pest_control",
    "landscaping", "garage_door", "pool_service", "solar",
    "concrete", "fencing", "irrigation", "lawn_care", "restoration",
    "windows_doors", "painting", "cleaning", "general_contracting", "flooring",
]

_GOALS = ["lower_cpl", "more_leads", "stop_waste", "improve_quality"]


def _get_profile(aid: int) -> dict:
    out = {
        "business_name": "",
        "trade": "",
        "service_area": "",
        "avg_ticket": "",
        "close_rate": "",
        "monthly_budget": "",
        "target_cpl": "",
        "business_description": "",
        "business_services": "",
    }
    try:
        with db.engine.connect() as conn:
            row = conn.execute(
                text("""
                    SELECT business_name, detected_trade, detected_location,
                           business_description
                    FROM accounts WHERE id = :aid
                """),
                {"aid": aid},
            ).fetchone()
            if row:
                out["business_name"] = row[0] or ""
                out["trade"] = row[1] or ""
                out["service_area"] = row[2] or ""
                out["business_description"] = row[3] or ""

            rows = conn.execute(
                text("""
                    SELECT key, value FROM account_settings
                    WHERE account_id = :aid
                    AND key IN ('avg_ticket','close_rate','monthly_budget','target_cpl','business_services')
                """),
                {"aid": aid},
            ).fetchall()
            for r in rows:
                out[r[0]] = r[1]
    except Exception as e:
        log.warning("trade_profile load failed: %s", e)
    return out


def _upsert(conn, aid: int, key: str, value: str) -> None:
    conn.execute(
        text("""
            INSERT INTO account_settings (account_id, `key`, value)
            VALUES (:aid, :key, :val)
            ON DUPLICATE KEY UPDATE value = VALUES(value)
        """),
        {"aid": aid, "key": key, "val": value},
    )


@account_bp.route("/trade-profile", methods=["GET"], endpoint="trade_profile")
@login_required
def trade_profile():
    from app.account import current_account_id
    aid = current_account_id()
    profile = _get_profile(aid)
    return render_template(
        "account/trade_profile.html",
        profile=profile,
        trades=_TRADES,
    )


@account_bp.route("/trade-profile", methods=["POST"], endpoint="trade_profile_save")
@login_required
def trade_profile_save():
    from app.account import current_account_id
    aid = current_account_id()

    trade = request.form.get("trade", "")
    if trade not in _TRADES:
        trade = ""

    service_area = request.form.get("service_area", "")[:300]
    business_description = request.form.get("business_description", "")[:1000]
    business_services = request.form.get("business_services", "")[:500]

    def _safe_int(key: str, lo: int = 0, hi: int = 1_000_000) -> str:
        try:
            return str(min(hi, max(lo, int(request.form.get(key, 0)))))
        except (ValueError, TypeError):
            return ""

    avg_ticket = _safe_int("avg_ticket", 0, 100_000)
    close_rate = _safe_int("close_rate", 0, 100)
    monthly_budget = _safe_int("monthly_budget", 0, 500_000)
    target_cpl = _safe_int("target_cpl", 0, 10_000)

    try:
        with db.engine.connect() as conn:
            with conn.begin():
                conn.execute(
                    text("""
                        UPDATE accounts
                        SET detected_trade = :trade,
                            detected_location = :loc,
                            business_description = :desc
                        WHERE id = :aid
                    """),
                    {"trade": trade or None, "loc": service_area or None,
                     "desc": business_description or None, "aid": aid},
                )
                for key, val in [
                    ("avg_ticket", avg_ticket),
                    ("close_rate", close_rate),
                    ("monthly_budget", monthly_budget),
                    ("target_cpl", target_cpl),
                    ("business_services", business_services),
                ]:
                    if val:
                        _upsert(conn, aid, key, val)

        flash("Trade profile saved.", "success")
    except Exception as e:
        log.exception("trade_profile_save failed: %s", e)
        flash("Could not save profile. Please try again.", "error")

    return redirect(url_for("account_bp.trade_profile"))
