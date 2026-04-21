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


@main_bp.route("/robots.txt", methods=["GET"], endpoint="robots_txt")
def robots_txt():
    from flask import Response
    body = (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /account/\n"
        "Disallow: /admin/\n"
        "Disallow: /api/\n"
        "Disallow: /_deploy_check\n"
        "Disallow: /test\n\n"
        "Sitemap: https://fieldsprout.io/sitemap.xml\n"
    )
    return Response(body, mimetype="text/plain")


@main_bp.route("/sitemap.xml", methods=["GET"], endpoint="sitemap_xml")
def sitemap_xml():
    from flask import Response
    from datetime import date
    today = date.today().isoformat()
    pages = [
        ("https://fieldsprout.io/", "1.0", "weekly"),
        ("https://fieldsprout.io/pricing", "0.9", "monthly"),
        ("https://fieldsprout.io/about", "0.7", "monthly"),
        ("https://fieldsprout.io/contact", "0.7", "monthly"),
        ("https://fieldsprout.io/free-tools", "0.9", "weekly"),
        ("https://fieldsprout.io/vs-agency", "0.8", "monthly"),
        ("https://fieldsprout.io/industries/hvac", "0.9", "monthly"),
        ("https://fieldsprout.io/industries/plumbing", "0.9", "monthly"),
        ("https://fieldsprout.io/industries/electricians", "0.9", "monthly"),
        ("https://fieldsprout.io/industries/roofing", "0.9", "monthly"),
        ("https://fieldsprout.io/industries/pest-control", "0.9", "monthly"),
        ("https://fieldsprout.io/industries/landscaping", "0.9", "monthly"),
        ("https://fieldsprout.io/industries/garage-door", "0.8", "monthly"),
        ("https://fieldsprout.io/industries/pool-service", "0.8", "monthly"),
        ("https://fieldsprout.io/industries/solar", "0.8", "monthly"),
        ("https://fieldsprout.io/products/ads", "0.8", "monthly"),
        ("https://fieldsprout.io/products/glsa", "0.8", "monthly"),
        ("https://fieldsprout.io/products/gbp", "0.8", "monthly"),
        ("https://fieldsprout.io/products/facebook-ads", "0.8", "monthly"),
        ("https://fieldsprout.io/products/reviews", "0.8", "monthly"),
        ("https://fieldsprout.io/products/listings", "0.8", "monthly"),
        ("https://fieldsprout.io/products/forms-chat", "0.7", "monthly"),
        ("https://fieldsprout.io/solutions/lead-generation", "0.8", "monthly"),
        ("https://fieldsprout.io/solutions/multi-location", "0.8", "monthly"),
        ("https://fieldsprout.io/solutions/lower-ad-cost", "0.8", "monthly"),
        ("https://fieldsprout.io/solutions/get-more-reviews", "0.7", "monthly"),
        ("https://fieldsprout.io/solutions/spend-when-open", "0.7", "monthly"),
        ("https://fieldsprout.io/solutions/see-what-works", "0.7", "monthly"),
        ("https://fieldsprout.io/ads-grader", "0.9", "weekly"),
        ("https://fieldsprout.io/privacy-policy", "0.3", "yearly"),
        ("https://fieldsprout.io/terms-of-service", "0.3", "yearly"),
        ("https://fieldsprout.io/security", "0.4", "yearly"),
    ]
    urls = "\n".join(
        f"  <url>\n"
        f"    <loc>{loc}</loc>\n"
        f"    <lastmod>{today}</lastmod>\n"
        f"    <changefreq>{freq}</changefreq>\n"
        f"    <priority>{pri}</priority>\n"
        f"  </url>"
        for loc, pri, freq in pages
    )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{urls}\n"
        "</urlset>"
    )
    return Response(xml, mimetype="application/xml")


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


