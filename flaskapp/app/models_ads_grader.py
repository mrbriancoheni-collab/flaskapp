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

    # Sharing
    shareable_token = db.Column(String(64), nullable=True, index=True, unique=True)

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


class GoogleAdsAIAnalysisTracker(db.Model):
    """
    Tracks AI analysis usage per Google Ads customer ID.
    Enforces rate limiting: 1 analysis per account per month for free users.
    """
    __tablename__ = "google_ads_ai_analysis_tracker"

    id = db.Column(Integer, primary_key=True)
    google_ads_customer_id = db.Column(String(20), nullable=False, unique=True, index=True)

    # Last analysis tracking
    last_analysis_at = db.Column(DateTime, nullable=True)
    analysis_count_current_month = db.Column(Integer, nullable=False, server_default="0")
    analysis_count_total = db.Column(Integer, nullable=False, server_default="0")

    # Month tracking (to reset monthly count)
    current_month_year = db.Column(String(7), nullable=True)  # Format: "2025-10"

    # Tracking
    created_at = db.Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = db.Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    def __repr__(self) -> str:
        return f"<GoogleAdsAIAnalysisTracker customer_id={self.google_ads_customer_id} count={self.analysis_count_current_month}>"

    @classmethod
    def can_run_analysis(cls, customer_id: str) -> tuple[bool, Optional[str]]:
        """
        Check if AI analysis can be run for this customer.
        Returns: (allowed, error_message)
        """
        tracker = cls.query.filter_by(google_ads_customer_id=customer_id).first()
        current_month = datetime.utcnow().strftime("%Y-%m")

        if not tracker:
            # First time - allowed
            return True, None

        # Check if month changed (reset counter)
        if tracker.current_month_year != current_month:
            # New month - reset counter
            tracker.current_month_year = current_month
            tracker.analysis_count_current_month = 0
            db.session.commit()
            return True, None

        # Check monthly limit (1 per month for free users)
        if tracker.analysis_count_current_month >= 1:
            days_until_reset = 30 - datetime.utcnow().day
            return False, f"Monthly AI analysis limit reached (1 per month). Next analysis available in {days_until_reset} days. Upgrade to Pro for unlimited analyses."

        return True, None

    @classmethod
    def record_analysis(cls, customer_id: str):
        """Record that an AI analysis was run for this customer."""
        tracker = cls.query.filter_by(google_ads_customer_id=customer_id).first()
        current_month = datetime.utcnow().strftime("%Y-%m")

        if not tracker:
            tracker = cls(
                google_ads_customer_id=customer_id,
                last_analysis_at=datetime.utcnow(),
                analysis_count_current_month=1,
                analysis_count_total=1,
                current_month_year=current_month
            )
            db.session.add(tracker)
        else:
            # Check if month changed
            if tracker.current_month_year != current_month:
                tracker.current_month_year = current_month
                tracker.analysis_count_current_month = 1
            else:
                tracker.analysis_count_current_month += 1

            tracker.analysis_count_total += 1
            tracker.last_analysis_at = datetime.utcnow()

        db.session.commit()
