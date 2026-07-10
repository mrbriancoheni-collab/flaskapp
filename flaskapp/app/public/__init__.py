# app/public/__init__.py (or wherever your public routes live)
from flask import Blueprint, render_template, abort
from jinja2.exceptions import TemplateNotFound

public_bp = Blueprint(
    "public_bp",
    __name__,
    template_folder="../../templates",  # uses your existing templates dir
)

@public_bp.route("/privacy-policy", methods=["GET"])
def privacy_policy():
    return render_template("public/privacy_policy.html")

@public_bp.route("/terms-of-service", methods=["GET"])
def terms_of_service():
    return render_template("public/terms_of_service.html")

@public_bp.route("/products/ads")
@public_bp.route("/products/google-ads")
def product_google_ads(): return render_template("google_ads.html")

@public_bp.route("/products/glsa")
def product_glsa(): return render_template("glsa.html")

@public_bp.route("/products/gbp")
def product_gbp(): return render_template("gbp.html")

@public_bp.route("/products/facebook-ads")
def product_facebook_ads(): return render_template("facebook_ads.html")

@public_bp.route("/products/reviews")
def product_reviews(): return render_template("product_reviews.html")

@public_bp.route("/products/listings")
def product_listings(): return render_template("product_listings.html")

@public_bp.route("/products/forms-chat")
def product_forms_chat(): return render_template("product_forms_chat.html")

@public_bp.route("/solutions/lead-generation")
def solution_lead_gen(): return render_template("lead_generation.html")

@public_bp.route("/solutions/multi-location")
def solution_multi_location(): return render_template("multi_location.html")

@public_bp.route("/solutions/lower-ad-cost", endpoint="lower_ad_cost")
def lower_ad_cost():
    return render_template("lower_ad_cost.html")

@public_bp.route("/solutions/get-more-reviews", endpoint="get_more_reviews")
def get_more_reviews():
    return render_template("get_more_reviews.html")

@public_bp.route("/solutions/spend-when-open", endpoint="spend_when_open")
def spend_when_open():
    return render_template("spend_when_open.html")

@public_bp.route("/solutions/see-what-works", endpoint="see_what_works")
def see_what_works():
    return render_template("see_what_works.html")

@public_bp.route("/podcast", endpoint="podcast")
def podcast():
    return render_template("public/podcast.html")


@public_bp.route("/free-tools", endpoint="free_tools")
def free_tools():
    return render_template("free_tools.html")


@public_bp.route("/roadmap", endpoint="roadmap")
def roadmap():
    return render_template("roadmap.html")


@public_bp.route("/products/ads-demo", endpoint="product_ads_demo")
def product_ads_demo():
    return render_template("google_ads_demo.html")



@public_bp.route("/vs-agency", endpoint="vs_agency")
def vs_agency():
    return render_template("vs_agency.html")


@public_bp.route("/industries/hvac", endpoint="industry_hvac")
def industry_hvac():
    return render_template("industries/hvac.html")


@public_bp.route("/industries/plumbing", endpoint="industry_plumbing")
def industry_plumbing():
    return render_template("industries/plumbing.html")


@public_bp.route("/industries/electricians", endpoint="industry_electricians")
def industry_electricians():
    return render_template("industries/electricians.html")


@public_bp.route("/industries/roofing", endpoint="industry_roofing")
def industry_roofing():
    return render_template("industries/roofing.html")


@public_bp.route("/industries/pest-control", endpoint="industry_pest_control")
def industry_pest_control():
    return render_template("industries/pest-control.html")


@public_bp.route("/industries/landscaping", endpoint="industry_landscaping")
def industry_landscaping():
    return render_template("industries/landscaping.html")


@public_bp.route("/industries/garage-door", endpoint="industry_garage_door")
def industry_garage_door():
    return render_template("industries/garage-door.html")


@public_bp.route("/industries/pool-service", endpoint="industry_pool_service")
def industry_pool_service():
    return render_template("industries/pool-service.html")


@public_bp.route("/industries/solar", endpoint="industry_solar")
def industry_solar():
    return render_template("industries/solar.html")


_INDUSTRY_TEMPLATE_OVERRIDES = {
    'electricians-google-ads':        'industries/electrical-google-ads.html',
    'electricians-local-service-ads': 'industries/electrical-local-service-ads.html',
    'electricians-meta-ads':          'industries/electrical-meta-ads.html',
    'electricians-website-cro':       'industries/electrical-website-cro.html',
    'pool-service-google-ads':        'industries/pools-google-ads.html',
    'pool-service-local-service-ads': 'industries/pools-local-service-ads.html',
    'pool-service-meta-ads':          'industries/pools-meta-ads.html',
    'pool-service-website-cro':       'industries/pools-website-cro.html',
}


@public_bp.route("/industries/<slug>", endpoint="industry_subpage")
def industry_subpage(slug):
    template = _INDUSTRY_TEMPLATE_OVERRIDES.get(slug, f'industries/{slug}.html')
    try:
        return render_template(template)
    except TemplateNotFound:
        abort(404)


@public_bp.route("/sitemap.html", endpoint="sitemap")
def sitemap():
    return render_template("public/sitemap.html")


@public_bp.route("/lifetime/<tier>", endpoint="lifetime_deal")
def lifetime_deal(tier):
    if tier not in ("499", "999"):
        from flask import abort
        abort(404)
    return render_template("public/lifetime_deal.html", tier=tier)


@public_bp.route("/nps/<token>", endpoint="nps_respond")
def nps_respond(token: str):
    """Public NPS survey response endpoint — no login required."""
    from flask import request, make_response
    try:
        score = int(request.args.get("score", 0))
    except (ValueError, TypeError):
        score = 0

    if score < 1 or score > 10:
        from flask import abort
        abort(400)

    try:
        from app.services.nps_service import record_nps_response, build_response_page
        survey = record_nps_response(token, score)
        html = build_response_page(survey, score)
    except Exception:
        html = "<p>Thank you for your feedback!</p>"

    return make_response(html, 200, {"Content-Type": "text/html; charset=utf-8"})