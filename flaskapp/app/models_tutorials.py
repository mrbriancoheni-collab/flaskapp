# app/models_tutorials.py
"""
Interactive tutorial popup models for Pendo-style user onboarding.

Provides:
- Tutorial popup definitions (what, where, when to show)
- User progress tracking (which popups seen/dismissed)
- CRUD management via admin interface
"""

from datetime import datetime
from sqlalchemy import (
    Integer,
    String,
    Text,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
)
from sqlalchemy.sql import func
from app import db


class TutorialPopup(db.Model):
    """
    Defines an interactive tutorial popup/tooltip.

    Similar to Pendo guides - can be positioned on any page element
    with customizable content and display rules.
    """
    __tablename__ = "tutorial_popups"

    id = db.Column(Integer, primary_key=True)

    # Identification
    key = db.Column(String(100), unique=True, nullable=False, index=True)  # Unique identifier (e.g., "demo-bulk-selection")
    title = db.Column(String(200), nullable=False)  # Popup title
    content = db.Column(Text, nullable=False)  # HTML content for popup body

    # Positioning
    page_path = db.Column(String(500), nullable=False, index=True)  # URL path where popup appears (e.g., "/account/google/ads/opportunities")
    target_selector = db.Column(String(500), nullable=True)  # CSS selector for element to attach to (null = modal center)
    position = db.Column(String(20), default="bottom")  # Popup position: top, bottom, left, right, center

    # Display rules
    sequence_order = db.Column(Integer, default=0, index=True)  # Order in sequence (0 = first, 1 = second, etc.)
    trigger_type = db.Column(String(50), default="page_load")  # Trigger: page_load, click, hover, scroll, delay
    trigger_value = db.Column(String(200), nullable=True)  # Trigger value (e.g., selector for click, ms for delay)

    # Behavior
    dismissible = db.Column(Boolean, default=True)  # Can user dismiss/close?
    auto_dismiss_seconds = db.Column(Integer, nullable=True)  # Auto-dismiss after N seconds (null = manual only)
    show_once = db.Column(Boolean, default=True)  # Show only once per user?

    # Styling
    theme = db.Column(String(50), default="default")  # Theme: default, success, warning, info, primary
    width = db.Column(String(20), default="320px")  # Popup width (e.g., "320px", "auto")

    # CTA (Call to Action)
    cta_text = db.Column(String(100), nullable=True)  # Button text (e.g., "Got it", "Next")
    cta_link = db.Column(String(500), nullable=True)  # Optional link when CTA clicked

    # Status
    is_active = db.Column(Boolean, default=True, index=True)  # Active/inactive

    # Metadata
    created_at = db.Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = db.Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)
    created_by = db.Column(Integer, ForeignKey("users.id"), nullable=True)  # Admin who created it

    def __repr__(self):
        return f"<TutorialPopup key={self.key!r} title={self.title!r} active={self.is_active}>"

    def to_dict(self):
        """Convert to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "key": self.key,
            "title": self.title,
            "content": self.content,
            "page_path": self.page_path,
            "target_selector": self.target_selector,
            "position": self.position,
            "sequence_order": self.sequence_order,
            "trigger_type": self.trigger_type,
            "trigger_value": self.trigger_value,
            "dismissible": self.dismissible,
            "auto_dismiss_seconds": self.auto_dismiss_seconds,
            "show_once": self.show_once,
            "theme": self.theme,
            "width": self.width,
            "cta_text": self.cta_text,
            "cta_link": self.cta_link,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class TutorialUserProgress(db.Model):
    """
    Tracks which popups a user has seen/dismissed.

    Used to implement "show once" behavior and analytics.
    """
    __tablename__ = "tutorial_user_progress"
    __table_args__ = (
        Index('ix_tutorial_user_popup', 'user_id', 'popup_id', unique=True),
    )

    id = db.Column(Integer, primary_key=True)

    user_id = db.Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    popup_id = db.Column(Integer, ForeignKey("tutorial_popups.id"), nullable=False, index=True)

    # Tracking
    viewed_at = db.Column(DateTime, server_default=func.now(), nullable=False)  # First time viewed
    dismissed_at = db.Column(DateTime, nullable=True)  # When user dismissed it
    dismissed_action = db.Column(String(50), nullable=True)  # How dismissed: close_button, cta_click, auto_dismiss, backdrop_click

    # Analytics
    view_count = db.Column(Integer, default=1, nullable=False)  # How many times viewed

    def __repr__(self):
        return f"<TutorialUserProgress user_id={self.user_id} popup_id={self.popup_id} dismissed={self.dismissed_at is not None}>"
