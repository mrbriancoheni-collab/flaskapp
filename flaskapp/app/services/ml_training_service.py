# app/services/ml_training_service.py
"""
ML Training Service

Prepares training data for ML models to predict demand, CPL, and conversions.

Features:
- Comprehensive feature engineering (40+ features)
- Seasonality curves for HVAC, plumbing, electrical, roofing
- Weather integration (with fallback)
- Capacity utilization
- CSV export for Google Colab, Jupyter, sklearn, TensorFlow, PyTorch
- Model metadata tracking
"""

from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta, date
from decimal import Decimal
import logging
import csv
import io

logger = logging.getLogger(__name__)


class MLTrainingService:
    """Service for ML model training data preparation."""

    # Seasonality curves (demand multipliers by month, 1-12)
    SEASONALITY_CURVES = {
        'hvac_heating': {
            1: 2.5, 2: 2.3, 3: 1.8, 4: 1.2, 5: 0.8, 6: 0.5,
            7: 0.4, 8: 0.5, 9: 0.8, 10: 1.5, 11: 2.0, 12: 2.4
        },
        'hvac_cooling': {
            1: 0.4, 2: 0.5, 3: 0.8, 4: 1.5, 5: 2.0, 6: 2.5,
            7: 2.8, 8: 2.6, 9: 2.0, 10: 1.2, 11: 0.7, 12: 0.5
        },
        'plumbing_general': {
            1: 1.2, 2: 1.1, 3: 1.0, 4: 1.0, 5: 1.1, 6: 1.2,
            7: 1.3, 8: 1.2, 9: 1.1, 10: 1.0, 11: 1.0, 12: 1.1
        },
        'plumbing_emergency': {
            1: 1.5, 2: 1.3, 3: 1.0, 4: 0.9, 5: 1.0, 6: 1.1,
            7: 1.2, 8: 1.1, 9: 1.0, 10: 1.0, 11: 1.3, 12: 1.6
        },
        'electrical': {
            1: 0.9, 2: 0.9, 3: 1.0, 4: 1.1, 5: 1.2, 6: 1.3,
            7: 1.4, 8: 1.3, 9: 1.2, 10: 1.1, 11: 1.0, 12: 0.9
        },
        'roofing': {
            1: 0.6, 2: 0.7, 3: 1.0, 4: 1.5, 5: 2.0, 6: 2.2,
            7: 2.3, 8: 2.4, 9: 2.2, 10: 1.8, 11: 1.2, 12: 0.7
        },
        'landscaping': {
            1: 0.4, 2: 0.5, 3: 1.0, 4: 1.8, 5: 2.5, 6: 2.8,
            7: 2.6, 8: 2.4, 9: 2.0, 10: 1.5, 11: 0.8, 12: 0.5
        },
        'snow_removal': {
            1: 2.5, 2: 2.2, 3: 1.5, 4: 0.5, 5: 0.2, 6: 0.1,
            7: 0.1, 8: 0.1, 9: 0.2, 10: 0.8, 11: 1.8, 12: 2.4
        }
    }

    # US Holidays
    HOLIDAYS = [
        (1, 1),   # New Year's Day
        (7, 4),   # July 4th
        (11, 24), # Thanksgiving (approximate)
        (12, 25), # Christmas
        (12, 31)  # New Year's Eve
    ]

    def __init__(self, db_connection):
        """
        Initialize the service.

        Args:
            db_connection: Database connection object
        """
        self.db = db_connection

    def prepare_training_data(
        self,
        account_id: int,
        customer_id: str,
        start_date: date,
        end_date: date,
        industry: str = 'hvac_heating',
        include_weather: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Prepare comprehensive training data with all features.

        Args:
            account_id: Account ID
            customer_id: Google Ads customer ID
            start_date: Start date for historical data
            end_date: End date for historical data
            industry: Industry for seasonality curves
            include_weather: Whether to fetch weather data

        Returns:
            List of feature dictionaries (one per day)
        """
        training_data = []

        # Get historical campaign performance
        perf_data = self._get_historical_performance(account_id, customer_id, start_date, end_date)

        # Get capacity utilization if available
        capacity_data = self._get_capacity_data(account_id, start_date, end_date)

        # Get weather data if requested
        weather_data = {}
        if include_weather:
            weather_data = self._get_weather_data_safe(start_date, end_date)

        # Generate features for each day
        current_date = start_date
        while current_date <= end_date:
            features = self._generate_features(
                current_date,
                perf_data.get(current_date, {}),
                capacity_data.get(current_date, {}),
                weather_data.get(current_date, {}),
                industry,
                perf_data
            )

            training_data.append(features)
            current_date += timedelta(days=1)

        return training_data

    def _generate_features(
        self,
        target_date: date,
        perf: Dict[str, Any],
        capacity: Dict[str, Any],
        weather: Dict[str, Any],
        industry: str,
        all_perf_data: Dict[date, Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Generate all features for a single day."""

        features = {}

        # Target variable
        features['date'] = target_date.isoformat()
        features['conversions'] = perf.get('conversions', 0)
        features['cpl'] = perf.get('cpl', 0)
        features['spend'] = perf.get('spend', 0)
        features['clicks'] = perf.get('clicks', 0)
        features['impressions'] = perf.get('impressions', 0)

        # Temporal features
        features['year'] = target_date.year
        features['month'] = target_date.month
        features['day_of_week'] = target_date.weekday()  # 0=Monday
        features['day_of_month'] = target_date.day
        features['week_of_month'] = (target_date.day - 1) // 7 + 1
        features['is_weekend'] = 1 if target_date.weekday() >= 5 else 0
        features['is_holiday'] = 1 if (target_date.month, target_date.day) in self.HOLIDAYS else 0

        # Seasonality features
        seasonality_curve = self.SEASONALITY_CURVES.get(industry, self.SEASONALITY_CURVES['hvac_heating'])
        features['demand_multiplier'] = seasonality_curve[target_date.month]

        # CPL multiplier (inverse of demand - high demand = lower CPL)
        features['cpl_multiplier'] = 2.0 - seasonality_curve[target_date.month]

        # Historical rolling averages (7-day)
        rolling_stats = self._calculate_rolling_stats(target_date, all_perf_data, window=7)
        features['conversions_7d_avg'] = rolling_stats['conversions_avg']
        features['cpl_7d_avg'] = rolling_stats['cpl_avg']
        features['spend_7d_avg'] = rolling_stats['spend_avg']
        features['roas_7d_avg'] = rolling_stats['roas_avg']

        # Historical rolling averages (30-day)
        rolling_stats_30 = self._calculate_rolling_stats(target_date, all_perf_data, window=30)
        features['conversions_30d_avg'] = rolling_stats_30['conversions_avg']
        features['cpl_30d_avg'] = rolling_stats_30['cpl_avg']

        # Weather features
        features['temp_high'] = weather.get('temp_high', 75)
        features['temp_low'] = weather.get('temp_low', 55)
        features['temp_avg'] = (features['temp_high'] + features['temp_low']) / 2
        features['temp_range'] = features['temp_high'] - features['temp_low']
        features['is_extreme_heat'] = 1 if features['temp_high'] >= 90 else 0
        features['is_extreme_cold'] = 1 if features['temp_low'] <= 32 else 0
        features['is_extreme_weather'] = features['is_extreme_heat'] or features['is_extreme_cold']

        # Capacity features
        features['capacity_utilization'] = capacity.get('utilization_pct', 50.0)
        features['is_near_capacity'] = 1 if features['capacity_utilization'] >= 80 else 0

        # Campaign quality metrics
        features['avg_quality_score'] = perf.get('avg_quality_score', 7.0)
        features['impression_share'] = perf.get('impression_share', 50.0)
        features['avg_position'] = perf.get('avg_position', 2.5)

        # Derived features
        features['ctr'] = (features['clicks'] / features['impressions'] * 100) if features['impressions'] > 0 else 0
        features['conversion_rate'] = (features['conversions'] / features['clicks'] * 100) if features['clicks'] > 0 else 0

        return features

    def _calculate_rolling_stats(
        self,
        target_date: date,
        all_perf_data: Dict[date, Dict[str, Any]],
        window: int
    ) -> Dict[str, float]:
        """Calculate rolling averages for the window before target_date."""

        conversions_sum = 0
        cpl_sum = 0
        spend_sum = 0
        revenue_sum = 0
        count = 0

        for i in range(1, window + 1):
            past_date = target_date - timedelta(days=i)
            if past_date in all_perf_data:
                perf = all_perf_data[past_date]
                conversions_sum += perf.get('conversions', 0)
                cpl_sum += perf.get('cpl', 0)
                spend_sum += perf.get('spend', 0)
                revenue_sum += perf.get('revenue', 0)
                count += 1

        return {
            'conversions_avg': conversions_sum / count if count > 0 else 0,
            'cpl_avg': cpl_sum / count if count > 0 else 0,
            'spend_avg': spend_sum / count if count > 0 else 0,
            'roas_avg': (revenue_sum / spend_sum) if spend_sum > 0 else 0
        }

    def _get_historical_performance(
        self,
        account_id: int,
        customer_id: str,
        start_date: date,
        end_date: date
    ) -> Dict[date, Dict[str, Any]]:
        """
        Get historical performance data from database.

        Returns dict keyed by date.
        """
        # This would query your existing performance_metrics or similar table
        # For now, return mock structure
        cursor = self.db.cursor(dictionary=True)

        # Example query - adjust to your schema
        try:
            cursor.execute("""
                SELECT
                    metric_date,
                    SUM(conversions) as conversions,
                    AVG(cost_per_conversion) as cpl,
                    SUM(cost) as spend,
                    SUM(clicks) as clicks,
                    SUM(impressions) as impressions,
                    AVG(quality_score) as avg_quality_score,
                    AVG(search_impression_share) as impression_share,
                    AVG(average_position) as avg_position,
                    SUM(conversion_value) as revenue
                FROM performance_metrics
                WHERE account_id = %s
                AND customer_id = %s
                AND metric_date BETWEEN %s AND %s
                GROUP BY metric_date
            """, (account_id, customer_id, start_date, end_date))

            rows = cursor.fetchall()
            cursor.close()

            # Convert to dict keyed by date
            perf_by_date = {}
            for row in rows:
                metric_date = row['metric_date']
                if isinstance(metric_date, str):
                    metric_date = datetime.strptime(metric_date, '%Y-%m-%d').date()

                perf_by_date[metric_date] = {
                    'conversions': float(row.get('conversions', 0) or 0),
                    'cpl': float(row.get('cpl', 0) or 0),
                    'spend': float(row.get('spend', 0) or 0),
                    'clicks': int(row.get('clicks', 0) or 0),
                    'impressions': int(row.get('impressions', 0) or 0),
                    'avg_quality_score': float(row.get('avg_quality_score', 7) or 7),
                    'impression_share': float(row.get('impression_share', 50) or 50),
                    'avg_position': float(row.get('avg_position', 2.5) or 2.5),
                    'revenue': float(row.get('revenue', 0) or 0)
                }

            return perf_by_date

        except Exception as e:
            logger.warning(f"Could not fetch performance data: {e}")
            cursor.close()
            return {}

    def _get_capacity_data(
        self,
        account_id: int,
        start_date: date,
        end_date: date
    ) -> Dict[date, Dict[str, Any]]:
        """Get capacity utilization data."""
        cursor = self.db.cursor(dictionary=True)

        try:
            cursor.execute("""
                SELECT tracking_date, utilization_pct
                FROM capacity_tracking
                WHERE account_id = %s
                AND tracking_date BETWEEN %s AND %s
            """, (account_id, start_date, end_date))

            rows = cursor.fetchall()
            cursor.close()

            capacity_by_date = {}
            for row in rows:
                tracking_date = row['tracking_date']
                if isinstance(tracking_date, str):
                    tracking_date = datetime.strptime(tracking_date, '%Y-%m-%d').date()

                capacity_by_date[tracking_date] = {
                    'utilization_pct': float(row.get('utilization_pct', 50) or 50)
                }

            return capacity_by_date

        except Exception as e:
            logger.warning(f"Could not fetch capacity data: {e}")
            cursor.close()
            return {}

    def _get_weather_data_safe(
        self,
        start_date: date,
        end_date: date
    ) -> Dict[date, Dict[str, Any]]:
        """
        Get weather data with graceful fallback.

        Returns dict keyed by date.
        """
        try:
            # Try to fetch from weather API (implementation depends on your weather service)
            return self._fetch_weather_from_api(start_date, end_date)
        except Exception as e:
            logger.warning(f"Weather API unavailable, using defaults: {e}")
            # Return mock data as fallback
            return self._generate_default_weather(start_date, end_date)

    def _fetch_weather_from_api(
        self,
        start_date: date,
        end_date: date
    ) -> Dict[date, Dict[str, Any]]:
        """Fetch historical weather from Open-Meteo (free, no API key required)."""
        import requests as _req
        import os as _os

        # Latitude/longitude from env; defaults to mid-US if not configured
        lat = float(_os.getenv("WEATHER_LAT", "39.8283"))
        lon = float(_os.getenv("WEATHER_LON", "-98.5795"))

        resp = _req.get(
            "https://archive-api.open-meteo.com/v1/archive",
            params={
                "latitude": lat,
                "longitude": lon,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "daily": "temperature_2m_max,temperature_2m_min,weathercode",
                "temperature_unit": "fahrenheit",
                "timezone": "America/New_York",
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json().get("daily") or {}
        dates = data.get("time") or []
        max_temps = data.get("temperature_2m_max") or []
        min_temps = data.get("temperature_2m_min") or []
        codes = data.get("weathercode") or []

        result: Dict[date, Dict[str, Any]] = {}
        for i, d_str in enumerate(dates):
            d = date.fromisoformat(d_str)
            code = codes[i] if i < len(codes) else 0
            # WMO codes: 0=clear, 1-3=partly cloudy, 51-67=rain, 71-77=snow, 80-99=thunderstorm
            if code >= 80:
                condition = "stormy"
            elif code >= 51:
                condition = "rainy"
            elif code >= 71:
                condition = "snowy"
            elif code >= 1:
                condition = "cloudy"
            else:
                condition = "clear"
            result[d] = {
                "temp_high": max_temps[i] if i < len(max_temps) else 70,
                "temp_low": min_temps[i] if i < len(min_temps) else 50,
                "condition": condition,
            }
        return result

    def _generate_default_weather(
        self,
        start_date: date,
        end_date: date
    ) -> Dict[date, Dict[str, Any]]:
        """Generate seasonal default weather patterns."""
        weather_by_date = {}

        current_date = start_date
        while current_date <= end_date:
            month = current_date.month

            # Seasonal temperature patterns (for northern US)
            if month in [12, 1, 2]:  # Winter
                temp_high, temp_low = 35, 20
            elif month in [3, 4, 5]:  # Spring
                temp_high, temp_low = 65, 45
            elif month in [6, 7, 8]:  # Summer
                temp_high, temp_low = 85, 65
            else:  # Fall
                temp_high, temp_low = 60, 40

            weather_by_date[current_date] = {
                'temp_high': temp_high,
                'temp_low': temp_low
            }

            current_date += timedelta(days=1)

        return weather_by_date

    def export_to_csv(
        self,
        training_data: List[Dict[str, Any]],
        filepath: Optional[str] = None
    ) -> str:
        """
        Export training data to CSV format.

        Args:
            training_data: List of feature dicts
            filepath: Optional file path to save (if None, returns string)

        Returns:
            CSV string or filepath
        """
        if not training_data:
            return ""

        # Get all column names
        columns = list(training_data[0].keys())

        # Create CSV
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=columns)
        writer.writeheader()
        writer.writerows(training_data)

        csv_content = output.getvalue()
        output.close()

        if filepath:
            from pathlib import Path
            resolved = Path(filepath).resolve()
            allowed_dir = Path('/tmp').resolve()
            if not str(resolved).startswith(str(allowed_dir)):
                raise ValueError(f"Export path outside allowed directory: {filepath}")
            with open(resolved, 'w') as f:
                f.write(csv_content)
            return str(resolved)

        return csv_content

    def save_model_metadata(
        self,
        account_id: int,
        model_name: str,
        model_version: str,
        model_type: str,
        training_samples: int,
        features_used: List[str],
        hyperparameters: Dict[str, Any],
        accuracy_metrics: Dict[str, float]
    ) -> Optional[int]:
        """
        Save ML model metadata.

        Args:
            account_id: Account ID
            model_name: Model name (demand_forecaster, cpl_predictor, etc)
            model_version: Version string
            model_type: Type (random_forest, xgboost, etc)
            training_samples: Number of training samples
            features_used: List of feature names
            hyperparameters: Model hyperparameters
            accuracy_metrics: Dict of accuracy scores (mae, rmse, r2, etc)

        Returns:
            Model ID if successful
        """
        cursor = self.db.cursor()

        try:
            import json

            cursor.execute("""
                INSERT INTO ml_models (
                    account_id, model_name, model_version, model_type,
                    training_date, training_samples, features_used,
                    hyperparameters, accuracy_score, mae, rmse, r2_score
                ) VALUES (%s, %s, %s, %s, NOW(), %s, %s, %s, %s, %s, %s, %s)
            """, (
                account_id,
                model_name,
                model_version,
                model_type,
                training_samples,
                json.dumps(features_used),
                json.dumps(hyperparameters),
                accuracy_metrics.get('accuracy'),
                accuracy_metrics.get('mae'),
                accuracy_metrics.get('rmse'),
                accuracy_metrics.get('r2')
            ))

            model_id = cursor.lastrowid
            self.db.commit()
            cursor.close()
            return model_id

        except Exception as e:
            logger.error(f"Error saving model metadata: {e}")
            self.db.rollback()
            cursor.close()
            return None

    def log_prediction(
        self,
        ml_model_id: int,
        account_id: int,
        prediction_date: date,
        prediction_type: str,
        predicted_value: float,
        confidence_score: Optional[float] = None,
        campaign_id: Optional[str] = None,
        features_snapshot: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Log a model prediction.

        Args:
            ml_model_id: Model ID that made prediction
            account_id: Account ID
            prediction_date: Date being predicted
            prediction_type: Type (demand, cpl, conversions, roas)
            predicted_value: Predicted value
            confidence_score: Optional confidence (0-1)
            campaign_id: Optional campaign ID
            features_snapshot: Optional feature values used

        Returns:
            True if successful
        """
        cursor = self.db.cursor()

        try:
            import json

            cursor.execute("""
                INSERT INTO ml_predictions (
                    ml_model_id, account_id, prediction_date, prediction_type,
                    predicted_value, confidence_score, campaign_id, features_snapshot
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                ml_model_id, account_id, prediction_date, prediction_type,
                predicted_value, confidence_score, campaign_id,
                json.dumps(features_snapshot) if features_snapshot else None
            ))

            self.db.commit()
            cursor.close()
            return True

        except Exception as e:
            logger.error(f"Error logging prediction: {e}")
            self.db.rollback()
            cursor.close()
            return False
