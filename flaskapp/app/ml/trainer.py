# app/ml/trainer.py
"""
ML Model Training Pipeline.

Trains all agent-specific ML models using historical account data.
Designed to run weekly via cron or manually via Flask CLI.
"""
import logging
from typing import Dict, Tuple

from app.ml.data_pipeline import DataPipeline
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


class MLTrainer:
    """
    Trains all ML models for a given account using historical data.

    Usage:
        trainer = MLTrainer(account_id=123)
        results = trainer.train_all()
    """

    def __init__(self, account_id: int):
        self.account_id = account_id
        self.pipeline = DataPipeline(account_id)

    def train_all(self) -> Dict[str, bool]:
        """
        Train all ML models for this account.

        Returns dict mapping model name to success/failure.
        """
        results = {}

        trainers = [
            ('budget_roi', self._train_budget_roi),
            ('anomaly_detector', self._train_anomaly_detector),
            ('spend_forecaster', self._train_spend_forecaster),
            ('quality_score', self._train_quality_score),
            ('cpa_predictor', self._train_cpa_predictor),
            ('waste_classifier', self._train_waste_classifier),
            ('ctr_predictor', self._train_ctr_predictor),
        ]

        for name, trainer_fn in trainers:
            try:
                success = trainer_fn()
                results[name] = success
                status = "trained" if success else "skipped (insufficient data)"
                logger.info(f"[{self.account_id}] {name}: {status}")
            except Exception as e:
                results[name] = False
                logger.error(f"[{self.account_id}] {name}: FAILED - {e}")

        trained = sum(1 for v in results.values() if v)
        logger.info(
            f"[{self.account_id}] Training complete: "
            f"{trained}/{len(results)} models trained"
        )
        return results

    def _train_budget_roi(self) -> bool:
        campaign_data = self.pipeline.get_campaign_performance(days=365)
        budget_history = self.pipeline.get_budget_history(days=365)
        if not campaign_data:
            return False
        model = BudgetROIModel(self.account_id)
        return model.train(campaign_data, budget_history)

    def _train_anomaly_detector(self) -> bool:
        campaign_data = self.pipeline.get_campaign_performance(days=180)
        if not campaign_data:
            return False
        model = AnomalyDetectorModel(self.account_id)
        return model.train(campaign_data)

    def _train_spend_forecaster(self) -> bool:
        campaign_data = self.pipeline.get_campaign_performance(days=180)
        if not campaign_data:
            return False
        model = SpendForecastModel(self.account_id)
        return model.train(campaign_data)

    def _train_quality_score(self) -> bool:
        qs_data = self.pipeline.get_quality_score_history(days=365)
        keyword_data = self.pipeline.get_keyword_performance(days=90)
        if not qs_data:
            return False
        model = QualityScoreModel(self.account_id)
        return model.train(qs_data, keyword_data)

    def _train_cpa_predictor(self) -> bool:
        keyword_data = self.pipeline.get_keyword_performance(days=180)
        if not keyword_data:
            return False
        model = CPAPredictorModel(self.account_id)
        return model.train(keyword_data)

    def _train_waste_classifier(self) -> bool:
        search_data = self.pipeline.get_search_term_data(days=180)
        if not search_data:
            return False
        model = WasteClassifierModel(self.account_id)
        return model.train(search_data)

    def _train_ctr_predictor(self) -> bool:
        ad_data = self.pipeline.get_ad_performance(days=180)
        if not ad_data:
            return False
        model = CTRPredictorModel(self.account_id)
        return model.train(ad_data)


def train_all_accounts() -> Dict[int, Dict[str, bool]]:
    """
    Train ML models for all active Google Ads accounts.

    Returns dict mapping account_id to training results.
    """
    from app import db
    from sqlalchemy import text

    query = text("""
        SELECT DISTINCT a.id as account_id
        FROM accounts a
        JOIN google_oauth_tokens got ON a.id = got.account_id
        WHERE got.product = 'ads'
          AND got.credentials_json IS NOT NULL
          AND a.google_ads_customer_id IS NOT NULL
          AND a.status IN ('active', 'trial')
    """)

    with db.engine.connect() as conn:
        account_ids = [row[0] for row in conn.execute(query).fetchall()]

    logger.info(f"Training ML models for {len(account_ids)} accounts")

    results = {}
    for account_id in account_ids:
        try:
            trainer = MLTrainer(account_id)
            results[account_id] = trainer.train_all()
        except Exception as e:
            logger.error(f"Training failed for account {account_id}: {e}")
            results[account_id] = {'error': str(e)}

    return results
