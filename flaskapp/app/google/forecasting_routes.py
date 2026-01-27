# app/google/forecasting_routes.py
"""
Budget Forecasting Routes - Dashboard and API endpoints for budget forecasting.
"""
from flask import Blueprint, render_template, jsonify, request, current_app
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, ProgrammingError
from datetime import datetime, date, timedelta
import calendar
import logging

from app import db
from app.auth.utils import login_required, current_account_id

# Import services with fallbacks for when they're not implemented
try:
    from app.services.budget_forecasting_service import (
        generate_monthly_forecast,
        generate_seasonal_budget_recommendations,
        detect_budget_anomalies,
        store_anomaly
    )
except ImportError:
    logging.warning("budget_forecasting_service not available - using stubs")

    def generate_monthly_forecast(*args, **kwargs):
        return {"success": False, "error": "Forecasting service not configured", "forecast": []}

    def generate_seasonal_budget_recommendations(*args, **kwargs):
        return []

    def detect_budget_anomalies(*args, **kwargs):
        return []

    def store_anomaly(*args, **kwargs):
        pass

try:
    from app.services.historical_data_service import (
        calculate_baseline_metrics,
        get_year_over_year_comparison,
        detect_day_of_week_patterns
    )
except ImportError:
    logging.warning("historical_data_service not available - using stubs")

    def calculate_baseline_metrics(*args, **kwargs):
        return {"avg_cost": 0, "avg_clicks": 0, "avg_conversions": 0}

    def get_year_over_year_comparison(*args, **kwargs):
        return {"change_pct": 0, "last_year": 0, "this_year": 0}

    def detect_day_of_week_patterns(*args, **kwargs):
        return {}

try:
    from app.services.weather_service import fetch_current_weather, fetch_weather_forecast
except ImportError:
    logging.warning("weather_service not available - using stubs")

    def fetch_current_weather(*args, **kwargs):
        return {"temp_high": 70, "temp_low": 50, "condition": "clear"}

    def fetch_weather_forecast(*args, **kwargs):
        return []


forecasting_bp = Blueprint("forecasting_bp", __name__, url_prefix="/account/google/ads/forecasting")


def _table_exists(table_name: str) -> bool:
    """Check if a database table exists."""
    try:
        with db.engine.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT COUNT(*) FROM information_schema.TABLES
                    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :table_name
                """),
                {"table_name": table_name}
            )
            return result.scalar() > 0
    except Exception as e:
        current_app.logger.warning(f"Could not check if table {table_name} exists: {e}")
        return False


def _safe_db_query(query_func, default=None):
    """
    Execute a database query safely, catching table-not-found errors.

    Args:
        query_func: A callable that executes the database query
        default: Default value to return on error

    Returns:
        Query result or default value
    """
    try:
        return query_func()
    except (OperationalError, ProgrammingError) as e:
        error_msg = str(e).lower()
        if "doesn't exist" in error_msg or "does not exist" in error_msg or "no such table" in error_msg:
            current_app.logger.warning(f"Database table does not exist: {e}")
        else:
            current_app.logger.error(f"Database error: {e}")
        return default
    except Exception as e:
        current_app.logger.error(f"Unexpected error in database query: {e}")
        return default


@forecasting_bp.route("/")
@login_required
def forecasting_dashboard():
    """
    Budget Forecasting Dashboard - View forecasts, trends, and recommendations.
    """
    from flask import session
    import importlib
    account_id = current_account_id()

    # Log the request for debugging
    current_app.logger.info(f"[FORECASTING] Loading dashboard for account {account_id}")

    # Import the function that fetches and caches ads data
    _get_ads_state = None
    _is_connected = None
    import_error = None

    try:
        # Use importlib for more explicit import
        google_module = importlib.import_module('app.google')
        _get_ads_state = getattr(google_module, '_get_ads_state', None)
        _is_connected = getattr(google_module, '_is_connected', None)
        current_app.logger.info(f"[FORECASTING] Import success: _get_ads_state={_get_ads_state is not None}, _is_connected={_is_connected is not None}")
    except ImportError as e:
        import_error = str(e)
        current_app.logger.error(f"[FORECASTING] Import failed: {e}")
    except Exception as e:
        import_error = str(e)
        current_app.logger.error(f"[FORECASTING] Unexpected import error: {e}")

    # Get campaigns using the proper state function (which handles fetching + caching)
    campaigns = []
    is_connected = False
    customer_id = None
    error_message = None

    # Handle import failure gracefully
    if import_error:
        current_app.logger.warning(f"[FORECASTING] Running with import error: {import_error}")
        error_message = "Some features may be unavailable due to a configuration issue."

    # First check if user is connected to Google Ads
    if _is_connected:
        try:
            is_connected = _is_connected(account_id, "ads")
            current_app.logger.info(f"[FORECASTING] Connection check: is_connected={is_connected}")
        except Exception as e:
            current_app.logger.warning(f"[FORECASTING] Error checking connection: {e}")
            is_connected = False
    else:
        current_app.logger.warning("[FORECASTING] _is_connected function not available")

    # Helper function to transform campaign data
    def _transform_campaign(campaign):
        """Safely transform campaign data with null checks."""
        try:
            daily_budget = campaign.get('daily_budget')
            if daily_budget is None:
                daily_budget = 0
            return {
                'id': campaign.get('id'),
                'name': campaign.get('name') or 'Unnamed Campaign',
                'daily_budget_cents': int(float(daily_budget) * 100),
                'google_campaign_id': campaign.get('google_campaign_id') or campaign.get('id'),
                'status': campaign.get('status') or 'unknown',
                'cost_30d': campaign.get('cost_30d') or 0,
                'conversions': campaign.get('conversions') or 0,
                'clicks': campaign.get('clicks') or 0,
                'impressions': campaign.get('impressions') or 0
            }
        except (TypeError, ValueError) as e:
            current_app.logger.warning(f"Error transforming campaign data: {e}")
            return None

    # Use _get_ads_state to fetch/cache the data (this is what populates the session)
    if _get_ads_state and is_connected:
        try:
            current_app.logger.info(f"[FORECASTING] Calling _get_ads_state for account {account_id}")
            ads_data = _get_ads_state(account_id)

            if ads_data:
                raw_campaigns = ads_data.get('campaigns', []) or []
                customer_id = ads_data.get('account_name') or ads_data.get('customer_id')
                current_app.logger.info(f"[FORECASTING] Got {len(raw_campaigns)} campaigns, customer_id={customer_id}")

                # Transform campaign data to the expected format
                for campaign in raw_campaigns:
                    transformed = _transform_campaign(campaign)
                    if transformed:
                        campaigns.append(transformed)
            else:
                current_app.logger.warning("[FORECASTING] _get_ads_state returned None")

        except Exception as e:
            current_app.logger.error(f"[FORECASTING] Error fetching ads state: {e}", exc_info=True)
            error_message = "Error loading campaign data. Please try refreshing."

    # Fallback to session if not connected or _get_ads_state not available
    if not campaigns:
        current_app.logger.info(f"[FORECASTING] Trying session fallback")
        ads_state_key = f"ads_state_{account_id}"
        try:
            if ads_state_key in session and session[ads_state_key]:
                ads_data = session[ads_state_key]
                raw_campaigns = ads_data.get('campaigns', []) or []
                customer_id = customer_id or ads_data.get('account_name') or ads_data.get('customer_id')

                # Mark as connected if we have live data
                if not is_connected:
                    is_connected = ads_data.get('__source') == 'live' or len(raw_campaigns) > 0

                current_app.logger.info(f"[FORECASTING] Session fallback: {len(raw_campaigns)} campaigns found")

                for campaign in raw_campaigns:
                    transformed = _transform_campaign(campaign)
                    if transformed:
                        campaigns.append(transformed)
            else:
                current_app.logger.info(f"[FORECASTING] No session data found for key {ads_state_key}")
        except Exception as e:
            current_app.logger.warning(f"[FORECASTING] Session access error: {e}")

    # Sort campaigns by name
    campaigns.sort(key=lambda c: (c.get('name') or '').lower())

    current_app.logger.info(f"[FORECASTING] Final result: {len(campaigns)} campaigns, is_connected={is_connected}")

    return render_template(
        "google/forecasting_dashboard.html",
        campaigns=campaigns,
        is_connected=is_connected,
        customer_id=customer_id,
        error_message=error_message
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

        # Store new anomalies (only if table exists)
        if _table_exists('budget_anomalies'):
            for anomaly in anomalies:
                # Check if this anomaly already exists
                def _check_existing():
                    check_query = text("""
                        SELECT id FROM budget_anomalies
                        WHERE campaign_id = :campaign_id
                          AND anomaly_type = :anomaly_type
                          AND affected_period_start = :date
                          AND resolved = FALSE
                    """)
                    with db.engine.connect() as conn:
                        return conn.execute(check_query, {
                            "campaign_id": campaign_id,
                            "anomaly_type": anomaly.get('anomaly_type', ''),
                            "date": anomaly.get('date')
                        }).first()

                existing = _safe_db_query(_check_existing)
                if not existing:
                    try:
                        store_anomaly(account_id, campaign_id, anomaly)
                    except Exception as store_err:
                        current_app.logger.warning(f"Could not store anomaly: {store_err}")
        else:
            current_app.logger.info("budget_anomalies table does not exist, skipping storage")

        return jsonify({
            "success": True,
            "anomalies": anomalies
        })

    except Exception as e:
        current_app.logger.exception(f"Error detecting anomalies: {e}")
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
