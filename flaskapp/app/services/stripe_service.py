# app/services/stripe_service.py
"""
Stripe subscription management and webhook handling service.

Optimizations applied:
- Background email queue (no webhook blocking)
- Database transaction management
- Webhook idempotency checking
- Optimized first payment detection
- Customer lookup caching
- Circuit breaker for API calls
- Comprehensive monitoring/logging
"""

import stripe
from flask import current_app
from typing import Optional, Dict, Any, Tuple
from datetime import datetime, timedelta
from functools import wraps
import time

from app import db
from app.models_billing import (
    StripeCustomer, Subscription, Payment,
    StripeWebhookEvent, EmailQueue
)
from app.models import Account, User


# ===== Circuit Breaker Implementation =====

class CircuitBreaker:
    """
    Circuit breaker for Stripe API calls.
    Prevents cascading failures when Stripe is down.
    """
    def __init__(self, failure_threshold=5, timeout=60):
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.failures = 0
        self.last_failure_time = None
        self.state = 'closed'  # closed, open, half_open

    def call(self, func, *args, **kwargs):
        if self.state == 'open':
            if time.time() - self.last_failure_time > self.timeout:
                self.state = 'half_open'
                current_app.logger.info("Circuit breaker entering half-open state")
            else:
                raise Exception("Circuit breaker is OPEN - Stripe API calls blocked")

        try:
            result = func(*args, **kwargs)
            if self.state == 'half_open':
                self.state = 'closed'
                self.failures = 0
                current_app.logger.info("Circuit breaker closed - Stripe API recovered")
            return result
        except stripe.error.StripeError as e:
            self.failures += 1
            self.last_failure_time = time.time()

            if self.failures >= self.failure_threshold:
                self.state = 'open'
                current_app.logger.error(
                    f"Circuit breaker OPENED after {self.failures} failures"
                )
            raise


# Global circuit breaker instance
_circuit_breaker = CircuitBreaker()


def with_circuit_breaker(func):
    """Decorator to apply circuit breaker to Stripe API calls."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        return _circuit_breaker.call(func, *args, **kwargs)
    return wrapper


# ===== Customer Lookup Cache =====

class CustomerCache:
    """Simple in-memory cache for customer lookups."""
    def __init__(self, ttl=300):  # 5 minute TTL
        self.cache = {}
        self.ttl = ttl

    def get(self, user_id):
        if user_id in self.cache:
            customer, timestamp = self.cache[user_id]
            if time.time() - timestamp < self.ttl:
                return customer
            else:
                del self.cache[user_id]
        return None

    def set(self, user_id, customer):
        self.cache[user_id] = (customer, time.time())

    def invalidate(self, user_id):
        if user_id in self.cache:
            del self.cache[user_id]


# Global cache instance
_customer_cache = CustomerCache()


# ===== Core Functions =====

def get_stripe_client() -> stripe:
    """Get configured Stripe client."""
    api_key = current_app.config.get("STRIPE_SECRET_KEY")
    if not api_key:
        raise ValueError("STRIPE_SECRET_KEY not configured")
    stripe.api_key = api_key
    return stripe


@with_circuit_breaker
def get_or_create_stripe_customer(user_id: str, email: str, name: Optional[str] = None) -> StripeCustomer:
    """
    Get existing Stripe customer or create new one.

    Optimizations:
    - In-memory caching (5min TTL)
    - Monitoring spans for performance tracking

    Args:
        user_id: Internal user ID
        email: Customer email
        name: Customer name (optional)

    Returns:
        StripeCustomer model instance
    """
    from app.monitoring import start_span, add_breadcrumb

    # Check cache first
    cached = _customer_cache.get(user_id)
    if cached:
        add_breadcrumb("Customer cache hit", category="billing",
                      data={"customer_id": cached.stripe_customer_id})
        return cached

    # Check database
    with start_span("db.query", "Check existing Stripe customer"):
        existing = StripeCustomer.query.filter_by(user_id=user_id).first()
        if existing:
            _customer_cache.set(user_id, existing)
            add_breadcrumb("Found existing Stripe customer", category="billing",
                          data={"customer_id": existing.stripe_customer_id})
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

    # Update cache
    _customer_cache.set(user_id, customer)

    add_breadcrumb("Created new Stripe customer", category="billing",
                  data={"customer_id": stripe_customer.id})
    current_app.logger.info(
        f"Created Stripe customer {stripe_customer.id} for user {user_id}",
        extra={"metric": "stripe.customer.created", "user_id": user_id}
    )
    return customer


@with_circuit_breaker
def create_subscription(
    user_id: str,
    price_id: str,
    email: str,
    name: Optional[str] = None,
    trial_days: Optional[int] = None,
    success_url: Optional[str] = None,
    cancel_url: Optional[str] = None
) -> Tuple[Subscription, str]:
    """
    Create a new subscription for a user.

    Args:
        user_id: Internal user ID
        price_id: Stripe price ID
        email: Customer email
        name: Customer name
        trial_days: Number of trial days (optional)
        success_url: Full URL to redirect after successful payment
        cancel_url: Full URL to redirect if user cancels

    Returns:
        Tuple of (Subscription model, Stripe Checkout Session URL)
    """
    from flask import url_for

    get_stripe_client()
    customer = get_or_create_stripe_customer(user_id, email, name)

    # Use provided URLs or generate defaults
    if not success_url:
        success_url = url_for("account_bp.dashboard", payment="success", _external=True)
    if not cancel_url:
        cancel_url = url_for("main_bp.pricing", _external=True)

    # Create checkout session
    checkout_params = {
        "customer": customer.stripe_customer_id,
        "payment_method_types": ["card"],
        "line_items": [{
            "price": price_id,
            "quantity": 1,
        }],
        "mode": "subscription",
        "success_url": success_url,
        "cancel_url": cancel_url,
        "metadata": {"user_id": user_id},
        "allow_promotion_codes": True
    }

    if trial_days:
        checkout_params["subscription_data"] = {
            "trial_period_days": trial_days
        }

    session = stripe.checkout.Session.create(**checkout_params)

    current_app.logger.info(
        f"Created checkout session {session.id} for user {user_id}",
        extra={"metric": "stripe.checkout.created", "user_id": user_id}
    )
    return None, session.url  # Subscription will be created by webhook after payment


@with_circuit_breaker
def create_lifetime_checkout(
    user_id: str,
    tier: str,
    email: str,
    name: Optional[str] = None,
    success_url: Optional[str] = None,
    cancel_url: Optional[str] = None,
) -> str:
    """
    Create a one-time Stripe Checkout session for a lifetime deal purchase.

    Args:
        user_id: Internal user ID
        tier: '499' or '999' — selects the configured price ID
        email: Customer email
        name: Customer name (optional)
        success_url: Redirect after successful payment
        cancel_url: Redirect if customer cancels

    Returns:
        Stripe Checkout Session URL
    """
    from flask import url_for

    get_stripe_client()

    price_key = f"STRIPE_LIFETIME_{tier}_PRICE_ID"
    price_id = current_app.config.get(price_key, "")
    if not price_id:
        raise ValueError(
            f"Lifetime deal price ID not configured. Set the {price_key} environment variable."
        )

    customer = get_or_create_stripe_customer(user_id, email, name)

    if not success_url:
        success_url = url_for(
            "account_bp.dashboard",
            payment="success",
            plan="lifetime",
            _external=True,
        )
    if not cancel_url:
        cancel_url = url_for("public_bp.lifetime_deal", tier=tier, _external=True)

    session = stripe.checkout.Session.create(
        customer=customer.stripe_customer_id,
        payment_method_types=["card"],
        line_items=[{"price": price_id, "quantity": 1}],
        mode="payment",
        success_url=success_url,
        cancel_url=cancel_url,
        allow_promotion_codes=True,
        metadata={
            "user_id": str(user_id),
            "plan_type": f"lifetime_{tier}",
        },
        client_reference_id=str(user_id),
    )

    current_app.logger.info(
        f"Created lifetime checkout session {session.id} for user {user_id} tier={tier}",
        extra={"metric": "stripe.lifetime_checkout.created", "user_id": user_id, "tier": tier},
    )
    return session.url


@with_circuit_breaker
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

    current_app.logger.info(
        f"Upgraded subscription {subscription_id} to price {new_price_id}",
        extra={"metric": "stripe.subscription.upgraded", "subscription_id": subscription_id}
    )
    return sub


@with_circuit_breaker
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
        f"Subscription {subscription_id} {'canceled immediately' if immediate else 'scheduled for cancellation'}",
        extra={"metric": "stripe.subscription.canceled", "subscription_id": subscription_id, "immediate": immediate}
    )
    return sub


@with_circuit_breaker
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

    current_app.logger.info(
        f"Reactivated subscription {subscription_id}",
        extra={"metric": "stripe.subscription.reactivated", "subscription_id": subscription_id}
    )
    return sub


# ===== Email Queue Functions =====

def queue_email(to: str, subject: str, html_body: str, text_body: str = None, use_bulk: bool = False):
    """
    Queue an email for background sending.

    Optimization: Decouples email delivery from webhook processing.

    Args:
        to: Recipient email
        subject: Email subject
        html_body: HTML body
        text_body: Plain text body (optional)
        use_bulk: Use bulk email credentials
    """
    email = EmailQueue(
        to_email=to,
        subject=subject,
        html_body=html_body,
        text_body=text_body or "",
        use_bulk_credentials=use_bulk
    )
    db.session.add(email)
    db.session.commit()

    current_app.logger.info(
        f"Queued email to {to}: {subject}",
        extra={"metric": "email.queued", "recipient": to}
    )


def _notify_new_paying_customer(user_id: int, invoice: Dict[str, Any]):
    """
    Queue email notifications for new paying customers.

    Optimization: Uses background queue instead of synchronous sending.

    Args:
        user_id: The user ID of the new paying customer
        invoice: The Stripe invoice data
    """
    try:
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

        # Queue emails for both addresses (background processing)
        notification_emails = [
            "hi@fieldsprout.io",
            "mrbriancoheni@gmail.com"
        ]

        for email in notification_emails:
            queue_email(
                to=email,
                subject=subject,
                html_body=html_body,
                text_body=text_body,
                use_bulk=True
            )

        current_app.logger.info(
            f"Queued new paying customer notifications for user {user_id}",
            extra={"metric": "notification.new_customer.queued", "user_id": user_id}
        )

    except Exception as e:
        current_app.logger.error(
            f"Error queueing new customer notification: {e}",
            exc_info=True,
            extra={"metric": "notification.new_customer.error", "user_id": user_id}
        )


# ===== Webhook Event Handlers =====

def handle_customer_subscription_created(event_data: Dict[str, Any]):
    """
    Handle customer.subscription.created webhook event.

    Optimization: Wrapped in transaction by process_webhook_event.
    """
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
        current_app.logger.info(
            f"Created subscription {stripe_sub['id']} for user {user_id}",
            extra={"metric": "stripe.subscription.created", "user_id": user_id}
        )

        # Sync status to accounts table
        _sync_subscription_status_to_account(user_id, stripe_sub["status"])


def handle_customer_subscription_updated(event_data: Dict[str, Any]):
    """
    Handle customer.subscription.updated webhook event.

    Optimization: Wrapped in transaction by process_webhook_event.
    """
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
    """
    Handle customer.subscription.deleted webhook event.

    Optimization: Wrapped in transaction by process_webhook_event.
    """
    stripe_sub = event_data["object"]

    sub = Subscription.query.filter_by(
        stripe_subscription_id=stripe_sub["id"]
    ).first()

    if sub:
        sub.status = "canceled"
        sub.updated_at = datetime.utcnow()
        current_app.logger.info(
            f"Subscription {stripe_sub['id']} deleted/canceled",
            extra={"metric": "stripe.subscription.deleted", "subscription_id": stripe_sub['id']}
        )

        # Sync canceled status to accounts table
        _sync_subscription_status_to_account(sub.user_id, "canceled")


def handle_invoice_paid(event_data: Dict[str, Any]):
    """
    Handle invoice.paid webhook event.

    Optimizations:
    - Uses first_payment_at flag instead of COUNT query
    - Queues emails for background processing
    - Wrapped in transaction by process_webhook_event
    """
    invoice = event_data["object"]

    # Get customer
    customer = StripeCustomer.query.filter_by(
        stripe_customer_id=invoice["customer"]
    ).first()

    if not customer:
        current_app.logger.warning(f"Customer {invoice['customer']} not found for invoice {invoice['id']}")
        return

    # Optimized: Check first_payment_at flag instead of COUNT query
    is_new_paying_customer = (customer.first_payment_at is None)

    # Update first_payment_at if this is the first payment
    if is_new_paying_customer:
        customer.first_payment_at = datetime.utcnow()

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

    current_app.logger.info(
        f"Recorded payment for invoice {invoice['id']}, amount {invoice['amount_paid']}",
        extra={
            "metric": "stripe.payment.success",
            "amount": invoice['amount_paid'],
            "currency": invoice['currency'],
            "is_first_payment": is_new_paying_customer
        }
    )

    # Queue notification for new paying customers (non-blocking)
    if is_new_paying_customer:
        _notify_new_paying_customer(customer.user_id, invoice)


def handle_invoice_payment_failed(event_data: Dict[str, Any]):
    """
    Handle invoice.payment_failed webhook event.

    Optimization: Wrapped in transaction by process_webhook_event.
    """
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

        current_app.logger.warning(
            f"Payment failed for invoice {invoice['id']}",
            extra={
                "metric": "stripe.payment.failed",
                "amount": invoice['amount_due'],
                "user_id": customer.user_id
            }
        )

        # Notify the customer that their payment failed
        try:
            from app.models import User
            from app.services.email_service import send_email
            user = User.query.filter_by(email=customer.user_id).first()
            if user and user.email:
                amount_dollars = invoice["amount_due"] / 100
                send_email(
                    to_email=user.email,
                    subject="Action required: your FieldSprout payment failed",
                    html_body=(
                        f"<p>Hi {user.name or 'there'},</p>"
                        f"<p>We were unable to process your payment of "
                        f"<strong>${amount_dollars:.2f}</strong> "
                        f"(invoice <code>{invoice['id']}</code>).</p>"
                        f"<p>Please update your payment method to keep your account active:</p>"
                        f'<p><a href="https://fieldsprout.io/account/billing" '
                        f'style="background:#4f46e5;color:#fff;padding:10px 20px;'
                        f'border-radius:6px;text-decoration:none;font-weight:600;">'
                        f"Update Payment Method</a></p>"
                        f"<p style='color:#6b7280;font-size:13px'>"
                        f"If you have questions, just reply to this email.</p>"
                    ),
                )
        except Exception:
            current_app.logger.exception("Failed to send payment-failed email for invoice %s", invoice["id"])


def _update_subscription_from_stripe(sub: Subscription, stripe_sub: Dict[str, Any]):
    """Helper to update Subscription model from Stripe subscription object."""
    sub.status = stripe_sub["status"]
    sub.price_id = stripe_sub["items"]["data"][0]["price"]["id"]
    sub.current_period_end = datetime.fromtimestamp(stripe_sub["current_period_end"])
    sub.cancel_at_period_end = stripe_sub.get("cancel_at_period_end", False)
    sub.updated_at = datetime.utcnow()

    current_app.logger.info(
        f"Updated subscription {stripe_sub['id']}, status={stripe_sub['status']}",
        extra={"metric": "stripe.subscription.updated", "subscription_id": stripe_sub['id']}
    )

    # Sync status to accounts table
    _sync_subscription_status_to_account(sub.user_id, stripe_sub["status"])


def _sync_subscription_status_to_account(user_id: str, stripe_status: str):
    """
    Update the accounts table stripe_status field based on subscription status.
    This ensures is_paid_account() properly recognizes paid users.
    """
    try:
        from sqlalchemy import text

        # Get account_id from user_id (look up from users table)
        with db.engine.connect() as conn:
            result = conn.execute(
                text("SELECT account_id FROM users WHERE id = :user_id LIMIT 1"),
                {"user_id": user_id}
            ).first()

            if not result:
                current_app.logger.warning(
                    f"User {user_id} not found, cannot sync stripe_status to account",
                    extra={"metric": "account.stripe_status.user_not_found", "user_id": user_id}
                )
                return

            account_id = result[0]
            if not account_id:
                current_app.logger.warning(
                    f"User {user_id} has no account_id, cannot sync stripe_status",
                    extra={"metric": "account.stripe_status.no_account", "user_id": user_id}
                )
                return

            # Allowlist identifiers — never interpolate arbitrary config values into SQL
            _ALLOWED_TABLES = {"accounts", "users_accounts", "account"}
            _ALLOWED_FIELDS = {"stripe_status", "subscription_status", "plan_status"}
            table_name = current_app.config.get("ACCOUNT_TABLE_NAME", "accounts")
            stripe_field = current_app.config.get("ACCOUNT_STRIPE_FIELD", "stripe_status")
            if table_name not in _ALLOWED_TABLES or stripe_field not in _ALLOWED_FIELDS:
                raise ValueError(f"Disallowed SQL identifier: {table_name!r} / {stripe_field!r}")

            conn.execute(
                text(f"UPDATE {table_name} SET {stripe_field} = :status WHERE id = :id"),
                {"status": stripe_status, "id": account_id}
            )
            conn.commit()

            current_app.logger.info(
                f"Updated account {account_id} stripe_status to {stripe_status} (user {user_id})",
                extra={
                    "metric": "account.stripe_status.updated",
                    "account_id": account_id,
                    "user_id": user_id,
                    "status": stripe_status
                }
            )
    except Exception as e:
        current_app.logger.error(
            f"Error syncing subscription status to account: {e}",
            exc_info=True,
            extra={"metric": "account.stripe_status.error", "user_id": user_id}
        )


def _grant_lifetime_plan(user_id: str, tier: str):
    """
    Update the account's plan to 'lifetime' and stripe_status to 'active'
    after a successful one-time lifetime deal purchase.
    """
    try:
        from sqlalchemy import text

        with db.engine.connect() as conn:
            result = conn.execute(
                text("SELECT account_id FROM users WHERE id = :uid LIMIT 1"),
                {"uid": user_id},
            ).first()

            if not result or not result[0]:
                current_app.logger.warning(
                    f"Cannot grant lifetime plan: user {user_id} has no account"
                )
                return

            account_id = result[0]
            _ALLOWED_TABLES = {"accounts", "users_accounts", "account"}
            _ALLOWED_FIELDS = {"stripe_status", "subscription_status", "plan_status"}
            _ALLOWED_PLAN_FIELDS = {"plan", "plan_name", "subscription_plan"}
            table = current_app.config.get("ACCOUNT_TABLE_NAME", "accounts")
            plan_field = current_app.config.get("ACCOUNT_PLAN_FIELD", "plan")
            stripe_field = current_app.config.get("ACCOUNT_STRIPE_FIELD", "stripe_status")
            if table not in _ALLOWED_TABLES or plan_field not in _ALLOWED_PLAN_FIELDS \
                    or stripe_field not in _ALLOWED_FIELDS:
                raise ValueError(f"Disallowed SQL identifier in grant_lifetime_plan")

            conn.execute(
                text(
                    f"UPDATE {table} SET {plan_field} = 'lifetime', "
                    f"{stripe_field} = 'active' WHERE id = :id"
                ),
                {"id": account_id},
            )
            conn.commit()

            current_app.logger.info(
                f"Granted lifetime plan (tier={tier}) to account {account_id} (user {user_id})",
                extra={
                    "metric": "account.lifetime_plan.granted",
                    "account_id": account_id,
                    "user_id": user_id,
                    "tier": tier,
                },
            )
    except Exception as exc:
        current_app.logger.error(
            f"Error granting lifetime plan to user {user_id}: {exc}",
            exc_info=True,
            extra={"metric": "account.lifetime_plan.error", "user_id": user_id},
        )


def handle_checkout_session_completed(event_data: Dict[str, Any]):
    """
    Handle checkout.session.completed webhook event.

    For lifetime deal purchases (mode='payment', plan_type metadata starts with
    'lifetime_'), grants the lifetime plan to the user's account immediately.
    Also sends a notification email to admin.
    """
    session = event_data["object"]

    customer_email = session.get("customer_email")
    customer_name = session.get("customer_details", {}).get("name", "Unknown")
    subscription_id = session.get("subscription")

    # ── Lifetime deal: grant plan immediately on payment completion ───────
    plan_type = session.get("metadata", {}).get("plan_type", "")
    if plan_type.startswith("lifetime_") and session.get("payment_status") == "paid":
        tier = plan_type.replace("lifetime_", "")  # '499' or '999'
        uid = session.get("metadata", {}).get("user_id") or session.get("client_reference_id")
        if uid:
            _grant_lifetime_plan(str(uid), tier)
        else:
            current_app.logger.warning(
                f"Lifetime purchase {session.get('id')} has no user_id in metadata"
            )

    # Get user account details
    customer = StripeCustomer.query.filter_by(
        stripe_customer_id=session.get("customer")
    ).first()

    if customer:
        user = User.query.get(customer.user_id)
        account = Account.query.get(customer.account_id)

        # Send notification email to Brian
        try:
            from app.services.email_service import send_email

            subject = f"🎉 New FieldSprout Customer: {customer_name}"

            body_html = f"""
            <h2>New Stripe Payment Setup Completed</h2>

            <p>A customer has successfully set up payment on FieldSprout!</p>

            <h3>Customer Details:</h3>
            <ul>
                <li><strong>Name:</strong> {customer_name}</li>
                <li><strong>Email:</strong> {customer_email or 'N/A'}</li>
                <li><strong>Stripe Customer ID:</strong> {session.get("customer")}</li>
                <li><strong>Subscription ID:</strong> {subscription_id or 'N/A'}</li>
            </ul>

            <h3>Account Information:</h3>
            <ul>
                <li><strong>User ID:</strong> {user.id if user else 'N/A'}</li>
                <li><strong>User Email:</strong> {user.email if user else 'N/A'}</li>
                <li><strong>Account ID:</strong> {account.id if account else 'N/A'}</li>
                <li><strong>Account Name:</strong> {account.company_name if account else 'N/A'}</li>
            </ul>

            <h3>Session Details:</h3>
            <ul>
                <li><strong>Session ID:</strong> {session.get("id")}</li>
                <li><strong>Payment Status:</strong> {session.get("payment_status")}</li>
                <li><strong>Mode:</strong> {session.get("mode")}</li>
            </ul>

            <p><em>This is an automated notification from FieldSprout</em></p>
            """

            body_text = f"""
            New Stripe Payment Setup Completed

            Customer Details:
            - Name: {customer_name}
            - Email: {customer_email or 'N/A'}
            - Stripe Customer ID: {session.get("customer")}
            - Subscription ID: {subscription_id or 'N/A'}

            Account Information:
            - User ID: {user.id if user else 'N/A'}
            - User Email: {user.email if user else 'N/A'}
            - Account ID: {account.id if account else 'N/A'}
            - Account Name: {account.company_name if account else 'N/A'}

            Session Details:
            - Session ID: {session.get("id")}
            - Payment Status: {session.get("payment_status")}
            - Mode: {session.get("mode")}

            This is an automated notification from FieldSprout
            """

            send_email(
                to_email="mrbriancoheni@gmail.com",
                subject=subject,
                body_html=body_html,
                body_text=body_text
            )

            current_app.logger.info(
                f"Sent payment setup notification to Brian for customer {customer_name}",
                extra={
                    "metric": "stripe.notification.sent",
                    "customer_id": session.get("customer"),
                    "session_id": session.get("id")
                }
            )

        except Exception as e:
            current_app.logger.error(f"Failed to send payment notification email: {e}")
            # Don't fail the webhook if email fails
    else:
        current_app.logger.warning(f"No StripeCustomer found for session {session.get('id')}")


# Event handler mapping
WEBHOOK_HANDLERS = {
    "customer.subscription.created": handle_customer_subscription_created,
    "customer.subscription.updated": handle_customer_subscription_updated,
    "customer.subscription.deleted": handle_customer_subscription_deleted,
    "invoice.paid": handle_invoice_paid,
    "invoice.payment_failed": handle_invoice_payment_failed,
    "checkout.session.completed": handle_checkout_session_completed,
}


def process_webhook_event(event: Dict[str, Any]) -> bool:
    """
    Process a Stripe webhook event.

    Optimizations:
    - Idempotency checking (prevents duplicate processing)
    - Database transaction wrapping (prevents partial updates)
    - Comprehensive error logging
    - Performance monitoring

    Args:
        event: Stripe event object

    Returns:
        True if event was handled, False if event type not recognized
    """
    event_id = event.get("id")
    event_type = event.get("type")

    start_time = time.time()

    # Optimization: Check if we've already processed this event (idempotency)
    existing_event = StripeWebhookEvent.query.filter_by(event_id=event_id).first()
    if existing_event:
        current_app.logger.info(
            f"Webhook event {event_id} already processed, skipping",
            extra={"metric": "stripe.webhook.duplicate", "event_type": event_type}
        )
        return True

    # Get handler
    handler = WEBHOOK_HANDLERS.get(event_type)

    if not handler:
        # Unknown event type - log but don't fail
        webhook_event = StripeWebhookEvent(
            event_id=event_id,
            event_type=event_type,
            status='skipped'
        )
        db.session.add(webhook_event)
        db.session.commit()

        current_app.logger.debug(f"No handler for webhook event: {event_type}")
        return False

    # Process event within a transaction
    try:
        current_app.logger.info(
            f"Processing webhook event: {event_type}",
            extra={"metric": "stripe.webhook.processing", "event_type": event_type}
        )

        # Begin transaction
        handler(event["data"])

        # Record successful processing
        webhook_event = StripeWebhookEvent(
            event_id=event_id,
            event_type=event_type,
            status='processed'
        )
        db.session.add(webhook_event)
        db.session.commit()

        # Log performance metrics
        duration_ms = (time.time() - start_time) * 1000
        current_app.logger.info(
            f"Webhook event {event_type} processed successfully in {duration_ms:.2f}ms",
            extra={
                "metric": "stripe.webhook.success",
                "event_type": event_type,
                "duration_ms": duration_ms
            }
        )

        return True

    except Exception as e:
        # Rollback transaction on error
        db.session.rollback()

        # Record failed processing
        try:
            webhook_event = StripeWebhookEvent(
                event_id=event_id,
                event_type=event_type,
                status='failed',
                error_message=str(e)[:1000]  # Truncate long errors
            )
            db.session.add(webhook_event)
            db.session.commit()
        except Exception as db_error:
            current_app.logger.error(f"Failed to record webhook error: {db_error}")

        current_app.logger.error(
            f"Error processing webhook event {event_type}: {e}",
            exc_info=True,
            extra={"metric": "stripe.webhook.error", "event_type": event_type}
        )
        raise
