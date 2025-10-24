from functools import wraps
from flask import g, abort

def require_admin_cloaked(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = getattr(g, "user", None)
        if not user or not getattr(user, "is_admin", False):
            return abort(404)
        return view(*args, **kwargs)
    return wrapped