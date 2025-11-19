from functools import wraps
from flask import g, abort, redirect, url_for, request, jsonify

def require_admin_cloaked(view):
    """
    Require admin access. If not logged in, redirect to login with next parameter.
    If logged in but not admin, return 404 to "cloak" the admin area from non-admins.
    """
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = getattr(g, "user", None)

        # Not logged in at all - redirect to login with next parameter
        if not user:
            wants_json = (request.accept_mimetypes.best == "application/json") or request.is_json
            if wants_json:
                return jsonify({"ok": False, "error": "auth_required"}), 401
            # Redirect to login, passing the current URL so we can return here after login
            return redirect(url_for("auth_bp.login", next=request.url))

        # Logged in but not admin - return 404 to "cloak" the admin area
        if not getattr(user, "is_admin", False):
            return abort(404)

        return view(*args, **kwargs)
    return wrapped