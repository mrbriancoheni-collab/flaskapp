# app/journey_builder/__init__.py
"""
Visual Journey Builder Module
Allows users to create and visualize marketing funnels.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from flask import (
    Blueprint,
    current_app,
    render_template,
    jsonify,
    request,
    flash,
    redirect,
    url_for,
)
from sqlalchemy import text

from app import db
from app.auth.utils import login_required, current_account_id, is_paid_account

journey_bp = Blueprint("journey_bp", __name__, url_prefix="/account/journeys")


# Pre-built journey templates
JOURNEY_TEMPLATES = {
    "new_customer": {
        "name": "New Customer Acquisition",
        "description": "Attract and convert new customers",
        "icon": "fa-user-plus",
        "color": "blue",
        "stages": [
            {
                "id": "awareness",
                "name": "Awareness",
                "type": "ad",
                "description": "Customer sees your ad",
                "channels": ["Google Ads", "Facebook Ads"],
                "icon": "fa-eye",
                "metrics": ["impressions", "reach"]
            },
            {
                "id": "interest",
                "name": "Interest",
                "type": "landing",
                "description": "Customer clicks and visits website",
                "channels": ["Landing Page"],
                "icon": "fa-mouse-pointer",
                "metrics": ["clicks", "ctr"]
            },
            {
                "id": "consideration",
                "name": "Consideration",
                "type": "nurture",
                "description": "Customer browses, reads reviews",
                "channels": ["Website", "Google Business"],
                "icon": "fa-search",
                "metrics": ["time_on_site", "pages_viewed"]
            },
            {
                "id": "conversion",
                "name": "Conversion",
                "type": "action",
                "description": "Customer calls or fills form",
                "channels": ["Phone", "Form"],
                "icon": "fa-phone",
                "metrics": ["conversions", "calls"]
            },
            {
                "id": "retention",
                "name": "Retention",
                "type": "followup",
                "description": "Follow up for repeat business",
                "channels": ["Email", "SMS"],
                "icon": "fa-heart",
                "metrics": ["repeat_rate", "reviews"]
            }
        ]
    },
    "emergency_service": {
        "name": "Emergency Service Response",
        "description": "Quick response for urgent needs",
        "icon": "fa-bolt",
        "color": "red",
        "stages": [
            {
                "id": "emergency",
                "name": "Emergency Search",
                "type": "ad",
                "description": "Customer has urgent need",
                "channels": ["Google Ads (24/7)", "Local Services Ads"],
                "icon": "fa-magnifying-glass",
                "metrics": ["impressions", "position"]
            },
            {
                "id": "quick_contact",
                "name": "Quick Contact",
                "type": "action",
                "description": "Customer calls immediately",
                "channels": ["Click-to-Call", "Call Extension"],
                "icon": "fa-phone-volume",
                "metrics": ["calls", "answer_rate"]
            },
            {
                "id": "dispatch",
                "name": "Dispatch",
                "type": "service",
                "description": "Technician dispatched",
                "channels": ["SMS Confirmation"],
                "icon": "fa-truck",
                "metrics": ["response_time"]
            },
            {
                "id": "service",
                "name": "Service Complete",
                "type": "action",
                "description": "Problem solved",
                "channels": ["On-site"],
                "icon": "fa-wrench",
                "metrics": ["completion_rate"]
            },
            {
                "id": "review_request",
                "name": "Review Request",
                "type": "followup",
                "description": "Ask for Google review",
                "channels": ["SMS", "Email"],
                "icon": "fa-star",
                "metrics": ["review_rate", "avg_rating"]
            }
        ]
    },
    "seasonal_promo": {
        "name": "Seasonal Promotion",
        "description": "Drive bookings during peak season",
        "icon": "fa-calendar",
        "color": "green",
        "stages": [
            {
                "id": "announce",
                "name": "Announce Offer",
                "type": "ad",
                "description": "Promote seasonal deal",
                "channels": ["Email Blast", "Social Media", "Google Ads"],
                "icon": "fa-bullhorn",
                "metrics": ["reach", "opens"]
            },
            {
                "id": "engage",
                "name": "Engage",
                "type": "landing",
                "description": "Special landing page",
                "channels": ["Promo Page"],
                "icon": "fa-gift",
                "metrics": ["visits", "bounce_rate"]
            },
            {
                "id": "book",
                "name": "Book Appointment",
                "type": "action",
                "description": "Customer schedules service",
                "channels": ["Online Booking", "Phone"],
                "icon": "fa-calendar-check",
                "metrics": ["bookings", "conversion_rate"]
            },
            {
                "id": "remind",
                "name": "Reminder",
                "type": "nurture",
                "description": "Appointment reminder",
                "channels": ["SMS", "Email"],
                "icon": "fa-bell",
                "metrics": ["show_rate"]
            },
            {
                "id": "upsell",
                "name": "Upsell",
                "type": "followup",
                "description": "Offer maintenance plan",
                "channels": ["On-site", "Email"],
                "icon": "fa-arrow-up",
                "metrics": ["upsell_rate", "aov"]
            }
        ]
    },
    "review_generation": {
        "name": "Review Generation",
        "description": "Get more 5-star reviews",
        "icon": "fa-star",
        "color": "yellow",
        "stages": [
            {
                "id": "complete_service",
                "name": "Complete Service",
                "type": "service",
                "description": "Finish job successfully",
                "channels": ["On-site"],
                "icon": "fa-check-circle",
                "metrics": ["satisfaction_score"]
            },
            {
                "id": "immediate_ask",
                "name": "Immediate Ask",
                "type": "action",
                "description": "Tech asks for review",
                "channels": ["In-person"],
                "icon": "fa-comment",
                "metrics": ["ask_rate"]
            },
            {
                "id": "text_followup",
                "name": "Text Follow-up",
                "type": "followup",
                "description": "Send review link via SMS",
                "channels": ["SMS"],
                "icon": "fa-mobile",
                "metrics": ["click_rate"]
            },
            {
                "id": "email_reminder",
                "name": "Email Reminder",
                "type": "followup",
                "description": "2nd reminder if no response",
                "channels": ["Email"],
                "icon": "fa-envelope",
                "metrics": ["open_rate"]
            },
            {
                "id": "review_received",
                "name": "Review Received",
                "type": "action",
                "description": "Customer leaves review",
                "channels": ["Google", "Facebook"],
                "icon": "fa-star",
                "metrics": ["review_rate", "avg_rating"]
            }
        ]
    }
}


def get_journey_templates() -> Dict[str, Dict[str, Any]]:
    """Get all journey templates."""
    return JOURNEY_TEMPLATES


def get_account_journeys(aid: int) -> List[Dict[str, Any]]:
    """Get saved journeys for an account."""
    try:
        with db.engine.connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT id, name, template_key, config, is_active, created_at
                    FROM marketing_journeys
                    WHERE account_id = :aid
                    ORDER BY created_at DESC
                """),
                {"aid": aid}
            ).mappings().all()
            return [dict(r) for r in rows]
    except Exception as e:
        current_app.logger.error(f"Error fetching journeys: {e}")
        return []


# -------------------- Routes --------------------

@journey_bp.route("/", methods=["GET"])
@login_required
def index():
    """Journey builder main page."""
    aid = current_account_id()
    if not aid:
        return redirect(url_for("account_bp.dashboard"))

    templates = get_journey_templates()
    saved_journeys = get_account_journeys(aid)

    return render_template(
        "journey_builder/index.html",
        templates=templates,
        saved_journeys=saved_journeys,
        is_paid=is_paid_account()
    )


@journey_bp.route("/view/<template_key>", methods=["GET"])
@login_required
def view_template(template_key: str):
    """View a specific journey template."""
    template = JOURNEY_TEMPLATES.get(template_key)
    if not template:
        flash("Journey template not found.", "error")
        return redirect(url_for("journey_bp.index"))

    return render_template(
        "journey_builder/view.html",
        template=template,
        template_key=template_key,
        is_paid=is_paid_account()
    )


@journey_bp.route("/api/templates", methods=["GET"])
@login_required
def api_templates():
    """Get all journey templates via API."""
    return jsonify(JOURNEY_TEMPLATES)


@journey_bp.route("/api/template/<template_key>", methods=["GET"])
@login_required
def api_template(template_key: str):
    """Get a specific template via API."""
    template = JOURNEY_TEMPLATES.get(template_key)
    if not template:
        return jsonify({"error": "Template not found"}), 404
    return jsonify(template)
