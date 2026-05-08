# app/models_ads.py
from __future__ import annotations

import datetime as dt
from app import db


def utcnow():
    return dt.datetime.utcnow()


# ---------------------------------------------------------------------------
# Core Google Ads hierarchy – mapped to your existing table names
#   ads_campaigns, ad_groups, ads, keywords
# ---------------------------------------------------------------------------

class AdsCampaign(db.Model):
    __tablename__ = "ads_campaigns"

    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, index=True, nullable=True)

    name = db.Column(db.String(200), nullable=False)
    objective = db.Column(db.String(50), nullable=True)  # e.g., "LEADS", "SALES"
    status = db.Column(db.String(20), nullable=False, default="enabled")  # enabled|paused|removed|draft
    daily_budget_cents = db.Column(db.Integer, nullable=False, default=0)
    network = db.Column(db.String(40), nullable=True)  # "SEARCH" | "DISPLAY" | "PMax" etc.
    language = db.Column(db.String(10), nullable=True, default="en")
    geo_targets = db.Column(db.Text, nullable=True)  # JSON list of geo codes or names

    start_date = db.Column(db.Date, nullable=True)
    end_date = db.Column(db.Date, nullable=True)

    # Bid strategy (item 9)
    bid_strategy = db.Column(db.String(32), nullable=True, default="manual_cpc")
    # manual_cpc | target_cpa | target_roas | maximize_conversions | maximize_conversion_value | enhanced_cpc
    target_cpa_micros = db.Column(db.BigInteger, nullable=True)   # e.g. 5000000 = $5 CPA
    target_roas = db.Column(db.Float, nullable=True)              # e.g. 4.0 = 400% ROAS

    # External IDs (optional)
    google_customer_id = db.Column(db.String(32), nullable=True, index=True)
    google_campaign_id = db.Column(db.String(64), nullable=True, index=True)

    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    ad_groups = db.relationship(
        "AdsAdGroup",
        backref="campaign",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self):
        return f"<AdsCampaign {self.id} {self.name!r}>"

    @classmethod
    def ensure_columns(cls) -> None:
        """Add any model columns that are missing from the live table (safe no-op if up to date)."""
        from flask import current_app
        from sqlalchemy import text, inspect
        needed = {
            "bid_strategy":      "VARCHAR(32) NULL DEFAULT 'manual_cpc'",
            "target_cpa_micros": "BIGINT NULL",
            "target_roas":       "FLOAT NULL",
        }
        try:
            existing = {c["name"] for c in inspect(db.engine).get_columns("ads_campaigns")}
            missing = [c for c in needed if c not in existing]
            if not missing:
                return
            clauses = ", ".join(f"ADD COLUMN {c} {needed[c]}" for c in missing)
            with db.engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE ads_campaigns {clauses}"))
            current_app.logger.info("ads_campaigns: added missing columns: %s", missing)
        except Exception as exc:
            current_app.logger.warning("ads_campaigns ensure_columns failed: %s", exc)


class AdsAdGroup(db.Model):
    __tablename__ = "ad_groups"

    id = db.Column(db.Integer, primary_key=True)

    campaign_id = db.Column(
        db.Integer,
        db.ForeignKey("ads_campaigns.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = db.Column(db.String(200), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="enabled")  # enabled|paused|removed|draft
    max_cpc_cents = db.Column(db.Integer, nullable=True)  # optional per-click max

    google_ad_group_id = db.Column(db.String(64), nullable=True, index=True)

    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    ads = db.relationship("AdsAd", backref="ad_group", cascade="all, delete-orphan", lazy="selectin")
    keywords = db.relationship("AdsKeyword", backref="ad_group", cascade="all, delete-orphan", lazy="selectin")

    def __repr__(self):
        return f"<AdsAdGroup {self.id} {self.name!r}>"


class AdsAd(db.Model):
    __tablename__ = "ads"

    id = db.Column(db.Integer, primary_key=True)

    ad_group_id = db.Column(
        db.Integer,
        db.ForeignKey("ad_groups.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status = db.Column(db.String(20), nullable=False, default="enabled")  # enabled|paused|removed|draft
    ad_type = db.Column(db.String(20), nullable=False, default="text")  # "text" (RSA), "image", etc.

    headline1 = db.Column(db.String(30), nullable=False)
    headline2 = db.Column(db.String(30), nullable=True)
    headline3 = db.Column(db.String(30), nullable=True)
    description1 = db.Column(db.String(90), nullable=True)
    description2 = db.Column(db.String(90), nullable=True)

    path1 = db.Column(db.String(15), nullable=True)
    path2 = db.Column(db.String(15), nullable=True)
    final_url = db.Column(db.String(2048), nullable=False)

    google_ad_id = db.Column(db.String(64), nullable=True, index=True)

    # A/B testing (item 10)
    variant_group = db.Column(db.String(64), nullable=True, index=True)  # shared test identifier
    is_control = db.Column(db.Boolean, nullable=False, default=False)    # True = control ad
    test_name = db.Column(db.String(128), nullable=True)                 # human label for the test

    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    def __repr__(self):
        return f"<AdsAd {self.id} {self.headline1!r}>"


class AdsKeyword(db.Model):
    __tablename__ = "keywords"

    id = db.Column(db.Integer, primary_key=True)

    ad_group_id = db.Column(
        db.Integer,
        db.ForeignKey("ad_groups.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    text = db.Column(db.String(256), nullable=False)
    match_type = db.Column(db.String(10), nullable=False, default="broad")  # broad|phrase|exact
    status = db.Column(db.String(20), nullable=False, default="enabled")  # enabled|paused|removed
    max_cpc_cents = db.Column(db.Integer, nullable=True)

    google_keyword_id = db.Column(db.String(64), nullable=True, index=True)

    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    __table_args__ = (
        db.UniqueConstraint("ad_group_id", "text", "match_type", name="uq_ads_adgroup_kw"),
    )

    def __repr__(self):
        return f"<AdsKeyword {self.id} {self.text!r}>"


# ---------------------------------------------------------------------------
# Optimizer & reporting schema (table names match your migrations)
# ---------------------------------------------------------------------------

class NegativeKeyword(db.Model):
    __tablename__ = "negative_keywords"

    id = db.Column(db.BigInteger, primary_key=True)
    scope = db.Column(db.String(16), nullable=False)  # ad_group|campaign|list
    campaign_id = db.Column(db.Integer, db.ForeignKey("ads_campaigns.id"), nullable=True, index=True)
    ad_group_id = db.Column(db.Integer, db.ForeignKey("ad_groups.id"), nullable=True, index=True)
    list_id = db.Column(db.BigInteger, db.ForeignKey("shared_negative_lists.id"), nullable=True, index=True)
    text = db.Column(db.String(255), nullable=False)
    match_type = db.Column(db.String(16), nullable=False)  # EXACT|PHRASE|BROAD
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class SharedNegativeList(db.Model):
    __tablename__ = "shared_negative_lists"

    id = db.Column(db.BigInteger, primary_key=True)
    name = db.Column(db.String(255), unique=True, nullable=False)
    description = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    items = db.relationship("SharedNegativeItem", backref="list", cascade="all, delete-orphan", lazy="selectin")


class SharedNegativeItem(db.Model):
    __tablename__ = "shared_negative_items"

    id = db.Column(db.BigInteger, primary_key=True)
    list_id = db.Column(
        db.BigInteger,
        db.ForeignKey("shared_negative_lists.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    text = db.Column(db.String(255), nullable=False)
    match_type = db.Column(db.String(16), nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    __table_args__ = (db.UniqueConstraint("list_id", "text", "match_type", name="uq_list_kw"),)


class SharedNegativeMap(db.Model):
    __tablename__ = "shared_negative_map"

    id = db.Column(db.BigInteger, primary_key=True)
    list_id = db.Column(
        db.BigInteger,
        db.ForeignKey("shared_negative_lists.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    campaign_id = db.Column(
        db.Integer,
        db.ForeignKey("ads_campaigns.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    __table_args__ = (db.UniqueConstraint("list_id", "campaign_id", name="uq_list_campaign"),)


class GadsStatsDaily(db.Model):
    __tablename__ = "gads_stats_daily"

    id = db.Column(db.BigInteger, primary_key=True)
    account_id   = db.Column(db.Integer, nullable=True, index=True)  # local accounts.id
    entity_type  = db.Column(db.String(32), nullable=False, index=True)  # account|campaign|ad_group|keyword
    entity_id    = db.Column(db.BigInteger, nullable=False, index=True)  # local DB id
    google_entity_id = db.Column(db.BigInteger, nullable=True, index=True)  # raw Google Ads resource ID
    date         = db.Column(db.Date, nullable=False, index=True)

    impressions      = db.Column(db.BigInteger, nullable=False, default=0)
    clicks           = db.Column(db.BigInteger, nullable=False, default=0)
    cost_micros      = db.Column(db.BigInteger, nullable=False, default=0)
    conversions      = db.Column(db.Float, nullable=False, default=0.0)
    conversion_value = db.Column(db.Float, nullable=False, default=0.0)
    avg_cpc          = db.Column(db.Float, nullable=True)
    search_impr_share = db.Column(db.Float, nullable=True)
    lost_is_budget   = db.Column(db.Float, nullable=True)
    lost_is_rank     = db.Column(db.Float, nullable=True)

    # Quality Score — populated for entity_type='keyword' rows
    quality_score    = db.Column(db.Integer, nullable=True)   # 1-10
    landing_page_exp = db.Column(db.String(32), nullable=True)  # BELOW_AVERAGE|AVERAGE|ABOVE_AVERAGE
    ad_relevance     = db.Column(db.String(32), nullable=True)
    expected_ctr     = db.Column(db.String(32), nullable=True)

    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    __table_args__ = (
        db.Index("ix_stats_entity_date", "entity_type", "entity_id", "date"),
        db.Index("ix_stats_account_date", "account_id", "date"),
        db.UniqueConstraint("account_id", "entity_type", "google_entity_id", "date",
                            name="uq_gads_stats_daily"),
        {"extend_existing": True},
    )


class SearchTerm(db.Model):
    __tablename__ = "search_terms"

    id = db.Column(db.BigInteger, primary_key=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey("ads_campaigns.id"), nullable=True, index=True)
    ad_group_id = db.Column(db.Integer, db.ForeignKey("ad_groups.id"), nullable=True, index=True)
    keyword_id = db.Column(db.Integer, db.ForeignKey("keywords.id"), nullable=True, index=True)

    search_term = db.Column(db.String(512), nullable=False, index=True)
    clicks = db.Column(db.BigInteger, nullable=False, default=0)
    impressions = db.Column(db.BigInteger, nullable=False, default=0)
    cost_micros = db.Column(db.BigInteger, nullable=False, default=0)
    conversions = db.Column(db.Float, nullable=False, default=0.0)

    added_as_keyword = db.Column(db.Boolean, nullable=False, default=False)
    added_as_negative = db.Column(db.Boolean, nullable=False, default=False)

    date = db.Column(db.Date, nullable=False, default=lambda: dt.date.today())


class Label(db.Model):
    __tablename__ = "labels"

    id = db.Column(db.BigInteger, primary_key=True)
    name = db.Column(db.String(128), unique=True, nullable=False)


class LabelMap(db.Model):
    __tablename__ = "label_map"

    id = db.Column(db.BigInteger, primary_key=True)
    label_id = db.Column(db.BigInteger, db.ForeignKey("labels.id", ondelete="CASCADE"), nullable=False)
    entity_type = db.Column(db.String(32), nullable=False)
    entity_id = db.Column(db.BigInteger, nullable=False)

    __table_args__ = (db.UniqueConstraint("label_id", "entity_type", "entity_id", name="uq_label_entity"),)


class ConversionAction(db.Model):
    """Google Ads conversion actions synced from the API (item 6)."""
    __tablename__ = "conversion_actions"

    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, nullable=False, index=True)

    google_conversion_id = db.Column(db.String(64), nullable=True, index=True)
    name = db.Column(db.String(255), nullable=False)
    category = db.Column(db.String(64), nullable=True)       # PURCHASE, LEAD, SIGNUP, PAGE_VIEW, etc.
    type_ = db.Column("type", db.String(64), nullable=True)  # WEBPAGE, PHONE_CALL, IMPORT, etc.
    status = db.Column(db.String(32), nullable=True)         # ENABLED | REMOVED | HIDDEN
    counting_type = db.Column(db.String(32), nullable=True)  # ONE_PER_CLICK | MANY_PER_CLICK
    value_settings_default = db.Column(db.Float, nullable=True)
    value_settings_currency = db.Column(db.String(8), nullable=True)
    include_in_conversions = db.Column(db.Boolean, nullable=True, default=True)
    click_through_window_days = db.Column(db.Integer, nullable=True)
    view_through_window_days = db.Column(db.Integer, nullable=True)

    # 30-day aggregate totals refreshed on each sync
    conversions_30d = db.Column(db.Float, nullable=True, default=0.0)
    conversion_value_30d = db.Column(db.Float, nullable=True, default=0.0)

    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    __table_args__ = (
        db.UniqueConstraint("account_id", "google_conversion_id", name="uq_conversion_action"),
    )

    def __repr__(self):
        return f"<ConversionAction {self.id} {self.name!r}>"


class Snapshot(db.Model):
    __tablename__ = "snapshots"

    id = db.Column(db.BigInteger, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    entity_type = db.Column(db.String(32), nullable=False)  # e.g., 'account'|'campaign'
    entity_id = db.Column(db.BigInteger, nullable=False)
    payload_json = db.Column(db.Text, nullable=False)
    created_by = db.Column(db.BigInteger, nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)


class OptimizerRecommendation(db.Model):
    __tablename__ = "optimizer_recommendations"

    id = db.Column(db.BigInteger, primary_key=True)
    account_id = db.Column(db.BigInteger, index=True, nullable=True)

    scope_type = db.Column(db.String(32), nullable=False)  # 'campaign'|'ad_group'|'keyword'|'ad'|'account'
    scope_id = db.Column(db.BigInteger, nullable=False, index=True)

    category = db.Column(db.String(64), nullable=False)  # 'wasted_spend'|'budget'|'bidding'|'rsa'|'qs'|...
    title = db.Column(db.String(255), nullable=False)
    details = db.Column(db.Text, nullable=False)
    expected_impact = db.Column(db.String(255), nullable=True)
    severity = db.Column(db.Integer, nullable=False, default=3)  # 1=high ... 5=low
    suggested_action_json = db.Column(db.Text, nullable=False)  # JSON payload describing mutations

    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    status = db.Column(db.String(16), nullable=False, default="open")  # open|applied|ignored

    __table_args__ = (db.Index("ix_opt_scope", "scope_type", "scope_id"),)


class OptimizerAction(db.Model):
    __tablename__ = "optimizer_actions"

    id = db.Column(db.BigInteger, primary_key=True)
    recommendation_id = db.Column(
        db.BigInteger,
        db.ForeignKey("optimizer_recommendations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    applied_by = db.Column(db.BigInteger, nullable=True)
    applied_at = db.Column(db.DateTime, nullable=True)
    change_set_json = db.Column(db.Text, nullable=False)  # JSON list of mutations sent to Ads API
    result_json = db.Column(db.Text, nullable=True)       # API response or error payload
    status = db.Column(db.String(16), nullable=False, default="pending")  # pending|success|failed


# ---------------------------------------------------------------------------
# Performance Metrics (cross-platform)
# ---------------------------------------------------------------------------

class PerformanceMetrics(db.Model):
    """
    Unified storage for historical performance metrics across all platforms.
    Supports Google Ads, Analytics, Search Console, GLSA, GMB, Facebook Ads, etc.
    """
    __tablename__ = "performance_metrics"

    id = db.Column(db.BigInteger, primary_key=True)
    account_id = db.Column(db.BigInteger, nullable=False, index=True)

    # Source identification
    source_type = db.Column(db.String(32), nullable=False, index=True)  # google_ads, google_analytics, glsa, etc.
    source_id = db.Column(db.String(255), nullable=True, index=True)  # Property ID, Customer ID, etc.

    # Time dimension
    date = db.Column(db.Date, nullable=False, index=True)
    timeframe = db.Column(db.String(16), nullable=False, default='daily')  # daily, weekly, monthly

    # Entity hierarchy (optional, for drilldown)
    entity_type = db.Column(db.String(32), nullable=True, index=True)  # account, campaign, ad_group, etc.
    entity_id = db.Column(db.String(255), nullable=True, index=True)
    entity_name = db.Column(db.String(255), nullable=True)

    # Core metrics (flexible JSON for source-specific metrics)
    metrics_json = db.Column(db.Text, nullable=False)

    # Computed aggregates (for quick queries without parsing JSON)
    impressions = db.Column(db.BigInteger, nullable=True)
    clicks = db.Column(db.BigInteger, nullable=True)
    spend = db.Column(db.Float, nullable=True)  # In dollars
    conversions = db.Column(db.Float, nullable=True)

    # Audit fields
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    __table_args__ = (
        # Unique constraint: one record per account/source/entity/date
        db.UniqueConstraint(
            'account_id', 'source_type', 'source_id', 'entity_type', 'entity_id', 'date', 'timeframe',
            name='uq_perf_metrics'
        ),
        db.Index('ix_perf_account_source_date', 'account_id', 'source_type', 'date'),
        db.Index('ix_perf_source_entity_date', 'source_type', 'entity_type', 'date'),
    )

    def __repr__(self):
        return f"<PerformanceMetrics {self.account_id} {self.source_type} {self.date}>"


# ---------------------------------------------------------------------------
# Customer Impact Tracking (Savings & Additional Leads)
# ---------------------------------------------------------------------------

class CustomerImpact(db.Model):
    """
    Tracks the cumulative savings and additional leads generated for each customer
    compared to their pre-FieldSprout baseline.
    """
    __tablename__ = "customer_impact"

    id = db.Column(db.BigInteger, primary_key=True)
    account_id = db.Column(db.BigInteger, nullable=False, index=True, unique=True)

    # Baseline metrics (pre-FieldSprout)
    baseline_start_date = db.Column(db.Date, nullable=True)
    baseline_end_date = db.Column(db.Date, nullable=True)
    baseline_monthly_spend = db.Column(db.Float, nullable=True, default=0)
    baseline_monthly_leads = db.Column(db.Float, nullable=True, default=0)
    baseline_cost_per_lead = db.Column(db.Float, nullable=True, default=0)

    # Current performance
    current_monthly_spend = db.Column(db.Float, nullable=True, default=0)
    current_monthly_leads = db.Column(db.Float, nullable=True, default=0)
    current_cost_per_lead = db.Column(db.Float, nullable=True, default=0)

    # Running totals
    total_savings = db.Column(db.Float, nullable=False, default=0)  # Cumulative savings in dollars
    total_additional_leads = db.Column(db.Float, nullable=False, default=0)  # Cumulative additional leads

    # Monthly tracking
    monthly_savings = db.Column(db.Float, nullable=True, default=0)  # Last calculated monthly savings
    monthly_additional_leads = db.Column(db.Float, nullable=True, default=0)  # Last calculated monthly leads

    # Tracking
    last_calculated_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    def __repr__(self):
        return f"<CustomerImpact account_id={self.account_id} savings=${self.total_savings:.2f} leads=+{self.total_additional_leads:.0f}>"


# ---------------------------------------------------------------------------
# AI Prompts (Dynamic Prompt Management)
# ---------------------------------------------------------------------------

class AIPrompt(db.Model):
    """
    Stores AI prompts for various optimization services.
    Allows dynamic updates without code changes.
    """
    __tablename__ = "ai_prompts"

    id = db.Column(db.Integer, primary_key=True)
    prompt_key = db.Column(db.String(100), nullable=False, unique=True, index=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)

    # Prompt content
    system_message = db.Column(db.Text, nullable=False)
    prompt_template = db.Column(db.Text, nullable=False)

    # Model settings
    model = db.Column(db.String(50), nullable=False, default='gpt-4o-mini')
    temperature = db.Column(db.Float, nullable=False, default=0.7)
    max_tokens = db.Column(db.Integer, nullable=False, default=2000)

    # Status
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    # Tracking
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    def __repr__(self):
        return f"<AIPrompt {self.prompt_key} ({self.name})>"
