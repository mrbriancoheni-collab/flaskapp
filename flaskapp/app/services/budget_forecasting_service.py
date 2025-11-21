# app/services/budget_forecasting_service.py
"""
Budget Forecasting Engine - Phase 2 & 4

Combines historical data, seasonality curves, weather forecasts, and capacity
constraints to generate intelligent budget forecasts and recommendations.
"""

import os
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, date, timedelta
from sqlalchemy import text
from app import db
from app.services.historical_data_service import calculate_baseline_metrics, get_year_over_year_comparison
from app.services.weather_service import fetch_weather_forecast, calculate_weather_impact_multiplier
import calendar


def generate_monthly_forecast(
    account_id: int,
    campaign_id: int,
    service_type: str,
    target_month: int,
    target_year: int,
    include_weather: bool = True,
    include_capacity: bool = False
) -> Dict[str, Any]:
    """
    Generate a comprehensive monthly budget forecast.

    Args:
        account_id: Account ID
        campaign_id: Campaign ID
        service_type: Service type (hvac_ac, plumbing, etc.)
        target_month: Month to forecast (1-12)
        target_year: Year to forecast
        include_weather: Include weather forecast in calculations
        include_capacity: Consider tech capacity constraints

    Returns:
        Dict with forecast details
    """
    # 1. Get baseline metrics from historical data (90 days)
    baseline = calculate_baseline_metrics(campaign_id, days=90)

    if not baseline:
        return {
            "success": False,
            "error": "Insufficient historical data for forecast"
        }

    # 2. Get seasonality multiplier for target month
    seasonality_multiplier = get_seasonality_multiplier(
        service_type=service_type,
        month=target_month
    )

    # 3. Get weather forecast impact (if enabled)
    weather_multiplier = 1.0
    if include_weather:
        # For now, use historical weather patterns for the month
        weather_multiplier = get_weather_impact_for_month(
            service_type=service_type,
            month=target_month
        )

    # 4. Get capacity constraints (if enabled)
    capacity_adjustment = 1.0
    if include_capacity:
        capacity_adjustment = get_capacity_adjustment(
            account_id=account_id,
            service_type=service_type,
            target_month=target_month
        )

    # 5. Calculate combined multiplier
    combined_multiplier = seasonality_multiplier['demand_multiplier'] * weather_multiplier * capacity_adjustment

    # 6. Project metrics
    days_in_month = calendar.monthrange(target_year, target_month)[1]

    projected_daily_conversions = baseline['avg_daily_conversions'] * combined_multiplier
    projected_monthly_conversions = projected_daily_conversions * days_in_month

    # CPL also varies with seasonality
    cpl_multiplier = seasonality_multiplier['cpl_multiplier']
    projected_cpl_cents = baseline['avg_cpl_cents'] * cpl_multiplier

    projected_monthly_spend_cents = projected_monthly_conversions * projected_cpl_cents
    projected_monthly_revenue_cents = projected_monthly_spend_cents * baseline['avg_roas']

    # 7. Calculate confidence intervals (variance)
    stddev_multiplier = 1.96  # 95% confidence interval
    variance_low_cents = int(projected_monthly_spend_cents - (baseline['stddev_cpl_cents'] * projected_monthly_conversions * stddev_multiplier))
    variance_high_cents = int(projected_monthly_spend_cents + (baseline['stddev_cpl_cents'] * projected_monthly_conversions * stddev_multiplier))

    # 8. Calculate confidence score
    confidence_score = calculate_forecast_confidence(
        baseline=baseline,
        has_weather_data=include_weather,
        has_capacity_data=include_capacity,
        days_of_history=90
    )

    # 9. Store forecast in database
    forecast_data = {
        "account_id": account_id,
        "forecast_type": "monthly",
        "forecast_date": date.today(),
        "period_start": date(target_year, target_month, 1),
        "period_end": date(target_year, target_month, days_in_month),
        "projected_spend_cents": int(projected_monthly_spend_cents),
        "projected_leads": int(projected_monthly_conversions),
        "projected_revenue_cents": int(projected_monthly_revenue_cents),
        "projected_roas": baseline['avg_roas'],
        "confidence_score": confidence_score,
        "variance_low_cents": max(0, variance_low_cents),
        "variance_high_cents": variance_high_cents,
        "uses_historical_data": True,
        "uses_seasonality": True,
        "uses_weather_forecast": include_weather,
        "uses_capacity_constraints": include_capacity,
        "uses_ml_model": False
    }

    save_forecast(forecast_data)

    return {
        "success": True,
        "forecast": {
            "period": f"{calendar.month_name[target_month]} {target_year}",
            "projected_spend": projected_monthly_spend_cents / 100,
            "projected_leads": int(projected_monthly_conversions),
            "projected_cpl": projected_cpl_cents / 100,
            "projected_revenue": projected_monthly_revenue_cents / 100,
            "projected_roas": round(baseline['avg_roas'], 2),
            "confidence_score": round(confidence_score, 2),
            "variance": {
                "low": variance_low_cents / 100,
                "high": variance_high_cents / 100
            }
        },
        "factors": {
            "baseline_daily_conversions": round(baseline['avg_daily_conversions'], 2),
            "seasonality_multiplier": round(seasonality_multiplier['demand_multiplier'], 2),
            "weather_multiplier": round(weather_multiplier, 2),
            "capacity_adjustment": round(capacity_adjustment, 2),
            "combined_multiplier": round(combined_multiplier, 2)
        }
    }


def get_seasonality_multiplier(service_type: str, month: int) -> Dict[str, float]:
    """
    Get seasonality multipliers for a service type and month.

    Args:
        service_type: Service type (hvac_ac, plumbing, etc.)
        month: Month (1-12)

    Returns:
        Dict with demand, CPL, and conversion rate multipliers
    """
    query = text("""
        SELECT
            demand_multiplier,
            cpl_multiplier,
            conversion_rate_multiplier
        FROM service_seasonality_curves
        WHERE service_type = :service_type
          AND month = :month
        ORDER BY confidence_score DESC
        LIMIT 1
    """)

    with db.engine.connect() as conn:
        result = conn.execute(query, {
            "service_type": service_type,
            "month": month
        }).first()

        if result:
            return {
                "demand_multiplier": float(result.demand_multiplier),
                "cpl_multiplier": float(result.cpl_multiplier),
                "conversion_rate_multiplier": float(result.conversion_rate_multiplier)
            }

    # Default to baseline if no seasonality data
    return {
        "demand_multiplier": 1.0,
        "cpl_multiplier": 1.0,
        "conversion_rate_multiplier": 1.0
    }


def get_weather_impact_for_month(service_type: str, month: int) -> float:
    """
    Get average weather impact multiplier for a month based on historical patterns.

    Args:
        service_type: Service type
        month: Month (1-12)

    Returns:
        Weather multiplier
    """
    # Get historical weather data for this month across all years
    query = text("""
        SELECT AVG(temp_high) as avg_temp_high, AVG(temp_low) as avg_temp_low
        FROM weather_history
        WHERE month = :month
    """)

    with db.engine.connect() as conn:
        result = conn.execute(query, {"month": month}).first()

        if result:
            mock_weather = {
                'temp_high': int(result.avg_temp_high or 70),
                'temp_low': int(result.avg_temp_low or 50),
                'condition': 'clear'
            }
            return calculate_weather_impact_multiplier(mock_weather, service_type)

    return 1.0


def get_capacity_adjustment(account_id: int, service_type: str, target_month: int) -> float:
    """
    Get capacity-based budget adjustment.

    If techs are fully booked, reduce budget multiplier.

    Args:
        account_id: Account ID
        service_type: Service type
        target_month: Target month

    Returns:
        Capacity adjustment multiplier (0.5-1.0)
    """
    # Get average capacity utilization for this service type
    query = text("""
        SELECT AVG(capacity_utilization) as avg_utilization
        FROM capacity_tracking
        WHERE account_id = :account_id
          AND service_type = :service_type
          AND date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
    """)

    with db.engine.connect() as conn:
        result = conn.execute(query, {
            "account_id": account_id,
            "service_type": service_type
        }).first()

        if result and result.avg_utilization:
            utilization = float(result.avg_utilization)

            # If >90% booked, reduce budget significantly
            if utilization >= 0.90:
                return 0.5
            # If >80% booked, reduce somewhat
            elif utilization >= 0.80:
                return 0.7
            # If >70% booked, reduce slightly
            elif utilization >= 0.70:
                return 0.85

    return 1.0  # No adjustment


def calculate_forecast_confidence(
    baseline: Dict[str, float],
    has_weather_data: bool,
    has_capacity_data: bool,
    days_of_history: int
) -> float:
    """
    Calculate confidence score for a forecast.

    Args:
        baseline: Baseline metrics
        has_weather_data: Whether weather data was used
        has_capacity_data: Whether capacity data was used
        days_of_history: Days of historical data used

    Returns:
        Confidence score (0-1)
    """
    confidence = 0.5  # Base confidence

    # More history = higher confidence
    if days_of_history >= 365:
        confidence += 0.2
    elif days_of_history >= 180:
        confidence += 0.15
    elif days_of_history >= 90:
        confidence += 0.1

    # Lower variance = higher confidence
    if baseline.get('stddev_cpl_cents', 0) < baseline.get('avg_cpl_cents', 1) * 0.2:
        confidence += 0.1

    # Weather data adds confidence
    if has_weather_data:
        confidence += 0.1

    # Capacity data adds confidence
    if has_capacity_data:
        confidence += 0.1

    return min(confidence, 0.95)  # Cap at 95%


def save_forecast(forecast_data: Dict[str, Any]) -> int:
    """
    Save forecast to database.

    Args:
        forecast_data: Forecast data dict

    Returns:
        Forecast ID
    """
    import json

    query = text("""
        INSERT INTO budget_forecasts
            (account_id, forecast_type, forecast_date, period_start, period_end,
             projected_spend_cents, projected_leads, projected_revenue_cents, projected_roas,
             confidence_score, variance_low_cents, variance_high_cents,
             uses_historical_data, uses_seasonality, uses_weather_forecast,
             uses_capacity_constraints, uses_ml_model)
        VALUES
            (:account_id, :forecast_type, :forecast_date, :period_start, :period_end,
             :projected_spend_cents, :projected_leads, :projected_revenue_cents, :projected_roas,
             :confidence_score, :variance_low_cents, :variance_high_cents,
             :uses_historical_data, :uses_seasonality, :uses_weather_forecast,
             :uses_capacity_constraints, :uses_ml_model)
    """)

    with db.engine.begin() as conn:
        result = conn.execute(query, forecast_data)
        return result.lastrowid


def generate_seasonal_budget_recommendations(
    account_id: int,
    campaign_id: int,
    service_type: str,
    current_monthly_budget: float
) -> List[Dict[str, Any]]:
    """
    Generate month-by-month budget recommendations for next 12 months based on seasonality.

    Args:
        account_id: Account ID
        campaign_id: Campaign ID
        service_type: Service type
        current_monthly_budget: Current monthly budget

    Returns:
        List of monthly budget recommendations
    """
    recommendations = []
    today = date.today()

    for i in range(12):
        target_date = today + timedelta(days=30 * i)
        target_month = target_date.month
        target_year = target_date.year

        # Get forecast
        forecast = generate_monthly_forecast(
            account_id=account_id,
            campaign_id=campaign_id,
            service_type=service_type,
            target_month=target_month,
            target_year=target_year
        )

        if forecast['success']:
            projected_spend = forecast['forecast']['projected_spend']
            seasonality_factor = forecast['factors']['combined_multiplier']

            # Recommend budget adjustment
            recommended_budget = current_monthly_budget * seasonality_factor

            # Calculate impact
            budget_change = recommended_budget - current_monthly_budget
            budget_change_pct = (budget_change / current_monthly_budget) * 100

            recommendations.append({
                "month": calendar.month_name[target_month],
                "year": target_year,
                "current_budget": current_monthly_budget,
                "recommended_budget": round(recommended_budget, 2),
                "budget_change": round(budget_change, 2),
                "budget_change_pct": round(budget_change_pct, 1),
                "projected_leads": forecast['forecast']['projected_leads'],
                "seasonality_factor": round(seasonality_factor, 2),
                "confidence": forecast['forecast']['confidence_score']
            })

    return recommendations


def detect_budget_anomalies(campaign_id: int, lookback_days: int = 7) -> List[Dict[str, Any]]:
    """
    Detect anomalies in campaign performance using statistical analysis.

    Phase 4: Anomaly Detection

    Args:
        campaign_id: Campaign ID
        lookback_days: Days to analyze

    Returns:
        List of detected anomalies
    """
    # Get baseline metrics (90 days)
    baseline = calculate_baseline_metrics(campaign_id, days=90)

    if not baseline:
        return []

    # Get recent performance
    end_date = date.today()
    start_date = end_date - timedelta(days=lookback_days)

    query = text("""
        SELECT
            date,
            cpl_cents,
            conversion_rate,
            cost_cents / 100 as daily_spend
        FROM campaign_performance_history
        WHERE campaign_id = :campaign_id
          AND date BETWEEN :start_date AND :end_date
        ORDER BY date DESC
    """)

    anomalies = []

    with db.engine.connect() as conn:
        result = conn.execute(query, {
            "campaign_id": campaign_id,
            "start_date": start_date,
            "end_date": end_date
        })

        for row in result:
            # Calculate Z-scores
            cpl_z_score = 0
            if baseline['stddev_cpl_cents'] > 0:
                cpl_z_score = (row.cpl_cents - baseline['avg_cpl_cents']) / baseline['stddev_cpl_cents']

            conv_rate_z_score = 0
            if baseline['stddev_conversion_rate'] > 0:
                conv_rate_z_score = (row.conversion_rate - baseline['avg_conversion_rate']) / baseline['stddev_conversion_rate']

            # Detect CPL spike (Z-score > 2 = 95% confidence it's anomalous)
            if abs(cpl_z_score) > 2:
                deviation_pct = ((row.cpl_cents - baseline['avg_cpl_cents']) / baseline['avg_cpl_cents']) * 100

                anomalies.append({
                    "date": row.date,
                    "anomaly_type": "cpl_spike" if cpl_z_score > 0 else "cpl_drop",
                    "severity": "high" if abs(cpl_z_score) > 3 else "medium",
                    "metric_name": "cpl",
                    "baseline_value": baseline['avg_cpl_cents'] / 100,
                    "actual_value": row.cpl_cents / 100,
                    "deviation_pct": round(deviation_pct, 1),
                    "z_score": round(cpl_z_score, 2),
                    "confidence_score": min(abs(cpl_z_score) / 4, 0.99)
                })

            # Detect conversion rate drop
            if conv_rate_z_score < -2:
                deviation_pct = ((row.conversion_rate - baseline['avg_conversion_rate']) / baseline['avg_conversion_rate']) * 100

                anomalies.append({
                    "date": row.date,
                    "anomaly_type": "conversion_drop",
                    "severity": "high" if conv_rate_z_score < -3 else "medium",
                    "metric_name": "conversion_rate",
                    "baseline_value": round(baseline['avg_conversion_rate'], 2),
                    "actual_value": round(row.conversion_rate, 2),
                    "deviation_pct": round(deviation_pct, 1),
                    "z_score": round(conv_rate_z_score, 2),
                    "confidence_score": min(abs(conv_rate_z_score) / 4, 0.99)
                })

    return anomalies


def store_anomaly(
    account_id: int,
    campaign_id: int,
    anomaly_data: Dict[str, Any]
) -> int:
    """
    Store detected anomaly in database.

    Args:
        account_id: Account ID
        campaign_id: Campaign ID
        anomaly_data: Anomaly data

    Returns:
        Anomaly ID
    """
    query = text("""
        INSERT INTO budget_anomalies
            (account_id, campaign_id, anomaly_type, severity,
             metric_name, baseline_value, actual_value, deviation_pct,
             z_score, confidence_score, affected_period_start,
             requires_manual_review)
        VALUES
            (:account_id, :campaign_id, :anomaly_type, :severity,
             :metric_name, :baseline_value, :actual_value, :deviation_pct,
             :z_score, :confidence_score, :affected_period_start,
             :requires_manual_review)
    """)

    with db.engine.begin() as conn:
        result = conn.execute(query, {
            "account_id": account_id,
            "campaign_id": campaign_id,
            "anomaly_type": anomaly_data['anomaly_type'],
            "severity": anomaly_data['severity'],
            "metric_name": anomaly_data['metric_name'],
            "baseline_value": anomaly_data['baseline_value'],
            "actual_value": anomaly_data['actual_value'],
            "deviation_pct": anomaly_data['deviation_pct'],
            "z_score": anomaly_data.get('z_score'),
            "confidence_score": anomaly_data['confidence_score'],
            "affected_period_start": anomaly_data['date'],
            "requires_manual_review": True
        })
        return result.lastrowid
