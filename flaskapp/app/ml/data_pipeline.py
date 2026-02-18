# app/ml/data_pipeline.py
"""
Data extraction and preparation pipeline for ML models.

Extracts historical Google Ads data from the database and transforms it
into feature matrices suitable for training and prediction.
"""
import logging
from datetime import datetime, timedelta, date
from typing import Dict, List, Optional, Tuple, Any

import numpy as np
from sqlalchemy import text

from app import db

logger = logging.getLogger(__name__)


class DataPipeline:
    """Extracts and prepares Google Ads data for ML models."""

    def __init__(self, account_id: int):
        self.account_id = account_id

    # ------------------------------------------------------------------
    # Campaign-level features
    # ------------------------------------------------------------------

    def get_campaign_performance(
        self, days: int = 365, granularity: str = 'daily'
    ) -> List[Dict]:
        """
        Get campaign performance data for training.

        Returns list of dicts with features per campaign per time period.
        """
        cutoff = (date.today() - timedelta(days=days)).isoformat()

        query = text("""
            SELECT
                cph.campaign_id,
                cph.campaign_name,
                cph.date,
                cph.day_of_week,
                cph.week_of_month,
                cph.month,
                cph.year,
                cph.impressions,
                cph.clicks,
                cph.conversions,
                cph.cost_cents,
                cph.revenue_cents,
                cph.ctr,
                cph.cpl_cents,
                cph.conversion_rate,
                cph.roas,
                cph.avg_quality_score,
                cph.impression_share,
                cph.was_holiday
            FROM campaign_performance_history cph
            WHERE cph.account_id = :account_id
              AND cph.date >= :cutoff
            ORDER BY cph.campaign_id, cph.date
        """)

        with db.engine.connect() as conn:
            rows = conn.execute(query, {
                'account_id': self.account_id,
                'cutoff': cutoff,
            }).fetchall()

        return [dict(r._mapping) for r in rows]

    def get_campaign_features(self, campaign_id: int, days: int = 90) -> Dict:
        """
        Build feature vector for a single campaign (for prediction).

        Aggregates recent performance into statistical features.
        """
        cutoff = (date.today() - timedelta(days=days)).isoformat()

        query = text("""
            SELECT
                COUNT(*) as days_active,
                SUM(impressions) as total_impressions,
                SUM(clicks) as total_clicks,
                SUM(conversions) as total_conversions,
                SUM(cost_cents) as total_cost_cents,
                SUM(revenue_cents) as total_revenue_cents,
                AVG(ctr) as avg_ctr,
                AVG(conversion_rate) as avg_conv_rate,
                AVG(cpl_cents) as avg_cpl_cents,
                AVG(roas) as avg_roas,
                AVG(impression_share) as avg_impression_share,
                AVG(avg_quality_score) as avg_quality_score,
                STDDEV(cost_cents) as stddev_cost,
                STDDEV(conversions) as stddev_conversions,
                STDDEV(ctr) as stddev_ctr,
                -- Trend: compare last 7d to prior 7d
                AVG(CASE WHEN date >= DATE_SUB(CURDATE(), INTERVAL 7 DAY) THEN cost_cents END) as avg_cost_7d,
                AVG(CASE WHEN date >= DATE_SUB(CURDATE(), INTERVAL 7 DAY) THEN conversions END) as avg_conv_7d,
                AVG(CASE WHEN date BETWEEN DATE_SUB(CURDATE(), INTERVAL 14 DAY)
                                       AND DATE_SUB(CURDATE(), INTERVAL 7 DAY) THEN cost_cents END) as avg_cost_prev_7d,
                AVG(CASE WHEN date BETWEEN DATE_SUB(CURDATE(), INTERVAL 14 DAY)
                                       AND DATE_SUB(CURDATE(), INTERVAL 7 DAY) THEN conversions END) as avg_conv_prev_7d
            FROM campaign_performance_history
            WHERE account_id = :account_id
              AND campaign_id = :campaign_id
              AND date >= :cutoff
        """)

        with db.engine.connect() as conn:
            row = conn.execute(query, {
                'account_id': self.account_id,
                'campaign_id': campaign_id,
                'cutoff': cutoff,
            }).fetchone()

        if not row:
            return {}

        d = dict(row._mapping)

        # Compute derived features
        total_cost = (d.get('total_cost_cents') or 0) / 100
        total_conv = d.get('total_conversions') or 0
        d['cpa'] = total_cost / total_conv if total_conv > 0 else 0
        d['total_spend'] = total_cost

        # Trend features
        avg_cost_7d = d.get('avg_cost_7d') or 0
        avg_cost_prev = d.get('avg_cost_prev_7d') or 0
        d['cost_trend'] = (
            (avg_cost_7d - avg_cost_prev) / avg_cost_prev
            if avg_cost_prev > 0 else 0
        )
        avg_conv_7d = d.get('avg_conv_7d') or 0
        avg_conv_prev = d.get('avg_conv_prev_7d') or 0
        d['conv_trend'] = (
            (avg_conv_7d - avg_conv_prev) / avg_conv_prev
            if avg_conv_prev > 0 else 0
        )

        return d

    # ------------------------------------------------------------------
    # Keyword-level features
    # ------------------------------------------------------------------

    def get_keyword_performance(self, days: int = 90) -> List[Dict]:
        """Get keyword-level performance data."""
        cutoff = (date.today() - timedelta(days=days)).isoformat()

        query = text("""
            SELECT
                s.entity_id as keyword_id,
                k.text as keyword_text,
                k.match_type,
                s.date,
                s.impressions,
                s.clicks,
                s.cost_micros,
                s.conversions,
                s.conversion_value,
                s.avg_cpc,
                s.search_impr_share
            FROM gads_stats_daily s
            JOIN keywords k ON k.id = s.entity_id
            WHERE s.entity_type = 'keyword'
              AND s.date >= :cutoff
              AND EXISTS (
                  SELECT 1 FROM ad_groups ag
                  JOIN ads_campaigns ac ON ac.id = ag.campaign_id
                  WHERE ag.id = k.ad_group_id AND ac.account_id = :account_id
              )
            ORDER BY s.entity_id, s.date
        """)

        with db.engine.connect() as conn:
            rows = conn.execute(query, {
                'account_id': self.account_id,
                'cutoff': cutoff,
            }).fetchall()

        return [dict(r._mapping) for r in rows]

    def get_keyword_features(self, keyword_id: int, days: int = 30) -> Dict:
        """Build feature vector for a single keyword."""
        cutoff = (date.today() - timedelta(days=days)).isoformat()

        query = text("""
            SELECT
                COUNT(*) as days_with_data,
                SUM(impressions) as total_impressions,
                SUM(clicks) as total_clicks,
                SUM(conversions) as total_conversions,
                SUM(cost_micros) / 1000000.0 as total_spend,
                AVG(cost_micros) / 1000000.0 as avg_daily_spend,
                AVG(CASE WHEN clicks > 0 THEN cost_micros / clicks / 1000000.0 END) as avg_cpc,
                AVG(CASE WHEN impressions > 0 THEN clicks / impressions END) as avg_ctr,
                AVG(search_impr_share) as avg_impression_share,
                STDDEV(cost_micros / 1000000.0) as stddev_spend,
                STDDEV(conversions) as stddev_conversions
            FROM gads_stats_daily
            WHERE entity_type = 'keyword'
              AND entity_id = :keyword_id
              AND date >= :cutoff
        """)

        with db.engine.connect() as conn:
            row = conn.execute(query, {
                'keyword_id': keyword_id,
                'cutoff': cutoff,
            }).fetchone()

        if not row:
            return {}

        d = dict(row._mapping)
        total_spend = d.get('total_spend') or 0
        total_conv = d.get('total_conversions') or 0
        d['cpa'] = total_spend / total_conv if total_conv > 0 else 0
        return d

    # ------------------------------------------------------------------
    # Search term features (for negative keyword agent)
    # ------------------------------------------------------------------

    def get_search_term_data(self, days: int = 90) -> List[Dict]:
        """Get search term performance data for waste classification."""
        cutoff = (date.today() - timedelta(days=days)).isoformat()

        query = text("""
            SELECT
                st.search_term,
                st.clicks,
                st.impressions,
                st.cost_micros,
                st.conversions,
                st.added_as_keyword,
                st.added_as_negative,
                st.date,
                k.text as matched_keyword,
                k.match_type as matched_keyword_type
            FROM search_terms st
            LEFT JOIN keywords k ON k.id = st.keyword_id
            JOIN ads_campaigns ac ON ac.id = st.campaign_id
            WHERE ac.account_id = :account_id
              AND st.date >= :cutoff
            ORDER BY st.cost_micros DESC
        """)

        with db.engine.connect() as conn:
            rows = conn.execute(query, {
                'account_id': self.account_id,
                'cutoff': cutoff,
            }).fetchall()

        return [dict(r._mapping) for r in rows]

    # ------------------------------------------------------------------
    # Budget features
    # ------------------------------------------------------------------

    def get_budget_history(self, days: int = 180) -> List[Dict]:
        """Get budget change history for spend forecasting."""
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()

        query = text("""
            SELECT
                campaign_id,
                change_date,
                old_daily_budget_cents,
                new_daily_budget_cents,
                change_pct,
                change_reason,
                adjustment_type
            FROM budget_change_log
            WHERE account_id = :account_id
              AND change_date >= :cutoff
            ORDER BY change_date
        """)

        with db.engine.connect() as conn:
            rows = conn.execute(query, {
                'account_id': self.account_id,
                'cutoff': cutoff,
            }).fetchall()

        return [dict(r._mapping) for r in rows]

    def get_budget_pacing(self, days: int = 30) -> List[Dict]:
        """Get hourly budget pacing data."""
        cutoff = (date.today() - timedelta(days=days)).isoformat()

        query = text("""
            SELECT
                date, hour,
                budget_allocated,
                budget_spent,
                impressions,
                clicks,
                conversions,
                pacing_score
            FROM ads_budget_pacing_history
            WHERE account_id = :account_id
              AND date >= :cutoff
            ORDER BY date, hour
        """)

        with db.engine.connect() as conn:
            rows = conn.execute(query, {
                'account_id': self.account_id,
                'cutoff': cutoff,
            }).fetchall()

        return [dict(r._mapping) for r in rows]

    # ------------------------------------------------------------------
    # Ad-level features (for ad copy agent)
    # ------------------------------------------------------------------

    def get_ad_performance(self, days: int = 90) -> List[Dict]:
        """Get ad-level performance for CTR prediction."""
        cutoff = (date.today() - timedelta(days=days)).isoformat()

        query = text("""
            SELECT
                s.entity_id as ad_id,
                a.headline1, a.headline2, a.headline3,
                a.description1, a.description2,
                a.final_url,
                s.date,
                s.impressions,
                s.clicks,
                s.cost_micros,
                s.conversions
            FROM gads_stats_daily s
            JOIN ads a ON a.id = s.entity_id
            WHERE s.entity_type = 'ad'
              AND s.date >= :cutoff
              AND EXISTS (
                  SELECT 1 FROM ad_groups ag
                  JOIN ads_campaigns ac ON ac.id = ag.campaign_id
                  WHERE ag.id = a.ad_group_id AND ac.account_id = :account_id
              )
            ORDER BY s.entity_id, s.date
        """)

        with db.engine.connect() as conn:
            rows = conn.execute(query, {
                'account_id': self.account_id,
                'cutoff': cutoff,
            }).fetchall()

        return [dict(r._mapping) for r in rows]

    # ------------------------------------------------------------------
    # Quality score features
    # ------------------------------------------------------------------

    def get_quality_score_history(self, days: int = 180) -> List[Dict]:
        """Get quality score prediction history."""
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()

        query = text("""
            SELECT
                keyword_id,
                keyword_text,
                predicted_quality_score,
                predicted_ctr_score,
                predicted_ad_relevance,
                predicted_landing_page_exp,
                confidence_score,
                actual_quality_score,
                actual_ctr,
                prediction_accuracy,
                created_at,
                measured_at
            FROM ads_quality_score_predictions
            WHERE account_id = :account_id
              AND created_at >= :cutoff
            ORDER BY keyword_id, created_at
        """)

        with db.engine.connect() as conn:
            rows = conn.execute(query, {
                'account_id': self.account_id,
                'cutoff': cutoff,
            }).fetchall()

        return [dict(r._mapping) for r in rows]

    # ------------------------------------------------------------------
    # Competitive data
    # ------------------------------------------------------------------

    def get_auction_insights(self, days: int = 90) -> List[Dict]:
        """Get competitive auction insight history."""
        cutoff = (date.today() - timedelta(days=days)).isoformat()

        query = text("""
            SELECT
                campaign_id,
                date,
                competitor_domain,
                impression_share,
                overlap_rate,
                position_above_rate,
                top_of_page_rate,
                absolute_top_of_page_rate,
                outranking_share
            FROM ads_auction_insights_history
            WHERE account_id = :account_id
              AND date >= :cutoff
            ORDER BY date, competitor_domain
        """)

        with db.engine.connect() as conn:
            rows = conn.execute(query, {
                'account_id': self.account_id,
                'cutoff': cutoff,
            }).fetchall()

        return [dict(r._mapping) for r in rows]

    # ------------------------------------------------------------------
    # Anomaly history (for learning normal patterns)
    # ------------------------------------------------------------------

    def get_anomaly_history(self, days: int = 365) -> List[Dict]:
        """Get historical anomalies for learning detection patterns."""
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()

        query = text("""
            SELECT
                entity_type,
                entity_id,
                metric_name,
                anomaly_type,
                expected_value,
                actual_value,
                deviation_pct,
                severity,
                confidence_score,
                status,
                detected_at
            FROM ads_anomalies
            WHERE account_id = :account_id
              AND detected_at >= :cutoff
            ORDER BY detected_at
        """)

        with db.engine.connect() as conn:
            rows = conn.execute(query, {
                'account_id': self.account_id,
                'cutoff': cutoff,
            }).fetchall()

        return [dict(r._mapping) for r in rows]

    # ------------------------------------------------------------------
    # Cross-account aggregate (for new accounts with little data)
    # ------------------------------------------------------------------

    def get_cross_account_benchmarks(self) -> Dict:
        """
        Get aggregated benchmarks across all accounts.

        Used when a single account doesn't have enough data
        to train its own model. Provides industry-wide baselines.
        """
        query = text("""
            SELECT
                COUNT(DISTINCT account_id) as num_accounts,
                AVG(avg_ctr) as benchmark_ctr,
                AVG(avg_conv_rate) as benchmark_conv_rate,
                AVG(avg_cpa) as benchmark_cpa,
                AVG(avg_roas) as benchmark_roas
            FROM (
                SELECT
                    cph.account_id,
                    AVG(cph.ctr) as avg_ctr,
                    AVG(cph.conversion_rate) as avg_conv_rate,
                    AVG(CASE WHEN cph.conversions > 0
                         THEN cph.cost_cents / cph.conversions / 100.0 END) as avg_cpa,
                    AVG(cph.roas) as avg_roas
                FROM campaign_performance_history cph
                WHERE cph.date >= DATE_SUB(CURDATE(), INTERVAL 90 DAY)
                GROUP BY cph.account_id
            ) account_avgs
        """)

        with db.engine.connect() as conn:
            row = conn.execute(query).fetchone()

        return dict(row._mapping) if row else {}

    # ------------------------------------------------------------------
    # Outcome tracking (feedback loop)
    # ------------------------------------------------------------------

    def get_decision_outcomes(self, days: int = 90) -> List[Dict]:
        """
        Get past agent decisions and their outcomes for feedback learning.

        Joins agent_decisions with performance data to see if decisions
        led to improvements.
        """
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()

        query = text("""
            SELECT
                ad.agent_id,
                ad.agent_type,
                ad.decision_type,
                ad.risk_level,
                ad.confidence,
                ad.expected_monthly_savings,
                ad.status,
                ad.executed_at,
                ad.created_at,
                ad.parameters
            FROM agent_decisions ad
            WHERE ad.account_id = :account_id
              AND ad.created_at >= :cutoff
            ORDER BY ad.created_at
        """)

        with db.engine.connect() as conn:
            rows = conn.execute(query, {
                'account_id': self.account_id,
                'cutoff': cutoff,
            }).fetchall()

        return [dict(r._mapping) for r in rows]
