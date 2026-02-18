# app/ml/predictor.py
"""
Prediction service - runtime interface used by agents.

Loads trained models and provides predictions for each agent type.
Falls back gracefully when models aren't trained yet.
"""
import logging
from typing import Dict, Optional, Any

from app.ml.models import (
    BudgetROIModel,
    AnomalyDetectorModel,
    SpendForecastModel,
    QualityScoreModel,
    CPAPredictorModel,
    WasteClassifierModel,
    CTRPredictorModel,
)

logger = logging.getLogger(__name__)


class MLPredictor:
    """
    Unified prediction interface for all agent ML models.

    Agents call this service to get ML-powered predictions that
    supplement their rule-based logic. When a model isn't available,
    returns empty predictions so agents can still function.
    """

    def __init__(self, account_id: int):
        self.account_id = account_id
        self._models = {}

    def _get_model(self, model_class):
        """Lazy-load a model instance."""
        name = model_class.model_name
        if name not in self._models:
            model = model_class(self.account_id)
            model.load()
            self._models[name] = model
        return self._models[name]

    # ------------------------------------------------------------------
    # Strategic Director
    # ------------------------------------------------------------------

    def predict_campaign_roas(self, campaign_features: Dict) -> Dict:
        """Predict ROAS for a campaign at current or proposed budget level."""
        model = self._get_model(BudgetROIModel)
        if not model.is_trained():
            return {'predicted_roas': None, 'confidence': 0, 'source': 'no_model'}
        result = model.predict_roas(campaign_features)
        result['source'] = 'ml_model'
        result['model_trained_at'] = str(model.trained_at) if model.trained_at else None
        return result

    def get_budget_allocation_insights(self, campaigns: list) -> Dict:
        """Get ML-guided budget allocation across campaigns."""
        model = self._get_model(BudgetROIModel)
        if not model.is_trained():
            return {'insights': [], 'confidence': 0, 'source': 'no_model'}

        predictions = []
        for campaign in campaigns:
            pred = model.predict_roas(campaign)
            predictions.append({
                'campaign_id': campaign.get('id'),
                'campaign_name': campaign.get('name'),
                'current_spend': campaign.get('monthly_spend', 0),
                'predicted_roas': pred.get('predicted_roas'),
                'confidence': pred.get('confidence', 0),
            })

        # Sort by predicted ROAS descending
        predictions.sort(key=lambda x: x.get('predicted_roas') or 0, reverse=True)

        return {
            'insights': predictions,
            'recommendation': self._budget_recommendation(predictions),
            'confidence': sum(p.get('confidence', 0) for p in predictions) / max(len(predictions), 1),
            'source': 'ml_model',
        }

    def _budget_recommendation(self, predictions: list) -> str:
        """Generate budget allocation recommendation from predictions."""
        if not predictions:
            return "Insufficient data for budget recommendations."

        top = [p for p in predictions if (p.get('predicted_roas') or 0) > 2.0]
        bottom = [p for p in predictions if (p.get('predicted_roas') or 0) < 1.0]

        parts = []
        if top:
            names = ', '.join(p.get('campaign_name', '?') for p in top[:3])
            parts.append(f"Increase budget for high-ROAS campaigns: {names}")
        if bottom:
            names = ', '.join(p.get('campaign_name', '?') for p in bottom[:3])
            parts.append(f"Consider reducing budget for low-ROAS campaigns: {names}")

        return '. '.join(parts) if parts else "Budget allocation looks balanced."

    # ------------------------------------------------------------------
    # Campaign Manager
    # ------------------------------------------------------------------

    def detect_anomaly(self, campaign_features: Dict) -> Dict:
        """Check if current performance is anomalous."""
        model = self._get_model(AnomalyDetectorModel)
        if not model.is_trained():
            return {'is_anomaly': False, 'score': 0, 'confidence': 0, 'source': 'no_model'}
        result = model.detect(campaign_features)
        result['source'] = 'ml_model'
        return result

    def get_performance_trend(self, campaign_features: Dict) -> Dict:
        """Analyze performance trends with ML context."""
        cost_trend = campaign_features.get('cost_trend', 0)
        conv_trend = campaign_features.get('conv_trend', 0)

        # Determine trend direction and concern level
        if conv_trend < -0.2 and cost_trend > 0.1:
            concern = 'high'
            direction = 'degrading'
            description = 'Conversions declining while costs increasing'
        elif conv_trend < -0.1:
            concern = 'medium'
            direction = 'declining'
            description = 'Conversions trending down'
        elif conv_trend > 0.2 and cost_trend < 0:
            concern = 'none'
            direction = 'improving'
            description = 'Conversions increasing while costs decreasing'
        else:
            concern = 'low'
            direction = 'stable'
            description = 'Performance within normal range'

        return {
            'direction': direction,
            'concern_level': concern,
            'description': description,
            'cost_trend_pct': round(cost_trend * 100, 1),
            'conv_trend_pct': round(conv_trend * 100, 1),
            'source': 'statistical',
        }

    # ------------------------------------------------------------------
    # Budget Guardian
    # ------------------------------------------------------------------

    def predict_daily_spend(self, features: Dict) -> Dict:
        """Predict tomorrow's spend for budget planning."""
        model = self._get_model(SpendForecastModel)
        if not model.is_trained():
            return {'predicted_daily_spend': None, 'confidence': 0, 'source': 'no_model'}
        result = model.predict_spend(features)
        result['source'] = 'ml_model'
        return result

    def predict_budget_exhaustion(self, daily_budget: float, features: Dict) -> Dict:
        """Predict when budget will be exhausted in current month."""
        spend_pred = self.predict_daily_spend(features)
        predicted_daily = spend_pred.get('predicted_daily_spend')

        if predicted_daily is None or predicted_daily <= 0:
            return {'days_until_exhaustion': None, 'confidence': 0, 'source': 'no_model'}

        from datetime import date
        today = date.today()
        days_left_in_month = (date(today.year, today.month + 1 if today.month < 12 else 1,
                                    1 if today.month < 12 else 1) - today).days
        remaining_budget = daily_budget * days_left_in_month
        days_until_exhaustion = remaining_budget / predicted_daily if predicted_daily > 0 else 999

        return {
            'predicted_daily_spend': predicted_daily,
            'days_until_exhaustion': round(days_until_exhaustion, 1),
            'on_track': days_until_exhaustion >= days_left_in_month * 0.9,
            'confidence': spend_pred.get('confidence', 0),
            'source': 'ml_model',
        }

    # ------------------------------------------------------------------
    # Quality Score
    # ------------------------------------------------------------------

    def predict_quality_score(self, keyword_features: Dict) -> Dict:
        """Predict quality score for a keyword."""
        model = self._get_model(QualityScoreModel)
        if not model.is_trained():
            return {'predicted_qs': None, 'confidence': 0, 'source': 'no_model'}
        result = model.predict_qs(keyword_features)
        result['source'] = 'ml_model'
        return result

    # ------------------------------------------------------------------
    # Keyword Optimizer
    # ------------------------------------------------------------------

    def predict_keyword_cpa(self, keyword_features: Dict) -> Dict:
        """Predict CPA for a keyword at current bid level."""
        model = self._get_model(CPAPredictorModel)
        if not model.is_trained():
            return {'predicted_cpa': None, 'confidence': 0, 'source': 'no_model'}
        result = model.predict_cpa(keyword_features)
        result['source'] = 'ml_model'
        return result

    def get_bid_recommendation(self, keyword_features: Dict, target_cpa: float) -> Dict:
        """Recommend optimal bid to achieve target CPA."""
        current_cpa_pred = self.predict_keyword_cpa(keyword_features)
        predicted_cpa = current_cpa_pred.get('predicted_cpa')

        if predicted_cpa is None:
            return {'recommended_bid': None, 'confidence': 0, 'source': 'no_model'}

        current_cpc = keyword_features.get('current_cpc', 0)
        if predicted_cpa > 0 and current_cpc > 0:
            # Simple proportional bid adjustment
            adjustment_ratio = target_cpa / predicted_cpa
            recommended_bid = current_cpc * min(max(adjustment_ratio, 0.5), 2.0)
        else:
            recommended_bid = current_cpc

        return {
            'recommended_bid': round(recommended_bid, 2),
            'current_cpc': round(current_cpc, 2),
            'predicted_cpa_at_current': round(predicted_cpa, 2),
            'target_cpa': target_cpa,
            'bid_change_pct': round((recommended_bid / current_cpc - 1) * 100, 1) if current_cpc > 0 else 0,
            'confidence': current_cpa_pred.get('confidence', 0),
            'source': 'ml_model',
        }

    # ------------------------------------------------------------------
    # Negative Keyword
    # ------------------------------------------------------------------

    def classify_search_term(self, search_term: str, metrics: Dict) -> Dict:
        """Classify whether a search term is wasteful."""
        model = self._get_model(WasteClassifierModel)
        if not model.is_trained():
            return {'is_waste': False, 'probability': 0, 'confidence': 0, 'source': 'no_model'}
        result = model.predict_waste(search_term, metrics)
        result['source'] = 'ml_model'
        return result

    # ------------------------------------------------------------------
    # Ad Copy
    # ------------------------------------------------------------------

    def predict_ad_ctr(self, ad_text: Dict, context: Dict) -> Dict:
        """Predict CTR for an ad copy variation."""
        model = self._get_model(CTRPredictorModel)
        if not model.is_trained():
            return {'predicted_ctr': None, 'confidence': 0, 'source': 'no_model'}
        result = model.predict_ctr(ad_text, context)
        result['source'] = 'ml_model'
        return result

    # ------------------------------------------------------------------
    # Summary for context builder
    # ------------------------------------------------------------------

    def get_all_predictions_summary(self, context: Dict) -> Dict:
        """
        Generate a summary of all available ML predictions for the context builder.

        This is called once at the start of an agent cycle and provides
        all ML insights at once for the LLM to consider.
        """
        summary = {
            'models_available': [],
            'models_unavailable': [],
            'predictions': {},
        }

        model_classes = [
            BudgetROIModel, AnomalyDetectorModel, SpendForecastModel,
            QualityScoreModel, CPAPredictorModel, WasteClassifierModel,
            CTRPredictorModel,
        ]

        for cls in model_classes:
            model = self._get_model(cls)
            if model.is_trained():
                summary['models_available'].append({
                    'name': cls.model_name,
                    'trained_at': str(model.trained_at),
                    'metrics': model.metrics,
                })
            else:
                summary['models_unavailable'].append(cls.model_name)

        # Generate campaign-level predictions if data available
        campaigns = context.get('campaigns', [])
        if campaigns:
            campaign_predictions = []
            for c in campaigns[:10]:
                pred = self.predict_campaign_roas(c)
                if pred.get('predicted_roas') is not None:
                    campaign_predictions.append({
                        'campaign': c.get('name'),
                        'predicted_roas': pred['predicted_roas'],
                        'confidence': pred['confidence'],
                    })
            if campaign_predictions:
                summary['predictions']['campaign_roas'] = campaign_predictions

        # Keyword CPA predictions
        keywords = context.get('keywords', [])
        if keywords:
            keyword_predictions = []
            for kw in keywords[:10]:
                pred = self.predict_keyword_cpa(kw)
                if pred.get('predicted_cpa') is not None:
                    keyword_predictions.append({
                        'keyword': kw.get('text'),
                        'predicted_cpa': pred['predicted_cpa'],
                        'confidence': pred['confidence'],
                    })
            if keyword_predictions:
                summary['predictions']['keyword_cpa'] = keyword_predictions

        # Search term waste classifications
        search_terms = context.get('search_terms', [])
        if search_terms:
            waste_predictions = []
            for st in search_terms[:20]:
                pred = self.classify_search_term(st.get('text', ''), st)
                if pred.get('probability', 0) > 0.5:
                    waste_predictions.append({
                        'term': st.get('text'),
                        'waste_probability': pred['probability'],
                        'spend': st.get('spend', 0),
                    })
            if waste_predictions:
                summary['predictions']['waste_search_terms'] = waste_predictions

        return summary
