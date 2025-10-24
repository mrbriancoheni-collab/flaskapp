# app/models_fbads.py
from __future__ import annotations
from datetime import datetime
from typing import Any, Optional, Dict, List

from sqlalchemy.dialects.mysql import BIGINT, JSON
from app import db


class FBAccount(db.Model):
    """
    Stores Facebook user and selected Page context for an app account.
    """
    __tablename__ = "fb_accounts"

    id = db.Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    account_id = db.Column(db.Integer, index=True, nullable=True)  # your app's account

    fb_user_id = db.Column(db.String(64), index=True, nullable=True)
    email = db.Column(db.String(255), index=True, nullable=True)

    access_token = db.Column(db.String(1024), nullable=True)
    token_expiry = db.Column(db.DateTime, nullable=True)

    page_id = db.Column(db.String(64), index=True, nullable=True)
    page_name = db.Column(db.String(255), nullable=True)
    page_access_token = db.Column(db.String(1024), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow,
                           onupdate=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"<FBAccount id={self.id} acct={self.account_id} page={self.page_name or '-'}>"


class FBLead(db.Model):
    """
    Normalized copy of Facebook Lead Ads submissions.
    """
    __tablename__ = "fb_leads"

    id = db.Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    account_id = db.Column(db.Integer, index=True, nullable=True)

    external_id = db.Column(db.String(128), index=True, nullable=False)  # FB lead id
    page_id = db.Column(db.String(64), index=True, nullable=True)
    form_name = db.Column(db.String(255), nullable=True)

    name = db.Column(db.String(255), nullable=True)
    email = db.Column(db.String(255), nullable=True)
    phone = db.Column(db.String(64), nullable=True)

    created_time = db.Column(db.DateTime, nullable=True)  # from FB payload
    raw = db.Column(JSON, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow,
                           onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        db.UniqueConstraint("account_id", "external_id", name="uq_fb_lead_ext"),
    )

    def __repr__(self) -> str:
        return f"<FBLead id={self.id} acct={self.account_id} ext={self.external_id}>"


class FBProfile(db.Model):
    """
    Cached snapshot of a Facebook Page profile for quick reads and reporting.
    """
    __tablename__ = "fb_profiles"

    id = db.Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    account_id = db.Column(db.Integer, index=True, nullable=True)

    page_id = db.Column(db.String(64), index=True, nullable=False)
    page_name = db.Column(db.String(255), nullable=True)

    about = db.Column(db.Text, nullable=True)
    description = db.Column(db.Text, nullable=True)
    website = db.Column(db.String(512), nullable=True)
    phone = db.Column(db.String(64), nullable=True)
    hours = db.Column(JSON, nullable=True)

    raw = db.Column(JSON, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow,
                           onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        db.UniqueConstraint("account_id", "page_id", name="uq_fb_profile_page"),
    )

    def __repr__(self) -> str:
        return f"<FBProfile id={self.id} acct={self.account_id} page={self.page_id}>"


__all__ = [
    "FBAccount",
    "FBLead",
    "FBProfile",
]
