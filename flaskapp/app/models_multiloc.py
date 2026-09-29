# app/models_multiloc.py
"""
SQLAlchemy models for the multi-location feature.

Tables:
  location_groups        — a named group of FieldSprout accounts
  location_group_members — junction between a group and each member account
  keyword_overlaps       — detected keyword overlap between two accounts in a group
"""
from __future__ import annotations

import datetime as dt

from app import db


def utcnow() -> dt.datetime:
    return dt.datetime.utcnow()


# ---------------------------------------------------------------------------
# LocationGroup
# ---------------------------------------------------------------------------

class LocationGroup(db.Model):
    __tablename__ = "location_groups"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(120), nullable=False)
    primary_account_id = db.Column(db.Integer, nullable=False)
    join_token = db.Column(db.String(64), nullable=False, unique=True)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"<LocationGroup id={self.id} name={self.name!r}>"

    @classmethod
    def ensure_columns(cls) -> None:
        """Add any model columns missing from the live table (safe no-op if up to date)."""
        from flask import current_app
        from sqlalchemy import text, inspect

        needed = {
            "name":               "VARCHAR(120) NOT NULL",
            "primary_account_id": "INT NOT NULL",
            "join_token":         "VARCHAR(64) NOT NULL",
            "created_at":         "DATETIME NOT NULL",
        }
        try:
            existing = {c["name"] for c in inspect(db.engine).get_columns("location_groups")}
            missing = [c for c in needed if c not in existing]
            if not missing:
                return
            clauses = ", ".join(f"ADD COLUMN {c} {needed[c]}" for c in missing)
            with db.engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE location_groups {clauses}"))
            current_app.logger.info("location_groups: added missing columns: %s", missing)
        except Exception as exc:
            current_app.logger.warning("location_groups ensure_columns failed: %s", exc)


# ---------------------------------------------------------------------------
# LocationGroupMember
# ---------------------------------------------------------------------------

class LocationGroupMember(db.Model):
    __tablename__ = "location_group_members"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    group_id = db.Column(db.Integer, db.ForeignKey("location_groups.id"), nullable=False)
    account_id = db.Column(db.Integer, nullable=False)
    location_label = db.Column(db.String(120), nullable=True)
    joined_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    __table_args__ = (
        db.UniqueConstraint("group_id", "account_id", name="uq_lgm_group_account"),
    )

    def __repr__(self) -> str:
        return f"<LocationGroupMember group_id={self.group_id} account_id={self.account_id}>"

    @classmethod
    def ensure_columns(cls) -> None:
        """Add any model columns missing from the live table (safe no-op if up to date)."""
        from flask import current_app
        from sqlalchemy import text, inspect

        needed = {
            "location_label": "VARCHAR(120) NULL",
            "joined_at":      "DATETIME NOT NULL",
        }
        try:
            existing = {c["name"] for c in inspect(db.engine).get_columns("location_group_members")}
            missing = [c for c in needed if c not in existing]
            if not missing:
                return
            clauses = ", ".join(f"ADD COLUMN {c} {needed[c]}" for c in missing)
            with db.engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE location_group_members {clauses}"))
            current_app.logger.info("location_group_members: added missing columns: %s", missing)
        except Exception as exc:
            current_app.logger.warning("location_group_members ensure_columns failed: %s", exc)


# ---------------------------------------------------------------------------
# KeywordOverlap
# ---------------------------------------------------------------------------

class KeywordOverlap(db.Model):
    __tablename__ = "keyword_overlaps"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    group_id = db.Column(db.Integer, db.ForeignKey("location_groups.id"), nullable=False)
    account_id_a = db.Column(db.Integer, nullable=False)
    campaign_id_a = db.Column(db.String(64), nullable=True)
    adgroup_id_a = db.Column(db.String(64), nullable=True)
    account_id_b = db.Column(db.Integer, nullable=False)
    campaign_id_b = db.Column(db.String(64), nullable=True)
    adgroup_id_b = db.Column(db.String(64), nullable=True)
    keyword_text = db.Column(db.String(255), nullable=False)
    match_type = db.Column(db.String(20), nullable=True)
    detected_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    __table_args__ = (
        db.UniqueConstraint(
            "group_id", "account_id_a", "account_id_b", "keyword_text", "match_type",
            name="uq_overlap_group_accounts_kw_match",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<KeywordOverlap group={self.group_id} "
            f"accounts={self.account_id_a}&{self.account_id_b} "
            f"kw={self.keyword_text!r}>"
        )

    @classmethod
    def ensure_columns(cls) -> None:
        """Add any model columns missing from the live table (safe no-op if up to date)."""
        from flask import current_app
        from sqlalchemy import text, inspect

        needed = {
            "campaign_id_a": "VARCHAR(64) NULL",
            "adgroup_id_a":  "VARCHAR(64) NULL",
            "campaign_id_b": "VARCHAR(64) NULL",
            "adgroup_id_b":  "VARCHAR(64) NULL",
            "match_type":    "VARCHAR(20) NULL",
            "detected_at":   "DATETIME NOT NULL",
        }
        try:
            existing = {c["name"] for c in inspect(db.engine).get_columns("keyword_overlaps")}
            missing = [c for c in needed if c not in existing]
            if not missing:
                return
            clauses = ", ".join(f"ADD COLUMN {c} {needed[c]}" for c in missing)
            with db.engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE keyword_overlaps {clauses}"))
            current_app.logger.info("keyword_overlaps: added missing columns: %s", missing)
        except Exception as exc:
            current_app.logger.warning("keyword_overlaps ensure_columns failed: %s", exc)
