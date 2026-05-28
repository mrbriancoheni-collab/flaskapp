# app/google/dayparting_routes.py
"""
Dayparting Blueprint — Ad Schedule Optimizer routes.

URL prefix: /account/google/ads/dayparting
"""
from __future__ import annotations

import logging

from flask import Blueprint, jsonify, render_template, request

from app import db
from app.auth.utils import login_required, current_account_id

logger = logging.getLogger(__name__)

dayparting_bp = Blueprint(
    "dayparting_bp",
    __name__,
    url_prefix="/account/google/ads/dayparting",
)


# ── Page ──────────────────────────────────────────────────────────────────────

@dayparting_bp.get("/")
@login_required
def dayparting_page():
    """Render the Ad Schedule Optimizer heat-map page."""
    return render_template("google/ads/dayparting.html")


# ── API: sync hourly data from Google Ads ────────────────────────────────────

@dayparting_bp.post("/sync")
@login_required
def sync_hourly():
    """
    Pull the last 14 days of hourly campaign stats from Google Ads
    and upsert into gads_hourly_stats.

    Returns JSON: {"synced": N, "errors": [...]}.
    """
    aid = current_account_id()
    try:
        from app.services.google_ads_dayparting import sync_hourly_stats
        result = sync_hourly_stats(aid)
        return jsonify(result)
    except Exception as exc:
        logger.exception("sync_hourly: unexpected error for account %s", aid)
        return jsonify({"synced": 0, "errors": [str(exc)]}), 500


# ── API: compute proposed adjustments ────────────────────────────────────────

@dayparting_bp.post("/compute")
@login_required
def compute():
    """
    Analyse hourly data and return proposed bid modifiers.

    Returns JSON list of adjustment dicts.
    """
    aid = current_account_id()
    try:
        from app.services.google_ads_dayparting import compute_daypart_adjustments
        adjustments = compute_daypart_adjustments(aid)
        return jsonify(adjustments)
    except Exception as exc:
        logger.exception("compute: unexpected error for account %s", aid)
        return jsonify({"error": str(exc)}), 500


# ── API: apply adjustments to Google Ads ─────────────────────────────────────

@dayparting_bp.post("/apply")
@login_required
def apply():
    """
    Accepts a JSON list of adjustment dicts (from /compute) in the request body,
    pushes them to Google Ads, and persists to daypart_bid_adjustments.

    Returns JSON: {"applied": N, "errors": [...]}.
    """
    aid = current_account_id()
    try:
        adjustments = request.get_json(force=True, silent=True) or []
        if not isinstance(adjustments, list):
            return jsonify({"error": "Request body must be a JSON array."}), 400

        from app.services.google_ads_dayparting import apply_daypart_adjustments
        result = apply_daypart_adjustments(aid, adjustments)
        return jsonify(result)
    except Exception as exc:
        logger.exception("apply: unexpected error for account %s", aid)
        return jsonify({"applied": 0, "errors": [str(exc)]}), 500


# ── API: current schedule JSON (for heat-map rendering) ──────────────────────

@dayparting_bp.get("/schedule.json")
@login_required
def schedule_json():
    """
    Return all DaypartBidAdjustment rows for the current account as JSON.

    Each item: {campaign_id, campaign_name, day_of_week, hour, bid_modifier, applied_at}.
    """
    aid = current_account_id()
    try:
        from app.models_ads import DaypartBidAdjustment, AdsCampaign

        rows = (
            DaypartBidAdjustment.query
            .filter_by(account_id=aid)
            .order_by(
                DaypartBidAdjustment.campaign_id,
                DaypartBidAdjustment.day_of_week,
                DaypartBidAdjustment.hour,
            )
            .all()
        )

        # Build campaign name lookup
        camp_names = {
            c.id: c.name
            for c in AdsCampaign.query.filter_by(account_id=aid).all()
        }

        payload = []
        for r in rows:
            payload.append({
                "id": r.id,
                "campaign_id": r.campaign_id,
                "campaign_name": camp_names.get(r.campaign_id, f"Campaign {r.campaign_id}"),
                "day_of_week": r.day_of_week,
                "hour": r.hour,
                "bid_modifier": r.bid_modifier,
                "applied_at": r.applied_at.isoformat() if r.applied_at else None,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            })

        return jsonify(payload)
    except Exception as exc:
        logger.exception("schedule_json: unexpected error for account %s", aid)
        return jsonify({"error": str(exc)}), 500
