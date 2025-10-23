# app/services/yoy_analysis.py
"""
Year-over-Year (YoY) performance analysis service.
Compares current performance to same period last year to measure improvement.
"""

from __future__ import annotations
import datetime as dt
from typing import Dict, List, Optional, Any
from dateutil.relativedelta import relativedelta

from app import db
from app.models_ads import PerformanceMetrics
from sqlalchemy import func


def get_yoy_comparison(
    account_id: int,
    source_type: str,
    start_date: dt.date,
    end_date: Optional[dt.date] = None,
    source_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Compare performance metrics to the same period last year.

    Args:
        account_id: Account ID
        source_type: Source type identifier
        start_date: Start date for current period
        end_date: End date for current period (defaults to start_date)
        source_id: Optional source ID filter

    Returns:
        Dictionary with current, prior year, and comparison metrics
    """
    if end_date is None:
        end_date = start_date

    # Calculate prior year dates
    prior_start = start_date - relativedelta(years=1)
    prior_end = end_date - relativedelta(years=1)

    # Get current period metrics
    current_metrics = _get_period_aggregates(
        account_id, source_type, start_date, end_date, source_id
    )

    # Get prior year metrics
    prior_metrics = _get_period_aggregates(
        account_id, source_type, prior_start, prior_end, source_id
    )

    # Calculate YoY changes
    comparison = {
        'current_period': {
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat(),
            'metrics': current_metrics
        },
        'prior_year': {
            'start_date': prior_start.isoformat(),
            'end_date': prior_end.isoformat(),
            'metrics': prior_metrics
        },
        'yoy_change': _calculate_changes(current_metrics, prior_metrics),
        'yoy_percent': _calculate_percent_changes(current_metrics, prior_metrics)
    }

    return comparison


def get_monthly_yoy_comparison(
    account_id: int,
    source_type: str,
    year: int,
    month: int,
    source_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Compare a specific month to the same month last year.

    Args:
        account_id: Account ID
        source_type: Source type identifier
        year: Year of current month
        month: Month (1-12)
        source_id: Optional source ID filter

    Returns:
        Dictionary with monthly comparison
    """
    # Get date range for current month
    start_date = dt.date(year, month, 1)
    if month == 12:
        end_date = dt.date(year + 1, 1, 1) - dt.timedelta(days=1)
    else:
        end_date = dt.date(year, month + 1, 1) - dt.timedelta(days=1)

    return get_yoy_comparison(
        account_id=account_id,
        source_type=source_type,
        start_date=start_date,
        end_date=end_date,
        source_id=source_id
    )


def get_ytd_yoy_comparison(
    account_id: int,
    source_type: str,
    as_of_date: Optional[dt.date] = None,
    source_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Compare year-to-date performance to prior year-to-date.

    Args:
        account_id: Account ID
        source_type: Source type identifier
        as_of_date: End date for comparison (defaults to today)
        source_id: Optional source ID filter

    Returns:
        Dictionary with YTD comparison
    """
    if as_of_date is None:
        as_of_date = dt.date.today()

    # Current YTD: Jan 1 to as_of_date
    current_start = dt.date(as_of_date.year, 1, 1)
    current_end = as_of_date

    # Prior YTD: Jan 1 last year to same date last year
    prior_start = dt.date(as_of_date.year - 1, 1, 1)
    prior_end = as_of_date - relativedelta(years=1)

    current_metrics = _get_period_aggregates(
        account_id, source_type, current_start, current_end, source_id
    )

    prior_metrics = _get_period_aggregates(
        account_id, source_type, prior_start, prior_end, source_id
    )

    return {
        'current_ytd': {
            'start_date': current_start.isoformat(),
            'end_date': current_end.isoformat(),
            'metrics': current_metrics
        },
        'prior_ytd': {
            'start_date': prior_start.isoformat(),
            'end_date': prior_end.isoformat(),
            'metrics': prior_metrics
        },
        'yoy_change': _calculate_changes(current_metrics, prior_metrics),
        'yoy_percent': _calculate_percent_changes(current_metrics, prior_metrics)
    }


def get_all_channels_yoy_summary(
    account_id: int,
    start_date: dt.date,
    end_date: Optional[dt.date] = None
) -> Dict[str, Any]:
    """
    Get YoY comparison for all channels (sources) at once.

    Args:
        account_id: Account ID
        start_date: Start date for current period
        end_date: End date for current period

    Returns:
        Dictionary with per-channel YoY comparisons
    """
    if end_date is None:
        end_date = start_date

    channels = ['google_ads', 'google_analytics', 'search_console', 'glsa', 'gmb', 'fbads']

    summary = {
        'period': {
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat()
        },
        'channels': {}
    }

    for channel in channels:
        try:
            comparison = get_yoy_comparison(
                account_id=account_id,
                source_type=channel,
                start_date=start_date,
                end_date=end_date
            )
            summary['channels'][channel] = comparison
        except Exception:
            # Skip channels with no data
            continue

    return summary


def get_baseline_vs_current(
    account_id: int,
    source_type: str,
    baseline_start: dt.date,
    baseline_end: dt.date,
    current_start: dt.date,
    current_end: dt.date,
    source_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Compare current performance to a baseline period (e.g., before using FieldSprout).

    Args:
        account_id: Account ID
        source_type: Source type identifier
        baseline_start: Start of baseline period
        baseline_end: End of baseline period
        current_start: Start of current period
        current_end: End of current period
        source_id: Optional source ID filter

    Returns:
        Dictionary with baseline vs current comparison
    """
    baseline_metrics = _get_period_aggregates(
        account_id, source_type, baseline_start, baseline_end, source_id
    )

    current_metrics = _get_period_aggregates(
        account_id, source_type, current_start, current_end, source_id
    )

    return {
        'baseline_period': {
            'start_date': baseline_start.isoformat(),
            'end_date': baseline_end.isoformat(),
            'metrics': baseline_metrics,
            'label': 'Before FieldSprout'
        },
        'current_period': {
            'start_date': current_start.isoformat(),
            'end_date': current_end.isoformat(),
            'metrics': current_metrics,
            'label': 'After FieldSprout'
        },
        'improvement': _calculate_changes(current_metrics, baseline_metrics),
        'improvement_percent': _calculate_percent_changes(current_metrics, baseline_metrics)
    }


def _get_period_aggregates(
    account_id: int,
    source_type: str,
    start_date: dt.date,
    end_date: dt.date,
    source_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get aggregated metrics for a date range.

    Returns:
        Dictionary with summed impressions, clicks, spend, conversions
    """
    query = db.session.query(
        func.sum(PerformanceMetrics.impressions).label('impressions'),
        func.sum(PerformanceMetrics.clicks).label('clicks'),
        func.sum(PerformanceMetrics.spend).label('spend'),
        func.sum(PerformanceMetrics.conversions).label('conversions'),
        func.count(PerformanceMetrics.id).label('days')
    ).filter(
        PerformanceMetrics.account_id == account_id,
        PerformanceMetrics.source_type == source_type,
        PerformanceMetrics.date >= start_date,
        PerformanceMetrics.date <= end_date
    )

    if source_id:
        query = query.filter(PerformanceMetrics.source_id == source_id)

    result = query.first()

    impressions = int(result.impressions or 0)
    clicks = int(result.clicks or 0)
    spend = float(result.spend or 0.0)
    conversions = float(result.conversions or 0.0)
    days = int(result.days or 0)

    return {
        'impressions': impressions,
        'clicks': clicks,
        'spend': spend,
        'conversions': conversions,
        'leads': conversions,  # Alias for conversions
        'days': days,
        'ctr': round((clicks / impressions * 100) if impressions > 0 else 0, 2),
        'cpc': round((spend / clicks) if clicks > 0 else 0, 2),
        'cpa': round((spend / conversions) if conversions > 0 else 0, 2),
        'cost_per_lead': round((spend / conversions) if conversions > 0 else 0, 2)
    }


def _calculate_changes(current: Dict[str, Any], prior: Dict[str, Any]) -> Dict[str, Any]:
    """Calculate absolute changes between two periods."""
    changes = {}
    for key in ['impressions', 'clicks', 'spend', 'conversions', 'leads']:
        if key in current and key in prior:
            changes[key] = current[key] - prior[key]
    return changes


def _calculate_percent_changes(current: Dict[str, Any], prior: Dict[str, Any]) -> Dict[str, Any]:
    """Calculate percent changes between two periods."""
    percent_changes = {}
    for key in ['impressions', 'clicks', 'spend', 'conversions', 'leads']:
        if key in current and key in prior:
            prior_val = prior[key]
            current_val = current[key]
            if prior_val > 0:
                percent_changes[key] = round(((current_val - prior_val) / prior_val) * 100, 2)
            else:
                percent_changes[key] = 0.0 if current_val == 0 else 100.0
    return percent_changes


def get_monthly_trend(
    account_id: int,
    source_type: str,
    months: int = 12,
    source_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Get month-by-month metrics for trend analysis.

    Args:
        account_id: Account ID
        source_type: Source type identifier
        months: Number of months to retrieve (default 12)
        source_id: Optional source ID filter

    Returns:
        List of monthly aggregates
    """
    end_date = dt.date.today()
    start_date = end_date - relativedelta(months=months)

    query = db.session.query(
        func.year(PerformanceMetrics.date).label('year'),
        func.month(PerformanceMetrics.date).label('month'),
        func.sum(PerformanceMetrics.impressions).label('impressions'),
        func.sum(PerformanceMetrics.clicks).label('clicks'),
        func.sum(PerformanceMetrics.spend).label('spend'),
        func.sum(PerformanceMetrics.conversions).label('conversions')
    ).filter(
        PerformanceMetrics.account_id == account_id,
        PerformanceMetrics.source_type == source_type,
        PerformanceMetrics.date >= start_date,
        PerformanceMetrics.date <= end_date
    )

    if source_id:
        query = query.filter(PerformanceMetrics.source_id == source_id)

    query = query.group_by('year', 'month').order_by('year', 'month')

    results = []
    for row in query.all():
        impressions = int(row.impressions or 0)
        clicks = int(row.clicks or 0)
        spend = float(row.spend or 0.0)
        conversions = float(row.conversions or 0.0)

        results.append({
            'year': row.year,
            'month': row.month,
            'month_name': dt.date(row.year, row.month, 1).strftime('%B'),
            'impressions': impressions,
            'clicks': clicks,
            'spend': spend,
            'conversions': conversions,
            'leads': conversions,
            'ctr': round((clicks / impressions * 100) if impressions > 0 else 0, 2),
            'cpc': round((spend / clicks) if clicks > 0 else 0, 2),
            'cost_per_lead': round((spend / conversions) if conversions > 0 else 0, 2)
        })

    return results
