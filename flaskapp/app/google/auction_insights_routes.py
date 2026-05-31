# app/google/auction_insights_routes.py
"""
Auction Insights / Competitor Benchmarking Routes.

Blueprint: auction_insights_bp
Prefix:    /account/google/ads/competitors
"""
from __future__ import annotations

import logging

from flask import Blueprint, jsonify, render_template

from app.auth.utils import login_required, current_account_id, growth_required

log = logging.getLogger(__name__)

auction_insights_bp = Blueprint(
    "auction_insights_bp",
    __name__,
    url_prefix="/account/google/ads/competitors",
)


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

@auction_insights_bp.get("/")
@login_required
def competitors_page():
    """Render the competitor benchmarking dashboard."""
    return render_template("google/ads/competitors.html")


# ---------------------------------------------------------------------------
# Data / Actions
# ---------------------------------------------------------------------------

@auction_insights_bp.post("/sync")
@login_required
def sync():
    """
    POST /account/google/ads/competitors/sync

    Pulls the latest auction insight data from Google Ads and upserts it
    into the local database.  Returns JSON with sync counts and any errors.
    """
    account_id = current_account_id()
    try:
        from app.services.google_ads_auction_insights import sync_auction_insights
        result = sync_auction_insights(account_id)
        return jsonify({"ok": True, **result})
    except Exception as exc:
        log.exception("sync_auction_insights failed for account %s", account_id)
        return jsonify({"ok": False, "synced": 0, "errors": [str(exc)]}), 500


@auction_insights_bp.get("/summary.json")
@login_required
def summary_json():
    """
    GET /account/google/ads/competitors/summary.json

    Returns an aggregated competitor summary for the last 30 days including
    plain-English insights and a top opportunity recommendation.
    """
    account_id = current_account_id()
    try:
        from app.services.google_ads_auction_insights import get_competitor_summary
        data = get_competitor_summary(account_id)
        # Serialize datetime to ISO string for JSON
        if data.get("last_synced"):
            data["last_synced"] = data["last_synced"].isoformat()
        return jsonify({"ok": True, **data})
    except Exception as exc:
        log.exception("get_competitor_summary failed for account %s", account_id)
        return jsonify({"ok": False, "error": str(exc)}), 500


@auction_insights_bp.post("/auto-respond")
@login_required
@growth_required
def auto_respond():
    """
    POST /account/google/ads/competitors/auto-respond

    Checks whether a top competitor has recently gained significant impression
    share while ours has dropped, and generates an OptimizerRecommendation if so.
    """
    account_id = current_account_id()
    try:
        from app.services.google_ads_auction_insights import auto_respond_to_impression_loss
        result = auto_respond_to_impression_loss(account_id)
        return jsonify({"ok": True, **result})
    except Exception as exc:
        log.exception("auto_respond_to_impression_loss failed for account %s", account_id)
        return jsonify({"ok": False, "triggered": False, "error": str(exc)}), 500
