# app/models_tooling.py
from __future__ import annotations
from datetime import datetime, date
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.dialects.mysql import JSON as MySQLJSON
from app import db  # uses your global db

class ReviewRequest(db.Model):
    __tablename__ = "review_requests"
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, nullable=False, index=True)
    channel = db.Column(db.String(16), nullable=False)  # 'email' | 'sms'
    recipient = db.Column(db.String(255), nullable=False)  # email or phone
    status = db.Column(db.String(32), nullable=False, default="queued")  # queued/sent/failed
    payload = db.Column(MySQLJSON, nullable=True)  # template vars, debug logs, etc.
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    sent_at = db.Column(db.DateTime, nullable=True)

class AdSpend(db.Model):
    __tablename__ = "ad_spend"
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, nullable=False, index=True)
    source = db.Column(db.String(64), nullable=False)  # glsa|facebook|yelp|google-ads|other
    spend_date = db.Column(db.Date, nullable=False, index=True)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    meta = db.Column(MySQLJSON, nullable=True)  # campaign, notes, currency, etc.
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

class LeadIngest(db.Model):
    __tablename__ = "lead_ingest"
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, nullable=False, index=True)
    source = db.Column(db.String(64), nullable=False)  # glsa|facebook|yelp|phone|webform|other
    external_id = db.Column(db.String(128), nullable=True, index=True)
    name = db.Column(db.String(255), nullable=True)
    phone = db.Column(db.String(64), nullable=True, index=True)
    email = db.Column(db.String(255), nullable=True, index=True)
    city = db.Column(db.String(255), nullable=True)
    occurred_at = db.Column(db.DateTime, nullable=True, index=True)
    raw = db.Column(MySQLJSON, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
