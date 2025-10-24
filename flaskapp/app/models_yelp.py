from __future__ import annotations
from datetime import datetime
from typing import Optional

from sqlalchemy.dialects.mysql import BIGINT, JSON, VARCHAR, DATETIME, TEXT
from app import db

class YelpAccount(db.Model):
    __tablename__ = "yelp_accounts"
    id = db.Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    account_id = db.Column(BIGINT(unsigned=True), index=True, nullable=True)
    yelp_user_id = db.Column(VARCHAR(191), nullable=True, index=True)   # optional (not used with API key)
    email = db.Column(VARCHAR(191), nullable=True)
    access_token = db.Column(TEXT, nullable=True)    # store API key
    refresh_token = db.Column(TEXT, nullable=True)   # not used for API key flow
    token_expiry = db.Column(DATETIME, nullable=True)
    created_at = db.Column(DATETIME, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(DATETIME, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

class YelpLead(db.Model):
    __tablename__ = "yelp_leads"
    id = db.Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    account_id = db.Column(BIGINT(unsigned=True), index=True, nullable=True)
    external_id = db.Column(VARCHAR(191), index=True, nullable=False)
    name = db.Column(VARCHAR(191), nullable=True)
    phone = db.Column(VARCHAR(64), nullable=True)
    message = db.Column(TEXT, nullable=True)
    city = db.Column(VARCHAR(191), nullable=True)
    lead_ts = db.Column(DATETIME, nullable=True)
    raw = db.Column(JSON, nullable=True)
    created_at = db.Column(DATETIME, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(DATETIME, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

class YelpProfile(db.Model):
    __tablename__ = "yelp_profiles"
    id = db.Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    account_id = db.Column(BIGINT(unsigned=True), index=True, nullable=True)
    profile_id = db.Column(VARCHAR(191), index=True, nullable=False)
    business_name = db.Column(VARCHAR(191), nullable=True)
    description = db.Column(TEXT, nullable=True)
    categories = db.Column(JSON, nullable=True)
    service_areas = db.Column(JSON, nullable=True)
    phone = db.Column(VARCHAR(64), nullable=True)
    website = db.Column(VARCHAR(255), nullable=True)
    hours = db.Column(JSON, nullable=True)
    raw = db.Column(JSON, nullable=True)
    created_at = db.Column(DATETIME, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(DATETIME, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
