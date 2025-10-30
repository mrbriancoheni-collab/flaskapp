"""
Customer Impact Service

Calculates and tracks savings and additional leads generated for each customer
compared to their pre-FieldSprout baseline performance.
"""
from __future__ import annotations
import datetime as dt
from typing import Dict, Optional, List
from sqlalchemy import func

from app import db
from app.models_ads import PerformanceMetrics, CustomerImpact
from app.models import Account


def calculate_baseline_metrics(account_id: int, start_date: dt.date, end_date: dt.date) -> Dict:
    """
    Calculate baseline metrics for a customer from historical data.

    Args:
        account_id: Account ID
        start_date: Start date of baseline period
        end_date: End date of baseline period

    Returns:
        Dictionary with baseline metrics (monthly_spend, monthly_leads, cost_per_lead)
    """
    # Query performance metrics for the baseline period
    metrics = PerformanceMetrics.query.filter(
        PerformanceMetrics.account_id == account_id,
        PerformanceMetrics.date >= start_date,
        PerformanceMetrics.date <= end_date
    ).all()

    if not metrics:
        return {
            'monthly_spend': 0,
            'monthly_leads': 0,
            'cost_per_lead': 0,
            'days': 0
        }

    # Aggregate totals
    total_spend = sum(m.spend or 0 for m in metrics)
    total_leads = sum(m.conversions or 0 for m in metrics)
    days = (end_date - start_date).days + 1

    # Calculate monthly averages
    monthly_spend = (total_spend / days) * 30 if days > 0 else 0
    monthly_leads = (total_leads / days) * 30 if days > 0 else 0
    cost_per_lead = total_spend / total_leads if total_leads > 0 else 0

    return {
        'monthly_spend': round(monthly_spend, 2),
        'monthly_leads': round(monthly_leads, 2),
        'cost_per_lead': round(cost_per_lead, 2),
        'days': days
    }


def calculate_current_metrics(account_id: int, days: int = 30) -> Dict:
    """
    Calculate current performance metrics for a customer.

    Args:
        account_id: Account ID
        days: Number of days to analyze (default: 30)

    Returns:
        Dictionary with current metrics (monthly_spend, monthly_leads, cost_per_lead)
    """
    end_date = dt.date.today()
    start_date = end_date - dt.timedelta(days=days)

    # Query recent performance metrics
    metrics = PerformanceMetrics.query.filter(
        PerformanceMetrics.account_id == account_id,
        PerformanceMetrics.date >= start_date,
        PerformanceMetrics.date <= end_date
    ).all()

    if not metrics:
        return {
            'monthly_spend': 0,
            'monthly_leads': 0,
            'cost_per_lead': 0
        }

    # Aggregate totals
    total_spend = sum(m.spend or 0 for m in metrics)
    total_leads = sum(m.conversions or 0 for m in metrics)

    # Calculate monthly averages
    monthly_spend = (total_spend / days) * 30
    monthly_leads = (total_leads / days) * 30
    cost_per_lead = total_spend / total_leads if total_leads > 0 else 0

    return {
        'monthly_spend': round(monthly_spend, 2),
        'monthly_leads': round(monthly_leads, 2),
        'cost_per_lead': round(cost_per_lead, 2)
    }


def update_customer_impact(account_id: int) -> CustomerImpact:
    """
    Update or create customer impact record with current calculations.

    Args:
        account_id: Account ID

    Returns:
        Updated CustomerImpact record
    """
    # Get or create impact record
    impact = CustomerImpact.query.filter_by(account_id=account_id).first()
    if not impact:
        impact = CustomerImpact(account_id=account_id)
        db.session.add(impact)

    # Calculate current metrics
    current = calculate_current_metrics(account_id)
    impact.current_monthly_spend = current['monthly_spend']
    impact.current_monthly_leads = current['monthly_leads']
    impact.current_cost_per_lead = current['cost_per_lead']

    # If we have baseline data, calculate savings and additional leads
    if impact.baseline_monthly_spend > 0 or impact.baseline_monthly_leads > 0:
        # Calculate monthly savings (reduction in spend for same or better results)
        monthly_savings = impact.baseline_monthly_spend - impact.current_monthly_spend

        # Calculate additional leads (increase in leads)
        monthly_additional_leads = impact.current_monthly_leads - impact.baseline_monthly_leads

        # Update monthly metrics
        impact.monthly_savings = round(monthly_savings, 2)
        impact.monthly_additional_leads = round(monthly_additional_leads, 2)

        # Update running totals
        # If this is first calculation, initialize totals
        if not impact.last_calculated_at:
            impact.total_savings = impact.monthly_savings
            impact.total_additional_leads = impact.monthly_additional_leads
        else:
            # Add monthly values to running totals
            # (This assumes monthly calculations, adjust frequency as needed)
            days_since_last = (dt.datetime.utcnow() - impact.last_calculated_at).days
            if days_since_last >= 30:  # Only add if it's been at least 30 days
                impact.total_savings += impact.monthly_savings
                impact.total_additional_leads += impact.monthly_additional_leads

    impact.last_calculated_at = dt.datetime.utcnow()
    db.session.commit()

    return impact


def set_customer_baseline(
    account_id: int,
    start_date: dt.date,
    end_date: dt.date
) -> CustomerImpact:
    """
    Set baseline metrics for a customer from historical data.

    Args:
        account_id: Account ID
        start_date: Start date of baseline period
        end_date: End date of baseline period

    Returns:
        Updated CustomerImpact record
    """
    # Calculate baseline metrics
    baseline = calculate_baseline_metrics(account_id, start_date, end_date)

    # Get or create impact record
    impact = CustomerImpact.query.filter_by(account_id=account_id).first()
    if not impact:
        impact = CustomerImpact(account_id=account_id)
        db.session.add(impact)

    # Update baseline data
    impact.baseline_start_date = start_date
    impact.baseline_end_date = end_date
    impact.baseline_monthly_spend = baseline['monthly_spend']
    impact.baseline_monthly_leads = baseline['monthly_leads']
    impact.baseline_cost_per_lead = baseline['cost_per_lead']

    db.session.commit()

    # Now update current metrics and calculate impact
    return update_customer_impact(account_id)


def get_aggregate_impact() -> Dict:
    """
    Get aggregate impact metrics across all customers for marketing purposes.

    Returns:
        Dictionary with total_savings, total_additional_leads, customer_count
    """
    result = db.session.query(
        func.sum(CustomerImpact.total_savings).label('total_savings'),
        func.sum(CustomerImpact.total_additional_leads).label('total_additional_leads'),
        func.count(CustomerImpact.id).label('customer_count')
    ).first()

    return {
        'total_savings': round(result.total_savings or 0, 2),
        'total_additional_leads': round(result.total_additional_leads or 0, 2),
        'customer_count': result.customer_count or 0
    }


def get_top_performing_customers(limit: int = 10) -> List[Dict]:
    """
    Get top performing customers by total savings.

    Args:
        limit: Number of customers to return

    Returns:
        List of dictionaries with customer data
    """
    impacts = (
        CustomerImpact.query
        .filter(CustomerImpact.total_savings > 0)
        .order_by(CustomerImpact.total_savings.desc())
        .limit(limit)
        .all()
    )

    result = []
    for impact in impacts:
        account = Account.query.get(impact.account_id)
        result.append({
            'account_id': impact.account_id,
            'account_name': account.name if account else 'Unknown',
            'total_savings': impact.total_savings,
            'total_additional_leads': impact.total_additional_leads,
            'monthly_savings': impact.monthly_savings,
            'monthly_additional_leads': impact.monthly_additional_leads,
            'baseline_cost_per_lead': impact.baseline_cost_per_lead,
            'current_cost_per_lead': impact.current_cost_per_lead
        })

    return result


def update_all_customer_impacts() -> Dict:
    """
    Update impact calculations for all customers with baseline data.

    Returns:
        Summary of updates performed
    """
    impacts = CustomerImpact.query.filter(
        CustomerImpact.baseline_monthly_spend > 0
    ).all()

    updated_count = 0
    error_count = 0

    for impact in impacts:
        try:
            update_customer_impact(impact.account_id)
            updated_count += 1
        except Exception as e:
            error_count += 1
            print(f"Error updating impact for account {impact.account_id}: {e}")

    return {
        'updated': updated_count,
        'errors': error_count,
        'total': len(impacts)
    }
