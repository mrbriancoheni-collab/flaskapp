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

from app.ml.predictor import MLPredictor
from app.ml.context_builder import ContextBuilder
from app.ml.llm_advisor import LLMAdvisor

__all__ = ['MLPredictor', 'ContextBuilder', 'LLMAdvisor']
