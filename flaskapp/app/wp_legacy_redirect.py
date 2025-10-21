from flask import Blueprint, redirect, request

wp_legacy = Blueprint("wp_legacy", __name__, url_prefix="/wp")

@wp_legacy.route("/", defaults={"subpath": ""})
@wp_legacy.route("/<path:subpath>")
def _redir(subpath):
    # carry query string through
    qs = ("?" + request.query_string.decode()) if request.query_string else ""
    return redirect(f"/account/wp/{subpath}{qs}", code=301)
