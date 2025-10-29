# app/auth/plan_helpers.py
"""
Helper functions for plan-based access control with admin bypass.
"""
from typing import Optional
from flask import g


def is_admin_user(user=None) -> bool:
    """
    Check if the given user (or current user from g) is an admin.

    Admins have the `is_admin` property set to True, which checks if their role
    is "owner" or "admin".

    Args:
        user: User object to check. If None, checks g.user.

    Returns:
        True if user is an admin, False otherwise
    """
    if user is None:
        user = getattr(g, 'user', None)

    if not user:
        return False

    return getattr(user, 'is_admin', False)


def has_plan_access(required_plan: str, account=None, user=None) -> bool:
    """
    Check if account has access to a specific plan tier.
    Admins always have access regardless of plan.

    Plan hierarchy (from lowest to highest):
    - free
    - starter
    - growth
    - professional
    - enterprise

    Args:
        required_plan: Minimum plan required (e.g., "professional")
        account: Account object to check. If None, uses g.user.account.
        user: User object for admin check. If None, uses g.user.

    Returns:
        True if account has access (or user is admin), False otherwise
    """
    # Admins bypass all plan restrictions
    if is_admin_user(user):
        return True

    if account is None:
        current_user = user or getattr(g, 'user', None)
        if current_user:
            account = getattr(current_user, 'account', None)

    if not account:
        return False

    PLAN_HIERARCHY = {
        "free": 0,
        "starter": 1,
        "growth": 2,
        "professional": 3,
        "enterprise": 4,
    }

    account_plan = (account.plan or "free").lower()
    required_plan_level = PLAN_HIERARCHY.get(required_plan.lower(), 0)
    account_plan_level = PLAN_HIERARCHY.get(account_plan, 0)

    return account_plan_level >= required_plan_level


def can_access_feature(feature_name: str, account=None, user=None) -> tuple[bool, Optional[str]]:
    """
    Check if account can access a specific feature.
    Admins always have access regardless of plan.

    Feature requirements:
    - "team_collaboration": starter+
    - "advanced_analytics": growth+
    - "api_access": professional+
    - "white_label": enterprise
    - "priority_support": professional+
    - "custom_integrations": enterprise

    Args:
        feature_name: Name of the feature to check
        account: Account object to check. If None, uses g.user.account.
        user: User object for admin check. If None, uses g.user.

    Returns:
        Tuple of (has_access: bool, error_message: Optional[str])
    """
    # Admins bypass all feature restrictions
    if is_admin_user(user):
        return True, None

    FEATURE_REQUIREMENTS = {
        "team_collaboration": "starter",
        "advanced_analytics": "growth",
        "api_access": "professional",
        "white_label": "enterprise",
        "priority_support": "professional",
        "custom_integrations": "enterprise",
        "bulk_operations": "growth",
        "custom_reporting": "professional",
    }

    required_plan = FEATURE_REQUIREMENTS.get(feature_name)
    if not required_plan:
        # Feature not found in requirements, allow access by default
        return True, None

    if has_plan_access(required_plan, account, user):
        return True, None

    return False, f"This feature requires the {required_plan.title()} plan or higher. Upgrade your plan to access it."


def require_plan_or_admin(required_plan: str):
    """
    Decorator to require a specific plan level (admins bypass).

    Usage:
        @require_plan_or_admin("professional")
        def api_endpoint():
            ...

    Args:
        required_plan: Minimum plan required
    """
    from functools import wraps
    from flask import flash, redirect, url_for, abort

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            user = getattr(g, 'user', None)

            # Admins bypass
            if is_admin_user(user):
                return f(*args, **kwargs)

            if not user:
                flash("Please log in to access this page.", "error")
                return redirect(url_for("auth_bp.login"))

            account = getattr(user, 'account', None)
            if not account:
                flash("Account not found.", "error")
                return redirect(url_for("account_bp.dashboard"))

            if not has_plan_access(required_plan, account, user):
                flash(f"This feature requires the {required_plan.title()} plan or higher.", "error")
                return redirect(url_for("billing_bp.plans"))

            return f(*args, **kwargs)
        return decorated_function
    return decorator


def require_feature_or_admin(feature_name: str):
    """
    Decorator to require access to a specific feature (admins bypass).

    Usage:
        @require_feature_or_admin("api_access")
        def api_endpoint():
            ...

    Args:
        feature_name: Name of the feature required
    """
    from functools import wraps
    from flask import flash, redirect, url_for

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            user = getattr(g, 'user', None)

            # Admins bypass
            if is_admin_user(user):
                return f(*args, **kwargs)

            if not user:
                flash("Please log in to access this page.", "error")
                return redirect(url_for("auth_bp.login"))

            account = getattr(user, 'account', None)
            has_access, error_message = can_access_feature(feature_name, account, user)

            if not has_access:
                flash(error_message, "error")
                return redirect(url_for("billing_bp.plans"))

            return f(*args, **kwargs)
        return decorated_function
    return decorator
