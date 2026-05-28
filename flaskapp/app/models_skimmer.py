# app/models_skimmer.py
"""
SQLAlchemy models for the Skimmer CRM integration.

Tables:
  skimmer_auth      — per-account Skimmer credentials & settings
  phone_gclid_map   — phone → GCLID look-up built from CallRail/click events
  skimmer_jobs      — imported Skimmer work orders / jobs
"""
from __future__ import annotations

import datetime as dt

from app import db


def utcnow() -> dt.datetime:
    return dt.datetime.utcnow()


def _90days_from_now() -> dt.datetime:
    return dt.datetime.utcnow() + dt.timedelta(days=90)


# ---------------------------------------------------------------------------
# SkimmerAuth
# ---------------------------------------------------------------------------

class SkimmerAuth(db.Model):
    __tablename__ = "skimmer_auth"

    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, unique=True, index=True, nullable=False)

    # Skimmer API credentials
    api_key_encrypted = db.Column(db.Text, nullable=True)

    # Optional webhook secret for Zapier validation
    webhook_secret = db.Column(db.String(128), nullable=True)

    # Sync state
    last_synced_at = db.Column(db.DateTime, nullable=True)
    sync_enabled = db.Column(db.Boolean, default=True, nullable=False)

    # Review request settings
    review_requests_enabled = db.Column(db.Boolean, default=True, nullable=False)
    review_request_delay_hours = db.Column(db.Integer, default=24, nullable=False)
    review_request_template = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"<SkimmerAuth account_id={self.account_id}>"

    @classmethod
    def ensure_columns(cls) -> None:
        """Add any model columns missing from the live table (safe no-op if up to date)."""
        from flask import current_app
        from sqlalchemy import text, inspect

        needed = {
            "webhook_secret":              "VARCHAR(128) NULL",
            "last_synced_at":              "DATETIME NULL",
            "sync_enabled":                "TINYINT(1) NOT NULL DEFAULT 1",
            "review_requests_enabled":     "TINYINT(1) NOT NULL DEFAULT 1",
            "review_request_delay_hours":  "INT NOT NULL DEFAULT 24",
            "review_request_template":     "TEXT NULL",
        }
        try:
            existing = {c["name"] for c in inspect(db.engine).get_columns("skimmer_auth")}
            missing = [c for c in needed if c not in existing]
            if not missing:
                return
            clauses = ", ".join(f"ADD COLUMN {c} {needed[c]}" for c in missing)
            with db.engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE skimmer_auth {clauses}"))
            current_app.logger.info("skimmer_auth: added missing columns: %s", missing)
        except Exception as exc:
            current_app.logger.warning("skimmer_auth ensure_columns failed: %s", exc)


# ---------------------------------------------------------------------------
# PhoneGclidMap
# ---------------------------------------------------------------------------

class PhoneGclidMap(db.Model):
    __tablename__ = "phone_gclid_map"

    id = db.Column(db.BigInteger, primary_key=True)
    account_id = db.Column(db.Integer, index=True, nullable=False)

    # Normalised E.164 phone, e.g. +15551234567
    phone_e164 = db.Column(db.String(20), index=True, nullable=False)

    # Google click identifier
    gclid = db.Column(db.String(255), nullable=False)

    # Optional UTM fields from the originating click
    utm_source = db.Column(db.String(128), nullable=True)
    utm_medium = db.Column(db.String(128), nullable=True)
    utm_campaign = db.Column(db.String(255), nullable=True)
    keyword = db.Column(db.String(255), nullable=True)

    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    expires_at = db.Column(db.DateTime, default=_90days_from_now, nullable=False)

    __table_args__ = (
        db.UniqueConstraint("account_id", "phone_e164", name="uq_phone_gclid"),
        db.Index("ix_phone_gclid_account_phone", "account_id", "phone_e164"),
    )

    def __repr__(self) -> str:
        return f"<PhoneGclidMap {self.phone_e164} → {self.gclid[:12]}…>"

    @classmethod
    def ensure_columns(cls) -> None:
        from flask import current_app
        from sqlalchemy import text, inspect

        needed = {
            "utm_source":   "VARCHAR(128) NULL",
            "utm_medium":   "VARCHAR(128) NULL",
            "utm_campaign": "VARCHAR(255) NULL",
            "keyword":      "VARCHAR(255) NULL",
            "expires_at":   "DATETIME NOT NULL",
        }
        try:
            existing = {c["name"] for c in inspect(db.engine).get_columns("phone_gclid_map")}
            missing = [c for c in needed if c not in existing]
            if not missing:
                return
            clauses = ", ".join(f"ADD COLUMN {c} {needed[c]}" for c in missing)
            with db.engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE phone_gclid_map {clauses}"))
            current_app.logger.info("phone_gclid_map: added missing columns: %s", missing)
        except Exception as exc:
            current_app.logger.warning("phone_gclid_map ensure_columns failed: %s", exc)


# ---------------------------------------------------------------------------
# SkimmerJob
# ---------------------------------------------------------------------------

class SkimmerJob(db.Model):
    __tablename__ = "skimmer_jobs"

    id = db.Column(db.BigInteger, primary_key=True)
    account_id = db.Column(db.Integer, index=True, nullable=False)

    # External identifiers from Skimmer
    skimmer_job_id = db.Column(db.String(128), index=True, nullable=False)
    skimmer_customer_id = db.Column(db.String(128), nullable=True)

    # Customer details
    customer_name = db.Column(db.String(255), nullable=True)
    customer_email = db.Column(db.String(255), nullable=True)
    customer_phone = db.Column(db.String(30), nullable=True)       # raw, as returned by Skimmer
    customer_phone_e164 = db.Column(db.String(20), nullable=True, index=True)  # normalised

    # Job details
    service_address = db.Column(db.String(512), nullable=True)
    service_type = db.Column(db.String(128), nullable=True)
    status = db.Column(db.String(32), default="pending", nullable=False)  # pending|completed|invoiced|paid
    completed_at = db.Column(db.DateTime, nullable=True)
    invoice_total_cents = db.Column(db.Integer, nullable=True)

    # Google Ads matching
    matched_gclid = db.Column(db.String(255), nullable=True)
    offline_conv_pushed_at = db.Column(db.DateTime, nullable=True)
    offline_conv_status = db.Column(db.String(16), nullable=True)  # uploaded|failed

    # Review request
    review_sent_at = db.Column(db.DateTime, nullable=True)

    # Raw API payload for debugging
    raw_json = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    __table_args__ = (
        db.UniqueConstraint("account_id", "skimmer_job_id", name="uq_skimmer_job"),
    )

    def __repr__(self) -> str:
        return f"<SkimmerJob {self.skimmer_job_id} account={self.account_id} status={self.status}>"

    @classmethod
    def ensure_columns(cls) -> None:
        from flask import current_app
        from sqlalchemy import text, inspect

        needed = {
            "skimmer_customer_id":    "VARCHAR(128) NULL",
            "customer_name":          "VARCHAR(255) NULL",
            "customer_email":         "VARCHAR(255) NULL",
            "customer_phone":         "VARCHAR(30) NULL",
            "customer_phone_e164":    "VARCHAR(20) NULL",
            "service_address":        "VARCHAR(512) NULL",
            "service_type":           "VARCHAR(128) NULL",
            "invoice_total_cents":    "INT NULL",
            "matched_gclid":          "VARCHAR(255) NULL",
            "offline_conv_pushed_at": "DATETIME NULL",
            "offline_conv_status":    "VARCHAR(16) NULL",
            "review_sent_at":         "DATETIME NULL",
            "raw_json":               "TEXT NULL",
        }
        try:
            existing = {c["name"] for c in inspect(db.engine).get_columns("skimmer_jobs")}
            missing = [c for c in needed if c not in existing]
            if not missing:
                return
            clauses = ", ".join(f"ADD COLUMN {c} {needed[c]}" for c in missing)
            with db.engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE skimmer_jobs {clauses}"))
            current_app.logger.info("skimmer_jobs: added missing columns: %s", missing)
        except Exception as exc:
            current_app.logger.warning("skimmer_jobs ensure_columns failed: %s", exc)
