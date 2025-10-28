# app/models_fb_ads_grader.py
"""
Database model for Facebook Ads Grader reports.

Stores comprehensive analysis of Facebook Ads account performance including:
- Overall performance score and grade
- Key metrics (CTR, CPC, ROAS, Relevance Score)
- Account diagnostics (campaigns, ad sets, ads, etc.)
- Section scores for 10+ performance categories
- Detailed metrics and recommendations
"""
from __future__ import annotations
from datetime import datetime
from typing import Optional, List, Dict, Any

from sqlalchemy.dialects.mysql import JSON, BIGINT
from app import db


class FacebookAdsGraderReport(db.Model):
    """
    Facebook Ads Performance Grader Report

    Stores comprehensive analysis results for a Facebook Ads account,
    including overall score, section scores, key metrics, and recommendations.
    """
    __tablename__ = "facebook_ads_grader_reports"

    # Primary Key
    id = db.Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)

    # Ownership (nullable for anonymous users)
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), index=True, nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True, nullable=True)

    # Facebook Ads Account Info
    fb_ad_account_id = db.Column(db.String(128), index=True, nullable=False)
    fb_ad_account_name = db.Column(db.String(255), nullable=True)
    fb_business_id = db.Column(db.String(128), nullable=True)
    fb_business_name = db.Column(db.String(255), nullable=True)
    currency = db.Column(db.String(10), nullable=True)

    # =========================================================================
    # OVERALL SCORE
    # =========================================================================
    overall_score = db.Column(db.Float, nullable=False, index=True)
    overall_grade = db.Column(db.String(3), nullable=False)  # A+, A, A-, B+, etc.

    # =========================================================================
    # KEY METRICS
    # =========================================================================
    ctr_avg = db.Column(db.Float, nullable=True)  # Click-through rate %
    cpc_avg = db.Column(db.Float, nullable=True)  # Cost per click
    cpm_avg = db.Column(db.Float, nullable=True)  # Cost per 1000 impressions
    relevance_score_avg = db.Column(db.Float, nullable=True)  # Facebook relevance score (1-10)
    roas_avg = db.Column(db.Float, nullable=True)  # Return on ad spend
    conversion_rate_avg = db.Column(db.Float, nullable=True)  # Conversion rate %

    # Wasted spend estimates
    wasted_spend_365d = db.Column(db.Float, nullable=True)  # Last year
    projected_waste_12m = db.Column(db.Float, nullable=True)  # Next 12 months

    # =========================================================================
    # ACCOUNT DIAGNOSTICS
    # =========================================================================
    active_campaigns = db.Column(db.Integer, default=0)
    active_ad_sets = db.Column(db.Integer, default=0)
    active_ads = db.Column(db.Integer, default=0)
    total_audiences = db.Column(db.Integer, default=0)

    # Performance metrics (365 days)
    clicks_365d = db.Column(db.Integer, default=0)
    impressions_365d = db.Column(db.BigInteger, default=0)
    conversions_365d = db.Column(db.Integer, default=0)
    spend_365d = db.Column(db.Float, default=0)
    revenue_365d = db.Column(db.Float, default=0)
    avg_monthly_spend = db.Column(db.Float, nullable=True)

    # =========================================================================
    # SECTION SCORES (0-100 for each category)
    # =========================================================================

    # 1. Wasted Spend Optimization
    wasted_spend_score = db.Column(db.Float, nullable=True)

    # 2. Creative Optimization
    creative_optimization_score = db.Column(db.Float, nullable=True)

    # 3. Audience Targeting
    audience_targeting_score = db.Column(db.Float, nullable=True)

    # 4. Relevance Score Optimization
    relevance_score_optimization_score = db.Column(db.Float, nullable=True)

    # 5. CTR Optimization
    ctr_optimization_score = db.Column(db.Float, nullable=True)

    # 6. Account Activity
    account_activity_score = db.Column(db.Float, nullable=True)

    # 7. Ad Format Diversity
    ad_format_diversity_score = db.Column(db.Float, nullable=True)

    # 8. Campaign Structure
    campaign_structure_score = db.Column(db.Float, nullable=True)

    # 9. Landing Page Experience
    landing_page_score = db.Column(db.Float, nullable=True)

    # 10. Mobile Optimization
    mobile_optimization_score = db.Column(db.Float, nullable=True)

    # 11. Conversion Tracking
    conversion_tracking_score = db.Column(db.Float, nullable=True)

    # 12. ROAS Performance
    roas_score = db.Column(db.Float, nullable=True)

    # =========================================================================
    # DETAILED DATA (JSON fields for flexibility)
    # =========================================================================
    detailed_metrics = db.Column(JSON, nullable=True)
    """
    Stores all raw metrics from Facebook Ads API:
    - Performance by campaign
    - Performance by ad set
    - Performance by ad
    - Audience insights
    - Creative performance
    - Placement performance
    - Device performance
    - etc.
    """

    best_practices = db.Column(JSON, nullable=True)
    """
    Checklist of best practices:
    {
        "conversion_tracking": true/false,
        "pixel_installed": true/false,
        "multiple_ad_creatives": true/false,
        "audience_testing": true/false,
        "placement_optimization": true/false,
        "mobile_optimized": true/false,
        "ad_rotation": true/false,
        "retargeting_campaigns": true/false,
        "lookalike_audiences": true/false,
        "dynamic_ads": true/false,
    }
    """

    recommendations = db.Column(JSON, nullable=True)
    """
    List of actionable recommendations based on analysis:
    [
        "Install Facebook Pixel to track 50% more conversions",
        "Test 3 new ad creatives to improve CTR by 0.8%",
        "Create lookalike audiences to reduce CPA by 30%",
        ...
    ]
    """

    # =========================================================================
    # METADATA
    # =========================================================================
    report_date = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    date_range_start = db.Column(db.DateTime, nullable=True)  # Analysis period start
    date_range_end = db.Column(db.DateTime, nullable=True)    # Analysis period end

    pdf_download_count = db.Column(db.Integer, default=0)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow,
                          onupdate=datetime.utcnow, nullable=False)

    # =========================================================================
    # RELATIONSHIPS
    # =========================================================================
    # Define relationships if needed
    # account = db.relationship("Account", backref="fb_ads_grader_reports")
    # user = db.relationship("User", backref="fb_ads_grader_reports")

    # =========================================================================
    # METHODS
    # =========================================================================

    def __repr__(self) -> str:
        return (
            f"<FacebookAdsGraderReport id={self.id} "
            f"account={self.fb_ad_account_name} "
            f"score={self.overall_score:.1f} "
            f"grade={self.overall_grade}>"
        )

    @classmethod
    def get_for_account(cls, account_id: int, limit: int = 10) -> List['FacebookAdsGraderReport']:
        """
        Get recent reports for a specific account.

        Args:
            account_id: Account ID to filter by
            limit: Maximum number of reports to return

        Returns:
            List of reports, most recent first
        """
        return cls.query.filter_by(account_id=account_id)\
                       .order_by(cls.created_at.desc())\
                       .limit(limit)\
                       .all()

    @classmethod
    def get_for_fb_account(cls, fb_ad_account_id: str, limit: int = 10) -> List['FacebookAdsGraderReport']:
        """
        Get recent reports for a specific Facebook Ads account.

        Args:
            fb_ad_account_id: Facebook Ad Account ID
            limit: Maximum number of reports to return

        Returns:
            List of reports, most recent first
        """
        return cls.query.filter_by(fb_ad_account_id=fb_ad_account_id)\
                       .order_by(cls.created_at.desc())\
                       .limit(limit)\
                       .all()

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert report to dictionary for JSON serialization.

        Returns:
            Dictionary representation of the report
        """
        return {
            "id": self.id,
            "fb_ad_account_id": self.fb_ad_account_id,
            "fb_ad_account_name": self.fb_ad_account_name,
            "overall_score": self.overall_score,
            "overall_grade": self.overall_grade,
            "report_date": self.report_date.isoformat() if self.report_date else None,
            "key_metrics": {
                "ctr_avg": self.ctr_avg,
                "cpc_avg": self.cpc_avg,
                "cpm_avg": self.cpm_avg,
                "relevance_score_avg": self.relevance_score_avg,
                "roas_avg": self.roas_avg,
                "conversion_rate_avg": self.conversion_rate_avg,
            },
            "section_scores": {
                "wasted_spend": self.wasted_spend_score,
                "creative_optimization": self.creative_optimization_score,
                "audience_targeting": self.audience_targeting_score,
                "relevance_score": self.relevance_score_optimization_score,
                "ctr_optimization": self.ctr_optimization_score,
                "account_activity": self.account_activity_score,
                "ad_format_diversity": self.ad_format_diversity_score,
                "campaign_structure": self.campaign_structure_score,
                "landing_page": self.landing_page_score,
                "mobile_optimization": self.mobile_optimization_score,
                "conversion_tracking": self.conversion_tracking_score,
                "roas": self.roas_score,
            },
            "recommendations": self.recommendations or [],
        }


__all__ = ["FacebookAdsGraderReport"]
