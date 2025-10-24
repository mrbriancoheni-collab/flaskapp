# app/services/ga_insights.py
"""
Google Analytics AI Insights Service

Generates AI-powered optimization insights for Google Analytics properties using OpenAI.
Similar to google_ads_insights.py but focused on GA4 data.

Features:
- Analyzes GA4 metrics (engagement, conversions, traffic sources)
- Generates actionable recommendations
- Stores insights in database for tracking
- Supports apply/dismiss workflow
- Confidence scoring based on data quality
"""

import os
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from flask import current_app
from app import db
from app.models_ads import OptimizerRecommendation, OptimizerAction

# Configuration
HIGH_SESSIONS_THRESHOLD = int(os.environ.get('HIGH_SESSIONS_THRESHOLD', 10000))  # 10k+ sessions/week = high traffic
OPENAI_MODEL = os.environ.get('OPENAI_MODEL', 'gpt-4o-mini')
CACHE_DURATION_HOURS = 6  # Prevent redundant API calls


def should_run_daily_analysis_ga(account_id: int, weekly_sessions: int) -> bool:
    """
    Determine if GA property warrants daily analysis based on traffic volume.

    Args:
        account_id: The account ID
        weekly_sessions: Average weekly sessions

    Returns:
        True for high-traffic properties (daily analysis)
        False for standard properties (weekly analysis)
    """
    if weekly_sessions >= HIGH_SESSIONS_THRESHOLD:
        return True
    return False


def generate_ga_insights(account_id: int, property_id: str, regenerate: bool = False) -> Dict:
    """
    Generate AI-powered optimization insights for a Google Analytics property.

    Args:
        account_id: The account ID
        property_id: GA4 property ID
        regenerate: If True, ignore cache and regenerate insights

    Returns:
        Dict with insights data:
        {
            "summary": str,
            "recommendations": [...],
            "stats": {...}
        }
    """
    try:
        # Check for recent insights (unless regenerate=True)
        if not regenerate:
            recent = OptimizerRecommendation.query.filter(
                OptimizerRecommendation.account_id == account_id,
                OptimizerRecommendation.source_type == 'google_analytics',
                OptimizerRecommendation.source_id == property_id,
                OptimizerRecommendation.status == 'open',
                OptimizerRecommendation.created_at >= datetime.utcnow() - timedelta(hours=CACHE_DURATION_HOURS)
            ).first()

            if recent:
                current_app.logger.info(f"Using cached GA insights for account {account_id}, property {property_id}")
                return _format_recommendations_response(account_id, property_id)

        # Get GA data for analysis
        ga_data = get_ga_performance_data(account_id, property_id, days=30)

        if not ga_data or not ga_data.get('summary'):
            return {
                "summary": "Insufficient data available for analysis.",
                "recommendations": [],
                "stats": {"total": 0, "open": 0}
            }

        # Generate insights using OpenAI
        current_app.logger.info(f"Generating GA insights for account {account_id}, property {property_id}")
        recommendations = _call_openai_for_ga_insights(ga_data)

        # Mark old recommendations as superseded
        if regenerate:
            OptimizerRecommendation.query.filter(
                OptimizerRecommendation.account_id == account_id,
                OptimizerRecommendation.source_type == 'google_analytics',
                OptimizerRecommendation.source_id == property_id,
                OptimizerRecommendation.status == 'open'
            ).update({'status': 'superseded'})
            db.session.commit()

        # Store recommendations in database
        for rec in recommendations:
            confidence = _calculate_confidence_ga(rec, ga_data)

            db_rec = OptimizerRecommendation(
                account_id=account_id,
                source_type='google_analytics',
                source_id=property_id,
                category=rec.get('category', 'general'),
                title=rec.get('title', 'Untitled'),
                details=rec.get('description', ''),
                expected_impact=rec.get('expected_impact', 'Not specified'),
                confidence=confidence,
                severity=rec.get('severity', 4),
                data_points=json.dumps(rec.get('data_points', [])),
                action_data=json.dumps(rec.get('action', {})),
                status='open'
            )
            db.session.add(db_rec)

        db.session.commit()
        current_app.logger.info(f"Stored {len(recommendations)} GA recommendations for account {account_id}")

        return _format_recommendations_response(account_id, property_id)

    except Exception as e:
        current_app.logger.error(f"Error generating GA insights: {e}", exc_info=True)
        return {
            "summary": f"Error generating insights: {str(e)}",
            "recommendations": [],
            "stats": {"total": 0, "open": 0}
        }


def _call_openai_for_ga_insights(ga_data: Dict) -> List[Dict]:
    """
    Call OpenAI to analyze GA data and generate recommendations.

    Args:
        ga_data: Performance data from GA4

    Returns:
        List of recommendation dicts
    """
    try:
        import openai
        from app.services.ai_prompts_init import get_prompt_for_service

        api_key = os.environ.get('OPENAI_API_KEY')
        if not api_key:
            raise ValueError("OPENAI_API_KEY not configured")

        openai.api_key = api_key

        # Prepare data summary for AI
        summary = ga_data.get('summary', {})
        top_pages = ga_data.get('top_pages', [])[:10]
        top_sources = ga_data.get('top_sources', [])[:10]
        conversions = ga_data.get('conversions', [])[:5]

        # Load prompt from database
        prompt_config = get_prompt_for_service('google_analytics_main')

        if not prompt_config:
            current_app.logger.warning("Google Analytics prompt not found in database, using fallback")
            # Fallback if database prompt not available
            system_message = "You are a Google Analytics expert providing data-driven optimization recommendations in JSON format."
            model = OPENAI_MODEL
            temperature = 0.7
            max_tokens = 2000

            prompt = f"""Analyze GA4 data and provide 5-10 recommendations in JSON array format.
Sessions: {summary.get('sessions', 0)}, Users: {summary.get('users', 0)}, Engagement: {summary.get('engagement_rate', 0):.2%}
TOP PAGES: {json.dumps(top_pages, indent=2)}
Return JSON array of recommendations."""
        else:
            # Use database prompt
            system_message = prompt_config.get('system_message', '')
            model = prompt_config.get('model', 'gpt-4o-mini')
            temperature = prompt_config.get('temperature', 0.7)
            max_tokens = prompt_config.get('max_tokens', 2000)

            # Format the prompt template with actual data
            prompt = prompt_config.get('prompt_template', '').format(
                sessions=f"{summary.get('sessions', 0):,}",
                users=f"{summary.get('users', 0):,}",
                engagement_rate=f"{summary.get('engagement_rate', 0):.2%}",
                avg_session_duration=f"{summary.get('avg_session_duration', 0):.1f}",
                conversions=summary.get('conversions', 0),
                conversion_rate=f"{summary.get('conversion_rate', 0):.2%}",
                revenue=f"{summary.get('revenue', 0):,.2f}",
                top_pages=json.dumps(top_pages, indent=2),
                top_sources=json.dumps(top_sources, indent=2),
                conversions_data=json.dumps(conversions, indent=2)
            )

        response = openai.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_message},
                {"role": "user", "content": prompt}
            ],
            temperature=temperature,
            max_tokens=max_tokens
        )

        content = response.choices[0].message.content.strip()

        # Parse JSON response
        if content.startswith('```json'):
            content = content[7:]
        if content.startswith('```'):
            content = content[3:]
        if content.endswith('```'):
            content = content[:-3]
        content = content.strip()

        recommendations = json.loads(content)

        if not isinstance(recommendations, list):
            raise ValueError("OpenAI response is not a JSON array")

        return recommendations

    except json.JSONDecodeError as e:
        current_app.logger.error(f"Failed to parse OpenAI response as JSON: {e}")
        return _get_fallback_ga_recommendations(ga_data)
    except Exception as e:
        current_app.logger.error(f"OpenAI API error: {e}", exc_info=True)
        return _get_fallback_ga_recommendations(ga_data)


def _get_fallback_ga_recommendations(ga_data: Dict) -> List[Dict]:
    """
    Generate basic rule-based recommendations if OpenAI fails.

    Args:
        ga_data: Performance data

    Returns:
        List of basic recommendations
    """
    recommendations = []
    summary = ga_data.get('summary', {})

    # Low engagement rate
    engagement_rate = summary.get('engagement_rate', 0)
    if engagement_rate < 0.4:  # Below 40%
        recommendations.append({
            "title": "Improve User Engagement",
            "description": f"Your engagement rate is {engagement_rate:.1%}, below industry average of 50-60%. Review content quality, page load speed, and user experience.",
            "category": "engagement",
            "severity": 2,
            "expected_impact": "Increase engagement rate by 15-25%",
            "data_points": [f"Current engagement rate: {engagement_rate:.1%}"],
            "action": {"type": "review", "target": "content_quality"}
        })

    # Low conversion rate
    conversion_rate = summary.get('conversion_rate', 0)
    if conversion_rate < 0.02:  # Below 2%
        recommendations.append({
            "title": "Optimize Conversion Funnel",
            "description": f"Conversion rate of {conversion_rate:.2%} indicates significant drop-off. Analyze user journey, simplify forms, and add clear CTAs.",
            "category": "conversions",
            "severity": 1,
            "expected_impact": "Increase conversion rate by 20-30%",
            "data_points": [f"Current conversion rate: {conversion_rate:.2%}"],
            "action": {"type": "optimize", "target": "conversion_funnel"}
        })

    # High bounce rate on top pages
    top_pages = ga_data.get('top_pages', [])
    high_bounce_pages = [p for p in top_pages if p.get('bounce_rate', 0) > 0.6]
    if high_bounce_pages:
        recommendations.append({
            "title": "Reduce Bounce Rate on Top Pages",
            "description": f"Found {len(high_bounce_pages)} high-traffic pages with bounce rate > 60%. Improve content relevance and internal linking.",
            "category": "content",
            "severity": 3,
            "expected_impact": "Reduce bounce rate by 10-15%",
            "data_points": [f"{p['page']}: {p.get('bounce_rate', 0):.1%} bounce" for p in high_bounce_pages[:3]],
            "action": {"type": "optimize", "target": "landing_pages", "pages": [p['page'] for p in high_bounce_pages[:5]]}
        })

    return recommendations


def _calculate_confidence_ga(recommendation: Dict, ga_data: Dict) -> float:
    """
    Calculate confidence score for GA recommendation based on data quality.

    Args:
        recommendation: The recommendation dict
        ga_data: Performance data

    Returns:
        Confidence score (0.0 to 1.0)
    """
    base_confidence = 0.75
    summary = ga_data.get('summary', {})

    # Reduce confidence for low traffic
    sessions = summary.get('sessions', 0)
    if sessions < 100:
        base_confidence *= 0.5
    elif sessions < 1000:
        base_confidence *= 0.8

    # Reduce confidence for limited time range
    # (Assuming 30-day analysis in production)

    # Increase confidence for critical severity (usually data-backed)
    severity = recommendation.get('severity', 4)
    if severity == 1:
        base_confidence = min(1.0, base_confidence * 1.1)

    return round(min(1.0, max(0.0, base_confidence)), 2)


def _format_recommendations_response(account_id: int, property_id: str) -> Dict:
    """
    Format stored recommendations into response structure.

    Args:
        account_id: The account ID
        property_id: GA property ID

    Returns:
        Formatted response dict
    """
    recs = OptimizerRecommendation.query.filter(
        OptimizerRecommendation.account_id == account_id,
        OptimizerRecommendation.source_type == 'google_analytics',
        OptimizerRecommendation.source_id == property_id,
        OptimizerRecommendation.status == 'open'
    ).order_by(OptimizerRecommendation.severity.asc()).all()

    recommendations = []
    for rec in recs:
        recommendations.append({
            "id": rec.id,
            "title": rec.title,
            "description": rec.details,
            "category": rec.category,
            "severity": rec.severity,
            "expected_impact": rec.expected_impact,
            "confidence": rec.confidence,
            "data_points": json.loads(rec.data_points) if rec.data_points else [],
            "action": json.loads(rec.action_data) if rec.action_data else {}
        })

    # Generate summary
    if not recommendations:
        summary = "No significant optimization opportunities found at this time. Your GA4 property is performing well."
    else:
        critical = len([r for r in recommendations if r['severity'] == 1])
        high = len([r for r in recommendations if r['severity'] == 2])

        if critical > 0:
            summary = f"Found {critical} critical issue(s) requiring immediate attention, plus {len(recommendations) - critical} additional optimization opportunities."
        elif high > 0:
            summary = f"Identified {high} high-impact opportunity/opportunities and {len(recommendations) - high} additional recommendations to improve your GA4 performance."
        else:
            summary = f"Found {len(recommendations)} optimization opportunities to enhance your analytics performance."

    return {
        "summary": summary,
        "recommendations": recommendations,
        "stats": {
            "total": len(recommendations),
            "open": len(recommendations),
            "critical": len([r for r in recommendations if r['severity'] == 1]),
            "high_impact": len([r for r in recommendations if r['severity'] == 2]),
            "quick_wins": len([r for r in recommendations if r['severity'] == 3])
        }
    }


def get_ga_performance_data(account_id: int, property_id: str, days: int = 30) -> Dict:
    """
    Retrieve GA4 performance data for analysis.

    This is a placeholder that should integrate with your existing GA data fetching logic.

    Args:
        account_id: The account ID
        property_id: GA property ID
        days: Number of days to analyze

    Returns:
        Dict with GA performance data
    """
    # TODO: Integrate with actual GA4 data fetching from your google routes
    # For now, return sample structure

    return {
        "summary": {
            "sessions": 0,
            "users": 0,
            "engagement_rate": 0.0,
            "avg_session_duration": 0.0,
            "conversions": 0,
            "conversion_rate": 0.0,
            "revenue": 0.0
        },
        "top_pages": [],
        "top_sources": [],
        "conversions": []
    }


def apply_ga_recommendation(recommendation_id: int, user_id: int) -> Tuple[bool, str]:
    """
    Mark a GA recommendation as applied.

    Args:
        recommendation_id: The recommendation ID
        user_id: User who applied it

    Returns:
        (success, message) tuple
    """
    try:
        rec = OptimizerRecommendation.query.get(recommendation_id)

        if not rec:
            return False, "Recommendation not found"

        if rec.status != 'open':
            return False, f"Recommendation is already {rec.status}"

        # Update status
        rec.status = 'applied'

        # Record action
        action = OptimizerAction(
            recommendation_id=recommendation_id,
            applied_by=user_id,
            applied_at=datetime.utcnow(),
            action_type='applied',
            notes=None
        )
        db.session.add(action)
        db.session.commit()

        current_app.logger.info(f"GA recommendation {recommendation_id} applied by user {user_id}")
        return True, "Recommendation marked as applied"

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error applying GA recommendation: {e}", exc_info=True)
        return False, str(e)


def dismiss_ga_recommendation(recommendation_id: int, user_id: int, reason: str = None) -> Tuple[bool, str]:
    """
    Dismiss a GA recommendation.

    Args:
        recommendation_id: The recommendation ID
        user_id: User who dismissed it
        reason: Optional reason for dismissal

    Returns:
        (success, message) tuple
    """
    try:
        rec = OptimizerRecommendation.query.get(recommendation_id)

        if not rec:
            return False, "Recommendation not found"

        if rec.status != 'open':
            return False, f"Recommendation is already {rec.status}"

        # Update status
        rec.status = 'dismissed'

        # Record action
        action = OptimizerAction(
            recommendation_id=recommendation_id,
            applied_by=user_id,
            applied_at=datetime.utcnow(),
            action_type='dismissed',
            notes=reason
        )
        db.session.add(action)
        db.session.commit()

        current_app.logger.info(f"GA recommendation {recommendation_id} dismissed by user {user_id}")
        return True, "Recommendation dismissed"

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error dismissing GA recommendation: {e}", exc_info=True)
        return False, str(e)
