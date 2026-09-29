# app/auth/utils.py
from __future__ import annotations

import re
from functools import wraps
from typing import Optional, Mapping, Tuple
from urllib.parse import urlparse

from flask import current_app, session, request, redirect, url_for, flash, g
from sqlalchemy import text

from app import db

# ---------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

def _auth_keys() -> Tuple[str, ...]:
    """
    Keys that indicate an authenticated session (configurable).
    Defaults are backward-compatible with earlier code.
    """
    return current_app.config.get(
        "AUTH_SESSION_KEYS",
        ("user_id", "user", "uid", "email"),
    )

def _normalize_email(v: Optional[str]) -> Optional[str]:
    if not v:
        return None
    v = str(v).strip().lower()
    return v or None

def _session_user_id() -> Optional[str]:
    """Try common keys for a user id."""
    for k in ("user_id", "uid", "user"):
        v = session.get(k)
        if v:
            return str(v)
    return None

def _session_email() -> Optional[str]:
    v = session.get("email")
    return _normalize_email(v)

def _fetch_user_row(uid: Optional[str], email: Optional[str]) -> Optional[Mapping]:
    """
    Return a row from `users` with at least: id, account_id, email, role, email_verified.
    Works even if only uid or only email is present.
    """
    if not uid and not email:
        return None

    with db.engine.connect() as conn:
        if email:
            row = (
                conn.execute(
                    text(
                        "SELECT id, account_id, email, role, email_verified "
                        "FROM users WHERE email=:e LIMIT 1"
                    ),
                    {"e": email},
                )
                .mappings()
                .first()
            )
            if row:
                return row

        if uid:
            return (
                conn.execute(
                    text(
                        "SELECT id, account_id, email, role, email_verified "
                        "FROM users WHERE id=:id LIMIT 1"
                    ),
                    {"id": uid},
                )
                .mappings()
                .first()
            )
    return None

def _user_row_cached() -> Optional[Mapping]:
    """
    Cache the current user row on flask.g for the request lifetime.

    When impersonating, returns the impersonated user's data instead of the admin's.
    This ensures current_account_id() and related helpers return the impersonated user's data.
    """
    if hasattr(g, "_user_row"):
        return g._user_row  # type: ignore[attr-defined]

    # Check for impersonation - if impersonating, use the impersonated user's ID
    impersonated_user_id = session.get("impersonated_user_id")
    if impersonated_user_id:
        # We're impersonating - fetch the impersonated user's row
        row = _fetch_user_row(str(impersonated_user_id), None)
    else:
        # Normal operation - fetch the session user's row
        row = _fetch_user_row(_session_user_id(), _session_email())

    g._user_row = row  # type: ignore[attr-defined]
    return row

def _lower_list(values) -> Tuple[str, ...]:
    return tuple((v or "").strip().lower() for v in values)

def _is_safe_next(url: Optional[str]) -> bool:
    """
    Basic open-redirect protection: only allow same-host or relative URLs.
    """
    if not url:
        return False
    try:
        base = urlparse(request.host_url)
        target = urlparse(url)
        if not target.netloc:
            return True  # relative path
        return (target.scheme, target.netloc) == (base.scheme, base.netloc)
    except Exception:
        return False

# ---------------------------------------------------------------------
# Public helpers consumed by blueprints/templates
# ---------------------------------------------------------------------

def is_logged_in() -> bool:
    return any(session.get(k) for k in _auth_keys())

def current_user_id() -> Optional[int]:
    row = _user_row_cached()
    try:
        return int(row["id"]) if row and row.get("id") is not None else None
    except Exception:
        return None

def current_account_id() -> Optional[int]:
    row = _user_row_cached()
    try:
        return int(row["account_id"]) if row and row.get("account_id") is not None else None
    except Exception:
        return None

def current_user_email() -> Optional[str]:
    row = _user_row_cached()
    return _normalize_email(row.get("email")) if row else None

def current_user_role(default: str = "user") -> str:
    row = _user_row_cached()
    return str(row.get("role") or default) if row else default

def email_is_verified() -> bool:
    row = _user_row_cached()
    try:
        return bool(row and (row.get("email_verified") in (True, 1, "1")))
    except Exception:
        return False

def is_paid_account() -> bool:
    """
    Determine if the current account is paid by checking either a 'plan' field
    against PAID_PLANS or a 'stripe_status' against PAID_STRIPE_STATES.
    All names are configurable in app config.

    Admins (users with is_admin = True) bypass this check and are treated as paid.
    When an admin is impersonating, they also bypass paid checks for support/debugging.
    """
    # Check if current user is an admin (bypass plan check)
    try:
        from flask import g
        user = getattr(g, 'user', None)
        if user and getattr(user, 'is_admin', False):
            # Admins have access to all paid features
            return True
        # Check if an admin is impersonating this user (bypass for support)
        if session.get("impersonator_user_id") and session.get("impersonated_user_id"):
            # Admin impersonating - bypass paid check to allow full access for support
            return True
    except Exception:
        pass  # Continue with normal plan check

    aid = current_account_id()
    if not aid:
        return False

    table = current_app.config.get("ACCOUNT_TABLE_NAME", "accounts")
    plan_field = current_app.config.get("ACCOUNT_PLAN_FIELD", "plan")
    stripe_field = current_app.config.get("ACCOUNT_STRIPE_FIELD", "stripe_status")

    paid_plans = _lower_list(current_app.config.get("PAID_PLANS", ()))
    paid_states = _lower_list(current_app.config.get("PAID_STRIPE_STATES", ()))

    try:
        with db.engine.connect() as conn:
            row = (
                conn.execute(
                    text(
                        f"SELECT {plan_field} AS plan, {stripe_field} AS stripe_status "
                        f"FROM {table} WHERE id=:id LIMIT 1"
                    ),
                    {"id": aid},
                )
                .mappings()
                .first()
            )
            if not row:
                return False

            plan = (row.get("plan") or "").strip().lower()
            status = (row.get("stripe_status") or "").strip().lower()
            return (plan in paid_plans) or (status in paid_states)
    except Exception:
        # If schema differs or table missing, treat as not paid (safe default)
        return False

_PLAN_TIER_MAP = {
    'free': 0,
    'growth': 1,
    'pro': 2,
    'managed': 3,
}

def current_plan_name() -> str:
    """Return the account's current plan name: 'free', 'growth', 'pro', or 'managed'."""
    aid = current_account_id()
    if not aid:
        return 'free'
    table = current_app.config.get("ACCOUNT_TABLE_NAME", "accounts")
    plan_field = current_app.config.get("ACCOUNT_PLAN_FIELD", "plan")
    stripe_field = current_app.config.get("ACCOUNT_STRIPE_FIELD", "stripe_status")
    try:
        with db.engine.connect() as conn:
            row = conn.execute(
                text(f"SELECT {plan_field} AS plan, {stripe_field} AS stripe_status "
                     f"FROM {table} WHERE id=:id LIMIT 1"),
                {"id": aid},
            ).mappings().first()
            if not row:
                return 'free'
            plan = (row.get("plan") or "").strip().lower()
            stripe_status = (row.get("stripe_status") or "").strip().lower()
            if plan in _PLAN_TIER_MAP:
                return plan
            # Fall back: any active Stripe subscription without a named plan = growth
            if stripe_status in ('active', 'trialing'):
                return 'growth'
            return 'free'
    except Exception:
        return 'free'


def current_plan_tier() -> int:
    """Return the account's plan tier as an integer: 0=free, 1=growth, 2=pro, 3=managed."""
    return _PLAN_TIER_MAP.get(current_plan_name(), 0)


def plan_required(min_plan: str):
    """
    Decorator that requires the account to be on at least `min_plan`.

    For JSON/API endpoints (request path ends with .json or Content-Type is JSON
    or it's a POST to an action URL): returns HTTP 402 JSON.
    For page requests: redirects to /pricing with a flash message.

    Usage:
        @rsa_bp.post("/auto-promote")
        @login_required
        @plan_required('growth')
        def auto_promote():
            ...
    """
    min_tier = _PLAN_TIER_MAP.get(min_plan, 1)

    def decorator(view_func):
        @wraps(view_func)
        def wrapper(*args, **kwargs):
            if current_plan_tier() < min_tier:
                plan_label = min_plan.capitalize()
                msg = f"{plan_label} plan required to use this feature."
                # API / AJAX requests get a 402 JSON response
                is_api = (
                    request.is_json
                    or request.path.endswith('.json')
                    or request.headers.get('X-Requested-With') == 'XMLHttpRequest'
                    or request.method == 'POST'
                )
                if is_api:
                    from flask import jsonify
                    return jsonify({
                        "ok": False,
                        "upgrade_required": True,
                        "min_plan": min_plan,
                        "message": msg,
                    }), 402
                flash(msg, "info")
                return redirect(url_for("main_bp.pricing"))
            return view_func(*args, **kwargs)
        return wrapper
    return decorator


# Convenience decorators
growth_required = plan_required('growth')
pro_required = plan_required('pro')
managed_required = plan_required('managed')

# ---------------------------------------------------------------------
# Session helpers (used by your login/Google One Tap routes)
# ---------------------------------------------------------------------

def start_user_session(user_row: Mapping) -> None:
    """
    Standardize how we set the session after a successful login or Google One Tap.
    Expects a user row with id, account_id, email, email_verified, role.
    """
    session.permanent = True
    session["user_id"] = int(user_row["id"])
    session["account_id"] = int(user_row.get("account_id") or 0)
    session["email"] = _normalize_email(user_row.get("email"))
    session["role"] = str(user_row.get("role") or "user")
    # mirror a boolean for easy checks in templates if needed
    session["email_verified"] = bool(user_row.get("email_verified") in (True, 1, "1"))
    # clear cached g user
    if hasattr(g, "_user_row"):
        delattr(g, "_user_row")

def clear_user_session() -> None:
    for k in ("user_id", "account_id", "email", "role", "email_verified"):
        session.pop(k, None)
    if hasattr(g, "_user_row"):
        delattr(g, "_user_row")

def login_next_url(default_endpoint: str = "main_bp.home") -> str:
    """Safe post-login redirect target honoring ?next=."""
    nxt = request.args.get("next") or request.form.get("next")
    if _is_safe_next(nxt):
        return nxt
    try:
        return url_for(default_endpoint)
    except Exception:
        return "/"

# ---------------------------------------------------------------------
# Decorators
# ---------------------------------------------------------------------

def login_required(view_func):
    """
    Redirect to login if the session doesn't look authenticated.
    Optionally enforce verified email globally via REQUIRE_VERIFIED_EMAIL_FOR_LOGIN.
    Preserves ?next= so we can send them back after login.
    """
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if not is_logged_in():
            flash("Please log in to continue.", "warning")
            return redirect(url_for("auth_bp.login", next=request.url))

        # Optional global gate
        if current_app.config.get("REQUIRE_VERIFIED_EMAIL_FOR_LOGIN", False) and not email_is_verified():
            flash("Please verify your email address to continue.", "warning")
            return redirect(url_for("auth_bp.verify_notice"))
        return view_func(*args, **kwargs)
    return wrapper


def ajax_login_required(view_func):
    """
    Like login_required but returns JSON for AJAX requests instead of redirecting.
    Use this for API/AJAX endpoints that need to handle session timeout gracefully.
    Returns: {"ok": false, "error": "session_expired", "login_url": "..."} with status 401
    """
    from flask import jsonify

    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if not is_logged_in():
            login_url = url_for("auth_bp.login", next=request.url)
            return jsonify({
                "ok": False,
                "error": "session_expired",
                "message": "Your session has expired. Please log in again.",
                "login_url": login_url
            }), 401

        # Optional global gate
        if current_app.config.get("REQUIRE_VERIFIED_EMAIL_FOR_LOGIN", False) and not email_is_verified():
            return jsonify({
                "ok": False,
                "error": "email_not_verified",
                "message": "Please verify your email address to continue."
            }), 403
        return view_func(*args, **kwargs)
    return wrapper

def verified_email_required(view_func):
    """
    Per-route email verification gate (use when global gate is off or for extra safety).
    """
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if not is_logged_in():
            flash("Please log in to continue.", "warning")
            return redirect(url_for("auth_bp.login", next=request.url))
        if not email_is_verified():
            flash("Please verify your email address to access that feature.", "warning")
            return redirect(url_for("auth_bp.verify_notice"))
        return view_func(*args, **kwargs)
    return wrapper

_PLAN_TIER_MAP = {
    'free': 0,
    'growth': 1,
    'pro': 2,
    'managed': 3,
}

def current_plan_name() -> str:
    """Return the account's current plan name: 'free', 'growth', 'pro', or 'managed'."""
    aid = current_account_id()
    if not aid:
        return 'free'
    table = current_app.config.get("ACCOUNT_TABLE_NAME", "accounts")
    plan_field = current_app.config.get("ACCOUNT_PLAN_FIELD", "plan")
    stripe_field = current_app.config.get("ACCOUNT_STRIPE_FIELD", "stripe_status")
    try:
        with db.engine.connect() as conn:
            row = conn.execute(
                text(f"SELECT {plan_field} AS plan, {stripe_field} AS stripe_status "
                     f"FROM {table} WHERE id=:id LIMIT 1"),
                {"id": aid},
            ).mappings().first()
            if not row:
                return 'free'
            plan = (row.get("plan") or "").strip().lower()
            stripe_status = (row.get("stripe_status") or "").strip().lower()
            if plan in _PLAN_TIER_MAP:
                return plan
            # Fall back: any active Stripe subscription without a named plan = growth
            if stripe_status in ('active', 'trialing'):
                return 'growth'
            return 'free'
    except Exception:
        return 'free'


def current_plan_tier() -> int:
    """Return the account's plan tier as an integer: 0=free, 1=growth, 2=pro, 3=managed."""
    return _PLAN_TIER_MAP.get(current_plan_name(), 0)


def plan_required(min_plan: str):
    """
    Decorator that requires the account to be on at least `min_plan`.

    For JSON/API endpoints (request path ends with .json or Content-Type is JSON
    or it's a POST to an action URL): returns HTTP 402 JSON.
    For page requests: redirects to /pricing with a flash message.

    Usage:
        @rsa_bp.post("/auto-promote")
        @login_required
        @plan_required('growth')
        def auto_promote():
            ...
    """
    min_tier = _PLAN_TIER_MAP.get(min_plan, 1)

    def decorator(view_func):
        @wraps(view_func)
        def wrapper(*args, **kwargs):
            if current_plan_tier() < min_tier:
                plan_label = min_plan.capitalize()
                msg = f"{plan_label} plan required to use this feature."
                # API / AJAX requests get a 402 JSON response
                is_api = (
                    request.is_json
                    or request.path.endswith('.json')
                    or request.headers.get('X-Requested-With') == 'XMLHttpRequest'
                    or request.method == 'POST'
                )
                if is_api:
                    from flask import jsonify
                    return jsonify({
                        "ok": False,
                        "upgrade_required": True,
                        "min_plan": min_plan,
                        "message": msg,
                    }), 402
                flash(msg, "info")
                return redirect(url_for("main_bp.pricing"))
            return view_func(*args, **kwargs)
        return wrapper
    return decorator


# Convenience decorators
growth_required = plan_required('growth')
pro_required = plan_required('pro')
managed_required = plan_required('managed')


def paid_required(view_func):
    """
    Optional decorator if you want to guard routes for paid users only.
    """
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if not is_logged_in():
            flash("Please log in to continue.", "warning")
            return redirect(url_for("auth_bp.login", next=request.url))
        if not is_paid_account():
            flash("A paid plan is required to access that feature.", "info")
            try:
                ep = current_app.config.get("PRICING_ENDPOINT", "main_bp.pricing")
                return redirect(url_for(ep))
            except Exception:
                return redirect(url_for("main_bp.home"))
        return view_func(*args, **kwargs)
    return wrapper

# ---------------------------------------------------------------------
# Optional: lightweight One Tap email sanity check
# ---------------------------------------------------------------------

def looks_like_email(value: str) -> bool:
    """Utility for routes that accept an identifier but expect an email now."""
    return bool(_EMAIL_RE.match((value or "").strip()))
