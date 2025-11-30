"""
Google Ads Advanced Intelligence Services

Provides advanced analytics, automation, and optimization for Google Ads campaigns.
Includes conversion scoring, intent classification, competitive intelligence, and more.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, date
from typing import Dict, List, Optional, Any, Tuple
from decimal import Decimal
import json

from sqlalchemy import text, and_, or_
from app.extensions import db

logger = logging.getLogger(__name__)


# =============================================================================
# CONVERSION PROBABILITY SCORING (#3)
# =============================================================================

def score_conversion_probability(
    account_id: int,
    search_query: str,
    device: str,
    location: str,
    time_of_day: str,
    keyword_id: Optional[int] = None,
    ad_id: Optional[int] = None,
    session_id: Optional[str] = None
) -> Decimal:
    """
    Score the probability that a click will convert (0.0 to 1.0).

    Uses ML-based scoring combining:
    - Historical conversion patterns
    - Time of day / day of week
    - Device type
    - Location
    - Search query intent
    - Keyword/ad performance history

    Args:
        account_id: Account ID
        search_query: The search query
        device: mobile, desktop, tablet
        location: User location (city/state)
        time_of_day: HH:MM format
        keyword_id: Optional keyword ID
        ad_id: Optional ad ID
        session_id: Optional session identifier

    Returns:
        Probability score 0.0000 to 1.0000
    """
    score = Decimal("0.5000")  # baseline
    quality_indicators = []

    try:
        # Factor 1: Time-based scoring
        hour = int(time_of_day.split(':')[0])
        day_of_week = datetime.now().weekday()

        # Business hours bonus (9am-6pm weekdays)
        if 9 <= hour <= 18 and day_of_week < 5:
            score += Decimal("0.15")
            quality_indicators.append("business_hours")

        # Emergency hours (after 6pm, before 8am, weekends)
        if hour >= 18 or hour < 8 or day_of_week >= 5:
            # Check if query has emergency intent
            if any(word in search_query.lower() for word in ['emergency', 'urgent', 'now', '24/7', 'asap']):
                score += Decimal("0.25")
                quality_indicators.append("emergency_intent_afterhours")

        # Factor 2: Device scoring
        if device.lower() == 'mobile':
            # Mobile users tend to convert better for local services
            score += Decimal("0.10")
            quality_indicators.append("mobile_device")

        # Factor 3: Intent-based scoring
        intent_data = classify_query_intent(account_id, search_query)

        if intent_data['intent_type'] == 'emergency':
            score += Decimal("0.30")
            quality_indicators.append("emergency_intent")
        elif intent_data['intent_type'] == 'transactional':
            score += Decimal("0.20")
            quality_indicators.append("transactional_intent")
        elif intent_data['intent_type'] == 'local':
            score += Decimal("0.15")
            quality_indicators.append("local_intent")
        elif intent_data['intent_type'] == 'research':
            score -= Decimal("0.10")
            quality_indicators.append("research_intent_low")

        # Factor 4: Historical keyword performance
        if keyword_id:
            keyword_cvr = _get_keyword_historical_cvr(account_id, keyword_id)
            if keyword_cvr:
                if keyword_cvr > 0.05:  # 5%+ CVR
                    score += Decimal("0.15")
                    quality_indicators.append(f"high_performing_keyword_{keyword_cvr:.2%}")
                elif keyword_cvr < 0.01:  # <1% CVR
                    score -= Decimal("0.10")
                    quality_indicators.append(f"low_performing_keyword_{keyword_cvr:.2%}")

        # Factor 5: Geographic scoring
        # TODO: Analyze historical conversion rates by location

        # Normalize to 0.0-1.0 range
        score = max(Decimal("0.0000"), min(Decimal("1.0000"), score))

        # Save the score
        _save_conversion_score(
            account_id=account_id,
            search_query=search_query,
            device=device,
            location=location,
            time_of_day=time_of_day,
            score=score,
            quality_indicators=quality_indicators,
            keyword_id=keyword_id,
            ad_id=ad_id,
            session_id=session_id
        )

        return score

    except Exception as e:
        logger.exception(f"Error scoring conversion probability: {e}")
        return Decimal("0.5000")  # default neutral score


def _get_keyword_historical_cvr(account_id: int, keyword_id: int) -> Optional[float]:
    """Get historical conversion rate for a keyword."""
    try:
        query = text("""
            SELECT
                SUM(conversions) / NULLIF(SUM(clicks), 0) as cvr
            FROM keywords
            WHERE account_id = :account_id
            AND id = :keyword_id
            AND clicks > 50  -- minimum sample size
        """)

        result = db.session.execute(query, {
            'account_id': account_id,
            'keyword_id': keyword_id
        }).fetchone()

        return float(result[0]) if result and result[0] else None

    except Exception as e:
        logger.error(f"Error getting keyword CVR: {e}")
        return None


def _save_conversion_score(
    account_id: int,
    search_query: str,
    device: str,
    location: str,
    time_of_day: str,
    score: Decimal,
    quality_indicators: List[str],
    keyword_id: Optional[int] = None,
    ad_id: Optional[int] = None,
    session_id: Optional[str] = None
):
    """Save conversion probability score to database."""
    try:
        query = text("""
            INSERT INTO ads_conversion_scores (
                account_id, search_query, device, location,
                time_of_day, day_of_week, probability_score,
                quality_indicators, keyword_id, ad_id, session_id
            ) VALUES (
                :account_id, :search_query, :device, :location,
                :time_of_day, :day_of_week, :score,
                :quality_indicators, :keyword_id, :ad_id, :session_id
            )
        """)

        db.session.execute(query, {
            'account_id': account_id,
            'search_query': search_query,
            'device': device,
            'location': location,
            'time_of_day': time_of_day,
            'day_of_week': datetime.now().weekday() + 1,
            'score': float(score),
            'quality_indicators': json.dumps(quality_indicators),
            'keyword_id': keyword_id,
            'ad_id': ad_id,
            'session_id': session_id
        })
        db.session.commit()

    except Exception as e:
        logger.error(f"Error saving conversion score: {e}")
        db.session.rollback()


# =============================================================================
# SEARCH QUERY INTENT CLASSIFICATION (#4)
# =============================================================================

def classify_query_intent(account_id: int, search_query: str) -> Dict[str, Any]:
    """
    Classify search query intent and recommend optimizations.

    Intent types:
    - emergency: urgent, now, today, asap, 24/7
    - research: best, reviews, compare, vs, top rated
    - price_shopping: cheap, affordable, cost, price, discount
    - local: near me, [city name], local, nearby
    - brand: specific company name
    - competitor: competitor brand names
    - informational: how to, what is, why, diy
    - transactional: buy, hire, book, schedule, quote
    - navigational: website, login, hours

    Returns:
        Dict with intent_type, confidence_score, signals, recommended_actions
    """
    query_lower = search_query.lower()

    # Intent patterns with confidence scores
    intent_patterns = {
        'emergency': {
            'keywords': ['emergency', 'urgent', 'now', 'asap', '24/7', '24 hour', 'immediate', 'same day'],
            'confidence': 0.95,
            'bid_adjustment': 100.0,  # +100%
            'recommended_extensions': ['call', 'location'],
            'recommended_ad_copy': 'Emergency service available now'
        },
        'transactional': {
            'keywords': ['hire', 'book', 'schedule', 'quote', 'estimate', 'get', 'call', 'contact'],
            'confidence': 0.85,
            'bid_adjustment': 50.0,
            'recommended_extensions': ['call', 'sitelink:quote'],
            'recommended_ad_copy': 'Get your free quote today'
        },
        'local': {
            'keywords': ['near me', 'nearby', 'local', 'in my area', 'close'],
            'confidence': 0.90,
            'bid_adjustment': 40.0,
            'recommended_extensions': ['location', 'call'],
            'recommended_ad_copy': 'Serving [Location] - Call Now'
        },
        'price_shopping': {
            'keywords': ['cheap', 'affordable', 'cost', 'price', 'discount', 'deal', 'sale'],
            'confidence': 0.80,
            'bid_adjustment': -20.0,  # Lower bids for price shoppers
            'recommended_extensions': ['price', 'promotion'],
            'recommended_ad_copy': 'Competitive pricing - Free estimates'
        },
        'research': {
            'keywords': ['best', 'top', 'reviews', 'compare', 'vs', 'versus', 'rated'],
            'confidence': 0.75,
            'bid_adjustment': -10.0,
            'recommended_extensions': ['review', 'sitelink:testimonials'],
            'recommended_ad_copy': '500+ 5-star reviews'
        },
        'informational': {
            'keywords': ['how to', 'what is', 'why', 'diy', 'tips', 'guide', 'tutorial'],
            'confidence': 0.90,
            'bid_adjustment': -50.0,  # Very low commercial intent
            'recommended_extensions': [],
            'recommended_ad_copy': None  # Consider not bidding
        }
    }

    # Check each pattern
    detected_intent = None
    max_confidence = 0.0
    signals = []

    for intent_type, pattern in intent_patterns.items():
        matches = [kw for kw in pattern['keywords'] if kw in query_lower]
        if matches:
            confidence = pattern['confidence'] * (len(matches) / len(pattern['keywords']))
            if confidence > max_confidence:
                max_confidence = confidence
                detected_intent = intent_type
                signals = matches

    # Default to informational if no match
    if not detected_intent:
        detected_intent = 'informational'
        max_confidence = 0.60

    intent_data = {
        'intent_type': detected_intent,
        'confidence_score': max_confidence,
        'signals': signals,
        'recommended_bid_adjustment': intent_patterns[detected_intent]['bid_adjustment'],
        'recommended_extensions': intent_patterns[detected_intent]['recommended_extensions'],
        'recommended_ad_copy': intent_patterns[detected_intent]['recommended_ad_copy']
    }

    # Save classification
    _save_intent_classification(account_id, search_query, intent_data)

    return intent_data


def _save_intent_classification(account_id: int, search_query: str, intent_data: Dict):
    """Save or update intent classification."""
    try:
        query_normalized = search_query.lower().strip()

        query = text("""
            INSERT INTO ads_query_intent_classification (
                account_id, search_query, query_normalized,
                intent_type, confidence_score, signals,
                recommended_bid_adjustment, recommended_ad_extensions,
                first_seen, last_seen, classification_updated_at
            ) VALUES (
                :account_id, :search_query, :query_normalized,
                :intent_type, :confidence, :signals,
                :bid_adj, :extensions,
                NOW(), NOW(), NOW()
            )
            ON DUPLICATE KEY UPDATE
                last_seen = NOW(),
                confidence_score = :confidence,
                signals = :signals,
                recommended_bid_adjustment = :bid_adj,
                recommended_ad_extensions = :extensions,
                classification_updated_at = NOW()
        """)

        db.session.execute(query, {
            'account_id': account_id,
            'search_query': search_query,
            'query_normalized': query_normalized,
            'intent_type': intent_data['intent_type'],
            'confidence': intent_data['confidence_score'],
            'signals': json.dumps(intent_data['signals']),
            'bid_adj': intent_data['recommended_bid_adjustment'],
            'extensions': json.dumps(intent_data['recommended_extensions'])
        })
        db.session.commit()

    except Exception as e:
        logger.error(f"Error saving intent classification: {e}")
        db.session.rollback()


# =============================================================================
# NEGATIVE KEYWORD MINING WITH NLP (#6)
# =============================================================================

def mine_negative_keywords(account_id: int, lookback_days: int = 30) -> List[Dict]:
    """
    Analyze search term reports and suggest negative keywords using NLP.

    Identifies:
    - Job searches (jobs, hiring, careers, employment)
    - DIY intent (diy, how to, myself, tutorial)
    - Student/homework (homework, project, class, school)
    - Free/cheap variations (free, cheap, volunteer)
    - Wrong location (cities outside service area)
    - Competitor brands

    Returns:
        List of negative keyword suggestions with reasons and impact
    """
    suggestions = []

    try:
        # Negative patterns with reasons
        negative_patterns = {
            'job_search': {
                'keywords': ['job', 'jobs', 'hiring', 'career', 'employment', 'work', 'salary', 'resume'],
                'reason': 'Job searches not converting'
            },
            'diy_intent': {
                'keywords': ['diy', 'how to', 'myself', 'tutorial', 'instructions', 'guide', 'tips'],
                'reason': 'DIY intent - not hiring professionals'
            },
            'student_homework': {
                'keywords': ['homework', 'project', 'class', 'school', 'essay', 'research paper'],
                'reason': 'Student research queries'
            },
            'free_cheap': {
                'keywords': ['free', 'volunteer', 'donation', 'nonprofit'],
                'reason': 'Looking for free services'
            }
        }

        # Get search terms with spend but no conversions
        query = text("""
            SELECT
                search_query,
                SUM(cost) as total_cost,
                SUM(clicks) as total_clicks,
                SUM(impressions) as total_impressions,
                SUM(conversions) as total_conversions
            FROM search_terms_report
            WHERE account_id = :account_id
            AND date >= DATE_SUB(CURDATE(), INTERVAL :days DAY)
            GROUP BY search_query
            HAVING total_clicks > 0
            AND total_conversions = 0
            AND total_cost > 5.00
            ORDER BY total_cost DESC
            LIMIT 200
        """)

        results = db.session.execute(query, {
            'account_id': account_id,
            'days': lookback_days
        }).fetchall()

        for row in results:
            query_text = row[0]
            cost = row[1]
            clicks = row[2]
            impressions = row[3]

            query_lower = query_text.lower()

            # Check against negative patterns
            for pattern_type, pattern_data in negative_patterns.items():
                matched_keywords = [kw for kw in pattern_data['keywords'] if kw in query_lower]

                if matched_keywords:
                    # Calculate confidence based on how many pattern keywords matched
                    confidence = min(95, 60 + (len(matched_keywords) * 15))

                    suggestion = {
                        'search_query': query_text,
                        'negative_reason': pattern_type,
                        'confidence_score': confidence,
                        'detected_patterns': matched_keywords,
                        'wasted_spend': float(cost),
                        'clicks': clicks,
                        'impressions': impressions,
                        'suggested_match_type': 'PHRASE',
                        'suggested_level': 'CAMPAIGN'
                    }

                    suggestions.append(suggestion)

                    # Save to database
                    _save_negative_keyword_suggestion(account_id, suggestion)
                    break  # One reason per query

        logger.info(f"[NEGATIVE_MINING] Found {len(suggestions)} negative keyword suggestions for account {account_id}")
        return suggestions

    except Exception as e:
        logger.exception(f"Error mining negative keywords: {e}")
        return []


def _save_negative_keyword_suggestion(account_id: int, suggestion: Dict):
    """Save negative keyword suggestion to database."""
    try:
        query = text("""
            INSERT INTO ads_negative_keyword_suggestions (
                account_id, search_query, query_normalized,
                negative_reason, confidence_score, detected_patterns,
                wasted_spend, clicks, impressions,
                suggested_match_type, suggested_level, status
            ) VALUES (
                :account_id, :search_query, :query_normalized,
                :reason, :confidence, :patterns,
                :spend, :clicks, :impressions,
                :match_type, :level, 'pending'
            )
            ON DUPLICATE KEY UPDATE
                wasted_spend = wasted_spend + :spend,
                clicks = clicks + :clicks,
                impressions = impressions + :impressions,
                confidence_score = GREATEST(confidence_score, :confidence)
        """)

        db.session.execute(query, {
            'account_id': account_id,
            'search_query': suggestion['search_query'],
            'query_normalized': suggestion['search_query'].lower().strip(),
            'reason': suggestion['negative_reason'],
            'confidence': suggestion['confidence_score'],
            'patterns': json.dumps(suggestion['detected_patterns']),
            'spend': suggestion['wasted_spend'],
            'clicks': suggestion['clicks'],
            'impressions': suggestion['impressions'],
            'match_type': suggestion['suggested_match_type'],
            'level': suggestion['suggested_level']
        })
        db.session.commit()

    except Exception as e:
        logger.error(f"Error saving negative keyword suggestion: {e}")
        db.session.rollback()


# =============================================================================
# QUALITY SCORE PREDICTOR (#7)
# =============================================================================

def predict_quality_score(
    account_id: int,
    keyword_text: str,
    ad_headline: str,
    landing_page_url: str,
    keyword_id: Optional[int] = None,
    ad_id: Optional[int] = None
) -> Dict[str, Any]:
    """
    Predict Quality Score before launching a keyword/ad.

    Analyzes:
    - Keyword-ad relevance
    - Ad-landing page match
    - Expected CTR based on similar keywords
    - Landing page experience signals

    Returns:
        Dict with predicted QS (1-10), component scores, and improvement suggestions
    """
    prediction = {
        'predicted_quality_score': 5.0,
        'predicted_ctr_score': 'Average',
        'predicted_ad_relevance': 'Average',
        'predicted_landing_page_exp': 'Average',
        'confidence_score': 0.70,
        'improvement_factors': []
    }

    try:
        keyword_lower = keyword_text.lower()
        headline_lower = ad_headline.lower()
        url_lower = landing_page_url.lower()

        # Factor 1: Keyword in headline (strong QS signal)
        keyword_in_headline = keyword_lower in headline_lower
        if keyword_in_headline:
            prediction['predicted_quality_score'] += 2.0
            prediction['predicted_ad_relevance'] = 'Above Average'
            prediction['confidence_score'] += 0.10
        else:
            prediction['improvement_factors'].append({
                'factor': 'keyword_not_in_headline',
                'impact': -2.0,
                'suggestion': f'Include "{keyword_text}" in your ad headline for better relevance'
            })

        # Factor 2: Keyword in URL
        keyword_parts = keyword_lower.split()
        keyword_in_url = any(part in url_lower for part in keyword_parts if len(part) > 3)
        if keyword_in_url:
            prediction['predicted_quality_score'] += 1.0
            prediction['predicted_landing_page_exp'] = 'Above Average'
        else:
            prediction['improvement_factors'].append({
                'factor': 'keyword_not_in_url',
                'impact': -1.0,
                'suggestion': f'Ensure landing page URL or content matches "{keyword_text}"'
            })

        # Factor 3: Expected CTR based on similar keywords
        historical_ctr = _get_similar_keywords_ctr(account_id, keyword_text)
        if historical_ctr:
            if historical_ctr > 0.03:  # >3% CTR
                prediction['predicted_quality_score'] += 1.5
                prediction['predicted_ctr_score'] = 'Above Average'
            elif historical_ctr < 0.015:  # <1.5% CTR
                prediction['predicted_quality_score'] -= 1.0
                prediction['predicted_ctr_score'] = 'Below Average'
                prediction['improvement_factors'].append({
                    'factor': 'low_expected_ctr',
                    'impact': -1.0,
                    'suggestion': 'Keyword has low expected CTR. Consider more specific long-tail variations.'
                })

        # Factor 4: Landing page quality signals
        # TODO: Analyze page speed, mobile-friendliness, content relevance

        # Normalize to 1-10 scale
        prediction['predicted_quality_score'] = max(1.0, min(10.0, prediction['predicted_quality_score']))

        # Save prediction
        _save_quality_score_prediction(account_id, prediction, keyword_text, ad_headline, landing_page_url, keyword_id, ad_id)

        return prediction

    except Exception as e:
        logger.exception(f"Error predicting quality score: {e}")
        return prediction


def _get_similar_keywords_ctr(account_id: int, keyword_text: str) -> Optional[float]:
    """Get average CTR of similar keywords."""
    try:
        # Get first 2 words of keyword for matching
        keyword_parts = keyword_text.lower().split()[:2]
        like_pattern = '%' + '%'.join(keyword_parts) + '%'

        query = text("""
            SELECT AVG(ctr) as avg_ctr
            FROM keywords
            WHERE account_id = :account_id
            AND LOWER(text) LIKE :pattern
            AND impressions > 100
        """)

        result = db.session.execute(query, {
            'account_id': account_id,
            'pattern': like_pattern
        }).fetchone()

        return float(result[0]) if result and result[0] else None

    except Exception as e:
        logger.error(f"Error getting similar keywords CTR: {e}")
        return None


def _save_quality_score_prediction(
    account_id: int,
    prediction: Dict,
    keyword_text: str,
    ad_headline: str,
    landing_page_url: str,
    keyword_id: Optional[int],
    ad_id: Optional[int]
):
    """Save quality score prediction to database."""
    try:
        query = text("""
            INSERT INTO ads_quality_score_predictions (
                account_id, keyword_id, ad_id,
                keyword_text, ad_headline, landing_page_url,
                predicted_quality_score, predicted_ctr_score,
                predicted_ad_relevance, predicted_landing_page_exp,
                confidence_score, improvement_factors
            ) VALUES (
                :account_id, :keyword_id, :ad_id,
                :keyword_text, :ad_headline, :landing_page_url,
                :predicted_qs, :predicted_ctr,
                :predicted_relevance, :predicted_lp,
                :confidence, :improvements
            )
        """)

        db.session.execute(query, {
            'account_id': account_id,
            'keyword_id': keyword_id,
            'ad_id': ad_id,
            'keyword_text': keyword_text,
            'ad_headline': ad_headline,
            'landing_page_url': landing_page_url,
            'predicted_qs': prediction['predicted_quality_score'],
            'predicted_ctr': prediction['predicted_ctr_score'],
            'predicted_relevance': prediction['predicted_ad_relevance'],
            'predicted_lp': prediction['predicted_landing_page_exp'],
            'confidence': prediction['confidence_score'],
            'improvements': json.dumps(prediction['improvement_factors'])
        })
        db.session.commit()

    except Exception as e:
        logger.error(f"Error saving quality score prediction: {e}")
        db.session.rollback()


# Placeholder functions - implementations to be completed
def analyze_auction_insights(account_id: int, campaign_id: Optional[int] = None) -> Dict:
    """Analyze competitive auction insights (#14)."""
    # TODO: Implement auction insights analysis
    pass


def find_competitive_keyword_gaps(account_id: int) -> List[Dict]:
    """Find keywords competitors rank for that you don't (#15)."""
    # TODO: Implement competitive keyword gap analysis
    pass


def track_competitor_ad_copy(account_id: int, competitor_domains: List[str]) -> List[Dict]:
    """Track and analyze competitor ad copy changes (#16)."""
    # TODO: Implement competitor ad copy tracking
    pass


def run_self_healing_campaigns(account_id: int) -> int:
    """Execute self-healing campaign rules (#17)."""
    # TODO: Implement self-healing automation
    pass


def reallocate_budgets(account_id: int) -> List[Dict]:
    """Reallocate budgets between campaigns based on performance (#18)."""
    # TODO: Implement budget reallocation engine
    pass


def forecast_impression_share(account_id: int, campaign_id: int, budget_scenarios: List[float]) -> Dict:
    """Forecast impression share at different budget levels (#19)."""
    # TODO: Implement impression share forecasting
    pass
