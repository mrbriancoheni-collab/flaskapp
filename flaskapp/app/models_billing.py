# app/models_billing.py
from datetime import datetime
from app import db

class StripeCustomer(db.Model):
    __tablename__ = "stripe_customers"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(64), index=True, nullable=False)  # your app's user id/email
    stripe_customer_id = db.Column(db.String(64), unique=True, nullable=False)
    first_payment_at = db.Column(db.DateTime, nullable=True)  # Optimization: Track first payment for faster queries
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Subscription(db.Model):
    __tablename__ = "subscriptions"

    # Composite index for common queries (user_id + status)
    __table_args__ = (
        db.Index('idx_subscriptions_user_status', 'user_id', 'status'),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(64), index=True, nullable=False)
    stripe_customer_id = db.Column(db.String(64), index=True, nullable=False)
    stripe_subscription_id = db.Column(db.String(64), unique=True, nullable=False)
    price_id = db.Column(db.String(64), nullable=True)
    status = db.Column(db.String(32), index=True)  # trialing, active, past_due, canceled, incomplete, etc.
    current_period_end = db.Column(db.DateTime, nullable=True)
    cancel_at_period_end = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Payment(db.Model):
    __tablename__ = "payments"

    # Composite index for common queries (user_id + status)
    __table_args__ = (
        db.Index('idx_payments_user_status', 'user_id', 'status'),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(64), index=True, nullable=False)
    stripe_customer_id = db.Column(db.String(64), index=True, nullable=False)
    invoice_id = db.Column(db.String(64), index=True)
    payment_intent_id = db.Column(db.String(64), index=True)
    amount = db.Column(db.Integer)  # in cents
    currency = db.Column(db.String(8))
    status = db.Column(db.String(32))  # paid, open, uncollectible
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class StripeWebhookEvent(db.Model):
    """
    Track processed Stripe webhook events for idempotency.
    Prevents duplicate processing of the same event.
    """
    __tablename__ = "stripe_webhook_events"

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.String(64), unique=True, nullable=False, index=True)
    event_type = db.Column(db.String(64), nullable=False, index=True)
    processed_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    status = db.Column(db.String(32), default='processed')  # processed, failed, skipped
    error_message = db.Column(db.Text, nullable=True)

    def __repr__(self):
        return f'<StripeWebhookEvent {self.event_id} {self.event_type}>'


class EmailQueue(db.Model):
    """
    Queue for background email sending.
    Decouples email delivery from critical payment flows.
    """
    __tablename__ = "email_queue"

    __table_args__ = (
        db.Index('idx_email_queue_status_created', 'status', 'created_at'),
    )

    id = db.Column(db.Integer, primary_key=True)
    to_email = db.Column(db.String(255), nullable=False)
    subject = db.Column(db.String(255), nullable=False)
    html_body = db.Column(db.Text, nullable=False)
    text_body = db.Column(db.Text, nullable=True)
    use_bulk_credentials = db.Column(db.Boolean, default=False)
    status = db.Column(db.String(32), default='pending', index=True)  # pending, sent, failed
    attempts = db.Column(db.Integer, default=0)
    max_attempts = db.Column(db.Integer, default=3)
    error_message = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    sent_at = db.Column(db.DateTime, nullable=True)

    def __repr__(self):
        return f'<EmailQueue {self.id} to={self.to_email} status={self.status}>'

