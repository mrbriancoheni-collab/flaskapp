# app/auth/session.py
from __future__ import annotations

from functools import wraps
from urllib.parse import urlparse, urljoin
from typing import Callable, Optional

from flask import g, session, redirect, url_for, request, jsonify
from app.models import User
from app.extensions import db  # if you need it elsewhere; safe to keep


# ---------------------- Core helpers ----------------------

def _is_safe_next_url(target: str) -> bool:
    """Prevent open redirects by ensuring 'next' stays on our host."""
    if not target:
        return False
    host_url = urlparse(request.host_url)
    redirect_url = urlparse(urljoin(request.host_url, target))
    return (redirect_url.scheme in ("http", "https")
            and host_url.netloc == redirect_url.netloc)

def _next_param() -> str:
    nxt = request.args.get("next") or request.referrer or ""
    return nxt if _is_safe_next_url(nxt) else ""

def load_current_user() -> None:
    """Populate g.user from session['user_id']."""
    uid = session.get("user_id")
    g.user = User.query.get(uid) if uid else None  # type: ignore[assignment]


# ---------------------- Public API ------------------------

def login_required(view: Callable) -> Callable:
    """Require a logged-in session. API requests get JSON 401; browser gets redirect."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            # If JSON/AJAX, return JSON 401; else redirect to login with safe next
            wants_json = (request.accept_mimetypes.best == "application/json") or request.is_json
            if wants_json:
                return jsonify({"ok": False, "error": "auth_required"}), 401
            return redirect(url_for("auth.login", next=_next_param()))
        return view(*args, **kwargs)
    return wrapped


def require_admin(view: Callable) -> Callable:
    """Minimal RBAC gate for admin-only views."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = getattr(g, "user", None)
        if not user or not getattr(user, "is_admin", False):
            # Same JSON/browser behavior as login_required
            wants_json = (request.accept_mimetypes.best == "application/json") or request.is_json
            if wants_json:
                return jsonify({"ok": False, "error": "forbidden"}), 403
            # Send non-admins to home (or your 403 page)
            return redirect(url_for("account_bp.dashboard"))
        return view(*args, **kwargs)
    return wrapped


def is_impersonating() -> bool:
    return bool(session.get("impersonated_user_id") and session.get("impersonator_user_id"))


def real_user_id() -> Optional[int]:
    """If impersonating, return the real admin's user_id; else None."""
    return session.get("impersonator_user_id")


def stop_impersonation() -> None:
    """Clear impersonation keys (used by a route or on logout)."""
    session.pop("impersonated_user_id", None)
    session.pop("impersonator_user_id", None)
    session.modified = True


# ---------------------- Request lifecycle ----------------------

def before_request_hook() -> None:
    """
    1) Load the real logged-in user (g.user from session.user_id).
    2) If impersonation keys exist and the real user is an admin,
       swap g.user to the impersonated user and expose g.real_admin_user_id.
       Otherwise, clear any forged keys.
    """
    # Step 1: establish the real session user
    load_current_user()

    imp_uid = session.get("impersonated_user_id")
    imp_admin = session.get("impersonator_user_id")

    # Default: not impersonating
    if hasattr(g, "real_admin_user_id"):
        delattr(g, "real_admin_user_id")

    if not (imp_uid and imp_admin):
        return  # nothing to do

    # Verify real session user is present and matches the stored admin id
    real_user = getattr(g, "user", None)
    if not real_user or real_user.id != imp_admin or not getattr(real_user, "is_admin", False):
        # Harden: if keys are present but the real user isn't the recorded admin (or not admin anymore),
        # clear the stale/forged impersonation.
        stop_impersonation()
        return

    # Load the target user and swap
    target = User.query.get(imp_uid)
    if target is None:
        # Target disappeared; clear and continue as admin
        stop_impersonation()
        return

    # Expose the real admin id and impersonate transparently
    g.real_admin_user_id = real_user.id  # who is doing the impersonation
    g.user = target


# ---------------------- (Optional) logout hook ----------------------

def on_logout_cleanup() -> None:
    """If your logout flow calls this, it guarantees impersonation is cleared."""
    stop_impersonation()
    session.pop("user_id", None)
    session.modified = True
