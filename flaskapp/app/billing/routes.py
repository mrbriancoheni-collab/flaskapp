# app/billing/routes.py
from __future__ import annotations
from flask import Blueprint, render_template, request, jsonify, current_app, flash, redirect, url_for, g
from app.auth.session_utils import login_required
from app.services.stripe_service import (
    create_subscription,
    upgrade_subscription,
    cancel_subscription,
    reactivate_subscription,
    get_or_create_stripe_customer
)
from app.models_billing import Subscription, StripeCustomer
from app.models import User
from app import db

billing_bp = Blueprint("billing", __name__, url_prefix="/billing")

@billing_bp.route("/choose")
@login_required
def choose_plan():
    """Display available subscription plans."""
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

    # Get user's current subscription if any
    user_subscription = None
    if g.user:
        user_subscription = Subscription.query.filter_by(
            user_id=str(g.user.id)
        ).filter(
            Subscription.status.in_(["active", "trialing"])
        ).first()

    return render_template("billing/choose_plan.html", plans=plans, current_subscription=user_subscription)


@billing_bp.route("/subscribe", methods=["POST"])
@login_required
def subscribe():
    """Create a new subscription (redirects to Stripe Checkout)."""
    price_id = request.form.get("price_id")
    plan_type = request.form.get("plan_type", "monthly")  # monthly or annual

    if not price_id:
        # Use configured price IDs based on plan type
        if plan_type == "annual":
            price_id = current_app.config.get("STRIPE_YEARLY_PRICE_ID")
        else:
            price_id = current_app.config.get("STRIPE_MONTHLY_PRICE_ID")

    if not price_id:
        flash("Invalid plan selected", "error")
        return redirect(url_for("billing.choose_plan"))

    try:
        # Get user details
        user = g.user
        user_id = str(user.id)
        email = user.email
        name = f"{user.first_name} {user.last_name}" if hasattr(user, 'first_name') else user.email

        # Create subscription (returns checkout URL)
        _, checkout_url = create_subscription(
            user_id=user_id,
            price_id=price_id,
            email=email,
            name=name,
            trial_days=request.form.get("trial_days", None)
        )

        return redirect(checkout_url)

    except Exception as e:
        current_app.logger.error(f"Error creating subscription: {e}", exc_info=True)
        flash("Failed to create subscription. Please try again.", "error")
        return redirect(url_for("billing.choose_plan"))


@billing_bp.route("/upgrade", methods=["POST"])
@login_required
def upgrade():
    """Upgrade or change subscription to a different plan."""
    new_price_id = request.form.get("price_id")
    subscription_id = request.form.get("subscription_id")

    if not new_price_id or not subscription_id:
        return jsonify({"error": "Missing price_id or subscription_id"}), 400

    try:
        # Verify subscription belongs to user
        sub = Subscription.query.filter_by(
            stripe_subscription_id=subscription_id,
            user_id=str(g.user.id)
        ).first()

        if not sub:
            return jsonify({"error": "Subscription not found"}), 404

        # Perform upgrade
        updated_sub = upgrade_subscription(subscription_id, new_price_id, prorate=True)

        flash("Subscription upgraded successfully!", "success")
        return jsonify({
            "success": True,
            "subscription": {
                "id": updated_sub.stripe_subscription_id,
                "status": updated_sub.status,
                "price_id": updated_sub.price_id
            }
        })

    except Exception as e:
        current_app.logger.error(f"Error upgrading subscription: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@billing_bp.route("/cancel", methods=["POST"])
@login_required
def cancel():
    """Cancel subscription (at period end by default)."""
    subscription_id = request.form.get("subscription_id")
    immediate = request.form.get("immediate", "false").lower() == "true"

    if not subscription_id:
        return jsonify({"error": "Missing subscription_id"}), 400

    try:
        # Verify subscription belongs to user
        sub = Subscription.query.filter_by(
            stripe_subscription_id=subscription_id,
            user_id=str(g.user.id)
        ).first()

        if not sub:
            return jsonify({"error": "Subscription not found"}), 404

        # Cancel subscription
        updated_sub = cancel_subscription(subscription_id, immediate=immediate)

        if immediate:
            flash("Subscription canceled immediately.", "success")
        else:
            flash("Subscription will be canceled at the end of the current billing period.", "success")

        return jsonify({
            "success": True,
            "subscription": {
                "id": updated_sub.stripe_subscription_id,
                "status": updated_sub.status,
                "cancel_at_period_end": updated_sub.cancel_at_period_end
            }
        })

    except Exception as e:
        current_app.logger.error(f"Error canceling subscription: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@billing_bp.route("/reactivate", methods=["POST"])
@login_required
def reactivate():
    """Reactivate a subscription that's scheduled for cancellation."""
    subscription_id = request.form.get("subscription_id")

    if not subscription_id:
        return jsonify({"error": "Missing subscription_id"}), 400

    try:
        # Verify subscription belongs to user
        sub = Subscription.query.filter_by(
            stripe_subscription_id=subscription_id,
            user_id=str(g.user.id)
        ).first()

        if not sub:
            return jsonify({"error": "Subscription not found"}), 404

        # Reactivate subscription
        updated_sub = reactivate_subscription(subscription_id)

        flash("Subscription reactivated successfully!", "success")
        return jsonify({
            "success": True,
            "subscription": {
                "id": updated_sub.stripe_subscription_id,
                "status": updated_sub.status,
                "cancel_at_period_end": updated_sub.cancel_at_period_end
            }
        })

    except Exception as e:
        current_app.logger.error(f"Error reactivating subscription: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@billing_bp.route("/portal")
@login_required
def portal():
    """Display billing portal / subscription management page."""
    user_id = str(g.user.id)

    # Get user's subscriptions
    subscriptions = Subscription.query.filter_by(user_id=user_id).order_by(
        Subscription.created_at.desc()
    ).all()

    # Get Stripe customer
    customer = StripeCustomer.query.filter_by(user_id=user_id).first()

    # Get payment history
    payments = Payment.query.filter_by(user_id=user_id).order_by(
        Payment.created_at.desc()
    ).limit(10).all()

    return render_template(
        "billing/portal.html",
        subscriptions=subscriptions,
        customer=customer,
        payments=payments
    )
