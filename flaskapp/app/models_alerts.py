# app/models_alerts.py
"""
Alert system models for Google Ads monitoring.

Provides general-purpose alerting for:
- Paused campaigns
- CPL (Cost Per Lead) spikes
- Quality Score drops
- Custom alerts

Budget alerts are handled separately in BudgetAlert model (models.py).
"""

from datetime import datetime
from typing import Optional, Dict, Any
import json

from sqlalchemy import Enum as SAEnum, Index
from app import db


class Alert(db.Model):
    """
    General-purpose alert for Google Ads monitoring.

    Tracks various alert types:
    - paused_campaign: Campaign or ad group is paused
    - cpl_spike: Cost per lead increased significantly
    - quality_score_drop: Quality score dropped below threshold
    - custom: User-defined custom alerts
    """
    __tablename__ = "alerts"

    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)

    # Alert classification
    alert_type = db.Column(
        SAEnum(
            "paused_campaign",
            "cpl_spike",
            "quality_score_drop",
            "custom",
            name="alert_type_enum"
        ),
        nullable=False,
        index=True
    )
    severity = db.Column(
        SAEnum("info", "warning", "critical", name="alert_severity_enum_general"),
        nullable=False,
        default="warning",
        index=True
    )

    # Alert content
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=False)

    # Alert-specific data stored as JSON
    # Examples:
    # - paused_campaign: {"campaign_id": "123", "campaign_name": "Summer Sale", "paused_at": "2025-01-01"}
    # - cpl_spike: {"campaign_id": "123", "old_cpl": 45.50, "new_cpl": 65.00, "change_pct": 42.9}
    # - quality_score_drop: {"campaign_id": "123", "old_qs": 7, "new_qs": 4, "keywords_affected": 15}
    data = db.Column(db.JSON, nullable=True)

    # Status tracking
    status = db.Column(
        SAEnum("active", "resolved", "dismissed", name="alert_status_enum"),
        nullable=False,
        default="active",
        index=True
    )

    # Timestamps
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    resolved_at = db.Column(db.DateTime, nullable=True)
    dismissed_at = db.Column(db.DateTime, nullable=True)

    # Notification tracking
    notified_at = db.Column(db.DateTime, nullable=True)
    email_sent = db.Column(db.Boolean, nullable=False, default=False)

    # Action URL (optional - link to fix the issue)
    action_url = db.Column(db.String(512), nullable=True)
    action_text = db.Column(db.String(100), nullable=True)  # e.g., "Enable Campaign", "Review Keywords"

    # Relationships
    account = db.relationship("Account", backref=db.backref("alerts", lazy="dynamic"))
    user = db.relationship("User", backref=db.backref("alerts", lazy="dynamic"))

    # Indexes
    __table_args__ = (
        Index("idx_alerts_account_status", "account_id", "status"),
        Index("idx_alerts_user_status", "user_id", "status"),
        Index("idx_alerts_type_status", "alert_type", "status"),
        Index("idx_alerts_created", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<Alert id={self.id} type={self.alert_type} severity={self.severity} status={self.status}>"

    def to_dict(self) -> Dict[str, Any]:
        """Convert alert to dictionary for API responses."""
        return {
            "id": self.id,
            "account_id": self.account_id,
            "user_id": self.user_id,
            "alert_type": self.alert_type,
            "severity": self.severity,
            "title": self.title,
            "description": self.description,
            "data": self.data,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "notified_at": self.notified_at.isoformat() if self.notified_at else None,
            "email_sent": self.email_sent,
            "action_url": self.action_url,
            "action_text": self.action_text,
        }

    @property
    def is_active(self) -> bool:
        """Check if alert is still active."""
        return self.status == "active"

    @property
    def age_hours(self) -> float:
        """Get age of alert in hours."""
        if not self.created_at:
            return 0
        return (datetime.utcnow() - self.created_at).total_seconds() / 3600

    def resolve(self) -> None:
        """Mark alert as resolved."""
        self.status = "resolved"
        self.resolved_at = datetime.utcnow()

    def dismiss(self) -> None:
        """Mark alert as dismissed."""
        self.status = "dismissed"
        self.dismissed_at = datetime.utcnow()

    def mark_notified(self) -> None:
        """Mark alert as notified via email."""
        self.notified_at = datetime.utcnow()
        self.email_sent = True


class AlertSettings(db.Model):
    """
    User preferences for alert system.

    Controls which alerts are enabled and their thresholds.
    """
    __tablename__ = "alert_settings"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, unique=True, index=True)

    # Paused Campaign Alerts
    paused_campaign_enabled = db.Column(db.Boolean, nullable=False, default=True)

    # CPL Spike Alerts
    cpl_spike_enabled = db.Column(db.Boolean, nullable=False, default=True)
    cpl_spike_threshold_percent = db.Column(db.Integer, nullable=False, default=20)  # % increase threshold
    cpl_spike_lookback_days = db.Column(db.Integer, nullable=False, default=7)  # Compare to last N days

    # Quality Score Drop Alerts
    quality_score_enabled = db.Column(db.Boolean, nullable=False, default=True)
    quality_score_threshold = db.Column(db.Integer, nullable=False, default=5)  # Alert if QS below this

    # Email Notifications
    email_notifications_enabled = db.Column(db.Boolean, nullable=False, default=True)
    email_digest_enabled = db.Column(db.Boolean, nullable=False, default=False)  # Daily digest vs immediate
    email_digest_time = db.Column(db.String(5), nullable=False, default="09:00")  # HH:MM format

    # Alert frequency limits (prevent spam)
    max_alerts_per_day = db.Column(db.Integer, nullable=False, default=10)

    # Timestamps
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user = db.relationship("User", backref=db.backref("alert_settings", uselist=False))

    def __repr__(self) -> str:
        return f"<AlertSettings user_id={self.user_id}>"

    def to_dict(self) -> Dict[str, Any]:
        """Convert settings to dictionary."""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "paused_campaign_enabled": self.paused_campaign_enabled,
            "cpl_spike_enabled": self.cpl_spike_enabled,
            "cpl_spike_threshold_percent": self.cpl_spike_threshold_percent,
            "cpl_spike_lookback_days": self.cpl_spike_lookback_days,
            "quality_score_enabled": self.quality_score_enabled,
            "quality_score_threshold": self.quality_score_threshold,
            "email_notifications_enabled": self.email_notifications_enabled,
            "email_digest_enabled": self.email_digest_enabled,
            "email_digest_time": self.email_digest_time,
            "max_alerts_per_day": self.max_alerts_per_day,
        }

    @classmethod
    def get_or_create_for_user(cls, user_id: int) -> "AlertSettings":
        """Get existing settings or create default settings for user."""
        settings = cls.query.filter_by(user_id=user_id).first()
        if not settings:
            settings = cls(user_id=user_id)
            db.session.add(settings)
            db.session.commit()
        return settings
