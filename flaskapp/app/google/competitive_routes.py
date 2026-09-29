# app/google/competitive_routes.py
"""
Google Ads Competitive Intelligence Routes

Thin shim that:
  - Redirects the old /account/google/ads/competitive URL to the main
    competitive dashboard at /account/competitive.
  - Exposes a /auction-insights endpoint that returns raw auction insight
    data as JSON (or redirects if a browser visits it).

The variable exported as `competitive_bp` uses the internal Blueprint name
`google_competitive_bp` to avoid a Flask name collision with the
`competitive_bp` Blueprint registered from app.account.competitive_routes.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from flask import Blueprint, jsonify, redirect, request

from app import db
from app.auth.utils import current_account_id, login_required
from sqlalchemy import text

log = logging.getLogger(__name__)

# NOTE: Blueprint *variable* is `competitive_bp` (as imported by app/__init__.py),
#       but the Flask-internal *name* is `google_competitive_bp` to avoid conflicts.
competitive_bp = Blueprint(
    "google_competitive_bp",
    __name__,
    url_prefix="/account/google/ads/competitive",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_customer_id(account_id: int) -> str | None:
    """Return the Google Ads customer_id for an account, or None."""
    try:
        from app.google.utils_ads import resolve_ads_context

        ctx = resolve_ads_context(account_id) or {}
        return ctx.get("customer_id")
    except Exception as exc:
        log.debug("resolve_ads_context unavailable: %s", exc)
        return None


def _fetch_auction_insights_gaql(
    account_id: int, customer_id: str, days: int = 30
) -> list[dict]:
    """
    Run a GAQL query for auction insights and return rows as dicts.
    Returns an empty list if Google Ads is not connected or the query fails.
    """
    try:
        from app.google.utils_ads import google_ads_search
    except ImportError:
        return []

    end = date.today()
    start = end - timedelta(days=days)

    query = f"""
        SELECT
          auction_insight_competitor.domain,
          metrics.search_impression_share,
          metrics.search_overlap_rate,
          metrics.search_position_above_rate,
          metrics.search_top_impression_share,
          metrics.search_absolute_top_impression_share
        FROM auction_insight_competitor
        WHERE segments.date BETWEEN '{start}' AND '{end}'
    """

    try:
        rows = google_ads_search(
            account_id=account_id,
            customer_id=customer_id,
            query=query,
        )
        return rows or []
    except Exception as exc:
        log.info("Auction insights GAQL query failed: %s", exc)
        return []


def _format_auction_insights(raw_rows: list[dict]) -> list[dict]:
    """Normalise GAQL result rows into a clean list of dicts."""
    results = []
    for row in raw_rows:
        domain = (
            row.get("auction_insight_competitor", {}).get("domain")
            or row.get("domain", "unknown")
        )
        metrics = row.get("metrics", {})
        impression_share = round(
            float(metrics.get("search_impression_share", 0)) * 100, 1
        )
        overlap_rate = round(float(metrics.get("search_overlap_rate", 0)), 2)
        position_above_rate = round(
            float(metrics.get("search_position_above_rate", 0)), 2
        )
        top_impression_share = round(
            float(metrics.get("search_top_impression_share", 0)) * 100, 1
        )
        abs_top = round(
            float(metrics.get("search_absolute_top_impression_share", 0)) * 100, 1
        )

        threat_level = (
            "high" if position_above_rate > 0.60
            else "medium" if position_above_rate > 0.45
            else "low"
        )

        results.append(
            {
                "domain": domain,
                "competitor_domain": domain,
                "impression_share": impression_share,
                "overlap_rate": overlap_rate,
                "position_above_rate": position_above_rate,
                "top_impression_share": top_impression_share,
                "absolute_top_impression_share": abs_top,
                "threat_level": threat_level,
            }
        )

    results.sort(key=lambda x: x["impression_share"], reverse=True)
    return results


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@competitive_bp.route("/", methods=["GET"])
def index():
    """Redirect legacy URL to the main competitive dashboard."""
    return redirect("/account/competitive")


@competitive_bp.route("/auction-insights", methods=["GET"])
@login_required
def auction_insights():
    """
    GET /account/google/ads/competitive/auction-insights

    Returns Google Ads Auction Insights as JSON.
    Query params:
      - days  (int, default 30)  : lookback window

    Falls back to an empty dataset with a descriptive message when
    Google Ads is not connected.
    """
    account_id = current_account_id()
    days = request.args.get("days", 30, type=int)

    customer_id = _resolve_customer_id(account_id)

    if not customer_id:
        return jsonify(
            {
                "ok": False,
                "success": False,
                "connected": False,
                "message": (
                    "Google Ads is not connected for this account. "
                    "Connect via Settings → Integrations to see real auction insights."
                ),
                "competitors": [],
            }
        )

    raw_rows = _fetch_auction_insights_gaql(account_id, customer_id, days=days)

    if not raw_rows:
        return jsonify(
            {
                "ok": True,
                "success": True,
                "connected": True,
                "customer_id": customer_id,
                "days": days,
                "message": (
                    "No auction insight data returned for the selected period. "
                    "Data typically appears after campaigns have been running for a few days."
                ),
                "competitors": [],
            }
        )

    competitors = _format_auction_insights(raw_rows)

    return jsonify(
        {
            "ok": True,
            "success": True,
            "connected": True,
            "customer_id": customer_id,
            "days": days,
            "num_competitors": len(competitors),
            "competitors": competitors,
        }
    )
