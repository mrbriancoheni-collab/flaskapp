# app/services/glsa_insights.py
"""
AI-powered optimization insights for Google Local Services Ads (GLSA).
Uses OpenAI GPT models with database-stored prompts to generate recommendations.
"""

import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from flask import current_app
from openai import OpenAI

from app import db
from app.models_ads import OptimizerRecommendation, OptimizerAction

# OpenAI Configuration
OPENAI_API_KEY = None  # Set from env in generate_glsa_insights
OPENAI_MODEL = "gpt-4o-mini"


def generate_glsa_insights(
    account_id: int,
    profile_data: Dict,
    regenerate: bool = False
) -> Dict:
    """
    Generate AI-powered optimization insights for a Local Services Ads profile.

    Args:
        account_id: The account ID
        profile_data: Profile data including categories, service areas, reviews, etc.
        regenerate: If True, force regeneration even if recent insights exist

    Returns:
        Dict with summary and recommendations
    """
    # Check for recent insights (6-hour cache)
    if not regenerate:
        cutoff = datetime.utcnow() - timedelta(hours=6)
        recent = OptimizerRecommendation.query.filter(
            OptimizerRecommendation.account_id == account_id,
            OptimizerRecommendation.source_type == 'glsa',
            OptimizerRecommendation.status == 'open',
            OptimizerRecommendation.created_at >= cutoff
        ).first()

        if recent:
            current_app.logger.info(f"Using cached GLSA insights for account {account_id}")
            return _format_recommendations_response(account_id)

    # Generate new insights
    current_app.logger.info(f"Generating new GLSA insights for account {account_id}")

    try:
        # Get AI recommendations from OpenAI
        recommendations = _call_openai_for_glsa_insights(profile_data)

        # Store recommendations in database
        _store_recommendations(account_id, recommendations, profile_data)

        # Return formatted response
        return _format_recommendations_response(account_id)

    except Exception as e:
        current_app.logger.exception(f"Error generating GLSA insights: {e}")
        return {
            "ok": False,
            "error": str(e),
            "summary": "Failed to generate insights. Please try again.",
            "recommendations": []
        }


def _call_openai_for_glsa_insights(profile_data: Dict) -> List[Dict]:
    """
    Call OpenAI API to generate GLSA optimization insights using database-stored prompts.

    Args:
        profile_data: Profile data to analyze

    Returns:
        List of recommendation dictionaries
    """
    from app.services.ai_prompts_init import get_prompt_for_service

    # Load prompt from database
    prompt_config = get_prompt_for_service('glsa_main')

    if not prompt_config:
        current_app.logger.warning("GLSA prompt not found in database, using fallback")
        # Fallback to basic prompt
        system_message = "You are a Google Local Services Ads optimization expert providing data-driven recommendations in JSON format."
        model = OPENAI_MODEL
        temperature = 0.7
        max_tokens = 2000

        user_prompt = f"""Analyze this Local Services Ads profile and provide 5-10 actionable optimization recommendations.

PROFILE DATA:
{json.dumps(profile_data, indent=2)}

Return ONLY valid JSON array of recommendations with these fields:
- title: Brief action-oriented title
- description: Detailed explanation (2-3 sentences)
- category: One of [categories, service_areas, reviews, budget, profile, responsiveness]
- severity: 1=critical, 2=high-impact, 3=quick win, 4-5=long-term
- expected_impact: Specific improvement (e.g., "Increase leads by 15-20%")
- data_points: Array of supporting metrics
- action: Dict with implementation details"""
    else:
        # Use database prompt with template formatting
        system_message = prompt_config.get('system_message', '')
        model = prompt_config.get('model', 'gpt-4o-mini')
        temperature = prompt_config.get('temperature', 0.7)
        max_tokens = prompt_config.get('max_tokens', 2000)

        # Extract profile metrics
        primary_category = profile_data.get('primary_category', 'Not set')
        categories = profile_data.get('categories', [])
        categories_list = ', '.join(categories) if categories else 'None'

        service_areas = profile_data.get('service_areas', [])
        service_areas_list = ', '.join(service_areas) if service_areas else 'None'

        rating = profile_data.get('rating', 0)
        reviews_count = profile_data.get('reviews_count', 0)

        weekly_budget = profile_data.get('weekly_budget', 0)

        hours = profile_data.get('hours', 'Not specified')
        website = profile_data.get('website', 'Not set')
        phone = profile_data.get('phone', 'Not set')

        # Answers from questionnaire
        answers = profile_data.get('answers', {})
        priorities = answers.get('priorities', 'Not specified')
        priority_areas = answers.get('priority_areas', 'Not specified')
        response_time = answers.get('response_time', 'Not specified')
        after_hours = answers.get('after_hours', 'Not specified')
        lead_goal = answers.get('lead_goal', 'Not specified')

        # Format template with data
        user_prompt = prompt_config.get('prompt_template', '').format(
            primary_category=primary_category,
            categories=categories_list,
            categories_count=len(categories),
            service_areas=service_areas_list,
            service_areas_count=len(service_areas),
            rating=f"{rating:.1f}" if rating else "Not set",
            reviews_count=reviews_count,
            weekly_budget=f"${weekly_budget:,.2f}" if weekly_budget else "Not set",
            hours=hours,
            website=website,
            phone=phone,
            priorities=priorities,
            priority_areas=priority_areas,
            response_time=response_time,
            after_hours=after_hours,
            lead_goal=lead_goal
        )

    # Get API key from environment
    api_key = current_app.config.get('OPENAI_API_KEY')
    if not api_key:
        raise ValueError("OPENAI_API_KEY not configured")

    # Call OpenAI
    client = OpenAI(api_key=api_key)

    try:
        response = client.chat.completions.create(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_message},
                {"role": "user", "content": user_prompt}
            ]
        )

        content = response.choices[0].message.content
        result = json.loads(content)

        # Extract recommendations array
        if isinstance(result, dict) and 'recommendations' in result:
            recommendations = result['recommendations']
        elif isinstance(result, list):
            recommendations = result
        else:
            current_app.logger.warning(f"Unexpected OpenAI response format: {result}")
            recommendations = []

        return recommendations

    except Exception as e:
        current_app.logger.exception(f"OpenAI API error: {e}")
        raise


def _store_recommendations(account_id: int, recommendations: List[Dict], profile_data: Dict):
    """
    Store recommendations in the database.

    Args:
        account_id: The account ID
        recommendations: List of recommendation dicts from OpenAI
        profile_data: Original profile data for context
    """
    # Calculate confidence based on data completeness
    confidence = _calculate_confidence(profile_data)

    # Get profile identifier (customer_id or manager_id)
    source_id = profile_data.get('customer_id') or profile_data.get('manager_id') or 'unknown'

    for rec in recommendations:
        # Create recommendation record
        recommendation = OptimizerRecommendation(
            account_id=account_id,
            source_type='glsa',
            source_id=str(source_id),
            title=rec.get('title', 'Untitled Recommendation'),
            description=rec.get('description', ''),
            category=rec.get('category', 'profile'),
            severity=rec.get('severity', 3),
            expected_impact=rec.get('expected_impact', ''),
            confidence=confidence,
            data_points=json.dumps(rec.get('data_points', [])),
            action_data=json.dumps(rec.get('action', {})),
            status='open',
            created_at=datetime.utcnow()
        )

        db.session.add(recommendation)

    try:
        db.session.commit()
        current_app.logger.info(f"Stored {len(recommendations)} GLSA recommendations for account {account_id}")
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception(f"Error storing GLSA recommendations: {e}")
        raise


def _calculate_confidence(profile_data: Dict) -> float:
    """
    Calculate confidence score (0.0-1.0) based on profile data completeness.

    More complete profiles = higher confidence in recommendations.
    """
    confidence = 0.5  # Base confidence

    # Boost for having categories
    if profile_data.get('primary_category'):
        confidence += 0.1
    categories = profile_data.get('categories', [])
    if len(categories) >= 2:
        confidence += 0.05

    # Boost for service areas
    service_areas = profile_data.get('service_areas', [])
    if len(service_areas) >= 1:
        confidence += 0.1

    # Boost for reviews data
    reviews_count = profile_data.get('reviews_count', 0)
    if reviews_count >= 50:
        confidence += 0.1
    elif reviews_count >= 20:
        confidence += 0.05

    # Boost for budget being set
    if profile_data.get('weekly_budget'):
        confidence += 0.05

    # Boost for having answers/context
    answers = profile_data.get('answers', {})
    if answers.get('priorities'):
        confidence += 0.05
    if answers.get('lead_goal'):
        confidence += 0.05

    return min(confidence, 1.0)


def _format_recommendations_response(account_id: int) -> Dict:
    """
    Format recommendations for API response.

    Args:
        account_id: The account ID

    Returns:
        Dict with summary and recommendations
    """
    recommendations = OptimizerRecommendation.query.filter(
        OptimizerRecommendation.account_id == account_id,
        OptimizerRecommendation.source_type == 'glsa',
        OptimizerRecommendation.status == 'open'
    ).order_by(
        OptimizerRecommendation.severity.asc(),
        OptimizerRecommendation.created_at.desc()
    ).all()

    # Format recommendations
    formatted_recs = []
    for rec in recommendations:
        formatted_recs.append({
            'id': rec.id,
            'title': rec.title,
            'description': rec.description,
            'category': rec.category,
            'severity': rec.severity,
            'expected_impact': rec.expected_impact,
            'confidence': rec.confidence or 0.75,
            'data_points': json.loads(rec.data_points) if rec.data_points else [],
            'action': json.loads(rec.action_data) if rec.action_data else {},
            'created_at': rec.created_at.isoformat() if rec.created_at else None
        })

    # Generate summary
    if not formatted_recs:
        summary = "No optimization recommendations at this time."
    elif len(formatted_recs) == 1:
        summary = "Found 1 optimization opportunity for your Local Services Ads profile."
    else:
        critical_count = sum(1 for r in formatted_recs if r['severity'] == 1)
        if critical_count > 0:
            summary = f"Found {len(formatted_recs)} optimization opportunities including {critical_count} critical issue(s)."
        else:
            summary = f"Found {len(formatted_recs)} optimization opportunities to improve your Local Services Ads performance."

    return {
        "ok": True,
        "summary": summary,
        "recommendations": formatted_recs,
        "total_count": len(formatted_recs)
    }


def apply_glsa_recommendation(account_id: int, recommendation_id: int, user_id: int) -> Dict:
    """
    Mark a GLSA recommendation as applied.

    Args:
        account_id: The account ID
        recommendation_id: The recommendation ID
        user_id: The user who applied it

    Returns:
        Dict with ok status
    """
    recommendation = OptimizerRecommendation.query.filter(
        OptimizerRecommendation.id == recommendation_id,
        OptimizerRecommendation.account_id == account_id,
        OptimizerRecommendation.source_type == 'glsa'
    ).first()

    if not recommendation:
        return {"ok": False, "error": "Recommendation not found"}

    # Update status
    recommendation.status = 'applied'

    # Create action record
    action = OptimizerAction(
        recommendation_id=recommendation_id,
        applied_by=user_id,
        applied_at=datetime.utcnow(),
        action_type='applied',
        notes=None
    )

    db.session.add(action)

    try:
        db.session.commit()
        current_app.logger.info(f"Applied GLSA recommendation {recommendation_id} for account {account_id}")
        return {"ok": True}
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception(f"Error applying GLSA recommendation: {e}")
        return {"ok": False, "error": str(e)}


def dismiss_glsa_recommendation(
    account_id: int,
    recommendation_id: int,
    user_id: int,
    reason: Optional[str] = None
) -> Dict:
    """
    Dismiss a GLSA recommendation.

    Args:
        account_id: The account ID
        recommendation_id: The recommendation ID
        user_id: The user who dismissed it
        reason: Optional dismissal reason

    Returns:
        Dict with ok status
    """
    recommendation = OptimizerRecommendation.query.filter(
        OptimizerRecommendation.id == recommendation_id,
        OptimizerRecommendation.account_id == account_id,
        OptimizerRecommendation.source_type == 'glsa'
    ).first()

    if not recommendation:
        return {"ok": False, "error": "Recommendation not found"}

    # Update status
    recommendation.status = 'dismissed'

    # Create action record
    action = OptimizerAction(
        recommendation_id=recommendation_id,
        applied_by=user_id,
        applied_at=datetime.utcnow(),
        action_type='dismissed',
        notes=reason
    )

    db.session.add(action)

    try:
        db.session.commit()
        current_app.logger.info(f"Dismissed GLSA recommendation {recommendation_id} for account {account_id}")
        return {"ok": True}
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception(f"Error dismissing GLSA recommendation: {e}")
        return {"ok": False, "error": str(e)}
