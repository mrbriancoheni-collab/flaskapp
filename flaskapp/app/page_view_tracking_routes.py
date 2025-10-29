# app/page_view_tracking_routes.py
"""
Public endpoints for tracking page views.
These endpoints are called by JavaScript on the frontend to log user navigation.
"""
from __future__ import annotations

from flask import Blueprint, request, jsonify, current_app
from flask_login import current_user

from app.services.page_view_tracking import log_page_view, update_time_on_page


page_view_tracking_bp = Blueprint("page_view_tracking_bp", __name__, url_prefix="/pv")


@page_view_tracking_bp.route("/pageview", methods=["POST"])
def track_pageview():
    """
    Track a page view.

    Expected JSON payload:
    {
        "session_id": "abc123...",
        "path": "/pricing",
        "page_title": "Pricing - FieldSprout",
        "referrer": "https://google.com/...",
        "query_string": "?utm_source=google&utm_medium=cpc"
    }

    Returns:
        JSON with page_view_id
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400

        session_id = data.get("session_id")
        path = data.get("path")

        if not session_id or not path:
            return jsonify({"error": "session_id and path are required"}), 400

        # Get user ID if logged in
        user_id = None
        try:
            if current_user and current_user.is_authenticated:
                user_id = current_user.id
        except Exception:
            pass

        # Get client details
        ip_address = request.headers.get("X-Forwarded-For", request.remote_addr)
        user_agent = request.headers.get("User-Agent", "")

        # Log the page view
        page_view = log_page_view(
            session_id=session_id,
            path=path,
            page_title=data.get("page_title"),
            referrer=data.get("referrer"),
            query_string=data.get("query_string"),
            ip_address=ip_address,
            user_agent=user_agent,
            user_id=user_id,
        )

        return jsonify({
            "success": True,
            "page_view_id": page_view.id,
        }), 200

    except Exception as e:
        current_app.logger.error(f"Error tracking page view: {e}")
        # Always return success to not break the user experience
        return jsonify({"success": True}), 200


@page_view_tracking_bp.route("/pageview/<int:page_view_id>/time", methods=["POST"])
def update_page_time(page_view_id: int):
    """
    Update time spent on a page.

    Expected JSON payload:
    {
        "time_on_page": 45  // seconds
    }
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400

        time_on_page = data.get("time_on_page")
        if time_on_page is None:
            return jsonify({"error": "time_on_page is required"}), 400

        success = update_time_on_page(page_view_id, int(time_on_page))

        return jsonify({"success": success}), 200

    except Exception as e:
        current_app.logger.error(f"Error updating page time: {e}")
        # Always return success to not break the user experience
        return jsonify({"success": True}), 200


@page_view_tracking_bp.route("/health", methods=["GET"])
def health_check():
    """Health check endpoint for tracking service."""
    return jsonify({"status": "ok"}), 200
