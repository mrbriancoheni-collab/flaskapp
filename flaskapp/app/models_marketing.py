# app/models_marketing.py
"""
Marketing attribution and channel management models.

MarketingChannel      — named channel (billboard, Google Ads campaign, etc.)
ChannelSpendEntry     — monthly spend logged per channel
ChannelLeadEntry      — monthly lead/booking outcomes per channel
AggregatorAccount     — credentials for lead aggregator platforms (Angi, etc.)
AggregatorLead        — individual leads received from aggregators
MarketingBudget       — monthly total marketing budget cap per account
LeadAttribution       — links a single lead to a channel and job outcome
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.dialects.mysql import JSON as MySQLJSON

from app import db


# ---------------------------------------------------------------------------
# MarketingChannel
# ---------------------------------------------------------------------------

class MarketingChannel(db.Model):
    """
    A named marketing channel for an account.

    channel_type values:
        google_ads | lsa | facebook | yelp | angi | homeadvisor | thumbtack |
        nextdoor | billboard | direct_mail | print | radio | tv | door_hangers |
        organic | referral | other
    """
    __tablename__ = "marketing_channels"

    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False)  # e.g. "Q4 Billboard I-35"
    channel_type = db.Column(db.String(64), nullable=False)  # google_ads|lsa|facebook|…
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    monthly_budget_cents = db.Column(db.Integer, nullable=True)   # budget cap in cents
    notes = db.Column(db.Text, nullable=True)                      # vendor info, contract details
    tracking_phone = db.Column(db.String(32), nullable=True)       # unique phone for this channel
    promo_code = db.Column(db.String(64), nullable=True)           # offline attribution promo code
    vendor_name = db.Column(db.String(255), nullable=True)         # e.g. "Lamar Outdoor"
    start_date = db.Column(db.Date, nullable=True)
    end_date = db.Column(db.Date, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, nullable=False,
        default=datetime.utcnow, onupdate=datetime.utcnow,
    )

    __table_args__ = (
        db.UniqueConstraint("account_id", "name", name="uq_marketing_channel_account_name"),
    )

    # Relationships
    spend_entries = db.relationship(
        "ChannelSpendEntry", back_populates="channel",
        lazy="dynamic", cascade="all, delete-orphan",
    )
    lead_entries = db.relationship(
        "ChannelLeadEntry", back_populates="channel",
        lazy="dynamic", cascade="all, delete-orphan",
    )
    attributions = db.relationship(
        "LeadAttribution", back_populates="channel",
        lazy="dynamic",
    )

    def __repr__(self) -> str:
        return f"<MarketingChannel id={self.id} name={self.name!r} type={self.channel_type}>"


# ---------------------------------------------------------------------------
# ChannelSpendEntry
# ---------------------------------------------------------------------------

class ChannelSpendEntry(db.Model):
    """Monthly ad spend recorded for a specific channel."""
    __tablename__ = "channel_spend_entries"

    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, nullable=False, index=True)
    channel_id = db.Column(
        db.Integer,
        db.ForeignKey("marketing_channels.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    period_month = db.Column(db.Integer, nullable=False)  # 1–12
    period_year = db.Column(db.Integer, nullable=False)
    amount_cents = db.Column(db.Integer, nullable=False)  # spend in cents
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint(
            "channel_id", "period_year", "period_month",
            name="uq_channel_spend_period",
        ),
    )

    channel = db.relationship("MarketingChannel", back_populates="spend_entries")

    def __repr__(self) -> str:
        return (
            f"<ChannelSpendEntry channel_id={self.channel_id} "
            f"{self.period_year}-{self.period_month:02d} "
            f"amount={self.amount_cents}¢>"
        )


# ---------------------------------------------------------------------------
# ChannelLeadEntry
# ---------------------------------------------------------------------------

class ChannelLeadEntry(db.Model):
    """Monthly lead and booking outcomes for a channel."""
    __tablename__ = "channel_lead_entries"

    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, nullable=False, index=True)
    channel_id = db.Column(
        db.Integer,
        db.ForeignKey("marketing_channels.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    period_month = db.Column(db.Integer, nullable=False)  # 1–12
    period_year = db.Column(db.Integer, nullable=False)
    lead_count = db.Column(db.Integer, nullable=False)
    booked_count = db.Column(db.Integer, nullable=False, default=0)  # converted to jobs
    revenue_cents = db.Column(db.Integer, nullable=False, default=0)  # revenue from these leads
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint(
            "channel_id", "period_year", "period_month",
            name="uq_channel_lead_period",
        ),
    )

    channel = db.relationship("MarketingChannel", back_populates="lead_entries")

    def __repr__(self) -> str:
        return (
            f"<ChannelLeadEntry channel_id={self.channel_id} "
            f"{self.period_year}-{self.period_month:02d} "
            f"leads={self.lead_count} booked={self.booked_count}>"
        )


# ---------------------------------------------------------------------------
# AggregatorAccount
# ---------------------------------------------------------------------------

class AggregatorAccount(db.Model):
    """
    Credentials and settings for a lead-aggregator platform account.

    platform values: angi | homeadvisor | thumbtack | nextdoor | bark | houzz
    """
    __tablename__ = "aggregator_accounts"

    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, nullable=False, index=True)
    platform = db.Column(db.String(64), nullable=False)  # angi|homeadvisor|thumbtack|…
    api_key = db.Column(db.String(512), nullable=True)          # encrypted API key
    webhook_secret = db.Column(db.String(255), nullable=True)
    account_external_id = db.Column(db.String(255), nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    monthly_budget_cents = db.Column(db.Integer, nullable=True)
    cost_per_lead_cents = db.Column(db.Integer, nullable=True)  # fixed CPL for this platform
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, nullable=False,
        default=datetime.utcnow, onupdate=datetime.utcnow,
    )

    __table_args__ = (
        db.UniqueConstraint(
            "account_id", "platform",
            name="uq_aggregator_account_platform",
        ),
    )

    leads = db.relationship(
        "AggregatorLead", back_populates="aggregator_account",
        lazy="dynamic", cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<AggregatorAccount id={self.id} platform={self.platform} account={self.account_id}>"


# ---------------------------------------------------------------------------
# AggregatorLead
# ---------------------------------------------------------------------------

class AggregatorLead(db.Model):
    """
    An individual lead received from an aggregator platform.

    status values: new | contacted | booked | lost | disputed
    """
    __tablename__ = "aggregator_leads"

    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, nullable=False, index=True)
    aggregator_account_id = db.Column(
        db.Integer,
        db.ForeignKey("aggregator_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    platform = db.Column(db.String(64), nullable=False, index=True)  # angi|homeadvisor|…
    external_lead_id = db.Column(db.String(255), nullable=True, index=True)
    name = db.Column(db.String(255), nullable=True)
    phone = db.Column(db.String(64), nullable=True)
    email = db.Column(db.String(255), nullable=True)
    service_requested = db.Column(db.String(512), nullable=True)
    city = db.Column(db.String(255), nullable=True)
    zip_code = db.Column(db.String(20), nullable=True)
    lead_cost_cents = db.Column(db.Integer, nullable=True)   # actual cost charged for this lead
    status = db.Column(db.String(32), nullable=False, default="new")  # new|contacted|booked|lost|disputed
    dispute_reason = db.Column(db.Text, nullable=True)
    booked_revenue_cents = db.Column(db.Integer, nullable=True)  # revenue if booked
    occurred_at = db.Column(db.DateTime, nullable=True)
    raw_data = db.Column(MySQLJSON, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, nullable=False,
        default=datetime.utcnow, onupdate=datetime.utcnow,
    )

    __table_args__ = (
        db.UniqueConstraint(
            "account_id", "platform", "external_lead_id",
            name="uq_aggregator_lead_external",
        ),
    )

    aggregator_account = db.relationship("AggregatorAccount", back_populates="leads")

    def __repr__(self) -> str:
        return (
            f"<AggregatorLead id={self.id} platform={self.platform} "
            f"external_id={self.external_lead_id} status={self.status}>"
        )


# ---------------------------------------------------------------------------
# MarketingBudget
# ---------------------------------------------------------------------------

class MarketingBudget(db.Model):
    """Total marketing budget allocated for a given account/month."""
    __tablename__ = "marketing_budgets"

    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, nullable=False, index=True)
    period_year = db.Column(db.Integer, nullable=False)
    period_month = db.Column(db.Integer, nullable=False)  # 1–12
    total_budget_cents = db.Column(db.Integer, nullable=False)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, nullable=False,
        default=datetime.utcnow, onupdate=datetime.utcnow,
    )

    __table_args__ = (
        db.UniqueConstraint(
            "account_id", "period_year", "period_month",
            name="uq_marketing_budget_period",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<MarketingBudget account={self.account_id} "
            f"{self.period_year}-{self.period_month:02d} "
            f"budget={self.total_budget_cents}¢>"
        )


# ---------------------------------------------------------------------------
# LeadAttribution
# ---------------------------------------------------------------------------

class LeadAttribution(db.Model):
    """
    Links a single inbound lead to a marketing channel and its downstream
    job/revenue outcome.

    Soft references (no hard FKs) are used for lead_ingest_id,
    aggregator_lead_id, and call_event_id to avoid cross-table cascade
    complexity and allow partial data.
    """
    __tablename__ = "lead_attributions"

    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, nullable=False, index=True)

    # Channel reference (hard FK, nullable so unattributed leads can be stored)
    channel_id = db.Column(
        db.Integer,
        db.ForeignKey("marketing_channels.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    channel_type = db.Column(db.String(64), nullable=True)   # denormalized for fast queries
    channel_name = db.Column(db.String(255), nullable=True)  # denormalized

    # Lead source identifiers (soft references — no hard FK for safety)
    lead_ingest_id = db.Column(db.Integer, nullable=True)      # FK to lead_ingest.id
    aggregator_lead_id = db.Column(db.Integer, nullable=True)  # FK to aggregator_leads.id
    call_event_id = db.Column(db.Integer, nullable=True)

    # Contact info
    phone = db.Column(db.String(64), nullable=True, index=True)
    email = db.Column(db.String(255), nullable=True)

    # Job outcome
    st_job_id = db.Column(db.Integer, nullable=True)           # ServiceTitan job id if booked
    job_status = db.Column(db.String(50), nullable=True)       # Completed|Scheduled|Canceled
    revenue_cents = db.Column(db.Integer, nullable=True)
    lead_cost_cents = db.Column(db.Integer, nullable=True)     # what was paid for this lead

    # Timing
    lead_occurred_at = db.Column(db.DateTime, nullable=True)
    job_completed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, nullable=False,
        default=datetime.utcnow, onupdate=datetime.utcnow,
    )

    __table_args__ = (
        db.Index("idx_lead_attr_account_channel_type", "account_id", "channel_type"),
        db.Index("idx_lead_attr_account_occurred_at", "account_id", "lead_occurred_at"),
    )

    channel = db.relationship("MarketingChannel", back_populates="attributions")

    def __repr__(self) -> str:
        return (
            f"<LeadAttribution id={self.id} account={self.account_id} "
            f"channel={self.channel_name!r} status={self.job_status}>"
        )
