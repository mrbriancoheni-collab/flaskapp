# app/auth/permissions.py
"""
Role-based permission decorators for team access control.

Usage:
    @require_permission("invite_users")
    def invite_team_member():
        ...

    @require_role("admin")
    def admin_settings():
        ...
"""

from functools import wraps
from flask import flash, redirect, url_for, abort, g, current_app
from typing import Callable, Optional, List, Union


def require_role(*allowed_roles: str):
    """
    Decorator to require specific user role(s).

    Args:
        allowed_roles: One or more role names (e.g., "owner", "admin", "member")

    Usage:
        @require_role("owner")
        def delete_account():
            ...

        @require_role("owner", "admin")
        def manage_team():
            ...
    """
    def decorator(f: Callable) -> Callable:
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not hasattr(g, 'user') or not g.user:
                flash("Please log in to access this page.", "error")
                return redirect(url_for("auth_bp.login"))

            if g.user.role not in allowed_roles:
                current_app.logger.warning(
                    f"User {g.user.id} (role={g.user.role}) attempted to access {f.__name__} "
                    f"which requires roles: {allowed_roles}"
                )
                abort(403)  # Forbidden

            return f(*args, **kwargs)
        return decorated_function
    return decorator


def require_permission(*permissions: str):
    """
    Decorator to require specific permission(s).

    Args:
        permissions: One or more permission names (e.g., "invite_users", "manage_billing")

    Usage:
        @require_permission("invite_users")
        def send_invite():
            ...

        @require_permission("manage_billing", "view_analytics")
        def billing_dashboard():
            ...
    """
    def decorator(f: Callable) -> Callable:
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not hasattr(g, 'user') or not g.user:
                flash("Please log in to access this page.", "error")
                return redirect(url_for("auth_bp.login"))

            from app.models_team import has_permission

            # Check if user has ANY of the required permissions (OR logic)
            has_any_permission = any(
                has_permission(g.user, perm) for perm in permissions
            )

            if not has_any_permission:
                current_app.logger.warning(
                    f"User {g.user.id} (role={g.user.role}) lacks permission for {f.__name__} "
                    f"(requires one of: {permissions})"
                )
                flash("You don't have permission to perform this action.", "error")
                abort(403)

            return f(*args, **kwargs)
        return decorated_function
    return decorator


def require_owner():
    """
    Decorator shorthand for require_role("owner").

    Usage:
        @require_owner()
        def delete_account():
            ...
    """
    return require_role("owner")


def require_admin():
    """
    Decorator to require admin or owner role.

    Usage:
        @require_admin()
        def manage_team():
            ...
    """
    return require_role("owner", "admin")


def check_seat_limit(f: Callable) -> Callable:
    """
    Decorator to check if account has available seats before adding team members.

    Usage:
        @check_seat_limit
        def invite_user():
            ...
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not hasattr(g, 'user') or not g.user:
            flash("Please log in to access this page.", "error")
            return redirect(url_for("auth_bp.login"))

        from app.models import Account
        from app.models_team import can_add_team_member

        account = Account.query.get(g.user.account_id)
        if not account:
            current_app.logger.error(f"Account {g.user.account_id} not found for user {g.user.id}")
            flash("Account not found.", "error")
            return redirect(url_for("account_bp.dashboard"))

        can_add, error_message = can_add_team_member(account)

        if not can_add:
            flash(error_message, "error")
            return redirect(url_for("team_bp.members"))

        return f(*args, **kwargs)
    return decorated_function


def get_user_permissions(user) -> List[str]:
    """
    Get list of all permissions for a user.

    Args:
        user: User model instance

    Returns:
        List of permission names the user has
    """
    if not user:
        return []

    from app.models_team import has_permission

    # All possible permissions
    ALL_PERMISSIONS = [
        "invite_users",
        "remove_members",
        "manage_billing",
        "manage_integrations",
        "view_analytics",
        "manage_content",
        "manage_settings",
        "delete_account",
    ]

    return [perm for perm in ALL_PERMISSIONS if has_permission(user, perm)]


def can_manage_user(actor, target_user) -> tuple[bool, Optional[str]]:
    """
    Check if actor can manage (edit/remove) target user.

    Rules:
    - Owner can manage anyone
    - Admin can manage members but not other admins or owner
    - Members cannot manage anyone

    Args:
        actor: User performing the action
        target_user: User being managed

    Returns:
        Tuple of (can_manage: bool, reason: Optional[str])
    """
    if not actor or not target_user:
        return False, "Invalid users"

    if actor.account_id != target_user.account_id:
        return False, "Users are not in the same account"

    if actor.id == target_user.id:
        # Users can always manage themselves (e.g., leave team)
        return True, None

    if actor.role == "owner":
        # Owners can manage anyone
        return True, None

    if actor.role == "admin":
        # Admins can only manage members
        if target_user.role == "member":
            return True, None
        else:
            return False, "Admins cannot manage other admins or the owner"

    # Members cannot manage anyone (except themselves)
    return False, "Members cannot manage other team members"
