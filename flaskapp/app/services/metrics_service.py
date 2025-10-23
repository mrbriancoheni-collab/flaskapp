# app/services/metrics_service.py
"""
Unified service for storing and retrieving performance metrics across all platforms.
Supports Google Ads, Analytics, Search Console, GLSA, GMB, and Facebook Ads.
"""

from __future__ import annotations
import json
import datetime as dt
from typing import Dict, List, Optional, Any
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app import db
from app.models_ads import PerformanceMetrics


def save_metrics(
    account_id: int,
    source_type: str,
    date: dt.date,
    metrics: Dict[str, Any],
    source_id: Optional[str] = None,
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    entity_name: Optional[str] = None,
    timeframe: str = 'daily'
) -> PerformanceMetrics:
    """
    Save or update performance metrics for a given source and date.

    Args:
        account_id: Account ID
        source_type: 'google_ads', 'google_analytics', 'search_console', 'glsa', 'gmb', 'fbads'
        date: Date of the metrics
        metrics: Dictionary of metrics to store
        source_id: Property ID, Site URL, Customer ID, Page ID, etc.
        entity_type: Optional entity type for drilldown
        entity_id: Optional entity ID for drilldown
        entity_name: Optional entity name for display
        timeframe: 'daily', 'weekly', or 'monthly'

    Returns:
        PerformanceMetrics instance
    """
    # Extract common metrics for quick querying
    impressions = metrics.get('impressions') or metrics.get('views')
    clicks = metrics.get('clicks')
    spend = metrics.get('spend') or metrics.get('cost') or metrics.get('cost_micros', 0) / 1_000_000
    conversions = metrics.get('conversions')

    # Use upsert (PostgreSQL) or find and update (SQLite/MySQL)
    metric_record = PerformanceMetrics.query.filter_by(
        account_id=account_id,
        source_type=source_type,
        source_id=source_id,
        entity_type=entity_type,
        entity_id=entity_id,
        date=date,
        timeframe=timeframe
    ).first()

    if metric_record:
        # Update existing record
        metric_record.metrics_json = json.dumps(metrics)
        metric_record.impressions = impressions
        metric_record.clicks = clicks
        metric_record.spend = spend
        metric_record.conversions = conversions
        metric_record.entity_name = entity_name
        metric_record.updated_at = dt.datetime.utcnow()
    else:
        # Create new record
        metric_record = PerformanceMetrics(
            account_id=account_id,
            source_type=source_type,
            source_id=source_id,
            entity_type=entity_type,
            entity_id=entity_id,
            entity_name=entity_name,
            date=date,
            timeframe=timeframe,
            metrics_json=json.dumps(metrics),
            impressions=impressions,
            clicks=clicks,
            spend=spend,
            conversions=conversions
        )
        db.session.add(metric_record)

    db.session.commit()
    return metric_record


def save_metrics_batch(
    account_id: int,
    source_type: str,
    metrics_list: List[Dict[str, Any]],
    source_id: Optional[str] = None,
    timeframe: str = 'daily'
) -> int:
    """
    Save multiple metrics records in batch for better performance.

    Args:
        account_id: Account ID
        source_type: Source type identifier
        metrics_list: List of metric dictionaries, each containing:
            - date: Date of the metrics
            - metrics: Dictionary of metrics
            - entity_type: Optional entity type
            - entity_id: Optional entity ID
            - entity_name: Optional entity name
        source_id: Optional source ID
        timeframe: Timeframe granularity

    Returns:
        Number of records saved
    """
    count = 0
    for item in metrics_list:
        date = item.get('date')
        metrics = item.get('metrics', {})
        entity_type = item.get('entity_type')
        entity_id = item.get('entity_id')
        entity_name = item.get('entity_name')

        if not date or not metrics:
            continue

        save_metrics(
            account_id=account_id,
            source_type=source_type,
            date=date,
            metrics=metrics,
            source_id=source_id,
            entity_type=entity_type,
            entity_id=entity_id,
            entity_name=entity_name,
            timeframe=timeframe
        )
        count += 1

    return count


def get_metrics(
    account_id: int,
    source_type: str,
    start_date: dt.date,
    end_date: Optional[dt.date] = None,
    source_id: Optional[str] = None,
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    timeframe: str = 'daily'
) -> List[PerformanceMetrics]:
    """
    Retrieve performance metrics for a given source and date range.

    Args:
        account_id: Account ID
        source_type: Source type identifier
        start_date: Start date (inclusive)
        end_date: End date (inclusive), defaults to start_date
        source_id: Optional source ID filter
        entity_type: Optional entity type filter
        entity_id: Optional entity ID filter
        timeframe: Timeframe granularity

    Returns:
        List of PerformanceMetrics records
    """
    if end_date is None:
        end_date = start_date

    query = PerformanceMetrics.query.filter(
        PerformanceMetrics.account_id == account_id,
        PerformanceMetrics.source_type == source_type,
        PerformanceMetrics.date >= start_date,
        PerformanceMetrics.date <= end_date,
        PerformanceMetrics.timeframe == timeframe
    )

    if source_id:
        query = query.filter(PerformanceMetrics.source_id == source_id)

    if entity_type:
        query = query.filter(PerformanceMetrics.entity_type == entity_type)

    if entity_id:
        query = query.filter(PerformanceMetrics.entity_id == entity_id)

    return query.order_by(PerformanceMetrics.date.asc()).all()


def get_metrics_summary(
    account_id: int,
    source_type: str,
    start_date: dt.date,
    end_date: Optional[dt.date] = None,
    source_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get aggregated metrics summary for a date range.

    Args:
        account_id: Account ID
        source_type: Source type identifier
        start_date: Start date (inclusive)
        end_date: End date (inclusive), defaults to start_date
        source_id: Optional source ID filter

    Returns:
        Dictionary with aggregated metrics
    """
    metrics = get_metrics(
        account_id=account_id,
        source_type=source_type,
        start_date=start_date,
        end_date=end_date,
        source_id=source_id
    )

    total_impressions = 0
    total_clicks = 0
    total_spend = 0.0
    total_conversions = 0.0

    for m in metrics:
        total_impressions += m.impressions or 0
        total_clicks += m.clicks or 0
        total_spend += m.spend or 0.0
        total_conversions += m.conversions or 0.0

    summary = {
        'impressions': total_impressions,
        'clicks': total_clicks,
        'spend': total_spend,
        'conversions': total_conversions,
        'ctr': (total_clicks / total_impressions * 100) if total_impressions > 0 else 0,
        'cpc': (total_spend / total_clicks) if total_clicks > 0 else 0,
        'cpa': (total_spend / total_conversions) if total_conversions > 0 else 0,
        'days': len(metrics)
    }

    return summary


def get_trend_data(
    account_id: int,
    source_type: str,
    metric_name: str,
    days: int = 30,
    source_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Get trend data for a specific metric over time.

    Args:
        account_id: Account ID
        source_type: Source type identifier
        metric_name: Name of metric to track (e.g., 'impressions', 'clicks', 'spend')
        days: Number of days to look back
        source_id: Optional source ID filter

    Returns:
        List of {date, value} dictionaries
    """
    end_date = dt.date.today()
    start_date = end_date - dt.timedelta(days=days - 1)

    metrics = get_metrics(
        account_id=account_id,
        source_type=source_type,
        start_date=start_date,
        end_date=end_date,
        source_id=source_id
    )

    trend_data = []
    for m in metrics:
        value = None

        # Check common fields first
        if metric_name in ['impressions', 'clicks', 'spend', 'conversions']:
            value = getattr(m, metric_name, None)
        else:
            # Parse JSON for source-specific metrics
            try:
                metrics_dict = json.loads(m.metrics_json)
                value = metrics_dict.get(metric_name)
            except (json.JSONDecodeError, AttributeError):
                value = None

        trend_data.append({
            'date': m.date.isoformat(),
            'value': value
        })

    return trend_data
