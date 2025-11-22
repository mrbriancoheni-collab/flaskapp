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

    # Content
    title = db.Column(String(200), nullable=True)  # Popup title
    content = db.Column(Text, nullable=True)  # HTML content for popup body

    # Positioning
    page_path = db.Column(String(500), nullable=False, index=True)  # URL path where popup appears
    page_element = db.Column(String(500), nullable=True)  # CSS selector to highlight
    position_x = db.Column(Integer, nullable=True)  # X position
    position_y = db.Column(Integer, nullable=True)  # Y position

    # Styling
    icon = db.Column(String(100), nullable=True)  # Font Awesome icon class
    theme = db.Column(String(50), default="default")  # Theme: default, success, warning, info, primary
    width_px = db.Column(Integer, nullable=True)  # Popup width in pixels

    # Display rules
    sequence_order = db.Column(Integer, default=0, index=True)  # Order in sequence

    # Behavior
    show_once = db.Column(Boolean, default=True)  # Show only once per user?

    # Status
    is_active = db.Column(Boolean, default=True, index=True)  # Active/inactive

    # Metadata
    created_at = db.Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = db.Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    def __repr__(self):
        return f"<TutorialPopup id={self.id} title={self.title!r} active={self.is_active}>"

    def to_dict(self):
        """Convert to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "title": self.title,
            "content": self.content,
            "page_path": self.page_path,
            "page_element": self.page_element,
            "position_x": self.position_x,
            "position_y": self.position_y,
            "icon": self.icon,
            "theme": self.theme,
            "width_px": self.width_px,
            "sequence_order": self.sequence_order,
            "show_once": self.show_once,
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
