# app/services/stripe_service.py
"""
Stripe subscription management and webhook handling service.

Provides:
- Webhook event processing for subscription lifecycle
- Subscription creation, upgrade, downgrade, and cancellation
- Customer management
- Payment processing and reconciliation
"""

import stripe
from flask import current_app
from typing import Optional, Dict, Any, Tuple
from datetime import datetime

from app import db
from app.models_billing import StripeCustomer, Subscription, Payment
from app.models import Account, User


def get_stripe_client() -> stripe:
    """Get configured Stripe client."""
    api_key = current_app.config.get("STRIPE_SECRET_KEY")
    if not api_key:
        raise ValueError("STRIPE_SECRET_KEY not configured")
    stripe.api_key = api_key
    return stripe


def get_or_create_stripe_customer(user_id: str, email: str, name: Optional[str] = None) -> StripeCustomer:
    """
    Get existing Stripe customer or create new one.

    Args:
        user_id: Internal user ID
        email: Customer email
        name: Customer name (optional)

    Returns:
        StripeCustomer model instance
    """
    from app.monitoring import start_span, add_breadcrumb

    # Check if customer already exists
    with start_span("db.query", "Check existing Stripe customer"):
        existing = StripeCustomer.query.filter_by(user_id=user_id).first()
        if existing:
            add_breadcrumb("Found existing Stripe customer", category="billing", data={"customer_id": existing.stripe_customer_id})
            return existing

    # Create new Stripe customer
    get_stripe_client()

    with start_span("stripe.api", "Create Stripe customer"):
        stripe_customer = stripe.Customer.create(
            email=email,
            name=name,
            metadata={"user_id": user_id}
        )

    # Save to database
    customer = StripeCustomer(
        user_id=user_id,
        stripe_customer_id=stripe_customer.id
    )

    with start_span("db.insert", "Save Stripe customer to database"):
        db.session.add(customer)
        db.session.commit()

    add_breadcrumb("Created new Stripe customer", category="billing", data={"customer_id": stripe_customer.id})
    current_app.logger.info(f"Created Stripe customer {stripe_customer.id} for user {user_id}")
    return customer


def create_subscription(
    user_id: str,
    price_id: str,
    email: str,
    name: Optional[str] = None,
    trial_days: Optional[int] = None
) -> Tuple[Subscription, str]:
    """
    Create a new subscription for a user.

    Args:
        user_id: Internal user ID
        price_id: Stripe price ID
        email: Customer email
        name: Customer name
        trial_days: Number of trial days (optional)

    Returns:
        Tuple of (Subscription model, Stripe Checkout Session URL)
    """
    get_stripe_client()
    customer = get_or_create_stripe_customer(user_id, email, name)

    # Create checkout session
    checkout_params = {
        "customer": customer.stripe_customer_id,
        "payment_method_types": ["card"],
        "line_items": [{
            "price": price_id,
            "quantity": 1,
        }],
        "mode": "subscription",
        "success_url": current_app.config.get("STRIPE_SUCCESS_URL", "/account/dashboard?payment=success"),
        "cancel_url": current_app.config.get("STRIPE_CANCEL_URL", "/account/dashboard?payment=cancelled"),
        "metadata": {"user_id": user_id}
    }

    if trial_days:
        checkout_params["subscription_data"] = {
            "trial_period_days": trial_days
        }

    session = stripe.checkout.Session.create(**checkout_params)

    current_app.logger.info(f"Created checkout session {session.id} for user {user_id}")
    return None, session.url  # Subscription will be created by webhook after payment


def upgrade_subscription(subscription_id: str, new_price_id: str, prorate: bool = True) -> Subscription:
    """
    Upgrade or change a subscription to a different price.

    Args:
        subscription_id: Stripe subscription ID
        new_price_id: New Stripe price ID
        prorate: Whether to prorate the charge (default True)

    Returns:
        Updated Subscription model
    """
    get_stripe_client()

    # Get current subscription from database
    sub = Subscription.query.filter_by(stripe_subscription_id=subscription_id).first()
    if not sub:
        raise ValueError(f"Subscription {subscription_id} not found")

    # Get Stripe subscription
    stripe_sub = stripe.Subscription.retrieve(subscription_id)

    # Update subscription item with new price
    stripe.Subscription.modify(
        subscription_id,
        items=[{
            "id": stripe_sub["items"]["data"][0].id,
            "price": new_price_id,
        }],
        proration_behavior="create_prorations" if prorate else "none"
    )

    # Update database
    sub.price_id = new_price_id
    sub.updated_at = datetime.utcnow()
    db.session.commit()

    current_app.logger.info(f"Upgraded subscription {subscription_id} to price {new_price_id}")
    return sub


def cancel_subscription(subscription_id: str, immediate: bool = False) -> Subscription:
    """
    Cancel a subscription.

    Args:
        subscription_id: Stripe subscription ID
        immediate: If True, cancel immediately. If False, cancel at period end.

    Returns:
        Updated Subscription model
    """
    get_stripe_client()

    sub = Subscription.query.filter_by(stripe_subscription_id=subscription_id).first()
    if not sub:
        raise ValueError(f"Subscription {subscription_id} not found")

    if immediate:
        # Cancel immediately
        stripe.Subscription.cancel(subscription_id)
        sub.status = "canceled"
        sub.cancel_at_period_end = False
    else:
        # Cancel at period end
        stripe.Subscription.modify(
            subscription_id,
            cancel_at_period_end=True
        )
        sub.cancel_at_period_end = True

    sub.updated_at = datetime.utcnow()
    db.session.commit()

    current_app.logger.info(
        f"Subscription {subscription_id} {'canceled immediately' if immediate else 'scheduled for cancellation'}"
    )
    return sub


def reactivate_subscription(subscription_id: str) -> Subscription:
    """
    Reactivate a subscription that's scheduled for cancellation.

    Args:
        subscription_id: Stripe subscription ID

    Returns:
        Updated Subscription model
    """
    get_stripe_client()

    sub = Subscription.query.filter_by(stripe_subscription_id=subscription_id).first()
    if not sub:
        raise ValueError(f"Subscription {subscription_id} not found")

    # Remove cancel_at_period_end flag
    stripe.Subscription.modify(
        subscription_id,
        cancel_at_period_end=False
    )

    sub.cancel_at_period_end = False
    sub.updated_at = datetime.utcnow()
    db.session.commit()

    current_app.logger.info(f"Reactivated subscription {subscription_id}")
    return sub


# ===== Webhook Event Handlers =====

def _notify_new_paying_customer(user_id: int, invoice: Dict[str, Any]):
    """
    Send email notification to team when a new paying customer signs up.

    Args:
        user_id: The user ID of the new paying customer
        invoice: The Stripe invoice data
    """
    try:
        from app.services.email_service import send_email

        # Get user details
        user = User.query.get(user_id)
        if not user:
            current_app.logger.error(f"User {user_id} not found for new customer notification")
            return

        # Get subscription details
        subscription = Subscription.query.filter_by(user_id=user_id).first()
        plan_name = "Unknown Plan"
        if subscription:
            # Try to get plan name from price_id
            if "monthly" in subscription.price_id.lower():
                plan_name = "Growth Monthly"
            elif "yearly" in subscription.price_id.lower() or "annual" in subscription.price_id.lower():
                plan_name = "Growth Annual"
            else:
                plan_name = subscription.price_id

        # Format amount
        amount_cents = invoice.get("amount_paid", 0)
        amount_dollars = amount_cents / 100
        currency = invoice.get("currency", "usd").upper()

        # Build email content
        subject = f"🎉 New Paying Customer: {user.name}"

        html_body = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f9fafb;">
    <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #f9fafb; padding: 40px 20px;">
        <tr>
            <td align="center">
                <table width="600" cellpadding="0" cellspacing="0" style="background-color: #ffffff; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1);">
                    <!-- Header -->
                    <tr>
                        <td style="padding: 40px 40px 20px 40px; text-align: center;">
                            <h1 style="margin: 0; font-size: 28px; color: #10b981;">🎉 New Paying Customer!</h1>
                        </td>
                    </tr>

                    <!-- Content -->
                    <tr>
                        <td style="padding: 20px 40px;">
                            <table width="100%" cellpadding="8" cellspacing="0" style="border-collapse: collapse;">
                                <tr>
                                    <td style="padding: 12px 0; border-bottom: 1px solid #e5e7eb;">
                                        <strong style="color: #374151;">Customer Name:</strong>
                                    </td>
                                    <td style="padding: 12px 0; border-bottom: 1px solid #e5e7eb; text-align: right; color: #111827;">
                                        {user.name}
                                    </td>
                                </tr>
                                <tr>
                                    <td style="padding: 12px 0; border-bottom: 1px solid #e5e7eb;">
                                        <strong style="color: #374151;">Email:</strong>
                                    </td>
                                    <td style="padding: 12px 0; border-bottom: 1px solid #e5e7eb; text-align: right; color: #111827;">
                                        {user.email}
                                    </td>
                                </tr>
                                <tr>
                                    <td style="padding: 12px 0; border-bottom: 1px solid #e5e7eb;">
                                        <strong style="color: #374151;">Plan:</strong>
                                    </td>
                                    <td style="padding: 12px 0; border-bottom: 1px solid #e5e7eb; text-align: right; color: #111827;">
                                        {plan_name}
                                    </td>
                                </tr>
                                <tr>
                                    <td style="padding: 12px 0; border-bottom: 1px solid #e5e7eb;">
                                        <strong style="color: #374151;">Payment Amount:</strong>
                                    </td>
                                    <td style="padding: 12px 0; border-bottom: 1px solid #e5e7eb; text-align: right; color: #10b981; font-size: 18px; font-weight: bold;">
                                        ${amount_dollars:.2f} {currency}
                                    </td>
                                </tr>
                                <tr>
                                    <td style="padding: 12px 0; border-bottom: 1px solid #e5e7eb;">
                                        <strong style="color: #374151;">Invoice ID:</strong>
                                    </td>
                                    <td style="padding: 12px 0; border-bottom: 1px solid #e5e7eb; text-align: right; color: #6b7280; font-size: 14px;">
                                        {invoice.get('id', 'N/A')}
                                    </td>
                                </tr>
                                <tr>
                                    <td style="padding: 12px 0;">
                                        <strong style="color: #374151;">Account Created:</strong>
                                    </td>
                                    <td style="padding: 12px 0; text-align: right; color: #6b7280;">
                                        {user.created_at.strftime('%B %d, %Y at %I:%M %p') if user.created_at else 'N/A'}
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>

                    <!-- Footer -->
                    <tr>
                        <td style="padding: 30px 40px; text-align: center; background-color: #f9fafb; border-radius: 0 0 8px 8px;">
                            <p style="margin: 0 0 10px 0; font-size: 14px; color: #6b7280;">
                                This is an automated notification from FieldSprout.
                            </p>
                            <p style="margin: 0; font-size: 12px; color: #9ca3af;">
                                © 2025 FieldSprout. All rights reserved.
                            </p>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>
        """

        text_body = f"""
🎉 New Paying Customer!

Customer Name: {user.name}
Email: {user.email}
Plan: {plan_name}
Payment Amount: ${amount_dollars:.2f} {currency}
Invoice ID: {invoice.get('id', 'N/A')}
Account Created: {user.created_at.strftime('%B %d, %Y at %I:%M %p') if user.created_at else 'N/A'}

This is an automated notification from FieldSprout.
        """

        # Send to both email addresses
        notification_emails = [
            "hi@fieldsprout.io",
            "mrbriancoheni@gmail.com"
        ]

        for email in notification_emails:
            try:
                send_email(
                    to=email,
                    subject=subject,
                    html_body=html_body,
                    text_body=text_body,
                    use_bulk_credentials=True
                )
                current_app.logger.info(f"Sent new paying customer notification to {email}")
            except Exception as e:
                current_app.logger.error(f"Failed to send notification to {email}: {e}", exc_info=True)

    except Exception as e:
        current_app.logger.error(f"Error in _notify_new_paying_customer: {e}", exc_info=True)


def handle_customer_subscription_created(event_data: Dict[str, Any]):
    """Handle customer.subscription.created webhook event."""
    stripe_sub = event_data["object"]

    # Extract data
    user_id = stripe_sub.get("metadata", {}).get("user_id")
    if not user_id:
        # Try to get user_id from customer
        customer = StripeCustomer.query.filter_by(
            stripe_customer_id=stripe_sub["customer"]
        ).first()
        if customer:
            user_id = customer.user_id
        else:
            current_app.logger.warning(
                f"Cannot determine user_id for subscription {stripe_sub['id']}"
            )
            return

    # Check if subscription already exists
    existing = Subscription.query.filter_by(
        stripe_subscription_id=stripe_sub["id"]
    ).first()

    if existing:
        current_app.logger.info(f"Subscription {stripe_sub['id']} already exists, updating")
        _update_subscription_from_stripe(existing, stripe_sub)
    else:
        # Create new subscription
        sub = Subscription(
            user_id=user_id,
            stripe_customer_id=stripe_sub["customer"],
            stripe_subscription_id=stripe_sub["id"],
            price_id=stripe_sub["items"]["data"][0]["price"]["id"],
            status=stripe_sub["status"],
            current_period_end=datetime.fromtimestamp(stripe_sub["current_period_end"]),
            cancel_at_period_end=stripe_sub.get("cancel_at_period_end", False)
        )
        db.session.add(sub)
        db.session.commit()
        current_app.logger.info(f"Created subscription {stripe_sub['id']} for user {user_id}")


def handle_customer_subscription_updated(event_data: Dict[str, Any]):
    """Handle customer.subscription.updated webhook event."""
    stripe_sub = event_data["object"]

    sub = Subscription.query.filter_by(
        stripe_subscription_id=stripe_sub["id"]
    ).first()

    if not sub:
        current_app.logger.warning(f"Subscription {stripe_sub['id']} not found in database")
        # Try to create it
        handle_customer_subscription_created(event_data)
        return

    _update_subscription_from_stripe(sub, stripe_sub)


def handle_customer_subscription_deleted(event_data: Dict[str, Any]):
    """Handle customer.subscription.deleted webhook event."""
    stripe_sub = event_data["object"]

    sub = Subscription.query.filter_by(
        stripe_subscription_id=stripe_sub["id"]
    ).first()

    if sub:
        sub.status = "canceled"
        sub.updated_at = datetime.utcnow()
        db.session.commit()
        current_app.logger.info(f"Subscription {stripe_sub['id']} deleted/canceled")


def handle_invoice_paid(event_data: Dict[str, Any]):
    """Handle invoice.paid webhook event."""
    invoice = event_data["object"]

    # Get customer
    customer = StripeCustomer.query.filter_by(
        stripe_customer_id=invoice["customer"]
    ).first()

    if not customer:
        current_app.logger.warning(f"Customer {invoice['customer']} not found for invoice {invoice['id']}")
        return

    # Check if this is the first successful payment for this customer
    previous_payments = Payment.query.filter_by(
        user_id=customer.user_id,
        status="paid"
    ).count()

    is_new_paying_customer = (previous_payments == 0)

    # Record payment
    payment = Payment(
        user_id=customer.user_id,
        stripe_customer_id=invoice["customer"],
        invoice_id=invoice["id"],
        payment_intent_id=invoice.get("payment_intent"),
        amount=invoice["amount_paid"],
        currency=invoice["currency"],
        status="paid"
    )
    db.session.add(payment)
    db.session.commit()

    current_app.logger.info(f"Recorded payment for invoice {invoice['id']}, amount {invoice['amount_paid']}")

    # Send notification for new paying customers
    if is_new_paying_customer:
        _notify_new_paying_customer(customer.user_id, invoice)


def handle_invoice_payment_failed(event_data: Dict[str, Any]):
    """Handle invoice.payment_failed webhook event."""
    invoice = event_data["object"]

    customer = StripeCustomer.query.filter_by(
        stripe_customer_id=invoice["customer"]
    ).first()

    if customer:
        # Record failed payment
        payment = Payment(
            user_id=customer.user_id,
            stripe_customer_id=invoice["customer"],
            invoice_id=invoice["id"],
            payment_intent_id=invoice.get("payment_intent"),
            amount=invoice["amount_due"],
            currency=invoice["currency"],
            status="failed"
        )
        db.session.add(payment)
        db.session.commit()

        current_app.logger.warning(f"Payment failed for invoice {invoice['id']}")

        # TODO: Send email notification to customer


def _update_subscription_from_stripe(sub: Subscription, stripe_sub: Dict[str, Any]):
    """Helper to update Subscription model from Stripe subscription object."""
    sub.status = stripe_sub["status"]
    sub.price_id = stripe_sub["items"]["data"][0]["price"]["id"]
    sub.current_period_end = datetime.fromtimestamp(stripe_sub["current_period_end"])
    sub.cancel_at_period_end = stripe_sub.get("cancel_at_period_end", False)
    sub.updated_at = datetime.utcnow()
    db.session.commit()

    current_app.logger.info(f"Updated subscription {stripe_sub['id']}, status={stripe_sub['status']}")


# Event handler mapping
WEBHOOK_HANDLERS = {
    "customer.subscription.created": handle_customer_subscription_created,
    "customer.subscription.updated": handle_customer_subscription_updated,
    "customer.subscription.deleted": handle_customer_subscription_deleted,
    "invoice.paid": handle_invoice_paid,
    "invoice.payment_failed": handle_invoice_payment_failed,
}


def process_webhook_event(event: Dict[str, Any]) -> bool:
    """
    Process a Stripe webhook event.

    Args:
        event: Stripe event object

    Returns:
        True if event was handled, False if event type not recognized
    """
    event_type = event.get("type")
    handler = WEBHOOK_HANDLERS.get(event_type)

    if handler:
        current_app.logger.info(f"Processing webhook event: {event_type}")
        try:
            handler(event["data"])
            return True
        except Exception as e:
            current_app.logger.error(f"Error processing webhook event {event_type}: {e}", exc_info=True)
            raise
    else:
        current_app.logger.debug(f"No handler for webhook event: {event_type}")
        return False
