# app/models_tooling.py
from __future__ import annotations
from datetime import datetime, date
from sqlalchemy.dialects.mysql import JSON as MySQLJSON
from app import db


class ReviewRequest(db.Model):
    __tablename__ = "review_requests"
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, nullable=False, index=True)
    channel = db.Column(db.String(16), nullable=False)  # 'email' | 'sms'
    recipient = db.Column(db.String(255), nullable=False)  # email or phone
    status = db.Column(db.String(32), nullable=False, default="queued")  # queued/sent/failed
    customer_name = db.Column(db.String(255), nullable=True)
    job_type = db.Column(db.String(128), nullable=True)
    review_link_google = db.Column(db.String(512), nullable=True)
    review_link_yelp = db.Column(db.String(512), nullable=True)
    payload = db.Column(MySQLJSON, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    sent_at = db.Column(db.DateTime, nullable=True)


class AdSpend(db.Model):
    __tablename__ = "ad_spend"
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, nullable=False, index=True)
    source = db.Column(db.String(64), nullable=False)  # glsa|facebook|yelp|google-ads|networx|elocal|other
    spend_date = db.Column(db.Date, nullable=False, index=True)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    meta = db.Column(MySQLJSON, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class LeadIngest(db.Model):
    __tablename__ = "lead_ingest"
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, nullable=False, index=True)
    source = db.Column(db.String(64), nullable=False)  # glsa|facebook|yelp|phone|webform|networx|elocal|other
    external_id = db.Column(db.String(128), nullable=True, index=True)
    name = db.Column(db.String(255), nullable=True)
    phone = db.Column(db.String(64), nullable=True, index=True)
    email = db.Column(db.String(255), nullable=True, index=True)
    city = db.Column(db.String(255), nullable=True)
    service_type = db.Column(db.String(128), nullable=True)
    lead_cost = db.Column(db.Numeric(10, 2), nullable=True)
    status = db.Column(db.String(32), nullable=False, default="new")  # new|contacted|booked|completed|lost
    job_notes = db.Column(db.Text, nullable=True)
    contacted_at = db.Column(db.DateTime, nullable=True)
    booked_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    occurred_at = db.Column(db.DateTime, nullable=True, index=True)
    raw = db.Column(MySQLJSON, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class LeadIntakeConfig(db.Model):
    """Per-account config for external lead source integrations."""
    __tablename__ = "lead_intake_configs"
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, nullable=False, unique=True, index=True)

    # Networx
    networx_webhook_secret = db.Column(db.String(128), nullable=True)
    networx_default_lead_cost = db.Column(db.Numeric(10, 2), nullable=True, default=45.00)

    # eLocal
    elocal_tracking_number = db.Column(db.String(32), nullable=True)  # Twilio number assigned to eLocal calls
    elocal_default_lead_cost = db.Column(db.Numeric(10, 2), nullable=True, default=35.00)

    # Missed call SMS (per-account override)
    missed_call_sms_body = db.Column(db.Text, nullable=True)

    # Review request templates
    review_request_sms_template = db.Column(db.Text, nullable=True)
    review_request_email_subject = db.Column(db.String(255), nullable=True)
    review_link_google = db.Column(db.String(512), nullable=True)
    review_link_yelp = db.Column(db.String(512), nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
