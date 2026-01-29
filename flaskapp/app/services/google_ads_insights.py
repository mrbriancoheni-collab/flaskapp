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
from app.services.roi_calculator import ROICalculator


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

    Uses the entity-based gads_stats_daily table (entity_type + entity_id)
    and joins to ads_campaigns/keywords for names.

    Args:
        account_id: Account ID
        days: Number of days of historical data

    Returns:
        Dictionary with performance metrics
    """
    from app.models_ads import GadsStatsDaily, AdsCampaign
    from sqlalchemy import func, text as sa_text

    since = datetime.utcnow().date() - timedelta(days=days)

    with start_span("db.query", f"Fetch {days} days of Google Ads performance data"):
        # Get campaign IDs belonging to this account
        campaign_ids = [
            c.id for c in
            AdsCampaign.query.filter_by(account_id=account_id).with_entities(AdsCampaign.id).all()
        ]

        if not campaign_ids:
            return {
                "account_summary": {
                    "account_id": account_id, "period_days": days,
                    "total_spend": 0, "total_conversions": 0,
                    "avg_cpa": 0, "avg_ctr": 0,
                    "daily_spend_avg": 0, "days_of_data": 0,
                },
                "campaigns": [], "keywords": [], "search_terms": [],
            }

        # Aggregate stats for campaign-level rows
        stats = db.session.query(
            func.sum(GadsStatsDaily.cost_micros).label('total_cost_micros'),
            func.sum(GadsStatsDaily.conversions).label('total_conversions'),
            func.sum(GadsStatsDaily.clicks).label('total_clicks'),
            func.sum(GadsStatsDaily.impressions).label('total_impressions'),
            func.count(func.distinct(GadsStatsDaily.date)).label('days_of_data')
        ).filter(
            GadsStatsDaily.entity_type == 'campaign',
            GadsStatsDaily.entity_id.in_(campaign_ids),
            GadsStatsDaily.date >= since
        ).first()

        total_spend = float(stats.total_cost_micros or 0) / 1_000_000
        total_conversions = float(stats.total_conversions or 0)
        total_clicks = int(stats.total_clicks or 0)
        total_impressions = int(stats.total_impressions or 0)
        avg_cpa = total_spend / total_conversions if total_conversions > 0 else 0
        avg_ctr = total_clicks / total_impressions if total_impressions > 0 else 0
        daily_spend_avg = total_spend / max(days, 1)

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
                "total_spend": total_spend,
                "total_conversions": int(total_conversions),
                "avg_cpa": avg_cpa,
                "avg_ctr": avg_ctr,
                "daily_spend_avg": daily_spend_avg,
                "days_of_data": int(stats.days_of_data or 0),
            },
            "campaigns": campaigns,
            "keywords": keywords,
            "search_terms": search_terms,
        }


def _get_campaign_summary(account_id: int, days: int) -> List[Dict]:
    """Get campaign performance summary using entity-based stats table."""
    from app.models_ads import GadsStatsDaily, AdsCampaign
    from sqlalchemy import func

    since = datetime.utcnow().date() - timedelta(days=days)

    campaign_ids = [
        c.id for c in
        AdsCampaign.query.filter_by(account_id=account_id).with_entities(AdsCampaign.id).all()
    ]
    if not campaign_ids:
        return []

    campaigns = db.session.query(
        GadsStatsDaily.entity_id,
        func.sum(GadsStatsDaily.cost_micros).label('cost_micros'),
        func.sum(GadsStatsDaily.conversions).label('conversions'),
        func.sum(GadsStatsDaily.clicks).label('clicks'),
        func.sum(GadsStatsDaily.impressions).label('impressions'),
        func.count(func.distinct(GadsStatsDaily.date)).label('active_days')
    ).filter(
        GadsStatsDaily.entity_type == 'campaign',
        GadsStatsDaily.entity_id.in_(campaign_ids),
        GadsStatsDaily.date >= since
    ).group_by(
        GadsStatsDaily.entity_id
    ).order_by(
        func.sum(GadsStatsDaily.cost_micros).desc()
    ).limit(20).all()

    # Map campaign IDs to names
    campaign_names = {
        c.id: c.name
        for c in AdsCampaign.query.filter(AdsCampaign.id.in_(campaign_ids)).all()
    }

    results = []
    for c in campaigns:
        spend = float(c.cost_micros or 0) / 1_000_000
        conversions = float(c.conversions or 0)
        clicks = int(c.clicks or 0)
        impressions = int(c.impressions or 0)
        results.append({
            "id": c.entity_id,
            "name": campaign_names.get(c.entity_id, f"Campaign {c.entity_id}"),
            "spend": spend,
            "conversions": int(conversions),
            "cpa": spend / conversions if conversions > 0 else 0,
            "ctr": clicks / impressions if impressions > 0 else 0,
            "active_days": int(c.active_days or 0),
        })
    return results


def _get_keyword_summary(account_id: int, days: int) -> List[Dict]:
    """Get keyword performance summary using entity-based stats table."""
    from app.models_ads import GadsStatsDaily, AdsKeyword, AdsAdGroup, AdsCampaign
    from sqlalchemy import func

    since = datetime.utcnow().date() - timedelta(days=days)

    # Get keyword IDs that belong to this account (keyword -> ad_group -> campaign -> account)
    keyword_ids_q = (
        db.session.query(AdsKeyword.id)
        .join(AdsAdGroup, AdsKeyword.ad_group_id == AdsAdGroup.id)
        .join(AdsCampaign, AdsAdGroup.campaign_id == AdsCampaign.id)
        .filter(AdsCampaign.account_id == account_id)
        .all()
    )
    keyword_ids = [k.id for k in keyword_ids_q]
    if not keyword_ids:
        return []

    keywords = db.session.query(
        GadsStatsDaily.entity_id,
        func.sum(GadsStatsDaily.cost_micros).label('cost_micros'),
        func.sum(GadsStatsDaily.conversions).label('conversions'),
        func.sum(GadsStatsDaily.clicks).label('clicks'),
        func.sum(GadsStatsDaily.impressions).label('impressions'),
    ).filter(
        GadsStatsDaily.entity_type == 'keyword',
        GadsStatsDaily.entity_id.in_(keyword_ids),
        GadsStatsDaily.date >= since
    ).group_by(
        GadsStatsDaily.entity_id
    ).order_by(
        func.sum(GadsStatsDaily.cost_micros).desc()
    ).limit(50).all()

    # Map keyword IDs to text
    keyword_texts = {
        k.id: k.text
        for k in AdsKeyword.query.filter(AdsKeyword.id.in_([kw.entity_id for kw in keywords])).all()
    } if keywords else {}

    results = []
    for k in keywords:
        spend = float(k.cost_micros or 0) / 1_000_000
        conversions = float(k.conversions or 0)
        clicks = int(k.clicks or 0)
        impressions = int(k.impressions or 0)
        results.append({
            "id": k.entity_id,
            "text": keyword_texts.get(k.entity_id, f"Keyword {k.entity_id}"),
            "spend": spend,
            "conversions": int(conversions),
            "cpa": spend / conversions if conversions > 0 else 0,
            "ctr": clicks / impressions if impressions > 0 else 0,
            "clicks": clicks,
        })
    return results


def _get_search_term_summary(account_id: int, days: int) -> List[Dict]:
    """Get search term performance summary."""
    from app.models_ads import SearchTerm, AdsCampaign
    from sqlalchemy import func

    since = datetime.utcnow().date() - timedelta(days=days)

    # Get campaign IDs for this account
    campaign_ids = [
        c.id for c in
        AdsCampaign.query.filter_by(account_id=account_id).with_entities(AdsCampaign.id).all()
    ]
    if not campaign_ids:
        return []

    search_terms = db.session.query(
        SearchTerm.search_term,
        func.sum(SearchTerm.cost_micros).label('cost_micros'),
        func.sum(SearchTerm.conversions).label('conversions'),
        func.sum(SearchTerm.clicks).label('clicks'),
        func.sum(SearchTerm.impressions).label('impressions'),
    ).filter(
        SearchTerm.campaign_id.in_(campaign_ids),
        SearchTerm.date >= since
    ).group_by(
        SearchTerm.search_term
    ).order_by(
        func.sum(SearchTerm.cost_micros).desc()
    ).limit(30).all()

    results = []
    for st in search_terms:
        spend = float(st.cost_micros or 0) / 1_000_000
        clicks = int(st.clicks or 0)
        impressions = int(st.impressions or 0)
        results.append({
            "text": st.search_term,
            "spend": spend,
            "conversions": int(st.conversions or 0),
            "ctr": clicks / impressions if impressions > 0 else 0,
        })
    return results


def generate_ai_insights(account_id: int, scope: str = "all", regenerate: bool = False, customer_id: str = None) -> Dict:
    """
    Generate AI-powered optimization insights using OpenAI.

    Args:
        account_id: Account ID
        scope: Analysis scope (all, campaigns, keywords, etc.)
        regenerate: Force regeneration even if recent insights exist
        customer_id: Google Ads customer ID (for rate limiting)

    Returns:
        Dictionary with summary and categorized recommendations
    """
    from app.models_ads_grader import GoogleAdsAIAnalysisTracker

    add_breadcrumb(
        "Generating AI optimization insights",
        category="ai",
        data={"account_id": account_id, "scope": scope}
    )

    # Check rate limit for Google Ads Inspector (1 per month per customer)
    if customer_id:
        can_run, error_message = GoogleAdsAIAnalysisTracker.can_run_analysis(customer_id)
        if not can_run:
            current_app.logger.warning(f"Rate limit exceeded for customer {customer_id}")
            return {
                "error": "rate_limit_exceeded",
                "message": error_message,
                "upgrade_required": True,
                "upgrade_cta": {
                    "title": "🚀 Upgrade for Unlimited AI Analysis",
                    "message": "Get unlimited AI-powered insights and recommendations every day with a Pro plan.",
                    "benefits": [
                        "Unlimited AI analyses (no monthly limits)",
                        "Daily optimization recommendations",
                        "Automated campaign improvements",
                        "Priority support",
                        "Advanced reporting"
                    ],
                    "cta_button": "Upgrade to Pro",
                    "cta_link": "/pricing"
                }
            }

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

    # Record analysis for rate limiting (if customer_id provided)
    if customer_id:
        try:
            GoogleAdsAIAnalysisTracker.record_analysis(customer_id)
            current_app.logger.info(f"Recorded AI analysis for customer {customer_id}")
        except Exception as e:
            current_app.logger.error(f"Failed to record analysis tracking: {e}")

    return insights


def _call_openai_for_insights(account_id: int, perf_data: Dict, scope: str) -> Dict:
    """Call OpenAI API to generate insights using database-stored prompts."""
    from app.services.ai_prompts_init import get_prompt_for_service

    api_key = current_app.config.get("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY not configured")

    # Load prompt from database
    prompt_config = get_prompt_for_service('google_ads_main')

    if not prompt_config:
        current_app.logger.warning("Google Ads prompt not found in database, using fallback")
        # Fallback to basic prompt if database prompt not available
        system_prompt = "You are an expert Google Ads optimization consultant providing data-driven recommendations in JSON format."
        model = "gpt-4o-mini"
        temperature = 0.3
        max_tokens = 2000

        user_prompt = f"""Analyze this Google Ads account and provide 5-10 optimization recommendations in JSON format.

ACCOUNT PERFORMANCE (Last 30 days):
- Total Spend: ${perf_data['account_summary']['total_spend']:.2f}
- Total Conversions: {perf_data['account_summary']['total_conversions']}
- Average CPA: ${perf_data['account_summary']['avg_cpa']:.2f}
- Average CTR: {perf_data['account_summary']['avg_ctr']:.2%}

TOP CAMPAIGNS: {json.dumps(perf_data['campaigns'][:10], indent=2)}
TOP KEYWORDS: {json.dumps(perf_data['keywords'][:20], indent=2)}
SEARCH TERMS: {json.dumps(perf_data['search_terms'][:15], indent=2)}

Return JSON with: {{"summary": "...", "recommendations": [...]}}"""
    else:
        # Use database prompt
        system_prompt = prompt_config.get('system_message', '')
        model = prompt_config.get('model', 'gpt-4o-mini')
        temperature = prompt_config.get('temperature', 0.7)
        max_tokens = prompt_config.get('max_tokens', 2000)

        # Format the prompt template with actual data
        performance_summary = f"""- Total Spend: ${perf_data['account_summary']['total_spend']:.2f}
- Total Conversions: {perf_data['account_summary']['total_conversions']}
- Average CPA: ${perf_data['account_summary']['avg_cpa']:.2f}
- Average CTR: {perf_data['account_summary']['avg_ctr']:.2%}
- Daily Spend: ${perf_data['account_summary']['daily_spend_avg']:.2f}"""

        campaigns_data = json.dumps(perf_data['campaigns'][:10], indent=2)
        ad_groups_data = json.dumps(perf_data.get('ad_groups', [])[:10], indent=2) if 'ad_groups' in perf_data else "[]"
        keywords_data = json.dumps(perf_data['keywords'][:20], indent=2)
        search_terms_data = json.dumps(perf_data['search_terms'][:15], indent=2)

        user_prompt = prompt_config.get('prompt_template', '').format(
            performance_summary=performance_summary,
            campaigns_data=campaigns_data,
            ad_groups_data=ad_groups_data,
            keywords_data=keywords_data,
            search_terms_data=search_terms_data
        )

    # Call OpenAI
    client = OpenAI(api_key=api_key)

    response = client.chat.completions.create(
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
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

    # Add upgrade CTA for paid plan
    result["upgrade_cta"] = {
        "title": "🚀 Ready to Implement These Optimizations?",
        "message": "Upgrade to a paid plan to unlock automated implementation, continuous monitoring, and expert support to help you achieve these results faster.",
        "benefits": [
            "Automated campaign optimization based on AI recommendations",
            "Real-time performance monitoring and alerts",
            "Monthly strategic reviews with optimization experts",
            "Priority support for campaign issues",
            "Advanced reporting and ROI tracking"
        ],
        "cta_button": "Upgrade to Pro",
        "cta_link": "/pricing"
    }

    return result


def _store_recommendations(account_id: int, recommendations: List[Dict], perf_data: Dict):
    """Store recommendations in database with confidence scoring and ROI calculations."""

    # Clear old open recommendations for this account
    OptimizerRecommendation.query.filter(
        OptimizerRecommendation.account_id == account_id,
        OptimizerRecommendation.status == 'open'
    ).update({"status": "superseded"})

    # Get performance data for ROI calculations
    summary = perf_data.get("account_summary", {})
    total_spend = summary.get("total_spend", 0)
    total_conversions = summary.get("total_conversions", 0)
    days_of_data = summary.get("days_of_data", 30)

    for rec in recommendations:
        # Calculate confidence score
        confidence = _calculate_confidence(rec, perf_data)

        # Calculate ROI based on category and severity
        category = rec.get("category", "general")
        severity = rec.get("severity", 3)

        # Calculate ROI impact
        roi_data = ROICalculator.calculate_combined_roi(
            current_spend=total_spend,
            current_conversions=total_conversions,
            avg_customer_value=None,  # Don't have this data yet
            category=category,
            timeframe_days=days_of_data,
            severity=severity
        )

        # Get effort estimate
        effort = ROICalculator.estimate_implementation_effort(category, severity)

        # Enhance expected_impact with ROI data
        impact_summary = roi_data['roi_summary']
        if not impact_summary or impact_summary == "Efficiency improvement":
            # Fall back to original AI-generated impact
            impact_summary = rec.get("expected_impact", "Performance improvement expected")

        # Store ROI data as JSON in a new field (or append to details)
        roi_json = {
            'monthly_savings': roi_data['savings']['monthly_savings'],
            'annual_savings': roi_data['savings']['annual_savings'],
            'monthly_leads': roi_data['leads']['monthly_new_leads'],
            'annual_leads': roi_data['leads']['annual_new_leads'],
            'total_monthly_value': roi_data['total_monthly_value'],
            'savings_percentage': roi_data['savings']['percentage_reduction'],
            'leads_percentage': roi_data['leads']['percentage_increase'],
            'effort': effort,
            'summary': impact_summary
        }

        # Enhance description with ROI context
        enhanced_description = rec["description"]
        if roi_data['savings']['monthly_savings'] > 0:
            enhanced_description += f"\n\n💰 Estimated savings: ${roi_data['savings']['monthly_savings']:,.0f}/month"
        if roi_data['leads']['monthly_new_leads'] > 0:
            enhanced_description += f"\n📈 Estimated lead increase: +{roi_data['leads']['monthly_new_leads']:.0f} leads/month"
        if effort['time_estimate']:
            enhanced_description += f"\n⏱️ Implementation time: {effort['time_estimate']} ({effort['difficulty']})"

        # Create database record
        db_rec = OptimizerRecommendation(
            account_id=account_id,
            scope_type=rec.get("action", {}).get("type", "account"),
            scope_id=int(rec.get("action", {}).get("target_id") or 0),
            category=category,
            title=rec["title"],
            details=enhanced_description,
            expected_impact=json.dumps(roi_json),  # Store ROI data as JSON
            severity=severity,
            suggested_action_json=json.dumps(rec.get("action", {})),
            status="open"
        )

        db.session.add(db_rec)

    db.session.commit()
    current_app.logger.info(f"Stored {len(recommendations)} recommendations with ROI data for account {account_id}")


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


def _execute_recommendation_action(account_id: int, action: dict) -> dict:
    """
    Execute a recommendation action via Google Ads API.

    Args:
        account_id: Account ID
        action: Action dictionary with type and parameters

    Returns:
        dict with 'success' key and either 'result' or 'error'
    """
    from sqlalchemy import text

    action_type = action.get('type', 'unknown')

    # Get Google Ads credentials for this account
    try:
        with db.engine.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT customer_id, credentials_json
                    FROM google_oauth_tokens
                    WHERE account_id = :account_id AND product = 'ads'
                    ORDER BY id DESC LIMIT 1
                """),
                {"account_id": account_id}
            )
            row = result.mappings().first()

        if not row:
            return {'success': False, 'error': 'No Google Ads credentials found for account'}

        customer_id = row['customer_id']
        creds = json.loads(row['credentials_json']) if isinstance(row['credentials_json'], str) else row['credentials_json']
        refresh_token = creds.get('refresh_token')

        if not refresh_token:
            return {'success': False, 'error': 'No refresh token found in credentials'}

        # Initialize executor
        from app.agents.executor import GoogleAdsAgentExecutor

        developer_token = current_app.config.get('GOOGLE_ADS_DEVELOPER_TOKEN')
        if not developer_token:
            return {'success': False, 'error': 'GOOGLE_ADS_DEVELOPER_TOKEN not configured'}

        executor = GoogleAdsAgentExecutor(
            refresh_token=refresh_token,
            developer_token=developer_token,
            client_customer_id=customer_id
        )

        # Execute based on action type
        if action_type == 'add_negative_keyword':
            campaign_id = action.get('campaign_id')
            keyword_text = action.get('keyword_text')
            match_type = action.get('match_type', 'PHRASE')

            if not campaign_id or not keyword_text:
                return {'success': False, 'error': 'Missing campaign_id or keyword_text'}

            result = executor.add_negative_keyword(campaign_id, keyword_text, match_type)
            return result

        elif action_type == 'pause_keyword':
            ad_group_id = action.get('ad_group_id')
            keyword_id = action.get('keyword_id')

            if not ad_group_id or not keyword_id:
                return {'success': False, 'error': 'Missing ad_group_id or keyword_id'}

            result = executor.pause_keyword(ad_group_id, keyword_id)
            return result

        elif action_type == 'adjust_keyword_bid':
            ad_group_id = action.get('ad_group_id')
            keyword_id = action.get('keyword_id')
            bid_change_pct = action.get('bid_change_pct', 0)

            if not ad_group_id or not keyword_id:
                return {'success': False, 'error': 'Missing ad_group_id or keyword_id'}

            result = executor.adjust_keyword_bid(ad_group_id, keyword_id, bid_change_pct)
            return result

        elif action_type == 'adjust_campaign_bids':
            campaign_id = action.get('campaign_id')
            bid_change_pct = action.get('bid_change_pct', 0)

            if not campaign_id:
                return {'success': False, 'error': 'Missing campaign_id'}

            result = executor.adjust_campaign_bids(campaign_id, bid_change_pct)
            return result

        elif action_type == 'adjust_daily_budget':
            campaign_id = action.get('campaign_id')
            new_budget = action.get('new_budget')

            if not campaign_id or new_budget is None:
                return {'success': False, 'error': 'Missing campaign_id or new_budget'}

            result = executor.adjust_daily_budget(campaign_id, new_budget)
            return result

        elif action_type == 'pause_campaign':
            campaign_id = action.get('campaign_id')

            if not campaign_id:
                return {'success': False, 'error': 'Missing campaign_id'}

            result = executor.pause_campaign(campaign_id)
            return result

        elif action_type == 'reallocate_budget':
            from_campaigns = action.get('from_campaigns', [])
            to_campaigns = action.get('to_campaigns', [])
            amount = action.get('amount', 0)

            if not from_campaigns or not to_campaigns or not amount:
                return {'success': False, 'error': 'Missing from_campaigns, to_campaigns, or amount'}

            result = executor.reallocate_budget(from_campaigns, to_campaigns, amount)
            return result

        elif action_type in ('review_keywords', 'review_budgets', 'add_negatives'):
            # These are manual review actions - mark as acknowledged
            return {'success': True, 'result': 'Manual review action acknowledged', 'manual': True}

        else:
            return {'success': False, 'error': f'Unknown action type: {action_type}'}

    except Exception as e:
        current_app.logger.error(f"Failed to execute recommendation action: {e}", exc_info=True)
        capture_exception(e, extra_context={"account_id": account_id, "action": action})
        return {'success': False, 'error': str(e)}


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

        # Execute the recommendation via Google Ads API
        execution_result = _execute_recommendation_action(rec.account_id, action)

        if execution_result.get('success'):
            optimizer_action.status = "executed"
            optimizer_action.result_json = json.dumps(execution_result)
            db.session.commit()
            return True, f"Recommendation applied successfully: {rec.title}"
        else:
            # Mark as failed but keep the record
            optimizer_action.status = "failed"
            optimizer_action.result_json = json.dumps(execution_result)
            db.session.commit()
            return False, f"Failed to execute recommendation: {execution_result.get('error', 'Unknown error')}"

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
