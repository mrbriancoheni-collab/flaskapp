# app/google/alerts_routes.py
"""
Google Ads Alerts - Display alerts and recommendations from Google Ads.
"""
from flask import Blueprint, render_template, jsonify, request, current_app
from sqlalchemy import text
from datetime import datetime
import json as json_module

from app import db
from app.auth.utils import login_required, current_account_id
from app.services.google_ads_alerts_service import (
    fetch_google_ads_alerts,
    apply_recommendation,
    dismiss_recommendation,
    get_google_ads_client
)

alerts_bp = Blueprint("alerts_bp", __name__, url_prefix="/account/google/ads/alerts")


def _safe_parse_credentials(credentials_json) -> dict:
    """Safely parse credentials JSON, returning empty dict on failure."""
    if not credentials_json:
        return {}
    try:
        if isinstance(credentials_json, str):
            return json_module.loads(credentials_json)
        elif isinstance(credentials_json, dict):
            return credentials_json
        return {}
    except (json_module.JSONDecodeError, TypeError, ValueError) as e:
        current_app.logger.error(f"Failed to parse credentials_json: {e}")
        return {}


def _get_ads_credentials(account_id: int) -> tuple:
    """
    Get Google Ads credentials for an account.
    Returns (customer_id, refresh_token) or (None, None) on failure.
    """
    try:
        creds_query = text("""
            SELECT customer_id, credentials_json, refresh_token
            FROM google_oauth_tokens
            WHERE account_id = :account_id AND LOWER(product) IN ('ads', 'lsa')
            ORDER BY updated_at DESC
            LIMIT 1
        """)

        with db.engine.connect() as conn:
            result = conn.execute(creds_query, {"account_id": account_id})
            row = result.first()

            if not row:
                return None, None

            customer_id = row.customer_id if hasattr(row, 'customer_id') else None

            # Try refresh_token column first, then credentials_json
            refresh_token = None
            if hasattr(row, 'refresh_token') and row.refresh_token:
                refresh_token = row.refresh_token
            elif hasattr(row, 'credentials_json') and row.credentials_json:
                creds = _safe_parse_credentials(row.credentials_json)
                refresh_token = creds.get('refresh_token')

            return customer_id, refresh_token
    except Exception as e:
        current_app.logger.error(f"Error getting ads credentials: {e}")
        return None, None


@alerts_bp.route("/")
@login_required
def alerts_dashboard():
    """
    Google Ads Alerts Dashboard - View recommendations and alerts from Google Ads.
    """
    account_id = current_account_id()

    # Default empty response for error cases
    empty_response = {
        "recommendations": [],
        "account_alerts": [],
        "change_history": []
    }

    # Get Google Ads credentials using helper function
    customer_id, refresh_token = _get_ads_credentials(account_id)

    if not customer_id and not refresh_token:
        return render_template(
            "google/alerts_dashboard.html",
            error="Google Ads not connected. Please connect Google Ads first.",
            **empty_response
        )

    if not customer_id:
        return render_template(
            "google/alerts_dashboard.html",
            error="No Google Ads customer ID found. Please select a Google Ads account.",
            **empty_response
        )

    if not refresh_token:
        return render_template(
            "google/alerts_dashboard.html",
            error="No refresh token found. Please reconnect Google Ads.",
            **empty_response
        )

    try:
        # Fetch alerts from Google Ads
        alerts_data = fetch_google_ads_alerts(refresh_token, customer_id)

        if not alerts_data.get('success', True):  # If there's an error
            error_msg = alerts_data.get('error', 'Unknown error')
            error_details = alerts_data.get('details', [])

            # Check for authentication errors - suggest reconnection
            if 'UNAUTHENTICATED' in str(error_msg) or 'authentication' in str(error_msg).lower():
                error_msg = "Authentication failed. Please try disconnecting and reconnecting Google Ads."

            return render_template(
                "google/alerts_dashboard.html",
                error=error_msg,
                error_details=error_details,
                **empty_response
            )

        return render_template(
            "google/alerts_dashboard.html",
            recommendations=alerts_data.get('recommendations', []),
            account_alerts=alerts_data.get('account_alerts', []),
            change_history=alerts_data.get('change_history', [])[:20],  # Limit to 20 recent changes
            fetched_at=alerts_data.get('fetched_at')
        )

    except Exception as e:
        current_app.logger.exception(f"Error in alerts_dashboard: {e}")
        return render_template(
            "google/alerts_dashboard.html",
            error=f"Error fetching alerts: {str(e)}",
            **empty_response
        )


@alerts_bp.route("/api/recommendations/<path:resource_name>/apply", methods=["POST"])
@login_required
def apply_recommendation_route(resource_name):
    """Apply a Google Ads recommendation."""
    account_id = current_account_id()

    # Get credentials using helper function
    customer_id, refresh_token = _get_ads_credentials(account_id)

    if not customer_id or not refresh_token:
        return jsonify({
            "success": False,
            "error": "Google Ads not connected or missing credentials"
        }), 400

    try:
        client = get_google_ads_client(refresh_token, customer_id)
        result = apply_recommendation(client, customer_id, resource_name)
        return jsonify(result)

    except Exception as e:
        current_app.logger.exception(f"Error applying recommendation: {e}")
        error_msg = str(e)
        if 'UNAUTHENTICATED' in error_msg:
            error_msg = "Authentication failed. Please reconnect Google Ads."
        return jsonify({"success": False, "error": error_msg}), 500


@alerts_bp.route("/api/recommendations/<path:resource_name>/dismiss", methods=["POST"])
@login_required
def dismiss_recommendation_route(resource_name):
    """Dismiss a Google Ads recommendation."""
    account_id = current_account_id()

    # Get credentials using helper function
    customer_id, refresh_token = _get_ads_credentials(account_id)

    if not customer_id or not refresh_token:
        return jsonify({
            "success": False,
            "error": "Google Ads not connected or missing credentials"
        }), 400

    try:
        client = get_google_ads_client(refresh_token, customer_id)
        result = dismiss_recommendation(client, customer_id, resource_name)
        return jsonify(result)

    except Exception as e:
        current_app.logger.exception(f"Error dismissing recommendation: {e}")
        error_msg = str(e)
        if 'UNAUTHENTICATED' in error_msg:
            error_msg = "Authentication failed. Please reconnect Google Ads."
        return jsonify({"success": False, "error": error_msg}), 500


@alerts_bp.route("/api/refresh", methods=["POST"])
@login_required
def refresh_alerts():
    """Manually refresh alerts from Google Ads."""
    account_id = current_account_id()

    # Get credentials using helper function
    customer_id, refresh_token = _get_ads_credentials(account_id)

    if not customer_id or not refresh_token:
        return jsonify({
            "success": False,
            "error": "Google Ads not connected or missing credentials"
        }), 400

    try:
        alerts_data = fetch_google_ads_alerts(refresh_token, customer_id)
        return jsonify(alerts_data)

    except Exception as e:
        current_app.logger.exception(f"Error refreshing alerts: {e}")
        error_msg = str(e)
        if 'UNAUTHENTICATED' in error_msg:
            error_msg = "Authentication failed. Please reconnect Google Ads."
        return jsonify({"success": False, "error": error_msg}), 500
