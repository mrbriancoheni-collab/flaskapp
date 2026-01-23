# app/google/forecasting_routes.py
"""
Budget Forecasting Routes - Dashboard and API endpoints for budget forecasting.
"""
from flask import Blueprint, render_template, jsonify, request
from sqlalchemy import text
from datetime import datetime, date, timedelta
import calendar

from app import db
from app.auth.utils import login_required, current_account_id
from app.services.budget_forecasting_service import (
    generate_monthly_forecast,
    generate_seasonal_budget_recommendations,
    detect_budget_anomalies,
    store_anomaly
)
from app.services.historical_data_service import (
    calculate_baseline_metrics,
    get_year_over_year_comparison,
    detect_day_of_week_patterns
)
from app.services.weather_service import fetch_current_weather, fetch_weather_forecast

forecasting_bp = Blueprint("forecasting_bp", __name__, url_prefix="/account/google/ads/forecasting")


@forecasting_bp.route("/")
@login_required
def forecasting_dashboard():
    """
    Budget Forecasting Dashboard - View forecasts, trends, and recommendations.
    """
    from flask import session, current_app
    import logging
    account_id = current_account_id()

    # Import the function that fetches and caches ads data
    try:
        from app.google import _get_ads_state, _is_connected
    except ImportError:
        logging.error("Could not import _get_ads_state from app.google")
        _get_ads_state = None
        _is_connected = None

    # Get campaigns using the proper state function (which handles fetching + caching)
    campaigns = []
    is_connected = False
    customer_id = None

    # First check if user is connected to Google Ads
    if _is_connected:
        try:
            is_connected = _is_connected(account_id, "ads")
        except Exception as e:
            logging.warning(f"Error checking connection: {e}")
            is_connected = False

    # Use _get_ads_state to fetch/cache the data (this is what populates the session)
    if _get_ads_state and is_connected:
        try:
            ads_data = _get_ads_state(account_id)
            raw_campaigns = ads_data.get('campaigns', [])
            customer_id = ads_data.get('account_name') or ads_data.get('customer_id')

            # Transform campaign data to the expected format
            for campaign in raw_campaigns:
                campaigns.append({
                    'id': campaign.get('id'),
                    'name': campaign.get('name'),
                    'daily_budget_cents': int(float(campaign.get('daily_budget') or 0) * 100),
                    'google_campaign_id': campaign.get('google_campaign_id') or campaign.get('id'),
                    'status': campaign.get('status', 'unknown'),
                    'cost_30d': campaign.get('cost_30d', 0),
                    'conversions': campaign.get('conversions', 0),
                    'clicks': campaign.get('clicks', 0),
                    'impressions': campaign.get('impressions', 0)
                })

            # Sort by name
            campaigns.sort(key=lambda c: c.get('name', '').lower())
            logging.info(f"Forecasting: Found {len(campaigns)} campaigns for account {account_id}")
        except Exception as e:
            logging.error(f"Error fetching ads state: {e}")
    else:
        # Fallback to session if _get_ads_state not available
        ads_state_key = f"ads_state_{account_id}"
        if ads_state_key in session and session[ads_state_key]:
            ads_data = session[ads_state_key]
            raw_campaigns = ads_data.get('campaigns', [])
            customer_id = ads_data.get('account_name') or ads_data.get('customer_id')
            is_connected = ads_data.get('__source') == 'live' or len(raw_campaigns) > 0

            for campaign in raw_campaigns:
                campaigns.append({
                    'id': campaign.get('id'),
                    'name': campaign.get('name'),
                    'daily_budget_cents': int(float(campaign.get('daily_budget') or 0) * 100),
                    'google_campaign_id': campaign.get('google_campaign_id') or campaign.get('id'),
                    'status': campaign.get('status', 'unknown'),
                    'cost_30d': campaign.get('cost_30d', 0),
                    'conversions': campaign.get('conversions', 0),
                    'clicks': campaign.get('clicks', 0),
                    'impressions': campaign.get('impressions', 0)
                })
            campaigns.sort(key=lambda c: c.get('name', '').lower())

    if not campaigns:
        logging.warning(f"Forecasting: No campaigns found for account {account_id}, is_connected={is_connected}")

    return render_template(
        "google/forecasting_dashboard.html",
        campaigns=campaigns,
        is_connected=is_connected,
        customer_id=customer_id
    )


@forecasting_bp.route("/api/forecast/monthly", methods=["POST"])
@login_required
def get_monthly_forecast():
    """Generate monthly forecast for a campaign."""
    account_id = current_account_id()
    data = request.get_json()

    campaign_id = data.get('campaign_id')
    service_type = data.get('service_type', 'hvac_ac')
    target_month = data.get('month', date.today().month)
    target_year = data.get('year', date.today().year)

    try:
        forecast = generate_monthly_forecast(
            account_id=account_id,
            campaign_id=campaign_id,
            service_type=service_type,
            target_month=target_month,
            target_year=target_year,
            include_weather=True,
            include_capacity=False
        )

        return jsonify(forecast)

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@forecasting_bp.route("/api/forecast/seasonal", methods=["POST"])
@login_required
def get_seasonal_recommendations():
    """Get 12-month seasonal budget recommendations."""
    account_id = current_account_id()
    data = request.get_json()

    campaign_id = data.get('campaign_id')
    service_type = data.get('service_type', 'hvac_ac')
    current_budget = data.get('current_monthly_budget', 5000)

    try:
        recommendations = generate_seasonal_budget_recommendations(
            account_id=account_id,
            campaign_id=campaign_id,
            service_type=service_type,
            current_monthly_budget=current_budget
        )

        return jsonify({
            "success": True,
            "recommendations": recommendations
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@forecasting_bp.route("/api/baseline/<int:campaign_id>", methods=["GET"])
@login_required
def get_campaign_baseline(campaign_id):
    """Get baseline metrics for a campaign."""
    try:
        baseline = calculate_baseline_metrics(campaign_id, days=90)
        yoy = get_year_over_year_comparison(campaign_id, date.today())
        dow_patterns = detect_day_of_week_patterns(campaign_id, days=90)

        return jsonify({
            "success": True,
            "baseline": baseline,
            "year_over_year": yoy,
            "day_of_week_patterns": dow_patterns
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@forecasting_bp.route("/api/anomalies/<int:campaign_id>", methods=["GET"])
@login_required
def get_campaign_anomalies(campaign_id):
    """Detect anomalies in campaign performance."""
    account_id = current_account_id()

    try:
        anomalies = detect_budget_anomalies(campaign_id, lookback_days=7)

        # Store new anomalies
        for anomaly in anomalies:
            # Check if this anomaly already exists
            check_query = text("""
                SELECT id FROM budget_anomalies
                WHERE campaign_id = :campaign_id
                  AND anomaly_type = :anomaly_type
                  AND affected_period_start = :date
                  AND resolved = FALSE
            """)

            with db.engine.connect() as conn:
                existing = conn.execute(check_query, {
                    "campaign_id": campaign_id,
                    "anomaly_type": anomaly['anomaly_type'],
                    "date": anomaly['date']
                }).first()

                if not existing:
                    store_anomaly(account_id, campaign_id, anomaly)

        return jsonify({
            "success": True,
            "anomalies": anomalies
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@forecasting_bp.route("/api/weather/current", methods=["POST"])
@login_required
def get_current_weather_impact():
    """Get current weather and its impact on budget."""
    data = request.get_json()

    zip_code = data.get('zip_code', '10001')
    service_type = data.get('service_type', 'hvac_ac')

    try:
        weather = fetch_current_weather(zip_code)

        from app.services.weather_service import calculate_weather_impact_multiplier
        impact_multiplier = calculate_weather_impact_multiplier(weather, service_type)

        return jsonify({
            "success": True,
            "weather": weather,
            "impact_multiplier": impact_multiplier,
            "recommendation": get_weather_recommendation(impact_multiplier)
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@forecasting_bp.route("/api/weather/forecast", methods=["POST"])
@login_required
def get_weather_forecast_impact():
    """Get 7-day weather forecast and budget impact."""
    data = request.get_json()

    zip_code = data.get('zip_code', '10001')
    service_type = data.get('service_type', 'hvac_ac')

    try:
        forecast = fetch_weather_forecast(zip_code, days=7)

        # Calculate impact for each day
        from app.services.weather_service import calculate_weather_impact_multiplier
        for day in forecast:
            day['impact_multiplier'] = calculate_weather_impact_multiplier({
                'temp_high': day['temp_high'],
                'temp_low': day['temp_low'],
                'condition': day['condition']
            }, service_type)

        return jsonify({
            "success": True,
            "forecast": forecast
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


def get_weather_recommendation(multiplier: float) -> str:
    """Get budget recommendation based on weather impact multiplier."""
    if multiplier >= 2.5:
        return "CRITICAL: Extreme weather event. Increase budget by 100%+ immediately."
    elif multiplier >= 2.0:
        return "HIGH DEMAND: Increase budget by 50-100% to capture seasonal spike."
    elif multiplier >= 1.5:
        return "MODERATE INCREASE: Consider increasing budget by 25-50%."
    elif multiplier >= 1.2:
        return "SLIGHT INCREASE: Weather favors your service. Increase budget by 10-25%."
    elif multiplier <= 0.8:
        return "REDUCE BUDGET: Low demand period. Consider reducing budget by 20-30%."
    else:
        return "MAINTAIN: Weather conditions are normal for your service."
