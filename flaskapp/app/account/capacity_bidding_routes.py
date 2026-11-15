# app/account/capacity_bidding_routes.py
"""
Capacity-Aware Bidding settings.

Route: GET/POST /account/capacity-bidding
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from flask import flash, g, redirect, render_template, request, url_for
from sqlalchemy import text

from app import db
from app.auth.utils import login_required, current_account_id
from app.account import account_bp

logger = logging.getLogger(__name__)

_SETTINGS_KEY = "capacity_bidding"


def _load_config(aid: int) -> Optional[Dict[str, Any]]:
    """
    Try several storage strategies in order:
    1. accounts.settings_json column (JSON dict)
    2. account_settings key-value table
    Returns a dict or None.
    """
    # Strategy 1: accounts.settings_json
    try:
        row = db.session.execute(
            text("SELECT settings_json FROM accounts WHERE id = :id"),
            {"id": aid},
        ).mappings().first()
        if row and row.get("settings_json"):
            raw = row["settings_json"]
            data = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(data, dict) and _SETTINGS_KEY in data:
                return data[_SETTINGS_KEY]
    except Exception:
        pass

    # Strategy 2: account_settings key-value table
    try:
        row = db.session.execute(
            text(
                "SELECT setting_value FROM account_settings "
                "WHERE account_id = :aid AND setting_key = :key LIMIT 1"
            ),
            {"aid": aid, "key": _SETTINGS_KEY},
        ).mappings().first()
        if row and row.get("setting_value"):
            raw = row["setting_value"]
            return json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        pass

    return None


def _save_config(aid: int, cfg: Dict[str, Any]) -> None:
    """Persist config — tries account_settings KV table, falls back to in-memory log."""
    try:
        existing = db.session.execute(
            text(
                "SELECT id FROM account_settings "
                "WHERE account_id = :aid AND setting_key = :key LIMIT 1"
            ),
            {"aid": aid, "key": _SETTINGS_KEY},
        ).fetchone()

        val = json.dumps(cfg)
        if existing:
            db.session.execute(
                text(
                    "UPDATE account_settings SET setting_value = :val, updated_at = NOW() "
                    "WHERE account_id = :aid AND setting_key = :key"
                ),
                {"val": val, "aid": aid, "key": _SETTINGS_KEY},
            )
        else:
            db.session.execute(
                text(
                    "INSERT INTO account_settings (account_id, setting_key, setting_value) "
                    "VALUES (:aid, :key, :val)"
                ),
                {"aid": aid, "key": _SETTINGS_KEY, "val": val},
            )
        db.session.commit()
    except Exception as exc:
        logger.warning("capacity_bidding save failed (account_settings): %s", exc)
        db.session.rollback()
        # Attempt accounts.settings_json update
        try:
            row = db.session.execute(
                text("SELECT settings_json FROM accounts WHERE id = :id"),
                {"id": aid},
            ).mappings().first()
            existing_json: Dict = {}
            if row and row.get("settings_json"):
                raw = row["settings_json"]
                existing_json = json.loads(raw) if isinstance(raw, str) else (raw or {})
            existing_json[_SETTINGS_KEY] = cfg
            db.session.execute(
                text("UPDATE accounts SET settings_json = :val WHERE id = :id"),
                {"val": json.dumps(existing_json), "id": aid},
            )
            db.session.commit()
        except Exception as exc2:
            logger.warning("capacity_bidding fallback save also failed: %s", exc2)
            db.session.rollback()


# ── Route ──────────────────────────────────────────────────────────────────────

@account_bp.route("/capacity-bidding", methods=["GET", "POST"], endpoint="capacity_bidding")
@login_required
def capacity_bidding():
    aid = current_account_id()
    config = _load_config(aid) if aid else {}

    if request.method == "POST":
        action = request.form.get("action", "save_config")

        if action == "pause_now":
            cfg = dict(config or {})
            cfg["ad_status_override"] = "paused"
            if aid:
                _save_config(aid, cfg)
            flash("All ads paused. Resume them below when you're ready.", "success")
            return redirect(url_for("account_bp.capacity_bidding"))

        elif action == "resume_now":
            cfg = dict(config or {})
            cfg["ad_status_override"] = "active"
            if aid:
                _save_config(aid, cfg)
            flash("Ads resumed.", "success")
            return redirect(url_for("account_bp.capacity_bidding"))

        else:  # save_config
            try:
                cfg = {
                    "max_jobs_per_week":       int(request.form.get("max_jobs_per_week", 20)),
                    "current_jobs_this_week":  int(request.form.get("current_jobs_this_week", 0)),
                    "pause_when_full":         bool(request.form.get("pause_when_full")),
                    "bid_reduction":           request.form.get("bid_reduction", "-50"),
                    "resume_buffer_pct":       int(request.form.get("resume_buffer_pct", 25)),
                    "ad_status_override":      (config or {}).get("ad_status_override", "active"),
                }
                if aid:
                    _save_config(aid, cfg)
                config = cfg
                flash("Capacity settings saved.", "success")
            except (ValueError, TypeError) as exc:
                logger.warning("capacity_bidding form parse error: %s", exc)
                flash("Invalid values — please check your inputs.", "error")
            return redirect(url_for("account_bp.capacity_bidding"))

    return render_template(
        "account/capacity_bidding.html",
        config=config or {},
        account=getattr(g, "user", None),
    )
