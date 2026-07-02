# app/models_fbads.py
from __future__ import annotations
from datetime import datetime
from typing import Any, Optional, Dict, List

from sqlalchemy.dialects.mysql import BIGINT, JSON
from app import db


class FBAccount(db.Model):
    """
    Stores Facebook user and selected Page context for an app account.
    """
    __tablename__ = "fb_accounts"

    id = db.Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    account_id = db.Column(db.Integer, index=True, nullable=True)  # your app's account

    fb_user_id = db.Column(db.String(64), index=True, nullable=True)
    email = db.Column(db.String(255), index=True, nullable=True)

    access_token = db.Column(db.String(1024), nullable=True)
    token_expiry = db.Column(db.DateTime, nullable=True)

    page_id = db.Column(db.String(64), index=True, nullable=True)
    page_name = db.Column(db.String(255), nullable=True)
    page_access_token = db.Column(db.String(1024), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow,
                           onupdate=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"<FBAccount id={self.id} acct={self.account_id} page={self.page_name or '-'}>"


class FBLead(db.Model):
    """
    Normalized copy of Facebook Lead Ads submissions.
    """
    __tablename__ = "fb_leads"

    id = db.Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    account_id = db.Column(db.Integer, index=True, nullable=True)

    external_id = db.Column(db.String(128), index=True, nullable=False)  # FB lead id
    page_id = db.Column(db.String(64), index=True, nullable=True)
    form_name = db.Column(db.String(255), nullable=True)

    name = db.Column(db.String(255), nullable=True)
    email = db.Column(db.String(255), nullable=True)
    phone = db.Column(db.String(64), nullable=True)

    created_time = db.Column(db.DateTime, nullable=True)  # from FB payload
    raw = db.Column(JSON, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow,
                           onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        db.UniqueConstraint("account_id", "external_id", name="uq_fb_lead_ext"),
    )

    def __repr__(self) -> str:
        return f"<FBLead id={self.id} acct={self.account_id} ext={self.external_id}>"


class FBProfile(db.Model):
    """
    Cached snapshot of a Facebook Page profile for quick reads and reporting.
    """
    __tablename__ = "fb_profiles"

    id = db.Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    account_id = db.Column(db.Integer, index=True, nullable=True)

    page_id = db.Column(db.String(64), index=True, nullable=False)
    page_name = db.Column(db.String(255), nullable=True)

    about = db.Column(db.Text, nullable=True)
    description = db.Column(db.Text, nullable=True)
    website = db.Column(db.String(512), nullable=True)
    phone = db.Column(db.String(64), nullable=True)
    hours = db.Column(JSON, nullable=True)

    raw = db.Column(JSON, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow,
                           onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        db.UniqueConstraint("account_id", "page_id", name="uq_fb_profile_page"),
    )

    def __repr__(self) -> str:
        return f"<FBProfile id={self.id} acct={self.account_id} page={self.page_id}>"


class FBCampaign(db.Model):
    """
    Local cache of Facebook Ad campaigns, synced daily.
    """
    __tablename__ = "fb_campaigns"

    id = db.Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=False, index=True)

    fb_campaign_id = db.Column(db.String(64), nullable=False, index=True)
    name = db.Column(db.String(255), nullable=True)
    status = db.Column(db.String(32), nullable=True)        # ACTIVE, PAUSED, ARCHIVED
    objective = db.Column(db.String(64), nullable=True)
    daily_budget = db.Column(db.BigInteger, nullable=True)   # in cents
    lifetime_budget = db.Column(db.BigInteger, nullable=True)
    start_time = db.Column(db.DateTime, nullable=True)
    stop_time = db.Column(db.DateTime, nullable=True)
    synced_at = db.Column(db.DateTime, nullable=True)

    __table_args__ = (
        db.UniqueConstraint("account_id", "fb_campaign_id", name="uq_fb_campaign"),
    )

    def __repr__(self) -> str:
        return f"<FBCampaign id={self.id} acct={self.account_id} fb={self.fb_campaign_id} name={self.name!r}>"


class FBAdSet(db.Model):
    """
    Local cache of Facebook Ad sets, synced daily.
    """
    __tablename__ = "fb_adsets"

    id = db.Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=False, index=True)

    fb_adset_id = db.Column(db.String(64), nullable=False, index=True)
    fb_campaign_id = db.Column(db.String(64), nullable=True, index=True)
    name = db.Column(db.String(255), nullable=True)
    status = db.Column(db.String(32), nullable=True)
    daily_budget = db.Column(db.BigInteger, nullable=True)
    bid_amount = db.Column(db.BigInteger, nullable=True)
    synced_at = db.Column(db.DateTime, nullable=True)

    __table_args__ = (
        db.UniqueConstraint("account_id", "fb_adset_id", name="uq_fb_adset"),
    )

    def __repr__(self) -> str:
        return f"<FBAdSet id={self.id} acct={self.account_id} fb={self.fb_adset_id} name={self.name!r}>"


class FBAd(db.Model):
    """
    Local cache of Facebook Ads, synced daily.
    """
    __tablename__ = "fb_ads"

    id = db.Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=False, index=True)

    fb_ad_id = db.Column(db.String(64), nullable=False, index=True)
    fb_adset_id = db.Column(db.String(64), nullable=True, index=True)
    fb_campaign_id = db.Column(db.String(64), nullable=True, index=True)
    name = db.Column(db.String(255), nullable=True)
    status = db.Column(db.String(32), nullable=True)
    synced_at = db.Column(db.DateTime, nullable=True)

    __table_args__ = (
        db.UniqueConstraint("account_id", "fb_ad_id", name="uq_fb_ad"),
    )

    def __repr__(self) -> str:
        return f"<FBAd id={self.id} acct={self.account_id} fb={self.fb_ad_id} name={self.name!r}>"


class FBDailyInsight(db.Model):
    """
    Daily aggregated Facebook Ads insights at the campaign level.
    """
    __tablename__ = "fb_daily_insights"

    id = db.Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=False, index=True)

    fb_campaign_id = db.Column(db.String(64), nullable=True, index=True)
    date = db.Column(db.Date, nullable=False, index=True)
    spend = db.Column(db.Numeric(12, 2), nullable=True)
    impressions = db.Column(db.Integer, nullable=True)
    clicks = db.Column(db.Integer, nullable=True)
    conversions = db.Column(db.Integer, nullable=True)
    leads = db.Column(db.Integer, nullable=True)
    cpm = db.Column(db.Numeric(10, 4), nullable=True)
    cpc = db.Column(db.Numeric(10, 4), nullable=True)
    ctr = db.Column(db.Numeric(8, 4), nullable=True)

    __table_args__ = (
        db.UniqueConstraint("account_id", "fb_campaign_id", "date", name="uq_fb_daily_insight"),
    )

    def __repr__(self) -> str:
        return (
            f"<FBDailyInsight id={self.id} acct={self.account_id} "
            f"camp={self.fb_campaign_id} date={self.date}>"
        )


__all__ = [
    "FBAccount",
    "FBLead",
    "FBProfile",
    "FBCampaign",
    "FBAdSet",
    "FBAd",
    "FBDailyInsight",
]
