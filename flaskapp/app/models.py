# app/models.py
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Enum as SAEnum,
    Text,
    String,
    Integer,
    Boolean,
    DateTime,
    ForeignKey,
    Float,
)
from sqlalchemy.sql import func
from sqlalchemy import JSON as SAJSON  # generic JSON fallback
from sqlalchemy.dialects.mysql import LONGTEXT
from flask_login import UserMixin  # Add Flask-Login mixin

try:
    # Prefer native MySQL JSON when available
    from sqlalchemy.dialects.mysql import JSON as MySQLJSON  # type: ignore
    JSONType = MySQLJSON
except Exception:  # pragma: no cover
    JSONType = SAJSON

from app import db
# Imported for side-effects/consumers
from app.models_fbads import FBAccount, FBLead, FBProfile  # noqa: F401
from app.models_linkedin import LinkedInScheduledPost  # noqa: F401
from app.models_ads_grader import GoogleAdsGraderReport  # noqa: F401
from app.models_fb_ads_grader import FacebookAdsGraderReport  # noqa: F401
from app.models_oauth import UserOAuthProvider  # noqa: F401
from app.models_tutorials import TutorialPopup, TutorialUserProgress  # noqa: F401
from app.models_leads import LeadCampaign, Lead, EmailSequence, LeadEmail, EmailUnsubscribe  # noqa: F401


# -------------------------
# Account
# -------------------------
class Account(db.Model):
    __tablename__ = "accounts"

    id = db.Column(Integer, primary_key=True)
    name = db.Column(String(150), nullable=False)

    # Optional metadata for plan/billing state
    status = db.Column(String(32), nullable=False, server_default="active")  # active|past_due|canceled

    # Your schema has `plan` (not `plan_code`)
    plan = db.Column(String(50), nullable=True, index=True)

    # NOTE: business_description and business_services columns are added via migration
    # Access them via get_business_description() / get_business_services() methods below

    created_at = db.Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = db.Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    users = db.relationship("User", back_populates="account", cascade="all, delete-orphan")

    # --- Compatibility properties (using @property instead of @hybrid_property)
    @property
    def owner_user_id(self):
        return None

    @property
    def plan_code(self):
        return self.plan

    @property
    def industry(self):
        """Compatibility shim - industry field removed from DB"""
        return None

    def get_business_description(self):
        """Get business_description from DB. Returns None if column doesn't exist yet."""
        from sqlalchemy import text
        try:
            with db.engine.connect() as conn:
                result = conn.execute(
                    text("SELECT business_description FROM accounts WHERE id = :id"),
                    {"id": self.id}
                )
                row = result.fetchone()
                return row[0] if row else None
        except Exception:
            return None

    def get_business_services(self):
        """Get business_services from DB. Returns None if column doesn't exist yet."""
        from sqlalchemy import text
        try:
            with db.engine.connect() as conn:
                result = conn.execute(
                    text("SELECT business_services FROM accounts WHERE id = :id"),
                    {"id": self.id}
                )
                row = result.fetchone()
                return row[0] if row else None
        except Exception:
            return None

    def get_negative_keyword_examples(self):
        """Get negative_keyword_examples from DB. Returns None if column doesn't exist yet."""
        from sqlalchemy import text
        try:
            with db.engine.connect() as conn:
                result = conn.execute(
                    text("SELECT negative_keyword_examples FROM accounts WHERE id = :id"),
                    {"id": self.id}
                )
                row = result.fetchone()
                return row[0] if row else None
        except Exception:
            return None

    @property
    def google_ads_connected(self):
        """
        Compatibility shim - deprecated property.
        NOTE: This property should NOT be used in SQLAlchemy queries.
        Instead, join with GoogleAdsAuth table in your query.
        Returns False to avoid breaking existing code.
        """
        return False

    def __repr__(self) -> str:
        return f"<Account id={self.id} name={self.name!r} status={self.status!r} plan={self.plan!r}>"


# -------------------------
# User
# -------------------------
class User(UserMixin, db.Model):
    """
    User model with Flask-Login integration.
    UserMixin provides: is_authenticated, is_active, is_anonymous, get_id()
    """
    __tablename__ = "users"

    id = db.Column(Integer, primary_key=True)

    # Link to account (matches earlier raw SQL usage of account_id)
    account_id = db.Column(Integer, db.ForeignKey("accounts.id"), index=True, nullable=False)

    name = db.Column(String(120), nullable=False)
    email = db.Column(String(255), unique=True, index=True, nullable=False)
    password_hash = db.Column(String(255), nullable=False)

    # Roles: owner|admin|member
    role = db.Column(String(32), nullable=False, server_default="member", index=True)

    # Email verification flags
    email_verified = db.Column(Boolean, nullable=False, server_default="0")
    email_verified_at = db.Column(DateTime, nullable=True)

    created_at = db.Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = db.Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationship
    account = db.relationship("Account", back_populates="users", lazy="joined")

    # ---- Google Search Console compatibility shims (NOT mapped columns) ----
    @property
    def gsc_connected(self):
        return False

    @property
    def gsc_property_id(self):
        return None

    @property
    def gsc_site_url(self):
        return None

    @property
    def gsc_token_json(self):
        return None

    # ---- Auth helpers ----
    from werkzeug.security import generate_password_hash, check_password_hash  # type: ignore

    def set_password(self, password: str) -> None:
        self.password_hash = self.generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return self.check_password_hash(self.password_hash, password)

    # ---- Convenience ----
    @property
    def is_owner(self) -> bool:
        # No longer depends on accounts.owner_user_id (not in DB)
        return self.role == "owner"

    @property
    def is_admin(self) -> bool:
        # Treat owners and admins as admins
        return self.role in ("owner", "admin")

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email!r} role={self.role!r}>"


# -------------------------
# Admin Audit Log
# -------------------------
class AdminAuditLog(db.Model):
    """
    Tracks admin actions for security and compliance.
    Records who did what, when, and to which resources.
    """
    __tablename__ = "admin_audit_logs"

    id = db.Column(Integer, primary_key=True)
    admin_user_id = db.Column(Integer, ForeignKey("users.id"), nullable=True, index=True)

    # Action details
    action = db.Column(String(64), nullable=False, index=True)
    target_user_id = db.Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    target_account_id = db.Column(Integer, ForeignKey("accounts.id"), nullable=True, index=True)
    note = db.Column(String(1000), nullable=False, server_default="")

    # Request metadata
    ip = db.Column(String(45), nullable=True)
    user_agent = db.Column(String(255), nullable=True)
    created_at = db.Column(DateTime, server_default=func.now(), nullable=False, index=True)

    # Relationships
    admin_user = db.relationship("User", foreign_keys=[admin_user_id], backref="admin_actions")
    target_user = db.relationship("User", foreign_keys=[target_user_id], backref="actions_received")
    target_account = db.relationship("Account", foreign_keys=[target_account_id], backref="admin_actions")

    def __repr__(self) -> str:
        return f"<AdminAuditLog id={self.id} action={self.action!r} admin={self.admin_user_id}>"


# -------------------------
# Plan (simple catalog)
# -------------------------
class Plan(db.Model):
    __tablename__ = "plans"

    id = db.Column(Integer, primary_key=True)

    # A short code you can reference in UI/logic (e.g., 'monthly', 'yearly', 'pro')
    code = db.Column(String(50), unique=True, index=True, nullable=False)
    name = db.Column(String(120), nullable=False)

    # Prices in cents to avoid float issues
    price_month_cents = db.Column(Integer, nullable=True)
    price_year_cents = db.Column(Integer, nullable=True)

    # Stripe price IDs (optional; you may also keep these in env)
    stripe_price_monthly_id = db.Column(String(120), nullable=True, index=True)
    stripe_price_yearly_id = db.Column(String(120), nullable=True, index=True)

    active = db.Column(Boolean, nullable=False, server_default="1")

    created_at = db.Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = db.Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    def __repr__(self) -> str:
        return f"<Plan code={self.code!r} name={self.name!r} active={self.active}>"


# -------------------------
# BusinessProfile (onboarding strategy)
# -------------------------
class BusinessProfile(db.Model):
    __tablename__ = "business_profiles"

    id = db.Column(Integer, primary_key=True)
    account_id = db.Column(Integer, index=True, nullable=False)
    user_id = db.Column(Integer, index=True, nullable=False)

    # Step 1
    business_name = db.Column(String(255), nullable=False, default="Your Business")
    phone = db.Column(String(64))
    website = db.Column(String(255))
    service_area = db.Column(String(512))

    # Step 2
    services = db.Column(JSONType)                # list[str]
    top_services = db.Column(JSONType)            # list[str]
    price_position = db.Column(
        SAEnum("budget", "competitive", "premium", name="price_pos_enum"),
        nullable=True,
    )

    # Step 3
    ideal_customers = db.Column(JSONType)         # list[str]
    urgency = db.Column(SAEnum("emergency", "scheduled", "both", name="urgency_enum"), nullable=True)
    tone = db.Column(SAEnum("friendly", "professional", "direct", name="tone_enum"), nullable=True)
    lead_channels = db.Column(JSONType)           # list[str]

    # Step 4
    why_choose_us = db.Column(Text)               # multiline

    # Step 5
    current_promo = db.Column(String(255))
    hours = db.Column(String(255))

    # Step 6
    primary_goal = db.Column(
        SAEnum("fill_schedule", "steady_recurring", "brand_awareness", "upsell_high_value", name="goal_enum"),
        nullable=True,
    )
    ads_budget = db.Column(
        SAEnum("starter", "growth", "aggressive", name="budget_enum"),
        nullable=True,
    )

    # Step 7
    edge_statement = db.Column(Text)              # multiline
    competitors = db.Column(Text)                 # optional

    # Meta
    approvals_via_email = db.Column(Boolean, default=True)
    status = db.Column(SAEnum("draft", "complete", name="profile_status_enum"), default="draft", nullable=False)
    completed_at = db.Column(DateTime, nullable=True)

    created_at = db.Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def is_complete(self) -> bool:
        return self.status == "complete" and self.completed_at is not None

    def __repr__(self) -> str:
        return f"<BusinessProfile id={self.id} account_id={self.account_id} status={self.status}>"


# -------------------------
# Ads / Workflow tables
# -------------------------
class CampaignDraft(db.Model):
    __tablename__ = "campaign_drafts"

    id = db.Column(Integer, primary_key=True, autoincrement=True)
    account_id = db.Column(Integer, index=True, nullable=False)
    user_id = db.Column(Integer, index=True, nullable=False)
    profile_id = db.Column(Integer, ForeignKey("business_profiles.id"), index=True, nullable=False)

    draft_json = db.Column(JSONType, nullable=False)  # full campaign structure for review/approval
    status = db.Column(
        SAEnum("draft", "approved", "uploaded", name="campaign_draft_status_enum"),
        nullable=False,
        server_default="draft",
    )

    created_at = db.Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"<CampaignDraft id={self.id} status={self.status}>"


class GoogleAdsAuth(db.Model):
    __tablename__ = "google_ads_auth"

    id = db.Column(Integer, primary_key=True, autoincrement=True)
    account_id = db.Column(Integer, index=True, nullable=False)
    user_id = db.Column(Integer, index=True, nullable=False)

    manager_customer_id = db.Column(String(32), nullable=True)
    customer_id = db.Column(String(32), nullable=False)
    refresh_token = db.Column(Text, nullable=False)   # consider encrypting at rest

    created_at = db.Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"<GoogleAdsAuth cid={self.customer_id} user_id={self.user_id}>"


# ---- Heatmap points (generic lead/customer locations) ----
class GeoPoint(db.Model):
    __tablename__ = "geo_points"

    id = db.Column(Integer, primary_key=True)
    account_id = db.Column(Integer, index=True, nullable=False)
    source = db.Column(String(64), index=True)  # 'glsa', 'yelp', 'fb', 'csv', 'manual', etc.
    name = db.Column(String(255))
    email = db.Column(String(255))
    phone = db.Column(String(64))
    address = db.Column(String(255))
    city = db.Column(String(128))
    state = db.Column(String(32))
    zip = db.Column(String(16), index=True)
    lat = db.Column(Float, index=True)
    lng = db.Column(Float, index=True)
    occurred_at = db.Column(DateTime)            # when the lead/job happened
    raw = db.Column(JSONType)                    # original payload if any
    created_at = db.Column(DateTime, server_default=func.now(), nullable=False)

    def __repr__(self) -> str:
        return f"<GeoPoint id={self.id} src={self.source!r} zip={self.zip!r}>"


class CampaignUpload(db.Model):
    __tablename__ = "campaign_uploads"

    id = db.Column(Integer, primary_key=True, autoincrement=True)
    account_id = db.Column(Integer, index=True, nullable=False)
    user_id = db.Column(Integer, index=True, nullable=False)
    campaign_draft_id = db.Column(Integer, ForeignKey("campaign_drafts.id"), index=True, nullable=False)

    upload_status = db.Column(
        SAEnum("pending", "success", "failed", name="campaign_upload_status_enum"),
        nullable=False,
        server_default="pending",
    )
    google_ads_job_id = db.Column(String(128), nullable=True)
    error_text = db.Column(Text, nullable=True)

    created_at = db.Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"<CampaignUpload id={self.id} status={self.upload_status}>"


class PerformanceSnapshot(db.Model):
    __tablename__ = "performance_snapshots"

    id = db.Column(Integer, primary_key=True, autoincrement=True)
    account_id = db.Column(Integer, index=True, nullable=False)
    user_id = db.Column(Integer, index=True, nullable=False)

    customer_id = db.Column(String(32), nullable=False)   # Google Ads CID used for querying
    as_of_date = db.Column(DateTime, default=datetime.utcnow, nullable=False)
    metrics = db.Column(JSONType, nullable=False)         # raw/perf metrics blob

    created_at = db.Column(DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"<PerformanceSnapshot id={self.id} cid={self.customer_id}>"


class Suggestions(db.Model):
    __tablename__ = "suggestions"

    id = db.Column(Integer, primary_key=True, autoincrement=True)
    account_id = db.Column(Integer, index=True, nullable=False)
    user_id = db.Column(Integer, index=True, nullable=False)

    snapshot_id = db.Column(Integer, ForeignKey("performance_snapshots.id"), index=True, nullable=False)
    suggestion_json = db.Column(JSONType, nullable=False)
    accepted = db.Column(Boolean, nullable=False, server_default="0")

    created_at = db.Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"<Suggestions id={self.id} accepted={self.accepted}>"


# -------------------------
# Simple CRM
# -------------------------
CRM_STAGES = (
    "stranger",   # cold
    "lead",       # hand-raise / form / inbound
    "mql",        # marketing qualified
    "sql",        # sales qualified
    "opportunity",
    "customer",
    "churned",
)


class CRMContact(db.Model):
    __tablename__ = "crm_contacts"

    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    stage = db.Column(db.String(24), nullable=False, default="stranger")

    business_name = db.Column(db.String(255), nullable=False)
    contact_name = db.Column(db.String(255))
    email = db.Column(db.String(255))
    phone = db.Column(db.String(64))

    domain = db.Column(db.String(255))
    address1 = db.Column(db.String(255))
    address2 = db.Column(db.String(255))
    city = db.Column(db.String(128))
    region = db.Column(db.String(128))
    postal_code = db.Column(db.String(32))
    country = db.Column(db.String(64))

    source = db.Column(db.String(128))   # where did we get it (optional)
    notes = db.Column(db.Text)

    # Domain crawling tracking
    last_crawled_at = db.Column(db.DateTime, nullable=True)  # when we last crawled their website
    crawl_attempts = db.Column(db.Integer, nullable=False, default=0)  # number of crawl attempts

    owner_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=True)  # if/when they convert

    # indexes you'll actually use
    __table_args__ = (
        db.Index("idx_crm_contacts_stage", "stage"),
        db.Index("idx_crm_contacts_email", "email"),
        db.Index("idx_crm_contacts_domain", "domain"),
        db.Index("idx_crm_contacts_created_at", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<CRMContact id={self.id} stage={self.stage!r} business={self.business_name!r}>"


class CompanyContact(db.Model):
    """
    Individual contacts discovered for a company (CEO, owner, marketing director, etc.)
    Multiple contacts can exist for a single CRMContact (company).
    """
    __tablename__ = "company_contacts"

    id = db.Column(db.Integer, primary_key=True)
    crm_contact_id = db.Column(db.Integer, db.ForeignKey("crm_contacts.id"), nullable=False, index=True)

    # Contact info
    full_name = db.Column(db.String(255), nullable=False)
    title = db.Column(db.String(255))  # CEO, President, Marketing Director, etc.
    email = db.Column(db.String(255))
    phone = db.Column(db.String(64))
    linkedin_url = db.Column(db.String(512))

    # Role categorization
    role_category = db.Column(db.String(50))  # executive, owner, marketing, operations, other

    # Tracking
    source = db.Column(db.String(128))  # where we found them (team page, about page, etc.)
    discovered_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    # Relationship back to company
    crm_contact = db.relationship("CRMContact", backref="contacts")

    # Indexes
    __table_args__ = (
        db.Index("idx_company_contacts_crm", "crm_contact_id"),
        db.Index("idx_company_contacts_role", "role_category"),
        db.Index("idx_company_contacts_email", "email"),
    )

    def __repr__(self) -> str:
        return f"<CompanyContact id={self.id} name={self.full_name!r} title={self.title!r}>"


# -------------------------
# Email Tracking
# -------------------------
class EmailSent(db.Model):
    """
    Tracks each email sent to CRM contacts.
    Used for email campaign performance tracking (opens, clicks, etc.)
    """
    __tablename__ = "emails_sent"

    id = db.Column(db.Integer, primary_key=True)
    crm_contact_id = db.Column(db.Integer, db.ForeignKey("crm_contacts.id"), nullable=False, index=True)
    sent_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)

    # Email content
    subject = db.Column(db.String(500), nullable=False)
    body_html = db.Column(LONGTEXT, nullable=True)  # HTML version
    body_text = db.Column(db.Text, nullable=True)   # Plain text version

    # Tracking
    tracking_token = db.Column(db.String(64), unique=True, nullable=False, index=True)  # unique token for tracking
    campaign_name = db.Column(db.String(255), nullable=True, index=True)  # optional campaign identifier

    # Status
    sent_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    delivered = db.Column(db.Boolean, nullable=False, default=True)  # assume delivered unless bounced
    bounced = db.Column(db.Boolean, nullable=False, default=False)
    bounced_at = db.Column(db.DateTime, nullable=True)

    # Relationships
    crm_contact = db.relationship("CRMContact", backref="emails_sent")
    sent_by = db.relationship("User", backref="emails_sent")
    opens = db.relationship("EmailOpen", backref="email", cascade="all, delete-orphan", lazy="dynamic")
    clicks = db.relationship("EmailClick", backref="email", cascade="all, delete-orphan", lazy="dynamic")

    # Computed properties for quick stats
    @property
    def open_count(self) -> int:
        """Total number of opens (can be > 1 per email)"""
        return self.opens.count()

    @property
    def unique_opens(self) -> int:
        """Number of unique opens (first open only)"""
        # Count distinct by grouping on the first open timestamp
        return len(set(o.opened_at.date() for o in self.opens.all())) if self.opens.count() > 0 else 0

    @property
    def was_opened(self) -> bool:
        """Whether email was opened at least once"""
        return self.opens.count() > 0

    @property
    def click_count(self) -> int:
        """Total number of clicks"""
        return self.clicks.count()

    @property
    def was_clicked(self) -> bool:
        """Whether any link was clicked"""
        return self.clicks.count() > 0

    @property
    def first_opened_at(self):
        """Timestamp of first open"""
        first_open = self.opens.order_by(EmailOpen.opened_at.asc()).first()
        return first_open.opened_at if first_open else None

    @property
    def first_clicked_at(self):
        """Timestamp of first click"""
        first_click = self.clicks.order_by(EmailClick.clicked_at.asc()).first()
        return first_click.clicked_at if first_click else None

    # Indexes
    __table_args__ = (
        db.Index("idx_emails_sent_contact", "crm_contact_id"),
        db.Index("idx_emails_sent_user", "sent_by_user_id"),
        db.Index("idx_emails_sent_token", "tracking_token"),
        db.Index("idx_emails_sent_campaign", "campaign_name"),
        db.Index("idx_emails_sent_date", "sent_at"),
    )

    def __repr__(self) -> str:
        return f"<EmailSent id={self.id} to={self.crm_contact_id} subject={self.subject[:30]!r}>"


class EmailOpen(db.Model):
    """
    Tracks when an email is opened (via tracking pixel).
    An email can be opened multiple times.
    """
    __tablename__ = "email_opens"

    id = db.Column(db.Integer, primary_key=True)
    email_sent_id = db.Column(db.Integer, db.ForeignKey("emails_sent.id"), nullable=False, index=True)

    opened_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    ip_address = db.Column(db.String(45), nullable=True)  # IPv4 or IPv6
    user_agent = db.Column(db.String(512), nullable=True)

    # Indexes
    __table_args__ = (
        db.Index("idx_email_opens_email", "email_sent_id"),
        db.Index("idx_email_opens_date", "opened_at"),
    )

    def __repr__(self) -> str:
        return f"<EmailOpen id={self.id} email_id={self.email_sent_id} at={self.opened_at}>"


class EmailClick(db.Model):
    """
    Tracks when a link in an email is clicked.
    Multiple clicks per email are possible (different links or same link multiple times).
    """
    __tablename__ = "email_clicks"

    id = db.Column(db.Integer, primary_key=True)
    email_sent_id = db.Column(db.Integer, db.ForeignKey("emails_sent.id"), nullable=False, index=True)

    clicked_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    url = db.Column(db.String(2048), nullable=False)  # the original destination URL
    ip_address = db.Column(db.String(45), nullable=True)
    user_agent = db.Column(db.String(512), nullable=True)

    # Indexes
    __table_args__ = (
        db.Index("idx_email_clicks_email", "email_sent_id"),
        db.Index("idx_email_clicks_date", "clicked_at"),
    )

    def __repr__(self) -> str:
        return f"<EmailClick id={self.id} email_id={self.email_sent_id} url={self.url[:50]!r}>"


# -------------------------
# User Flow Tracking
# -------------------------
class PageView(db.Model):
    """
    Tracks user page views for analyzing user flow through the site.
    Used to identify conversion funnels, drop-off points, and user journey patterns.
    """
    __tablename__ = "page_views"

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.String(64), nullable=False, index=True)  # browser session ID
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)  # NULL for anonymous

    # Page information
    path = db.Column(db.String(512), nullable=False, index=True)  # e.g., "/", "/pricing", "/signup"
    page_title = db.Column(db.String(255), nullable=True)
    referrer = db.Column(db.String(512), nullable=True)  # previous page URL
    query_string = db.Column(db.String(512), nullable=True)  # URL parameters

    # Timing
    viewed_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    time_on_page = db.Column(db.Integer, nullable=True)  # seconds spent on page (updated when leaving)

    # Technical details
    ip_address = db.Column(db.String(45), nullable=True)
    user_agent = db.Column(db.String(512), nullable=True)
    device_type = db.Column(db.String(20), nullable=True)  # desktop, mobile, tablet
    browser = db.Column(db.String(50), nullable=True)  # chrome, firefox, safari, etc.

    # UTM parameters for marketing attribution
    utm_source = db.Column(db.String(100), nullable=True)
    utm_medium = db.Column(db.String(100), nullable=True)
    utm_campaign = db.Column(db.String(100), nullable=True)
    utm_term = db.Column(db.String(100), nullable=True)
    utm_content = db.Column(db.String(100), nullable=True)

    # Relationships
    user = db.relationship("User", backref="page_views")

    # Indexes for common queries
    __table_args__ = (
        db.Index("idx_page_views_session", "session_id"),
        db.Index("idx_page_views_user", "user_id"),
        db.Index("idx_page_views_path", "path"),
        db.Index("idx_page_views_date", "viewed_at"),
        db.Index("idx_page_views_session_date", "session_id", "viewed_at"),
    )

    def __repr__(self) -> str:
        return f"<PageView id={self.id} session={self.session_id[:8]}... path={self.path!r}>"


# -------------------------
# Budget Tracking
# -------------------------
class BudgetTracker(db.Model):
    """
    Tracks budgets for Google Ads campaigns/accounts.
    Monitors spend vs. budget and generates alerts when thresholds are hit.
    """
    __tablename__ = "budget_trackers"

    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)

    # Google Ads identifiers
    customer_id = db.Column(db.String(32), nullable=False, index=True)  # Google Ads account ID
    campaign_id = db.Column(db.String(32), nullable=True, index=True)  # Optional: specific campaign
    campaign_name = db.Column(db.String(255), nullable=True)  # For display purposes

    # Budget configuration
    budget_type = db.Column(
        SAEnum("monthly", "weekly", "daily", "campaign", name="budget_type_enum"),
        nullable=False,
        default="monthly"
    )
    budget_amount = db.Column(db.Integer, nullable=False)  # in cents

    # Time period
    start_date = db.Column(db.DateTime, nullable=False)
    end_date = db.Column(db.DateTime, nullable=False, index=True)

    # Alert configuration
    alert_threshold_percent = db.Column(db.Integer, nullable=False, default=80)  # Alert at 80% by default
    alert_enabled = db.Column(db.Boolean, nullable=False, default=True)

    # Status
    status = db.Column(
        SAEnum("active", "paused", "completed", "cancelled", name="budget_status_enum"),
        nullable=False,
        default="active",
        index=True
    )

    # Tracking
    last_checked_at = db.Column(db.DateTime, nullable=True)
    last_spend_amount = db.Column(db.Integer, nullable=True)  # Last known spend in cents

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    account = db.relationship("Account", backref="budget_trackers")
    user = db.relationship("User", backref="budget_trackers")
    alerts = db.relationship("BudgetAlert", backref="budget_tracker", cascade="all, delete-orphan", lazy="dynamic")

    # Indexes
    __table_args__ = (
        db.Index("idx_budget_trackers_account", "account_id"),
        db.Index("idx_budget_trackers_customer", "customer_id"),
        db.Index("idx_budget_trackers_status", "status"),
        db.Index("idx_budget_trackers_end_date", "end_date"),
    )

    @property
    def budget_amount_dollars(self):
        """Return budget amount in dollars"""
        return self.budget_amount / 100.0 if self.budget_amount else 0

    @property
    def last_spend_dollars(self):
        """Return last spend amount in dollars"""
        return self.last_spend_amount / 100.0 if self.last_spend_amount else 0

    @property
    def spend_percentage(self):
        """Return percentage of budget spent"""
        if not self.budget_amount or not self.last_spend_amount:
            return 0
        return (self.last_spend_amount / self.budget_amount) * 100

    @property
    def remaining_budget_dollars(self):
        """Return remaining budget in dollars"""
        if not self.budget_amount or not self.last_spend_amount:
            return self.budget_amount_dollars
        return (self.budget_amount - self.last_spend_amount) / 100.0

    def __repr__(self) -> str:
        return f"<BudgetTracker id={self.id} account_id={self.account_id} type={self.budget_type} status={self.status}>"


class BudgetAlert(db.Model):
    """
    Tracks alerts sent for budget tracking.
    Records when users are notified about budget issues.
    """
    __tablename__ = "budget_alerts"

    id = db.Column(db.Integer, primary_key=True)
    budget_tracker_id = db.Column(db.Integer, db.ForeignKey("budget_trackers.id"), nullable=False, index=True)

    # Alert details
    alert_type = db.Column(
        SAEnum("threshold_reached", "overspend", "underspend", "pacing_ahead", "pacing_behind", "budget_depleted", name="budget_alert_type_enum"),
        nullable=False,
        index=True
    )
    alert_message = db.Column(db.Text, nullable=False)
    severity = db.Column(
        SAEnum("info", "warning", "critical", name="alert_severity_enum"),
        nullable=False,
        default="warning"
    )

    # Spend details at time of alert
    spend_amount = db.Column(db.Integer, nullable=False)  # in cents
    budget_amount = db.Column(db.Integer, nullable=False)  # in cents
    spend_percentage = db.Column(db.Float, nullable=False)  # percentage at time of alert

    # Notification tracking
    sent_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    acknowledged = db.Column(db.Boolean, nullable=False, default=False)
    acknowledged_at = db.Column(db.DateTime, nullable=True)
    acknowledged_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    # Indexes
    __table_args__ = (
        db.Index("idx_budget_alerts_tracker", "budget_tracker_id"),
        db.Index("idx_budget_alerts_type", "alert_type"),
        db.Index("idx_budget_alerts_sent", "sent_at"),
        db.Index("idx_budget_alerts_ack", "acknowledged"),
    )

    def __repr__(self) -> str:
        return f"<BudgetAlert id={self.id} tracker_id={self.budget_tracker_id} type={self.alert_type} severity={self.severity}>"


# -------------------------
# Email Workflow System
# -------------------------
class ContactGroup(db.Model):
    """
    Groups for organizing contacts (customers, leads, strangers, friends, associates, etc.)
    Used to segment email campaigns and workflows.
    """
    __tablename__ = "contact_groups"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True, index=True)
    description = db.Column(db.Text, nullable=True)

    # Metadata
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    contacts = db.relationship("CRMContact", secondary="contact_group_members", backref="groups", lazy="dynamic")

    def __repr__(self) -> str:
        return f"<ContactGroup id={self.id} name={self.name!r}>"


class ContactGroupMember(db.Model):
    """
    Junction table linking contacts to groups (many-to-many relationship)
    """
    __tablename__ = "contact_group_members"

    id = db.Column(db.Integer, primary_key=True)
    contact_id = db.Column(db.Integer, db.ForeignKey("crm_contacts.id"), nullable=False, index=True)
    group_id = db.Column(db.Integer, db.ForeignKey("contact_groups.id"), nullable=False, index=True)

    added_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    added_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    __table_args__ = (
        db.UniqueConstraint("contact_id", "group_id", name="uq_contact_group"),
        db.Index("idx_contact_group_members_contact", "contact_id"),
        db.Index("idx_contact_group_members_group", "group_id"),
    )

    def __repr__(self) -> str:
        return f"<ContactGroupMember contact_id={self.contact_id} group_id={self.group_id}>"


class EmailTemplate(db.Model):
    """
    Reusable email templates for campaigns and workflows.
    Supports variable substitution (e.g., {{first_name}}, {{company_name}}).
    """
    __tablename__ = "email_templates"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False, unique=True, index=True)
    description = db.Column(db.Text, nullable=True)

    # Email content
    subject = db.Column(db.String(500), nullable=False)
    body_html = db.Column(LONGTEXT, nullable=True)
    body_text = db.Column(db.Text, nullable=True)

    # Metadata
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Status
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    # Relationships
    created_by = db.relationship("User", backref="email_templates_created")

    def __repr__(self) -> str:
        return f"<EmailTemplate id={self.id} name={self.name!r}>"


class EmailWorkflow(db.Model):
    """
    Automated email workflow/sequence.
    Contains multiple steps (emails) sent over time with delays.
    """
    __tablename__ = "email_workflows"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False, unique=True, index=True)
    description = db.Column(db.Text, nullable=True)

    # Target groups
    target_groups = db.Column(JSONType, nullable=True)  # Array of group IDs this workflow targets

    # Metadata
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Status
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    # Relationships
    created_by = db.relationship("User", backref="email_workflows_created")
    steps = db.relationship("WorkflowStep", backref="workflow", cascade="all, delete-orphan", order_by="WorkflowStep.step_order")
    enrollments = db.relationship("WorkflowEnrollment", backref="workflow", cascade="all, delete-orphan", lazy="dynamic")

    def __repr__(self) -> str:
        return f"<EmailWorkflow id={self.id} name={self.name!r}>"


class WorkflowStep(db.Model):
    """
    Individual step in an email workflow.
    Each step sends an email template after a specified delay from the previous step.
    Supports conditional branching based on email engagement (opens, clicks).
    """
    __tablename__ = "workflow_steps"

    id = db.Column(db.Integer, primary_key=True)
    workflow_id = db.Column(db.Integer, db.ForeignKey("email_workflows.id"), nullable=False, index=True)
    email_template_id = db.Column(db.Integer, db.ForeignKey("email_templates.id"), nullable=False, index=True)

    # Step configuration
    step_order = db.Column(db.Integer, nullable=False)  # 1, 2, 3, etc.
    delay_days = db.Column(db.Integer, nullable=False, default=0)  # days to wait before sending (0 = immediate)
    delay_hours = db.Column(db.Integer, nullable=False, default=0)  # additional hours to wait

    # Conditional branching
    condition_type = db.Column(
        SAEnum("none", "email_opened", "email_not_opened", "link_clicked", name="workflow_condition_type_enum"),
        nullable=False,
        default="none",
        index=True
    )  # What condition to check before sending this step
    condition_wait_hours = db.Column(db.Integer, nullable=False, default=24)  # Hours to wait before checking condition
    alt_email_template_id = db.Column(db.Integer, db.ForeignKey("email_templates.id"), nullable=True)  # Alternative template if condition not met
    condition_data = db.Column(JSONType, nullable=True)  # Additional condition data (e.g., specific URL for link_clicked)

    # Metadata
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    # Relationships
    email_template = db.relationship("EmailTemplate", foreign_keys=[email_template_id], backref="workflow_steps")
    alt_email_template = db.relationship("EmailTemplate", foreign_keys=[alt_email_template_id])

    __table_args__ = (
        db.UniqueConstraint("workflow_id", "step_order", name="uq_workflow_step_order"),
        db.Index("idx_workflow_steps_workflow", "workflow_id"),
        db.Index("idx_workflow_steps_order", "workflow_id", "step_order"),
    )

    def __repr__(self) -> str:
        return f"<WorkflowStep id={self.id} workflow_id={self.workflow_id} order={self.step_order}>"


class WorkflowEnrollment(db.Model):
    """
    Tracks which contacts are enrolled in which workflows.
    Records progress through the workflow steps.
    """
    __tablename__ = "workflow_enrollments"

    id = db.Column(db.Integer, primary_key=True)
    workflow_id = db.Column(db.Integer, db.ForeignKey("email_workflows.id"), nullable=False, index=True)
    crm_contact_id = db.Column(db.Integer, db.ForeignKey("crm_contacts.id"), nullable=False, index=True)

    # Progress tracking
    current_step = db.Column(db.Integer, nullable=False, default=0)  # 0 = not started, 1 = first step sent, etc.
    status = db.Column(
        SAEnum("active", "paused", "completed", "unsubscribed", "bounced", name="workflow_enrollment_status_enum"),
        nullable=False,
        default="active",
        index=True
    )

    # Timing
    enrolled_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    last_email_sent_at = db.Column(db.DateTime, nullable=True)
    next_email_scheduled_at = db.Column(db.DateTime, nullable=True, index=True)  # when to send next email
    step_history = db.Column(JSONType, nullable=True)  # History of which templates were sent at each step
    completed_at = db.Column(db.DateTime, nullable=True)

    # Email tracking for conditional logic
    last_email_sent_id = db.Column(db.Integer, db.ForeignKey("emails_sent.id"), nullable=True, index=True)

    # Metadata
    enrolled_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    # Relationships
    crm_contact = db.relationship("CRMContact", backref="workflow_enrollments")
    enrolled_by = db.relationship("User", backref="workflow_enrollments_created")
    last_email_sent = db.relationship("EmailSent", foreign_keys=[last_email_sent_id])

    __table_args__ = (
        db.UniqueConstraint("workflow_id", "crm_contact_id", name="uq_workflow_enrollment"),
        db.Index("idx_workflow_enrollments_workflow", "workflow_id"),
        db.Index("idx_workflow_enrollments_contact", "crm_contact_id"),
        db.Index("idx_workflow_enrollments_status", "status"),
        db.Index("idx_workflow_enrollments_next_send", "next_email_scheduled_at"),
    )

    def __repr__(self) -> str:
        return f"<WorkflowEnrollment id={self.id} workflow_id={self.workflow_id} contact_id={self.crm_contact_id} status={self.status}>"


# -------------------------
# ServiceTitan Integration
# -------------------------
class ServiceTitanConnection(db.Model):
    """
    Stores ServiceTitan API connection settings per account.
    Each account can have one ServiceTitan connection.
    """
    __tablename__ = "servicetitan_connections"

    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=False, unique=True, index=True)

    # API credentials (should be encrypted in production)
    tenant_id = db.Column(db.String(100), nullable=False)  # ServiceTitan tenant ID
    client_id = db.Column(db.String(255), nullable=False)  # OAuth client ID
    client_secret = db.Column(db.String(255), nullable=False)  # OAuth client secret (encrypt this!)

    # OAuth tokens
    access_token = db.Column(db.Text, nullable=True)  # Current access token
    refresh_token = db.Column(db.Text, nullable=True)  # Refresh token
    token_expires_at = db.Column(db.DateTime, nullable=True)  # When access token expires

    # Connection settings
    app_key = db.Column(db.String(255), nullable=True)  # ServiceTitan app key
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    # Sync settings
    sync_enabled = db.Column(db.Boolean, nullable=False, default=True)
    sync_frequency_hours = db.Column(db.Integer, nullable=False, default=4)  # How often to sync
    last_sync_at = db.Column(db.DateTime, nullable=True)
    next_sync_at = db.Column(db.DateTime, nullable=True)

    # Metadata
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    # Relationships
    account = db.relationship("Account", backref="servicetitan_connection")
    created_by = db.relationship("User", backref="servicetitan_connections_created")

    def __repr__(self) -> str:
        return f"<ServiceTitanConnection id={self.id} account_id={self.account_id} tenant_id={self.tenant_id}>"


class ServiceTitanCustomer(db.Model):
    """
    Stores customer data synced from ServiceTitan.
    Linked to account for multi-tenant support.
    """
    __tablename__ = "servicetitan_customers"

    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=False, index=True)

    # ServiceTitan IDs
    st_customer_id = db.Column(db.BigInteger, nullable=False, index=True)  # ServiceTitan customer ID

    # Customer details
    name = db.Column(db.String(255), nullable=True)
    first_name = db.Column(db.String(100), nullable=True)
    last_name = db.Column(db.String(100), nullable=True)
    email = db.Column(db.String(255), nullable=True, index=True)
    phone = db.Column(db.String(50), nullable=True)

    # Address
    address = db.Column(db.String(255), nullable=True)
    city = db.Column(db.String(100), nullable=True)
    state = db.Column(db.String(50), nullable=True)
    zip_code = db.Column(db.String(20), nullable=True)

    # Customer metrics
    customer_type = db.Column(db.String(50), nullable=True)  # Residential, Commercial, etc.
    lifetime_value = db.Column(db.Numeric(12, 2), nullable=True)  # Total revenue from this customer
    job_count = db.Column(db.Integer, nullable=False, default=0)  # Number of jobs

    # ServiceTitan metadata
    st_data = db.Column(JSONType, nullable=True)  # Full ServiceTitan customer object

    # Timestamps
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    st_created_at = db.Column(db.DateTime, nullable=True)  # When created in ServiceTitan
    st_modified_at = db.Column(db.DateTime, nullable=True)  # When last modified in ServiceTitan

    # Relationships
    account = db.relationship("Account", backref="servicetitan_customers")

    __table_args__ = (
        db.UniqueConstraint("account_id", "st_customer_id", name="uq_st_customer_per_account"),
        db.Index("idx_st_customers_account", "account_id"),
        db.Index("idx_st_customers_st_id", "st_customer_id"),
    )

    def __repr__(self) -> str:
        return f"<ServiceTitanCustomer id={self.id} st_id={self.st_customer_id} name={self.name}>"


class ServiceTitanJobType(db.Model):
    """
    Stores job type/category data from ServiceTitan.
    Used to analyze revenue and performance by service type.
    """
    __tablename__ = "servicetitan_job_types"

    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=False, index=True)

    # ServiceTitan IDs
    st_job_type_id = db.Column(db.BigInteger, nullable=False, index=True)

    # Job type details
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True)

    # Metrics (calculated from jobs)
    avg_revenue = db.Column(db.Numeric(12, 2), nullable=True)
    total_jobs = db.Column(db.Integer, nullable=False, default=0)
    total_revenue = db.Column(db.Numeric(12, 2), nullable=True)

    # ServiceTitan metadata
    st_data = db.Column(JSONType, nullable=True)

    # Timestamps
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    account = db.relationship("Account", backref="servicetitan_job_types")

    __table_args__ = (
        db.UniqueConstraint("account_id", "st_job_type_id", name="uq_st_job_type_per_account"),
        db.Index("idx_st_job_types_account", "account_id"),
    )

    def __repr__(self) -> str:
        return f"<ServiceTitanJobType id={self.id} name={self.name}>"


class ServiceTitanJob(db.Model):
    """
    Stores job/appointment data from ServiceTitan.
    Used for revenue tracking and conversion optimization.
    """
    __tablename__ = "servicetitan_jobs"

    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=False, index=True)

    # ServiceTitan IDs
    st_job_id = db.Column(db.BigInteger, nullable=False, index=True)
    st_customer_id = db.Column(db.BigInteger, nullable=True, index=True)
    st_job_type_id = db.Column(db.BigInteger, nullable=True, index=True)
    st_business_unit_id = db.Column(db.BigInteger, nullable=True)

    # Job details
    job_number = db.Column(db.String(50), nullable=True, index=True)
    job_status = db.Column(db.String(50), nullable=True, index=True)  # Scheduled, In Progress, Completed, Canceled
    job_type_name = db.Column(db.String(255), nullable=True)

    # Financial data
    total_amount = db.Column(db.Numeric(12, 2), nullable=True)  # Total job value
    outstanding_balance = db.Column(db.Numeric(12, 2), nullable=True)
    invoice_amount = db.Column(db.Numeric(12, 2), nullable=True)

    # Dates
    scheduled_date = db.Column(db.DateTime, nullable=True, index=True)
    completed_date = db.Column(db.DateTime, nullable=True, index=True)
    start_date = db.Column(db.DateTime, nullable=True)

    # Lead source tracking (for ads attribution)
    lead_source = db.Column(db.String(255), nullable=True, index=True)  # Where the lead came from
    campaign_name = db.Column(db.String(255), nullable=True)  # Marketing campaign

    # ServiceTitan metadata
    st_data = db.Column(JSONType, nullable=True)  # Full job object

    # Timestamps
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    st_created_at = db.Column(db.DateTime, nullable=True)
    st_modified_at = db.Column(db.DateTime, nullable=True)

    # Relationships
    account = db.relationship("Account", backref=db.backref("servicetitan_jobs", overlaps="customer,jobs"))
    customer = db.relationship(
        "ServiceTitanCustomer",
        foreign_keys=[account_id, st_customer_id],
        primaryjoin="and_(ServiceTitanJob.account_id==ServiceTitanCustomer.account_id, ServiceTitanJob.st_customer_id==ServiceTitanCustomer.st_customer_id)",
        backref=db.backref("jobs", overlaps="account,servicetitan_jobs"),
        uselist=False,
        overlaps="account,servicetitan_jobs"
    )

    __table_args__ = (
        db.UniqueConstraint("account_id", "st_job_id", name="uq_st_job_per_account"),
        db.Index("idx_st_jobs_account", "account_id"),
        db.Index("idx_st_jobs_st_id", "st_job_id"),
        db.Index("idx_st_jobs_customer", "st_customer_id"),
        db.Index("idx_st_jobs_status", "job_status"),
        db.Index("idx_st_jobs_scheduled", "scheduled_date"),
        db.Index("idx_st_jobs_lead_source", "lead_source"),
    )

    def __repr__(self) -> str:
        return f"<ServiceTitanJob id={self.id} job_number={self.job_number} status={self.job_status}>"


class ServiceTitanTechnician(db.Model):
    """
    Stores technician data from ServiceTitan.
    Used for capacity planning and scheduling optimization.
    """
    __tablename__ = "servicetitan_technicians"

    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=False, index=True)

    # ServiceTitan IDs
    st_technician_id = db.Column(db.BigInteger, nullable=False, index=True)
    st_business_unit_id = db.Column(db.BigInteger, nullable=True)

    # Technician details
    name = db.Column(db.String(255), nullable=True)
    email = db.Column(db.String(255), nullable=True)
    phone = db.Column(db.String(50), nullable=True)

    # Status
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    # ServiceTitan metadata
    st_data = db.Column(JSONType, nullable=True)

    # Timestamps
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    account = db.relationship("Account", backref="servicetitan_technicians")

    __table_args__ = (
        db.UniqueConstraint("account_id", "st_technician_id", name="uq_st_technician_per_account"),
        db.Index("idx_st_technicians_account", "account_id"),
    )

    def __repr__(self) -> str:
        return f"<ServiceTitanTechnician id={self.id} name={self.name}>"


class ServiceTitanCapacity(db.Model):
    """
    Stores daily capacity metrics from ServiceTitan.
    Used to optimize ad spend based on available capacity.
    """
    __tablename__ = "servicetitan_capacity"

    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=False, index=True)

    # Date and business unit
    capacity_date = db.Column(db.Date, nullable=False, index=True)
    st_business_unit_id = db.Column(db.BigInteger, nullable=True)
    business_unit_name = db.Column(db.String(255), nullable=True)

    # Capacity metrics
    total_slots = db.Column(db.Integer, nullable=False, default=0)  # Total available appointment slots
    booked_slots = db.Column(db.Integer, nullable=False, default=0)  # Number of booked slots
    available_slots = db.Column(db.Integer, nullable=False, default=0)  # Remaining available slots
    utilization_percent = db.Column(db.Numeric(5, 2), nullable=True)  # Capacity utilization %

    # Technician availability
    total_technicians = db.Column(db.Integer, nullable=False, default=0)
    available_technicians = db.Column(db.Integer, nullable=False, default=0)

    # Revenue metrics for the day
    scheduled_revenue = db.Column(db.Numeric(12, 2), nullable=True)  # Expected revenue from scheduled jobs

    # Calculated field for ads optimization
    capacity_score = db.Column(db.Numeric(5, 2), nullable=True)  # 0-100 score for ad budget adjustment

    # Timestamps
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    account = db.relationship("Account", backref="servicetitan_capacity")

    __table_args__ = (
        db.UniqueConstraint("account_id", "capacity_date", "st_business_unit_id", name="uq_st_capacity_per_day"),
        db.Index("idx_st_capacity_account", "account_id"),
        db.Index("idx_st_capacity_date", "capacity_date"),
    )

    def __repr__(self) -> str:
        return f"<ServiceTitanCapacity id={self.id} date={self.capacity_date} utilization={self.utilization_percent}%>"


class ServiceTitanSyncLog(db.Model):
    """
    Logs all ServiceTitan API sync operations.
    Used for debugging and monitoring data synchronization.
    """
    __tablename__ = "servicetitan_sync_logs"

    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=False, index=True)

    # Sync details
    sync_type = db.Column(db.String(50), nullable=False, index=True)  # customers, jobs, capacity, etc.
    status = db.Column(db.String(50), nullable=False, index=True)  # success, error, partial

    # Timing
    started_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    duration_seconds = db.Column(db.Integer, nullable=True)

    # Results
    records_fetched = db.Column(db.Integer, nullable=True)
    records_created = db.Column(db.Integer, nullable=True)
    records_updated = db.Column(db.Integer, nullable=True)
    records_failed = db.Column(db.Integer, nullable=True)

    # Error details
    error_message = db.Column(db.Text, nullable=True)
    error_details = db.Column(JSONType, nullable=True)

    # API response metadata
    api_calls_made = db.Column(db.Integer, nullable=True)

    # Relationships
    account = db.relationship("Account", backref="servicetitan_sync_logs")

    __table_args__ = (
        db.Index("idx_st_sync_logs_account", "account_id"),
        db.Index("idx_st_sync_logs_type", "sync_type"),
        db.Index("idx_st_sync_logs_started", "started_at"),
    )

    def __repr__(self) -> str:
        return f"<ServiceTitanSyncLog id={self.id} type={self.sync_type} status={self.status}>"
