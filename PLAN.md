# ML System Implementation Plan

## Architecture Overview

```
Historical DB Data → ML Models (predictions/scores) → Context Builder → LLM (decisions) → Agent Action
                           ↑                                                    ↓
                     Weekly Retrain                                    Feedback Loop (outcome tracking)
```

## Components to Build

### 1. Core ML Engine (`app/ml/`)
- `data_pipeline.py` - Extract/aggregate training data per agent from DB tables
- `models.py` - ML model wrappers (scikit-learn/xgboost) per agent purpose
- `trainer.py` - Weekly retraining pipeline
- `predictor.py` - Prediction service called by agents at runtime
- `context_builder.py` - Builds rich LLM context combining ML predictions + raw data
- `llm_advisor.py` - Sends structured prompts to LLM, parses structured responses

### 2. Per-Agent ML Models

| Agent | ML Model | Training Data | Prediction Output |
|-------|----------|---------------|-------------------|
| Strategic Director | Budget ROI predictor | campaign_performance_history, budget_change_log | Predicted ROAS per campaign, optimal budget split |
| Campaign Manager | Performance anomaly detector | gads_stats_daily (campaign), campaign_performance_history | Anomaly scores, trend direction, CPL predictions |
| Budget Guardian | Spend pacing forecaster | ads_budget_pacing_history, budget_change_log | Predicted daily spend, budget exhaustion date |
| Quality Score | QS component predictor | ads_quality_score_predictions, keyword perf | Predicted QS, improvement impact estimates |
| Keyword Optimizer | CPA/bid predictor | gads_stats_daily (keyword), search_terms | Optimal bid, predicted CPA at various bid levels |
| Negative Keyword | Query waste classifier | search_terms, ads_negative_keyword_suggestions | Waste probability per query, intent classification |
| Ad Copy | CTR predictor | gads_stats_daily (ad), ads table | Predicted CTR, ad strength score |

### 3. LLM Integration
- Structured prompts per agent with ML predictions as context
- JSON response parsing for actionable decisions
- Confidence scoring from LLM aligned with ML confidence
- Decision explanation generation for transparency

### 4. Training & Feedback
- Weekly cron job to retrain models with latest data
- Track prediction vs actual outcomes
- Model accuracy monitoring in ml_models table
- Gradual improvement via feedback loop

## Implementation Order
1. Core engine (data_pipeline, models, predictor)
2. Context builder + LLM advisor
3. All 7 agent-specific models
4. Integration into existing agent run_cycle()
5. Training scheduler + feedback loop
