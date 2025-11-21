# app/billing/routes.py
from __future__ import annotations
from flask import Blueprint, render_template, request, jsonify, current_app
from app.auth.session_helpers import login_required, current_user
import stripe
import os

billing_bp = Blueprint("billing", __name__, url_prefix="/billing")

@billing_bp.route("/choose")
@login_required
def choose_plan():
    # You can replace with live plan data pulled from Stripe
    plans = [
        {"id": "free", "name": "Free", "price": 0, "benefits": ["Basic listing sync"]},
        {"id": "monthly", "name": "Growth (Monthly)", "price": 99, "benefits": [
            "AI campaign suggestions", "Lead quality insights", "A/B creative tips"
        ]},
        {"id": "annual", "name": "Growth (Annual)", "price": 999, "benefits": [
            "Everything in Monthly", "2 months free"
        ]},
    ]
    return render_template("billing/choose_plan.html", plans=plans)


@billing_bp.route("/create-checkout-session", methods=["POST"])
def create_checkout_session():
    """
    Create a Stripe Checkout session for upgrading to a paid plan.
    Called from pricing modal.

    Optimization: Uses centralized stripe_service instead of duplicating logic.
    """
    try:
        data = request.get_json()
        price_id = data.get("price_id")
        plan_type = data.get("plan_type")  # 'monthly' or 'annual'

        if not price_id:
            return jsonify({"error": "price_id is required"}), 400

        # Check authentication
        if not current_user or not current_user.is_authenticated:
            return jsonify({"error": "Authentication required"}), 401

        # Use centralized service (includes circuit breaker, monitoring, etc.)
        from app.services.stripe_service import create_subscription

        # Override success/cancel URLs if provided
        if data.get("success_url"):
            original_url = current_app.config.get("STRIPE_SUCCESS_URL")
            current_app.config["STRIPE_SUCCESS_URL"] = data.get("success_url")

        if data.get("cancel_url"):
            original_cancel = current_app.config.get("STRIPE_CANCEL_URL")
            current_app.config["STRIPE_CANCEL_URL"] = data.get("cancel_url")

        try:
            _, checkout_url = create_subscription(
                user_id=str(current_user.id),
                price_id=price_id,
                email=current_user.email,
                name=current_user.name if hasattr(current_user, 'name') else None
            )
        finally:
            # Restore original URLs
            if data.get("success_url"):
                current_app.config["STRIPE_SUCCESS_URL"] = original_url
            if data.get("cancel_url"):
                current_app.config["STRIPE_CANCEL_URL"] = original_cancel

        return jsonify({
            "checkout_url": checkout_url,
            "session_id": None  # Not needed for redirect
        })

    except ValueError as e:
        current_app.logger.error(f"Configuration error: {e}")
        return jsonify({"error": "Stripe not configured properly"}), 500
    except stripe.error.StripeError as e:
        current_app.logger.error(f"Stripe error: {e}")
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        current_app.logger.error(f"Error creating checkout session: {e}", exc_info=True)
        return jsonify({"error": "Failed to create checkout session"}), 500

