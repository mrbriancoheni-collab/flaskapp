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
    """
    try:
        data = request.get_json()
        price_id = data.get("price_id")
        plan_type = data.get("plan_type")  # 'monthly' or 'annual'
        success_url = data.get("success_url", f"{request.host_url}account/dashboard?upgrade=success")
        cancel_url = data.get("cancel_url", f"{request.host_url}pricing")

        if not price_id:
            return jsonify({"error": "price_id is required"}), 400

        # Initialize Stripe with secret key
        stripe_secret = current_app.config.get("STRIPE_SECRET_KEY") or os.getenv("STRIPE_SECRET_KEY")
        if not stripe_secret:
            return jsonify({"error": "Stripe not configured"}), 500

        stripe.api_key = stripe_secret

        # Get customer email
        customer_email = None
        if current_user and current_user.is_authenticated:
            customer_email = current_user.email

        # Create Stripe Checkout Session
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price": price_id,
                "quantity": 1,
            }],
            mode="subscription",
            success_url=success_url,
            cancel_url=cancel_url,
            customer_email=customer_email,
            metadata={
                "user_id": current_user.id if current_user and current_user.is_authenticated else None,
                "account_id": current_user.account_id if current_user and current_user.is_authenticated else None,
                "plan_type": plan_type,
            },
            allow_promotion_codes=True,
        )

        return jsonify({
            "checkout_url": checkout_session.url,
            "session_id": checkout_session.id
        })

    except stripe.error.StripeError as e:
        current_app.logger.error(f"Stripe error: {e}")
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        current_app.logger.error(f"Error creating checkout session: {e}")
        return jsonify({"error": "Failed to create checkout session"}), 500

