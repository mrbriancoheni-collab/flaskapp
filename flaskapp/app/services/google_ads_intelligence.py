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

        # Factor 5: Geographic scoring — boost if location has historically converted well
        if location:
            try:
                geo_cvr = _get_location_historical_cvr(account_id, location)
                if geo_cvr is not None:
                    if geo_cvr > 0.04:
                        score += Decimal("0.10")
                        quality_indicators.append(f"high_cvr_location_{geo_cvr:.2%}")
                    elif geo_cvr < 0.01:
                        score -= Decimal("0.05")
                        quality_indicators.append(f"low_cvr_location_{geo_cvr:.2%}")
            except Exception:
                pass

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

        # Factor 4: Landing page quality signals — basic URL + keyword presence check
        try:
            import requests as _req
            resp = _req.get(landing_page_url, timeout=5, allow_redirects=True,
                            headers={"User-Agent": "Mozilla/5.0"})
            if resp.ok:
                page_text = resp.text.lower()
                # Keyword presence in page content boosts QS prediction
                kw_in_page = any(part in page_text for part in keyword_lower.split() if len(part) > 3)
                if kw_in_page:
                    prediction['predicted_quality_score'] += 1.0
                    prediction['predicted_landing_page_exp'] = 'Above Average'
                    prediction['confidence_score'] += 0.05
                else:
                    prediction['improvement_factors'].append({
                        'factor': 'keyword_not_on_page',
                        'impact': -1.0,
                        'suggestion': f'Add "{keyword_text}" to your landing page content for better QS'
                    })
                # Check for mobile viewport tag (basic mobile-friendliness signal)
                if 'viewport' in page_text and 'width=device-width' in page_text:
                    prediction['confidence_score'] += 0.05
                else:
                    prediction['improvement_factors'].append({
                        'factor': 'no_mobile_viewport',
                        'impact': -0.5,
                        'suggestion': 'Add a mobile viewport meta tag to improve mobile experience'
                    })
        except Exception:
            pass

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


# =============================================================================
# INTERNAL HELPERS
# =============================================================================

def _get_location_historical_cvr(account_id: int, location: str) -> Optional[float]:
    """Return the historical conversion rate for a city/region string."""
    try:
        row = db.session.execute(
            text("""
                SELECT SUM(conversions) / NULLIF(SUM(clicks), 0) AS cvr
                FROM ads_conversion_scores
                WHERE account_id = :aid
                  AND location LIKE :loc
                  AND clicks > 20
            """),
            {"aid": account_id, "loc": f"%{location}%"},
        ).fetchone()
        return float(row[0]) if row and row[0] else None
    except Exception:
        return None


def _ads_gaql(account_id: int, query: str) -> List[dict]:
    """
    Execute a GAQL query for an account and return raw result rows.
    Uses resolve_ads_context + token_utils for credentials.
    """
    from app.google.utils_ads import resolve_ads_context, google_ads_search
    from app.google.token_utils import ensure_access_token

    ctx = resolve_ads_context(account_id)
    customer_id = ctx.get("customer_id")
    if not customer_id:
        raise ValueError(f"No Google Ads customer_id for account {account_id}")

    access_token, _ = ensure_access_token(account_id, ("ads",))
    return google_ads_search(
        access_token=access_token,
        customer_id=customer_id,
        query=query,
        login_customer_id=ctx.get("login_customer_id"),
        stream=True,
    )


# =============================================================================
# AUCTION INSIGHTS (#14)
# =============================================================================

def analyze_auction_insights(account_id: int, campaign_id: Optional[int] = None) -> Dict:
    """
    Pull Google Ads auction insight data to show how you compare against
    competitors on impression share, overlap rate, and position metrics.

    Returns a dict with:
      - competitors: list of {domain, impression_share, overlap_rate,
                               position_above_rate, top_is, abs_top_is, outranking_share}
      - your_impression_share: float
      - summary: narrative string
    """
    try:
        campaign_filter = f"AND campaign.id = {campaign_id}" if campaign_id else ""
        rows = _ads_gaql(account_id, f"""
            SELECT
                auction_insight.domain,
                metrics.search_impression_share,
                metrics.search_overlap_rate,
                metrics.search_position_above_rate,
                metrics.search_top_impression_share,
                metrics.search_absolute_top_impression_share,
                metrics.search_outranking_share
            FROM auction_insight
            WHERE segments.date DURING LAST_30_DAYS
              {campaign_filter}
            ORDER BY metrics.search_impression_share DESC
            LIMIT 25
        """)

        competitors = []
        for row in rows:
            ai = row.get("auctionInsight", {})
            m = row.get("metrics", {})
            domain = ai.get("domain", "")
            if not domain:
                continue
            competitors.append({
                "domain": domain,
                "impression_share": round(float(m.get("searchImpressionShare") or 0), 3),
                "overlap_rate": round(float(m.get("searchOverlapRate") or 0), 3),
                "position_above_rate": round(float(m.get("searchPositionAboveRate") or 0), 3),
                "top_impression_share": round(float(m.get("searchTopImpressionShare") or 0), 3),
                "abs_top_impression_share": round(float(m.get("searchAbsoluteTopImpressionShare") or 0), 3),
                "outranking_share": round(float(m.get("searchOutrankingShare") or 0), 3),
            })

        top = competitors[0] if competitors else {}
        summary = (
            f"Your top competitor is {top.get('domain', 'unknown')} "
            f"with {top.get('impression_share', 0)*100:.0f}% impression share "
            f"and {top.get('outranking_share', 0)*100:.0f}% outranking rate."
        ) if top else "No auction insight data available."

        return {
            "competitors": competitors,
            "summary": summary,
            "fetched_at": datetime.utcnow().isoformat(),
        }

    except Exception as e:
        logger.exception("analyze_auction_insights failed account=%s: %s", account_id, e)
        return {"competitors": [], "summary": "Could not fetch auction insights.", "error": str(e)}


# =============================================================================
# COMPETITIVE KEYWORD GAPS (#15)
# =============================================================================

def find_competitive_keyword_gaps(account_id: int) -> List[Dict]:
    """
    Identify campaigns/keywords where impression share is low due to rank
    (not budget), meaning competitors are outbidding or outscoring us.
    Also surfaces search terms with clicks but no conversion as expansion gaps.

    Returns a list of gap opportunities with suggested actions.
    """
    gaps = []
    try:
        # 1. Campaign-level impression share gaps (rank-lost IS > 20%)
        rows = _ads_gaql(account_id, """
            SELECT
                campaign.id,
                campaign.name,
                metrics.search_impression_share,
                metrics.search_rank_lost_impression_share,
                metrics.search_budget_lost_impression_share,
                metrics.cost_micros,
                metrics.conversions
            FROM campaign
            WHERE campaign.status = 'ENABLED'
              AND segments.date DURING LAST_30_DAYS
            ORDER BY metrics.search_rank_lost_impression_share DESC
            LIMIT 20
        """)

        for row in rows:
            m = row.get("metrics", {})
            c = row.get("campaign", {})
            rank_lost = float(m.get("searchRankLostImpressionShare") or 0)
            budget_lost = float(m.get("searchBudgetLostImpressionShare") or 0)
            if rank_lost < 0.10:
                continue
            gaps.append({
                "type": "impression_share_gap",
                "campaign_id": c.get("id"),
                "campaign_name": c.get("name", ""),
                "impression_share": round(float(m.get("searchImpressionShare") or 0), 3),
                "rank_lost_is": round(rank_lost, 3),
                "budget_lost_is": round(budget_lost, 3),
                "cost": round(float(m.get("costMicros") or 0) / 1e6, 2),
                "conversions": round(float(m.get("conversions") or 0), 1),
                "action": "improve_quality_score_or_raise_bid",
                "opportunity": f"Recover up to {rank_lost*100:.0f}% lost IS by improving QS or bids",
            })

        # 2. High-spend search terms with no conversions (expansion/negative gaps)
        st_rows = _ads_gaql(account_id, """
            SELECT
                search_term_view.search_term,
                metrics.cost_micros,
                metrics.clicks,
                metrics.conversions,
                metrics.impressions
            FROM search_term_view
            WHERE segments.date DURING LAST_30_DAYS
              AND metrics.clicks > 5
              AND metrics.conversions < 0.5
              AND metrics.cost_micros > 2000000
            ORDER BY metrics.cost_micros DESC
            LIMIT 30
        """)

        for row in st_rows:
            m = row.get("metrics", {})
            st = row.get("searchTermView", {})
            term = st.get("searchTerm", "")
            cost = float(m.get("costMicros") or 0) / 1e6
            gaps.append({
                "type": "wasted_spend_term",
                "search_term": term,
                "cost": round(cost, 2),
                "clicks": int(m.get("clicks") or 0),
                "conversions": float(m.get("conversions") or 0),
                "action": "add_as_negative_or_create_dedicated_ad",
                "opportunity": f"${cost:.2f} spent, 0 conversions — consider negative or dedicated ad group",
            })

        logger.info("find_competitive_keyword_gaps: %d gaps for account %s", len(gaps), account_id)
        return gaps

    except Exception as e:
        logger.exception("find_competitive_keyword_gaps failed account=%s: %s", account_id, e)
        return []


# =============================================================================
# COMPETITOR AD COPY TRACKING (#16)
# =============================================================================

def track_competitor_ad_copy(account_id: int, competitor_domains: List[str]) -> List[Dict]:
    """
    Track competitive position changes for specific domains using auction insights.
    Compares stored historical data against current metrics to detect shifts.

    Returns a list of change events per competitor domain.
    """
    changes = []
    try:
        insight = analyze_auction_insights(account_id)
        competitors_now = {c["domain"]: c for c in insight.get("competitors", [])}

        # Load stored previous metrics
        prev_rows = db.session.execute(
            text("""
                SELECT domain, impression_share, outranking_share, overlap_rate, recorded_at
                FROM ads_competitor_snapshots
                WHERE account_id = :aid
                  AND recorded_at >= :since
                ORDER BY recorded_at DESC
            """),
            {"aid": account_id, "since": datetime.utcnow() - timedelta(days=8)},
        ).fetchall()

        prev = {}
        for r in prev_rows:
            if r[0] not in prev:
                prev[r[0]] = {"impression_share": float(r[1] or 0),
                               "outranking_share": float(r[2] or 0),
                               "overlap_rate": float(r[3] or 0)}

        # Detect meaningful changes (>5pp) for tracked domains
        for domain in (competitor_domains or list(competitors_now.keys())[:10]):
            current = competitors_now.get(domain)
            if not current:
                continue
            historic = prev.get(domain)
            if historic:
                is_delta = current["impression_share"] - historic["impression_share"]
                or_delta = current["outranking_share"] - historic["outranking_share"]
                if abs(is_delta) >= 0.05 or abs(or_delta) >= 0.05:
                    changes.append({
                        "domain": domain,
                        "impression_share_change": round(is_delta, 3),
                        "outranking_share_change": round(or_delta, 3),
                        "current_impression_share": current["impression_share"],
                        "current_outranking_share": current["outranking_share"],
                        "insight": (
                            f"{domain} {'gained' if is_delta > 0 else 'lost'} "
                            f"{abs(is_delta)*100:.0f}pp impression share vs last week."
                        ),
                    })

        # Persist current snapshot
        try:
            for domain, metrics in competitors_now.items():
                db.session.execute(
                    text("""
                        INSERT INTO ads_competitor_snapshots
                          (account_id, domain, impression_share, outranking_share,
                           overlap_rate, recorded_at)
                        VALUES (:aid, :domain, :is_, :os_, :ol_, NOW())
                    """),
                    {
                        "aid": account_id,
                        "domain": domain,
                        "is_": metrics["impression_share"],
                        "os_": metrics["outranking_share"],
                        "ol_": metrics["overlap_rate"],
                    },
                )
            db.session.commit()
        except Exception:
            db.session.rollback()

        return changes

    except Exception as e:
        logger.exception("track_competitor_ad_copy failed account=%s: %s", account_id, e)
        return []


# =============================================================================
# SELF-HEALING CAMPAIGNS (#17)
# =============================================================================

def run_self_healing_campaigns(account_id: int, dry_run: bool = True) -> Dict:
    """
    Apply automated rules to fix underperforming campaigns:
    - Pause keywords with QS <= 2 and no conversions in 30 days
    - Flag campaigns with CPA > 3x target for budget review
    - Recommend enabling responsive search ads for ad groups with only one ad

    dry_run=True (default): returns a plan without making API mutations.
    dry_run=False: applies changes via Google Ads mutate API.

    Returns {'total_changes': N, 'actions': [...], 'dry_run': bool}
    """
    actions = []
    try:
        from app.models_ads import AdsAccountGoal
        goal = AdsAccountGoal.query.filter_by(account_id=account_id).first()
        target_cpa = (goal.target_cpa_cents / 100.0) if goal and goal.target_cpa_cents else 50.0

        # 1. Low QS keywords with no conversions
        kw_rows = _ads_gaql(account_id, """
            SELECT
                ad_group_criterion.criterion_id,
                ad_group_criterion.keyword.text,
                ad_group_criterion.quality_info.quality_score,
                ad_group.id,
                campaign.id,
                campaign.name,
                metrics.cost_micros,
                metrics.conversions
            FROM ad_group_criterion
            WHERE ad_group_criterion.type = 'KEYWORD'
              AND ad_group_criterion.status = 'ENABLED'
              AND ad_group_criterion.quality_info.quality_score <= 2
              AND segments.date DURING LAST_30_DAYS
              AND metrics.cost_micros > 1000000
            ORDER BY metrics.cost_micros DESC
            LIMIT 50
        """)

        for row in kw_rows:
            kw = row.get("adGroupCriterion", {})
            m = row.get("metrics", {})
            if float(m.get("conversions") or 0) > 0:
                continue
            criterion_id = kw.get("criterionId")
            ad_group_id = (row.get("adGroup") or {}).get("id")
            campaign_name = (row.get("campaign") or {}).get("name", "")
            cost = float(m.get("costMicros") or 0) / 1e6
            action = {
                "type": "pause_keyword",
                "criterion_id": criterion_id,
                "ad_group_id": ad_group_id,
                "keyword_text": (kw.get("keyword") or {}).get("text", ""),
                "quality_score": kw.get("qualityInfo", {}).get("qualityScore"),
                "cost_wasted": round(cost, 2),
                "campaign": campaign_name,
                "reason": "QS ≤ 2 with zero conversions",
            }
            actions.append(action)

            if not dry_run and criterion_id and ad_group_id:
                _pause_keyword(account_id, ad_group_id, criterion_id)

        # 2. High-CPA campaigns (> 3x target) — flag for budget cut
        camp_rows = _ads_gaql(account_id, """
            SELECT
                campaign.id,
                campaign.name,
                campaign_budget.amount_micros,
                metrics.cost_micros,
                metrics.conversions
            FROM campaign
            WHERE campaign.status = 'ENABLED'
              AND segments.date DURING LAST_30_DAYS
              AND metrics.cost_micros > 5000000
            ORDER BY metrics.cost_micros DESC
            LIMIT 20
        """)

        for row in camp_rows:
            m = row.get("metrics", {})
            c = row.get("campaign", {})
            cost = float(m.get("costMicros") or 0) / 1e6
            convs = float(m.get("conversions") or 0)
            if convs < 1:
                continue
            cpa = cost / convs
            if cpa > target_cpa * 3:
                actions.append({
                    "type": "flag_high_cpa_campaign",
                    "campaign_id": c.get("id"),
                    "campaign_name": c.get("name", ""),
                    "actual_cpa": round(cpa, 2),
                    "target_cpa": target_cpa,
                    "overage_pct": round((cpa / target_cpa - 1) * 100, 0),
                    "reason": f"CPA ${cpa:.2f} is {cpa/target_cpa:.1f}x target (${target_cpa})",
                    "recommendation": "Reduce daily budget by 20% or pause underperforming ad groups",
                })

        logger.info(
            "run_self_healing_campaigns account=%s dry_run=%s actions=%d",
            account_id, dry_run, len(actions),
        )
        return {"total_changes": len(actions), "actions": actions, "dry_run": dry_run}

    except Exception as e:
        logger.exception("run_self_healing_campaigns failed account=%s: %s", account_id, e)
        return {"total_changes": 0, "actions": [], "dry_run": dry_run, "error": str(e)}


def _pause_keyword(account_id: int, ad_group_id: str, criterion_id: str) -> None:
    """Mutate a keyword status to PAUSED via the Google Ads REST API."""
    from app.google.utils_ads import resolve_ads_context, ads_headers, _get_ads_api_base
    from app.google.token_utils import ensure_access_token
    import requests as _req

    ctx = resolve_ads_context(account_id)
    customer_id = ctx["customer_id"]
    access_token, _ = ensure_access_token(account_id, ("ads",))
    headers = ads_headers(access_token, ctx.get("login_customer_id"))

    resource_name = f"customers/{customer_id}/adGroupCriteria/{ad_group_id}~{criterion_id}"
    body = {
        "operations": [{
            "update_mask": "status",
            "update": {
                "resource_name": resource_name,
                "status": "PAUSED",
            },
        }],
    }
    url = f"{_get_ads_api_base()}/customers/{customer_id}/adGroupCriteria:mutate"
    resp = _req.post(url, headers=headers, json=body, timeout=30)
    resp.raise_for_status()
    logger.info("paused keyword criterion_id=%s ad_group_id=%s", criterion_id, ad_group_id)


# =============================================================================
# BUDGET REALLOCATION (#18)
# =============================================================================

def reallocate_budgets(account_id: int, dry_run: bool = True) -> List[Dict]:
    """
    Identify campaigns that are budget-constrained with good CPA and
    recommend shifting spend from poor performers.

    Returns a list of reallocation dicts: {from_campaign, to_campaign,
    amount_dollars, reason}.
    """
    reallocations = []
    try:
        from app.models_ads import AdsAccountGoal
        goal = AdsAccountGoal.query.filter_by(account_id=account_id).first()
        target_cpa = (goal.target_cpa_cents / 100.0) if goal and goal.target_cpa_cents else 50.0

        rows = _ads_gaql(account_id, """
            SELECT
                campaign.id,
                campaign.name,
                campaign_budget.amount_micros,
                metrics.cost_micros,
                metrics.conversions,
                metrics.search_budget_lost_impression_share
            FROM campaign
            WHERE campaign.status = 'ENABLED'
              AND segments.date DURING LAST_30_DAYS
              AND metrics.clicks > 10
            ORDER BY metrics.cost_micros DESC
            LIMIT 30
        """)

        good = []   # on-target CPA, budget-constrained
        poor = []   # over-target CPA

        for row in rows:
            m = row.get("metrics", {})
            c = row.get("campaign", {})
            cost = float(m.get("costMicros") or 0) / 1e6
            convs = float(m.get("conversions") or 0)
            budget = float((row.get("campaignBudget") or {}).get("amountMicros") or 0) / 1e6
            budget_lost = float(m.get("searchBudgetLostImpressionShare") or 0)
            cpa = cost / convs if convs > 0 else None

            entry = {
                "campaign_id": c.get("id"),
                "name": c.get("name", ""),
                "cost": cost,
                "budget": budget,
                "cpa": cpa,
                "budget_lost_is": budget_lost,
            }

            if cpa and cpa <= target_cpa and budget_lost >= 0.15:
                good.append(entry)   # constrained winner — give more budget
            elif cpa and cpa > target_cpa * 2:
                poor.append(entry)   # over-spending loser — take budget

        transfer = min(len(good), len(poor))
        for i in range(transfer):
            donor = poor[i]
            recipient = good[i]
            shift = round(donor["budget"] * 0.20, 2)  # move 20% of donor budget
            reallocations.append({
                "from_campaign": donor["name"],
                "from_campaign_id": donor["campaign_id"],
                "to_campaign": recipient["name"],
                "to_campaign_id": recipient["campaign_id"],
                "amount_dollars": shift,
                "reason": (
                    f"Move ${shift} from '{donor['name']}' (CPA ${donor['cpa']:.2f}) "
                    f"to '{recipient['name']}' (CPA ${recipient['cpa']:.2f}, "
                    f"{recipient['budget_lost_is']*100:.0f}% budget-limited)"
                ),
                "dry_run": dry_run,
            })

        logger.info("reallocate_budgets account=%s %d reallocation(s)", account_id, len(reallocations))
        return reallocations

    except Exception as e:
        logger.exception("reallocate_budgets failed account=%s: %s", account_id, e)
        return []


# =============================================================================
# IMPRESSION SHARE FORECASTING (#19)
# =============================================================================

def forecast_impression_share(
    account_id: int, campaign_id: int, budget_scenarios: List[float]
) -> Dict:
    """
    Forecast impression share at different daily budget levels.

    Uses current IS, budget-lost IS, and a diminishing-returns model:
      IS_new ≈ IS_current + budget_lost_IS * (1 - exp(-k * budget_increase_pct))

    Returns:
      {
        'current_budget': float,
        'current_is': float,
        'max_recoverable_is': float,
        'scenarios': [{'budget': X, 'forecasted_is': Y, 'is_gain': Z}, ...]
      }
    """
    try:
        rows = _ads_gaql(account_id, f"""
            SELECT
                campaign_budget.amount_micros,
                metrics.search_impression_share,
                metrics.search_budget_lost_impression_share,
                metrics.search_rank_lost_impression_share
            FROM campaign
            WHERE campaign.id = {campaign_id}
              AND segments.date DURING LAST_30_DAYS
            LIMIT 1
        """)

        if not rows:
            return {"error": "No data for campaign", "scenarios": []}

        m = rows[0].get("metrics", {})
        budget_row = rows[0].get("campaignBudget", {})

        current_budget = float(budget_row.get("amountMicros") or 0) / 1e6
        current_is = float(m.get("searchImpressionShare") or 0)
        budget_lost_is = float(m.get("searchBudgetLostImpressionShare") or 0)
        rank_lost_is = float(m.get("searchRankLostImpressionShare") or 0)

        # Maximum IS we can recover via budget (rank-lost requires QS/bid work)
        max_recoverable = min(1.0, current_is + budget_lost_is)

        import math
        scenarios = []
        for new_budget in sorted(budget_scenarios):
            if current_budget <= 0:
                forecasted_is = current_is
            else:
                pct_increase = (new_budget - current_budget) / current_budget
                # Diminishing returns: k=0.7 gives ~50% of recoverable IS at 100% budget increase
                k = 0.7
                is_gain = budget_lost_is * (1 - math.exp(-k * max(0, pct_increase)))
                forecasted_is = min(max_recoverable, current_is + is_gain)

            scenarios.append({
                "budget": round(new_budget, 2),
                "forecasted_is": round(forecasted_is, 3),
                "is_gain": round(max(0, forecasted_is - current_is), 3),
                "pct_gain": round(max(0, (forecasted_is - current_is) * 100), 1),
            })

        return {
            "campaign_id": campaign_id,
            "current_budget": round(current_budget, 2),
            "current_is": round(current_is, 3),
            "budget_lost_is": round(budget_lost_is, 3),
            "rank_lost_is": round(rank_lost_is, 3),
            "max_recoverable_is": round(max_recoverable, 3),
            "scenarios": scenarios,
        }

    except Exception as e:
        logger.exception("forecast_impression_share failed account=%s campaign=%s: %s",
                         account_id, campaign_id, e)
        return {"error": str(e), "scenarios": []}
