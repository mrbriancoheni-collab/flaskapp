"""
Google Ads Forecasting and Analysis Services

Anomaly detection, seasonal forecasting, what-if scenarios, experiments, and voice search.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, date
from typing import Dict, List, Optional, Any, Tuple
from decimal import Decimal
import json
from statistics import mean, stdev
import random

from sqlalchemy import text
from app.extensions import db

logger = logging.getLogger(__name__)


# =============================================================================
# ANOMALY DETECTION WITH ROOT CAUSE ANALYSIS (#24)
# =============================================================================

def detect_anomalies(account_id: int, lookback_days: int = 7) -> List[Dict]:
    """
    Detect anomalies in campaign performance with root cause analysis.

    Detects:
    - Sudden CTR drops/spikes
    - CPC spikes
    - Conversion rate changes
    - Spend anomalies
    - Position changes

    Uses statistical analysis (Z-score, moving average) to detect outliers.

    Returns:
        List of anomalies with probable causes and recommended actions
    """
    anomalies = []

    try:
        # Get campaign metrics for analysis
        metrics = _get_metrics_for_anomaly_detection(account_id, lookback_days)

        for metric_name in ['ctr', 'cpc', 'cvr', 'cost', 'avg_position']:
            detected = _detect_metric_anomalies(account_id, metric_name, metrics)
            anomalies.extend(detected)

        # Save anomalies to database
        for anomaly in anomalies:
            _save_anomaly(account_id, anomaly)

        logger.info(f"[ANOMALY_DETECTION] Found {len(anomalies)} anomalies for account {account_id}")
        return anomalies

    except Exception as e:
        logger.exception(f"Error detecting anomalies: {e}")
        return []


def _detect_metric_anomalies(
    account_id: int,
    metric_name: str,
    metrics: List[Dict]
) -> List[Dict]:
    """Detect anomalies for a specific metric using statistical analysis."""
    anomalies = []

    try:
        # Group by entity (campaign, ad group, keyword)
        entities = {}
        for m in metrics:
            entity_key = f"{m['entity_type']}_{m['entity_id']}"
            if entity_key not in entities:
                entities[entity_key] = {
                    'entity_type': m['entity_type'],
                    'entity_id': m['entity_id'],
                    'entity_name': m['entity_name'],
                    'values': []
                }
            entities[entity_key]['values'].append({
                'date': m['date'],
                'value': m.get(metric_name, 0)
            })

        # Analyze each entity
        for entity_key, entity_data in entities.items():
            values = [v['value'] for v in entity_data['values']]

            if len(values) < 3:  # Need minimum sample size
                continue

            # Calculate baseline (mean and stddev)
            historical_mean = mean(values[:-1])  # All but last value
            historical_stddev = stdev(values[:-1]) if len(values) > 2 else 0

            current_value = values[-1]

            # Z-score anomaly detection
            if historical_stddev > 0:
                z_score = abs(current_value - historical_mean) / historical_stddev

                if z_score > 2.5:  # 2.5 sigma = ~99% confidence
                    # Determine anomaly type
                    if current_value > historical_mean:
                        anomaly_type = 'spike'
                    else:
                        anomaly_type = 'drop'

                    deviation_pct = ((current_value - historical_mean) / historical_mean) * 100 if historical_mean > 0 else 0

                    # Determine severity
                    if abs(deviation_pct) >= 50:
                        severity = 'critical'
                    elif abs(deviation_pct) >= 30:
                        severity = 'warning'
                    else:
                        severity = 'info'

                    # Root cause analysis
                    probable_causes = _analyze_root_cause(
                        account_id,
                        entity_data['entity_type'],
                        entity_data['entity_id'],
                        metric_name,
                        anomaly_type
                    )

                    # Recommended actions
                    recommended_actions = _get_anomaly_recommendations(
                        metric_name,
                        anomaly_type,
                        deviation_pct
                    )

                    anomaly = {
                        'entity_type': entity_data['entity_type'],
                        'entity_id': entity_data['entity_id'],
                        'entity_name': entity_data['entity_name'],
                        'metric_name': metric_name,
                        'anomaly_type': anomaly_type,
                        'expected_value': round(historical_mean, 2),
                        'actual_value': round(current_value, 2),
                        'deviation_pct': round(deviation_pct, 2),
                        'severity': severity,
                        'confidence_score': min(0.9999, z_score / 5.0),  # Normalize to 0-1
                        'probable_causes': probable_causes,
                        'recommended_actions': recommended_actions,
                        'occurred_at': entity_data['values'][-1]['date']
                    }

                    anomalies.append(anomaly)

        return anomalies

    except Exception as e:
        logger.error(f"Error detecting metric anomalies: {e}")
        return []


def _analyze_root_cause(
    account_id: int,
    entity_type: str,
    entity_id: int,
    metric_name: str,
    anomaly_type: str
) -> List[Dict]:
    """Analyze probable root causes for an anomaly."""
    causes = []

    try:
        # Check for position changes (affects CTR, CPC)
        if metric_name in ['ctr', 'cpc']:
            position_change = _check_position_change(account_id, entity_type, entity_id)
            if position_change:
                causes.append({
                    'cause': f"Position changed from {position_change['old']:.1f} to {position_change['new']:.1f}",
                    'confidence': 0.85,
                    'impact': position_change['impact']
                })

        # Check for bid changes
        if metric_name in ['cpc', 'avg_position', 'ctr']:
            bid_change = _check_bid_change(account_id, entity_type, entity_id)
            if bid_change:
                causes.append({
                    'cause': f"Bid changed from ${bid_change['old']:.2f} to ${bid_change['new']:.2f}",
                    'confidence': 0.90,
                    'impact': bid_change['impact']
                })

        # Check for competitive pressure (auction insights)
        if metric_name in ['impression_share', 'avg_position', 'cpc']:
            comp_pressure = _check_competitive_pressure(account_id, entity_id)
            if comp_pressure:
                causes.append({
                    'cause': f"Increased competitive pressure: {comp_pressure['competitors']} new competitors",
                    'confidence': 0.70,
                    'impact': 'Position and CPC affected'
                })

        # Check for quality score changes
        if metric_name in ['cpc', 'avg_position']:
            qs_change = _check_quality_score_change(account_id, entity_type, entity_id)
            if qs_change:
                causes.append({
                    'cause': f"Quality Score dropped from {qs_change['old']} to {qs_change['new']}",
                    'confidence': 0.80,
                    'impact': 'Higher CPC, lower position'
                })

        # If no specific cause found, provide general insights
        if not causes:
            causes.append({
                'cause': f"Unexplained {anomaly_type} in {metric_name}",
                'confidence': 0.50,
                'impact': 'Requires investigation'
            })

        return causes

    except Exception as e:
        logger.error(f"Error analyzing root cause: {e}")
        return []


def _get_anomaly_recommendations(metric_name: str, anomaly_type: str, deviation_pct: float) -> List[Dict]:
    """Get recommended actions for an anomaly."""
    recommendations = []

    if metric_name == 'ctr' and anomaly_type == 'drop':
        recommendations.append({
            'action': 'Review ad copy and test new variations',
            'priority': 'high' if abs(deviation_pct) > 40 else 'medium'
        })
        recommendations.append({
            'action': 'Check if position has dropped significantly',
            'priority': 'high'
        })

    elif metric_name == 'cpc' and anomaly_type == 'spike':
        recommendations.append({
            'action': 'Review competitive landscape and auction insights',
            'priority': 'high'
        })
        recommendations.append({
            'action': 'Consider lowering bids if CPA target is exceeded',
            'priority': 'medium'
        })

    elif metric_name == 'cvr' and anomaly_type == 'drop':
        recommendations.append({
            'action': 'Check landing page - load time, content, forms',
            'priority': 'critical'
        })
        recommendations.append({
            'action': 'Review recent changes to landing page or ad copy',
            'priority': 'high'
        })

    elif metric_name == 'cost' and anomaly_type == 'spike':
        recommendations.append({
            'action': 'Check budget pacing and daily spend limits',
            'priority': 'critical'
        })
        recommendations.append({
            'action': 'Review for click fraud or bot traffic',
            'priority': 'high'
        })

    return recommendations


def _save_anomaly(account_id: int, anomaly: Dict):
    """Save anomaly to database."""
    try:
        query = text("""
            INSERT INTO ads_anomalies (
                account_id, entity_type, entity_id, entity_name,
                metric_name, anomaly_type, expected_value, actual_value,
                deviation_pct, severity, confidence_score,
                probable_causes, recommended_actions, occurred_at
            ) VALUES (
                :account_id, :entity_type, :entity_id, :entity_name,
                :metric_name, :anomaly_type, :expected_value, :actual_value,
                :deviation_pct, :severity, :confidence_score,
                :probable_causes, :recommended_actions, :occurred_at
            )
        """)

        db.session.execute(query, {
            'account_id': account_id,
            'entity_type': anomaly['entity_type'],
            'entity_id': anomaly['entity_id'],
            'entity_name': anomaly['entity_name'],
            'metric_name': anomaly['metric_name'],
            'anomaly_type': anomaly['anomaly_type'],
            'expected_value': anomaly['expected_value'],
            'actual_value': anomaly['actual_value'],
            'deviation_pct': anomaly['deviation_pct'],
            'severity': anomaly['severity'],
            'confidence_score': anomaly['confidence_score'],
            'probable_causes': json.dumps(anomaly['probable_causes']),
            'recommended_actions': json.dumps(anomaly['recommended_actions']),
            'occurred_at': anomaly.get('occurred_at')
        })
        db.session.commit()

    except Exception as e:
        logger.error(f"Error saving anomaly: {e}")
        db.session.rollback()


# =============================================================================
# SEASONAL DEMAND FORECASTING (#26)
# =============================================================================

def forecast_seasonal_demand(
    account_id: int,
    category: str,
    forecast_days: int = 90
) -> List[Dict]:
    """
    Forecast seasonal demand for a service category.

    Uses historical data + external factors:
    - Last 3 years of search volume patterns
    - Weather forecasts (for HVAC, roofing, etc.)
    - Holiday calendars
    - Economic indicators

    Args:
        account_id: Account ID
        category: Service category (HVAC, Plumbing, Roofing, etc.)
        forecast_days: Number of days to forecast

    Returns:
        List of daily forecasts with recommended budget adjustments
    """
    forecasts = []

    try:
        # Get historical patterns
        historical_data = _get_historical_seasonal_patterns(account_id, category)

        # Generate forecasts for next N days
        start_date = date.today()

        for day_offset in range(forecast_days):
            forecast_date = start_date + timedelta(days=day_offset)

            # Base forecast from historical patterns
            base_forecast = _get_base_seasonal_forecast(historical_data, forecast_date)

            # Apply external factors
            weather_impact = _get_weather_forecast_impact(category, forecast_date)
            holiday_impact = _get_holiday_impact(forecast_date)

            # Calculate predictions
            predicted_volume = int(base_forecast['avg_volume'] * (1 + weather_impact + holiday_impact))
            predicted_cpc = base_forecast['avg_cpc'] * (1 + (weather_impact / 2))  # CPC increases with demand
            predicted_cvr = base_forecast['avg_cvr']
            predicted_leads = int(predicted_volume * predicted_cvr)

            # Confidence score
            confidence = min(0.95, base_forecast['confidence'] * (1 - abs(weather_impact + holiday_impact) / 2))

            # Budget recommendation
            current_budget = _get_current_daily_budget(account_id, category)
            recommended_budget = current_budget * (1 + weather_impact + holiday_impact)
            budget_change_pct = ((recommended_budget - current_budget) / current_budget) * 100 if current_budget > 0 else 0

            # Influencing factors
            factors = []
            if abs(weather_impact) > 0.10:
                factors.append({
                    'factor': f"Weather forecast: {'high' if weather_impact > 0 else 'low'} demand period",
                    'impact': f"{weather_impact:+.0%}"
                })
            if abs(holiday_impact) > 0.05:
                factors.append({
                    'factor': 'Holiday/seasonal period',
                    'impact': f"{holiday_impact:+.0%}"
                })

            forecast = {
                'forecast_for_date': forecast_date,
                'forecast_for_month': forecast_date.month,
                'forecast_for_week': forecast_date.isocalendar()[1],
                'category': category,
                'historical_avg': base_forecast['avg_volume'],
                'predicted_search_volume': predicted_volume,
                'predicted_cpc': round(predicted_cpc, 2),
                'predicted_conversion_rate': round(predicted_cvr, 4),
                'predicted_leads': predicted_leads,
                'confidence_score': round(confidence, 2),
                'influencing_factors': factors,
                'recommended_budget': round(recommended_budget, 2),
                'recommended_budget_change_pct': round(budget_change_pct, 2),
                'recommended_actions': _get_seasonal_recommendations(budget_change_pct, category)
            }

            forecasts.append(forecast)

            # Save forecast to database
            _save_seasonal_forecast(account_id, forecast)

        logger.info(f"[SEASONAL_FORECAST] Generated {len(forecasts)} days of forecasts for {category}")
        return forecasts

    except Exception as e:
        logger.exception(f"Error forecasting seasonal demand: {e}")
        return []


def _get_weather_forecast_impact(category: str, forecast_date: date) -> float:
    """
    Get weather forecast impact on demand.

    For demo purposes, using simplified logic.
    In production, integrate with weather API (OpenWeatherMap, etc.)
    """
    # Seasonal multipliers by month
    month = forecast_date.month

    # HVAC: High demand in summer (Jun-Aug) and winter (Dec-Feb)
    if category == 'HVAC':
        if month in [6, 7, 8]:  # Summer
            return 0.40  # +40% demand
        elif month in [12, 1, 2]:  # Winter
            return 0.35  # +35% demand
        elif month in [3, 4, 5, 9, 10, 11]:  # Spring/Fall
            return -0.15  # -15% demand

    # Roofing: High demand in spring/summer
    elif category == 'Roofing':
        if month in [4, 5, 6, 7]:
            return 0.30  # +30% demand
        elif month in [12, 1, 2]:
            return -0.40  # -40% demand (winter)

    # Plumbing: Relatively stable, slight winter increase (frozen pipes)
    elif category == 'Plumbing':
        if month in [12, 1, 2]:
            return 0.15  # +15% demand
        else:
            return 0.0

    # Lawn Care: Peak in spring/summer
    elif category == 'Lawn Care':
        if month in [4, 5, 6, 7, 8]:
            return 0.50  # +50% demand
        elif month in [11, 12, 1, 2]:
            return -0.70  # -70% demand (winter)

    return 0.0


def _get_holiday_impact(forecast_date: date) -> float:
    """Get holiday impact on search volume."""
    # Major holidays typically reduce commercial searches
    month, day = forecast_date.month, forecast_date.day

    # Christmas week
    if month == 12 and 23 <= day <= 26:
        return -0.30

    # New Year's week
    if month == 1 and day <= 2:
        return -0.20

    # Thanksgiving week
    if month == 11 and 22 <= day <= 25:
        return -0.15

    # July 4th
    if month == 7 and 3 <= day <= 5:
        return -0.10

    return 0.0


def _get_seasonal_recommendations(budget_change_pct: float, category: str) -> List[str]:
    """Get recommendations based on forecast."""
    recommendations = []

    if budget_change_pct >= 30:
        recommendations.append(f"High demand period for {category} - increase budget by {budget_change_pct:.0f}%")
        recommendations.append("Consider adding more ad groups for high-intent keywords")
        recommendations.append("Ensure adequate landing page capacity for increased traffic")
    elif budget_change_pct >= 15:
        recommendations.append(f"Moderate demand increase - adjust budget by {budget_change_pct:.0f}%")
        recommendations.append("Monitor conversion rates closely")
    elif budget_change_pct <= -20:
        recommendations.append(f"Low demand period - reduce budget by {abs(budget_change_pct):.0f}%")
        recommendations.append("Focus on brand awareness and retargeting")
    else:
        recommendations.append("Maintain current budget allocation")

    return recommendations


def _save_seasonal_forecast(account_id: int, forecast: Dict):
    """Save seasonal forecast to database."""
    try:
        query = text("""
            INSERT INTO ads_seasonal_forecasts (
                account_id, forecast_for_date, forecast_for_month, forecast_for_week,
                category, historical_avg, predicted_search_volume, predicted_cpc,
                predicted_conversion_rate, predicted_leads, confidence_score,
                influencing_factors, recommended_budget, recommended_budget_change_pct,
                recommended_actions
            ) VALUES (
                :account_id, :forecast_date, :forecast_month, :forecast_week,
                :category, :historical_avg, :predicted_volume, :predicted_cpc,
                :predicted_cvr, :predicted_leads, :confidence,
                :factors, :recommended_budget, :budget_change_pct,
                :actions
            )
            ON DUPLICATE KEY UPDATE
                predicted_search_volume = :predicted_volume,
                predicted_cpc = :predicted_cpc,
                predicted_leads = :predicted_leads,
                confidence_score = :confidence,
                recommended_budget = :recommended_budget
        """)

        db.session.execute(query, {
            'account_id': account_id,
            'forecast_date': forecast['forecast_for_date'],
            'forecast_month': forecast['forecast_for_month'],
            'forecast_week': forecast['forecast_for_week'],
            'category': forecast['category'],
            'historical_avg': forecast['historical_avg'],
            'predicted_volume': forecast['predicted_search_volume'],
            'predicted_cpc': forecast['predicted_cpc'],
            'predicted_cvr': forecast['predicted_conversion_rate'],
            'predicted_leads': forecast['predicted_leads'],
            'confidence': forecast['confidence_score'],
            'factors': json.dumps(forecast['influencing_factors']),
            'recommended_budget': forecast['recommended_budget'],
            'budget_change_pct': forecast['recommended_budget_change_pct'],
            'actions': json.dumps(forecast['recommended_actions'])
        })
        db.session.commit()

    except Exception as e:
        logger.error(f"Error saving seasonal forecast: {e}")
        db.session.rollback()


# =============================================================================
# WHAT-IF SCENARIO PLANNER (#23)
# =============================================================================

def analyze_what_if_scenario(
    account_id: int,
    scenario_name: str,
    scenario_type: str,
    changes: Dict
) -> Dict:
    """
    Analyze a what-if scenario and predict outcomes.

    Scenarios:
    - budget_change: What if I increase/decrease budget by X%?
    - bid_adjustment: What if I adjust bids by X%?
    - keyword_changes: What if I add/remove these keywords?
    - geo_changes: What if I target different locations?

    Returns:
        Predicted outcomes with confidence intervals
    """
    try:
        # Get current baseline metrics
        baseline = _get_current_baseline_metrics(account_id)

        # Predict outcomes based on scenario type
        if scenario_type == 'budget_change':
            predictions = _predict_budget_change_impact(account_id, baseline, changes)
        elif scenario_type == 'bid_adjustment':
            predictions = _predict_bid_adjustment_impact(account_id, baseline, changes)
        elif scenario_type == 'keyword_changes':
            predictions = _predict_keyword_change_impact(account_id, baseline, changes)
        else:
            predictions = {'error': 'Unknown scenario type'}

        # Calculate risk assessment
        risk = _assess_scenario_risk(scenario_type, changes, predictions)

        scenario = {
            'scenario_name': scenario_name,
            'scenario_type': scenario_type,
            'baseline_metrics': baseline,
            'changes': changes,
            'predicted_metrics': predictions,
            'expected_roi_change': predictions.get('roi_change_pct', 0),
            'expected_lead_change': predictions.get('lead_change', 0),
            'expected_cpa_change': predictions.get('cpa_change_pct', 0),
            'risk_assessment': risk,
            'confidence': predictions.get('confidence', 0.70)
        }

        # Save scenario
        _save_what_if_scenario(account_id, scenario)

        return scenario

    except Exception as e:
        logger.exception(f"Error analyzing what-if scenario: {e}")
        return {'error': str(e)}


def _predict_budget_change_impact(account_id: int, baseline: Dict, changes: Dict) -> Dict:
    """Predict impact of budget changes."""
    budget_change_pct = changes.get('budget_increase_pct', 0)

    # Simplified model - in production, use ML
    # Assumption: Linear relationship up to 50% increase, then diminishing returns
    if budget_change_pct <= 50:
        lead_increase_pct = budget_change_pct * 0.8  # 80% efficiency
    else:
        lead_increase_pct = 40 + (budget_change_pct - 50) * 0.4  # Diminishing returns

    # CPA typically increases slightly with budget (less qualified traffic)
    cpa_increase_pct = budget_change_pct * 0.15

    current_leads = baseline.get('total_leads', 100)
    current_cpa = baseline.get('avg_cpa', 50.0)

    new_leads = int(current_leads * (1 + lead_increase_pct / 100))
    new_cpa = current_cpa * (1 + cpa_increase_pct / 100)

    return {
        'predicted_leads': new_leads,
        'lead_change': new_leads - current_leads,
        'lead_change_pct': lead_increase_pct,
        'predicted_cpa': round(new_cpa, 2),
        'cpa_change_pct': cpa_increase_pct,
        'roi_change_pct': lead_increase_pct - cpa_increase_pct,
        'confidence': 0.75
    }


def _assess_scenario_risk(scenario_type: str, changes: Dict, predictions: Dict) -> str:
    """Assess risk level of a scenario."""
    if scenario_type == 'budget_change':
        change_pct = abs(changes.get('budget_increase_pct', 0))
        if change_pct >= 50:
            return 'high'
        elif change_pct >= 25:
            return 'medium'
        else:
            return 'low'

    elif scenario_type == 'bid_adjustment':
        change_pct = abs(changes.get('bid_adjustment_pct', 0))
        if change_pct >= 30:
            return 'high'
        elif change_pct >= 15:
            return 'medium'
        else:
            return 'low'

    return 'medium'


def _save_what_if_scenario(account_id: int, scenario: Dict):
    """Save what-if scenario to database."""
    # Implementation similar to other save functions
    pass


# =============================================================================
# VOICE SEARCH OPTIMIZATION (#25)
# =============================================================================

def optimize_for_voice_search(account_id: int) -> Dict:
    """
    Identify and optimize voice search queries.

    Voice search characteristics:
    - Questions (who, what, where, when, why, how)
    - Longer queries (5+ words)
    - Natural language
    - Local intent ("near me", "open now")
    - Action intent

    Returns:
        Voice search insights and optimization recommendations
    """
    try:
        voice_queries = _identify_voice_search_queries(account_id)

        recommendations = {
            'total_voice_queries': len(voice_queries),
            'question_queries': [q for q in voice_queries if q['is_question']],
            'local_intent_queries': [q for q in voice_queries if q['has_local_intent']],
            'suggested_keywords': _generate_voice_keywords(voice_queries),
            'suggested_ad_copy': _generate_voice_ad_copy(voice_queries),
            'optimization_tips': [
                "Use conversational language in ad copy",
                "Include FAQ-style headlines",
                "Target question-based keywords",
                "Emphasize local availability and hours",
                "Use call extensions prominently"
            ]
        }

        return recommendations

    except Exception as e:
        logger.exception(f"Error optimizing for voice search: {e}")
        return {}


def _identify_voice_search_queries(account_id: int) -> List[Dict]:
    """
    Identify voice search patterns in search queries.
    Voice searches typically:
    - Are questions (who, what, where, when, why, how)
    - Are longer (5+ words)
    - Use natural language
    - Have local intent ("near me", "open now")
    """
    voice_queries = []

    # Voice search pattern indicators
    question_starters = ['who', 'what', 'where', 'when', 'why', 'how', 'can', 'does', 'is', 'are']
    local_indicators = ['near me', 'nearby', 'close to', 'around here', 'open now', 'hours', 'directions']

    try:
        # Use search_terms table (the actual table name in the schema)
        query = text("""
            SELECT search_term, impressions, clicks, conversions
            FROM search_terms
            WHERE account_id = :account_id
              AND date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
            ORDER BY impressions DESC
            LIMIT 500
        """)

        result = db.session.execute(query, {'account_id': account_id})

        for row in result:
            search_term = (row.search_term or '').lower()
            word_count = len(search_term.split())

            # Check voice search characteristics
            is_question = any(search_term.startswith(q) for q in question_starters)
            has_local_intent = any(loc in search_term for loc in local_indicators)
            is_long_query = word_count >= 5

            # Consider it a voice query if it matches patterns
            if is_question or has_local_intent or is_long_query:
                voice_queries.append({
                    'search_term': row.search_term,
                    'impressions': row.impressions or 0,
                    'clicks': row.clicks or 0,
                    'conversions': float(row.conversions or 0),
                    'is_question': is_question,
                    'has_local_intent': has_local_intent,
                    'word_count': word_count
                })

    except Exception as e:
        logger.warning(f"Could not fetch voice search queries: {e}")

    return voice_queries


def _generate_voice_keywords(voice_queries: List[Dict]) -> List[str]:
    """Generate voice-optimized keywords from voice query patterns."""
    if not voice_queries:
        return [
            "how to find [service] near me",
            "best [service] in [city]",
            "who does [service] on weekends",
            "[service] open now near me"
        ]

    keywords = []
    seen = set()

    for query in voice_queries:
        term = query.get('search_term', '')
        if term and term not in seen:
            # Add the original term
            keywords.append(term)
            seen.add(term)

            # Generate variations
            if query.get('is_question'):
                # Convert question to phrase match
                keywords.append(f'"{term}"')

    return keywords[:20]  # Limit to top 20


def _generate_voice_ad_copy(voice_queries: List[Dict]) -> List[Dict]:
    """Generate voice-optimized ad copy suggestions."""
    suggestions = []

    # Generic voice-optimized suggestions
    suggestions.append({
        'headline': "Need Help Now? Call Us 24/7",
        'description': "Fast response times. Local experts ready to help.",
        'reason': "Addresses urgency common in voice searches"
    })

    suggestions.append({
        'headline': "Find Us Near You Today",
        'description': "Serving your area with same-day service available.",
        'reason': "Targets local intent voice queries"
    })

    # Generate from actual queries if available
    question_queries = [q for q in voice_queries if q.get('is_question')]
    for query in question_queries[:3]:
        term = query.get('search_term', '')
        if term:
            suggestions.append({
                'headline': f"Answer: {term[:30]}",
                'description': "Get your questions answered by our experts.",
                'reason': f"Directly answers voice query: {term}"
            })

    return suggestions


def _get_metrics_for_anomaly_detection(account_id: int, days: int) -> List[Dict]:
    """Get metrics for anomaly detection from campaign performance data."""
    metrics = []

    try:
        # Try to get data from gads_stats_daily or campaign performance tables
        query = text("""
            SELECT
                'campaign' as entity_type,
                entity_id,
                entity_name,
                date,
                CASE WHEN impressions > 0 THEN clicks * 100.0 / impressions ELSE 0 END as ctr,
                CASE WHEN clicks > 0 THEN cost_micros / 1000000.0 / clicks ELSE 0 END as cpc,
                CASE WHEN clicks > 0 THEN conversions * 100.0 / clicks ELSE 0 END as cvr,
                cost_micros / 1000000.0 as cost,
                avg_position
            FROM gads_stats_daily
            WHERE account_id = :account_id
              AND entity_type = 'campaign'
              AND date >= DATE_SUB(CURDATE(), INTERVAL :days DAY)
            ORDER BY entity_id, date
        """)

        result = db.session.execute(query, {'account_id': account_id, 'days': days})

        for row in result:
            metrics.append({
                'entity_type': row.entity_type,
                'entity_id': row.entity_id,
                'entity_name': row.entity_name or f'Campaign {row.entity_id}',
                'date': row.date,
                'ctr': float(row.ctr or 0),
                'cpc': float(row.cpc or 0),
                'cvr': float(row.cvr or 0),
                'cost': float(row.cost or 0),
                'avg_position': float(row.avg_position or 0)
            })

    except Exception as e:
        logger.warning(f"Could not fetch metrics for anomaly detection: {e}")

    return metrics


def _check_position_change(account_id: int, entity_type: str, entity_id: int) -> Optional[Dict]:
    """Check for recent position changes for an entity."""
    try:
        query = text("""
            SELECT
                AVG(CASE WHEN date >= DATE_SUB(CURDATE(), INTERVAL 3 DAY) THEN avg_position END) as recent_position,
                AVG(CASE WHEN date < DATE_SUB(CURDATE(), INTERVAL 3 DAY)
                         AND date >= DATE_SUB(CURDATE(), INTERVAL 10 DAY) THEN avg_position END) as previous_position
            FROM gads_stats_daily
            WHERE account_id = :account_id
              AND entity_type = :entity_type
              AND entity_id = :entity_id
              AND date >= DATE_SUB(CURDATE(), INTERVAL 10 DAY)
        """)

        result = db.session.execute(query, {
            'account_id': account_id,
            'entity_type': entity_type,
            'entity_id': entity_id
        }).first()

        if result and result.recent_position and result.previous_position:
            change = result.recent_position - result.previous_position
            if abs(change) > 0.5:  # Significant position change
                return {
                    'old': float(result.previous_position),
                    'new': float(result.recent_position),
                    'change': float(change),
                    'impact': 'Position dropped' if change > 0 else 'Position improved'
                }

    except Exception as e:
        logger.warning(f"Could not check position change: {e}")

    return None


def _check_bid_change(account_id: int, entity_type: str, entity_id: int) -> Optional[Dict]:
    """Check for recent bid changes for an entity."""
    try:
        query = text("""
            SELECT
                AVG(CASE WHEN date >= DATE_SUB(CURDATE(), INTERVAL 3 DAY) THEN max_cpc_micros END) as recent_bid,
                AVG(CASE WHEN date < DATE_SUB(CURDATE(), INTERVAL 3 DAY)
                         AND date >= DATE_SUB(CURDATE(), INTERVAL 10 DAY) THEN max_cpc_micros END) as previous_bid
            FROM gads_stats_daily
            WHERE account_id = :account_id
              AND entity_type = :entity_type
              AND entity_id = :entity_id
              AND date >= DATE_SUB(CURDATE(), INTERVAL 10 DAY)
        """)

        result = db.session.execute(query, {
            'account_id': account_id,
            'entity_type': entity_type,
            'entity_id': entity_id
        }).first()

        if result and result.recent_bid and result.previous_bid:
            old_bid = float(result.previous_bid) / 1000000
            new_bid = float(result.recent_bid) / 1000000
            change_pct = ((new_bid - old_bid) / old_bid * 100) if old_bid > 0 else 0

            if abs(change_pct) > 10:  # Significant bid change (>10%)
                return {
                    'old': old_bid,
                    'new': new_bid,
                    'change_pct': change_pct,
                    'impact': f"Bid {'increased' if change_pct > 0 else 'decreased'} by {abs(change_pct):.1f}%"
                }

    except Exception as e:
        logger.warning(f"Could not check bid change: {e}")

    return None


def _check_competitive_pressure(account_id: int, entity_id: int) -> Optional[Dict]:
    """Check for increased competitive pressure from auction insights."""
    try:
        query = text("""
            SELECT
                COUNT(DISTINCT CASE WHEN report_date >= DATE_SUB(CURDATE(), INTERVAL 7 DAY)
                                    THEN competitor_domain END) as recent_competitors,
                COUNT(DISTINCT CASE WHEN report_date < DATE_SUB(CURDATE(), INTERVAL 7 DAY)
                                    AND report_date >= DATE_SUB(CURDATE(), INTERVAL 14 DAY)
                                    THEN competitor_domain END) as previous_competitors
            FROM competitive_auction_insights
            WHERE campaign_id = :entity_id
              AND report_date >= DATE_SUB(CURDATE(), INTERVAL 14 DAY)
        """)

        result = db.session.execute(query, {'entity_id': entity_id}).first()

        if result and result.recent_competitors and result.previous_competitors:
            new_competitors = result.recent_competitors - result.previous_competitors
            if new_competitors > 0:
                return {
                    'competitors': new_competitors,
                    'recent_count': result.recent_competitors,
                    'previous_count': result.previous_competitors
                }

    except Exception as e:
        logger.warning(f"Could not check competitive pressure: {e}")

    return None


def _check_quality_score_change(account_id: int, entity_type: str, entity_id: int) -> Optional[Dict]:
    """Check for quality score changes."""
    try:
        query = text("""
            SELECT
                AVG(CASE WHEN date >= DATE_SUB(CURDATE(), INTERVAL 3 DAY) THEN quality_score END) as recent_qs,
                AVG(CASE WHEN date < DATE_SUB(CURDATE(), INTERVAL 3 DAY)
                         AND date >= DATE_SUB(CURDATE(), INTERVAL 10 DAY) THEN quality_score END) as previous_qs
            FROM keyword_quality_scores
            WHERE account_id = :account_id
              AND date >= DATE_SUB(CURDATE(), INTERVAL 10 DAY)
        """)

        result = db.session.execute(query, {'account_id': account_id}).first()

        if result and result.recent_qs and result.previous_qs:
            change = result.recent_qs - result.previous_qs
            if abs(change) >= 1:  # Quality score changed by 1+ point
                return {
                    'old': int(result.previous_qs),
                    'new': int(result.recent_qs),
                    'change': int(change)
                }

    except Exception as e:
        logger.warning(f"Could not check quality score change: {e}")

    return None


def _get_historical_seasonal_patterns(account_id: int, category: str) -> Dict:
    """Get historical seasonal patterns from past data."""
    default_patterns = {
        'avg_volume': 1000,
        'avg_cpc': 3.50,
        'avg_cvr': 0.03,
        'confidence': 0.50  # Low confidence for default data
    }

    try:
        # Try to get real historical data
        query = text("""
            SELECT
                AVG(impressions) as avg_volume,
                AVG(CASE WHEN clicks > 0 THEN cost_micros / 1000000.0 / clicks ELSE NULL END) as avg_cpc,
                AVG(CASE WHEN clicks > 0 THEN conversions / clicks ELSE NULL END) as avg_cvr,
                COUNT(*) as data_points
            FROM gads_stats_daily
            WHERE account_id = :account_id
              AND entity_type = 'campaign'
              AND date >= DATE_SUB(CURDATE(), INTERVAL 90 DAY)
        """)

        result = db.session.execute(query, {'account_id': account_id}).first()

        if result and result.data_points and result.data_points >= 30:
            # Calculate confidence based on data availability
            confidence = min(0.95, 0.50 + (result.data_points / 180))

            return {
                'avg_volume': int(result.avg_volume or default_patterns['avg_volume']),
                'avg_cpc': round(float(result.avg_cpc or default_patterns['avg_cpc']), 2),
                'avg_cvr': round(float(result.avg_cvr or default_patterns['avg_cvr']), 4),
                'confidence': round(confidence, 2)
            }

    except Exception as e:
        logger.warning(f"Could not get historical seasonal patterns: {e}")

    return default_patterns


def _get_base_seasonal_forecast(historical_data: Dict, forecast_date: date) -> Dict:
    """Get base forecast from historical patterns adjusted for the forecast date."""
    # Start with historical averages
    forecast = historical_data.copy()

    # Adjust based on day of week (weekdays typically have more commercial searches)
    day_of_week = forecast_date.weekday()
    if day_of_week >= 5:  # Weekend
        forecast['avg_volume'] = int(forecast['avg_volume'] * 0.7)
    elif day_of_week == 0:  # Monday
        forecast['avg_volume'] = int(forecast['avg_volume'] * 1.1)

    return forecast


def _get_current_daily_budget(account_id: int, category: str) -> float:
    """Get current daily budget for campaigns in a category."""
    try:
        # Use budget_groups table which has min/max daily budget settings
        query = text("""
            SELECT AVG(
                CASE
                    WHEN max_daily_budget IS NOT NULL THEN max_daily_budget
                    ELSE monthly_budget_target / 30
                END
            ) as avg_budget
            FROM budget_groups
            WHERE account_id = :account_id
              AND enabled = TRUE
        """)

        result = db.session.execute(query, {'account_id': account_id}).first()

        if result and result.avg_budget:
            return float(result.avg_budget)

    except Exception as e:
        logger.warning(f"Could not get current daily budget: {e}")

    return 100.0  # Default budget


def _get_current_baseline_metrics(account_id: int) -> Dict:
    """Get current baseline metrics for the account."""
    default_metrics = {
        'total_leads': 0,
        'avg_cpa': 0,
        'total_spend': 0,
        'total_clicks': 0
    }

    try:
        query = text("""
            SELECT
                SUM(conversions) as total_leads,
                CASE WHEN SUM(conversions) > 0
                     THEN SUM(cost_micros) / 1000000.0 / SUM(conversions)
                     ELSE 0 END as avg_cpa,
                SUM(cost_micros) / 1000000.0 as total_spend,
                SUM(clicks) as total_clicks
            FROM gads_stats_daily
            WHERE account_id = :account_id
              AND entity_type = 'account'
              AND date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
        """)

        result = db.session.execute(query, {'account_id': account_id}).first()

        if result:
            return {
                'total_leads': int(result.total_leads or 0),
                'avg_cpa': round(float(result.avg_cpa or 0), 2),
                'total_spend': round(float(result.total_spend or 0), 2),
                'total_clicks': int(result.total_clicks or 0)
            }

    except Exception as e:
        logger.warning(f"Could not get current baseline metrics: {e}")

    return default_metrics


def _predict_bid_adjustment_impact(account_id: int, baseline: Dict, changes: Dict) -> Dict:
    """Predict impact of bid adjustments."""
    bid_change_pct = changes.get('bid_adjustment_pct', 0)

    # Simplified model: bid changes have non-linear effect on position and traffic
    # Higher bids generally improve position but with diminishing returns
    if bid_change_pct > 0:
        # Increasing bids
        position_improvement = min(2.0, bid_change_pct / 20)  # Max 2 position improvement
        traffic_increase_pct = bid_change_pct * 0.6  # 60% efficiency
        cpc_increase_pct = bid_change_pct * 0.8  # CPC rises nearly proportionally
    else:
        # Decreasing bids
        position_decline = min(3.0, abs(bid_change_pct) / 15)  # Position drops faster
        traffic_increase_pct = bid_change_pct * 0.7  # Traffic drops
        cpc_increase_pct = bid_change_pct * 0.5  # CPC savings

    current_clicks = baseline.get('total_clicks', 500)
    current_cpa = baseline.get('avg_cpa', 50.0)

    new_clicks = int(current_clicks * (1 + traffic_increase_pct / 100))
    new_cpa = current_cpa * (1 + cpc_increase_pct / 100)

    return {
        'predicted_clicks': new_clicks,
        'click_change': new_clicks - current_clicks,
        'click_change_pct': traffic_increase_pct,
        'predicted_cpa': round(new_cpa, 2),
        'cpa_change_pct': cpc_increase_pct,
        'roi_change_pct': traffic_increase_pct - cpc_increase_pct,
        'confidence': 0.70
    }


def _predict_keyword_change_impact(account_id: int, baseline: Dict, changes: Dict) -> Dict:
    """Predict impact of keyword changes."""
    keywords_to_add = changes.get('keywords_to_add', [])
    keywords_to_remove = changes.get('keywords_to_remove', [])

    # Estimate impact based on number of keywords
    add_count = len(keywords_to_add)
    remove_count = len(keywords_to_remove)

    # Each new keyword might add ~5% incremental traffic (diminishing)
    traffic_from_new = min(50, add_count * 5 * (1 - add_count * 0.02))
    # Removing keywords reduces traffic
    traffic_from_removed = -remove_count * 3

    total_traffic_change = traffic_from_new + traffic_from_removed

    current_leads = baseline.get('total_leads', 100)
    current_cpa = baseline.get('avg_cpa', 50.0)

    new_leads = int(current_leads * (1 + total_traffic_change / 100))

    # New keywords might have higher CPA initially
    cpa_impact = add_count * 2 if add_count > 0 else 0

    return {
        'predicted_leads': new_leads,
        'lead_change': new_leads - current_leads,
        'lead_change_pct': total_traffic_change,
        'predicted_cpa': round(current_cpa + cpa_impact, 2),
        'cpa_change_pct': (cpa_impact / current_cpa * 100) if current_cpa > 0 else 0,
        'roi_change_pct': total_traffic_change - (cpa_impact / current_cpa * 100 if current_cpa > 0 else 0),
        'confidence': 0.65
    }
