# app/models_oauth.py
"""
OAuth Provider Models

Stores OAuth authentication connections for users (Google, Facebook, etc.)
Allows users to sign in with social providers.
"""
from __future__ import annotations
from datetime import datetime
from typing import Optional

from sqlalchemy.dialects.mysql import BIGINT
from app import db


class UserOAuthProvider(db.Model):
    """
    Stores OAuth provider connections for users.

    Allows users to sign in with Google, Facebook, etc.
    Multiple providers can be linked to the same user.
    """
    __tablename__ = "user_oauth_providers"

    id = db.Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)

    # User association
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True, nullable=False)

    # OAuth provider info
    provider = db.Column(db.String(32), nullable=False, index=True)  # 'google', 'facebook', etc.
    provider_user_id = db.Column(db.String(255), nullable=False)  # Provider's unique ID for this user

    # User info from provider
    email = db.Column(db.String(255), nullable=True)
    name = db.Column(db.String(255), nullable=True)
    picture = db.Column(db.String(512), nullable=True)  # Profile picture URL

    # Tokens (optional - not needed for authentication, but useful for API access)
    access_token = db.Column(db.Text, nullable=True)
    refresh_token = db.Column(db.Text, nullable=True)
    token_expires_at = db.Column(db.DateTime, nullable=True)

    # Metadata
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow,
                          onupdate=datetime.utcnow, nullable=False)
    last_login_at = db.Column(db.DateTime, nullable=True)

    # Unique constraint: one provider per user
    __table_args__ = (
        db.UniqueConstraint("user_id", "provider", name="uq_user_provider"),
        db.UniqueConstraint("provider", "provider_user_id", name="uq_provider_user_id"),
    )

    # Relationships
    user = db.relationship("User", backref="oauth_providers")

    def __repr__(self) -> str:
        return f"<UserOAuthProvider user_id={self.user_id} provider={self.provider}>"

    @classmethod
    def get_by_provider(cls, provider: str, provider_user_id: str) -> Optional['UserOAuthProvider']:
        """
        Get OAuth provider record by provider and provider user ID.

        Args:
            provider: Provider name (e.g., 'google')
            provider_user_id: Provider's unique ID for the user

        Returns:
            UserOAuthProvider instance or None
        """
        return cls.query.filter_by(
            provider=provider,
            provider_user_id=provider_user_id
        ).first()

    @classmethod
    def get_by_user(cls, user_id: int, provider: str) -> Optional['UserOAuthProvider']:
        """
        Get OAuth provider record for a user.

        Args:
            user_id: User ID
            provider: Provider name (e.g., 'google')

        Returns:
            UserOAuthProvider instance or None
        """
        return cls.query.filter_by(
            user_id=user_id,
            provider=provider
        ).first()


__all__ = ["UserOAuthProvider"]
