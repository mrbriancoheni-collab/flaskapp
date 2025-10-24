# app/models_audit.py
"""
Audit log system for tracking important actions and changes.

Tracks:
- Team member changes (invited, joined, removed, role changed)
- Subscription changes (created, upgraded, downgraded, canceled)
- Permission changes
- Security events (login failures, password changes)
- Data access (sensitive operations)
"""

from datetime import datetime
from typing import Optional, Dict, Any
import json

from app import db
from sqlalchemy import func, Index


class AuditLog(db.Model):
    """
    Audit log for tracking user actions and system events.

    Each log entry records who did what, when, and any relevant context.
    """
    __tablename__ = "audit_logs"

    id = db.Column(db.Integer, primary_key=True)

    # Who performed the action
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    # If null, it was a system action

    # Which account this relates to
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=False, index=True)

    # Action details
    action = db.Column(db.String(64), nullable=False, index=True)
    # Examples: 'team.member_invited', 'team.member_removed', 'subscription.created'

    resource_type = db.Column(db.String(64), nullable=True, index=True)
    # Examples: 'user', 'subscription', 'team_invite'

    resource_id = db.Column(db.String(64), nullable=True)
    # ID of the affected resource

    # Additional context (JSON)
    metadata = db.Column(db.JSON, nullable=True)
    # Flexible field for action-specific data

    # IP address and user agent (for security auditing)
    ip_address = db.Column(db.String(45), nullable=True)
    user_agent = db.Column(db.String(255), nullable=True)

    # Timestamp
    created_at = db.Column(db.DateTime, nullable=False, server_default=func.now(), index=True)

    # Indexes for common queries
    __table_args__ = (
        Index('idx_audit_account_action', 'account_id', 'action'),
        Index('idx_audit_user_created', 'user_id', 'created_at'),
        Index('idx_audit_resource', 'resource_type', 'resource_id'),
    )

    def __repr__(self) -> str:
        return f"<AuditLog {self.action} by user={self.user_id} at {self.created_at}>"

    @classmethod
    def log(
        cls,
        action: str,
        account_id: int,
        user_id: Optional[int] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> "AuditLog":
        """
        Create an audit log entry.

        Args:
            action: Action performed (e.g., 'team.member_invited')
            account_id: Account ID
            user_id: User who performed the action (None for system actions)
            resource_type: Type of resource affected
            resource_id: ID of affected resource
            metadata: Additional context as dict
            ip_address: IP address of user
            user_agent: User agent string

        Returns:
            Created AuditLog instance
        """
        log = cls(
            action=action,
            account_id=account_id,
            user_id=user_id,
            resource_type=resource_type,
            resource_id=resource_id,
            metadata=metadata,
            ip_address=ip_address,
            user_agent=user_agent
        )

        db.session.add(log)
        db.session.commit()

        return log

    def to_dict(self) -> Dict[str, Any]:
        """Convert audit log to dictionary."""
        return {
            'id': self.id,
            'user_id': self.user_id,
            'account_id': self.account_id,
            'action': self.action,
            'resource_type': self.resource_type,
            'resource_id': self.resource_id,
            'metadata': self.metadata,
            'ip_address': self.ip_address,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


# Audit action constants
class AuditAction:
    """Constants for audit log actions."""

    # Team actions
    TEAM_MEMBER_INVITED = "team.member_invited"
    TEAM_MEMBER_JOINED = "team.member_joined"
    TEAM_MEMBER_REMOVED = "team.member_removed"
    TEAM_MEMBER_LEFT = "team.member_left"
    TEAM_ROLE_CHANGED = "team.role_changed"
    TEAM_INVITE_REVOKED = "team.invite_revoked"

    # Subscription actions
    SUBSCRIPTION_CREATED = "subscription.created"
    SUBSCRIPTION_UPGRADED = "subscription.upgraded"
    SUBSCRIPTION_DOWNGRADED = "subscription.downgraded"
    SUBSCRIPTION_CANCELED = "subscription.canceled"
    SUBSCRIPTION_REACTIVATED = "subscription.reactivated"

    # Payment actions
    PAYMENT_SUCCESS = "payment.success"
    PAYMENT_FAILED = "payment.failed"

    # Auth actions
    USER_REGISTERED = "auth.user_registered"
    USER_LOGIN = "auth.user_login"
    USER_LOGIN_FAILED = "auth.user_login_failed"
    USER_LOGOUT = "auth.user_logout"
    PASSWORD_CHANGED = "auth.password_changed"
    PASSWORD_RESET_REQUESTED = "auth.password_reset_requested"

    # Account actions
    ACCOUNT_CREATED = "account.created"
    ACCOUNT_UPDATED = "account.updated"
    ACCOUNT_DELETED = "account.deleted"


def ensure_audit_tables():
    """Create audit log table if it doesn't exist (for deployments without Alembic)."""
    with db.engine.begin() as conn:
        conn.execute(db.text("""
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NULL,
            account_id INT NOT NULL,
            action VARCHAR(64) NOT NULL,
            resource_type VARCHAR(64) NULL,
            resource_id VARCHAR(64) NULL,
            metadata JSON NULL,
            ip_address VARCHAR(45) NULL,
            user_agent VARCHAR(255) NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_audit_user (user_id),
            INDEX idx_audit_account (account_id),
            INDEX idx_audit_action (action),
            INDEX idx_audit_resource_type (resource_type),
            INDEX idx_audit_created (created_at),
            INDEX idx_audit_account_action (account_id, action),
            INDEX idx_audit_user_created (user_id, created_at),
            INDEX idx_audit_resource (resource_type, resource_id),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """))


# Helper functions for common audit operations

def log_team_action(action: str, account_id: int, actor_id: int, target_user_id: Optional[int] = None, **kwargs):
    """Log a team-related action."""
    from flask import request

    metadata = kwargs.copy()
    if target_user_id:
        metadata['target_user_id'] = target_user_id

    return AuditLog.log(
        action=action,
        account_id=account_id,
        user_id=actor_id,
        resource_type='user',
        resource_id=str(target_user_id) if target_user_id else None,
        metadata=metadata,
        ip_address=request.remote_addr if request else None,
        user_agent=request.headers.get('User-Agent') if request else None
    )


def log_subscription_action(action: str, account_id: int, user_id: int, subscription_id: str, **kwargs):
    """Log a subscription-related action."""
    from flask import request

    return AuditLog.log(
        action=action,
        account_id=account_id,
        user_id=user_id,
        resource_type='subscription',
        resource_id=subscription_id,
        metadata=kwargs,
        ip_address=request.remote_addr if request else None,
        user_agent=request.headers.get('User-Agent') if request else None
    )


def get_account_activity(account_id: int, limit: int = 50, action_filter: Optional[str] = None):
    """
    Get recent activity for an account.

    Args:
        account_id: Account ID
        limit: Maximum number of entries to return
        action_filter: Optional action prefix to filter by (e.g., 'team.')

    Returns:
        List of AuditLog instances
    """
    query = AuditLog.query.filter_by(account_id=account_id)

    if action_filter:
        query = query.filter(AuditLog.action.like(f"{action_filter}%"))

    return query.order_by(AuditLog.created_at.desc()).limit(limit).all()


def get_user_activity(user_id: int, limit: int = 50):
    """Get recent activity by a specific user."""
    return AuditLog.query.filter_by(user_id=user_id).order_by(
        AuditLog.created_at.desc()
    ).limit(limit).all()
