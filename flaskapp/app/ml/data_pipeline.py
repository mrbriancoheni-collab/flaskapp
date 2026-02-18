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

    # ------------------------------------------------------------------
    # Enhanced Seasonality Analysis
    # ------------------------------------------------------------------

    def get_seasonality_features(self, days: int = 365) -> Dict:
        """
        Extract seasonality patterns from historical data.

        Returns aggregated performance metrics by:
        - Quarter (Q1-Q4)
        - Month (1-12)
        - Day of week (0-6)
        - Week of year (1-52)
        - Holiday vs non-holiday periods
        """
        cutoff = (date.today() - timedelta(days=days)).isoformat()

        query = text("""
            SELECT
                -- Quarterly patterns
                QUARTER(date) as quarter,
                MONTH(date) as month,
                DAYOFWEEK(date) as day_of_week,
                WEEK(date) as week_of_year,
                was_holiday,

                -- Aggregated metrics
                COUNT(*) as days_in_period,
                SUM(impressions) as total_impressions,
                SUM(clicks) as total_clicks,
                SUM(conversions) as total_conversions,
                SUM(cost_cents) / 100.0 as total_cost,
                AVG(ctr) as avg_ctr,
                AVG(conversion_rate) as avg_conv_rate,
                AVG(CASE WHEN conversions > 0 THEN cost_cents / conversions / 100.0 END) as avg_cpa,
                AVG(roas) as avg_roas
            FROM campaign_performance_history
            WHERE account_id = :account_id
              AND date >= :cutoff
            GROUP BY quarter, month, day_of_week, week_of_year, was_holiday
            ORDER BY quarter, month, day_of_week
        """)

        with db.engine.connect() as conn:
            rows = conn.execute(query, {
                'account_id': self.account_id,
                'cutoff': cutoff,
            }).fetchall()

        raw_data = [dict(r._mapping) for r in rows]

        # Aggregate into seasonal profiles
        quarterly = {}
        monthly = {}
        daily = {}
        holiday_impact = {'holiday': [], 'non_holiday': []}

        for row in raw_data:
            q = row['quarter']
            m = row['month']
            d = row['day_of_week']

            if q not in quarterly:
                quarterly[q] = []
            quarterly[q].append(row)

            if m not in monthly:
                monthly[m] = []
            monthly[m].append(row)

            if d not in daily:
                daily[d] = []
            daily[d].append(row)

            key = 'holiday' if row['was_holiday'] else 'non_holiday'
            holiday_impact[key].append(row)

        return {
            'raw_data': raw_data,
            'quarterly_patterns': self._aggregate_seasonal(quarterly),
            'monthly_patterns': self._aggregate_seasonal(monthly),
            'daily_patterns': self._aggregate_seasonal(daily),
            'holiday_impact': {
                'holiday_avg_cpa': np.mean([r['avg_cpa'] for r in holiday_impact['holiday'] if r['avg_cpa']]) if holiday_impact['holiday'] else None,
                'non_holiday_avg_cpa': np.mean([r['avg_cpa'] for r in holiday_impact['non_holiday'] if r['avg_cpa']]) if holiday_impact['non_holiday'] else None,
            }
        }

    def _aggregate_seasonal(self, grouped_data: Dict) -> Dict:
        """Helper to aggregate seasonal metrics."""
        result = {}
        for key, rows in grouped_data.items():
            cpas = [r['avg_cpa'] for r in rows if r['avg_cpa']]
            ctrs = [r['avg_ctr'] for r in rows if r['avg_ctr']]
            conv_rates = [r['avg_conv_rate'] for r in rows if r['avg_conv_rate']]

            result[key] = {
                'avg_cpa': np.mean(cpas) if cpas else None,
                'avg_ctr': np.mean(ctrs) if ctrs else None,
                'avg_conv_rate': np.mean(conv_rates) if conv_rates else None,
                'total_conversions': sum(r['total_conversions'] or 0 for r in rows),
                'total_cost': sum(r['total_cost'] or 0 for r in rows),
                'sample_days': sum(r['days_in_period'] or 0 for r in rows),
            }
        return result

    # ------------------------------------------------------------------
    # Hourly Performance (Time of Day)
    # ------------------------------------------------------------------

    def get_hourly_performance(self, days: int = 90) -> List[Dict]:
        """
        Get hourly performance patterns.

        Analyzes performance by hour of day to identify optimal bidding windows.
        """
        cutoff = (date.today() - timedelta(days=days)).isoformat()

        query = text("""
            SELECT
                hour,
                DAYOFWEEK(date) as day_of_week,

                -- Aggregated metrics by hour
                COUNT(*) as data_points,
                SUM(impressions) as total_impressions,
                SUM(clicks) as total_clicks,
                SUM(conversions) as total_conversions,
                SUM(budget_spent) as total_spend,
                AVG(CASE WHEN clicks > 0 THEN conversions * 1.0 / clicks END) as avg_conv_rate,
                AVG(CASE WHEN impressions > 0 THEN clicks * 100.0 / impressions END) as avg_ctr,
                AVG(pacing_score) as avg_pacing_score
            FROM ads_budget_pacing_history
            WHERE account_id = :account_id
              AND date >= :cutoff
            GROUP BY hour, day_of_week
            ORDER BY day_of_week, hour
        """)

        with db.engine.connect() as conn:
            rows = conn.execute(query, {
                'account_id': self.account_id,
                'cutoff': cutoff,
            }).fetchall()

        return [dict(r._mapping) for r in rows]

    def get_hourly_summary(self, days: int = 90) -> Dict:
        """
        Get summary of best/worst performing hours.
        """
        hourly_data = self.get_hourly_performance(days)

        if not hourly_data:
            return {'best_hours': [], 'worst_hours': [], 'by_hour': {}}

        # Aggregate by hour across all days
        by_hour = {}
        for row in hourly_data:
            h = row['hour']
            if h not in by_hour:
                by_hour[h] = {'conversions': 0, 'spend': 0, 'clicks': 0}
            by_hour[h]['conversions'] += row['total_conversions'] or 0
            by_hour[h]['spend'] += row['total_spend'] or 0
            by_hour[h]['clicks'] += row['total_clicks'] or 0

        # Calculate CPA by hour
        for h, data in by_hour.items():
            data['cpa'] = (data['spend'] / data['conversions']) if data['conversions'] > 0 else None

        # Sort hours by CPA (best = lowest CPA)
        hours_with_cpa = [(h, d['cpa']) for h, d in by_hour.items() if d['cpa']]
        hours_with_cpa.sort(key=lambda x: x[1])

        return {
            'best_hours': [h for h, _ in hours_with_cpa[:4]],  # Top 4 hours
            'worst_hours': [h for h, _ in hours_with_cpa[-4:]],  # Bottom 4 hours
            'by_hour': by_hour,
        }

    # ------------------------------------------------------------------
    # Service Type Extraction
    # ------------------------------------------------------------------

    SERVICE_TYPE_KEYWORDS = {
        'hvac': ['hvac', 'heating', 'cooling', 'air conditioning', 'ac repair', 'furnace', 'heat pump'],
        'plumbing': ['plumber', 'plumbing', 'drain', 'pipe', 'water heater', 'sewer', 'faucet'],
        'electrical': ['electrician', 'electrical', 'wiring', 'outlet', 'panel', 'lighting'],
        'roofing': ['roof', 'roofing', 'shingle', 'gutter', 'leak repair'],
        'landscaping': ['landscaping', 'lawn', 'tree', 'garden', 'mowing', 'irrigation'],
        'pest_control': ['pest', 'exterminator', 'termite', 'rodent', 'bug', 'insect'],
        'cleaning': ['cleaning', 'maid', 'janitorial', 'carpet cleaning', 'pressure wash'],
        'moving': ['moving', 'movers', 'relocation', 'packing'],
        'painting': ['painting', 'painter', 'interior painting', 'exterior painting'],
        'concrete': ['concrete', 'driveway', 'patio', 'foundation'],
        'garage_door': ['garage door', 'overhead door'],
        'windows': ['window', 'glass', 'replacement windows'],
        'flooring': ['flooring', 'hardwood', 'tile', 'carpet', 'laminate'],
        'remodeling': ['remodel', 'renovation', 'kitchen', 'bathroom', 'basement'],
    }

    def extract_service_types(self) -> Dict:
        """
        Extract service type/vertical from campaign and keyword names.

        Returns inferred service categories with confidence scores.
        """
        # Get campaign names
        campaign_query = text("""
            SELECT DISTINCT campaign_name
            FROM campaign_performance_history
            WHERE account_id = :account_id
        """)

        # Get keywords
        keyword_query = text("""
            SELECT DISTINCT k.text as keyword_text
            FROM keywords k
            JOIN ad_groups ag ON ag.id = k.ad_group_id
            JOIN ads_campaigns ac ON ac.id = ag.campaign_id
            WHERE ac.account_id = :account_id
            LIMIT 500
        """)

        with db.engine.connect() as conn:
            campaigns = conn.execute(campaign_query, {'account_id': self.account_id}).fetchall()
            keywords = conn.execute(keyword_query, {'account_id': self.account_id}).fetchall()

        # Combine all text for analysis
        all_text = ' '.join([
            *[r[0].lower() for r in campaigns if r[0]],
            *[r[0].lower() for r in keywords if r[0]],
        ])

        # Score each service type
        service_scores = {}
        for service_type, keywords_list in self.SERVICE_TYPE_KEYWORDS.items():
            matches = sum(1 for kw in keywords_list if kw in all_text)
            if matches > 0:
                service_scores[service_type] = matches

        if not service_scores:
            return {'primary_service': 'unknown', 'services': {}, 'confidence': 0}

        # Sort by score
        sorted_services = sorted(service_scores.items(), key=lambda x: -x[1])
        total_matches = sum(service_scores.values())

        return {
            'primary_service': sorted_services[0][0],
            'services': {s: score / total_matches for s, score in sorted_services},
            'confidence': min(sorted_services[0][1] / 5.0, 1.0),  # Cap at 1.0
        }

    # ------------------------------------------------------------------
    # Cost Pattern Analysis
    # ------------------------------------------------------------------

    def get_cost_patterns(self, days: int = 180) -> Dict:
        """
        Analyze cost patterns over time.

        Returns:
        - Cost trends (increasing/decreasing/stable)
        - Cost volatility
        - Cost by day of week
        - Cost efficiency trends (CPA over time)
        """
        cutoff = (date.today() - timedelta(days=days)).isoformat()

        query = text("""
            SELECT
                date,
                DAYOFWEEK(date) as day_of_week,
                WEEK(date) as week_num,
                SUM(cost_cents) / 100.0 as daily_cost,
                SUM(conversions) as daily_conversions,
                SUM(clicks) as daily_clicks,
                AVG(ctr) as avg_ctr,
                AVG(CASE WHEN conversions > 0 THEN cost_cents / conversions / 100.0 END) as daily_cpa
            FROM campaign_performance_history
            WHERE account_id = :account_id
              AND date >= :cutoff
            GROUP BY date, day_of_week, week_num
            ORDER BY date
        """)

        with db.engine.connect() as conn:
            rows = conn.execute(query, {
                'account_id': self.account_id,
                'cutoff': cutoff,
            }).fetchall()

        data = [dict(r._mapping) for r in rows]

        if not data:
            return {'trend': 'unknown', 'volatility': None, 'by_day': {}}

        # Calculate trend (linear regression slope)
        costs = [r['daily_cost'] for r in data if r['daily_cost']]
        if len(costs) >= 7:
            # Simple trend: compare first half avg to second half avg
            mid = len(costs) // 2
            first_half_avg = np.mean(costs[:mid])
            second_half_avg = np.mean(costs[mid:])

            if second_half_avg > first_half_avg * 1.1:
                trend = 'increasing'
            elif second_half_avg < first_half_avg * 0.9:
                trend = 'decreasing'
            else:
                trend = 'stable'
        else:
            trend = 'insufficient_data'

        # Cost volatility (coefficient of variation)
        volatility = (np.std(costs) / np.mean(costs)) if costs and np.mean(costs) > 0 else None

        # Cost by day of week
        by_day = {}
        for row in data:
            d = row['day_of_week']
            if d not in by_day:
                by_day[d] = {'costs': [], 'cpas': []}
            if row['daily_cost']:
                by_day[d]['costs'].append(row['daily_cost'])
            if row['daily_cpa']:
                by_day[d]['cpas'].append(row['daily_cpa'])

        day_summary = {}
        for d, values in by_day.items():
            day_summary[d] = {
                'avg_cost': np.mean(values['costs']) if values['costs'] else None,
                'avg_cpa': np.mean(values['cpas']) if values['cpas'] else None,
            }

        return {
            'trend': trend,
            'volatility': volatility,
            'avg_daily_cost': np.mean(costs) if costs else None,
            'by_day_of_week': day_summary,
            'data_points': len(data),
        }
