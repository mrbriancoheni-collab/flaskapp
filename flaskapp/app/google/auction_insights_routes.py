# app/google/auction_insights_routes.py
"""
Auction Insights / Competitor Benchmarking Routes.

Blueprint: auction_insights_bp
Prefix:    /account/google/ads/competitors

Deliberately separate from competitive_routes.py (which only does live-GAQL
pass-through and redirects). This module owns the DB-backed workflow:
  GET  /          → render competitors.html
  POST /sync      → pull from Google Ads API, upsert DB
  GET  /summary.json → aggregate + plain-English insights JSON
  POST /auto-respond  → create OptimizerRecommendation if IS dropped
"""
from __future__ import annotations

import logging

from flask import Blueprint, jsonify, render_template

from app.auth.utils import login_required, current_account_id

log = logging.getLogger(__name__)

auction_insights_bp = Blueprint(
    "auction_insights_bp",
    __name__,
    url_prefix="/account/google/ads/competitors",
)


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

@auction_insights_bp.get("/")
@login_required
def competitors_page():
    """Render the competitor benchmarking dashboard."""
    return render_template("google/ads/competitors.html")


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------

@auction_insights_bp.post("/sync")
@login_required
def sync():
    """
    POST /account/google/ads/competitors/sync

    Pulls auction insight rows from Google Ads and upserts into DB.
    Returns JSON: {"ok": bool, "synced": int, "errors": [str]}
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

    Returns aggregated competitor data for the last 30 days.
    Response shape:
      {
        "ok": true,
        "your_avg_impression_share": 0.42,
        "competitors": [...],
        "top_opportunity": "...",
        "last_synced": "2024-01-15T10:30:00"
      }
    """
    account_id = current_account_id()
    try:
        from app.services.google_ads_auction_insights import get_competitor_summary
        summary = get_competitor_summary(account_id)
        return jsonify({"ok": True, **summary})
    except Exception as exc:
        log.exception("get_competitor_summary failed for account %s", account_id)
        return jsonify({"ok": False, "error": str(exc)}), 500


@auction_insights_bp.post("/auto-respond")
@login_required
def auto_respond():
    """
    POST /account/google/ads/competitors/auto-respond

    Detects impression share drops vs competitor gains and creates
    OptimizerRecommendation rows.
    Returns JSON: {"ok": bool, "recommendations_created": int, "details": [...]}
    """
    account_id = current_account_id()
    try:
        from app.services.google_ads_auction_insights import (
            auto_respond_to_impression_loss,
        )
        result = auto_respond_to_impression_loss(account_id)
        return jsonify({"ok": True, **result})
    except Exception as exc:
        log.exception(
            "auto_respond_to_impression_loss failed for account %s", account_id
        )
        return jsonify(
            {"ok": False, "recommendations_created": 0, "errors": [str(exc)]}
        ), 500
