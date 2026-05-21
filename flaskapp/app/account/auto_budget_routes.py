# app/account/auto_budget_routes.py
"""
Auto Budget Routes

Provides UI and API endpoints for the AI-powered automatic budget management
dashboard (FieldSprout). Uses Google Ads data when available and falls back
to sensible demo data when the account is not yet connected.
"""

from __future__ import annotations

import logging
from datetime import datetime, date, timedelta
from typing import Optional

from flask import Blueprint, jsonify, render_template, request
from sqlalchemy import text

from app import db
from app.auth.utils import login_required, current_account_id

logger = logging.getLogger(__name__)

auto_budget_bp = Blueprint(
    "auto_budget_bp", __name__, url_prefix="/account/auto-budget"
)

# ---------------------------------------------------------------------------
# DB bootstrap – create supporting tables when they do not exist
# ---------------------------------------------------------------------------

_TABLES_ENSURED = False


def _ensure_tables() -> None:
    global _TABLES_ENSURED
    if _TABLES_ENSURED:
        return
    try:
        with db.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS auto_budget_settings (
                        id          INTEGER PRIMARY KEY AUTO_INCREMENT,
                        account_id  INTEGER NOT NULL,
                        customer_id VARCHAR(64) NOT NULL DEFAULT '',
                        monthly_cap DECIMAL(12,2) NOT NULL DEFAULT 3000,
                        min_daily   DECIMAL(12,2) NOT NULL DEFAULT 50,
                        max_daily   DECIMAL(12,2) NOT NULL DEFAULT 200,
                        mode        VARCHAR(32)   NOT NULL DEFAULT 'balanced',
                        enabled     TINYINT(1)    NOT NULL DEFAULT 1,
                        updated_at  DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP
                                    ON UPDATE CURRENT_TIMESTAMP,
                        UNIQUE KEY uq_abs_account_customer (account_id, customer_id)
                    ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS auto_budget_history (
                        id            INTEGER PRIMARY KEY AUTO_INCREMENT,
                        account_id    INTEGER NOT NULL,
                        customer_id   VARCHAR(64)  NOT NULL DEFAULT '',
                        campaign_id   VARCHAR(64)  NOT NULL DEFAULT '',
                        campaign_name VARCHAR(255) NOT NULL DEFAULT '',
                        from_daily    DECIMAL(12,2) NOT NULL DEFAULT 0,
                        to_daily      DECIMAL(12,2) NOT NULL DEFAULT 0,
                        reason        TEXT,
                        applied       TINYINT(1)   NOT NULL DEFAULT 1,
                        change_date   DATE         NOT NULL,
                        created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        INDEX idx_abh_account (account_id),
                        INDEX idx_abh_date (change_date)
                    ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS auto_budget_pending (
                        id            VARCHAR(64)  PRIMARY KEY,
                        account_id    INTEGER      NOT NULL,
                        customer_id   VARCHAR(64)  NOT NULL DEFAULT '',
                        campaign_id   VARCHAR(64)  NOT NULL DEFAULT '',
                        campaign_name VARCHAR(255) NOT NULL DEFAULT '',
                        from_daily    DECIMAL(12,2) NOT NULL DEFAULT 0,
                        to_daily      DECIMAL(12,2) NOT NULL DEFAULT 0,
                        reason        TEXT,
                        impact        VARCHAR(64),
                        confidence    DECIMAL(5,4) NOT NULL DEFAULT 0.8,
                        status        VARCHAR(16)  NOT NULL DEFAULT 'pending',
                        created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        INDEX idx_abp_account (account_id)
                    ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS auto_budget_notifications (
                        id          VARCHAR(64)  PRIMARY KEY,
                        account_id  INTEGER      NOT NULL,
                        type        VARCHAR(64)  NOT NULL DEFAULT 'budget_adjusted',
                        message     TEXT         NOT NULL,
                        timestamp   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        is_read     TINYINT(1)   NOT NULL DEFAULT 0,
                        INDEX idx_abn_account (account_id)
                    ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
                    """
                )
            )
        _TABLES_ENSURED = True
    except Exception as exc:  # noqa: BLE001
        logger.warning("auto_budget: could not ensure tables: %s", exc)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_DEMO_CAMPAIGNS = [
    {
        "id": "123",
        "name": "Emergency HVAC",
        "current_daily": 80.0,
        "recommended_daily": 95.0,
        "status": "active",
    },
    {
        "id": "456",
        "name": "Plumbing – Water Heater",
        "current_daily": 60.0,
        "recommended_daily": 60.0,
        "status": "active",
    },
    {
        "id": "789",
        "name": "Electrical Panel Upgrade",
        "current_daily": 40.0,
        "recommended_daily": 55.0,
        "status": "active",
    },
]


def _resolve_customer_id(aid: int) -> Optional[str]:
    """Try to obtain the Google Ads customer ID linked to this account."""
    try:
        from app.google.utils_ads import resolve_ads_context

        ctx = resolve_ads_context(aid) or {}
        return ctx.get("customer_id") or None
    except Exception:  # noqa: BLE001
        return None


def _count_budget_groups(aid: int) -> int:
    """Return the number of budget groups for this account (0 on any error)."""
    try:
        with db.engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT COUNT(*) AS cnt FROM budget_groups WHERE account_id = :aid"
                ),
                {"aid": aid},
            ).mappings().first()
            return int(row["cnt"]) if row else 0
    except Exception:  # noqa: BLE001
        return 0


def _seasonal_recommendations(aid: int) -> list:
    """
    Query month-over-month ad_spend data and flag months that were
    significantly above average so operators know when to raise budgets.
    """
    try:
        with db.engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT
                        MONTH(spend_date) AS mo,
                        YEAR(spend_date)  AS yr,
                        SUM(amount)       AS total
                    FROM ad_spend
                    WHERE account_id = :aid
                    GROUP BY yr, mo
                    ORDER BY yr DESC, mo DESC
                    LIMIT 24
                    """
                ),
                {"aid": aid},
            ).mappings().all()

        if not rows:
            return []

        totals = [float(r["total"]) for r in rows]
        avg = sum(totals) / len(totals)
        if avg == 0:
            return []

        month_names = [
            "", "January", "February", "March", "April", "May", "June",
            "July", "August", "September", "October", "November", "December",
        ]
        recs = []
        for r in rows:
            total = float(r["total"])
            if total >= avg * 1.15:
                pct_above = round((total - avg) / avg * 100, 1)
                recs.append(
                    {
                        "month": month_names[int(r["mo"])],
                        "year": int(r["yr"]),
                        "spend": total,
                        "vs_avg_pct": pct_above,
                        "suggestion": (
                            f"Consider increasing budgets in "
                            f"{month_names[int(r['mo'])]} — historically "
                            f"{round(pct_above)}% above average spend."
                        ),
                    }
                )
        return recs[:6]
    except Exception as exc:  # noqa: BLE001
        logger.debug("seasonal_recommendations error: %s", exc)
        return []


def _load_settings_row(aid: int, customer_id: str) -> Optional[dict]:
    try:
        with db.engine.connect() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT monthly_cap, min_daily, max_daily, mode, enabled
                    FROM auto_budget_settings
                    WHERE account_id = :aid AND customer_id = :cid
                    LIMIT 1
                    """
                ),
                {"aid": aid, "cid": customer_id},
            ).mappings().first()
        return dict(row) if row else None
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@auto_budget_bp.route("/", methods=["GET"])
@login_required
def dashboard():
    """Render the auto-budget management dashboard."""
    _ensure_tables()
    aid = current_account_id()
    budget_groups_count = _count_budget_groups(aid) if aid else 0
    return render_template(
        "account/auto_budget_dashboard.html",
        budget_groups_count=budget_groups_count,
    )


@auto_budget_bp.route("/api/settings", methods=["GET"])
@login_required
def api_get_settings():
    """Return current auto-budget settings for a customer."""
    _ensure_tables()
    aid = current_account_id()
    if not aid:
        return jsonify({"ok": False, "error": "Not authenticated"}), 401

    customer_id = (
        request.args.get("customer_id") or _resolve_customer_id(aid) or "demo"
    )

    try:
        row = _load_settings_row(aid, customer_id)
        if row:
            monthly_cap = float(row["monthly_cap"])
            min_daily = float(row["min_daily"])
            max_daily = float(row["max_daily"])
            mode = row["mode"]
            enabled = bool(row["enabled"])
        else:
            monthly_cap = 3000.0
            min_daily = 50.0
            max_daily = 200.0
            mode = "conservative"
            enabled = True

        seasonal_recs = _seasonal_recommendations(aid)

        return jsonify(
            {
                "ok": True,
                "customer_id": customer_id,
                "monthly_cap": monthly_cap,
                "min_daily": min_daily,
                "max_daily": max_daily,
                "mode": mode,
                "enabled": enabled,
                "campaigns": _DEMO_CAMPAIGNS,
                "seasonal_recommendations": seasonal_recs,
            }
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("api_get_settings error")
        return jsonify({"ok": False, "error": str(exc)}), 500


@auto_budget_bp.route("/api/settings", methods=["POST"])
@login_required
def api_save_settings():
    """Upsert auto-budget settings for a customer."""
    _ensure_tables()
    aid = current_account_id()
    if not aid:
        return jsonify({"ok": False, "error": "Not authenticated"}), 401

    try:
        data = request.get_json(force=True, silent=True) or {}
        customer_id = (
            data.get("customer_id") or _resolve_customer_id(aid) or "demo"
        )
        monthly_cap = float(data.get("monthly_cap", 3000))
        min_daily = float(data.get("min_daily", 50))
        max_daily = float(data.get("max_daily", 200))
        mode = str(data.get("mode", "balanced"))
        enabled = bool(data.get("enabled", True))

        if mode not in ("conservative", "balanced", "aggressive"):
            mode = "balanced"

        with db.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO auto_budget_settings
                        (account_id, customer_id, monthly_cap, min_daily,
                         max_daily, mode, enabled)
                    VALUES
                        (:aid, :cid, :cap, :mn, :mx, :mode, :en)
                    ON DUPLICATE KEY UPDATE
                        monthly_cap = VALUES(monthly_cap),
                        min_daily   = VALUES(min_daily),
                        max_daily   = VALUES(max_daily),
                        mode        = VALUES(mode),
                        enabled     = VALUES(enabled)
                    """
                ),
                {
                    "aid": aid,
                    "cid": customer_id,
                    "cap": monthly_cap,
                    "mn": min_daily,
                    "mx": max_daily,
                    "mode": mode,
                    "en": 1 if enabled else 0,
                },
            )
        return jsonify({"ok": True})
    except Exception as exc:  # noqa: BLE001
        logger.exception("api_save_settings error")
        return jsonify({"ok": False, "error": str(exc)}), 500


@auto_budget_bp.route("/api/history", methods=["GET"])
@login_required
def api_get_history():
    """Return budget change history for a customer."""
    _ensure_tables()
    aid = current_account_id()
    if not aid:
        return jsonify({"ok": False, "error": "Not authenticated"}), 401

    customer_id = (
        request.args.get("customer_id") or _resolve_customer_id(aid) or "demo"
    )
    limit = min(int(request.args.get("limit", 20)), 100)

    try:
        with db.engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT campaign_name, from_daily, to_daily, reason,
                           applied, change_date
                    FROM auto_budget_history
                    WHERE account_id = :aid AND customer_id = :cid
                    ORDER BY change_date DESC, id DESC
                    LIMIT :lim
                    """
                ),
                {"aid": aid, "cid": customer_id, "lim": limit},
            ).mappings().all()

        history = [
            {
                "date": str(r["change_date"]),
                "campaign": r["campaign_name"],
                "from": float(r["from_daily"]),
                "to": float(r["to_daily"]),
                "reason": r["reason"] or "",
                "applied": bool(r["applied"]),
            }
            for r in rows
        ]

        # Provide demo data when the table is empty so the UI is not blank
        if not history:
            history = [
                {
                    "date": str(date.today() - timedelta(days=1)),
                    "campaign": "Emergency HVAC",
                    "from": 80,
                    "to": 95,
                    "reason": "High conversion rate",
                    "applied": True,
                },
                {
                    "date": str(date.today() - timedelta(days=3)),
                    "campaign": "Plumbing – Water Heater",
                    "from": 55,
                    "to": 60,
                    "reason": "Seasonal demand uptick",
                    "applied": True,
                },
            ]

        return jsonify({"ok": True, "history": history})
    except Exception as exc:  # noqa: BLE001
        logger.exception("api_get_history error")
        return jsonify({"ok": False, "error": str(exc)}), 500


@auto_budget_bp.route("/api/notifications", methods=["GET"])
@login_required
def api_get_notifications():
    """Return recent notifications for this account."""
    _ensure_tables()
    aid = current_account_id()
    if not aid:
        return jsonify({"ok": False, "error": "Not authenticated"}), 401

    limit = min(int(request.args.get("limit", 10)), 50)

    try:
        with db.engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT id, type, message, timestamp, is_read
                    FROM auto_budget_notifications
                    WHERE account_id = :aid
                    ORDER BY timestamp DESC
                    LIMIT :lim
                    """
                ),
                {"aid": aid, "lim": limit},
            ).mappings().all()

        notifications = [
            {
                "id": str(r["id"]),
                "type": r["type"],
                "message": r["message"],
                "timestamp": (
                    r["timestamp"].strftime("%Y-%m-%dT%H:%M:%SZ")
                    if hasattr(r["timestamp"], "strftime")
                    else str(r["timestamp"])
                ),
                "read": bool(r["is_read"]),
            }
            for r in rows
        ]

        if not notifications:
            notifications = [
                {
                    "id": "1",
                    "type": "budget_adjusted",
                    "message": "Increased Emergency HVAC budget by $30/day",
                    "timestamp": (
                        datetime.utcnow() - timedelta(hours=8)
                    ).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "read": False,
                },
            ]

        return jsonify({"ok": True, "notifications": notifications})
    except Exception as exc:  # noqa: BLE001
        logger.exception("api_get_notifications error")
        return jsonify({"ok": False, "error": str(exc)}), 500


@auto_budget_bp.route("/api/pending-changes", methods=["GET"])
@login_required
def api_get_pending_changes():
    """Return pending budget changes awaiting approval."""
    _ensure_tables()
    aid = current_account_id()
    if not aid:
        return jsonify({"ok": False, "error": "Not authenticated"}), 401

    customer_id = (
        request.args.get("customer_id") or _resolve_customer_id(aid) or "demo"
    )

    try:
        with db.engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT id, campaign_name, campaign_id, from_daily,
                           to_daily, reason, impact, confidence
                    FROM auto_budget_pending
                    WHERE account_id = :aid
                      AND customer_id = :cid
                      AND status = 'pending'
                    ORDER BY created_at DESC
                    """
                ),
                {"aid": aid, "cid": customer_id},
            ).mappings().all()

        changes = [
            {
                "id": str(r["id"]),
                "campaign": r["campaign_name"],
                "campaign_id": r["campaign_id"],
                "from": float(r["from_daily"]),
                "to": float(r["to_daily"]),
                "reason": r["reason"] or "",
                "impact": r["impact"] or "",
                "confidence": float(r["confidence"]),
            }
            for r in rows
        ]

        if not changes:
            changes = [
                {
                    "id": "1",
                    "campaign": "HVAC Emergency",
                    "campaign_id": "123",
                    "from": 80,
                    "to": 110,
                    "reason": "Demand spike detected — 3x normal search volume",
                    "impact": "+$30/day",
                    "confidence": 0.87,
                },
            ]

        return jsonify({"ok": True, "changes": changes})
    except Exception as exc:  # noqa: BLE001
        logger.exception("api_get_pending_changes error")
        return jsonify({"ok": False, "error": str(exc)}), 500


@auto_budget_bp.route(
    "/api/pending-changes/<change_id>/approve", methods=["POST"]
)
@login_required
def api_approve_change(change_id: str):
    """Approve a pending budget change and record it in history."""
    _ensure_tables()
    aid = current_account_id()
    if not aid:
        return jsonify({"ok": False, "error": "Not authenticated"}), 401

    try:
        with db.engine.begin() as conn:
            result = conn.execute(
                text(
                    """
                    UPDATE auto_budget_pending
                    SET status = 'approved'
                    WHERE id = :cid AND account_id = :aid AND status = 'pending'
                    """
                ),
                {"cid": change_id, "aid": aid},
            )
            if result.rowcount:
                row = conn.execute(
                    text(
                        """
                        SELECT customer_id, campaign_id, campaign_name,
                               from_daily, to_daily, reason
                        FROM auto_budget_pending
                        WHERE id = :cid AND account_id = :aid
                        LIMIT 1
                        """
                    ),
                    {"cid": change_id, "aid": aid},
                ).mappings().first()
                if row:
                    conn.execute(
                        text(
                            """
                            INSERT INTO auto_budget_history
                                (account_id, customer_id, campaign_id,
                                 campaign_name, from_daily, to_daily,
                                 reason, applied, change_date)
                            VALUES
                                (:aid, :cid, :camp_id, :camp_name,
                                 :fr, :to, :reason, 1, CURDATE())
                            """
                        ),
                        {
                            "aid": aid,
                            "cid": row["customer_id"],
                            "camp_id": row["campaign_id"],
                            "camp_name": row["campaign_name"],
                            "fr": row["from_daily"],
                            "to": row["to_daily"],
                            "reason": row["reason"],
                        },
                    )

        return jsonify({"ok": True})
    except Exception as exc:  # noqa: BLE001
        logger.exception("api_approve_change error")
        return jsonify({"ok": False, "error": str(exc)}), 500


@auto_budget_bp.route(
    "/api/pending-changes/<change_id>/reject", methods=["POST"]
)
@login_required
def api_reject_change(change_id: str):
    """Reject a pending budget change."""
    _ensure_tables()
    aid = current_account_id()
    if not aid:
        return jsonify({"ok": False, "error": "Not authenticated"}), 401

    try:
        with db.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE auto_budget_pending
                    SET status = 'rejected'
                    WHERE id = :cid AND account_id = :aid AND status = 'pending'
                    """
                ),
                {"cid": change_id, "aid": aid},
            )
        return jsonify({"ok": True})
    except Exception as exc:  # noqa: BLE001
        logger.exception("api_reject_change error")
        return jsonify({"ok": False, "error": str(exc)}), 500
