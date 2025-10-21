# app/onboarding_bp.py
from __future__ import annotations
from datetime import datetime
from typing import Any, Dict

from flask import Blueprint, request, jsonify, session, current_app
from sqlalchemy.exc import SQLAlchemyError

from app import db
from app.models import BusinessProfile

# Optional auth: prefer flask_login if present, else fall back to session keys
try:
    from app.auth.utils import login_required, current_user  # type: ignore
    _HAS_FLASK_LOGIN = True
except Exception:  # pragma: no cover
    _HAS_FLASK_LOGIN = False

    def login_required(fn):  # very light fallback; you already gate pages by auth UI
        def _wrap(*a, **k):
            if not _get_session_user_id():
                return jsonify({"error": "auth required"}), 401
            return fn(*a, **k)
        _wrap.__name__ = fn.__name__
        return _wrap

    class _CurrentUser:
        id = None
        account_id = None
    current_user = _CurrentUser()  # type: ignore


onboarding_bp = Blueprint("onboarding_bp", __name__, url_prefix="/onboarding")


def _get_session_user_id() -> Any:
    """Fallback if flask_login isn't available. Looks for IDs in session using app config AUTH_SESSION_KEYS."""
    keys = current_app.config.get("AUTH_SESSION_KEYS", ("user_id", "user", "uid", "email"))
    for k in keys:
        v = session.get(k)
        if v:
            return v
    return None


def _get_account_and_user_ids() -> Dict[str, Any]:
    """
    Resolve (account_id, user_id) regardless of auth style.
    You likely already store these in session or on current_user.
    """
    # flask_login path
    if _HAS_FLASK_LOGIN and getattr(current_user, "is_authenticated", False):
        acc_id = getattr(current_user, "account_id", None)
        usr_id = getattr(current_user, "id", None)
        # fallback to session if not present
        if not usr_id:
            usr_id = _get_session_user_id()
        return {"account_id": acc_id, "user_id": usr_id}

    # session-only path
    usr_id = _get_session_user_id()
    # Try to find a default account_id from session if you store one (optional)
    acc_id = session.get("account_id") or session.get("acct_id")
    return {"account_id": acc_id, "user_id": usr_id}


def _ensure_profile() -> BusinessProfile:
    ids = _get_account_and_user_ids()
    if not ids["user_id"]:
        raise PermissionError("auth required")
    if not ids["account_id"]:
        # If you don't separate accounts, you can map account_id=user_id
        ids["account_id"] = ids["user_id"]

    bp = BusinessProfile.query.filter_by(account_id=ids["account_id"]).first()
    if not bp:
        # Seed business_name from any session/company field if you have it
        seed_name = session.get("company") or session.get("business_name") or "Your Business"
        bp = BusinessProfile(
            account_id=ids["account_id"],
            user_id=ids["user_id"],
            business_name=seed_name,
        )
        db.session.add(bp)
        db.session.commit()
    return bp


@onboarding_bp.get("/me")
@login_required
def get_profile():
    try:
        bp = _ensure_profile()
    except PermissionError:
        return jsonify({"error": "auth required"}), 401

    # Serialize minimal fields used by the modal
    data = {
        "business_name": bp.business_name,
        "phone": bp.phone,
        "website": bp.website,
        "service_area": bp.service_area,
        "services": bp.services or [],
        "top_services": bp.top_services or [],
        "price_position": bp.price_position,
        "ideal_customers": bp.ideal_customers or [],
        "urgency": bp.urgency,
        "tone": bp.tone,
        "lead_channels": bp.lead_channels or [],
        "why_choose_us": bp.why_choose_us or "",
        "current_promo": bp.current_promo or "",
        "hours": bp.hours or "",
        "primary_goal": bp.primary_goal,
        "ads_budget": bp.ads_budget,
        "edge_statement": bp.edge_statement or "",
        "competitors": bp.competitors or "",
        "approvals_via_email": bool(bp.approvals_via_email),
    }
    return jsonify({"status": bp.status, "data": data})


@onboarding_bp.post("/save")
@login_required
def save_step():
    """
    Accepts JSON: { "step": <int>, "data": {field: value, ...} }
    Updates the BusinessProfile with only those fields; commits.
    """
    payload = request.get_json(silent=True) or {}
    updates: dict = payload.get("data", {}) or {}

    try:
        bp = _ensure_profile()
    except PermissionError:
        return jsonify({"error": "auth required"}), 401

    # Whitelist fields we allow to be updated via onboarding
    ALLOWED = {
        "business_name", "phone", "website", "service_area",
        "services", "top_services", "price_position",
        "ideal_customers", "urgency", "tone", "lead_channels",
        "why_choose_us", "current_promo", "hours",
        "primary_goal", "ads_budget",
        "edge_statement", "competitors",
        "approvals_via_email",
    }

    changed = False
    for k, v in updates.items():
        if k not in ALLOWED:
            continue
        # Normalize lists for JSON fields if input is a comma string
        if k in {"services", "top_services", "ideal_customers", "lead_channels"} and isinstance(v, str):
            v = [s.strip() for s in v.split(",") if s.strip()]
        setattr(bp, k, v)
        changed = True

    if changed:
        try:
            db.session.commit()
        except SQLAlchemyError as e:
            current_app.logger.exception("Onboarding save failed: %s", e)
            db.session.rollback()
            return jsonify({"error": "save_failed"}), 400

    return jsonify({"ok": True})


@onboarding_bp.post("/complete")
@login_required
def complete():
    try:
        bp = _ensure_profile()
    except PermissionError:
        return jsonify({"error": "auth required"}), 401

    bp.status = "complete"
    bp.completed_at = datetime.utcnow()
    try:
        db.session.commit()
    except SQLAlchemyError as e:
        current_app.logger.exception("Onboarding complete failed: %s", e)
        db.session.rollback()
        return jsonify({"error": "complete_failed"}), 400

    return jsonify({"ok": True})
