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
class User(db.Model):
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

    owner_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=True)  # if/when they convert

    # indexes you’ll actually use
    __table_args__ = (
        db.Index("idx_crm_contacts_stage", "stage"),
        db.Index("idx_crm_contacts_email", "email"),
        db.Index("idx_crm_contacts_domain", "domain"),
        db.Index("idx_crm_contacts_created_at", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<CRMContact id={self.id} stage={self.stage!r} business={self.business_name!r}>"
