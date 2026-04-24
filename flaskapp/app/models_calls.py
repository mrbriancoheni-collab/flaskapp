# app/models_calls.py
"""
Call tracking models.

CallTrackingNumber — maps a Twilio phone number to a Google Ads campaign.
                     One number per campaign = automatic call attribution.

CallEvent          — every inbound Twilio call, enriched with attribution
                     and qualified-lead status based on call duration.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from app import db


class CallTrackingNumber(db.Model):
    """
    A Twilio phone number assigned to track calls from a specific campaign.

    When a call comes in on this number, it's attributed to the linked campaign.
    """
    __tablename__ = "call_tracking_numbers"

    id          = db.Column(db.Integer, primary_key=True)
    account_id  = db.Column(db.Integer, nullable=False, index=True)
    phone_number = db.Column(db.String(32), nullable=False)   # E.164, e.g. +15125550100
    label       = db.Column(db.String(255), nullable=True)    # "HVAC Search Campaign"
    campaign_id = db.Column(db.String(64),  nullable=True)    # Google Ads campaign ID
    campaign_name = db.Column(db.String(255), nullable=True)
    is_active   = db.Column(db.Boolean, nullable=False, default=True)
    # Duration threshold (seconds) to count a call as a qualified lead
    qualified_duration_secs = db.Column(db.Integer, nullable=False, default=60)
    created_at  = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    calls = db.relationship("CallEvent", back_populates="tracking_number",
                            lazy="dynamic", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<CallTrackingNumber {self.phone_number} campaign={self.campaign_id}>"


class CallEvent(db.Model):
    """
    One inbound Twilio call.

    Qualified lead threshold: duration >= tracking_number.qualified_duration_secs
    (default 60 s).  If the tracking number is unknown, falls back to the
    account-level setting or 60 s.
    """
    __tablename__ = "call_events"

    id          = db.Column(db.Integer, primary_key=True)
    account_id  = db.Column(db.Integer, nullable=False, index=True)

    # Twilio identifiers
    call_sid    = db.Column(db.String(64), nullable=False, unique=True)
    parent_call_sid = db.Column(db.String(64), nullable=True)

    # Parties
    from_number = db.Column(db.String(32), nullable=True)   # caller
    to_number   = db.Column(db.String(32), nullable=True)   # tracking number called

    # Attribution (filled from CallTrackingNumber lookup)
    tracking_number_id = db.Column(db.Integer, db.ForeignKey("call_tracking_numbers.id"),
                                   nullable=True, index=True)
    campaign_id   = db.Column(db.String(64),  nullable=True, index=True)
    campaign_name = db.Column(db.String(255), nullable=True)

    # Call outcome
    call_status  = db.Column(db.String(32),  nullable=True)  # completed|no-answer|busy|failed
    call_duration = db.Column(db.Integer,    nullable=True)   # seconds (from Twilio)
    is_qualified_lead = db.Column(db.Boolean, nullable=False, default=False)

    # Caller geo (from Twilio CallerCity/State/Zip fields)
    caller_city  = db.Column(db.String(64),  nullable=True)
    caller_state = db.Column(db.String(32),  nullable=True)
    caller_zip   = db.Column(db.String(16),  nullable=True)

    # Timestamps
    call_started_at = db.Column(db.DateTime, nullable=True, index=True)
    call_ended_at   = db.Column(db.DateTime, nullable=True)
    created_at      = db.Column(db.DateTime, nullable=False,
                                default=datetime.utcnow, index=True)

    # Full Twilio payload for debugging
    raw_payload = db.Column(db.JSON, nullable=True)

    # Relationships
    tracking_number = db.relationship("CallTrackingNumber", back_populates="calls")

    def __repr__(self) -> str:
        return (f"<CallEvent sid={self.call_sid} status={self.call_status} "
                f"duration={self.call_duration}s qualified={self.is_qualified_lead}>")

    @property
    def duration_minutes(self) -> float:
        return round((self.call_duration or 0) / 60, 1)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "call_sid": self.call_sid,
            "from_number": self.from_number,
            "campaign_id": self.campaign_id,
            "campaign_name": self.campaign_name,
            "call_status": self.call_status,
            "call_duration": self.call_duration,
            "is_qualified_lead": self.is_qualified_lead,
            "caller_city": self.caller_city,
            "caller_state": self.caller_state,
            "call_started_at": self.call_started_at.isoformat() if self.call_started_at else None,
        }
