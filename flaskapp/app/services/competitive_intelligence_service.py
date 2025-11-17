# app/services/competitive_intelligence_service.py
"""
Competitive Intelligence Service

Collects and analyzes competitive data from:
1. Google Ads Auction Insights (official API)
2. Search term reports (competitor ad triggers)
3. Ad position/impression share data
4. Competitive CPCs from keyword planner
"""

from typing import Dict, List, Any, Optional
from datetime import datetime, date, timedelta
from sqlalchemy import text
from app import db


def fetch_auction_insights(
    refresh_token: str,
    customer_id: str,
    campaign_id: str,
    start_date: date,
    end_date: date
) -> Dict[str, Any]:
    """
    Fetch Auction Insights data from Google Ads API.

    Shows:
    - Competitors in the same auctions
    - Impression share vs competitors
    - Position above rate
    - Top of page rate
    - Overlap rate

    Args:
        refresh_token: Google Ads refresh token
        customer_id: Google Ads customer ID
        campaign_id: Campaign ID
        start_date: Start date
        end_date: End date

    Returns:
        Auction insights data
    """
    try:
        from app.services.google_ads_alerts_service import get_google_ads_client
        from google.ads.googleads.client import GoogleAdsClient

        client = get_google_ads_client(refresh_token, customer_id)
        ga_service = client.get_service("GoogleAdsService")

        # Query auction insights
        query = f"""
            SELECT
                auction_insight_search_term_view.domain,
                metrics.search_impression_share,
                metrics.search_absolute_top_impression_share,
                metrics.search_rank_lost_impression_share,
                metrics.search_overlap_rate,
                metrics.search_position_above_rate,
                metrics.search_outranking_share
            FROM auction_insight_search_term_view
            WHERE segments.date >= '{start_date.strftime('%Y-%m-%d')}'
              AND segments.date <= '{end_date.strftime('%Y-%m-%d')}'
              AND campaign.id = {campaign_id}
            ORDER BY metrics.search_impression_share DESC
            LIMIT 20
        """

        response = ga_service.search(customer_id=customer_id.replace('-', ''), query=query)

        competitors = []
        for row in response:
            competitors.append({
                'domain': row.auction_insight_search_term_view.domain,
                'impression_share': row.metrics.search_impression_share,
                'top_of_page_rate': row.metrics.search_absolute_top_impression_share,
                'rank_lost_share': row.metrics.search_rank_lost_impression_share,
                'overlap_rate': row.metrics.search_overlap_rate,
                'position_above_rate': row.metrics.search_position_above_rate,
                'outranking_share': row.metrics.search_outranking_share
            })

        # Store in database
        store_auction_insights(customer_id, campaign_id, start_date, end_date, competitors)

        return {
            "success": True,
            "competitors": competitors,
            "data_range": {
                "start": start_date.isoformat(),
                "end": end_date.isoformat()
            }
        }

    except Exception as e:
        print(f"Error fetching auction insights: {str(e)}")
        return {
            "success": False,
            "error": str(e)
        }


def store_auction_insights(
    customer_id: str,
    campaign_id: str,
    start_date: date,
    end_date: date,
    competitors: List[Dict[str, Any]]
) -> None:
    """Store auction insights in database."""
    # Delete old data for this period
    delete_query = text("""
        DELETE FROM competitive_auction_insights
        WHERE customer_id = :customer_id
          AND campaign_id = :campaign_id
          AND data_date BETWEEN :start_date AND :end_date
    """)

    with db.engine.begin() as conn:
        conn.execute(delete_query, {
            "customer_id": customer_id,
            "campaign_id": campaign_id,
            "start_date": start_date,
            "end_date": end_date
        })

        # Insert new data
        for competitor in competitors:
            insert_query = text("""
                INSERT INTO competitive_auction_insights
                    (customer_id, campaign_id, data_date, competitor_domain,
                     impression_share, top_of_page_rate, rank_lost_share,
                     overlap_rate, position_above_rate, outranking_share,
                     created_at)
                VALUES
                    (:customer_id, :campaign_id, :data_date, :domain,
                     :impression_share, :top_rate, :rank_lost,
                     :overlap, :position_above, :outranking,
                     NOW())
            """)

            conn.execute(insert_query, {
                "customer_id": customer_id,
                "campaign_id": campaign_id,
                "data_date": end_date,  # Use end date as snapshot date
                "domain": competitor['domain'],
                "impression_share": competitor['impression_share'],
                "top_rate": competitor['top_of_page_rate'],
                "rank_lost": competitor['rank_lost_share'],
                "overlap": competitor['overlap_rate'],
                "position_above": competitor['position_above_rate'],
                "outranking": competitor['outranking_share']
            })


def analyze_competitive_landscape(
    account_id: int,
    campaign_id: int,
    lookback_days: int = 30
) -> Dict[str, Any]:
    """
    Analyze competitive landscape and provide insights.

    Args:
        account_id: Account ID
        campaign_id: Campaign ID
        lookback_days: Days of data to analyze

    Returns:
        Competitive analysis
    """
    end_date = date.today()
    start_date = end_date - timedelta(days=lookback_days)

    # Get auction insights from database
    query = text("""
        SELECT
            competitor_domain,
            AVG(impression_share) as avg_impression_share,
            AVG(top_of_page_rate) as avg_top_rate,
            AVG(position_above_rate) as avg_position_above,
            AVG(outranking_share) as avg_outranking_share,
            COUNT(*) as data_points
        FROM competitive_auction_insights cai
        JOIN ads_campaigns ac ON ac.google_campaign_id = cai.campaign_id
        WHERE ac.id = :campaign_id
          AND ac.account_id = :account_id
          AND cai.data_date BETWEEN :start_date AND :end_date
        GROUP BY competitor_domain
        ORDER BY avg_impression_share DESC
    """)

    with db.engine.connect() as conn:
        result = conn.execute(query, {
            "account_id": account_id,
            "campaign_id": campaign_id,
            "start_date": start_date,
            "end_date": end_date
        })

        competitors = [dict(row._mapping) for row in result]

    if not competitors:
        return {
            "success": True,
            "message": "No competitive data available. Fetch auction insights first.",
            "competitors": []
        }

    # Analyze competitive threats
    threats = []
    opportunities = []

    for comp in competitors:
        # High threat: competitor outranks you significantly
        if comp['avg_position_above'] > 0.5:  # Above you 50%+ of time
            threats.append({
                "competitor": comp['competitor_domain'],
                "threat_level": "high",
                "reason": f"Outranks you {comp['avg_position_above']*100:.0f}% of the time",
                "recommendation": "Increase bids or improve Quality Score to compete"
            })

        # Opportunity: you outrank them
        if comp['avg_outranking_share'] > 0.6:  # You outrank them 60%+ of time
            opportunities.append({
                "competitor": comp['competitor_domain'],
                "opportunity": "Dominant position",
                "recommendation": "Maintain current strategy - you're winning"
            })

        # High overlap: competing for same searches
        if comp['avg_impression_share'] > 0.4:  # They get 40%+ impression share
            threats.append({
                "competitor": comp['competitor_domain'],
                "threat_level": "medium",
                "reason": f"High overlap - they capture {comp['avg_impression_share']*100:.0f}% impression share",
                "recommendation": "Consider increasing budget to capture more market share"
            })

    return {
        "success": True,
        "period": f"{start_date.isoformat()} to {end_date.isoformat()}",
        "total_competitors": len(competitors),
        "top_competitors": competitors[:5],
        "threats": threats,
        "opportunities": opportunities,
        "budget_recommendation": get_competitive_budget_recommendation(competitors, threats)
    }


def get_competitive_budget_recommendation(
    competitors: List[Dict[str, Any]],
    threats: List[Dict[str, Any]]
) -> str:
    """Generate budget recommendation based on competitive landscape."""
    if not competitors:
        return "No competitive data available"

    high_competition = len([c for c in competitors if c['avg_impression_share'] > 0.3])
    high_threats = len([t for t in threats if t['threat_level'] == 'high'])

    if high_threats >= 2:
        return "HIGH COMPETITION: Increase budget by 30-50% to maintain visibility"
    elif high_competition >= 3:
        return "MODERATE COMPETITION: Consider 15-30% budget increase"
    elif len(competitors) <= 2:
        return "LOW COMPETITION: Maintain current budget - you have good market position"
    else:
        return "BALANCED MARKET: Monitor competitors and adjust as needed"


def track_competitor_position_changes(
    account_id: int,
    campaign_id: int,
    competitor_domain: str,
    days: int = 30
) -> Dict[str, Any]:
    """
    Track how a specific competitor's position has changed over time.

    Args:
        account_id: Account ID
        campaign_id: Campaign ID
        competitor_domain: Competitor domain to track
        days: Days to analyze

    Returns:
        Position change analysis
    """
    end_date = date.today()
    start_date = end_date - timedelta(days=days)

    query = text("""
        SELECT
            cai.data_date,
            cai.impression_share,
            cai.position_above_rate,
            cai.outranking_share,
            cai.top_of_page_rate
        FROM competitive_auction_insights cai
        JOIN ads_campaigns ac ON ac.google_campaign_id = cai.campaign_id
        WHERE ac.id = :campaign_id
          AND ac.account_id = :account_id
          AND cai.competitor_domain = :domain
          AND cai.data_date BETWEEN :start_date AND :end_date
        ORDER BY cai.data_date ASC
    """)

    with db.engine.connect() as conn:
        result = conn.execute(query, {
            "account_id": account_id,
            "campaign_id": campaign_id,
            "domain": competitor_domain,
            "start_date": start_date,
            "end_date": end_date
        })

        history = [dict(row._mapping) for row in result]

    if len(history) < 2:
        return {
            "success": True,
            "message": "Insufficient data for trend analysis",
            "history": history
        }

    # Calculate trends
    first_week = history[:7] if len(history) >= 7 else history[:len(history)//2]
    last_week = history[-7:] if len(history) >= 7 else history[len(history)//2:]

    avg_position_above_first = sum(h['position_above_rate'] for h in first_week) / len(first_week)
    avg_position_above_last = sum(h['position_above_rate'] for h in last_week) / len(last_week)

    position_change = (avg_position_above_last - avg_position_above_first) * 100

    trend = "improving" if position_change < -5 else "worsening" if position_change > 5 else "stable"

    alert = None
    if position_change > 10:
        alert = f"⚠️ ALERT: {competitor_domain} is increasingly outranking you ({position_change:+.0f}% change)"

    return {
        "success": True,
        "competitor": competitor_domain,
        "trend": trend,
        "position_change_pct": round(position_change, 1),
        "history": history,
        "alert": alert
    }


def get_search_term_competitors(
    refresh_token: str,
    customer_id: str,
    campaign_id: str,
    start_date: date,
    end_date: date
) -> Dict[str, Any]:
    """
    Analyze search terms to find which competitors trigger ads.

    This helps identify:
    - Competitor brand terms you're bidding on
    - Terms where competitors appear frequently

    Args:
        refresh_token: Google Ads refresh token
        customer_id: Customer ID
        campaign_id: Campaign ID
        start_date: Start date
        end_date: End date

    Returns:
        Search term competitive analysis
    """
    try:
        from app.services.google_ads_alerts_service import get_google_ads_client

        client = get_google_ads_client(refresh_token, customer_id)
        ga_service = client.get_service("GoogleAdsService")

        # Get search terms with impression share data
        query = f"""
            SELECT
                search_term_view.search_term,
                metrics.impressions,
                metrics.clicks,
                metrics.conversions,
                metrics.search_impression_share,
                metrics.search_rank_lost_impression_share
            FROM search_term_view
            WHERE segments.date >= '{start_date.strftime('%Y-%m-%d')}'
              AND segments.date <= '{end_date.strftime('%Y-%m-%d')}'
              AND campaign.id = {campaign_id}
              AND metrics.impressions > 10
            ORDER BY metrics.impressions DESC
            LIMIT 100
        """

        response = ga_service.search(customer_id=customer_id.replace('-', ''), query=query)

        search_terms = []
        for row in response:
            search_term = row.search_term_view.search_term

            # Flag potential competitor terms
            is_competitor_term = any(word in search_term.lower() for word in ['vs', 'versus', 'compared', 'alternative'])

            search_terms.append({
                'search_term': search_term,
                'impressions': row.metrics.impressions,
                'clicks': row.metrics.clicks,
                'conversions': row.metrics.conversions,
                'impression_share': row.metrics.search_impression_share,
                'rank_lost_share': row.metrics.search_rank_lost_impression_share,
                'is_competitor_term': is_competitor_term,
                'lost_opportunity': row.metrics.search_rank_lost_impression_share > 0.2  # Losing 20%+ to rank
            })

        # Identify high-opportunity terms (low impression share)
        opportunities = [st for st in search_terms if st['impression_share'] < 0.5 and st['conversions'] > 0]

        return {
            "success": True,
            "search_terms": search_terms,
            "competitor_terms": [st for st in search_terms if st['is_competitor_term']],
            "lost_opportunities": [st for st in search_terms if st['lost_opportunity']],
            "high_opportunity_terms": opportunities
        }

    except Exception as e:
        print(f"Error fetching search terms: {str(e)}")
        return {
            "success": False,
            "error": str(e)
        }


def estimate_competitor_budget(
    competitor_impression_share: float,
    your_daily_budget: float,
    your_impression_share: float
) -> float:
    """
    Estimate competitor's daily budget based on impression share.

    Rough estimation: If they have 40% impression share and you have 30%,
    and you spend $100/day, they likely spend ~$133/day.

    Args:
        competitor_impression_share: Competitor's impression share (0-1)
        your_daily_budget: Your daily budget
        your_impression_share: Your impression share (0-1)

    Returns:
        Estimated competitor daily budget
    """
    if your_impression_share == 0:
        return 0

    # Rough estimation (assumes similar CPCs)
    estimated_budget = (competitor_impression_share / your_impression_share) * your_daily_budget

    return round(estimated_budget, 2)
