# app/services/quick_wins_service.py
"""
Quick Wins Service for Google Ads optimization recommendations.

Analyzes account data to identify the top 3 immediate action items with:
- ROI estimates
- Difficulty/time estimates
- One-click actions
- Visual priority indicators

Quick Win Types:
1. Negative Keywords - Identify wasted spend on irrelevant searches
2. Mobile Bid Adjustments - Optimize for mobile conversion rates
3. Pause Low Performers - Stop campaigns/ad groups with poor ROI
4. Budget Reallocation - Move budget from low to high performers
5. Quality Score Improvements - Fix low QS keywords
"""

from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import logging

from flask import current_app
from sqlalchemy import func

from app import db
from app.models import Account
from app.services.google_ads_service import client_from_refresh

logger = logging.getLogger(__name__)


class QuickWin:
    """Represents a single quick win recommendation."""

    def __init__(
        self,
        win_type: str,
        title: str,
        description: str,
        impact_monthly_value: float,
        impact_leads: int = 0,
        difficulty: str = "easy",  # easy, medium, hard
        time_estimate: str = "5 mins",
        action_url: str = None,
        action_text: str = "Take Action",
        data: Dict[str, Any] = None,
        priority_score: float = 0.0
    ):
        self.win_type = win_type
        self.title = title
        self.description = description
        self.impact_monthly_value = impact_monthly_value
        self.impact_leads = impact_leads
        self.difficulty = difficulty
        self.time_estimate = time_estimate
        self.action_url = action_url
        self.action_text = action_text
        self.data = data or {}
        self.priority_score = priority_score

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "win_type": self.win_type,
            "title": self.title,
            "description": self.description,
            "impact_monthly_value": round(self.impact_monthly_value, 2),
            "impact_leads": self.impact_leads,
            "difficulty": self.difficulty,
            "time_estimate": self.time_estimate,
            "action_url": self.action_url,
            "action_text": self.action_text,
            "data": self.data,
            "priority_score": round(self.priority_score, 2)
        }


class QuickWinsService:
    """Service for identifying quick win optimization opportunities."""

    # Difficulty multipliers for priority scoring (easier = higher priority)
    DIFFICULTY_MULTIPLIERS = {
        "easy": 2.0,
        "medium": 1.5,
        "hard": 1.0
    }

    def __init__(self):
        self.wins = []

    def _get_google_ads_client(self, account: Account):
        """Get Google Ads client for an account."""
        if not account.google_refresh_token:
            raise ValueError(f"Account {account.id} has no Google Ads connection")

        login_customer_id = account.google_login_customer_id or account.google_customer_id
        return client_from_refresh(account.google_refresh_token, login_customer_id)

    def _query_google_ads(self, account: Account, query: str):
        """Execute a Google Ads query."""
        client = self._get_google_ads_client(account)
        customer_id = account.google_customer_id

        if not customer_id:
            raise ValueError(f"Account {account.id} has no customer ID")

        ga_service = client.get_service("GoogleAdsService")
        stream = ga_service.search_stream(customer_id=customer_id, query=query)

        results = []
        for batch in stream:
            for row in batch.results:
                results.append(row)

        return results

    def _calculate_priority_score(self, value: float, leads: int, difficulty: str) -> float:
        """
        Calculate priority score for ranking quick wins.

        Score = (monthly_value + leads*avg_lead_value) * difficulty_multiplier
        Higher score = higher priority
        """
        avg_lead_value = 500  # Assume $500 per lead if not specified
        total_value = value + (leads * avg_lead_value)
        multiplier = self.DIFFICULTY_MULTIPLIERS.get(difficulty, 1.0)

        return total_value * multiplier

    def get_top_quick_wins(self, account: Account, limit: int = 3) -> List[QuickWin]:
        """
        Get top N quick wins for an account.

        Returns the highest priority recommendations based on value and ease.
        """
        self.wins = []

        try:
            # Check each type of quick win
            self._check_negative_keywords(account)
            self._check_mobile_bid_adjustments(account)
            self._check_low_performing_campaigns(account)
            self._check_budget_reallocation(account)
            self._check_quality_score_improvements(account)

            # Sort by priority score (highest first)
            self.wins.sort(key=lambda w: w.priority_score, reverse=True)

            # Return top N
            return self.wins[:limit]

        except Exception as e:
            logger.error(f"Error getting quick wins for account {account.id}: {e}")
            return []

    def _check_negative_keywords(self, account: Account):
        """
        Identify wasted spend on irrelevant search terms.

        Analyzes search query report for terms with:
        - High spend
        - Zero conversions
        - Low CTR
        """
        try:
            # Query for search terms with spend but no conversions (last 30 days)
            query = """
                SELECT
                    search_term_view.search_term,
                    metrics.cost_micros,
                    metrics.clicks,
                    metrics.impressions,
                    metrics.conversions,
                    campaign.id,
                    campaign.name
                FROM search_term_view
                WHERE segments.date DURING LAST_30_DAYS
                AND metrics.cost_micros > 0
                AND metrics.conversions = 0
            """

            response = self._query_google_ads(account, query)

            # Aggregate wasted spend by search term
            wasted_terms = {}
            for row in response:
                search_term = row.search_term_view.search_term
                cost_micros = row.metrics.cost_micros
                clicks = row.metrics.clicks
                impressions = row.metrics.impressions
                campaign_name = row.campaign.name

                if search_term not in wasted_terms:
                    wasted_terms[search_term] = {
                        "cost_micros": 0,
                        "clicks": 0,
                        "impressions": 0,
                        "campaigns": set()
                    }

                wasted_terms[search_term]["cost_micros"] += cost_micros
                wasted_terms[search_term]["clicks"] += clicks
                wasted_terms[search_term]["impressions"] += impressions
                wasted_terms[search_term]["campaigns"].add(campaign_name)

            # Filter for significant wasted spend (>$50 in 30 days)
            significant_waste = {
                term: data for term, data in wasted_terms.items()
                if data["cost_micros"] >= 50_000_000  # $50 in micros
            }

            if significant_waste:
                # Calculate total monthly waste
                total_waste_micros = sum(data["cost_micros"] for data in significant_waste.values())
                total_waste_monthly = (total_waste_micros / 1_000_000)  # 30 days of data

                # Sort by spend
                top_terms = sorted(
                    significant_waste.items(),
                    key=lambda x: x[1]["cost_micros"],
                    reverse=True
                )[:15]

                if total_waste_monthly >= 50:  # Only recommend if >= $50/month savings
                    win = QuickWin(
                        win_type="negative_keywords",
                        title=f"Add {len(top_terms)} Negative Keywords",
                        description=f"Block irrelevant search terms wasting ${total_waste_monthly:.0f}/month with zero conversions",
                        impact_monthly_value=total_waste_monthly,
                        impact_leads=0,
                        difficulty="easy",
                        time_estimate="5 mins",
                        action_url=f"/account/google/ads/negative-keywords",
                        action_text="Add Negative Keywords",
                        data={
                            "total_terms": len(top_terms),
                            "total_waste": round(total_waste_monthly, 2),
                            "top_terms": [
                                {
                                    "term": term,
                                    "cost": round(data["cost_micros"] / 1_000_000, 2),
                                    "clicks": data["clicks"],
                                    "campaigns": list(data["campaigns"])
                                }
                                for term, data in top_terms
                            ]
                        }
                    )
                    win.priority_score = self._calculate_priority_score(
                        total_waste_monthly, 0, "easy"
                    )
                    self.wins.append(win)

        except Exception as e:
            logger.error(f"Error checking negative keywords: {e}")

    def _check_mobile_bid_adjustments(self, account: Account):
        """
        Identify mobile bid adjustment opportunities.

        Compares mobile vs desktop performance to recommend bid adjustments.
        """
        try:
            # Query for device performance (last 30 days)
            query = """
                SELECT
                    segments.device,
                    metrics.cost_micros,
                    metrics.conversions,
                    metrics.clicks,
                    metrics.impressions
                FROM campaign
                WHERE segments.date DURING LAST_30_DAYS
            """

            response = self._query_google_ads(account, query)

            # Aggregate by device
            device_data = {}
            for row in response:
                device = row.segments.device.name  # MOBILE, DESKTOP, TABLET

                if device not in device_data:
                    device_data[device] = {
                        "cost_micros": 0,
                        "conversions": 0,
                        "clicks": 0,
                        "impressions": 0
                    }

                device_data[device]["cost_micros"] += row.metrics.cost_micros
                device_data[device]["conversions"] += row.metrics.conversions
                device_data[device]["clicks"] += row.metrics.clicks
                device_data[device]["impressions"] += row.metrics.impressions

            # Calculate CPL by device
            mobile_data = device_data.get("MOBILE", {})
            desktop_data = device_data.get("DESKTOP", {})

            if mobile_data and desktop_data:
                mobile_cost = mobile_data["cost_micros"] / 1_000_000
                mobile_conversions = mobile_data["conversions"]
                desktop_cost = desktop_data["cost_micros"] / 1_000_000
                desktop_conversions = desktop_data["conversions"]

                if mobile_conversions > 0 and desktop_conversions > 0:
                    mobile_cpl = mobile_cost / mobile_conversions
                    desktop_cpl = desktop_cost / desktop_conversions

                    # If mobile CPL is significantly better, recommend bid increase
                    if mobile_cpl < desktop_cpl * 0.7:  # 30% better
                        # Estimate impact of 20% bid increase
                        estimated_increase_leads = int(mobile_conversions * 0.15)  # Conservative 15% more leads
                        avg_lead_value = 500  # Assume $500 per lead
                        estimated_value = estimated_increase_leads * avg_lead_value

                        win = QuickWin(
                            win_type="mobile_bid_adjustment",
                            title="Increase Mobile Bids by 20%",
                            description=f"Mobile CPL (${mobile_cpl:.2f}) is {((desktop_cpl - mobile_cpl) / desktop_cpl * 100):.0f}% better than desktop. Capture more mobile leads.",
                            impact_monthly_value=0,
                            impact_leads=estimated_increase_leads,
                            difficulty="easy",
                            time_estimate="2 mins",
                            action_url=f"/account/google/ads/bid-adjustments",
                            action_text="Adjust Mobile Bids",
                            data={
                                "mobile_cpl": round(mobile_cpl, 2),
                                "desktop_cpl": round(desktop_cpl, 2),
                                "mobile_conversions": mobile_conversions,
                                "estimated_additional_leads": estimated_increase_leads,
                                "recommended_adjustment": "+20%"
                            }
                        )
                        win.priority_score = self._calculate_priority_score(
                            0, estimated_increase_leads, "easy"
                        )
                        self.wins.append(win)

                    # If mobile CPL is worse, recommend bid decrease
                    elif mobile_cpl > desktop_cpl * 1.5:  # 50% worse
                        estimated_savings = mobile_cost * 0.2  # 20% savings from bid decrease

                        win = QuickWin(
                            win_type="mobile_bid_adjustment",
                            title="Decrease Mobile Bids by 20%",
                            description=f"Mobile CPL (${mobile_cpl:.2f}) is {((mobile_cpl - desktop_cpl) / desktop_cpl * 100):.0f}% worse than desktop. Reduce wasted spend.",
                            impact_monthly_value=estimated_savings,
                            impact_leads=0,
                            difficulty="easy",
                            time_estimate="2 mins",
                            action_url=f"/account/google/ads/bid-adjustments",
                            action_text="Adjust Mobile Bids",
                            data={
                                "mobile_cpl": round(mobile_cpl, 2),
                                "desktop_cpl": round(desktop_cpl, 2),
                                "mobile_cost": round(mobile_cost, 2),
                                "estimated_monthly_savings": round(estimated_savings, 2),
                                "recommended_adjustment": "-20%"
                            }
                        )
                        win.priority_score = self._calculate_priority_score(
                            estimated_savings, 0, "easy"
                        )
                        self.wins.append(win)

        except Exception as e:
            logger.error(f"Error checking mobile bid adjustments: {e}")

    def _check_low_performing_campaigns(self, account: Account):
        """
        Identify campaigns with poor ROI that should be paused.

        Looks for campaigns with:
        - High spend
        - Zero or very low conversions
        - Running for at least 30 days
        """
        try:
            # Query for campaign performance (last 60 days)
            query = """
                SELECT
                    campaign.id,
                    campaign.name,
                    campaign.status,
                    metrics.cost_micros,
                    metrics.conversions,
                    metrics.clicks,
                    metrics.impressions
                FROM campaign
                WHERE segments.date DURING LAST_60_DAYS
                AND campaign.status = 'ENABLED'
            """

            response = self._query_google_ads(account, query)

            # Aggregate by campaign
            campaign_data = {}
            for row in response:
                campaign_id = row.campaign.id
                campaign_name = row.campaign.name

                if campaign_id not in campaign_data:
                    campaign_data[campaign_id] = {
                        "name": campaign_name,
                        "cost_micros": 0,
                        "conversions": 0,
                        "clicks": 0,
                        "impressions": 0
                    }

                campaign_data[campaign_id]["cost_micros"] += row.metrics.cost_micros
                campaign_data[campaign_id]["conversions"] += row.metrics.conversions
                campaign_data[campaign_id]["clicks"] += row.metrics.clicks
                campaign_data[campaign_id]["impressions"] += row.metrics.impressions

            # Find poor performers: spend >$200 in 60 days with 0 conversions
            poor_performers = []
            total_waste = 0

            for campaign_id, data in campaign_data.items():
                cost = data["cost_micros"] / 1_000_000
                conversions = data["conversions"]

                if cost >= 200 and conversions == 0:
                    poor_performers.append({
                        "id": campaign_id,
                        "name": data["name"],
                        "cost": cost,
                        "clicks": data["clicks"],
                        "impressions": data["impressions"]
                    })
                    total_waste += cost

            if poor_performers:
                # Calculate monthly savings (60 days to 30 days)
                monthly_savings = total_waste / 2

                # Find the worst performer
                worst = max(poor_performers, key=lambda x: x["cost"])

                if monthly_savings >= 100:  # Only recommend if >= $100/month savings
                    win = QuickWin(
                        win_type="pause_low_performers",
                        title=f"Pause '{worst['name']}' Campaign",
                        description=f"Campaign has spent ${worst['cost']:.0f} in 60 days with zero conversions. Save ${monthly_savings:.0f}/month.",
                        impact_monthly_value=monthly_savings,
                        impact_leads=0,
                        difficulty="easy",
                        time_estimate="1 min",
                        action_url=f"/account/google/ads/campaigns/{worst['id']}",
                        action_text="Pause Campaign",
                        data={
                            "campaign_id": worst["id"],
                            "campaign_name": worst["name"],
                            "total_poor_performers": len(poor_performers),
                            "monthly_savings": round(monthly_savings, 2),
                            "all_poor_performers": poor_performers
                        }
                    )
                    win.priority_score = self._calculate_priority_score(
                        monthly_savings, 0, "easy"
                    )
                    self.wins.append(win)

        except Exception as e:
            logger.error(f"Error checking low performing campaigns: {e}")

    def _check_budget_reallocation(self, account: Account):
        """
        Identify budget reallocation opportunities.

        Finds high-ROI campaigns that are limited by budget.
        """
        try:
            # Query for campaign performance with budget (last 30 days)
            query = """
                SELECT
                    campaign.id,
                    campaign.name,
                    campaign_budget.amount_micros,
                    metrics.cost_micros,
                    metrics.conversions,
                    metrics.search_impression_share,
                    metrics.search_budget_lost_impression_share
                FROM campaign
                WHERE segments.date DURING LAST_30_DAYS
                AND campaign.status = 'ENABLED'
            """

            response = self._query_google_ads(account, query)

            # Aggregate by campaign
            campaign_data = {}
            for row in response:
                campaign_id = row.campaign.id
                campaign_name = row.campaign.name

                if campaign_id not in campaign_data:
                    campaign_data[campaign_id] = {
                        "name": campaign_name,
                        "budget_micros": row.campaign_budget.amount_micros if hasattr(row, 'campaign_budget') else 0,
                        "cost_micros": 0,
                        "conversions": 0,
                        "impression_share": 0,
                        "budget_lost_share": 0,
                        "days": 0
                    }

                campaign_data[campaign_id]["cost_micros"] += row.metrics.cost_micros
                campaign_data[campaign_id]["conversions"] += row.metrics.conversions
                campaign_data[campaign_id]["impression_share"] += row.metrics.search_impression_share
                campaign_data[campaign_id]["budget_lost_share"] += row.metrics.search_budget_lost_impression_share
                campaign_data[campaign_id]["days"] += 1

            # Find budget-limited high performers
            budget_opportunities = []

            for campaign_id, data in campaign_data.items():
                if data["days"] == 0:
                    continue

                cost = data["cost_micros"] / 1_000_000
                conversions = data["conversions"]
                avg_budget_lost_share = data["budget_lost_share"] / data["days"] if data["days"] > 0 else 0

                # High performer = >5 conversions, >10% budget lost share
                if conversions >= 5 and avg_budget_lost_share > 0.10:
                    cpl = cost / conversions if conversions > 0 else 0

                    # Estimate leads gained from 20% budget increase
                    estimated_additional_leads = int(conversions * 0.15)  # Conservative 15%

                    budget_opportunities.append({
                        "id": campaign_id,
                        "name": data["name"],
                        "conversions": conversions,
                        "cpl": cpl,
                        "budget_lost_share": avg_budget_lost_share,
                        "estimated_additional_leads": estimated_additional_leads
                    })

            if budget_opportunities:
                # Sort by estimated additional leads
                best_opportunity = max(budget_opportunities, key=lambda x: x["estimated_additional_leads"])

                if best_opportunity["estimated_additional_leads"] >= 3:
                    win = QuickWin(
                        win_type="budget_reallocation",
                        title=f"Increase Budget for '{best_opportunity['name']}'",
                        description=f"Campaign is losing {best_opportunity['budget_lost_share']*100:.0f}% impression share due to budget. Increase by 20% to gain ~{best_opportunity['estimated_additional_leads']} leads/month.",
                        impact_monthly_value=0,
                        impact_leads=best_opportunity["estimated_additional_leads"],
                        difficulty="medium",
                        time_estimate="5 mins",
                        action_url=f"/account/google/ads/campaigns/{best_opportunity['id']}/budget",
                        action_text="Adjust Budget",
                        data={
                            "campaign_id": best_opportunity["id"],
                            "campaign_name": best_opportunity["name"],
                            "current_conversions": best_opportunity["conversions"],
                            "current_cpl": round(best_opportunity["cpl"], 2),
                            "budget_lost_share": round(best_opportunity["budget_lost_share"] * 100, 1),
                            "recommended_increase": "+20%",
                            "estimated_additional_leads": best_opportunity["estimated_additional_leads"]
                        }
                    )
                    win.priority_score = self._calculate_priority_score(
                        0, best_opportunity["estimated_additional_leads"], "medium"
                    )
                    self.wins.append(win)

        except Exception as e:
            logger.error(f"Error checking budget reallocation: {e}")

    def _check_quality_score_improvements(self, account: Account):
        """
        Identify quality score improvement opportunities.

        Finds keywords with low QS that could be improved easily.
        """
        try:
            # Query for keyword quality scores (last 30 days)
            query = """
                SELECT
                    campaign.id,
                    campaign.name,
                    ad_group.id,
                    ad_group.name,
                    ad_group_criterion.keyword.text,
                    ad_group_criterion.quality_info.quality_score,
                    metrics.cost_micros,
                    metrics.clicks,
                    metrics.impressions
                FROM keyword_view
                WHERE campaign.status = 'ENABLED'
                AND ad_group.status = 'ENABLED'
                AND ad_group_criterion.status = 'ENABLED'
                AND segments.date DURING LAST_30_DAYS
            """

            response = self._query_google_ads(account, query)

            # Find keywords with low QS and significant spend
            low_qs_keywords = []
            total_cost = 0

            for row in response:
                quality_score = row.ad_group_criterion.quality_info.quality_score
                cost_micros = row.metrics.cost_micros
                cost = cost_micros / 1_000_000

                # Low QS = 1-4, with spend >$50 in 30 days
                if quality_score > 0 and quality_score <= 4 and cost >= 50:
                    low_qs_keywords.append({
                        "campaign_id": row.campaign.id,
                        "campaign_name": row.campaign.name,
                        "ad_group_id": row.ad_group.id,
                        "ad_group_name": row.ad_group.name,
                        "keyword": row.ad_group_criterion.keyword.text,
                        "quality_score": quality_score,
                        "cost": cost,
                        "clicks": row.metrics.clicks,
                        "impressions": row.metrics.impressions
                    })
                    total_cost += cost

            if low_qs_keywords:
                # Sort by cost (highest first)
                low_qs_keywords.sort(key=lambda x: x["cost"], reverse=True)
                top_keywords = low_qs_keywords[:10]

                # Estimate savings from improving QS (lower CPC by 20%)
                estimated_monthly_savings = total_cost * 0.20

                if estimated_monthly_savings >= 100:
                    win = QuickWin(
                        win_type="quality_score_improvement",
                        title=f"Improve {len(low_qs_keywords)} Low Quality Score Keywords",
                        description=f"Found {len(low_qs_keywords)} keywords with QS ≤4 spending ${total_cost:.0f}/month. Improving QS could save ~${estimated_monthly_savings:.0f}/month.",
                        impact_monthly_value=estimated_monthly_savings,
                        impact_leads=0,
                        difficulty="medium",
                        time_estimate="15 mins",
                        action_url=f"/account/google/ads/keywords/quality-score",
                        action_text="Review Keywords",
                        data={
                            "total_keywords": len(low_qs_keywords),
                            "total_monthly_cost": round(total_cost, 2),
                            "estimated_savings": round(estimated_monthly_savings, 2),
                            "top_keywords": top_keywords[:5]  # Top 5 by spend
                        }
                    )
                    win.priority_score = self._calculate_priority_score(
                        estimated_monthly_savings, 0, "medium"
                    )
                    self.wins.append(win)

        except Exception as e:
            logger.error(f"Error checking quality score improvements: {e}")
