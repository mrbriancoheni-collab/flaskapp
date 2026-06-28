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
    job_status      = db.Column(db.String(64),  nullable=True)   # estimate|booked|scheduled|completed|invoiced|cancelled
    revenue_cents   = db.Column(db.Integer, nullable=True, default=0)
    job_date        = db.Column(db.Date, nullable=True, index=True)
    appointment_at  = db.Column(db.DateTime, nullable=True)      # scheduled appointment datetime
    invoiced_at     = db.Column(db.DateTime, nullable=True)      # when invoice was sent

    # Lead source
    lead_source     = db.Column(db.String(128), nullable=True)   # 'google_ads'|'organic'|'referral'|etc.

    # Attribution — linked to a tracked call and campaign if available
    call_event_id   = db.Column(db.Integer, nullable=True, index=True)
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


class CRMEstimate(db.Model):
    """
    A quote/estimate from any connected CRM, or logged manually.

    Lifecycle: sent → viewed → accepted | rejected | expired

    Triggers:
      - on sent:    queue 2-day follow-up SMS/email if no response
      - on accepted: queue appointment confirmation
      - on rejected: optionally queue win-back after 30 days
    """
    __tablename__ = "crm_estimates"

    id                   = db.Column(db.Integer, primary_key=True)
    account_id           = db.Column(db.Integer, nullable=False, index=True)
    crm_connection_id    = db.Column(db.Integer, db.ForeignKey("crm_connections.id"),
                                     nullable=True, index=True)
    external_estimate_id = db.Column(db.String(128), nullable=True)

    # Customer contact info (denormalised for easy automation)
    customer_name        = db.Column(db.String(255), nullable=True)
    customer_email       = db.Column(db.String(255), nullable=True)
    customer_phone       = db.Column(db.String(32),  nullable=True)

    job_type             = db.Column(db.String(255), nullable=True)
    amount_cents         = db.Column(db.Integer, nullable=True, default=0)

    # Status: sent | viewed | accepted | rejected | expired
    status               = db.Column(db.String(32), nullable=False, default="sent", index=True)

    # Timestamps
    sent_at              = db.Column(db.DateTime, nullable=True)
    viewed_at            = db.Column(db.DateTime, nullable=True)
    responded_at         = db.Column(db.DateTime, nullable=True)
    expires_at           = db.Column(db.DateTime, nullable=True)

    # Follow-up tracking — we update these so we don't double-send
    follow_up_1_sent_at  = db.Column(db.DateTime, nullable=True)
    follow_up_2_sent_at  = db.Column(db.DateTime, nullable=True)

    source_provider      = db.Column(db.String(64), nullable=True)  # servicetitan|jobber|housecall_pro|manual
    raw_data             = db.Column(db.JSON, nullable=True)

    created_at           = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at           = db.Column(db.DateTime, nullable=False, default=datetime.utcnow,
                                     onupdate=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint("crm_connection_id", "external_estimate_id",
                            name="uq_crm_estimate"),
    )

    connection = db.relationship("CRMConnection", foreign_keys=[crm_connection_id])

    def __repr__(self) -> str:
        return (f"<CRMEstimate id={self.id} status={self.status} "
                f"customer={self.customer_name} amount=${(self.amount_cents or 0)/100:.2f}>")

    @property
    def amount_dollars(self) -> float:
        return round((self.amount_cents or 0) / 100, 2)
