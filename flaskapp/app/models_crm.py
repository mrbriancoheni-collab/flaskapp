# app/models_crm.py
"""
CRM integration models — optional component.

CRMConnection  — credentials + config for a connected CRM (ServiceTitan,
                 Jobber, HouseCall Pro, etc.)
CRMJob         — a booked/completed job pulled from the CRM, optionally
                 attributed to a Google Ads campaign via call tracking.

These tables are created lazily (see crm_service._ensure_tables).
No code path requires them to exist — agents fall back to estimated values.
"""
from __future__ import annotations

from datetime import datetime
from app import db


class CRMConnection(db.Model):
    """Credentials and config for one connected CRM account."""
    __tablename__ = "crm_connections"

    id          = db.Column(db.Integer, primary_key=True)
    account_id  = db.Column(db.Integer, nullable=False, index=True)
    provider    = db.Column(db.String(64), nullable=False)   # 'servicetitan' | 'jobber' | 'housecall_pro'
    is_active   = db.Column(db.Boolean, nullable=False, default=True)

    # ServiceTitan specifics
    tenant_id   = db.Column(db.String(128), nullable=True)   # ST tenant/app key
    credentials_json = db.Column(db.JSON, nullable=True)      # access_token, refresh_token, expires_at

    # Sync state
    last_sync_at     = db.Column(db.DateTime, nullable=True)
    last_sync_status = db.Column(db.String(32), nullable=True)  # ok | error
    last_sync_error  = db.Column(db.Text, nullable=True)

    created_at  = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at  = db.Column(db.DateTime, nullable=False, default=datetime.utcnow,
                            onupdate=datetime.utcnow)

    jobs = db.relationship("CRMJob", back_populates="connection",
                           lazy="dynamic", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<CRMConnection account={self.account_id} provider={self.provider}>"


class CRMJob(db.Model):
    """A job/booking record pulled from the connected CRM."""
    __tablename__ = "crm_jobs"

    id              = db.Column(db.Integer, primary_key=True)
    account_id      = db.Column(db.Integer, nullable=False, index=True)
    crm_connection_id = db.Column(db.Integer, db.ForeignKey("crm_connections.id"),
                                  nullable=False, index=True)

    # CRM-side identifiers
    external_job_id = db.Column(db.String(128), nullable=False)
    external_customer_id = db.Column(db.String(128), nullable=True)

    # Job details
    job_type        = db.Column(db.String(255), nullable=True)   # e.g. "AC Repair"
    job_status      = db.Column(db.String(64),  nullable=True)   # booked|scheduled|completed|cancelled
    revenue_cents   = db.Column(db.Integer, nullable=True, default=0)  # job revenue in cents
    job_date        = db.Column(db.Date, nullable=True, index=True)

    # Lead source
    lead_source     = db.Column(db.String(128), nullable=True)   # 'google_ads'|'organic'|'referral'|etc.

    # Attribution — linked to a tracked call and campaign if available
    call_event_id   = db.Column(db.Integer, nullable=True, index=True)  # FK to call_events.id
    campaign_id     = db.Column(db.String(64), nullable=True, index=True)
    campaign_name   = db.Column(db.String(255), nullable=True)

    created_at      = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    synced_at       = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    # Constraints
    __table_args__ = (
        db.UniqueConstraint("crm_connection_id", "external_job_id", name="uq_crm_job"),
    )

    connection = db.relationship("CRMConnection", back_populates="jobs")

    def __repr__(self) -> str:
        return (f"<CRMJob id={self.external_job_id} status={self.job_status} "
                f"revenue=${(self.revenue_cents or 0)/100:.2f}>")

    @property
    def revenue_dollars(self) -> float:
        return round((self.revenue_cents or 0) / 100, 2)
