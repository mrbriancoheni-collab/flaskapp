# app/models_ai_actions.py
"""
AI Action Logging Models

Tracks all automated changes made by AI to Google Ads campaigns.
Provides audit trail and undo functionality.
"""

from datetime import datetime
from typing import Optional, Dict, Any
from sqlalchemy import Enum as SAEnum

from app import db


class AIAction(db.Model):
    """
    Log of all AI-driven changes to Google Ads campaigns.

    Provides:
    - Complete audit trail
    - Undo functionality
    - Change attribution
    - Performance tracking
    """
    __tablename__ = "ai_actions"

    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, nullable=False, index=True)  # No FK to avoid MySQL constraint issues

    # Action classification
    action_type = db.Column(
        SAEnum(
            "negative_keyword_added",
            "negative_keyword_removed",
            "bid_adjusted",
            "budget_reallocated",
            "keyword_paused",
            "keyword_enabled",
            "ad_paused",
            "ad_enabled",
            "campaign_paused",
            "campaign_enabled",
            "search_term_blocked",
            "quality_score_fix",
            "custom",
            name="ai_action_type_enum"
        ),
        nullable=False,
        index=True
    )

    # Action details
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=False)

    # Google Ads entity references
    campaign_id = db.Column(db.String(64), nullable=True, index=True)
    campaign_name = db.Column(db.String(255), nullable=True)
    ad_group_id = db.Column(db.String(64), nullable=True)
    ad_group_name = db.Column(db.String(255), nullable=True)
    keyword_id = db.Column(db.String(64), nullable=True)
    ad_id = db.Column(db.String(64), nullable=True)

    # Change details (before/after values)
    before_value = db.Column(db.JSON, nullable=True)  # e.g., {"bid": 2.50, "status": "ENABLED"}
    after_value = db.Column(db.JSON, nullable=True)   # e.g., {"bid": 3.00, "status": "ENABLED"}

    # Impact metrics
    estimated_monthly_savings = db.Column(db.Float, nullable=True)  # Dollar amount
    estimated_monthly_value = db.Column(db.Float, nullable=True)    # Revenue/lead value
    confidence_score = db.Column(db.Float, nullable=True)           # 0.0 to 1.0

    # Reasoning
    reasoning = db.Column(db.Text, nullable=True)  # Why this action was taken
    data_used = db.Column(db.JSON, nullable=True)  # What data informed the decision

    # Status tracking
    status = db.Column(
        SAEnum("pending", "executed", "failed", "undone", name="ai_action_status_enum"),
        nullable=False,
        default="pending",
        index=True
    )

    # Execution details
    executed_at = db.Column(db.DateTime, nullable=True)
    executed_by = db.Column(db.String(64), nullable=True, default="system")  # "system" or user_id
    execution_error = db.Column(db.Text, nullable=True)

    # Undo tracking
    can_undo = db.Column(db.Boolean, nullable=False, default=True)
    undone_at = db.Column(db.DateTime, nullable=True)
    undone_by = db.Column(db.Integer, nullable=True)  # User ID who undid the action (no FK to avoid constraint issues)
    undo_reason = db.Column(db.String(255), nullable=True)

    # Timestamps
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships (using foreign_keys since no FK constraint)
    account = db.relationship("Account", foreign_keys=[account_id], backref=db.backref("ai_actions", lazy="dynamic"))

    def __repr__(self) -> str:
        return f"<AIAction id={self.id} type={self.action_type} status={self.status}>"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "id": self.id,
            "account_id": self.account_id,
            "action_type": self.action_type,
            "title": self.title,
            "description": self.description,
            "campaign_id": self.campaign_id,
            "campaign_name": self.campaign_name,
            "ad_group_id": self.ad_group_id,
            "ad_group_name": self.ad_group_name,
            "before_value": self.before_value,
            "after_value": self.after_value,
            "estimated_monthly_savings": self.estimated_monthly_savings,
            "estimated_monthly_value": self.estimated_monthly_value,
            "confidence_score": self.confidence_score,
            "reasoning": self.reasoning,
            "status": self.status,
            "executed_at": self.executed_at.isoformat() if self.executed_at else None,
            "can_undo": self.can_undo,
            "undone_at": self.undone_at.isoformat() if self.undone_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    @property
    def is_executed(self) -> bool:
        """Check if action has been executed."""
        return self.status == "executed"

    @property
    def is_undoable(self) -> bool:
        """Check if action can be undone."""
        return self.can_undo and self.status == "executed" and self.undone_at is None

    def mark_executed(self, executed_by: str = "system") -> None:
        """Mark action as executed."""
        self.status = "executed"
        self.executed_at = datetime.utcnow()
        self.executed_by = executed_by

    def mark_failed(self, error: str) -> None:
        """Mark action as failed."""
        self.status = "failed"
        self.execution_error = error

    def mark_undone(self, user_id: Optional[int] = None, reason: Optional[str] = None) -> None:
        """Mark action as undone."""
        self.status = "undone"
        self.undone_at = datetime.utcnow()
        self.undone_by = user_id
        self.undo_reason = reason


class AIActionRule(db.Model):
    """
    Rules that govern when AI should take action automatically.

    Examples:
    - Auto-add negative keywords if search term has < 5% CTR and > $50 spent
    - Auto-pause ads if quality score drops below 3
    - Auto-increase bids if conversion rate > 10% and position > 3
    """
    __tablename__ = "ai_action_rules"

    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, nullable=False, index=True)  # No FK to avoid MySQL constraint issues

    # Rule identification
    rule_name = db.Column(db.String(255), nullable=False)
    action_type = db.Column(db.String(64), nullable=False)  # Same as AIAction.action_type

    # Rule conditions (stored as JSON for flexibility)
    # Example: {"ctr_below": 0.05, "spend_above": 50, "lookback_days": 30}
    conditions = db.Column(db.JSON, nullable=False)

    # Rule actions
    auto_execute = db.Column(db.Boolean, nullable=False, default=True)  # Execute automatically or just suggest
    min_confidence = db.Column(db.Float, nullable=False, default=0.8)   # Minimum confidence to execute

    # Status
    enabled = db.Column(db.Boolean, nullable=False, default=True, index=True)

    # Limits to prevent runaway automation
    max_actions_per_day = db.Column(db.Integer, nullable=False, default=50)
    max_actions_per_campaign = db.Column(db.Integer, nullable=False, default=10)

    # Timestamps
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships (using foreign_keys since no FK constraint)
    account = db.relationship("Account", foreign_keys=[account_id], backref=db.backref("ai_action_rules", lazy="dynamic"))

    def __repr__(self) -> str:
        return f"<AIActionRule id={self.id} name={self.rule_name!r} enabled={self.enabled}>"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "account_id": self.account_id,
            "rule_name": self.rule_name,
            "action_type": self.action_type,
            "conditions": self.conditions,
            "auto_execute": self.auto_execute,
            "min_confidence": self.min_confidence,
            "enabled": self.enabled,
            "max_actions_per_day": self.max_actions_per_day,
            "max_actions_per_campaign": self.max_actions_per_campaign,
        }


def ensure_ai_action_tables():
    """
    Ensure AI action tables exist.
    Creates tables if they don't exist.
    """
    from app import db

    try:
        db.create_all()
        return True
    except Exception as e:
        print(f"Error creating AI action tables: {e}")
        return False
