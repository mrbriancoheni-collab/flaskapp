# app/budget_forecast/__init__.py
"""
Budget Forecasting Module
Provides predictive budget recommendations and scenario modeling.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from flask import (
    Blueprint,
    current_app,
    render_template,
    jsonify,
    request,
)
from sqlalchemy import text

from app import db
from app.auth.utils import login_required, current_account_id, is_paid_account

budget_forecast_bp = Blueprint("budget_forecast_bp", __name__, url_prefix="/account/budget-forecast")


def _get_historical_performance(aid: int, days: int = 90) -> Dict[str, Any]:
    """Get historical campaign performance data."""
    try:
        with db.engine.connect() as conn:
            row = conn.execute(
                text("""
                    SELECT
                        SUM(cost_micros) / 1000000 as total_cost,
                        SUM(clicks) as total_clicks,
                        SUM(impressions) as total_impressions,
                        SUM(conversions) as total_conversions,
                        COUNT(DISTINCT id) as campaign_count
                    FROM google_ads_campaigns
                    WHERE account_id = :aid
                      AND status = 'ENABLED'
                """),
                {"aid": aid}
            ).mappings().first()

            if row:
                total_cost = float(row.get("total_cost") or 0)
                total_clicks = int(row.get("total_clicks") or 0)
                total_conversions = float(row.get("total_conversions") or 0)

                return {
                    "total_cost": total_cost,
                    "total_clicks": total_clicks,
                    "total_impressions": int(row.get("total_impressions") or 0),
                    "total_conversions": total_conversions,
                    "campaign_count": int(row.get("campaign_count") or 0),
                    "avg_cpc": total_cost / total_clicks if total_clicks > 0 else 0,
                    "avg_cpa": total_cost / total_conversions if total_conversions > 0 else 0,
                    "conversion_rate": (total_conversions / total_clicks * 100) if total_clicks > 0 else 0
                }
    except Exception as e:
        current_app.logger.error(f"Error getting historical performance: {e}")

    return {
        "total_cost": 0, "total_clicks": 0, "total_impressions": 0,
        "total_conversions": 0, "campaign_count": 0,
        "avg_cpc": 0, "avg_cpa": 0, "conversion_rate": 0
    }


def _get_current_budget(aid: int) -> float:
    """Get current monthly budget."""
    try:
        with db.engine.connect() as conn:
            row = conn.execute(
                text("""
                    SELECT SUM(daily_budget_micros) / 1000000 * 30 as monthly_budget
                    FROM google_ads_campaigns
                    WHERE account_id = :aid
                      AND status = 'ENABLED'
                """),
                {"aid": aid}
            ).mappings().first()
            return float(row.get("monthly_budget") or 0) if row else 0
    except Exception:
        return 0


def forecast_results(
    current_budget: float,
    new_budget: float,
    avg_cpc: float,
    conversion_rate: float,
    avg_cpa: float
) -> Dict[str, Any]:
    """
    Forecast results based on budget change.
    Uses simple linear scaling with diminishing returns for large increases.
    """
    if current_budget <= 0 or avg_cpc <= 0:
        return {
            "predicted_clicks": 0,
            "predicted_conversions": 0,
            "predicted_cost": new_budget,
            "change_percent": 0
        }

    budget_ratio = new_budget / current_budget if current_budget > 0 else 1

    # Apply diminishing returns for budget increases > 50%
    if budget_ratio > 1.5:
        effective_ratio = 1.5 + (budget_ratio - 1.5) * 0.7  # 70% efficiency on excess
    else:
        effective_ratio = budget_ratio

    current_clicks = current_budget / avg_cpc if avg_cpc > 0 else 0
    predicted_clicks = current_clicks * effective_ratio

    predicted_conversions = predicted_clicks * (conversion_rate / 100) if conversion_rate > 0 else 0

    return {
        "predicted_clicks": int(predicted_clicks),
        "predicted_conversions": round(predicted_conversions, 1),
        "predicted_cost": new_budget,
        "predicted_cpa": new_budget / predicted_conversions if predicted_conversions > 0 else 0,
        "change_percent": int((budget_ratio - 1) * 100)
    }


def generate_recommendations(
    performance: Dict[str, Any],
    current_budget: float
) -> List[Dict[str, Any]]:
    """Generate budget recommendations based on performance."""
    recommendations = []

    avg_cpa = performance.get("avg_cpa", 0)
    conversion_rate = performance.get("conversion_rate", 0)
    avg_cpc = performance.get("avg_cpc", 0)

    # Recommendation 1: If CPA is good, suggest increase
    if avg_cpa > 0 and avg_cpa < 100:
        increase_budget = current_budget * 1.25
        forecast = forecast_results(current_budget, increase_budget, avg_cpc, conversion_rate, avg_cpa)
        recommendations.append({
            "type": "increase",
            "title": "Grow Your Leads",
            "description": f"Your cost per lead (${avg_cpa:.0f}) is efficient. Increasing budget could get you more leads.",
            "current_budget": current_budget,
            "suggested_budget": increase_budget,
            "predicted_conversions": forecast["predicted_conversions"],
            "predicted_change": "+25%",
            "confidence": "high",
            "icon": "fa-chart-line",
            "color": "green"
        })

    # Recommendation 2: Conservative growth
    if current_budget > 0:
        small_increase = current_budget * 1.1
        forecast = forecast_results(current_budget, small_increase, avg_cpc, conversion_rate, avg_cpa)
        recommendations.append({
            "type": "conservative",
            "title": "Safe Growth",
            "description": "A small budget increase to test the waters without major risk.",
            "current_budget": current_budget,
            "suggested_budget": small_increase,
            "predicted_conversions": forecast["predicted_conversions"],
            "predicted_change": "+10%",
            "confidence": "high",
            "icon": "fa-shield-check",
            "color": "blue"
        })

    # Recommendation 3: If CPA is high, suggest optimization first
    if avg_cpa > 150:
        recommendations.append({
            "type": "optimize",
            "title": "Optimize First",
            "description": f"Your cost per lead (${avg_cpa:.0f}) is high. Focus on optimization before increasing budget.",
            "current_budget": current_budget,
            "suggested_budget": current_budget,
            "predicted_conversions": performance.get("total_conversions", 0),
            "predicted_change": "0%",
            "confidence": "medium",
            "icon": "fa-wrench",
            "color": "yellow",
            "action_url": "/account/google/ads/opportunities"
        })

    # Recommendation 4: Aggressive growth (for good performers)
    if avg_cpa > 0 and avg_cpa < 75 and conversion_rate > 3:
        aggressive_budget = current_budget * 1.5
        forecast = forecast_results(current_budget, aggressive_budget, avg_cpc, conversion_rate, avg_cpa)
        recommendations.append({
            "type": "aggressive",
            "title": "Accelerate Growth",
            "description": "Your campaigns are performing well. Consider a significant budget increase.",
            "current_budget": current_budget,
            "suggested_budget": aggressive_budget,
            "predicted_conversions": forecast["predicted_conversions"],
            "predicted_change": "+50%",
            "confidence": "medium",
            "icon": "fa-rocket",
            "color": "purple"
        })

    return recommendations[:3]  # Return top 3 recommendations


# -------------------- Routes --------------------

@budget_forecast_bp.route("/", methods=["GET"])
@login_required
def index():
    """Budget forecasting dashboard."""
    aid = current_account_id()
    if not aid:
        return jsonify({"error": "Account not found"}), 404

    performance = _get_historical_performance(aid)
    current_budget = _get_current_budget(aid)
    recommendations = generate_recommendations(performance, current_budget)

    # Generate scenario comparisons
    scenarios = []
    for multiplier, label in [(0.75, "-25%"), (1.0, "Current"), (1.25, "+25%"), (1.5, "+50%"), (2.0, "+100%")]:
        budget = current_budget * multiplier
        forecast = forecast_results(
            current_budget, budget,
            performance.get("avg_cpc", 2.5),
            performance.get("conversion_rate", 3),
            performance.get("avg_cpa", 50)
        )
        scenarios.append({
            "label": label,
            "budget": budget,
            "clicks": forecast["predicted_clicks"],
            "conversions": forecast["predicted_conversions"],
            "is_current": multiplier == 1.0
        })

    return render_template(
        "budget_forecast/index.html",
        performance=performance,
        current_budget=current_budget,
        recommendations=recommendations,
        scenarios=scenarios,
        is_paid=is_paid_account()
    )


@budget_forecast_bp.route("/api/forecast", methods=["POST"])
@login_required
def api_forecast():
    """API endpoint for custom budget forecasting."""
    aid = current_account_id()
    if not aid:
        return jsonify({"error": "Account not found"}), 404

    data = request.get_json() or {}
    new_budget = float(data.get("budget", 0))

    performance = _get_historical_performance(aid)
    current_budget = _get_current_budget(aid)

    forecast = forecast_results(
        current_budget, new_budget,
        performance.get("avg_cpc", 2.5),
        performance.get("conversion_rate", 3),
        performance.get("avg_cpa", 50)
    )

    return jsonify(forecast)
