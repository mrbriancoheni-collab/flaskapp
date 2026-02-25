# app/ml/models.py
"""
ML model definitions for each agent.

Each model class wraps a scikit-learn or xgboost estimator with
agent-specific feature engineering and prediction logic.
Models are trained on historical account data and serialized to disk.
"""
import json
import logging
import os
import pickle
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# Directory to store serialized models
MODEL_DIR = os.path.join(os.path.dirname(__file__), 'trained_models')
os.makedirs(MODEL_DIR, exist_ok=True)


def _safe_float(val, default=0.0):
    """Convert value to float safely."""
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


class BaseMLModel:
    """Base class for all agent ML models."""

    model_name: str = 'base'
    model_type: str = 'gradient_boosting'
    target_metric: str = 'unknown'

    def __init__(self, account_id: int):
        self.account_id = account_id
        self.model = None
        self.feature_names: List[str] = []
        self.trained_at: Optional[datetime] = None
        self.metrics: Dict[str, float] = {}

    def _model_path(self) -> str:
        return os.path.join(
            MODEL_DIR,
            f'{self.model_name}_account_{self.account_id}.pkl'
        )

    def save(self):
        """Serialize trained model to disk."""
        data = {
            'model': self.model,
            'feature_names': self.feature_names,
            'trained_at': self.trained_at,
            'metrics': self.metrics,
            'account_id': self.account_id,
        }
        with open(self._model_path(), 'wb') as f:
            pickle.dump(data, f)
        logger.info(f"Saved {self.model_name} for account {self.account_id}")

    def load(self) -> bool:
        """Load serialized model from disk. Returns True if successful."""
        path = self._model_path()
        if not os.path.exists(path):
            return False
        try:
            with open(path, 'rb') as f:
                data = pickle.load(f)
            self.model = data['model']
            self.feature_names = data['feature_names']
            self.trained_at = data['trained_at']
            self.metrics = data.get('metrics', {})
            return True
        except Exception as e:
            logger.warning(f"Failed to load {self.model_name}: {e}")
            return False

    def is_trained(self) -> bool:
        return self.model is not None

    def _log_to_db(self):
        """Log model metadata to ml_models table."""
        from app import db
        from sqlalchemy import text

        try:
            db.session.execute(text("""
                INSERT INTO ml_models
                    (account_id, model_name, model_type, target_metric,
                     training_date, features_used, accuracy_score, mae, rmse,
                     r2_score, is_active, feature_count, training_samples)
                VALUES
                    (:account_id, :model_name, :model_type, :target_metric,
                     :training_date, :features_used, :accuracy, :mae, :rmse,
                     :r2, TRUE, :feature_count, :training_samples)
                ON DUPLICATE KEY UPDATE
                    training_date = VALUES(training_date),
                    features_used = VALUES(features_used),
                    accuracy_score = VALUES(accuracy_score),
                    mae = VALUES(mae),
                    rmse = VALUES(rmse),
                    r2_score = VALUES(r2_score),
                    feature_count = VALUES(feature_count),
                    training_samples = VALUES(training_samples)
            """), {
                'account_id': self.account_id,
                'model_name': self.model_name,
                'model_type': self.model_type,
                'target_metric': self.target_metric,
                'training_date': self.trained_at,
                'features_used': json.dumps(self.feature_names),
                'accuracy': self.metrics.get('accuracy'),
                'mae': self.metrics.get('mae'),
                'rmse': self.metrics.get('rmse'),
                'r2': self.metrics.get('r2'),
                'feature_count': len(self.feature_names),
                'training_samples': self.metrics.get('training_samples', 0),
            })
            db.session.commit()
        except Exception as e:
            logger.warning(f"Failed to log model to DB: {e}")
            db.session.rollback()


# ======================================================================
# Strategic Director: Budget ROI Predictor
# ======================================================================

class BudgetROIModel(BaseMLModel):
    """
    Predicts expected ROAS for campaigns at different budget levels.

    Training data: campaign_performance_history with budget changes.
    Features: spend level, day of week, month, historical performance.
    Target: ROAS or conversions per dollar.
    """
    model_name = 'budget_roi_predictor'
    model_type = 'gradient_boosting'
    target_metric = 'roas'

    FEATURE_NAMES = [
        'daily_spend', 'day_of_week', 'month', 'week_of_month',
        'avg_ctr_30d', 'avg_conv_rate_30d', 'avg_cpa_30d',
        'impression_share', 'lost_is_budget', 'quality_score',
        'spend_trend_7d', 'conv_trend_7d',
        'days_since_budget_change', 'budget_change_magnitude',
    ]

    def train(self, campaign_data: List[Dict], budget_history: List[Dict]):
        """Train on campaign performance + budget change data."""
        from sklearn.ensemble import GradientBoostingRegressor
        from sklearn.model_selection import train_test_split

        if len(campaign_data) < 30:
            logger.warning(f"Not enough data to train BudgetROI ({len(campaign_data)} rows)")
            return False

        X, y = self._prepare_features(campaign_data, budget_history)
        if len(X) < 20:
            return False

        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42
        )

        self.model = GradientBoostingRegressor(
            n_estimators=100, max_depth=4, learning_rate=0.1,
            min_samples_leaf=5, random_state=42
        )
        self.model.fit(X_train, y_train)
        self.feature_names = self.FEATURE_NAMES
        self.trained_at = datetime.utcnow()

        # Evaluate
        from sklearn.metrics import mean_absolute_error, r2_score
        y_pred = self.model.predict(X_test)
        self.metrics = {
            'mae': float(mean_absolute_error(y_test, y_pred)),
            'r2': float(r2_score(y_test, y_pred)),
            'training_samples': len(X_train),
        }

        self.save()
        self._log_to_db()
        logger.info(f"BudgetROI trained: MAE={self.metrics['mae']:.4f}, R2={self.metrics['r2']:.4f}")
        return True

    def predict_roas(self, features: Dict) -> Dict:
        """Predict ROAS for given feature set."""
        if not self.is_trained():
            if not self.load():
                return {'predicted_roas': None, 'confidence': 0}

        X = self._features_to_array(features)
        predicted = float(self.model.predict(X.reshape(1, -1))[0])

        # Estimate confidence from feature importances
        importances = self.model.feature_importances_
        confidence = min(0.95, 0.5 + self.metrics.get('r2', 0) * 0.5)

        return {
            'predicted_roas': round(predicted, 2),
            'confidence': round(confidence, 2),
            'top_factors': self._top_factors(importances),
        }

    def _prepare_features(self, data, budget_hist) -> Tuple[np.ndarray, np.ndarray]:
        """Convert raw data to feature matrix and target vector."""
        budget_dates = {}
        for bh in budget_hist:
            cid = bh.get('campaign_id')
            bd = bh.get('changed_at')
            if cid and bd:
                budget_dates.setdefault(cid, []).append(bd)

        X_list, y_list = [], []
        for row in data:
            roas = _safe_float(row.get('roas'))
            if roas <= 0:
                continue

            cost = _safe_float(row.get('cost_cents')) / 100
            if cost <= 0:
                continue

            cid = row.get('campaign_id')
            row_date = row.get('date')

            # Days since last budget change
            days_since_change = 999
            change_magnitude = 0
            if cid in budget_dates:
                for bd in sorted(budget_dates[cid], reverse=True):
                    if bd <= row_date:
                        days_since_change = (row_date - bd.date() if hasattr(bd, 'date') else (row_date - bd)).days
                        break

            features = [
                cost,                                         # daily_spend
                _safe_float(row.get('day_of_week')),         # day_of_week
                _safe_float(row.get('month')),               # month
                _safe_float(row.get('week_of_month')),       # week_of_month
                _safe_float(row.get('ctr')),                 # avg_ctr_30d
                _safe_float(row.get('conversion_rate')),     # avg_conv_rate_30d
                _safe_float(row.get('cpl_cents')) / 100,     # avg_cpa_30d
                _safe_float(row.get('impression_share')),    # impression_share
                0,                                            # lost_is_budget (not in this table)
                _safe_float(row.get('avg_quality_score')),   # quality_score
                0,                                            # spend_trend_7d (computed in predict)
                0,                                            # conv_trend_7d
                days_since_change,                            # days_since_budget_change
                change_magnitude,                             # budget_change_magnitude
            ]

            X_list.append(features)
            y_list.append(roas)

        return np.array(X_list), np.array(y_list)

    def _features_to_array(self, f: Dict) -> np.ndarray:
        """Convert feature dict to numpy array in correct order."""
        return np.array([_safe_float(f.get(name)) for name in self.FEATURE_NAMES])

    def _top_factors(self, importances: np.ndarray, top_n: int = 3) -> List[Dict]:
        """Get top contributing features."""
        indices = np.argsort(importances)[::-1][:top_n]
        return [
            {'feature': self.FEATURE_NAMES[i], 'importance': round(float(importances[i]), 3)}
            for i in indices
        ]


# ======================================================================
# Campaign Manager: Performance Anomaly Detector
# ======================================================================

class AnomalyDetectorModel(BaseMLModel):
    """
    Detects performance anomalies using statistical baselines
    learned from historical data.

    Uses Isolation Forest for unsupervised anomaly detection
    plus rolling statistics for trend detection.
    """
    model_name = 'anomaly_detector'
    model_type = 'isolation_forest'
    target_metric = 'anomaly_score'

    FEATURE_NAMES = [
        'impressions_zscore', 'clicks_zscore', 'cost_zscore',
        'conversions_zscore', 'ctr_zscore', 'cpa_zscore',
        'day_of_week', 'is_weekend',
    ]

    def train(self, campaign_data: List[Dict]):
        """Train anomaly detector on normal performance patterns."""
        from sklearn.ensemble import IsolationForest

        if len(campaign_data) < 30:
            logger.warning(f"Not enough data for anomaly detector ({len(campaign_data)} rows)")
            return False

        # Compute rolling statistics per campaign
        self._compute_baselines(campaign_data)

        X = self._prepare_features(campaign_data)
        if len(X) < 20:
            return False

        self.model = IsolationForest(
            n_estimators=100, contamination=0.05,
            max_samples='auto', random_state=42
        )
        self.model.fit(X)
        self.feature_names = self.FEATURE_NAMES
        self.trained_at = datetime.utcnow()
        self.metrics = {'training_samples': len(X)}

        self.save()
        self._log_to_db()
        logger.info(f"AnomalyDetector trained on {len(X)} samples")
        return True

    def detect(self, features: Dict) -> Dict:
        """Score a data point for anomalousness."""
        if not self.is_trained():
            if not self.load():
                return {'is_anomaly': False, 'score': 0, 'confidence': 0}

        X = self._features_to_array(features)
        score = float(self.model.decision_function(X.reshape(1, -1))[0])
        is_anomaly = score < 0

        return {
            'is_anomaly': is_anomaly,
            'score': round(score, 4),
            'severity': 'critical' if score < -0.3 else ('warning' if score < -0.1 else 'info'),
            'confidence': round(min(0.95, abs(score)), 2),
        }

    def _compute_baselines(self, data: List[Dict]):
        """Compute per-campaign rolling means/stdevs."""
        from collections import defaultdict
        stats = defaultdict(lambda: defaultdict(list))

        for row in data:
            cid = row.get('campaign_id', 0)
            stats[cid]['impressions'].append(_safe_float(row.get('impressions')))
            stats[cid]['clicks'].append(_safe_float(row.get('clicks')))
            stats[cid]['cost'].append(_safe_float(row.get('cost_cents', 0)) / 100)
            stats[cid]['conversions'].append(_safe_float(row.get('conversions')))

        self._baselines = {}
        for cid, metrics in stats.items():
            self._baselines[cid] = {}
            for metric, values in metrics.items():
                arr = np.array(values)
                self._baselines[cid][metric] = {
                    'mean': float(np.mean(arr)),
                    'std': float(np.std(arr)) if len(arr) > 1 else 1.0,
                }

    def _prepare_features(self, data: List[Dict]) -> np.ndarray:
        X = []
        for row in data:
            cid = row.get('campaign_id', 0)
            bl = self._baselines.get(cid, {})

            def zscore(metric, val):
                b = bl.get(metric, {'mean': 0, 'std': 1})
                std = b['std'] if b['std'] > 0 else 1
                return (val - b['mean']) / std

            cost = _safe_float(row.get('cost_cents', 0)) / 100
            clicks = _safe_float(row.get('clicks'))
            impressions = _safe_float(row.get('impressions'))
            conversions = _safe_float(row.get('conversions'))
            ctr = clicks / impressions if impressions > 0 else 0
            cpa = cost / conversions if conversions > 0 else 0
            dow = _safe_float(row.get('day_of_week'))

            X.append([
                zscore('impressions', impressions),
                zscore('clicks', clicks),
                zscore('cost', cost),
                zscore('conversions', conversions),
                zscore('impressions', ctr),  # approximate
                zscore('cost', cpa),
                dow,
                1 if dow in (6, 7) else 0,
            ])
        return np.array(X)

    def _features_to_array(self, f: Dict) -> np.ndarray:
        return np.array([_safe_float(f.get(name)) for name in self.FEATURE_NAMES])


# ======================================================================
# Budget Guardian: Spend Pacing Forecaster
# ======================================================================

class SpendForecastModel(BaseMLModel):
    """
    Forecasts daily spend and predicts budget exhaustion.

    Uses time-series features to predict tomorrow's spend.
    """
    model_name = 'spend_forecaster'
    model_type = 'gradient_boosting'
    target_metric = 'daily_spend'

    FEATURE_NAMES = [
        'spend_yesterday', 'spend_avg_7d', 'spend_avg_30d',
        'spend_trend_7d', 'day_of_week', 'day_of_month',
        'month', 'is_weekend', 'is_month_end',
        'daily_budget', 'budget_utilization_7d',
    ]

    def train(self, campaign_data: List[Dict]):
        from sklearn.ensemble import GradientBoostingRegressor
        from sklearn.model_selection import train_test_split

        if len(campaign_data) < 30:
            return False

        X, y = self._build_time_series_features(campaign_data)
        if len(X) < 20:
            return False

        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, shuffle=False  # time series: no shuffle
        )

        self.model = GradientBoostingRegressor(
            n_estimators=100, max_depth=3, learning_rate=0.1,
            random_state=42
        )
        self.model.fit(X_train, y_train)
        self.feature_names = self.FEATURE_NAMES
        self.trained_at = datetime.utcnow()

        from sklearn.metrics import mean_absolute_error, r2_score
        y_pred = self.model.predict(X_test)
        self.metrics = {
            'mae': float(mean_absolute_error(y_test, y_pred)),
            'r2': float(r2_score(y_test, y_pred)),
            'training_samples': len(X_train),
        }

        self.save()
        self._log_to_db()
        return True

    def predict_spend(self, features: Dict) -> Dict:
        if not self.is_trained():
            if not self.load():
                return {'predicted_spend': None, 'confidence': 0}

        X = np.array([[_safe_float(features.get(n)) for n in self.FEATURE_NAMES]])
        predicted = float(self.model.predict(X)[0])

        return {
            'predicted_daily_spend': round(max(0, predicted), 2),
            'confidence': round(min(0.95, 0.5 + self.metrics.get('r2', 0) * 0.5), 2),
        }

    def _build_time_series_features(self, data: List[Dict]) -> Tuple[np.ndarray, np.ndarray]:
        """Build lagged features from time series data."""
        # Group by campaign and sort by date
        from collections import defaultdict
        by_campaign = defaultdict(list)
        for row in data:
            by_campaign[row.get('campaign_id', 0)].append(row)

        X_list, y_list = [], []
        for cid, rows in by_campaign.items():
            rows.sort(key=lambda r: r.get('date'))
            costs = [_safe_float(r.get('cost_cents', 0)) / 100 for r in rows]

            for i in range(30, len(rows)):
                cost_today = costs[i]
                cost_yesterday = costs[i - 1]
                avg_7d = np.mean(costs[i - 7:i])
                avg_30d = np.mean(costs[i - 30:i])
                trend_7d = (avg_7d - np.mean(costs[i - 14:i - 7])) / max(np.mean(costs[i - 14:i - 7]), 0.01)

                row = rows[i]
                dow = _safe_float(row.get('day_of_week'))
                row_date = row.get('date')
                dom = row_date.day if hasattr(row_date, 'day') else 15
                month = row_date.month if hasattr(row_date, 'month') else 6

                X_list.append([
                    cost_yesterday, avg_7d, avg_30d, trend_7d,
                    dow, dom, month,
                    1 if dow in (6, 7) else 0,
                    1 if dom >= 28 else 0,
                    0,  # daily_budget (not available in this data)
                    cost_yesterday / avg_7d if avg_7d > 0 else 1,
                ])
                y_list.append(cost_today)

        return np.array(X_list), np.array(y_list)


# ======================================================================
# Quality Score: QS Component Predictor
# ======================================================================

class QualityScoreModel(BaseMLModel):
    """
    Predicts quality score changes based on keyword/ad features.

    Helps prioritize which keywords to optimize for QS improvement.
    """
    model_name = 'quality_score_predictor'
    model_type = 'gradient_boosting'
    target_metric = 'quality_score'

    FEATURE_NAMES = [
        'current_ctr', 'avg_ctr_30d', 'ctr_vs_benchmark',
        'impressions_30d', 'clicks_30d', 'ad_relevance_score',
        'landing_page_score', 'keyword_length', 'is_exact_match',
        'is_branded',
    ]

    def train(self, qs_data: List[Dict], keyword_data: List[Dict]):
        from sklearn.ensemble import GradientBoostingClassifier

        if len(qs_data) < 20:
            return False

        X, y = self._prepare_qs_features(qs_data, keyword_data)
        if len(X) < 15:
            return False

        from sklearn.model_selection import train_test_split
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

        self.model = GradientBoostingClassifier(
            n_estimators=50, max_depth=3, random_state=42
        )
        self.model.fit(X_train, y_train)
        self.feature_names = self.FEATURE_NAMES
        self.trained_at = datetime.utcnow()

        from sklearn.metrics import accuracy_score
        y_pred = self.model.predict(X_test)
        self.metrics = {
            'accuracy': float(accuracy_score(y_test, y_pred)),
            'training_samples': len(X_train),
        }

        self.save()
        self._log_to_db()
        return True

    def predict_qs(self, features: Dict) -> Dict:
        if not self.is_trained():
            if not self.load():
                return {'predicted_qs': None, 'confidence': 0}

        X = np.array([[_safe_float(features.get(n)) for n in self.FEATURE_NAMES]])
        predicted_class = int(self.model.predict(X)[0])
        probas = self.model.predict_proba(X)[0]
        confidence = float(max(probas))

        return {
            'predicted_qs': predicted_class,
            'confidence': round(confidence, 2),
            'improvement_potential': predicted_class > _safe_float(features.get('current_qs', 5)),
        }

    def _prepare_qs_features(self, qs_data, kw_data):
        kw_lookup = {kd.get('keyword_id'): kd for kd in kw_data}
        X, y = [], []

        for row in qs_data:
            actual_qs = row.get('actual_quality_score')
            if actual_qs is None:
                continue

            kw = kw_lookup.get(row.get('keyword_id'), {})
            keyword_text = row.get('keyword_text', '')

            X.append([
                _safe_float(row.get('actual_ctr')),
                _safe_float(kw.get('avg_ctr')),
                0,  # ctr_vs_benchmark
                _safe_float(kw.get('total_impressions')),
                _safe_float(kw.get('total_clicks')),
                {'ABOVE_AVERAGE': 3, 'AVERAGE': 2, 'BELOW_AVERAGE': 1}.get(
                    row.get('predicted_ad_relevance'), 2),
                {'ABOVE_AVERAGE': 3, 'AVERAGE': 2, 'BELOW_AVERAGE': 1}.get(
                    row.get('predicted_landing_page_exp'), 2),
                len(keyword_text.split()),
                1 if kw.get('match_type') == 'exact' else 0,
                0,  # is_branded
            ])
            y.append(int(actual_qs))

        return np.array(X), np.array(y)


# ======================================================================
# Keyword Optimizer: CPA Predictor
# ======================================================================

class CPAPredictorModel(BaseMLModel):
    """
    Predicts CPA at different bid levels for keywords.

    Helps optimize bids by predicting cost-per-acquisition.
    """
    model_name = 'cpa_predictor'
    model_type = 'gradient_boosting'
    target_metric = 'cpa'

    FEATURE_NAMES = [
        'current_cpc', 'avg_cpc_30d', 'current_ctr', 'avg_ctr_30d',
        'conversion_rate_30d', 'impressions_30d', 'impression_share',
        'quality_score', 'match_type_numeric', 'keyword_length',
        'competition_level', 'position_estimate',
    ]

    def train(self, keyword_data: List[Dict]):
        from sklearn.ensemble import GradientBoostingRegressor
        from sklearn.model_selection import train_test_split

        if len(keyword_data) < 30:
            return False

        X, y = self._prepare_features(keyword_data)
        if len(X) < 20:
            return False

        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42
        )

        self.model = GradientBoostingRegressor(
            n_estimators=100, max_depth=4, learning_rate=0.1, random_state=42
        )
        self.model.fit(X_train, y_train)
        self.feature_names = self.FEATURE_NAMES
        self.trained_at = datetime.utcnow()

        from sklearn.metrics import mean_absolute_error, r2_score
        y_pred = self.model.predict(X_test)
        self.metrics = {
            'mae': float(mean_absolute_error(y_test, y_pred)),
            'r2': float(r2_score(y_test, y_pred)),
            'training_samples': len(X_train),
        }

        self.save()
        self._log_to_db()
        return True

    def predict_cpa(self, features: Dict) -> Dict:
        if not self.is_trained():
            if not self.load():
                return {'predicted_cpa': None, 'confidence': 0}

        X = np.array([[_safe_float(features.get(n)) for n in self.FEATURE_NAMES]])
        predicted = float(self.model.predict(X)[0])

        return {
            'predicted_cpa': round(max(0, predicted), 2),
            'confidence': round(min(0.95, 0.5 + self.metrics.get('r2', 0) * 0.5), 2),
        }

    def _prepare_features(self, data: List[Dict]):
        X, y = [], []
        for row in data:
            cost = _safe_float(row.get('cost_micros', 0)) / 1_000_000
            conv = _safe_float(row.get('conversions'))
            if cost <= 0 or conv <= 0:
                continue

            cpa = cost / conv
            clicks = _safe_float(row.get('clicks'))
            impressions = _safe_float(row.get('impressions'))
            cpc = cost / clicks if clicks > 0 else 0
            ctr = clicks / impressions if impressions > 0 else 0
            match_map = {'EXACT': 3, 'PHRASE': 2, 'BROAD': 1}

            X.append([
                cpc, cpc, ctr, ctr,
                conv / clicks if clicks > 0 else 0,
                impressions,
                _safe_float(row.get('search_impr_share', 0.5)),
                _safe_float(row.get('quality_score', 5)),
                match_map.get(row.get('match_type', ''), 1),
                len(row.get('keyword_text', '').split()),
                0.5,  # competition_level
                3.0,  # position_estimate
            ])
            y.append(cpa)

        return np.array(X), np.array(y)


# ======================================================================
# Negative Keyword: Waste Classifier
# ======================================================================

class WasteClassifierModel(BaseMLModel):
    """
    Classifies search terms as wasteful or valuable.

    Binary classifier trained on historical search terms where
    high-spend + zero conversions = waste.
    """
    model_name = 'waste_classifier'
    model_type = 'gradient_boosting'
    target_metric = 'waste_probability'

    FEATURE_NAMES = [
        'cost', 'clicks', 'impressions', 'ctr',
        'word_count', 'avg_word_length',
        'contains_question', 'contains_location',
        'contains_diy', 'contains_free',
        'contains_job', 'keyword_match_ratio',
    ]

    def train(self, search_term_data: List[Dict]):
        from sklearn.ensemble import GradientBoostingClassifier
        from sklearn.model_selection import train_test_split

        if len(search_term_data) < 50:
            return False

        X, y = self._prepare_features(search_term_data)
        if len(X) < 30:
            return False

        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42
        )

        self.model = GradientBoostingClassifier(
            n_estimators=100, max_depth=4, random_state=42
        )
        self.model.fit(X_train, y_train)
        self.feature_names = self.FEATURE_NAMES
        self.trained_at = datetime.utcnow()

        from sklearn.metrics import accuracy_score, f1_score
        y_pred = self.model.predict(X_test)
        self.metrics = {
            'accuracy': float(accuracy_score(y_test, y_pred)),
            'f1': float(f1_score(y_test, y_pred, zero_division=0)),
            'training_samples': len(X_train),
        }

        self.save()
        self._log_to_db()
        return True

    def predict_waste(self, search_term: str, metrics: Dict) -> Dict:
        if not self.is_trained():
            if not self.load():
                return {'is_waste': False, 'probability': 0, 'confidence': 0}

        features = self._extract_text_features(search_term, metrics)
        X = np.array([[_safe_float(features.get(n)) for n in self.FEATURE_NAMES]])

        probability = float(self.model.predict_proba(X)[0][1])
        is_waste = probability > 0.6

        return {
            'is_waste': is_waste,
            'probability': round(probability, 3),
            'confidence': round(self.metrics.get('accuracy', 0.5), 2),
        }

    def _prepare_features(self, data: List[Dict]):
        X, y = [], []
        for row in data:
            term = row.get('search_term', '')
            cost = _safe_float(row.get('cost_micros', 0)) / 1_000_000
            conv = _safe_float(row.get('conversions', 0))
            clicks = max(_safe_float(row.get('clicks', 0)), 1)

            # Label: confirmed negatives are the strongest waste signal (feedback loop).
            # Fallback: statistically wasteful = meaningful spend (>$0.50) with
            # zero conversions and enough clicks to be reliable (>=3).
            # Using $0.50 + click gate avoids mislabelling brand-new or low-traffic terms.
            already_negated = bool(row.get('added_as_negative', False))
            is_statistically_wasteful = (cost > 0.50 and conv == 0 and clicks >= 3)
            is_waste = 1 if (already_negated or is_statistically_wasteful) else 0

            features = self._extract_text_features(term, row)
            X.append([_safe_float(features.get(n)) for n in self.FEATURE_NAMES])
            y.append(is_waste)

        return np.array(X), np.array(y)

    def _extract_text_features(self, term: str, metrics: Dict) -> Dict:
        """Extract text-based and performance features from search term."""
        words = term.lower().split()
        matched_kw = (metrics.get('matched_keyword') or '').lower()
        cost = _safe_float(metrics.get('cost_micros', 0)) / 1_000_000
        clicks = _safe_float(metrics.get('clicks'))
        impressions = _safe_float(metrics.get('impressions'))

        # Keyword match ratio: how similar is term to matched keyword
        if matched_kw and words:
            matched_words = set(matched_kw.split())
            match_ratio = len(set(words) & matched_words) / len(words)
        else:
            match_ratio = 0

        question_words = {'how', 'what', 'why', 'when', 'where', 'who', 'which', 'can', 'does', 'is'}
        diy_words = {'diy', 'yourself', 'tutorial', 'guide', 'instructions', 'steps'}
        free_words = {'free', 'cheap', 'cheapest', 'discount', 'coupon'}
        job_words = {'job', 'jobs', 'career', 'salary', 'hiring', 'apply', 'resume'}
        location_words = {'near', 'nearby', 'in', 'around'}

        return {
            'cost': cost,
            'clicks': clicks,
            'impressions': impressions,
            'ctr': clicks / impressions if impressions > 0 else 0,
            'word_count': len(words),
            'avg_word_length': np.mean([len(w) for w in words]) if words else 0,
            'contains_question': 1 if any(w in question_words for w in words) else 0,
            'contains_location': 1 if any(w in location_words for w in words) else 0,
            'contains_diy': 1 if any(w in diy_words for w in words) else 0,
            'contains_free': 1 if any(w in free_words for w in words) else 0,
            'contains_job': 1 if any(w in job_words for w in words) else 0,
            'keyword_match_ratio': match_ratio,
        }


# ======================================================================
# Ad Copy: CTR Predictor
# ======================================================================

class CTRPredictorModel(BaseMLModel):
    """
    Predicts expected CTR for ad variations.

    Features include text characteristics and historical performance.
    """
    model_name = 'ctr_predictor'
    model_type = 'gradient_boosting'
    target_metric = 'ctr'

    FEATURE_NAMES = [
        'headline_char_count', 'description_char_count',
        'headline_word_count', 'has_cta', 'has_number',
        'has_price', 'has_question',
        'impressions', 'position_estimate',
        'day_of_week',
    ]

    def train(self, ad_data: List[Dict]):
        from sklearn.ensemble import GradientBoostingRegressor
        from sklearn.model_selection import train_test_split

        if len(ad_data) < 30:
            return False

        X, y = self._prepare_features(ad_data)
        if len(X) < 20:
            return False

        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

        self.model = GradientBoostingRegressor(
            n_estimators=50, max_depth=3, random_state=42
        )
        self.model.fit(X_train, y_train)
        self.feature_names = self.FEATURE_NAMES
        self.trained_at = datetime.utcnow()

        from sklearn.metrics import mean_absolute_error, r2_score
        y_pred = self.model.predict(X_test)
        self.metrics = {
            'mae': float(mean_absolute_error(y_test, y_pred)),
            'r2': float(r2_score(y_test, y_pred)),
            'training_samples': len(X_train),
        }

        self.save()
        self._log_to_db()
        return True

    def predict_ctr(self, ad_text: Dict, context: Dict) -> Dict:
        if not self.is_trained():
            if not self.load():
                return {'predicted_ctr': None, 'confidence': 0}

        features = self._extract_ad_features(ad_text, context)
        X = np.array([[_safe_float(features.get(n)) for n in self.FEATURE_NAMES]])
        predicted = float(self.model.predict(X)[0])

        return {
            'predicted_ctr': round(max(0, min(1, predicted)), 4),
            'confidence': round(min(0.95, 0.5 + self.metrics.get('r2', 0) * 0.5), 2),
        }

    def _prepare_features(self, data: List[Dict]):
        X, y = [], []
        for row in data:
            impressions = _safe_float(row.get('impressions'))
            clicks = _safe_float(row.get('clicks'))
            if impressions < 100:
                continue

            ctr = clicks / impressions
            h1 = row.get('headline1') or ''
            h2 = row.get('headline2') or ''
            d1 = row.get('description1') or ''

            features = self._extract_ad_features(
                {'headline': f'{h1} | {h2}', 'description': d1},
                {'impressions': impressions}
            )
            X.append([_safe_float(features.get(n)) for n in self.FEATURE_NAMES])
            y.append(ctr)

        return np.array(X), np.array(y)

    def _extract_ad_features(self, ad_text: Dict, context: Dict) -> Dict:
        headline = ad_text.get('headline', '')
        description = ad_text.get('description', '')
        combined = f"{headline} {description}".lower()

        cta_words = {'call', 'get', 'book', 'schedule', 'free', 'buy', 'order', 'save', 'start', 'try'}
        has_number = any(c.isdigit() for c in combined)
        has_price = '$' in combined or 'price' in combined
        has_question = '?' in combined

        return {
            'headline_char_count': len(headline),
            'description_char_count': len(description),
            'headline_word_count': len(headline.split()),
            'has_cta': 1 if any(w in combined for w in cta_words) else 0,
            'has_number': 1 if has_number else 0,
            'has_price': 1 if has_price else 0,
            'has_question': 1 if has_question else 0,
            'impressions': _safe_float(context.get('impressions')),
            'position_estimate': _safe_float(context.get('position', 3)),
            'day_of_week': _safe_float(context.get('day_of_week', 3)),
        }
