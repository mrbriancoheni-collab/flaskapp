# app/services/weather_service.py
"""
Weather Integration Service - Phase 3

Integrates with weather APIs to:
1. Fetch historical weather data for correlation analysis
2. Get current weather conditions for real-time budget adjustments
3. Retrieve weather forecasts for proactive budget planning
4. Detect extreme weather events that trigger demand spikes
"""

import os
import requests
from typing import Dict, List, Any, Optional
from datetime import datetime, date, timedelta
from sqlalchemy import text
from app import db


# Weather API Configuration (supports OpenWeatherMap, WeatherAPI, or NOAA)
WEATHER_API_KEY = os.getenv('WEATHER_API_KEY', '')
WEATHER_API_PROVIDER = os.getenv('WEATHER_API_PROVIDER', 'openweathermap')  # openweathermap, weatherapi, noaa


def fetch_current_weather(zip_code: str) -> Dict[str, Any]:
    """
    Fetch current weather conditions for a ZIP code.

    Args:
        zip_code: US ZIP code

    Returns:
        Dict with current weather data
    """
    if WEATHER_API_PROVIDER == 'openweathermap':
        return _fetch_openweathermap_current(zip_code)
    elif WEATHER_API_PROVIDER == 'weatherapi':
        return _fetch_weatherapi_current(zip_code)
    else:
        # Fallback mock data for development
        return _get_mock_weather(zip_code)


def fetch_weather_forecast(zip_code: str, days: int = 7) -> List[Dict[str, Any]]:
    """
    Fetch weather forecast for next N days.

    Args:
        zip_code: US ZIP code
        days: Number of days to forecast (max 7)

    Returns:
        List of daily forecast data
    """
    if WEATHER_API_PROVIDER == 'openweathermap':
        return _fetch_openweathermap_forecast(zip_code, days)
    elif WEATHER_API_PROVIDER == 'weatherapi':
        return _fetch_weatherapi_forecast(zip_code, days)
    else:
        return _get_mock_forecast(zip_code, days)


def fetch_historical_weather(zip_code: str, target_date: date) -> Dict[str, Any]:
    """
    Fetch historical weather data for a specific date.

    Args:
        zip_code: US ZIP code
        target_date: Date to fetch weather for

    Returns:
        Dict with historical weather data
    """
    # First check if we have it in database
    cached = get_cached_weather(zip_code, target_date)
    if cached:
        return cached

    # Fetch from API
    if WEATHER_API_PROVIDER == 'openweathermap':
        weather_data = _fetch_openweathermap_historical(zip_code, target_date)
    elif WEATHER_API_PROVIDER == 'weatherapi':
        weather_data = _fetch_weatherapi_historical(zip_code, target_date)
    else:
        weather_data = _get_mock_weather(zip_code)

    # Cache it
    if weather_data:
        store_weather_history(zip_code, target_date, weather_data)

    return weather_data


def store_weather_history(zip_code: str, target_date: date, weather_data: Dict[str, Any]) -> bool:
    """
    Store weather data in database for future use.

    Args:
        zip_code: US ZIP code
        target_date: Date of weather data
        weather_data: Weather data dict

    Returns:
        Success boolean
    """
    query = text("""
        INSERT INTO weather_history
            (zip_code, date, temp_high, temp_low, temp_avg,
             precipitation_inches, snow_inches, humidity_pct,
             condition, wind_speed_mph, is_extreme_weather, weather_alerts)
        VALUES
            (:zip_code, :date, :temp_high, :temp_low, :temp_avg,
             :precipitation, :snow, :humidity,
             :condition, :wind_speed, :is_extreme, :alerts)
        ON DUPLICATE KEY UPDATE
            temp_high = :temp_high,
            temp_low = :temp_low,
            temp_avg = :temp_avg,
            precipitation_inches = :precipitation,
            snow_inches = :snow,
            humidity_pct = :humidity,
            condition = :condition,
            wind_speed_mph = :wind_speed,
            is_extreme_weather = :is_extreme,
            weather_alerts = :alerts
    """)

    import json

    try:
        with db.engine.begin() as conn:
            conn.execute(query, {
                "zip_code": zip_code,
                "date": target_date,
                "temp_high": weather_data.get('temp_high'),
                "temp_low": weather_data.get('temp_low'),
                "temp_avg": weather_data.get('temp_avg'),
                "precipitation": weather_data.get('precipitation_inches', 0),
                "snow": weather_data.get('snow_inches', 0),
                "humidity": weather_data.get('humidity_pct'),
                "condition": weather_data.get('condition', 'unknown'),
                "wind_speed": weather_data.get('wind_speed_mph'),
                "is_extreme": weather_data.get('is_extreme_weather', False),
                "alerts": json.dumps(weather_data.get('alerts', []))
            })
        return True
    except Exception as e:
        print(f"Error storing weather history: {str(e)}")
        return False


def get_cached_weather(zip_code: str, target_date: date) -> Optional[Dict[str, Any]]:
    """Get cached weather data from database."""
    query = text("""
        SELECT * FROM weather_history
        WHERE zip_code = :zip_code AND date = :date
    """)

    with db.engine.connect() as conn:
        result = conn.execute(query, {
            "zip_code": zip_code,
            "date": target_date
        }).first()

        if result:
            return dict(result._mapping)
        return None


def detect_extreme_weather_events(
    zip_code: str,
    start_date: date,
    end_date: date,
    service_type: str
) -> List[Dict[str, Any]]:
    """
    Detect extreme weather events relevant to a service type.

    Args:
        zip_code: US ZIP code
        start_date: Start date
        end_date: End date
        service_type: Service type (hvac_ac, hvac_heat, plumbing, roofing, etc.)

    Returns:
        List of extreme weather events
    """
    # Define thresholds by service type
    thresholds = {
        'hvac_ac': {'temp_high': 90, 'condition': None},
        'hvac_heat': {'temp_low': 32, 'condition': None},
        'plumbing': {'temp_low': 32, 'condition': ['freeze', 'ice']},
        'roofing': {'condition': ['storm', 'hail', 'hurricane']},
        'electrical': {'condition': ['storm', 'lightning']}
    }

    threshold = thresholds.get(service_type, {})

    query_parts = ["SELECT * FROM weather_history WHERE zip_code = :zip_code AND date BETWEEN :start_date AND :end_date"]
    params = {
        "zip_code": zip_code,
        "start_date": start_date,
        "end_date": end_date
    }

    if 'temp_high' in threshold:
        query_parts.append("AND temp_high >= :temp_high")
        params['temp_high'] = threshold['temp_high']

    if 'temp_low' in threshold:
        query_parts.append("AND temp_low <= :temp_low")
        params['temp_low'] = threshold['temp_low']

    query = text(" ".join(query_parts) + " ORDER BY date")

    with db.engine.connect() as conn:
        result = conn.execute(query, params)
        events = [dict(row._mapping) for row in result]

    # Filter by condition if specified
    if threshold.get('condition'):
        conditions = threshold['condition']
        events = [e for e in events if any(c in e['condition'].lower() for c in conditions)]

    return events


def calculate_weather_impact_multiplier(
    current_weather: Dict[str, Any],
    service_type: str
) -> float:
    """
    Calculate demand multiplier based on current weather.

    Args:
        current_weather: Current weather data
        service_type: Service type

    Returns:
        Demand multiplier (1.0 = baseline, >1.0 = increased demand)
    """
    temp_high = current_weather.get('temp_high', 70)
    temp_low = current_weather.get('temp_low', 50)
    condition = current_weather.get('condition', 'clear').lower()

    multiplier = 1.0

    if service_type == 'hvac_ac':
        # Heat waves increase AC demand
        if temp_high >= 95:
            multiplier = 2.5
        elif temp_high >= 90:
            multiplier = 2.0
        elif temp_high >= 85:
            multiplier = 1.5

    elif service_type == 'hvac_heat':
        # Cold snaps increase heating demand
        if temp_low <= 20:
            multiplier = 2.5
        elif temp_low <= 32:
            multiplier = 2.0
        elif temp_low <= 40:
            multiplier = 1.5

    elif service_type == 'plumbing':
        # Freezing temps = frozen pipes
        if temp_low <= 20:
            multiplier = 2.0
        elif temp_low <= 32:
            multiplier = 1.6
        # Heavy rain = drain issues
        if 'rain' in condition or 'storm' in condition:
            multiplier *= 1.3

    elif service_type == 'roofing':
        # Storms increase roofing demand
        if 'storm' in condition or 'hail' in condition:
            multiplier = 2.5
        elif 'hurricane' in condition:
            multiplier = 3.0

    elif service_type == 'electrical':
        # Storms = power issues
        if 'storm' in condition or 'lightning' in condition:
            multiplier = 1.8

    return multiplier


# ============================================================================
# API Provider Implementations
# ============================================================================

def _fetch_openweathermap_current(zip_code: str) -> Dict[str, Any]:
    """Fetch current weather from OpenWeatherMap API."""
    if not WEATHER_API_KEY:
        return _get_mock_weather(zip_code)

    try:
        url = f"https://api.openweathermap.org/data/2.5/weather"
        params = {
            'zip': f"{zip_code},US",
            'appid': WEATHER_API_KEY,
            'units': 'imperial'
        }

        response = requests.get(url, params=params, timeout=5)
        response.raise_for_status()
        data = response.json()

        return {
            'temp_high': int(data['main']['temp_max']),
            'temp_low': int(data['main']['temp_min']),
            'temp_avg': int(data['main']['temp']),
            'humidity_pct': data['main']['humidity'],
            'condition': data['weather'][0]['main'].lower(),
            'wind_speed_mph': int(data['wind']['speed']),
            'is_extreme_weather': data['weather'][0]['main'].lower() in ['storm', 'thunderstorm', 'extreme'],
            'alerts': []
        }
    except Exception as e:
        print(f"Error fetching OpenWeatherMap data: {str(e)}")
        return _get_mock_weather(zip_code)


def _fetch_openweathermap_forecast(zip_code: str, days: int) -> List[Dict[str, Any]]:
    """Fetch forecast from OpenWeatherMap API."""
    if not WEATHER_API_KEY:
        return _get_mock_forecast(zip_code, days)

    try:
        url = f"https://api.openweathermap.org/data/2.5/forecast/daily"
        params = {
            'zip': f"{zip_code},US",
            'appid': WEATHER_API_KEY,
            'units': 'imperial',
            'cnt': days
        }

        response = requests.get(url, params=params, timeout=5)
        response.raise_for_status()
        data = response.json()

        forecast = []
        for day in data['list']:
            forecast.append({
                'date': datetime.fromtimestamp(day['dt']).date(),
                'temp_high': int(day['temp']['max']),
                'temp_low': int(day['temp']['min']),
                'condition': day['weather'][0]['main'].lower(),
                'precipitation_chance': day.get('pop', 0) * 100
            })

        return forecast
    except Exception as e:
        print(f"Error fetching OpenWeatherMap forecast: {str(e)}")
        return _get_mock_forecast(zip_code, days)


def _fetch_openweathermap_historical(zip_code: str, target_date: date) -> Dict[str, Any]:
    """Fetch historical weather from OpenWeatherMap API."""
    # Note: Historical weather requires paid plan
    # For now, return mock data
    return _get_mock_weather(zip_code)


def _fetch_weatherapi_current(zip_code: str) -> Dict[str, Any]:
    """Fetch current weather from WeatherAPI.com."""
    if not WEATHER_API_KEY:
        return _get_mock_weather(zip_code)

    try:
        url = f"https://api.weatherapi.com/v1/current.json"
        params = {
            'key': WEATHER_API_KEY,
            'q': zip_code
        }

        response = requests.get(url, params=params, timeout=5)
        response.raise_for_status()
        data = response.json()

        return {
            'temp_high': int(data['current']['temp_f']),  # Current temp (no daily high/low in current endpoint)
            'temp_low': int(data['current']['temp_f']),
            'temp_avg': int(data['current']['temp_f']),
            'humidity_pct': data['current']['humidity'],
            'condition': data['current']['condition']['text'].lower(),
            'wind_speed_mph': int(data['current']['wind_mph']),
            'is_extreme_weather': False,
            'alerts': []
        }
    except Exception as e:
        print(f"Error fetching WeatherAPI data: {str(e)}")
        return _get_mock_weather(zip_code)


def _fetch_weatherapi_forecast(zip_code: str, days: int) -> List[Dict[str, Any]]:
    """Fetch forecast from WeatherAPI.com."""
    if not WEATHER_API_KEY:
        return _get_mock_forecast(zip_code, days)

    try:
        url = f"https://api.weatherapi.com/v1/forecast.json"
        params = {
            'key': WEATHER_API_KEY,
            'q': zip_code,
            'days': days
        }

        response = requests.get(url, params=params, timeout=5)
        response.raise_for_status()
        data = response.json()

        forecast = []
        for day in data['forecast']['forecastday']:
            forecast.append({
                'date': datetime.strptime(day['date'], '%Y-%m-%d').date(),
                'temp_high': int(day['day']['maxtemp_f']),
                'temp_low': int(day['day']['mintemp_f']),
                'condition': day['day']['condition']['text'].lower(),
                'precipitation_chance': day['day']['daily_chance_of_rain']
            })

        return forecast
    except Exception as e:
        print(f"Error fetching WeatherAPI forecast: {str(e)}")
        return _get_mock_forecast(zip_code, days)


def _fetch_weatherapi_historical(zip_code: str, target_date: date) -> Dict[str, Any]:
    """Fetch historical weather from WeatherAPI.com."""
    if not WEATHER_API_KEY:
        return _get_mock_weather(zip_code)

    try:
        url = f"https://api.weatherapi.com/v1/history.json"
        params = {
            'key': WEATHER_API_KEY,
            'q': zip_code,
            'dt': target_date.strftime('%Y-%m-%d')
        }

        response = requests.get(url, params=params, timeout=5)
        response.raise_for_status()
        data = response.json()

        day = data['forecast']['forecastday'][0]

        return {
            'temp_high': int(day['day']['maxtemp_f']),
            'temp_low': int(day['day']['mintemp_f']),
            'temp_avg': int(day['day']['avgtemp_f']),
            'humidity_pct': day['day']['avghumidity'],
            'condition': day['day']['condition']['text'].lower(),
            'precipitation_inches': day['day']['totalprecip_in'],
            'snow_inches': day['day'].get('totalsnow_cm', 0) * 0.393701,  # cm to inches
            'is_extreme_weather': False,
            'alerts': []
        }
    except Exception as e:
        print(f"Error fetching WeatherAPI historical: {str(e)}")
        return _get_mock_weather(zip_code)


# ============================================================================
# Mock Data for Development
# ============================================================================

def _get_mock_weather(zip_code: str) -> Dict[str, Any]:
    """Return mock weather data for development."""
    return {
        'temp_high': 75,
        'temp_low': 55,
        'temp_avg': 65,
        'humidity_pct': 60,
        'condition': 'clear',
        'wind_speed_mph': 10,
        'precipitation_inches': 0,
        'snow_inches': 0,
        'is_extreme_weather': False,
        'alerts': []
    }


def _get_mock_forecast(zip_code: str, days: int) -> List[Dict[str, Any]]:
    """Return mock forecast data for development."""
    forecast = []
    today = date.today()

    for i in range(days):
        forecast.append({
            'date': today + timedelta(days=i),
            'temp_high': 75 + (i * 2),
            'temp_low': 55 + i,
            'condition': 'clear',
            'precipitation_chance': 10
        })

    return forecast
