# app/views.py
from datetime import datetime

from flask import (
    Blueprint,
    jsonify,
    render_template,
    redirect,
    request,
    session,
    current_app,
    url_for,
)
from app.ai_clients import chatgpt_response, claude_response
from app.forms import ChatForm
from app.auth.utils import login_required

# One blueprint for public + app pages.
# We keep explicit endpoint names so URLs stay 'home', 'chatgpt', etc.
main_bp = Blueprint("main_bp", __name__, template_folder="../templates")

APP_NAME = "FieldSprout"

# ---------------------------------------------------------------------
# Pass through the app-wide helpers so we DON'T shadow them here.
# This exposes the global has_endpoint/ep you defined in app/__init__.py
# and also provides app_name/year to templates rendered via this blueprint.
# ---------------------------------------------------------------------
@main_bp.app_context_processor
def expose_global_helpers():
    g = current_app.jinja_env.globals or {}
    helpers = {}
    if "has_endpoint" in g:
        helpers["has_endpoint"] = g["has_endpoint"]
    if "ep" in g:
        helpers["ep"] = g["ep"]
    return {
        "app_name": current_app.config.get("APP_NAME", APP_NAME),
        "year": datetime.now().year,
        **helpers,
    }

# ----------------------
# PUBLIC PAGES (no login)
# ----------------------
@main_bp.route("/index.php", endpoint="index_php_redirect")
def index_php_redirect():
    """Redirect bots/crawlers looking for a PHP entry point."""
    return redirect("/", 301)


@main_bp.route("/", methods=["GET"], endpoint="home")
def home():
    try:
        return render_template("home.html")
    except Exception:
        return (
            "<!doctype html><html><head><title>FieldSprout</title></head>"
            "<body><h1>FieldSprout</h1><p>Server is running.</p>"
            "<p><a href='/_deploy_check'>/_deploy_check</a></p></body></html>"
        ), 200


@main_bp.route("/test", methods=["GET"], endpoint="test")
def test_page():
    """Minimal route — returns raw HTML with zero dependencies to confirm Flask routing works."""
    from datetime import datetime as _dt
    return (
        "<!doctype html><html><head><title>Flask Test</title></head><body>"
        "<h1>Flask routing works</h1>"
        f"<p>Time: {_dt.utcnow().isoformat()}Z</p>"
        "<p><a href='/_deploy_check'>/_deploy_check</a> | "
        "<a href='/deploy_check'>/deploy_check</a> | "
        "<a href='/'>home</a></p>"
        "</body></html>"
    ), 200


@main_bp.route("/blog/", defaults={"subpath": ""}, endpoint="blog_index")
@main_bp.route("/blog/<path:subpath>", endpoint="blog")
def blog(subpath):
    """
    WordPress was removed.  If WP_BASE is configured, proxy-redirect there;
    otherwise return 404 so search engines drop stale blog URLs cleanly.
    """
    wp_base = current_app.config.get("WP_BASE", "").rstrip("/")
    if wp_base:
        target = f"{wp_base}/blog/{subpath}"
        qs = ("?" + request.query_string.decode()) if request.query_string else ""
        return redirect(target + qs, 301)
    from flask import abort
    abort(404)


@main_bp.route("/about", methods=["GET"], endpoint="about")
def about():
    return render_template("about.html")


@main_bp.route("/pricing", methods=["GET"], endpoint="pricing")
def pricing():
    # Template handles showing Stripe buttons or Register fallback.
    return render_template("pricing.html")


# -------------------------
# APP PAGES (require login)
# -------------------------
@main_bp.route("/chatgpt", methods=["GET", "POST"], endpoint="chatgpt")
@login_required
def chatgpt():
    form = ChatForm()
    response = None
    if request.method == "POST" and form.validate_on_submit():
        prompt = form.prompt.data
        profile = session.get("business_profile", {})  # optional profile context
        response = chatgpt_response(prompt, profile=profile)
    return render_template("chatgpt.html", form=form, response=response)


@main_bp.route("/claude", methods=["GET", "POST"], endpoint="claude")
@login_required
def claude():
    form = ChatForm()
    response = None
    if request.method == "POST" and form.validate_on_submit():
        prompt = form.prompt.data
        profile = session.get("business_profile", {})
        response = claude_response(prompt, profile=profile)
    return render_template("claude.html", form=form, response=response)


# -------------
# Health / Debug
# -------------
@main_bp.route("/ping", methods=["GET"], endpoint="ping")
def ping():
    return "pong", 200


@main_bp.route("/_deploy_check", methods=["GET"], endpoint="_deploy_check")
@main_bp.route("/deploy_check", methods=["GET"], endpoint="deploy_check")
def deploy_check():
    """Diagnostic health-check endpoint — returns JSON 200."""
    return jsonify({
        "status": "ok",
        "server": "flask",
        "timestamp": datetime.utcnow().isoformat() + "Z",
    })


@main_bp.route("/__routes__", methods=["GET"], endpoint="__routes__")
def __routes__():
    """Quickly inspect registered routes and whether url_for() resolves."""
    lines = []
    for rule in sorted(current_app.url_map.iter_rules(), key=lambda r: r.rule):
        methods = ",".join(sorted(m for m in rule.methods if m not in ("HEAD", "OPTIONS")))
        try:
            url_for(rule.endpoint, **{arg: f"<{arg}>" for arg in rule.arguments})
            ok = True
        except Exception:
            ok = False
        lines.append(f"{rule.rule} → {rule.endpoint} [{methods}] {'OK' if ok else '(broken)'}")
    return "<pre>" + "\n".join(lines) + "</pre>"
