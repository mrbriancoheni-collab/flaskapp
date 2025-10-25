# app/models_ads_grader.py
"""
Database models for Google Ads Quality Grader.
Stores grader reports and analysis results.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    String,
    Integer,
    DateTime,
    Float,
    Text,
    ForeignKey,
    Boolean,
)
from sqlalchemy.sql import func
from sqlalchemy import JSON as SAJSON

try:
    from sqlalchemy.dialects.mysql import JSON as MySQLJSON
    JSONType = MySQLJSON
except Exception:
    JSONType = SAJSON

from app import db


class GoogleAdsGraderReport(db.Model):
    """
    Stores Google Ads Quality Grader reports.
    Free for all users - no payment required.
    """
    __tablename__ = "google_ads_grader_reports"

    id = db.Column(Integer, primary_key=True)

    # Link to account (optional - can run without account)
    account_id = db.Column(Integer, ForeignKey("accounts.id"), index=True, nullable=True)
    user_id = db.Column(Integer, ForeignKey("users.id"), index=True, nullable=True)

    # Google Ads account info
    google_ads_customer_id = db.Column(String(20), nullable=False, index=True)
    google_ads_account_name = db.Column(String(255), nullable=True)

    # Overall score
    overall_score = db.Column(Float, nullable=False)  # 0-100
    overall_grade = db.Column(String(2), nullable=True)  # A+, A, B+, B, etc.

    # Key metrics
    quality_score_avg = db.Column(Float, nullable=True)
    ctr_avg = db.Column(Float, nullable=True)
    wasted_spend_90d = db.Column(Float, nullable=True)
    projected_waste_12m = db.Column(Float, nullable=True)

    # Account diagnostics
    active_campaigns = db.Column(Integer, nullable=True)
    active_ad_groups = db.Column(Integer, nullable=True)
    active_text_ads = db.Column(Integer, nullable=True)
    active_keywords = db.Column(Integer, nullable=True)
    clicks_90d = db.Column(Integer, nullable=True)
    conversions_90d = db.Column(Integer, nullable=True)
    avg_cpa_90d = db.Column(Float, nullable=True)
    avg_monthly_spend = db.Column(Float, nullable=True)

    # Section scores (0-100)
    wasted_spend_score = db.Column(Float, nullable=True)
    expanded_text_ads_score = db.Column(Float, nullable=True)
    text_ad_optimization_score = db.Column(Float, nullable=True)
    quality_score_optimization_score = db.Column(Float, nullable=True)
    ctr_optimization_score = db.Column(Float, nullable=True)
    account_activity_score = db.Column(Float, nullable=True)
    long_tail_keywords_score = db.Column(Float, nullable=True)
    impression_share_score = db.Column(Float, nullable=True)
    landing_page_score = db.Column(Float, nullable=True)
    mobile_advertising_score = db.Column(Float, nullable=True)

    # Detailed data (JSON)
    detailed_metrics = db.Column(JSONType, nullable=True)
    best_practices = db.Column(JSONType, nullable=True)
    recommendations = db.Column(JSONType, nullable=True)

    # Report metadata
    report_date = db.Column(DateTime, nullable=False, server_default=func.now())
    date_range_start = db.Column(DateTime, nullable=True)
    date_range_end = db.Column(DateTime, nullable=True)

    # Tracking
    pdf_generated = db.Column(Boolean, nullable=False, server_default="0")
    pdf_download_count = db.Column(Integer, nullable=False, server_default="0")

    created_at = db.Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = db.Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    def __repr__(self) -> str:
        return f"<GoogleAdsGraderReport id={self.id} customer_id={self.google_ads_customer_id} score={self.overall_score}>"

    @classmethod
    def get_latest_for_customer(cls, customer_id: str) -> Optional[GoogleAdsGraderReport]:
        """Get the most recent report for a Google Ads customer ID."""
        return cls.query.filter_by(
            google_ads_customer_id=customer_id
        ).order_by(cls.created_at.desc()).first()

    @classmethod
    def get_history_for_customer(cls, customer_id: str, limit: int = 10):
        """Get report history for a Google Ads customer ID."""
        return cls.query.filter_by(
            google_ads_customer_id=customer_id
        ).order_by(cls.created_at.desc()).limit(limit).all()

    @classmethod
    def get_for_account(cls, account_id: int, limit: int = 10):
        """Get reports for a FieldSprout account."""
        return cls.query.filter_by(
            account_id=account_id
        ).order_by(cls.created_at.desc()).limit(limit).all()

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON responses."""
        return {
            "id": self.id,
            "account_id": self.account_id,
            "google_ads_customer_id": self.google_ads_customer_id,
            "google_ads_account_name": self.google_ads_account_name,
            "overall_score": self.overall_score,
            "overall_grade": self.overall_grade,
            "quality_score_avg": self.quality_score_avg,
            "ctr_avg": self.ctr_avg,
            "wasted_spend_90d": self.wasted_spend_90d,
            "projected_waste_12m": self.projected_waste_12m,
            "active_campaigns": self.active_campaigns,
            "active_ad_groups": self.active_ad_groups,
            "active_text_ads": self.active_text_ads,
            "active_keywords": self.active_keywords,
            "clicks_90d": self.clicks_90d,
            "conversions_90d": self.conversions_90d,
            "avg_cpa_90d": self.avg_cpa_90d,
            "avg_monthly_spend": self.avg_monthly_spend,
            "scores": {
                "wasted_spend": self.wasted_spend_score,
                "expanded_text_ads": self.expanded_text_ads_score,
                "text_ad_optimization": self.text_ad_optimization_score,
                "quality_score_optimization": self.quality_score_optimization_score,
                "ctr_optimization": self.ctr_optimization_score,
                "account_activity": self.account_activity_score,
                "long_tail_keywords": self.long_tail_keywords_score,
                "impression_share": self.impression_share_score,
                "landing_page": self.landing_page_score,
                "mobile_advertising": self.mobile_advertising_score,
            },
            "detailed_metrics": self.detailed_metrics,
            "best_practices": self.best_practices,
            "recommendations": self.recommendations,
            "report_date": self.report_date.isoformat() if self.report_date else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def get_grade_letter(self) -> str:
        """Convert numerical score to letter grade."""
        if self.overall_score >= 90:
            return "A+"
        elif self.overall_score >= 85:
            return "A"
        elif self.overall_score >= 80:
            return "A-"
        elif self.overall_score >= 75:
            return "B+"
        elif self.overall_score >= 70:
            return "B"
        elif self.overall_score >= 65:
            return "B-"
        elif self.overall_score >= 60:
            return "C+"
        elif self.overall_score >= 55:
            return "C"
        elif self.overall_score >= 50:
            return "C-"
        elif self.overall_score >= 45:
            return "D+"
        elif self.overall_score >= 40:
            return "D"
        else:
            return "F"
