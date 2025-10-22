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


class AdsAdGroup(db.Model):
    __tablename__ = "ad_groups"

    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, index=True, nullable=True)

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
    account_id = db.Column(db.Integer, index=True, nullable=True)

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

    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    def __repr__(self):
        return f"<AdsAd {self.id} {self.headline1!r}>"


class AdsKeyword(db.Model):
    __tablename__ = "keywords"

    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, index=True, nullable=True)

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
    entity_type = db.Column(db.String(32), nullable=False, index=True)  # account|campaign|ad_group|ad|keyword
    entity_id = db.Column(db.BigInteger, nullable=False, index=True)
    date = db.Column(db.Date, nullable=False, index=True)

    impressions = db.Column(db.BigInteger, nullable=False, default=0)
    clicks = db.Column(db.BigInteger, nullable=False, default=0)
    cost_micros = db.Column(db.BigInteger, nullable=False, default=0)
    conversions = db.Column(db.Float, nullable=False, default=0.0)
    conversion_value = db.Column(db.Float, nullable=False, default=0.0)
    avg_cpc = db.Column(db.Float, nullable=True)
    search_impr_share = db.Column(db.Float, nullable=True)
    lost_is_budget = db.Column(db.Float, nullable=True)
    lost_is_rank = db.Column(db.Float, nullable=True)

    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    __table_args__ = (db.Index("ix_stats_entity_date", "entity_type", "entity_id", "date"),)


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

    # Legacy fields (for Google Ads)
    scope_type = db.Column(db.String(32), nullable=True)  # 'campaign'|'ad_group'|'keyword'|'ad'|'account'
    scope_id = db.Column(db.BigInteger, nullable=True, index=True)

    # New unified fields (for all Google products)
    source_type = db.Column(db.String(32), nullable=True, index=True)  # 'google_ads'|'google_analytics'|'search_console'
    source_id = db.Column(db.String(255), nullable=True, index=True)  # Property ID, Site URL, Customer ID, etc.

    category = db.Column(db.String(64), nullable=False)  # 'wasted_spend'|'budget'|'bidding'|'content'|'keywords'|...
    title = db.Column(db.String(255), nullable=False)
    details = db.Column(db.Text, nullable=False)
    expected_impact = db.Column(db.String(255), nullable=True)
    severity = db.Column(db.Integer, nullable=False, default=3)  # 1=critical ... 5=long-term

    # Legacy field
    suggested_action_json = db.Column(db.Text, nullable=True)  # JSON payload describing mutations

    # New unified fields
    action_data = db.Column(db.Text, nullable=True)  # JSON action data
    data_points = db.Column(db.Text, nullable=True)  # JSON array of supporting metrics
    confidence = db.Column(db.Float, nullable=True)  # 0.0-1.0 confidence score

    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    status = db.Column(db.String(16), nullable=False, default="open")  # open|applied|dismissed|superseded

    __table_args__ = (
        db.Index("ix_opt_scope", "scope_type", "scope_id"),
        db.Index("ix_opt_source", "source_type", "source_id"),
    )


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

    # Legacy fields (for Google Ads API mutations)
    change_set_json = db.Column(db.Text, nullable=True)  # JSON list of mutations sent to Ads API
    result_json = db.Column(db.Text, nullable=True)       # API response or error payload
    status = db.Column(db.String(16), nullable=True, default="pending")  # pending|success|failed

    # New unified fields
    action_type = db.Column(db.String(16), nullable=True)  # 'applied'|'dismissed'
    notes = db.Column(db.Text, nullable=True)  # Optional notes (e.g., dismissal reason)


class AIPrompt(db.Model):
    """
    Stores AI prompts for different Google product optimization features.
    Allows admins to edit prompts without code changes, and keeps them secure (server-side only).
    """
    __tablename__ = "ai_prompts"

    id = db.Column(db.BigInteger, primary_key=True)

    # Identifier for the prompt (e.g., 'google_ads_main', 'google_analytics_main', 'search_console_main')
    prompt_key = db.Column(db.String(64), unique=True, nullable=False, index=True)

    # Human-readable name
    name = db.Column(db.String(255), nullable=False)

    # Description of what this prompt does
    description = db.Column(db.Text, nullable=True)

    # The actual prompt template
    # Can include placeholders like {data}, {timeframe}, {metrics}, etc.
    prompt_template = db.Column(db.Text, nullable=False)

    # System message (optional, for chat-based models)
    system_message = db.Column(db.Text, nullable=True)

    # Model to use (e.g., 'gpt-4o-mini', 'gpt-4')
    model = db.Column(db.String(64), nullable=False, default='gpt-4o-mini')

    # Temperature setting (0.0 - 2.0)
    temperature = db.Column(db.Float, nullable=False, default=0.7)

    # Max tokens for response
    max_tokens = db.Column(db.Integer, nullable=False, default=2000)

    # Active status
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    # Audit fields
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow, nullable=False)
    updated_by = db.Column(db.BigInteger, nullable=True)  # User ID who last updated

    def __repr__(self):
        return f"<AIPrompt {self.prompt_key}: {self.name}>"
