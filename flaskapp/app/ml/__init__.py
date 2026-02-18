# app/ml/__init__.py
"""
ML-powered Google Ads optimization system.

Combines statistical ML models trained on historical account data
with LLM-based analysis to make intelligent optimization decisions.

Architecture:
    DB Data → DataPipeline → ML Models (predictions) → ContextBuilder → LLM Advisor → Agent Decisions
                                                                                          ↓
                                                                               Feedback Loop (outcomes)
"""
import logging

logger = logging.getLogger(__name__)


def ensure_tables():
    """
    Create ML-related database tables if they don't exist.
    Call this once at app startup or before first use.
    """
    from app import db
    from sqlalchemy import text

    try:
        # Create ml_models table for tracking trained models
        db.session.execute(text("""
            CREATE TABLE IF NOT EXISTS ml_models (
                id INT AUTO_INCREMENT PRIMARY KEY,
                account_id INT NOT NULL,
                model_name VARCHAR(100) NOT NULL,
                model_type VARCHAR(50),
                target_metric VARCHAR(100),
                training_date DATETIME,
                features_used JSON,
                accuracy_score FLOAT,
                mae FLOAT,
                rmse FLOAT,
                r2_score FLOAT,
                is_active BOOLEAN DEFAULT TRUE,
                feature_count INT,
                training_samples INT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                UNIQUE KEY uq_account_model (account_id, model_name),
                INDEX idx_account (account_id),
                INDEX idx_model_name (model_name),
                INDEX idx_training_date (training_date)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """))

        # Create ml_predictions table for tracking predictions
        db.session.execute(text("""
            CREATE TABLE IF NOT EXISTS ml_predictions (
                id INT AUTO_INCREMENT PRIMARY KEY,
                account_id INT NOT NULL,
                model_name VARCHAR(100) NOT NULL,
                prediction_type VARCHAR(100),
                input_data JSON,
                prediction_result JSON,
                confidence_score FLOAT,
                actual_outcome JSON,
                outcome_recorded_at DATETIME,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_account (account_id),
                INDEX idx_model (model_name),
                INDEX idx_created (created_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """))

        db.session.commit()
        logger.info("ML tables ensured")
    except Exception as e:
        logger.warning(f"Could not ensure ML tables: {e}")
        db.session.rollback()


from app.ml.predictor import MLPredictor
from app.ml.context_builder import ContextBuilder
from app.ml.llm_advisor import LLMAdvisor

__all__ = ['MLPredictor', 'ContextBuilder', 'LLMAdvisor', 'ensure_tables']
