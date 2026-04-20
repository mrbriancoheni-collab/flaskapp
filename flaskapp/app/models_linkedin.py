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
    BigInteger,
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
    account_id = db.Column(BigInteger, ForeignKey("accounts.id"), index=True, nullable=False)

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


class LinkedInCategory(db.Model):
    """
    Thought leadership content categories with unique POV.
    Users define 3-5 primary categories for their content strategy.
    """
    __tablename__ = "linkedin_categories"

    id = db.Column(Integer, primary_key=True)
    account_id = db.Column(BigInteger, ForeignKey("accounts.id"), index=True, nullable=False)

    # Category details
    name = db.Column(String(100), nullable=False)
    description = db.Column(Text, nullable=True)

    # Point of View (POV) - What makes this perspective unique
    pov_statement = db.Column(Text, nullable=False)
    unique_expertise = db.Column(Text, nullable=True)

    # Strategy settings
    post_frequency = db.Column(String(20), server_default="weekly")  # daily|weekly|biweekly|monthly
    priority = db.Column(Integer, server_default="1")  # 1=highest priority
    is_active = db.Column(Boolean, server_default="true", nullable=False)

    # Tracking
    posts_generated = db.Column(Integer, server_default="0", nullable=False)
    last_post_date = db.Column(Date, nullable=True)

    # Timestamps
    created_at = db.Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = db.Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    topics = db.relationship("LinkedInCategoryTopic", backref="category", cascade="all, delete-orphan", lazy="dynamic")

    def __repr__(self) -> str:
        return f"<LinkedInCategory id={self.id} name={self.name!r} account_id={self.account_id}>"

    @classmethod
    def get_active_for_account(cls, account_id: int):
        """Get all active categories for an account, ordered by priority."""
        return cls.query.filter_by(
            account_id=account_id,
            is_active=True
        ).order_by(cls.priority.asc(), cls.name.asc()).all()

    @classmethod
    def count_for_account(cls, account_id: int) -> int:
        """Count categories for an account."""
        return cls.query.filter_by(account_id=account_id).count()

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON responses."""
        return {
            "id": self.id,
            "account_id": self.account_id,
            "name": self.name,
            "description": self.description,
            "pov_statement": self.pov_statement,
            "unique_expertise": self.unique_expertise,
            "post_frequency": self.post_frequency,
            "priority": self.priority,
            "is_active": self.is_active,
            "posts_generated": self.posts_generated,
            "last_post_date": self.last_post_date.isoformat() if self.last_post_date else None,
            "topics_count": self.topics.count(),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class LinkedInCategoryTopic(db.Model):
    """
    Specific topic ideas within each category.
    AI uses these as inspiration for post generation.
    """
    __tablename__ = "linkedin_category_topics"

    id = db.Column(Integer, primary_key=True)
    category_id = db.Column(Integer, ForeignKey("linkedin_categories.id", ondelete="CASCADE"), index=True, nullable=False)

    # Topic details
    topic_idea = db.Column(Text, nullable=False)
    tone = db.Column(String(50), server_default="professional")

    # Usage tracking
    used = db.Column(Boolean, server_default="false", nullable=False)
    used_date = db.Column(Date, nullable=True)
    post_id = db.Column(Integer, ForeignKey("linkedin_scheduled_posts.id", ondelete="SET NULL"), nullable=True)

    # Timestamps
    created_at = db.Column(DateTime, server_default=func.now(), nullable=False)

    def __repr__(self) -> str:
        return f"<LinkedInCategoryTopic id={self.id} category_id={self.category_id} used={self.used}>"

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON responses."""
        return {
            "id": self.id,
            "category_id": self.category_id,
            "topic_idea": self.topic_idea,
            "tone": self.tone,
            "used": self.used,
            "used_date": self.used_date.isoformat() if self.used_date else None,
            "post_id": self.post_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class LinkedInCampaign(db.Model):
    """
    Automated content campaigns for thought leadership.
    Generates posts based on category rotation and strategy.
    """
    __tablename__ = "linkedin_campaigns"

    id = db.Column(Integer, primary_key=True)
    account_id = db.Column(BigInteger, ForeignKey("accounts.id"), index=True, nullable=False)

    # Campaign details
    name = db.Column(String(200), nullable=False)
    description = db.Column(Text, nullable=True)

    # Campaign settings
    start_date = db.Column(Date, nullable=False)
    end_date = db.Column(Date, nullable=True)
    posts_per_week = db.Column(Integer, server_default="3", nullable=False)

    # Category rotation strategy
    category_rotation = db.Column(String(20), server_default="round_robin")  # round_robin|priority|random

    # Status
    status = db.Column(String(20), server_default="active", nullable=False)  # active|paused|completed

    # Tracking
    posts_generated = db.Column(Integer, server_default="0", nullable=False)
    last_generation_date = db.Column(Date, nullable=True)

    # Timestamps
    created_at = db.Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = db.Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    def __repr__(self) -> str:
        return f"<LinkedInCampaign id={self.id} name={self.name!r} status={self.status}>"

    @classmethod
    def get_active_for_account(cls, account_id: int):
        """Get all active campaigns for an account."""
        return cls.query.filter_by(
            account_id=account_id,
            status="active"
        ).order_by(cls.created_at.desc()).all()

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON responses."""
        return {
            "id": self.id,
            "account_id": self.account_id,
            "name": self.name,
            "description": self.description,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "posts_per_week": self.posts_per_week,
            "category_rotation": self.category_rotation,
            "status": self.status,
            "posts_generated": self.posts_generated,
            "last_generation_date": self.last_generation_date.isoformat() if self.last_generation_date else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


def ensure_linkedin_tables():
    """
    Ensure all LinkedIn tables exist in the database.
    This function creates tables if they don't exist.
    """
    try:
        from app import db
        
        # Create all LinkedIn tables
        db.create_all()
        
        # Specifically check for LinkedIn tables
        from sqlalchemy import inspect
        inspector = inspect(db.engine)
        tables = inspector.get_table_names()
        
        linkedin_tables = [
            'linkedin_scheduled_posts',
            'linkedin_categories',
            'linkedin_category_topics',
            'linkedin_campaigns'
        ]
        
        missing_tables = [t for t in linkedin_tables if t not in tables]
        
        if missing_tables:
            raise Exception(f"Failed to create LinkedIn tables: {', '.join(missing_tables)}")
        
        return True
    except Exception as e:
        raise Exception(f"Error ensuring LinkedIn tables: {e}")
