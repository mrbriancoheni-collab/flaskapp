from __future__ import annotations

from flask import current_app, abort

def require_gmb_connection() -> None:
    if not current_app.config.get("GMB_CONNECTED", False):
        abort(401)  # or redirect to /gmb/start if you prefer

def require_gmb_connection_optional() -> None:
    # No-op helper to document intent; sometimes you want a soft check.
    return
