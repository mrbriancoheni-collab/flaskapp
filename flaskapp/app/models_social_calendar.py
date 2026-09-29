# app/models_social_calendar.py
"""
Database models for the unified Social Media Calendar feature.
Covers Facebook, Instagram, YouTube, and LinkedIn.
"""
from __future__ import annotations

from datetime import datetime, date
from typing import Optional, List

from sqlalchemy import (
    String,
    Integer,
    BigInteger,
    DateTime,
    Date,
    Text,
    Float,
    ForeignKey,
)
from sqlalchemy.sql import func

from app import db


class SocialCalendarPost(db.Model):
    """
    A scheduled social media post for the unified social calendar.
    Supports Facebook, Instagram, YouTube, and LinkedIn.
    """
    __tablename__ = "social_calendar_posts"

    # ---- Per-platform character limits ----------------------------------------
    CHAR_LIMITS = {
        'facebook': 80,
        'instagram': 120,
        'youtube_title': 70,
        'linkedin': 1300,
    }

    # ---- Post types per platform -----------------------------------------------
    POST_TYPES = {
        'facebook': ['Text-Only', 'Story', 'Poll', 'Image', 'Video', 'Event', 'Live'],
        'instagram': ['Single Image', 'Collaboration', 'Carousel', 'Shoppable', 'Video', 'Story', 'Reel', 'Live'],
        'youtube': ['Video'],
        'linkedin': ['Text', 'Image', 'Video', 'Article', 'Poll', 'Story'],
    }

    # ---- Columns ---------------------------------------------------------------
    id = db.Column(Integer, primary_key=True)
    account_id = db.Column(BigInteger, ForeignKey("accounts.id", ondelete="CASCADE"), index=True, nullable=False)
    platform = db.Column(String(20), nullable=False, index=True)   # facebook|instagram|youtube|linkedin
    scheduled_date = db.Column(Date, nullable=False, index=True)
    scheduled_time = db.Column(String(5), nullable=True, server_default="09:00")
    post_type = db.Column(String(50), nullable=True)
    copy_text = db.Column(Text, nullable=True)
    title = db.Column(String(200), nullable=True)        # YouTube title (<=70 chars)
    link = db.Column(String(500), nullable=True)
    campaign = db.Column(String(200), nullable=True)
    creative_url = db.Column(String(500), nullable=True)
    post_owner = db.Column(String(100), nullable=True)
    status = db.Column(String(20), nullable=False, server_default="pending")  # pending|approved|published|needs_revision
    engagement_rate = db.Column(Float, nullable=True)
    created_at = db.Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = db.Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    def __repr__(self) -> str:
        return (
            f"<SocialCalendarPost id={self.id} platform={self.platform} "
            f"date={self.scheduled_date} status={self.status}>"
        )

    # ---- Class methods --------------------------------------------------------

    @classmethod
    def get_for_account(
        cls,
        account_id: int,
        platform: Optional[str] = None,
        year: Optional[int] = None,
        month: Optional[int] = None,
    ) -> List["SocialCalendarPost"]:
        """Return posts for an account, optionally filtered by platform and month."""
        q = cls.query.filter_by(account_id=account_id)
        if platform:
            q = q.filter_by(platform=platform)
        if year and month:
            from sqlalchemy import extract
            q = q.filter(
                extract("year", cls.scheduled_date) == year,
                extract("month", cls.scheduled_date) == month,
            )
        return q.order_by(cls.scheduled_date.asc(), cls.scheduled_time.asc()).all()

    @classmethod
    def get_upcoming(
        cls,
        account_id: int,
        platform: Optional[str] = None,
        limit: int = 20,
    ) -> List["SocialCalendarPost"]:
        """Return upcoming posts (today onward) for an account."""
        today = date.today()
        q = cls.query.filter(
            cls.account_id == account_id,
            cls.scheduled_date >= today,
        )
        if platform:
            q = q.filter_by(platform=platform)
        return q.order_by(cls.scheduled_date.asc(), cls.scheduled_time.asc()).limit(limit).all()

    def to_dict(self) -> dict:
        """Serialize this post to a JSON-safe dictionary."""
        return {
            "id": self.id,
            "account_id": self.account_id,
            "platform": self.platform,
            "scheduled_date": self.scheduled_date.isoformat() if self.scheduled_date else None,
            "scheduled_time": self.scheduled_time,
            "post_type": self.post_type,
            "copy_text": self.copy_text,
            "title": self.title,
            "link": self.link,
            "campaign": self.campaign,
            "creative_url": self.creative_url,
            "post_owner": self.post_owner,
            "status": self.status,
            "engagement_rate": self.engagement_rate,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
