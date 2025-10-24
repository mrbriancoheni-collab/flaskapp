# app/ai.py
from __future__ import annotations

import os
from functools import wraps
from typing import Callable, Optional

from flask import current_app, flash, redirect, url_for, request

# NOTE: remove the dangling "as" and import the symbols directly
from app.auth.utils import is_paid_account, paid_required  # noqa: F401  (paid_required used by other modules)


def get_openai_key() -> Optional[str]:
    """
    Central place to read the OpenAI API key.
    Checks environment first, then Flask config.
    """
    key = os.getenv("OPENAI_API_KEY")
    if key:
        return key
    try:
        cfg = getattr(current_app, "config", {}) or {}
        return cfg.get("OPENAI_API_KEY")
    except Exception:
        return None


def ai_available() -> bool:
    """True if we have an API key configured."""
    return bool(get_openai_key())


def ai_required(view: Callable):
    """
    Decorator to guard AI-powered endpoints.
    - Requires a paid account
    - Requires OPENAI_API_KEY to be present
    If either is missing, redirect with a helpful flash.
    """
    @wraps(view)
    def wrapper(*args, **kwargs):
        # 1) paid gate
        if not is_paid_account():
            flash("AI features are available on paid plans. Upgrade to continue.", "warning")
            # send them back to the page they came from, or pricing
            next_url = request.referrer or url_for("public_bp.pricing") if "public_bp.pricing" in current_app.view_functions else url_for("main_bp.home")
            return redirect(next_url)

        # 2) key present
        if not ai_available():
            flash("Add your OpenAI API key in Settings to use AI features.", "warning")
            # try to route to an account settings page if present
            settings_endpoint = "account_bp.settings" if "account_bp.settings" in current_app.view_functions else "main_bp.home"
            return redirect(url_for(settings_endpoint))

        return view(*args, **kwargs)
    return wrapper
