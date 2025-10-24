# app/models_team.py
"""
Team management models for multi-user collaboration.

Supports:
- Team invitations with expiration
- Role-based permissions (owner, admin, member)
- Seat limit enforcement based on subscription plan
"""

from datetime import datetime, timedelta
from typing import Optional
import secrets

from app import db
from sqlalchemy import func


class TeamInvite(db.Model):
    """
    Pending team invitations.

    When a user is invited to join an account, a record is created here.
    The invite includes a unique token sent via email. When the recipient
    clicks the link, they can accept the invite and join the account.
    """
    __tablename__ = "team_invites"

    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=False, index=True)

    # Who was invited
    email = db.Column(db.String(255), nullable=False, index=True)
    role = db.Column(db.String(32), nullable=False, server_default="member")  # owner|admin|member

    # Who sent the invite
    invited_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    # Unique token for accepting invite
    token = db.Column(db.String(64), unique=True, nullable=False, index=True)

    # Status and timestamps
    status = db.Column(db.String(32), nullable=False, server_default="pending", index=True)
    # Status values: pending, accepted, expired, revoked

    created_at = db.Column(db.DateTime, nullable=False, server_default=func.now())
    expires_at = db.Column(db.DateTime, nullable=False)  # Usually 7 days from created_at
    accepted_at = db.Column(db.DateTime, nullable=True)
    revoked_at = db.Column(db.DateTime, nullable=True)

    def __init__(self, **kwargs):
        """Initialize invite with auto-generated token and expiration."""
        super().__init__(**kwargs)

        if not self.token:
            self.token = secrets.token_urlsafe(48)

        if not self.expires_at:
            # Default expiration: 7 days from now
            self.expires_at = datetime.utcnow() + timedelta(days=7)

    def is_valid(self) -> bool:
        """Check if invite is still valid (pending and not expired)."""
        return (
            self.status == "pending"
            and self.expires_at > datetime.utcnow()
        )

    def accept(self, user_id: int):
        """Mark invite as accepted."""
        self.status = "accepted"
        self.accepted_at = datetime.utcnow()

    def revoke(self):
        """Revoke the invite."""
        self.status = "revoked"
        self.revoked_at = datetime.utcnow()

    def __repr__(self) -> str:
        return f"<TeamInvite {self.email} → Account {self.account_id} ({self.status})>"


class TeamMember(db.Model):
    """
    Explicit team membership tracking (optional - can also use User.account_id).

    This table provides additional metadata about team membership beyond
    what's in the User model. Use this if you need to track:
    - When someone joined
    - Custom per-member settings
    - Member-specific permissions beyond role

    Note: The User model already has account_id and role, so this is optional.
    """
    __tablename__ = "team_members"

    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)

    # Additional permissions beyond role (JSON field)
    # Example: {"can_manage_billing": true, "can_invite": false}
    custom_permissions = db.Column(db.JSON, nullable=True)

    joined_at = db.Column(db.DateTime, nullable=False, server_default=func.now())
    last_active_at = db.Column(db.DateTime, nullable=True)

    # Unique constraint: one user per account
    __table_args__ = (
        db.UniqueConstraint('account_id', 'user_id', name='uq_account_user'),
    )

    def __repr__(self) -> str:
        return f"<TeamMember user={self.user_id} account={self.account_id}>"


# Helper functions for role-based permissions

def has_permission(user, permission: str) -> bool:
    """
    Check if user has a specific permission.

    Args:
        user: User model instance
        permission: Permission name (e.g., "manage_billing", "invite_users")

    Returns:
        True if user has permission, False otherwise
    """
    if not user:
        return False

    # Owner has all permissions
    if user.role == "owner":
        return True

    # Define permission matrix
    ROLE_PERMISSIONS = {
        "admin": {
            "invite_users",
            "remove_members",
            "manage_integrations",
            "view_analytics",
            "manage_content",
            "manage_settings",
        },
        "member": {
            "view_analytics",
            "manage_content",
        }
    }

    role_perms = ROLE_PERMISSIONS.get(user.role, set())

    # Check custom permissions if TeamMember exists
    member = TeamMember.query.filter_by(
        account_id=user.account_id,
        user_id=user.id
    ).first()

    if member and member.custom_permissions:
        # Custom permissions can grant additional access
        if member.custom_permissions.get(f"can_{permission}"):
            return True

    return permission in role_perms


def get_account_seat_limit(account) -> Optional[int]:
    """
    Get the seat limit for an account based on their plan.

    Args:
        account: Account model instance

    Returns:
        Number of seats allowed, or None for unlimited
    """
    PLAN_LIMITS = {
        "free": 1,
        "starter": 3,
        "growth": 10,
        "professional": 25,
        "enterprise": None,  # Unlimited
    }

    plan = (account.plan or "free").lower()
    return PLAN_LIMITS.get(plan, 1)  # Default to 1 seat if plan unknown


def get_account_seat_usage(account_id: int) -> int:
    """
    Get current number of seats used for an account.

    Args:
        account_id: Account ID

    Returns:
        Number of active users in the account
    """
    from app.models import User
    return User.query.filter_by(account_id=account_id).count()


def can_add_team_member(account) -> tuple[bool, Optional[str]]:
    """
    Check if account can add another team member.

    Args:
        account: Account model instance

    Returns:
        Tuple of (can_add: bool, error_message: Optional[str])
    """
    seat_limit = get_account_seat_limit(account)

    if seat_limit is None:
        # Unlimited seats
        return True, None

    current_usage = get_account_seat_usage(account.id)

    if current_usage >= seat_limit:
        return False, f"Seat limit reached ({current_usage}/{seat_limit}). Upgrade your plan to add more team members."

    return True, None


def ensure_team_tables():
    """Create team-related tables if they don't exist (for deployments without Alembic)."""
    with db.engine.begin() as conn:
        conn.execute(db.text("""
        CREATE TABLE IF NOT EXISTS team_invites (
            id INT AUTO_INCREMENT PRIMARY KEY,
            account_id INT NOT NULL,
            email VARCHAR(255) NOT NULL,
            role VARCHAR(32) NOT NULL DEFAULT 'member',
            invited_by_user_id INT NOT NULL,
            token VARCHAR(64) NOT NULL UNIQUE,
            status VARCHAR(32) NOT NULL DEFAULT 'pending',
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            expires_at DATETIME NOT NULL,
            accepted_at DATETIME NULL,
            revoked_at DATETIME NULL,
            INDEX idx_team_invite_account (account_id),
            INDEX idx_team_invite_email (email),
            INDEX idx_team_invite_token (token),
            INDEX idx_team_invite_status (status),
            FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE,
            FOREIGN KEY (invited_by_user_id) REFERENCES users(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """))

        conn.execute(db.text("""
        CREATE TABLE IF NOT EXISTS team_members (
            id INT AUTO_INCREMENT PRIMARY KEY,
            account_id INT NOT NULL,
            user_id INT NOT NULL,
            custom_permissions JSON NULL,
            joined_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_active_at DATETIME NULL,
            INDEX idx_team_member_account (account_id),
            INDEX idx_team_member_user (user_id),
            UNIQUE KEY uq_account_user (account_id, user_id),
            FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """))
