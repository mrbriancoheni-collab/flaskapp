# app/services/gmb_insights.py
"""
AI-powered optimization insights for Google My Business (GMB).
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
OPENAI_API_KEY = None  # Set from env in generate_gmb_insights
OPENAI_MODEL = "gpt-4o-mini"


def generate_gmb_insights(
    account_id: int,
    profile_data: Dict,
    regenerate: bool = False
) -> Dict:
    """
    Generate AI-powered optimization insights for a Google My Business profile.

    Args:
        account_id: The account ID
        profile_data: Profile data including name, categories, description, etc.
        regenerate: If True, force regeneration even if recent insights exist

    Returns:
        Dict with summary and recommendations
    """
    # Check for recent insights (6-hour cache)
    if not regenerate:
        cutoff = datetime.utcnow() - timedelta(hours=6)
        recent = OptimizerRecommendation.query.filter(
            OptimizerRecommendation.account_id == account_id,
            OptimizerRecommendation.source_type == 'gmb',
            OptimizerRecommendation.status == 'open',
            OptimizerRecommendation.created_at >= cutoff
        ).first()

        if recent:
            current_app.logger.info(f"Using cached GMB insights for account {account_id}")
            return _format_recommendations_response(account_id)

    # Generate new insights
    current_app.logger.info(f"Generating new GMB insights for account {account_id}")

    try:
        # Get AI recommendations from OpenAI
        recommendations = _call_openai_for_gmb_insights(profile_data)

        # Store recommendations in database
        _store_recommendations(account_id, recommendations, profile_data)

        # Return formatted response
        return _format_recommendations_response(account_id)

    except Exception as e:
        current_app.logger.exception(f"Error generating GMB insights: {e}")
        return {
            "ok": False,
            "error": str(e),
            "summary": "Failed to generate insights. Please try again.",
            "recommendations": []
        }


def _call_openai_for_gmb_insights(profile_data: Dict) -> List[Dict]:
    """
    Call OpenAI API to generate GMB optimization insights using database-stored prompts.

    Args:
        profile_data: Profile data to analyze

    Returns:
        List of recommendation dictionaries
    """
    from app.services.ai_prompts_init import get_prompt_for_service

    # Load prompt from database
    prompt_config = get_prompt_for_service('gmb_main')

    if not prompt_config:
        current_app.logger.warning("GMB prompt not found in database, using fallback")
        # Fallback to basic prompt
        system_message = "You are a Google My Business optimization expert providing data-driven recommendations in JSON format."
        model = OPENAI_MODEL
        temperature = 0.7
        max_tokens = 2000

        user_prompt = f"""Analyze this Google My Business profile and provide 5-10 actionable optimization recommendations.

PROFILE DATA:
{json.dumps(profile_data, indent=2)}

Return ONLY valid JSON array of recommendations with these fields:
- title: Brief action-oriented title
- description: Detailed explanation (2-3 sentences)
- category: One of [profile_info, categories, description, photos, posts, reviews, attributes]
- severity: 1=critical, 2=high-impact, 3=quick win, 4-5=long-term
- expected_impact: Specific improvement (e.g., "Increase profile views by 15-20%")
- data_points: Array of supporting metrics
- action: Dict with implementation details"""
    else:
        # Use database prompt with template formatting
        system_message = prompt_config.get('system_message', '')
        model = prompt_config.get('model', 'gpt-4o-mini')
        temperature = prompt_config.get('temperature', 0.7)
        max_tokens = prompt_config.get('max_tokens', 2000)

        # Extract profile metrics
        business_name = profile_data.get('name', 'Not set')
        primary_category = profile_data.get('primary_category', 'Not set')
        categories = profile_data.get('categories', [])
        categories_list = ', '.join(categories) if categories else 'None'

        description = profile_data.get('description', 'Not set')
        description_length = len(description) if description != 'Not set' else 0

        address = profile_data.get('address', 'Not set')
        phone = profile_data.get('phone', 'Not set')
        website = profile_data.get('website', 'Not set')
        hours = profile_data.get('hours', 'Not set')

        photos_count = profile_data.get('photos_count', 0)
        reviews_count = profile_data.get('reviews_count', 0)
        rating = profile_data.get('rating', 0)

        posts_count = profile_data.get('posts_count', 0)
        last_post_date = profile_data.get('last_post_date', 'Never')

        attributes = profile_data.get('attributes', [])
        attributes_list = ', '.join(attributes) if attributes else 'None'

        # Format template with data
        user_prompt = prompt_config.get('prompt_template', '').format(
            business_name=business_name,
            primary_category=primary_category,
            categories=categories_list,
            categories_count=len(categories),
            description=description[:200] + '...' if len(description) > 200 else description,
            description_length=description_length,
            address=address,
            phone=phone,
            website=website,
            hours=hours,
            photos_count=photos_count,
            reviews_count=reviews_count,
            rating=f"{rating:.1f}" if rating else "Not set",
            posts_count=posts_count,
            last_post_date=last_post_date,
            attributes=attributes_list,
            attributes_count=len(attributes)
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
    # Calculate confidence based on profile completeness
    confidence = _calculate_confidence(profile_data)

    # Get profile identifier (business name or ID)
    source_id = profile_data.get('place_id') or profile_data.get('name') or 'unknown'

    for rec in recommendations:
        # Create recommendation record
        recommendation = OptimizerRecommendation(
            account_id=account_id,
            source_type='gmb',
            source_id=str(source_id),
            title=rec.get('title', 'Untitled Recommendation'),
            description=rec.get('description', ''),
            category=rec.get('category', 'profile_info'),
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
        current_app.logger.info(f"Stored {len(recommendations)} GMB recommendations for account {account_id}")
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception(f"Error storing GMB recommendations: {e}")
        raise


def _calculate_confidence(profile_data: Dict) -> float:
    """
    Calculate confidence score (0.0-1.0) based on profile data completeness.

    More complete profiles = higher confidence in recommendations.
    """
    confidence = 0.5  # Base confidence

    # Boost for having basic info
    if profile_data.get('name'):
        confidence += 0.05
    if profile_data.get('primary_category'):
        confidence += 0.05

    # Boost for description
    description = profile_data.get('description', '')
    if len(description) >= 200:
        confidence += 0.1
    elif len(description) >= 100:
        confidence += 0.05

    # Boost for contact info
    if profile_data.get('phone'):
        confidence += 0.05
    if profile_data.get('website'):
        confidence += 0.05

    # Boost for reviews data
    reviews_count = profile_data.get('reviews_count', 0)
    if reviews_count >= 50:
        confidence += 0.1
    elif reviews_count >= 20:
        confidence += 0.05

    # Boost for photos
    photos_count = profile_data.get('photos_count', 0)
    if photos_count >= 10:
        confidence += 0.05

    # Boost for posts activity
    posts_count = profile_data.get('posts_count', 0)
    if posts_count >= 5:
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
        OptimizerRecommendation.source_type == 'gmb',
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
        summary = "Found 1 optimization opportunity for your Google My Business profile."
    else:
        critical_count = sum(1 for r in formatted_recs if r['severity'] == 1)
        if critical_count > 0:
            summary = f"Found {len(formatted_recs)} optimization opportunities including {critical_count} critical issue(s)."
        else:
            summary = f"Found {len(formatted_recs)} optimization opportunities to improve your Google My Business profile."

    return {
        "ok": True,
        "summary": summary,
        "recommendations": formatted_recs,
        "total_count": len(formatted_recs)
    }


def apply_gmb_recommendation(account_id: int, recommendation_id: int, user_id: int) -> Dict:
    """
    Mark a GMB recommendation as applied.

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
        OptimizerRecommendation.source_type == 'gmb'
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
        current_app.logger.info(f"Applied GMB recommendation {recommendation_id} for account {account_id}")
        return {"ok": True}
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception(f"Error applying GMB recommendation: {e}")
        return {"ok": False, "error": str(e)}


def dismiss_gmb_recommendation(
    account_id: int,
    recommendation_id: int,
    user_id: int,
    reason: Optional[str] = None
) -> Dict:
    """
    Dismiss a GMB recommendation.

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
        OptimizerRecommendation.source_type == 'gmb'
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
        current_app.logger.info(f"Dismissed GMB recommendation {recommendation_id} for account {account_id}")
        return {"ok": True}
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception(f"Error dismissing GMB recommendation: {e}")
        return {"ok": False, "error": str(e)}
