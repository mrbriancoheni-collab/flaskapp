# app/services/fbads_insights.py
"""
AI-powered optimization insights for Facebook Ads.
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
OPENAI_API_KEY = None  # Set from env in generate_fbads_insights
OPENAI_MODEL = "gpt-4o-mini"


def generate_fbads_insights(
    account_id: int,
    profile_data: Dict,
    campaign_data: Optional[Dict] = None,
    regenerate: bool = False
) -> Dict:
    """
    Generate AI-powered optimization insights for Facebook Ads profile and campaigns.

    Args:
        account_id: The account ID
        profile_data: Facebook Page profile data
        campaign_data: Optional campaign performance data
        regenerate: If True, force regeneration even if recent insights exist

    Returns:
        Dict with summary and recommendations
    """
    # Check for recent insights (6-hour cache)
    if not regenerate:
        cutoff = datetime.utcnow() - timedelta(hours=6)
        recent = OptimizerRecommendation.query.filter(
            OptimizerRecommendation.account_id == account_id,
            OptimizerRecommendation.source_type == 'fbads',
            OptimizerRecommendation.status == 'open',
            OptimizerRecommendation.created_at >= cutoff
        ).first()

        if recent:
            current_app.logger.info(f"Using cached FB Ads insights for account {account_id}")
            return _format_recommendations_response(account_id)

    # Generate new insights
    current_app.logger.info(f"Generating new FB Ads insights for account {account_id}")

    try:
        # Get AI recommendations from OpenAI
        recommendations = []

        # Generate profile recommendations
        if profile_data:
            profile_recs = _call_openai_for_profile_insights(profile_data)
            recommendations.extend(profile_recs)

        # Generate campaign recommendations if data provided
        if campaign_data:
            campaign_recs = _call_openai_for_campaign_insights(campaign_data)
            recommendations.extend(campaign_recs)

        # Store recommendations in database
        _store_recommendations(account_id, recommendations, profile_data, campaign_data)

        # Return formatted response
        return _format_recommendations_response(account_id)

    except Exception as e:
        current_app.logger.exception(f"Error generating FB Ads insights: {e}")
        return {
            "ok": False,
            "error": str(e),
            "summary": "Failed to generate insights. Please try again.",
            "recommendations": []
        }


def _call_openai_for_profile_insights(profile_data: Dict) -> List[Dict]:
    """
    Call OpenAI API to generate Facebook Page profile optimization insights.

    Args:
        profile_data: Facebook Page profile data

    Returns:
        List of recommendation dictionaries
    """
    from app.services.ai_prompts_init import get_prompt_for_service

    # Load prompt from database
    prompt_config = get_prompt_for_service('fbads_profile_main')

    if not prompt_config:
        current_app.logger.warning("FB Ads profile prompt not found in database, using fallback")
        # Fallback to basic prompt
        system_message = "You are a Facebook Ads profile optimization expert providing data-driven recommendations in JSON format."
        model = OPENAI_MODEL
        temperature = 0.7
        max_tokens = 2000

        user_prompt = f"""Analyze this Facebook Page profile and provide 3-5 actionable optimization recommendations.

PROFILE DATA:
{json.dumps(profile_data, indent=2)}

Return ONLY valid JSON array of recommendations with these fields:
- title: Brief action-oriented title
- description: Detailed explanation (2-3 sentences)
- category: One of [page_info, about, description, cta, cover_photo, profile_photo]
- severity: 1=critical, 2=high-impact, 3=quick win, 4-5=long-term
- expected_impact: Specific improvement (e.g., "Increase page engagement by 15-20%")
- data_points: Array of supporting metrics
- action: Dict with implementation details"""
    else:
        # Use database prompt with template formatting
        system_message = prompt_config.get('system_message', '')
        model = prompt_config.get('model', 'gpt-4o-mini')
        temperature = prompt_config.get('temperature', 0.7)
        max_tokens = prompt_config.get('max_tokens', 2000)

        # Extract profile metrics
        page_name = profile_data.get('name', 'Not set')
        category = profile_data.get('category', 'Not set')
        about = profile_data.get('about', 'Not set')
        about_length = len(about) if about != 'Not set' else 0
        description = profile_data.get('description', 'Not set')
        description_length = len(description) if description != 'Not set' else 0
        website = profile_data.get('website', 'Not set')
        cta_button = profile_data.get('cta_button', 'Not set')
        cover_photo = 'Set' if profile_data.get('cover_photo') else 'Not set'
        profile_photo = 'Set' if profile_data.get('profile_photo') else 'Not set'

        # Format template with data
        user_prompt = prompt_config.get('prompt_template', '').format(
            page_name=page_name,
            category=category,
            about=about[:100] + '...' if len(about) > 100 else about,
            about_length=about_length,
            description=description[:200] + '...' if len(description) > 200 else description,
            description_length=description_length,
            website=website,
            cta_button=cta_button,
            cover_photo=cover_photo,
            profile_photo=profile_photo
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


def _call_openai_for_campaign_insights(campaign_data: Dict) -> List[Dict]:
    """
    Call OpenAI API to generate Facebook Ads campaign optimization insights.

    Args:
        campaign_data: Campaign performance data

    Returns:
        List of recommendation dictionaries
    """
    from app.services.ai_prompts_init import get_prompt_for_service

    # Load prompt from database
    prompt_config = get_prompt_for_service('fbads_campaigns_main')

    if not prompt_config:
        current_app.logger.warning("FB Ads campaigns prompt not found in database, using fallback")
        # Fallback to basic prompt
        system_message = "You are a Facebook Ads campaign optimization expert providing data-driven recommendations in JSON format."
        model = OPENAI_MODEL
        temperature = 0.7
        max_tokens = 2000

        user_prompt = f"""Analyze this Facebook Ads campaign data and provide 5-8 actionable optimization recommendations.

CAMPAIGN DATA:
{json.dumps(campaign_data, indent=2)}

Return ONLY valid JSON array of recommendations."""
    else:
        # Use database prompt with template formatting
        system_message = prompt_config.get('system_message', '')
        model = prompt_config.get('model', 'gpt-4o-mini')
        temperature = prompt_config.get('temperature', 0.7)
        max_tokens = prompt_config.get('max_tokens', 2000)

        # Extract campaign metrics
        campaigns = campaign_data.get('campaigns', [])
        total_spend = sum(float(c.get('spend', 0)) for c in campaigns)
        total_impressions = sum(int(c.get('impressions', 0)) for c in campaigns)
        total_clicks = sum(int(c.get('clicks', 0)) for c in campaigns)
        avg_cpc = total_spend / total_clicks if total_clicks > 0 else 0
        avg_cpm = (total_spend / total_impressions) * 1000 if total_impressions > 0 else 0
        avg_ctr = (total_clicks / total_impressions) * 100 if total_impressions > 0 else 0

        # Format template with data
        user_prompt = prompt_config.get('prompt_template', '').format(
            campaigns_count=len(campaigns),
            total_spend=f"${total_spend:,.2f}",
            total_impressions=f"{total_impressions:,}",
            total_clicks=f"{total_clicks:,}",
            avg_cpc=f"${avg_cpc:.2f}",
            avg_cpm=f"${avg_cpm:.2f}",
            avg_ctr=f"{avg_ctr:.2f}%",
            campaigns_data=json.dumps(campaigns[:5], indent=2)  # Top 5 campaigns
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


def _store_recommendations(account_id: int, recommendations: List[Dict], profile_data: Dict, campaign_data: Optional[Dict]):
    """
    Store recommendations in the database.

    Args:
        account_id: The account ID
        recommendations: List of recommendation dicts from OpenAI
        profile_data: Profile data for context
        campaign_data: Campaign data for context
    """
    # Calculate confidence based on data completeness
    confidence = _calculate_confidence(profile_data, campaign_data)

    # Get profile identifier
    source_id = profile_data.get('page_id') or profile_data.get('name') or 'unknown'

    for rec in recommendations:
        # Create recommendation record
        recommendation = OptimizerRecommendation(
            account_id=account_id,
            source_type='fbads',
            source_id=str(source_id),
            title=rec.get('title', 'Untitled Recommendation'),
            description=rec.get('description', ''),
            category=rec.get('category', 'general'),
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
        current_app.logger.info(f"Stored {len(recommendations)} FB Ads recommendations for account {account_id}")
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception(f"Error storing FB Ads recommendations: {e}")
        raise


def _calculate_confidence(profile_data: Dict, campaign_data: Optional[Dict]) -> float:
    """
    Calculate confidence score (0.0-1.0) based on data completeness.

    More complete data = higher confidence in recommendations.
    """
    confidence = 0.5  # Base confidence

    # Boost for having profile data
    if profile_data.get('name'):
        confidence += 0.05
    if profile_data.get('about'):
        confidence += 0.05
    if profile_data.get('description'):
        confidence += 0.1
    if profile_data.get('website'):
        confidence += 0.05

    # Boost for having campaign data
    if campaign_data:
        campaigns = campaign_data.get('campaigns', [])
        if len(campaigns) >= 1:
            confidence += 0.1
        if len(campaigns) >= 3:
            confidence += 0.05

        # Check if campaigns have performance data
        has_perf_data = any(c.get('spend') or c.get('impressions') for c in campaigns)
        if has_perf_data:
            confidence += 0.1

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
        OptimizerRecommendation.source_type == 'fbads',
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
        summary = "Found 1 optimization opportunity for your Facebook Ads account."
    else:
        critical_count = sum(1 for r in formatted_recs if r['severity'] == 1)
        if critical_count > 0:
            summary = f"Found {len(formatted_recs)} optimization opportunities including {critical_count} critical issue(s)."
        else:
            summary = f"Found {len(formatted_recs)} optimization opportunities to improve your Facebook Ads performance."

    return {
        "ok": True,
        "summary": summary,
        "recommendations": formatted_recs,
        "total_count": len(formatted_recs)
    }


def apply_fbads_recommendation(account_id: int, recommendation_id: int, user_id: int) -> Dict:
    """
    Mark a FB Ads recommendation as applied.

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
        OptimizerRecommendation.source_type == 'fbads'
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
        current_app.logger.info(f"Applied FB Ads recommendation {recommendation_id} for account {account_id}")
        return {"ok": True}
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception(f"Error applying FB Ads recommendation: {e}")
        return {"ok": False, "error": str(e)}


def dismiss_fbads_recommendation(
    account_id: int,
    recommendation_id: int,
    user_id: int,
    reason: Optional[str] = None
) -> Dict:
    """
    Dismiss a FB Ads recommendation.

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
        OptimizerRecommendation.source_type == 'fbads'
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
        current_app.logger.info(f"Dismissed FB Ads recommendation {recommendation_id} for account {account_id}")
        return {"ok": True}
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception(f"Error dismissing FB Ads recommendation: {e}")
        return {"ok": False, "error": str(e)}
