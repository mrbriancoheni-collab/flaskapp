# app/services/ml_training_service.py
"""
ML Training Service for Demand Prediction

Prepares data and trains models for:
1. Demand forecasting (lead volume prediction)
2. CPL prediction
3. Conversion rate prediction
4. Budget optimization

Infrastructure-ready for sklearn, TensorFlow, or PyTorch models.
"""

from typing import Dict, List, Any, Tuple, Optional
from datetime import datetime, date, timedelta
from sqlalchemy import text
from app import db
import json


def prepare_training_data(
    account_id: int,
    campaign_id: Optional[int] = None,
    lookback_days: int = 365,
    service_type: str = 'hvac_ac'
) -> Dict[str, Any]:
    """
    Prepare training data for ML models.

    Features included:
    - Historical performance (CPL, conversion rate, ROAS)
    - Seasonality (month, week, day of week)
    - Weather data (temperature, conditions)
    - Capacity utilization
    - Competitive metrics (if available)

    Args:
        account_id: Account ID
        campaign_id: Optional campaign ID (None = all campaigns)
        lookback_days: Days of history to include
        service_type: Service type for seasonality

    Returns:
        Training data with features and targets
    """
    end_date = date.today()
    start_date = end_date - timedelta(days=lookback_days)

    # Query comprehensive training data
    query = text("""
        SELECT
            cph.date,
            cph.campaign_id,
            cph.campaign_name,
            cph.day_of_week,
            cph.week_of_month,
            cph.month,
            cph.year,
            cph.impressions,
            cph.clicks,
            cph.conversions,
            cph.cost_cents,
            cph.revenue_cents,
            cph.ctr,
            cph.cpl_cents,
            cph.conversion_rate,
            cph.roas,
            cph.avg_quality_score,
            cph.avg_position,
            cph.impression_share,
            cph.weather_temp_high,
            cph.weather_temp_low,
            cph.weather_condition,
            cph.was_holiday,
            ct.capacity_utilization,
            ct.booked_slots,
            ct.total_appointment_slots
        FROM campaign_performance_history cph
        LEFT JOIN capacity_tracking ct ON
            ct.account_id = cph.account_id
            AND ct.date = cph.date
            AND ct.service_type = :service_type
        WHERE cph.account_id = :account_id
          AND cph.date BETWEEN :start_date AND :end_date
          AND (:campaign_id IS NULL OR cph.campaign_id = :campaign_id)
        ORDER BY cph.date ASC
    """)

    with db.engine.connect() as conn:
        result = conn.execute(query, {
            "account_id": account_id,
            "campaign_id": campaign_id,
            "start_date": start_date,
            "end_date": end_date,
            "service_type": service_type
        })

        raw_data = [dict(row._mapping) for row in result]

    if not raw_data:
        return {
            "success": False,
            "error": "No training data available"
        }

    # Get seasonality curves
    seasonality_query = text("""
        SELECT month, demand_multiplier, cpl_multiplier, conversion_rate_multiplier
        FROM service_seasonality_curves
        WHERE service_type = :service_type
    """)

    with db.engine.connect() as conn:
        result = conn.execute(seasonality_query, {"service_type": service_type})
        seasonality_data = {row.month: dict(row._mapping) for row in result}

    # Feature engineering
    training_data = []

    for i, row in enumerate(raw_data):
        # Skip first 7 days (need lagging features)
        if i < 7:
            continue

        # Get lagging features (7-day rolling averages)
        lag_window = raw_data[max(0, i-7):i]

        avg_conversions_7d = sum(r['conversions'] for r in lag_window) / len(lag_window) if lag_window else 0
        avg_cpl_7d = sum(r['cpl_cents'] for r in lag_window) / len(lag_window) if lag_window else 0
        avg_roas_7d = sum(r['roas'] for r in lag_window) / len(lag_window) if lag_window else 0

        # Seasonality features
        month_seasonality = seasonality_data.get(row['month'], {})
        demand_multiplier = month_seasonality.get('demand_multiplier', 1.0)
        cpl_multiplier = month_seasonality.get('cpl_multiplier', 1.0)

        # Weather features
        temp_high = row['weather_temp_high'] if row['weather_temp_high'] else 70
        temp_low = row['weather_temp_low'] if row['weather_temp_low'] else 50
        is_extreme_weather = temp_high > 95 or temp_low < 32

        # Capacity features
        capacity_util = row['capacity_utilization'] if row['capacity_utilization'] else 0.5

        # Create feature vector
        features = {
            # Temporal features
            'month': row['month'],
            'day_of_week': row['day_of_week'],
            'week_of_month': row['week_of_month'],
            'is_holiday': int(row['was_holiday']),

            # Historical performance (lagging features)
            'avg_conversions_7d': avg_conversions_7d,
            'avg_cpl_7d': avg_cpl_7d / 100,  # Convert to dollars
            'avg_roas_7d': avg_roas_7d,

            # Seasonality
            'demand_multiplier': demand_multiplier,
            'cpl_multiplier': cpl_multiplier,

            # Weather
            'temp_high': temp_high,
            'temp_low': temp_low,
            'temp_range': temp_high - temp_low,
            'is_extreme_weather': int(is_extreme_weather),

            # Capacity
            'capacity_utilization': capacity_util,

            # Quality metrics
            'avg_quality_score': row['avg_quality_score'] or 7.0,
            'impression_share': row['impression_share'] or 0.5
        }

        # Target variables
        targets = {
            'conversions': row['conversions'],
            'cpl': row['cpl_cents'] / 100,
            'conversion_rate': row['conversion_rate'],
            'roas': row['roas']
        }

        training_data.append({
            'date': row['date'].isoformat(),
            'features': features,
            'targets': targets
        })

    return {
        "success": True,
        "records": len(training_data),
        "date_range": {
            "start": training_data[0]['date'],
            "end": training_data[-1]['date']
        },
        "training_data": training_data,
        "feature_columns": list(training_data[0]['features'].keys()),
        "target_columns": list(training_data[0]['targets'].keys())
    }


def export_training_data_csv(
    account_id: int,
    output_path: str,
    campaign_id: Optional[int] = None,
    lookback_days: int = 365
) -> Dict[str, Any]:
    """
    Export training data to CSV for external ML tools.

    Args:
        account_id: Account ID
        output_path: Path to save CSV
        campaign_id: Optional campaign ID
        lookback_days: Days of history

    Returns:
        Export summary
    """
    data = prepare_training_data(account_id, campaign_id, lookback_days)

    if not data['success']:
        return data

    import csv

    try:
        with open(output_path, 'w', newline='') as csvfile:
            # Flatten features and targets into single row
            if data['training_data']:
                sample = data['training_data'][0]
                fieldnames = ['date'] + list(sample['features'].keys()) + list(sample['targets'].keys())

                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()

                for row in data['training_data']:
                    flat_row = {'date': row['date']}
                    flat_row.update(row['features'])
                    flat_row.update(row['targets'])
                    writer.writerow(flat_row)

        return {
            "success": True,
            "output_path": output_path,
            "records_exported": len(data['training_data'])
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


def train_demand_prediction_model(
    account_id: int,
    campaign_id: Optional[int] = None,
    model_type: str = 'random_forest'  # random_forest, gradient_boosting, neural_network
) -> Dict[str, Any]:
    """
    Train a demand prediction model (placeholder for actual ML implementation).

    This is infrastructure-ready. To implement:
    1. Install: pip install scikit-learn pandas numpy
    2. Use prepare_training_data() to get features
    3. Train model using sklearn, tensorflow, or pytorch
    4. Save model using joblib or pickle
    5. Store model path in database

    Args:
        account_id: Account ID
        campaign_id: Optional campaign ID
        model_type: Type of model to train

    Returns:
        Training results
    """
    # Get training data
    data = prepare_training_data(account_id, campaign_id, lookback_days=365)

    if not data['success']:
        return data

    # Extract features and targets
    training_data = data['training_data']

    # TODO: Implement actual model training
    # Example with sklearn (commented out until sklearn is installed):
    """
    import pandas as pd
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import mean_absolute_error, r2_score
    import joblib

    # Convert to pandas DataFrame
    features_list = [row['features'] for row in training_data]
    targets_list = [row['targets']['conversions'] for row in training_data]

    X = pd.DataFrame(features_list)
    y = pd.Series(targets_list)

    # Split train/test
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    # Train model
    if model_type == 'random_forest':
        model = RandomForestRegressor(n_estimators=100, random_state=42)
    # ... other model types

    model.fit(X_train, y_train)

    # Evaluate
    y_pred = model.predict(X_test)
    mae = mean_absolute_error(y_test, y_pred)
    r2 = r2_score(y_test, y_pred)

    # Save model
    model_path = f'/path/to/models/demand_model_{account_id}.joblib'
    joblib.dump(model, model_path)

    # Store model metadata in database
    store_model_metadata(account_id, model_path, model_type, mae, r2)
    """

    # Return placeholder results
    return {
        "success": True,
        "model_type": model_type,
        "training_records": len(training_data),
        "message": "Model training infrastructure ready. Install scikit-learn to enable ML training.",
        "next_steps": [
            "1. Install ML libraries: pip install scikit-learn pandas numpy",
            "2. Uncomment training code in ml_training_service.py",
            "3. Create models directory for storing trained models",
            "4. Run training on historical data",
            "5. Deploy model for predictions"
        ]
    }


def predict_demand(
    account_id: int,
    campaign_id: int,
    prediction_date: date,
    features: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Predict demand for a future date using trained model.

    Args:
        account_id: Account ID
        campaign_id: Campaign ID
        prediction_date: Date to predict
        features: Feature vector for prediction

    Returns:
        Prediction results
    """
    # TODO: Load trained model and make prediction
    # Example (commented out):
    """
    import joblib

    # Load model
    model_path = get_model_path(account_id, campaign_id)
    model = joblib.load(model_path)

    # Prepare features
    import pandas as pd
    X = pd.DataFrame([features])

    # Predict
    predicted_conversions = model.predict(X)[0]

    return {
        "success": True,
        "prediction_date": prediction_date.isoformat(),
        "predicted_conversions": round(predicted_conversions, 2),
        "confidence_interval": {
            "low": predicted_conversions * 0.8,
            "high": predicted_conversions * 1.2
        }
    }
    """

    return {
        "success": True,
        "message": "Prediction infrastructure ready. Train model first.",
        "prediction_date": prediction_date.isoformat()
    }


def store_model_metadata(
    account_id: int,
    model_path: str,
    model_type: str,
    mae: float,
    r2_score: float
) -> None:
    """Store ML model metadata in database."""
    query = text("""
        INSERT INTO ml_models
            (account_id, model_path, model_type, mae, r2_score,
             trained_at, is_active)
        VALUES
            (:account_id, :model_path, :model_type, :mae, :r2_score,
             NOW(), TRUE)
    """)

    with db.engine.begin() as conn:
        conn.execute(query, {
            "account_id": account_id,
            "model_path": model_path,
            "model_type": model_type,
            "mae": mae,
            "r2_score": r2_score
        })


def get_model_path(account_id: int, campaign_id: Optional[int] = None) -> Optional[str]:
    """Get path to trained model for account/campaign."""
    query = text("""
        SELECT model_path
        FROM ml_models
        WHERE account_id = :account_id
          AND is_active = TRUE
        ORDER BY trained_at DESC
        LIMIT 1
    """)

    with db.engine.connect() as conn:
        result = conn.execute(query, {"account_id": account_id}).first()

        return result.model_path if result else None


def get_feature_importance(account_id: int) -> Dict[str, Any]:
    """
    Get feature importance from trained model.

    Useful for understanding what drives demand.
    """
    # TODO: Load model and extract feature importance
    # Example (commented out):
    """
    import joblib

    model_path = get_model_path(account_id)
    model = joblib.load(model_path)

    feature_names = [...] # From training data
    importances = model.feature_importances_

    feature_importance = dict(zip(feature_names, importances))
    sorted_features = sorted(feature_importance.items(), key=lambda x: x[1], reverse=True)

    return {
        "success": True,
        "feature_importance": dict(sorted_features[:10])  # Top 10
    }
    """

    return {
        "success": True,
        "message": "Feature importance analysis ready after model training"
    }
