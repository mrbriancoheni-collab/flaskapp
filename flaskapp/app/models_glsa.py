# app/models_glsa.py
from __future__ import annotations
from datetime import datetime
from typing import Optional, Any, Dict, List

from flask import current_app
from app import db


class GLSAAccount(db.Model):
    __tablename__ = "glsa_accounts"

    id = db.Column(db.BigInteger, primary_key=True)
    account_id = db.Column(db.Integer, index=True, nullable=True)

    google_user_id = db.Column(db.String(128), index=True, nullable=True)
    email = db.Column(db.String(255), index=True, nullable=True)

    access_token = db.Column(db.Text, nullable=True)
    refresh_token = db.Column(db.Text, nullable=True)
    token_expiry = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # relationships
    leads = db.relationship(
        "GLSALead",
        back_populates="glsa_account",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    profiles = db.relationship(
        "GLSAProfile",
        back_populates="glsa_account",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"<GLSAAccount id={self.id} email={self.email!r}>"


class GLSALead(db.Model):
    __tablename__ = "glsa_leads"

    id = db.Column(db.BigInteger, primary_key=True)
    account_id = db.Column(db.Integer, index=True, nullable=True)

    glsa_account_id = db.Column(
        db.BigInteger,
        db.ForeignKey("glsa_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    lead_id = db.Column(db.String(128), nullable=True)  # provider's external id
    name = db.Column(db.String(255), nullable=True)
    phone = db.Column(db.String(32), nullable=True)
    email = db.Column(db.String(255), nullable=True)

    job_type = db.Column(db.String(128), index=True, nullable=True)
    city = db.Column(db.String(128), nullable=True)

    lead_ts = db.Column(db.DateTime, nullable=True)
    recording_url = db.Column(db.Text, nullable=True)

    # Arbitrary payload from provider: pricing, meta, etc.
    notes = db.Column(db.JSON, nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    glsa_account = db.relationship("GLSAAccount", back_populates="leads")

    __table_args__ = (
        db.UniqueConstraint("glsa_account_id", "lead_id", name="uq_glsa_leads_provider"),
    )

    def __repr__(self) -> str:
        return f"<GLSALead id={self.id} lead_id={self.lead_id!r}>"

class GLSACallRecord(db.Model):
    __tablename__ = "glsa_call_records"
    id = db.Column(db.BigInteger, primary_key=True)
    account_id = db.Column(db.BigInteger, nullable=False)
    lead_id = db.Column(db.BigInteger, db.ForeignKey("glsa_leads.id", ondelete="CASCADE"), nullable=False)
    storage_url = db.Column(db.String(1024))
    mime_type = db.Column(db.String(128))
    duration_sec = db.Column(db.Integer)
    transcript = db.Column(db.Text)          # MEDIUMTEXT ok with Text in SQLAlchemy
    outcome_label = db.Column(db.String(64))
    outcome_reason = db.Column(db.String(255))
    confidence = db.Column(db.Numeric(4,3))
    reviewed = db.Column(db.Boolean, default=False)
    reviewer_notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class GLSAProfile(db.Model):
    """
    Optimizable business profile for Google Local Services Ads (GLSA).
    Store the latest pulled profile plus AI suggestions the user can apply.
    """
    __tablename__ = "glsa_profiles"

    id = db.Column(db.BigInteger, primary_key=True)
    account_id = db.Column(db.Integer, index=True, nullable=True)

    glsa_account_id = db.Column(
        db.BigInteger,
        db.ForeignKey("glsa_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Core business info
    business_name = db.Column(db.String(255), nullable=True, index=True)
    phone = db.Column(db.String(32), nullable=True)
    email = db.Column(db.String(255), nullable=True)
    website = db.Column(db.String(255), nullable=True)

    categories = db.Column(db.JSON, nullable=True)       # e.g., ["Plumber", "HVAC"]
    service_areas = db.Column(db.JSON, nullable=True)    # e.g., [{"city":"Austin","zip":"78701"}, ...]
    description = db.Column(db.Text, nullable=True)
    hours = db.Column(db.JSON, nullable=True)            # e.g., {"Mon":"8-5", ...}

    license_number = db.Column(db.String(128), nullable=True)
    verification_status = db.Column(db.String(64), nullable=True)

    rating = db.Column(db.Float, nullable=True)
    review_count = db.Column(db.Integer, nullable=True)

    # AI suggestion blocks (preview before apply)
    suggestions = db.Column(db.JSON, nullable=True)      # {"description": "...", "service_areas":[...], ...}

    last_synced_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    glsa_account = db.relationship("GLSAAccount", back_populates="profiles")

    def __repr__(self) -> str:
        return f"<GLSAProfile id={self.id} business={self.business_name!r}>"
