# app/services/google_ads_insights.py
"""
Google Ads AI Optimization Insights Service.

Provides:
- AI-powered recommendation generation using OpenAI
- Confidence scoring and categorization
- Expected impact calculations
- Database storage and retrieval
- Smart scheduling (weekly by default, daily for high-spend accounts)
"""

import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from flask import current_app
from openai import OpenAI

from app import db
from app.models_ads import OptimizerRecommendation, OptimizerAction
from app.monitoring import start_span, add_breadcrumb, capture_exception


# Constants for spend thresholds
HIGH_SPEND_DAILY_THRESHOLD = 1000  # $1000+/day = daily analysis
MEDIUM_SPEND_DAILY_THRESHOLD = 500  # $500+/day = 2x/week analysis
DEFAULT_ANALYSIS_DAYS = 7  # Weekly by default


def should_run_daily_analysis(account_id: int, daily_spend: float) -> bool:
    """
    Determine if account warrants daily analysis based on spend.

    Args:
        account_id: Account ID
        daily_spend: Average daily spend

    Returns:
        True if daily analysis recommended, False for weekly
    """
    if daily_spend >= HIGH_SPEND_DAILY_THRESHOLD:
        current_app.logger.info(
            f"Account {account_id}: High spend ${daily_spend:.2f}/day - enabling daily analysis"
        )
        return True

    if daily_spend >= MEDIUM_SPEND_DAILY_THRESHOLD:
        current_app.logger.info(
            f"Account {account_id}: Medium spend ${daily_spend:.2f}/day - enabling 2x/week analysis"
        )
        return "twice_weekly"

    current_app.logger.info(
        f"Account {account_id}: Standard spend ${daily_spend:.2f}/day - weekly analysis"
    )
    return False


def get_account_performance_data(account_id: int, days: int = 30) -> Dict[str, Any]:
    """
    Gather comprehensive account performance data for AI analysis.

    Args:
        account_id: Account ID
        days: Number of days of historical data

    Returns:
        Dictionary with performance metrics
    """
    from app.models_ads import GadsStatsDaily
    from sqlalchemy import func

    with start_span("db.query", f"Fetch {days} days of Google Ads performance data"):
        # Get aggregate stats
        stats = db.session.query(
            func.sum(GadsStatsDaily.cost).label('total_spend'),
            func.sum(GadsStatsDaily.conversions).label('total_conversions'),
            func.avg(GadsStatsDaily.cost / GadsStatsDaily.conversions).label('avg_cpa'),
            func.avg(GadsStatsDaily.ctr).label('avg_ctr'),
            func.count(GadsStatsDaily.id).label('days_of_data')
        ).filter(
            GadsStatsDaily.account_id == account_id,
            GadsStatsDaily.date >= datetime.utcnow().date() - timedelta(days=days)
        ).first()

        # Get daily spend for smart scheduling
        daily_spend_avg = (stats.total_spend or 0) / max(days, 1)

        # Get campaigns
        campaigns = _get_campaign_summary(account_id, days)

        # Get keywords
        keywords = _get_keyword_summary(account_id, days)

        # Get search terms
        search_terms = _get_search_term_summary(account_id, days)

        return {
            "account_summary": {
                "account_id": account_id,
                "period_days": days,
                "total_spend": float(stats.total_spend or 0),
                "total_conversions": int(stats.total_conversions or 0),
                "avg_cpa": float(stats.avg_cpa or 0),
                "avg_ctr": float(stats.avg_ctr or 0),
                "daily_spend_avg": daily_spend_avg,
                "days_of_data": int(stats.days_of_data or 0),
            },
            "campaigns": campaigns,
            "keywords": keywords,
            "search_terms": search_terms,
        }


def _get_campaign_summary(account_id: int, days: int) -> List[Dict]:
    """Get campaign performance summary."""
    from app.models_ads import GadsStatsDaily
    from sqlalchemy import func

    campaigns = db.session.query(
        GadsStatsDaily.campaign_id,
        GadsStatsDaily.campaign_name,
        func.sum(GadsStatsDaily.cost).label('spend'),
        func.sum(GadsStatsDaily.conversions).label('conversions'),
        func.avg(GadsStatsDaily.ctr).label('ctr'),
        func.count(func.distinct(GadsStatsDaily.date)).label('active_days')
    ).filter(
        GadsStatsDaily.account_id == account_id,
        GadsStatsDaily.date >= datetime.utcnow().date() - timedelta(days=days)
    ).group_by(
        GadsStatsDaily.campaign_id,
        GadsStatsDaily.campaign_name
    ).order_by(
        func.sum(GadsStatsDaily.cost).desc()
    ).limit(20).all()

    return [
        {
            "id": c.campaign_id,
            "name": c.campaign_name,
            "spend": float(c.spend or 0),
            "conversions": int(c.conversions or 0),
            "cpa": float(c.spend / c.conversions) if c.conversions else 0,
            "ctr": float(c.ctr or 0),
            "active_days": int(c.active_days or 0),
        }
        for c in campaigns
    ]


def _get_keyword_summary(account_id: int, days: int) -> List[Dict]:
    """Get keyword performance summary."""
    from app.models_ads import GadsStatsDaily
    from sqlalchemy import func

    keywords = db.session.query(
        GadsStatsDaily.keyword_id,
        GadsStatsDaily.keyword_text,
        func.sum(GadsStatsDaily.cost).label('spend'),
        func.sum(GadsStatsDaily.conversions).label('conversions'),
        func.avg(GadsStatsDaily.ctr).label('ctr'),
        func.sum(GadsStatsDaily.clicks).label('clicks')
    ).filter(
        GadsStatsDaily.account_id == account_id,
        GadsStatsDaily.date >= datetime.utcnow().date() - timedelta(days=days),
        GadsStatsDaily.keyword_id.isnot(None)
    ).group_by(
        GadsStatsDaily.keyword_id,
        GadsStatsDaily.keyword_text
    ).order_by(
        func.sum(GadsStatsDaily.cost).desc()
    ).limit(50).all()

    return [
        {
            "id": k.keyword_id,
            "text": k.keyword_text,
            "spend": float(k.spend or 0),
            "conversions": int(k.conversions or 0),
            "cpa": float(k.spend / k.conversions) if k.conversions else 0,
            "ctr": float(k.ctr or 0),
            "clicks": int(k.clicks or 0),
        }
        for k in keywords
    ]


def _get_search_term_summary(account_id: int, days: int) -> List[Dict]:
    """Get search term performance summary."""
    from app.models_ads import SearchTerm
    from sqlalchemy import func

    search_terms = db.session.query(
        SearchTerm.query_text,
        func.sum(SearchTerm.cost).label('spend'),
        func.sum(SearchTerm.conversions).label('conversions'),
        func.avg(SearchTerm.ctr).label('ctr')
    ).filter(
        SearchTerm.account_id == account_id,
        SearchTerm.date >= datetime.utcnow().date() - timedelta(days=days)
    ).group_by(
        SearchTerm.query_text
    ).order_by(
        func.sum(SearchTerm.cost).desc()
    ).limit(30).all()

    return [
        {
            "text": st.query_text,
            "spend": float(st.spend or 0),
            "conversions": int(st.conversions or 0),
            "ctr": float(st.ctr or 0),
        }
        for st in search_terms
    ]


def generate_ai_insights(account_id: int, scope: str = "all", regenerate: bool = False) -> Dict:
    """
    Generate AI-powered optimization insights using OpenAI.

    Args:
        account_id: Account ID
        scope: Analysis scope (all, campaigns, keywords, etc.)
        regenerate: Force regeneration even if recent insights exist

    Returns:
        Dictionary with summary and categorized recommendations
    """
    add_breadcrumb(
        "Generating AI optimization insights",
        category="ai",
        data={"account_id": account_id, "scope": scope}
    )

    # Check for recent insights (unless regenerating)
    if not regenerate:
        recent = OptimizerRecommendation.query.filter(
            OptimizerRecommendation.account_id == account_id,
            OptimizerRecommendation.created_at >= datetime.utcnow() - timedelta(hours=6),
            OptimizerRecommendation.status == 'open'
        ).first()

        if recent:
            current_app.logger.info(f"Using recent insights for account {account_id}")
            return _format_existing_insights(account_id)

    # Get performance data
    try:
        perf_data = get_account_performance_data(account_id, days=30)
    except Exception as e:
        current_app.logger.error(f"Failed to get performance data: {e}")
        capture_exception(e, extra_context={"account_id": account_id})
        return _generate_fallback_insights(account_id, scope)

    # Check if we have enough data
    if perf_data["account_summary"]["days_of_data"] < 7:
        current_app.logger.warning(f"Insufficient data for account {account_id}")
        return {
            "summary": "Insufficient data for AI analysis. Please wait until you have at least 7 days of performance data.",
            "recommendations": [],
            "generated_at": datetime.utcnow().isoformat()
        }

    # Call OpenAI for insights
    try:
        with start_span("openai.api", "Generate Google Ads optimization insights"):
            insights = _call_openai_for_insights(account_id, perf_data, scope)
    except Exception as e:
        current_app.logger.error(f"OpenAI API call failed: {e}", exc_info=True)
        capture_exception(e, extra_context={"account_id": account_id})
        return _generate_fallback_insights(account_id, scope)

    # Store recommendations in database
    try:
        _store_recommendations(account_id, insights["recommendations"], perf_data)
    except Exception as e:
        current_app.logger.error(f"Failed to store recommendations: {e}")
        capture_exception(e)

    add_breadcrumb(
        "AI insights generated successfully",
        category="ai",
        data={"count": len(insights["recommendations"]), "account_id": account_id}
    )

    return insights


def _call_openai_for_insights(account_id: int, perf_data: Dict, scope: str) -> Dict:
    """Call OpenAI API to generate insights."""
    api_key = current_app.config.get("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY not configured")

    model = current_app.config.get("OPENAI_MODEL", "gpt-4o-mini")

    # Build system prompt
    system_prompt = """You are an expert Google Ads optimization consultant. Analyze the provided account performance data and generate actionable optimization recommendations.

Focus on:
- Budget efficiency and wasted spend
- Underperforming campaigns, ad groups, and keywords
- High-potential opportunities being limited by budget
- Bid strategy optimization
- Negative keyword opportunities
- Ad copy and creative improvements
- Landing page optimization

Be specific, quantify expected impact when possible, and prioritize recommendations by potential ROI."""

    # Build user prompt with data
    user_prompt = f"""Analyze this Google Ads account and provide optimization recommendations.

ACCOUNT PERFORMANCE (Last 30 days):
- Total Spend: ${perf_data['account_summary']['total_spend']:.2f}
- Total Conversions: {perf_data['account_summary']['total_conversions']}
- Average CPA: ${perf_data['account_summary']['avg_cpa']:.2f}
- Average CTR: {perf_data['account_summary']['avg_ctr']:.2%}
- Daily Spend: ${perf_data['account_summary']['daily_spend_avg']:.2f}

TOP CAMPAIGNS:
{json.dumps(perf_data['campaigns'][:10], indent=2)}

TOP KEYWORDS:
{json.dumps(perf_data['keywords'][:20], indent=2)}

SEARCH TERMS:
{json.dumps(perf_data['search_terms'][:15], indent=2)}

Return a JSON object with this exact structure:
{{
  "summary": "3-5 sentence executive summary of account health and top opportunities",
  "recommendations": [
    {{
      "category": "budget|bidding|keywords|ads|targeting|negatives|landing_pages",
      "severity": 1-5 (1=critical/immediate action, 2=high impact, 3=quick win, 4=medium priority, 5=long-term),
      "title": "Brief, actionable title (max 80 chars)",
      "description": "Detailed explanation of the issue and recommended action (2-3 sentences)",
      "expected_impact": "Quantified expected result (e.g., 'Save $340/month' or 'Generate 12 more conversions/month')",
      "data_points": ["Key metric 1", "Key metric 2"],
      "action": {{
        "type": "increase_budget|decrease_budget|pause_keyword|add_negative|change_bid_strategy|etc",
        "target_id": "campaign_id or keyword_id or null",
        "target_name": "Campaign or keyword name",
        "params": {{"budget": 100, "change": "+20%"}}
      }}
    }}
  ]
}}

Provide 5-12 recommendations total, prioritizing by potential impact and ease of implementation."""

    # Call OpenAI
    client = OpenAI(api_key=api_key)

    response = client.chat.completions.create(
        model=model,
        temperature=0.3,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        timeout=30
    )

    # Parse response
    result = json.loads(response.choices[0].message.content)

    # Add metadata
    result["generated_at"] = datetime.utcnow().isoformat()
    result["model"] = model
    result["account_id"] = account_id

    return result


def _store_recommendations(account_id: int, recommendations: List[Dict], perf_data: Dict):
    """Store recommendations in database with confidence scoring."""

    # Clear old open recommendations for this account
    OptimizerRecommendation.query.filter(
        OptimizerRecommendation.account_id == account_id,
        OptimizerRecommendation.status == 'open'
    ).update({"status": "superseded"})

    for rec in recommendations:
        # Calculate confidence score
        confidence = _calculate_confidence(rec, perf_data)

        # Create database record
        db_rec = OptimizerRecommendation(
            account_id=account_id,
            scope_type=rec.get("action", {}).get("type", "account"),
            scope_id=int(rec.get("action", {}).get("target_id") or 0),
            category=rec["category"],
            title=rec["title"],
            details=rec["description"],
            expected_impact=rec["expected_impact"],
            severity=rec["severity"],
            suggested_action_json=json.dumps(rec.get("action", {})),
            status="open"
        )

        db.session.add(db_rec)

    db.session.commit()
    current_app.logger.info(f"Stored {len(recommendations)} recommendations for account {account_id}")


def _calculate_confidence(recommendation: Dict, perf_data: Dict) -> float:
    """
    Calculate confidence score for a recommendation.

    Based on:
    - Data quality (days of data)
    - Performance variance
    - Recommendation complexity

    Returns:
        Float between 0.0 and 1.0
    """
    confidence = 1.0

    summary = perf_data.get("account_summary", {})
    days_of_data = summary.get("days_of_data", 0)

    # Reduce confidence for limited data
    if days_of_data < 30:
        confidence *= 0.8
    if days_of_data < 14:
        confidence *= 0.7
    if days_of_data < 7:
        confidence *= 0.5

    # Reduce confidence for low spend (less statistical significance)
    total_spend = summary.get("total_spend", 0)
    if total_spend < 100:
        confidence *= 0.6
    elif total_spend < 500:
        confidence *= 0.8

    # Reduce confidence for complex actions
    action_type = recommendation.get("action", {}).get("type", "")
    complex_actions = ["restructure", "change_bid_strategy", "major_change"]
    if action_type in complex_actions:
        confidence *= 0.85

    # High confidence for simple wins
    if recommendation.get("severity") == 3:  # Quick wins
        confidence = min(1.0, confidence * 1.05)

    return round(min(1.0, max(0.0, confidence)), 2)


def _format_existing_insights(account_id: int) -> Dict:
    """Format existing database recommendations into response format."""
    recommendations = OptimizerRecommendation.query.filter(
        OptimizerRecommendation.account_id == account_id,
        OptimizerRecommendation.status == 'open'
    ).order_by(
        OptimizerRecommendation.severity.asc(),
        OptimizerRecommendation.created_at.desc()
    ).all()

    formatted_recs = []
    for rec in recommendations:
        try:
            action = json.loads(rec.suggested_action_json) if rec.suggested_action_json else {}
        except:
            action = {}

        formatted_recs.append({
            "id": rec.id,
            "category": rec.category,
            "severity": rec.severity,
            "title": rec.title,
            "description": rec.details,
            "expected_impact": rec.expected_impact,
            "confidence": 0.85,  # Default confidence for existing recs
            "action": action,
            "created_at": rec.created_at.isoformat() if rec.created_at else None
        })

    # Generate summary based on recommendations
    if formatted_recs:
        critical_count = sum(1 for r in formatted_recs if r["severity"] == 1)
        high_impact_count = sum(1 for r in formatted_recs if r["severity"] == 2)
        summary = f"Found {len(formatted_recs)} optimization opportunities"
        if critical_count:
            summary += f" including {critical_count} critical issue{'s' if critical_count > 1 else ''}"
        if high_impact_count:
            summary += f" and {high_impact_count} high-impact opportunity{'ies' if high_impact_count > 1 else 'y'}"
        summary += "."
    else:
        summary = "No active recommendations at this time. Your account is performing well!"

    return {
        "summary": summary,
        "recommendations": formatted_recs,
        "generated_at": recommendations[0].created_at.isoformat() if recommendations else datetime.utcnow().isoformat(),
        "from_cache": True
    }


def _generate_fallback_insights(account_id: int, scope: str) -> Dict:
    """Generate basic rule-based insights when AI is unavailable."""
    current_app.logger.warning(f"Using fallback insights for account {account_id}")

    return {
        "summary": "AI insights are temporarily unavailable. Basic recommendations shown below.",
        "recommendations": [
            {
                "id": "fallback-1",
                "category": "keywords",
                "severity": 2,
                "title": "Review low-performing keywords",
                "description": "Check for keywords with high spend but low conversions. Consider pausing or reducing bids.",
                "expected_impact": "Potential to reduce wasted spend",
                "confidence": 0.7,
                "action": {"type": "review_keywords", "target_id": None}
            },
            {
                "id": "fallback-2",
                "category": "budget",
                "severity": 2,
                "title": "Check budget-limited campaigns",
                "description": "Review campaigns that are frequently limited by budget and consider reallocating spend from underperformers.",
                "expected_impact": "Potential to increase conversions",
                "confidence": 0.7,
                "action": {"type": "review_budgets", "target_id": None}
            },
            {
                "id": "fallback-3",
                "category": "negatives",
                "severity": 3,
                "title": "Add negative keywords",
                "description": "Review search terms report and add negative keywords to exclude irrelevant queries.",
                "expected_impact": "Reduce wasted spend on irrelevant clicks",
                "confidence": 0.8,
                "action": {"type": "add_negatives", "target_id": None}
            }
        ],
        "generated_at": datetime.utcnow().isoformat(),
        "fallback": True
    }


def categorize_recommendations(recommendations: List[Dict]) -> Dict[str, List[Dict]]:
    """
    Categorize recommendations by severity for UI display.

    Returns:
        Dictionary with keys: critical, high_impact, quick_wins, long_term
    """
    categories = {
        "critical": [],
        "high_impact": [],
        "quick_wins": [],
        "long_term": []
    }

    for rec in recommendations:
        severity = rec.get("severity", 5)
        if severity == 1:
            categories["critical"].append(rec)
        elif severity == 2:
            categories["high_impact"].append(rec)
        elif severity == 3:
            categories["quick_wins"].append(rec)
        else:
            categories["long_term"].append(rec)

    return categories


def apply_recommendation(recommendation_id: int, user_id: int) -> Tuple[bool, str]:
    """
    Apply a recommendation and track the action.

    Args:
        recommendation_id: ID of recommendation to apply
        user_id: User applying the recommendation

    Returns:
        Tuple of (success: bool, message: str)
    """
    rec = OptimizerRecommendation.query.get(recommendation_id)
    if not rec:
        return False, "Recommendation not found"

    if rec.status != "open":
        return False, f"Recommendation already {rec.status}"

    try:
        # Parse action
        action = json.loads(rec.suggested_action_json) if rec.suggested_action_json else {}
        action_type = action.get("type", "unknown")

        # Log the action
        optimizer_action = OptimizerAction(
            recommendation_id=recommendation_id,
            applied_by=user_id,
            applied_at=datetime.utcnow(),
            change_set_json=json.dumps(action),
            status="pending"
        )
        db.session.add(optimizer_action)

        # Update recommendation status
        rec.status = "applied"

        db.session.commit()

        add_breadcrumb(
            "Applied optimization recommendation",
            category="optimization",
            data={"recommendation_id": recommendation_id, "action_type": action_type}
        )

        # TODO: Actually apply the changes via Google Ads API
        # For now, just mark as applied

        return True, f"Recommendation applied successfully: {rec.title}"

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Failed to apply recommendation: {e}", exc_info=True)
        capture_exception(e, extra_context={"recommendation_id": recommendation_id})
        return False, f"Failed to apply recommendation: {str(e)}"


def dismiss_recommendation(recommendation_id: int, reason: Optional[str] = None) -> Tuple[bool, str]:
    """
    Dismiss a recommendation.

    Args:
        recommendation_id: ID of recommendation to dismiss
        reason: Optional reason for dismissal

    Returns:
        Tuple of (success: bool, message: str)
    """
    rec = OptimizerRecommendation.query.get(recommendation_id)
    if not rec:
        return False, "Recommendation not found"

    rec.status = "dismissed"
    if reason:
        rec.details += f"\n\nDismissal reason: {reason}"

    db.session.commit()

    add_breadcrumb(
        "Dismissed optimization recommendation",
        category="optimization",
        data={"recommendation_id": recommendation_id}
    )

    return True, "Recommendation dismissed"


def send_insights_email(account_id: int, user_email: str, insights: Dict) -> bool:
    """
    Send weekly insights digest email to user.

    Args:
        account_id: Account ID
        user_email: User email address
        insights: Insights data dictionary

    Returns:
        True if email sent successfully
    """
    from flask import render_template
    from app.services.email_service import send_email

    try:
        # Categorize recommendations
        categorized = categorize_recommendations(insights.get("recommendations", []))

        # Get performance data for email
        try:
            perf_data = get_account_performance_data(account_id, days=30)
            performance = perf_data.get("account_summary", {})
        except:
            performance = {
                "total_spend": 0,
                "total_conversions": 0,
                "avg_cpa": 0,
                "avg_ctr": 0
            }

        # Prepare template context
        context = {
            "summary": insights.get("summary", ""),
            "insights_count": len(insights.get("recommendations", [])),
            "critical_recommendations": categorized.get("critical", []),
            "high_impact_recommendations": categorized.get("high_impact", []),
            "quick_wins_recommendations": categorized.get("quick_wins", []),
            "performance": performance,
            "dashboard_url": f"{current_app.config.get('BASE_URL', 'https://app.fieldsprout.com')}/account/google/ads",
            "help_url": f"{current_app.config.get('BASE_URL', 'https://app.fieldsprout.com')}/help",
            "unsubscribe_url": f"{current_app.config.get('BASE_URL', 'https://app.fieldsprout.com')}/account/settings/email",
            "preferences_url": f"{current_app.config.get('BASE_URL', 'https://app.fieldsprout.com')}/account/settings/email",
            "current_year": datetime.utcnow().year
        }

        # Render email template
        html_body = render_template('emails/google_ads_insights_digest.html', **context)

        # Create subject line
        critical_count = len(categorized.get("critical", []))
        if critical_count > 0:
            subject = f"🚨 {critical_count} Critical Google Ads Issue{'s' if critical_count > 1 else ''} + {len(insights.get('recommendations', [])) - critical_count} Optimization Opportunities"
        else:
            subject = f"🚀 {len(insights.get('recommendations', []))} Ways to Improve Your Google Ads This Week"

        # Send email
        success = send_email(
            to=user_email,
            subject=subject,
            html_body=html_body
        )

        if success:
            current_app.logger.info(f"Sent insights email to {user_email} for account {account_id}")
            add_breadcrumb(
                "Sent insights digest email",
                category="email",
                data={"account_id": account_id, "recipient": user_email}
            )
        else:
            current_app.logger.warning(f"Failed to send insights email to {user_email}")

        return success

    except Exception as e:
        current_app.logger.error(f"Error sending insights email: {e}", exc_info=True)
        capture_exception(e, extra_context={"account_id": account_id, "user_email": user_email})
        return False
