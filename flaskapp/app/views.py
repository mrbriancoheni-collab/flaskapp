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


@main_bp.route("/robots.txt")
def robots_txt():
    content = """User-agent: *
Allow: /
Disallow: /account/
Disallow: /admin/
Disallow: /api/
Disallow: /billing/
Disallow: /ads-grader/connect/
Disallow: /fb_ads_grader/
Disallow: /_deploy_check
Disallow: /test
Disallow: /wsgi-check
# Auth & utility endpoints — no SEO value. Login/register carry a noindex
# meta instead of a Disallow so Google can crawl them and drop them from the
# index (a Disallow can't remove an already-indexed page).
Disallow: /auth/
Disallow: /connect/
Disallow: /pv/
Disallow: /*?next=

# Allow major AI crawlers to index public content
User-agent: GPTBot
Allow: /

User-agent: ChatGPT-User
Allow: /

User-agent: anthropic-ai
Allow: /

User-agent: Claude-Web
Allow: /

User-agent: PerplexityBot
Allow: /

User-agent: Applebot-Extended
Allow: /

User-agent: CCBot
Allow: /

User-agent: Googlebot
Allow: /

Sitemap: https://fieldsprout.io/sitemap.xml
"""
    from flask import Response
    return Response(content, mimetype="text/plain")


@main_bp.route("/llms.txt")
def llms_txt():
    content = """# FieldSprout

> AI-powered Google Ads optimization and marketing automation for home service businesses.

FieldSprout helps HVAC, plumbing, roofing, electrical, pool service, landscaping, pest control, and other home service companies get more leads from Google Ads by automatically optimizing campaigns, ad copy, bids, and conversion tracking.

## Core Product

- [Campaign Health Score](https://fieldsprout.io/): Free AI audit of your Google Ads account — no credit card required
- [Google Ads Automation](https://fieldsprout.io/products/ads): AI agents that adjust bids, dayparting, negative keywords, and ad copy 24/7
- [Offline Conversion Import](https://fieldsprout.io/products/ads): Track phone calls and CRM jobs back to the exact ad click that drove them
- [Competitor Intelligence](https://fieldsprout.io/products/ads): Auction insights showing who's outbidding you and how to respond automatically
- [Ad Copy Performance](https://fieldsprout.io/products/ads): Grade every headline and description — auto-promote winners, flag losers

## AI Agent Architecture

FieldSprout uses a multi-layer autonomous agent system running 24/7:

**Strategic Layer (runs daily at 6am)**
- Strategic Director Agent: Budget reallocation, campaign scaling, pause decisions based on 90-day performance trends

**Operational Layer (runs every 4 hours)**
- Campaign Manager Agent: Detects CPL spikes, conversion drops, and budget pacing anomalies
- Budget Guardian Agent: Emergency spend protection — pauses runaway campaigns before they overspend
- Quality Score Agent: Diagnoses low Quality Scores and implements fixes (ad copy, landing page alignment, keyword relevance)

**Tactical Layer (runs hourly)**
- Keyword Optimizer Agent: Pauses non-converting keywords, adjusts bids to target CPA, adds high-performing search terms as keywords
- Negative Keyword Agent: Blocks irrelevant searches using pattern matching and LLM business-relevance scoring — evaluates 200 search terms per cycle
- Ad Copy Agent: Pauses underperforming ads, identifies variation opportunities
- Landing Page Analyst: Monitors message match between ads and landing pages

**Autonomy Levels**
- L1 (Assistive): Logs all findings, nothing auto-executes — for human review
- L2 (Semi-Auto, default): Auto-executes low-risk actions (bid adjustments, negative keywords, keyword pauses) with confidence >= 80%
- L3 (Fully Autonomous): Also auto-executes high-risk actions (budget changes, campaign pauses) when confidence >= 92%

## Performance Benchmarks

Based on managed accounts:
- Average cost-per-lead reduction: 38% within 60 days
- HVAC accounts: $89 avg CPL (down from $147 at start)
- Plumbing accounts: $94 avg CPL (down from $151 at start)
- Roofing accounts: $118 avg CPL (down from $198 at start)
- Electrical contractor accounts: $97 avg CPL (down from $162 at start)
- Wasted spend identified in new accounts: 32-47% of total budget
- Time to first automated optimization: within 1 hour of connecting Google Ads

## Integrations

- Google Ads (full read/write — bid adjustments, ad management, conversion upload)
- Google Analytics, Search Console, Business Profile
- Skimmer (pool service CRM), ServiceTitan, Housecall Pro
- CallRail (phone tracking webhooks)
- Twilio (call tracking and recording)
- Stripe (billing)
- Facebook Ads (in development)

## Industries Served

HVAC, plumbing, electrical, roofing, pool service, pest control, lawn care, landscaping, garage door, solar, concrete, fencing, irrigation, restoration, windows and doors

Industry pages:
- [HVAC Google Ads](https://fieldsprout.io/industries/hvac) — $89 avg CPL, seasonal demand automation
- [Plumbing Google Ads](https://fieldsprout.io/industries/plumbing) — $94 avg CPL, emergency call capture
- [Roofing Google Ads](https://fieldsprout.io/industries/roofing) — $118 avg CPL, storm response campaigns
- [Electricians Google Ads](https://fieldsprout.io/industries/electricians) — $97 avg CPL, panel upgrade targeting
- [Pest Control Google Ads](https://fieldsprout.io/industries/pest-control) — seasonal pest pattern optimization
- [Lawn Care Google Ads](https://fieldsprout.io/industries/lawn-care) — recurring contract acquisition
- [Pool Service Google Ads](https://fieldsprout.io/industries/pool-service) — route-building leads
- [Solar Google Ads](https://fieldsprout.io/industries/solar) — incentive-aware campaigns
- [Landscaping Google Ads](https://fieldsprout.io/industries/landscaping) — design-build vs. maintenance split
- [Garage Door Google Ads](https://fieldsprout.io/industries/garage-door) — emergency repair demand capture

## Pricing

- Free: Campaign health score, Google Ads audit, performance dashboard — no credit card required
- Growth ($99/month): Full automation, CRM integration, offline conversion upload, review requests
- Pro ($249/month): Multi-location dashboard, all CRM integrations, white-label reports, competitor intelligence
- Managed ($997/month): Done-for-you campaign management with dedicated account manager

## Key Pages

- [Pricing](https://fieldsprout.io/pricing)
- [Free Google Maps audit](https://fieldsprout.io/maps-audit)
- [Free Local Services Ads lead cost estimator](https://fieldsprout.io/lsa-estimator)
- [Google Ads product](https://fieldsprout.io/products/ads)
- [Get more reviews](https://fieldsprout.io/solutions/get-more-reviews)
- [Reduce ad spend](https://fieldsprout.io/solutions/lower-ad-cost)
- [Multi-location management](https://fieldsprout.io/solutions/multi-location)
- [About FieldSprout](https://fieldsprout.io/about)

## Company

FieldSprout is a US-based SaaS company serving home service businesses across the United States. All Google Ads integrations use official Google Ads API access with read/write permissions granted directly by the business owner. FieldSprout is an independent software vendor — not affiliated with Google LLC.
"""
    from flask import Response
    return Response(content, mimetype="text/plain")


@main_bp.route("/sitemap.xml", methods=["GET"], endpoint="sitemap_xml")
def sitemap_xml():
    from flask import Response
    from datetime import date
    today = date.today().isoformat()

    # Sub-route suffixes for industry pages
    industry_sub_routes = [
        "-google-ads",
        "-local-service-ads",
        "-meta-ads",
        "-website-cro",
    ]

    # Main 9 industries (already in sitemap) — add sub-routes
    main_industries = [
        "hvac", "plumbing", "electricians", "roofing", "pest-control",
        "landscaping", "garage-door", "pool-service", "solar",
    ]

    # Additional industries — add main page + sub-routes
    additional_industries = [
        "concrete", "fencing", "irrigation", "lawn-care", "restoration",
        "windows-doors",
    ]

    pages = [
        ("https://fieldsprout.io/", "1.0", "weekly"),
        ("https://fieldsprout.io/pricing", "0.9", "monthly"),
        ("https://fieldsprout.io/about", "0.7", "monthly"),
        ("https://fieldsprout.io/contact", "0.7", "monthly"),
        ("https://fieldsprout.io/free-tools", "0.9", "weekly"),
        ("https://fieldsprout.io/vs-agency", "0.8", "monthly"),
        ("https://fieldsprout.io/roadmap", "0.5", "monthly"),
        ("https://fieldsprout.io/products/ads-demo", "0.8", "monthly"),
        # Main industry pages (existing)
        ("https://fieldsprout.io/industries/hvac", "0.9", "monthly"),
        ("https://fieldsprout.io/industries/plumbing", "0.9", "monthly"),
        ("https://fieldsprout.io/industries/electricians", "0.9", "monthly"),
        ("https://fieldsprout.io/industries/roofing", "0.9", "monthly"),
        ("https://fieldsprout.io/industries/pest-control", "0.9", "monthly"),
        ("https://fieldsprout.io/industries/landscaping", "0.9", "monthly"),
        ("https://fieldsprout.io/industries/garage-door", "0.8", "monthly"),
        ("https://fieldsprout.io/industries/pool-service", "0.8", "monthly"),
        ("https://fieldsprout.io/industries/solar", "0.8", "monthly"),
        # Product pages
        ("https://fieldsprout.io/products/ads", "0.8", "monthly"),
        ("https://fieldsprout.io/products/glsa", "0.8", "monthly"),
        ("https://fieldsprout.io/products/gbp", "0.8", "monthly"),
        ("https://fieldsprout.io/products/facebook-ads", "0.8", "monthly"),
        ("https://fieldsprout.io/products/reviews", "0.8", "monthly"),
        ("https://fieldsprout.io/products/listings", "0.8", "monthly"),
        ("https://fieldsprout.io/products/forms-chat", "0.7", "monthly"),
        # Solution pages
        ("https://fieldsprout.io/solutions/lead-generation", "0.8", "monthly"),
        ("https://fieldsprout.io/solutions/multi-location", "0.8", "monthly"),
        ("https://fieldsprout.io/solutions/lower-ad-cost", "0.8", "monthly"),
        ("https://fieldsprout.io/solutions/get-more-reviews", "0.7", "monthly"),
        ("https://fieldsprout.io/solutions/spend-when-open", "0.7", "monthly"),
        ("https://fieldsprout.io/solutions/see-what-works", "0.7", "monthly"),
        # Tools & graders
        ("https://fieldsprout.io/ads-grader", "0.9", "weekly"),
        ("https://fieldsprout.io/maps-audit", "0.9", "weekly"),
        ("https://fieldsprout.io/lsa-estimator", "0.9", "weekly"),
        # Legal
        ("https://fieldsprout.io/privacy-policy", "0.3", "yearly"),
        ("https://fieldsprout.io/terms-of-service", "0.3", "yearly"),
        ("https://fieldsprout.io/security", "0.4", "yearly"),
        # llms.txt
        ("https://fieldsprout.io/llms.txt", "0.3", "monthly"),
    ]

    # Add sub-routes for main 9 industries
    for industry in main_industries:
        for sub in industry_sub_routes:
            pages.append((f"https://fieldsprout.io/industries/{industry}{sub}", "0.7", "monthly"))

    # Add sub-routes only for additional industries (no main-page template yet)
    for industry in additional_industries:
        for sub in industry_sub_routes:
            pages.append((f"https://fieldsprout.io/industries/{industry}{sub}", "0.7", "monthly"))

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


