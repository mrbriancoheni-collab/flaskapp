# app/services/gsc_insights.py
"""
Google Search Console AI Insights Service

Generates AI-powered SEO optimization insights for Google Search Console properties using OpenAI.
Similar to ga_insights.py but focused on GSC/SEO data.

Features:
- Analyzes GSC metrics (clicks, impressions, CTR, position)
- Generates actionable SEO recommendations
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
HIGH_CLICKS_THRESHOLD = int(os.environ.get('HIGH_CLICKS_THRESHOLD', 5000))  # 5k+ clicks/week = high traffic
OPENAI_MODEL = os.environ.get('OPENAI_MODEL', 'gpt-4o-mini')
CACHE_DURATION_HOURS = 6  # Prevent redundant API calls


def should_run_daily_analysis_gsc(account_id: int, weekly_clicks: int) -> bool:
    """
    Determine if GSC property warrants daily analysis based on traffic volume.

    Args:
        account_id: The account ID
        weekly_clicks: Average weekly clicks

    Returns:
        True for high-traffic properties (daily analysis)
        False for standard properties (weekly analysis)
    """
    if weekly_clicks >= HIGH_CLICKS_THRESHOLD:
        return True
    return False


def generate_gsc_insights(account_id: int, site_url: str, regenerate: bool = False) -> Dict:
    """
    Generate AI-powered SEO insights for a Google Search Console property.

    Args:
        account_id: The account ID
        site_url: GSC site URL
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
                OptimizerRecommendation.source_type == 'search_console',
                OptimizerRecommendation.source_id == site_url,
                OptimizerRecommendation.status == 'open',
                OptimizerRecommendation.created_at >= datetime.utcnow() - timedelta(hours=CACHE_DURATION_HOURS)
            ).first()

            if recent:
                current_app.logger.info(f"Using cached GSC insights for account {account_id}, site {site_url}")
                return _format_recommendations_response(account_id, site_url)

        # Get GSC data for analysis
        gsc_data = get_gsc_performance_data(account_id, site_url, days=30)

        if not gsc_data or not gsc_data.get('summary'):
            return {
                "summary": "Insufficient data available for analysis.",
                "recommendations": [],
                "stats": {"total": 0, "open": 0}
            }

        # Generate insights using OpenAI
        current_app.logger.info(f"Generating GSC insights for account {account_id}, site {site_url}")
        recommendations = _call_openai_for_gsc_insights(gsc_data)

        # Mark old recommendations as superseded
        if regenerate:
            OptimizerRecommendation.query.filter(
                OptimizerRecommendation.account_id == account_id,
                OptimizerRecommendation.source_type == 'search_console',
                OptimizerRecommendation.source_id == site_url,
                OptimizerRecommendation.status == 'open'
            ).update({'status': 'superseded'})
            db.session.commit()

        # Store recommendations in database
        for rec in recommendations:
            confidence = _calculate_confidence_gsc(rec, gsc_data)

            db_rec = OptimizerRecommendation(
                account_id=account_id,
                source_type='search_console',
                source_id=site_url,
                category=rec.get('category', 'seo'),
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
        current_app.logger.info(f"Stored {len(recommendations)} GSC recommendations for account {account_id}")

        return _format_recommendations_response(account_id, site_url)

    except Exception as e:
        current_app.logger.error(f"Error generating GSC insights: {e}", exc_info=True)
        return {
            "summary": f"Error generating insights: {str(e)}",
            "recommendations": [],
            "stats": {"total": 0, "open": 0}
        }


def _call_openai_for_gsc_insights(gsc_data: Dict) -> List[Dict]:
    """
    Call OpenAI to analyze GSC data and generate SEO recommendations.

    Args:
        gsc_data: Performance data from GSC

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
        summary = gsc_data.get('summary', {})
        top_pages = gsc_data.get('top_pages', [])[:10]
        top_queries = gsc_data.get('top_queries', [])[:15]
        low_ctr_queries = gsc_data.get('low_ctr_queries', [])[:10]

        # Load prompt from database
        prompt_config = get_prompt_for_service('search_console_main')

        if not prompt_config:
            current_app.logger.warning("Search Console prompt not found in database, using fallback")
            # Fallback if database prompt not available
            system_message = "You are an SEO expert providing data-driven optimization recommendations in JSON format."
            model = OPENAI_MODEL
            temperature = 0.7
            max_tokens = 2000

            prompt = f"""Analyze GSC data and provide 5-10 SEO recommendations in JSON array format.
Clicks: {summary.get('clicks', 0)}, Impressions: {summary.get('impressions', 0)}, CTR: {summary.get('avg_ctr', 0):.2%}
TOP QUERIES: {json.dumps(top_queries, indent=2)}
Return JSON array of recommendations."""
        else:
            # Use database prompt
            system_message = prompt_config.get('system_message', '')
            model = prompt_config.get('model', 'gpt-4o-mini')
            temperature = prompt_config.get('temperature', 0.7)
            max_tokens = prompt_config.get('max_tokens', 2000)

            # Format the prompt template with actual data
            prompt = prompt_config.get('prompt_template', '').format(
                clicks=f"{summary.get('clicks', 0):,}",
                impressions=f"{summary.get('impressions', 0):,}",
                avg_ctr=f"{summary.get('avg_ctr', 0):.2%}",
                avg_position=f"{summary.get('avg_position', 0):.1f}",
                top_pages=json.dumps(top_pages, indent=2),
                top_queries=json.dumps(top_queries, indent=2),
                low_ctr_queries=json.dumps(low_ctr_queries, indent=2)
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
        return _get_fallback_gsc_recommendations(gsc_data)
    except Exception as e:
        current_app.logger.error(f"OpenAI API error: {e}", exc_info=True)
        return _get_fallback_gsc_recommendations(gsc_data)


def _get_fallback_gsc_recommendations(gsc_data: Dict) -> List[Dict]:
    """
    Generate basic rule-based SEO recommendations if OpenAI fails.

    Args:
        gsc_data: Performance data

    Returns:
        List of basic recommendations
    """
    recommendations = []
    summary = gsc_data.get('summary', {})

    # Low CTR
    avg_ctr = summary.get('avg_ctr', 0)
    if avg_ctr < 0.02:  # Below 2%
        recommendations.append({
            "title": "Improve Meta Titles and Descriptions",
            "description": f"Your average CTR is {avg_ctr:.2%}, below the typical 3-5% benchmark. Optimize meta titles and descriptions to be more compelling.",
            "category": "ctr_optimization",
            "severity": 2,
            "expected_impact": "Increase CTR by 30-50%",
            "data_points": [f"Current avg CTR: {avg_ctr:.2%}"],
            "action": {"type": "optimize", "target": "meta_tags"}
        })

    # Poor average position
    avg_position = summary.get('avg_position', 0)
    if avg_position > 10:  # Not on first page
        recommendations.append({
            "title": "Improve Content Quality for Better Rankings",
            "description": f"Average position of {avg_position:.1f} indicates most content is not ranking on page 1. Focus on content depth, relevance, and backlinks.",
            "category": "rankings",
            "severity": 1,
            "expected_impact": "Improve average position by 3-5 spots",
            "data_points": [f"Current avg position: {avg_position:.1f}"],
            "action": {"type": "optimize", "target": "content_quality"}
        })

    # Low CTR queries
    low_ctr_queries = gsc_data.get('low_ctr_queries', [])
    if low_ctr_queries:
        recommendations.append({
            "title": "Optimize High-Impression, Low-CTR Queries",
            "description": f"Found {len(low_ctr_queries)} queries with high impressions but low clicks. These are quick wins for traffic growth.",
            "category": "keywords",
            "severity": 3,
            "expected_impact": "Increase clicks by 20-30%",
            "data_points": [f"{q['query']}: {q.get('impressions', 0)} impr, {q.get('ctr', 0):.2%} CTR" for q in low_ctr_queries[:3]],
            "action": {"type": "optimize", "target": "meta_descriptions", "queries": [q['query'] for q in low_ctr_queries[:10]]}
        })

    # Pages ranking 4-10
    top_pages = gsc_data.get('top_pages', [])
    page_2_pages = [p for p in top_pages if 4 <= p.get('position', 0) <= 10]
    if page_2_pages:
        recommendations.append({
            "title": "Push Page 2 Rankings to Page 1",
            "description": f"Found {len(page_2_pages)} pages ranking 4-10. Small content improvements can move these to page 1.",
            "category": "content",
            "severity": 3,
            "expected_impact": "Double traffic for improved pages",
            "data_points": [f"{p['page']}: Position {p.get('position', 0):.1f}" for p in page_2_pages[:3]],
            "action": {"type": "optimize", "target": "content", "pages": [p['page'] for p in page_2_pages[:5]]}
        })

    return recommendations


def _calculate_confidence_gsc(recommendation: Dict, gsc_data: Dict) -> float:
    """
    Calculate confidence score for GSC recommendation based on data quality.

    Args:
        recommendation: The recommendation dict
        gsc_data: Performance data

    Returns:
        Confidence score (0.0 to 1.0)
    """
    base_confidence = 0.75
    summary = gsc_data.get('summary', {})

    # Reduce confidence for low traffic
    clicks = summary.get('clicks', 0)
    if clicks < 50:
        base_confidence *= 0.5
    elif clicks < 500:
        base_confidence *= 0.8

    # Reduce confidence for limited impressions
    impressions = summary.get('impressions', 0)
    if impressions < 1000:
        base_confidence *= 0.7

    # Increase confidence for critical severity (usually data-backed)
    severity = recommendation.get('severity', 4)
    if severity == 1:
        base_confidence = min(1.0, base_confidence * 1.1)

    return round(min(1.0, max(0.0, base_confidence)), 2)


def _format_recommendations_response(account_id: int, site_url: str) -> Dict:
    """
    Format stored recommendations into response structure.

    Args:
        account_id: The account ID
        site_url: GSC site URL

    Returns:
        Formatted response dict
    """
    recs = OptimizerRecommendation.query.filter(
        OptimizerRecommendation.account_id == account_id,
        OptimizerRecommendation.source_type == 'search_console',
        OptimizerRecommendation.source_id == site_url,
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
        summary = "No significant SEO opportunities found at this time. Your site is performing well in search."
    else:
        critical = len([r for r in recommendations if r['severity'] == 1])
        high = len([r for r in recommendations if r['severity'] == 2])

        if critical > 0:
            summary = f"Found {critical} critical SEO issue(s) requiring immediate attention, plus {len(recommendations) - critical} additional optimization opportunities."
        elif high > 0:
            summary = f"Identified {high} high-impact SEO opportunity/opportunities and {len(recommendations) - high} additional recommendations to improve your search performance."
        else:
            summary = f"Found {len(recommendations)} SEO optimization opportunities to boost your organic traffic."

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


def get_gsc_performance_data(account_id: int, site_url: str, days: int = 30) -> Dict:
    """
    Retrieve GSC performance data for analysis.

    This is a placeholder that should integrate with your existing GSC data fetching logic.

    Args:
        account_id: The account ID
        site_url: GSC site URL
        days: Number of days to analyze

    Returns:
        Dict with GSC performance data
    """
    # TODO: Integrate with actual GSC data fetching from your google routes
    # For now, return sample structure

    return {
        "summary": {
            "clicks": 0,
            "impressions": 0,
            "avg_ctr": 0.0,
            "avg_position": 0.0
        },
        "top_pages": [],
        "top_queries": [],
        "low_ctr_queries": []
    }


def apply_gsc_recommendation(recommendation_id: int, user_id: int) -> Tuple[bool, str]:
    """
    Mark a GSC recommendation as applied.

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

        current_app.logger.info(f"GSC recommendation {recommendation_id} applied by user {user_id}")
        return True, "Recommendation marked as applied"

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error applying GSC recommendation: {e}", exc_info=True)
        return False, str(e)


def dismiss_gsc_recommendation(recommendation_id: int, user_id: int, reason: str = None) -> Tuple[bool, str]:
    """
    Dismiss a GSC recommendation.

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

        current_app.logger.info(f"GSC recommendation {recommendation_id} dismissed by user {user_id}")
        return True, "Recommendation dismissed"

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error dismissing GSC recommendation: {e}", exc_info=True)
        return False, str(e)
