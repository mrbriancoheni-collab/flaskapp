# app/google/alerts_routes.py
"""
Google Ads Alerts - Display alerts and recommendations from Google Ads.
"""
from flask import Blueprint, render_template, jsonify, request
from sqlalchemy import text
from datetime import datetime

from app import db
from app.auth.utils import login_required, current_account_id
from app.services.google_ads_alerts_service import (
    fetch_google_ads_alerts,
    apply_recommendation,
    dismiss_recommendation,
    get_google_ads_client
)

alerts_bp = Blueprint("alerts_bp", __name__, url_prefix="/account/google/ads/alerts")


@alerts_bp.route("/")
@login_required
def alerts_dashboard():
    """
    Google Ads Alerts Dashboard - View recommendations and alerts from Google Ads.
    """
    account_id = current_account_id()

    # Get Google Ads credentials
    creds_query = text("""
        SELECT customer_id, credentials_json
        FROM google_oauth_tokens
        WHERE account_id = :account_id AND product = 'ads'
        LIMIT 1
    """)

    with db.engine.connect() as conn:
        result = conn.execute(creds_query, {"account_id": account_id})
        row = result.first()

        if not row:
            return render_template(
                "google/alerts_dashboard.html",
                error="Google Ads not connected. Please connect Google Ads first.",
                recommendations=[],
                account_alerts=[],
                change_history=[]
            )

    customer_id = row.customer_id

    # Extract refresh token from credentials JSON
    import json
    try:
        creds = json.loads(row.credentials_json) if isinstance(row.credentials_json, str) else row.credentials_json
        refresh_token = creds.get('refresh_token')

        if not refresh_token:
            return render_template(
                "google/alerts_dashboard.html",
                error="No refresh token found in Google Ads credentials",
                recommendations=[],
                account_alerts=[],
                change_history=[]
            )

        # Fetch alerts from Google Ads
        alerts_data = fetch_google_ads_alerts(refresh_token, customer_id)

        if not alerts_data.get('success', True):  # If there's an error
            return render_template(
                "google/alerts_dashboard.html",
                error=alerts_data.get('error', 'Unknown error'),
                error_details=alerts_data.get('details', []),
                recommendations=[],
                account_alerts=[],
                change_history=[]
            )

        return render_template(
            "google/alerts_dashboard.html",
            recommendations=alerts_data.get('recommendations', []),
            account_alerts=alerts_data.get('account_alerts', []),
            change_history=alerts_data.get('change_history', [])[:20],  # Limit to 20 recent changes
            fetched_at=alerts_data.get('fetched_at')
        )

    except Exception as e:
        return render_template(
            "google/alerts_dashboard.html",
            error=f"Error fetching alerts: {str(e)}",
            recommendations=[],
            account_alerts=[],
            change_history=[]
        )


@alerts_bp.route("/api/recommendations/<path:resource_name>/apply", methods=["POST"])
@login_required
def apply_recommendation_route(resource_name):
    """Apply a Google Ads recommendation."""
    account_id = current_account_id()

    # Get credentials
    creds_query = text("""
        SELECT customer_id, credentials_json
        FROM google_oauth_tokens
        WHERE account_id = :account_id AND product = 'ads'
        LIMIT 1
    """)

    with db.engine.connect() as conn:
        result = conn.execute(creds_query, {"account_id": account_id})
        row = result.first()

        if not row:
            return jsonify({"success": False, "error": "Google Ads not connected"}), 400

    import json
    creds = json.loads(row.credentials_json) if isinstance(row.credentials_json, str) else row.credentials_json
    refresh_token = creds.get('refresh_token')

    try:
        client = get_google_ads_client(refresh_token, row.customer_id)
        result = apply_recommendation(client, row.customer_id, resource_name)
        return jsonify(result)

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@alerts_bp.route("/api/recommendations/<path:resource_name>/dismiss", methods=["POST"])
@login_required
def dismiss_recommendation_route(resource_name):
    """Dismiss a Google Ads recommendation."""
    account_id = current_account_id()

    # Get credentials
    creds_query = text("""
        SELECT customer_id, credentials_json
        FROM google_oauth_tokens
        WHERE account_id = :account_id AND product = 'ads'
        LIMIT 1
    """)

    with db.engine.connect() as conn:
        result = conn.execute(creds_query, {"account_id": account_id})
        row = result.first()

        if not row:
            return jsonify({"success": False, "error": "Google Ads not connected"}), 400

    import json
    creds = json.loads(row.credentials_json) if isinstance(row.credentials_json, str) else row.credentials_json
    refresh_token = creds.get('refresh_token')

    try:
        client = get_google_ads_client(refresh_token, row.customer_id)
        result = dismiss_recommendation(client, row.customer_id, resource_name)
        return jsonify(result)

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@alerts_bp.route("/api/refresh", methods=["POST"])
@login_required
def refresh_alerts():
    """Manually refresh alerts from Google Ads."""
    account_id = current_account_id()

    # Get credentials
    creds_query = text("""
        SELECT customer_id, credentials_json
        FROM google_oauth_tokens
        WHERE account_id = :account_id AND product = 'ads'
        LIMIT 1
    """)

    with db.engine.connect() as conn:
        result = conn.execute(creds_query, {"account_id": account_id})
        row = result.first()

        if not row:
            return jsonify({"success": False, "error": "Google Ads not connected"}), 400

    import json
    creds = json.loads(row.credentials_json) if isinstance(row.credentials_json, str) else row.credentials_json
    refresh_token = creds.get('refresh_token')

    try:
        alerts_data = fetch_google_ads_alerts(refresh_token, row.customer_id)
        return jsonify(alerts_data)

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
