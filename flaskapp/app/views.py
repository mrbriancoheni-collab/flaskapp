# app/views.py
from datetime import datetime

from flask import (
    Blueprint,
    render_template,
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
@main_bp.route("/", methods=["GET"], endpoint="home")
def home():
    return render_template("home.html")


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
