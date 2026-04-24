# app/services/historical_data_service.py
"""
Historical Data Collection Service - Phase 1

Collects and stores daily campaign performance snapshots for trend analysis,
forecasting, and seasonality detection.
"""

import os
from typing import Dict, List, Any, Optional
from datetime import datetime, date, timedelta
from sqlalchemy import text
from app import db


def collect_daily_campaign_performance(account_id: int, campaigns_data: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Collect and store daily performance snapshots for all campaigns.

    Args:
        account_id: Account ID
        campaigns_data: List of campaign performance data

    Returns:
        Dict with success status and records created
    """
    today = date.today()
    day_of_week = today.weekday() + 1  # 1=Monday, 7=Sunday
    week_of_month = (today.day - 1) // 7 + 1

    records_created = 0
    records_updated = 0

    with db.engine.begin() as conn:
        for campaign in campaigns_data:
            campaign_id = campaign.get('id')
            campaign_name = campaign.get('name', '')

            # Check if record already exists for today
            check_query = text("""
                SELECT id FROM campaign_performance_history
                WHERE campaign_id = :campaign_id AND date = :date
            """)

            existing = conn.execute(check_query, {
                "campaign_id": campaign_id,
                "date": today
            }).first()

            # Calculate metrics
            impressions = campaign.get('impressions', 0)
            clicks = campaign.get('clicks', 0)
            conversions = campaign.get('conversions', 0)
            cost_cents = int(campaign.get('cost', 0) * 100)
            revenue_cents = int(campaign.get('revenue', 0) * 100)

            ctr = (clicks / impressions * 100) if impressions > 0 else 0
            cpl_cents = (cost_cents / conversions) if conversions > 0 else 0
            conversion_rate = (conversions / clicks * 100) if clicks > 0 else 0
            roas = (revenue_cents / cost_cents) if cost_cents > 0 else 0

            if existing:
                # Update existing record
                update_query = text("""
                    UPDATE campaign_performance_history
                    SET impressions = :impressions,
                        clicks = :clicks,
                        conversions = :conversions,
                        cost_cents = :cost_cents,
                        revenue_cents = :revenue_cents,
                        ctr = :ctr,
                        cpl_cents = :cpl_cents,
                        conversion_rate = :conversion_rate,
                        roas = :roas,
                        avg_quality_score = :avg_quality_score,
                        avg_position = :avg_position,
                        impression_share = :impression_share
                    WHERE id = :id
                """)

                conn.execute(update_query, {
                    "id": existing.id,
                    "impressions": impressions,
                    "clicks": clicks,
                    "conversions": conversions,
                    "cost_cents": cost_cents,
                    "revenue_cents": revenue_cents,
                    "ctr": ctr,
                    "cpl_cents": int(cpl_cents),
                    "conversion_rate": conversion_rate,
                    "roas": roas,
                    "avg_quality_score": campaign.get('avg_quality_score', 0),
                    "avg_position": campaign.get('avg_position', 0),
                    "impression_share": campaign.get('impression_share', 0)
                })

                records_updated += 1
            else:
                # Insert new record
                insert_query = text("""
                    INSERT INTO campaign_performance_history
                        (account_id, campaign_id, campaign_name, date, day_of_week,
                         week_of_month, month, year, impressions, clicks, conversions,
                         cost_cents, revenue_cents, ctr, cpl_cents, conversion_rate, roas,
                         avg_quality_score, avg_position, impression_share)
                    VALUES
                        (:account_id, :campaign_id, :campaign_name, :date, :day_of_week,
                         :week_of_month, :month, :year, :impressions, :clicks, :conversions,
                         :cost_cents, :revenue_cents, :ctr, :cpl_cents, :conversion_rate, :roas,
                         :avg_quality_score, :avg_position, :impression_share)
                """)

                conn.execute(insert_query, {
                    "account_id": account_id,
                    "campaign_id": campaign_id,
                    "campaign_name": campaign_name,
                    "date": today,
                    "day_of_week": day_of_week,
                    "week_of_month": week_of_month,
                    "month": today.month,
                    "year": today.year,
                    "impressions": impressions,
                    "clicks": clicks,
                    "conversions": conversions,
                    "cost_cents": cost_cents,
                    "revenue_cents": revenue_cents,
                    "ctr": ctr,
                    "cpl_cents": int(cpl_cents),
                    "conversion_rate": conversion_rate,
                    "roas": roas,
                    "avg_quality_score": campaign.get('avg_quality_score', 0),
                    "avg_position": campaign.get('avg_position', 0),
                    "impression_share": campaign.get('impression_share', 0)
                })

                records_created += 1

    return {
        "success": True,
        "date": today.isoformat(),
        "records_created": records_created,
        "records_updated": records_updated
    }


def get_historical_performance(
    campaign_id: int,
    start_date: date,
    end_date: date
) -> List[Dict[str, Any]]:
    """
    Get historical performance data for a campaign.

    Args:
        campaign_id: Campaign ID
        start_date: Start date
        end_date: End date

    Returns:
        List of daily performance records
    """
    query = text("""
        SELECT
            date,
            day_of_week,
            impressions,
            clicks,
            conversions,
            cost_cents,
            revenue_cents,
            ctr,
            cpl_cents,
            conversion_rate,
            roas,
            weather_temp_high,
            weather_temp_low,
            weather_condition,
            was_holiday
        FROM campaign_performance_history
        WHERE campaign_id = :campaign_id
          AND date BETWEEN :start_date AND :end_date
        ORDER BY date ASC
    """)

    with db.engine.connect() as conn:
        result = conn.execute(query, {
            "campaign_id": campaign_id,
            "start_date": start_date,
            "end_date": end_date
        })

        return [dict(row._mapping) for row in result]


def calculate_baseline_metrics(campaign_id: int, days: int = 90) -> Dict[str, float]:
    """
    Calculate baseline metrics for a campaign based on historical data.

    Args:
        campaign_id: Campaign ID
        days: Number of days to look back

    Returns:
        Dict with baseline metrics (avg_cpl, avg_conversion_rate, avg_roas, etc.)
    """
    end_date = date.today()
    start_date = end_date - timedelta(days=days)

    query = text("""
        SELECT
            AVG(cpl_cents) as avg_cpl_cents,
            AVG(conversion_rate) as avg_conversion_rate,
            AVG(roas) as avg_roas,
            AVG(ctr) as avg_ctr,
            AVG(cost_cents) as avg_daily_cost_cents,
            AVG(conversions) as avg_daily_conversions,
            STDDEV(cpl_cents) as stddev_cpl_cents,
            STDDEV(conversion_rate) as stddev_conversion_rate
        FROM campaign_performance_history
        WHERE campaign_id = :campaign_id
          AND date BETWEEN :start_date AND :end_date
    """)

    with db.engine.connect() as conn:
        result = conn.execute(query, {
            "campaign_id": campaign_id,
            "start_date": start_date,
            "end_date": end_date
        }).first()

        if result and float(result.avg_daily_cost_cents or 0) > 0:
            return {
                "avg_cpl_cents": float(result.avg_cpl_cents or 0),
                "avg_conversion_rate": float(result.avg_conversion_rate or 0),
                "avg_roas": float(result.avg_roas or 0),
                "avg_ctr": float(result.avg_ctr or 0),
                "avg_daily_cost_cents": float(result.avg_daily_cost_cents or 0),
                "avg_daily_conversions": float(result.avg_daily_conversions or 0),
                "stddev_cpl_cents": float(result.stddev_cpl_cents or 0),
                "stddev_conversion_rate": float(result.stddev_conversion_rate or 0)
            }

    # Fallback: build baseline from gads_stats_daily using the campaign's google_campaign_id
    return _baseline_from_gads_stats(campaign_id, days)


def _baseline_from_gads_stats(campaign_id: int, days: int) -> Dict[str, float]:
    """
    Build baseline metrics from gads_stats_daily when campaign_performance_history is empty.
    """
    end_date = date.today()
    start_date = end_date - timedelta(days=days)

    # Look up the google_campaign_id
    id_query = text("SELECT google_campaign_id FROM ads_campaigns WHERE id = :id")
    with db.engine.connect() as conn:
        row = conn.execute(id_query, {"id": campaign_id}).first()
        if not row or not row.google_campaign_id:
            return {}

        google_campaign_id = str(row.google_campaign_id)

        stats_query = text("""
            SELECT
                SUM(cost_micros) / 1e6                          AS total_cost,
                SUM(conversions)                                 AS total_conversions,
                SUM(clicks)                                      AS total_clicks,
                SUM(impressions)                                 AS total_impressions,
                COUNT(DISTINCT date)                             AS days_with_data,
                AVG(cost_micros / 1e6)                           AS avg_daily_cost,
                AVG(conversions)                                 AS avg_daily_conversions,
                STDDEV(conversions)                              AS stddev_conversions
            FROM gads_stats_daily
            WHERE entity_type = 'campaign'
              AND entity_id    = :gcid
              AND date BETWEEN :start_date AND :end_date
        """)

        r = conn.execute(stats_query, {
            "gcid": google_campaign_id,
            "start_date": start_date,
            "end_date": end_date,
        }).first()

    if not r or not r.days_with_data or float(r.avg_daily_cost or 0) == 0:
        return {}

    total_cost = float(r.total_cost or 0)
    total_conversions = float(r.total_conversions or 0)
    total_clicks = float(r.total_clicks or 0)
    total_impressions = float(r.total_impressions or 0)
    avg_daily_cost = float(r.avg_daily_cost or 0)
    avg_daily_conversions = float(r.avg_daily_conversions or 0)

    avg_cpl = (total_cost / total_conversions) if total_conversions > 0 else 0
    avg_cpl_cents = avg_cpl * 100

    avg_daily_cost_cents = avg_daily_cost * 100

    avg_conversion_rate = (total_conversions / total_clicks * 100) if total_clicks > 0 else 0
    avg_ctr = (total_clicks / total_impressions * 100) if total_impressions > 0 else 0

    # ROAS requires revenue; gads_stats_daily doesn't have it, so approximate as 0
    avg_roas = 0.0

    stddev_cpl_cents = float(r.stddev_conversions or 0) * 100
    stddev_conversion_rate = 0.0

    return {
        "avg_cpl_cents": avg_cpl_cents,
        "avg_conversion_rate": avg_conversion_rate,
        "avg_roas": avg_roas,
        "avg_ctr": avg_ctr,
        "avg_daily_cost_cents": avg_daily_cost_cents,
        "avg_daily_conversions": avg_daily_conversions,
        "stddev_cpl_cents": stddev_cpl_cents,
        "stddev_conversion_rate": stddev_conversion_rate,
    }


def get_year_over_year_comparison(
    campaign_id: int,
    current_date: date
) -> Dict[str, Any]:
    """
    Compare current performance vs same period last year.

    Args:
        campaign_id: Campaign ID
        current_date: Date to compare

    Returns:
        Dict with current vs last year metrics
    """
    last_year_date = current_date.replace(year=current_date.year - 1)

    # Get current period (last 7 days)
    current_start = current_date - timedelta(days=7)
    last_year_start = last_year_date - timedelta(days=7)

    query = text("""
        SELECT
            SUM(impressions) as impressions,
            SUM(clicks) as clicks,
            SUM(conversions) as conversions,
            SUM(cost_cents) as cost_cents,
            AVG(cpl_cents) as avg_cpl_cents,
            AVG(conversion_rate) as avg_conversion_rate
        FROM campaign_performance_history
        WHERE campaign_id = :campaign_id
          AND date BETWEEN :start_date AND :end_date
    """)

    with db.engine.connect() as conn:
        # Current period
        current = conn.execute(query, {
            "campaign_id": campaign_id,
            "start_date": current_start,
            "end_date": current_date
        }).first()

        # Last year period
        last_year = conn.execute(query, {
            "campaign_id": campaign_id,
            "start_date": last_year_start,
            "end_date": last_year_date
        }).first()

        if not current or not last_year:
            return {}

        # Calculate year-over-year changes
        yoy_conversions = ((current.conversions - last_year.conversions) / last_year.conversions * 100) if last_year.conversions > 0 else 0
        yoy_cost = ((current.cost_cents - last_year.cost_cents) / last_year.cost_cents * 100) if last_year.cost_cents > 0 else 0
        yoy_cpl = ((current.avg_cpl_cents - last_year.avg_cpl_cents) / last_year.avg_cpl_cents * 100) if last_year.avg_cpl_cents > 0 else 0

        return {
            "current": {
                "conversions": current.conversions,
                "cost_cents": current.cost_cents,
                "avg_cpl_cents": float(current.avg_cpl_cents or 0),
                "avg_conversion_rate": float(current.avg_conversion_rate or 0)
            },
            "last_year": {
                "conversions": last_year.conversions,
                "cost_cents": last_year.cost_cents,
                "avg_cpl_cents": float(last_year.avg_cpl_cents or 0),
                "avg_conversion_rate": float(last_year.avg_conversion_rate or 0)
            },
            "yoy_change": {
                "conversions_pct": yoy_conversions,
                "cost_pct": yoy_cost,
                "cpl_pct": yoy_cpl
            }
        }


def detect_day_of_week_patterns(campaign_id: int, days: int = 90) -> Dict[int, Dict[str, float]]:
    """
    Detect day-of-week performance patterns.

    Args:
        campaign_id: Campaign ID
        days: Number of days to analyze

    Returns:
        Dict mapping day_of_week (1-7) to performance metrics
    """
    end_date = date.today()
    start_date = end_date - timedelta(days=days)

    query = text("""
        SELECT
            day_of_week,
            AVG(conversions) as avg_conversions,
            AVG(cost_cents) as avg_cost_cents,
            AVG(cpl_cents) as avg_cpl_cents,
            AVG(conversion_rate) as avg_conversion_rate,
            COUNT(*) as sample_size
        FROM campaign_performance_history
        WHERE campaign_id = :campaign_id
          AND date BETWEEN :start_date AND :end_date
        GROUP BY day_of_week
        ORDER BY day_of_week
    """)

    with db.engine.connect() as conn:
        result = conn.execute(query, {
            "campaign_id": campaign_id,
            "start_date": start_date,
            "end_date": end_date
        })

        patterns = {}
        for row in result:
            patterns[row.day_of_week] = {
                "avg_conversions": float(row.avg_conversions or 0),
                "avg_cost_cents": float(row.avg_cost_cents or 0),
                "avg_cpl_cents": float(row.avg_cpl_cents or 0),
                "avg_conversion_rate": float(row.avg_conversion_rate or 0),
                "sample_size": row.sample_size
            }

        return patterns
