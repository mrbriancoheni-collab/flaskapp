# app/models_billing.py
from datetime import datetime
from app import db

class StripeCustomer(db.Model):
    __tablename__ = "stripe_customers"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(64), index=True, nullable=False)  # your app's user id/email
    stripe_customer_id = db.Column(db.String(64), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Subscription(db.Model):
    __tablename__ = "subscriptions"
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
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(64), index=True, nullable=False)
    stripe_customer_id = db.Column(db.String(64), index=True, nullable=False)
    invoice_id = db.Column(db.String(64), index=True)
    payment_intent_id = db.Column(db.String(64), index=True)
    amount = db.Column(db.Integer)  # in cents
    currency = db.Column(db.String(8))
    status = db.Column(db.String(32))  # paid, open, uncollectible
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

