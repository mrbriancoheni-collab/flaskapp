# app/models_linkedin.py
"""
Database models for LinkedIn features including scheduled posts.
"""
from __future__ import annotations

from datetime import datetime, date
from typing import Optional

from sqlalchemy import (
    String,
    Integer,
    DateTime,
    Date,
    Text,
    ForeignKey,
    Boolean,
)
from sqlalchemy.sql import func

from app import db


class LinkedInScheduledPost(db.Model):
    """
    Scheduled LinkedIn posts for the thought leader post generator.
    Maximum 1 post per day, up to 1 week in advance.
    """
    __tablename__ = "linkedin_scheduled_posts"

    id = db.Column(Integer, primary_key=True)

    # Link to account
    account_id = db.Column(Integer, ForeignKey("accounts.id"), index=True, nullable=False)

    # Post content
    post_text = db.Column(Text, nullable=False)

    # Scheduling info
    scheduled_date = db.Column(Date, nullable=False, index=True)
    scheduled_time = db.Column(String(5), nullable=True, server_default="09:00")  # HH:MM format

    # Post metadata (from generation)
    expertise = db.Column(Text, nullable=True)
    industry = db.Column(String(100), nullable=True)
    topic = db.Column(Text, nullable=True)
    tone = db.Column(String(50), nullable=True)

    # Status tracking
    status = db.Column(
        String(20),
        nullable=False,
        server_default="scheduled",
        index=True
    )  # scheduled|posted|cancelled|failed

    posted_at = db.Column(DateTime, nullable=True)

    # Error tracking (if posting fails)
    error_message = db.Column(Text, nullable=True)

    # Timestamps
    created_at = db.Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = db.Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    def __repr__(self) -> str:
        return f"<LinkedInScheduledPost id={self.id} account_id={self.account_id} date={self.scheduled_date} status={self.status}>"

    @classmethod
    def get_scheduled_for_account(cls, account_id: int, status: str = "scheduled"):
        """Get all scheduled posts for an account with given status."""
        return cls.query.filter_by(
            account_id=account_id,
            status=status
        ).order_by(cls.scheduled_date.asc()).all()

    @classmethod
    def get_for_date(cls, account_id: int, scheduled_date: date) -> Optional[LinkedInScheduledPost]:
        """Get scheduled post for a specific date (enforces 1 post per day)."""
        return cls.query.filter_by(
            account_id=account_id,
            scheduled_date=scheduled_date,
            status="scheduled"
        ).first()

    @classmethod
    def count_scheduled_for_account(cls, account_id: int) -> int:
        """Count scheduled posts for an account."""
        return cls.query.filter_by(
            account_id=account_id,
            status="scheduled"
        ).count()

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON responses."""
        return {
            "id": self.id,
            "account_id": self.account_id,
            "post_text": self.post_text,
            "scheduled_date": self.scheduled_date.isoformat() if self.scheduled_date else None,
            "scheduled_time": self.scheduled_time,
            "expertise": self.expertise,
            "industry": self.industry,
            "topic": self.topic,
            "tone": self.tone,
            "status": self.status,
            "posted_at": self.posted_at.isoformat() if self.posted_at else None,
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
