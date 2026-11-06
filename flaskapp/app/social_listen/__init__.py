# app/social_listen/__init__.py
"""
Social Listening + AI-assisted posting system.

Exports social_listen_bp (Blueprint) registered at /admin/social-listen.
"""
from __future__ import annotations

from app.social_listen.routes import social_listen_bp  # noqa: F401

__all__ = ["social_listen_bp"]
