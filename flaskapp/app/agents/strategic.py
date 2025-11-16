# app/agents/strategic.py
"""
Strategic Layer - Long-term planning and goal-oriented agents.

The Strategic Director sets quarterly goals, allocates budget across campaigns,
and makes high-level decisions about scaling, pausing, or launching campaigns.
"""

from typing import Dict, List, Any
from datetime import datetime, timedelta
from .base import BaseAgent, AgentDecision, AgentCapability, DecisionRiskLevel


class StrategicDirectorAgent(BaseAgent):
    """
    Strategic Director - Your CMO for Google Ads.

    Responsibilities:
    - Set quarterly goals and KPIs
    - Allocate budget across campaigns
    - Decide when to launch, scale, or pause campaigns
    - Long-term planning (90-day outlook)
    - Business context awareness (seasonality, competition, capacity)

    Operates on: Weekly/Monthly cycles
    """

    def __init__(self, agent_id: str = "strategic_director", **kwargs):
        super().__init__(
            agent_id=agent_id,
            capabilities=[
                AgentCapability.STRATEGIC_PLANNING,
                AgentCapability.BUDGET_MANAGEMENT,
                AgentCapability.PERFORMANCE_MONITORING,
            ],
            auto_execute_threshold=0.85,  # Conservative for high-level decisions
            **kwargs
        )

        # Strategic context
        self.quarterly_goals = {}
        self.budget_allocation = {}
        self.campaign_priorities = {}

    def analyze(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Analyze account performance against strategic goals.

        Context should include:
        - performance_90d: 90-day performance metrics
        - campaigns: List of campaigns with metrics
        - budget: Current budget and spend
        - business_goals: Business objectives (if available)
        """
        opportunities = []

        # Extract context
        performance = context.get('performance_90d', {})
        campaigns = context.get('campaigns', [])
        total_budget = context.get('total_budget', 0)
        business_goals = context.get('business_goals', {})

        # 1. Check if we're meeting goals
        target_roas = business_goals.get('target_roas', 3.0)
        current_roas = performance.get('roas', 0)

        if current_roas < target_roas * 0.8:  # 20% below target
            opportunities.append({
                'type': 'goal_performance_gap',
                'severity': 'high',
                'metric': 'roas',
                'target': target_roas,
                'current': current_roas,
                'gap_pct': ((target_roas - current_roas) / target_roas) * 100
            })

        # 2. Identify budget reallocation opportunities
        # Find top and bottom performers
        if campaigns:
            campaign_performance = sorted(
                campaigns,
                key=lambda c: c.get('roas', 0),
                reverse=True
            )

            top_performers = campaign_performance[:3]
            bottom_performers = [c for c in campaign_performance if c.get('roas', 0) < 1.0]

            if bottom_performers and top_performers:
                # Calculate potential reallocation
                bottom_spend = sum(c.get('monthly_spend', 0) for c in bottom_performers)
                top_roas = sum(c.get('roas', 0) for c in top_performers) / len(top_performers)

                if bottom_spend > total_budget * 0.1:  # More than 10% on losers
                    opportunities.append({
                        'type': 'budget_reallocation',
                        'severity': 'high',
                        'from_campaigns': [c['id'] for c in bottom_performers],
                        'to_campaigns': [c['id'] for c in top_performers],
                        'amount': bottom_spend * 0.5,  # Move 50% of losing budget
                        'expected_roas_improvement': top_roas
                    })

        # 3. Check for scaling opportunities
        for campaign in campaigns:
            roas = campaign.get('roas', 0)
            impression_share = campaign.get('impression_share', 0)
            monthly_spend = campaign.get('monthly_spend', 0)

            # High ROAS + low impression share = scaling opportunity
            if roas > target_roas * 1.2 and impression_share < 70:
                opportunities.append({
                    'type': 'scaling_opportunity',
                    'severity': 'medium',
                    'campaign_id': campaign['id'],
                    'campaign_name': campaign.get('name'),
                    'current_roas': roas,
                    'impression_share': impression_share,
                    'current_spend': monthly_spend,
                    'recommended_increase': monthly_spend * 0.5  # Increase by 50%
                })

        # 4. Check for campaigns to pause
        for campaign in campaigns:
            roas = campaign.get('roas', 0)
            spend_90d = campaign.get('spend_90d', 0)

            # Consistent loser: Low ROAS + significant spend
            if roas < 0.5 and spend_90d > 1000:  # ROAS < 0.5 and spent >$1000
                opportunities.append({
                    'type': 'pause_campaign',
                    'severity': 'high',
                    'campaign_id': campaign['id'],
                    'campaign_name': campaign.get('name'),
                    'roas': roas,
                    'wasted_spend_90d': spend_90d * (1 - roas)
                })

        # 5. Seasonality check
        seasonality_multiplier = self._check_seasonality(context)
        if seasonality_multiplier != 1.0:
            opportunities.append({
                'type': 'seasonality_adjustment',
                'severity': 'medium',
                'multiplier': seasonality_multiplier,
                'reason': 'Peak season detected' if seasonality_multiplier > 1 else 'Off-season detected'
            })

        return opportunities

    def decide(self, opportunities: List[Dict[str, Any]]) -> List[AgentDecision]:
        """Make strategic decisions based on identified opportunities."""
        decisions = []

        for opp in opportunities:
            opp_type = opp['type']

            if opp_type == 'budget_reallocation':
                decision = AgentDecision(
                    agent_id=self.agent_id,
                    agent_type=self.agent_type,
                    decision_type='reallocate_budget',
                    title=f"Reallocate ${opp['amount']:,.0f} from losing to winning campaigns",
                    description=f"Move budget from {len(opp['from_campaigns'])} underperforming campaigns to {len(opp['to_campaigns'])} top performers",
                    reasoning=f"Bottom performers have ROAS < 1.0 while top performers average {opp['expected_roas_improvement']:.2f}x ROAS",
                    account_id=0,  # Will be filled in by caller
                    customer_id='',  # Will be filled in by caller
                    action_data={
                        'from_campaigns': opp['from_campaigns'],
                        'to_campaigns': opp['to_campaigns'],
                        'amount': opp['amount']
                    },
                    risk_level=DecisionRiskLevel.HIGH,  # Budget changes are high risk
                    requires_approval=True,
                    confidence=0.75,
                    expected_monthly_savings=opp['amount'] * 0.3,  # Conservative estimate
                )
                decisions.append(decision)

            elif opp_type == 'scaling_opportunity':
                decision = AgentDecision(
                    agent_id=self.agent_id,
                    agent_type=self.agent_type,
                    decision_type='scale_campaign',
                    title=f"Scale '{opp['campaign_name']}' by 50%",
                    description=f"Increase budget from ${opp['current_spend']:,.0f} to ${opp['current_spend'] * 1.5:,.0f}/month",
                    reasoning=f"Campaign has {opp['current_roas']:.2f}x ROAS but only {opp['impression_share']:.0f}% impression share",
                    account_id=0,
                    customer_id='',
                    campaign_id=opp['campaign_id'],
                    action_data={
                        'current_budget': opp['current_spend'],
                        'new_budget': opp['current_spend'] * 1.5,
                        'increase_amount': opp['recommended_increase']
                    },
                    risk_level=DecisionRiskLevel.MEDIUM,
                    requires_approval=True,
                    confidence=0.80,
                    expected_monthly_leads=int(opp['recommended_increase'] / 50),  # Assume $50 CPL
                    predicted_outcome={
                        'roas_change': 0.0,  # Should maintain ROAS
                        'lead_increase': opp['recommended_increase'] / 50
                    }
                )
                decisions.append(decision)

            elif opp_type == 'pause_campaign':
                decision = AgentDecision(
                    agent_id=self.agent_id,
                    agent_type=self.agent_type,
                    decision_type='pause_campaign',
                    title=f"Pause underperforming campaign '{opp['campaign_name']}'",
                    description=f"Campaign has {opp['roas']:.2f}x ROAS after 90 days",
                    reasoning=f"Consistent poor performance. Wasted ${opp['wasted_spend_90d']:,.0f} in last 90 days",
                    account_id=0,
                    customer_id='',
                    campaign_id=opp['campaign_id'],
                    action_data={
                        'campaign_id': opp['campaign_id'],
                        'reason': 'low_roas'
                    },
                    risk_level=DecisionRiskLevel.HIGH,
                    requires_approval=True,
                    confidence=0.85,
                    expected_monthly_savings=opp['wasted_spend_90d'] / 3  # Monthly equivalent
                )
                decisions.append(decision)

        return decisions

    def _execute_impl(self, decision: AgentDecision, google_ads_client: Any) -> Dict[str, Any]:
        """Execute strategic decisions via Google Ads API."""
        decision_type = decision.decision_type

        if decision_type == 'reallocate_budget':
            # Adjust campaign budgets
            return self._reallocate_budget(decision, google_ads_client)

        elif decision_type == 'scale_campaign':
            # Increase campaign budget
            return self._scale_campaign(decision, google_ads_client)

        elif decision_type == 'pause_campaign':
            # Pause campaign
            return self._pause_campaign(decision, google_ads_client)

        return {'success': False, 'error': f'Unknown decision type: {decision_type}'}

    def _reallocate_budget(self, decision: AgentDecision, client: Any) -> Dict[str, Any]:
        """Reallocate budget from losing to winning campaigns."""
        from .executor import GoogleAdsAgentExecutor

        if isinstance(client, GoogleAdsAgentExecutor):
            return client.reallocate_budget(
                from_campaigns=decision.action_data['from_campaigns'],
                to_campaigns=decision.action_data['to_campaigns'],
                amount=decision.action_data['amount']
            )

        # Fallback mock result
        return {
            'success': True,
            'from_campaigns_updated': len(decision.action_data['from_campaigns']),
            'to_campaigns_updated': len(decision.action_data['to_campaigns']),
            'amount_reallocated': decision.action_data['amount']
        }

    def _scale_campaign(self, decision: AgentDecision, client: Any) -> Dict[str, Any]:
        """Increase campaign budget."""
        from .executor import GoogleAdsAgentExecutor

        if isinstance(client, GoogleAdsAgentExecutor):
            return client.scale_campaign_budget(
                campaign_id=decision.campaign_id,
                new_budget=decision.action_data['new_budget']
            )

        return {
            'success': True,
            'campaign_id': decision.campaign_id,
            'old_budget': decision.action_data['current_budget'],
            'new_budget': decision.action_data['new_budget']
        }

    def _pause_campaign(self, decision: AgentDecision, client: Any) -> Dict[str, Any]:
        """Pause a campaign."""
        from .executor import GoogleAdsAgentExecutor

        if isinstance(client, GoogleAdsAgentExecutor):
            return client.pause_campaign(campaign_id=decision.campaign_id)

        return {
            'success': True,
            'campaign_id': decision.campaign_id,
            'status': 'PAUSED'
        }

    def _check_seasonality(self, context: Dict[str, Any]) -> float:
        """
        Check if we're in peak/off season and return budget multiplier.

        Returns:
            Multiplier (1.0 = normal, >1.0 = peak season, <1.0 = off-season)
        """
        # This would integrate with industry seasonality data
        # For now, simple month-based heuristic for home services
        current_month = datetime.now().month

        # HVAC: Peak in summer (June-Aug) and winter (Dec-Feb)
        peak_months = [6, 7, 8, 12, 1, 2]
        if current_month in peak_months:
            return 1.2  # 20% increase

        return 1.0
