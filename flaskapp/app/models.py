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
from sqlalchemy.ext.hybrid import hybrid_property
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

    # NOTE: DB does NOT have this column. Provide a compatibility shim so any
    # code that accesses Account.owner_user_id won’t crash, but SQL never selects it.
    @hybrid_property
    def owner_user_id(self):
        return None

    @owner_user_id.setter
    def owner_user_id(self, _value):
        # no-op: keep setter to avoid AttributeErrors if something assigns to it
        pass

    created_at = db.Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = db.Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    users = db.relationship("User", back_populates="account", cascade="all, delete-orphan")

    # --- Compatibility shim: code can read/write account.plan_code but it hits `plan`
    @hybrid_property
    def plan_code(self):
        return self.plan

    @plan_code.setter
    def plan_code(self, value):
        self.plan = value

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
    @hybrid_property
    def gsc_connected(self):
        return False

    @hybrid_property
    def gsc_property_id(self):
        return None

    @hybrid_property
    def gsc_site_url(self):
        return None

    @hybrid_property
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
