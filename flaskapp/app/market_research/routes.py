"""
Market Intelligence routes — self-serve UI for voice-of-customer research + ad scripts.

Exposes:
  GET  /account/market-intel                  — dashboard (trade/city selector)
  POST /account/market-intel/research         — run review + Reddit research (AJAX)
  POST /account/market-intel/ad-scripts       — generate ad scripts from research (AJAX)
  GET  /account/market-intel/volume-plan      — Motion-benchmark volume plan
"""

import json
import logging

from flask import Blueprint, jsonify, render_template, request
from flask_login import current_user

from app.auth.utils import login_required

log = logging.getLogger(__name__)

market_intel_bp = Blueprint(
    "market_intel_bp",
    __name__,
    url_prefix="/account/market-intel",
    template_folder="../../templates/market_intel",
)


@market_intel_bp.route("/")
@login_required
def index():
    return render_template("market_intel/index.html")


@market_intel_bp.route("/research", methods=["POST"])
@login_required
def run_research():
    """Run review miner + Reddit researcher for a trade/city. Returns JSON."""
    data = request.get_json(force=True) or {}
    trade = (data.get("trade") or "").strip().lower()
    city = (data.get("city") or "").strip()

    if not trade or not city:
        return jsonify({"error": "trade and city are required"}), 400

    try:
        from app.market_research.review_miner import mine_reviews
        review_data = mine_reviews(trade, city)
    except Exception:
        log.exception("review_miner failed for %s/%s", trade, city)
        review_data = {"_mock": True, "error": "review research unavailable"}

    try:
        from app.market_research.reddit_researcher import research_trade
        reddit_data = research_trade(trade)
    except Exception:
        log.exception("reddit_researcher failed for %s", trade)
        reddit_data = {"_mock": True, "error": "reddit research unavailable"}

    return jsonify({
        "trade": trade,
        "city": city,
        "review_data": review_data,
        "reddit_data": reddit_data,
        "is_mock": review_data.get("_mock") and reddit_data.get("_mock"),
    })


@market_intel_bp.route("/ad-scripts", methods=["POST"])
@login_required
def generate_scripts():
    """Generate ad script variants from research data. Returns JSON."""
    data = request.get_json(force=True) or {}
    trade = (data.get("trade") or "").strip().lower()
    city = (data.get("city") or "").strip()
    platform = data.get("platform", "meta")
    num_variants = min(12, max(4, int(data.get("num_variants", 8))))
    review_data = data.get("review_data")
    reddit_data = data.get("reddit_data")

    if not trade or not city:
        return jsonify({"error": "trade and city are required"}), 400

    try:
        from app.market_research.ad_scripter import generate_ad_scripts, generate_ad_volume_plan
        variants = generate_ad_scripts(trade, city, review_data, reddit_data, platform, num_variants)
        volume_plan = generate_ad_volume_plan(trade, data.get("monthly_budget", 3000))
    except Exception:
        log.exception("ad_scripter failed for %s/%s", trade, city)
        return jsonify({"error": "ad script generation failed"}), 500

    return jsonify({
        "trade": trade,
        "city": city,
        "platform": platform,
        "variants": variants,
        "volume_plan": volume_plan,
    })


@market_intel_bp.route("/content-strategy", methods=["POST"])
@login_required
def generate_content_strategy():
    """Generate multi-channel content strategy from research data. Returns JSON."""
    data = request.get_json(force=True) or {}
    trade = (data.get("trade") or "").strip().lower()
    city = (data.get("city") or "").strip()
    review_data = data.get("review_data")
    reddit_data = data.get("reddit_data")

    if not trade or not city:
        return jsonify({"error": "trade and city are required"}), 400

    try:
        from app.market_research.content_strategist import (
            generate_blog_ideas,
            generate_landing_page_copy,
            generate_gbp_posts,
            generate_email_sequence,
            generate_social_ideas,
        )
        blog_ideas = generate_blog_ideas(trade, city, review_data, reddit_data)
        landing_page_copy = generate_landing_page_copy(trade, city, review_data, reddit_data)
        gbp_posts = generate_gbp_posts(trade, city, review_data, reddit_data)
        email_sequence = generate_email_sequence(trade, city, review_data, reddit_data)
        social_ideas = generate_social_ideas(trade, city, review_data, reddit_data)
    except Exception:
        log.exception("content_strategist failed for %s/%s", trade, city)
        return jsonify({"error": "content strategy generation failed"}), 500

    return jsonify({
        "trade": trade,
        "city": city,
        "blog_ideas": blog_ideas,
        "landing_page_copy": landing_page_copy,
        "gbp_posts": gbp_posts,
        "email_sequence": email_sequence,
        "social_ideas": social_ideas,
    })


@market_intel_bp.route("/volume-plan")
@login_required
def volume_plan():
    """Return Motion-benchmark volume plan for a trade + budget."""
    trade = request.args.get("trade", "hvac").lower()
    monthly_budget = float(request.args.get("budget", 3000))

    try:
        from app.market_research.ad_scripter import generate_ad_volume_plan
        plan = generate_ad_volume_plan(trade, monthly_budget)
    except Exception:
        log.exception("volume_plan failed")
        return jsonify({"error": "volume plan generation failed"}), 500

    return jsonify(plan)
