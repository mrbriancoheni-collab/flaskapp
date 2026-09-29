# app/agents/fbads_strategic.py
"""
Facebook Ads Strategic Layer - Long-term planning and goal-oriented agents.

The FB Strategic Director sets goals, allocates budget across campaigns,
and makes high-level decisions about scaling, pausing, or launching campaigns.
Aligns with the overall Strategic Director for cross-platform optimization.
"""

from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
import logging
from .base import BaseAgent, AgentDecision, AgentCapability, DecisionRiskLevel
from .event_bus import AgentEventBus
from .fb_agent_executor import _fb_execute_action

logger = logging.getLogger(__name__)


class FBStrategicDirectorAgent(BaseAgent):
    """
    Facebook Ads Strategic Director - Your CMO for Facebook/Instagram Ads.

    Responsibilities:
    - Set campaign objectives aligned with business goals
    - Allocate budget across campaigns and ad sets
    - Decide when to launch, scale, or pause campaigns
    - Long-term planning (90-day outlook)
    - Cross-platform coordination with Google Ads strategy
    - Audience strategy (lookalike, custom, interest-based)

    Operates on: Weekly/Monthly cycles
    """

    def __init__(self, agent_id: str = "fb_strategic_director", **kwargs):
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
        self.audience_strategy = {}

    def analyze(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Analyze Facebook Ads account performance against strategic goals.

        Context should include:
        - performance_90d: 90-day performance metrics
        - campaigns: List of campaigns with metrics
        - ad_sets: List of ad sets with targeting info
        - audiences: Custom and lookalike audiences
        - budget: Current budget and spend
        - business_goals: Business objectives (if available)
        """
        opportunities = []

        # Extract context
        performance = context.get('performance_90d', {})
        campaigns = context.get('campaigns', [])
        ad_sets = context.get('ad_sets', [])
        audiences = context.get('audiences', [])
        total_budget = context.get('total_budget', 0)
        business_goals = context.get('business_goals', {})

        # 1. Check if we're meeting goals
        target_cpa = business_goals.get('target_cpa', 50)
        target_roas = business_goals.get('target_roas', 3.0)
        current_cpa = performance.get('cpa', 0)
        current_roas = performance.get('roas', 0)

        if current_cpa > target_cpa * 1.2:  # 20% above target
            opportunities.append({
                'type': 'goal_performance_gap',
                'severity': 'high',
                'metric': 'cpa',
                'target': target_cpa,
                'current': current_cpa,
                'gap_pct': ((current_cpa - target_cpa) / target_cpa) * 100
            })

        if current_roas < target_roas * 0.8 and current_roas > 0:  # 20% below target
            opportunities.append({
                'type': 'goal_performance_gap',
                'severity': 'high',
                'metric': 'roas',
                'target': target_roas,
                'current': current_roas,
                'gap_pct': ((target_roas - current_roas) / target_roas) * 100
            })

        # 2. Identify budget reallocation opportunities
        if campaigns:
            campaign_performance = sorted(
                campaigns,
                key=lambda c: c.get('roas', 0) if c.get('roas', 0) > 0 else -c.get('cpa', float('inf')),
                reverse=True
            )

            top_performers = campaign_performance[:3]
            bottom_performers = [c for c in campaign_performance if c.get('roas', 0) < 1.0 and c.get('spend_30d', 0) > 100]

            if bottom_performers and top_performers:
                bottom_spend = sum(c.get('spend_30d', 0) for c in bottom_performers)
                top_roas = sum(c.get('roas', 0) for c in top_performers if c.get('roas', 0) > 0) / max(1, len([c for c in top_performers if c.get('roas', 0) > 0]))

                if bottom_spend > total_budget * 0.1:
                    opportunities.append({
                        'type': 'budget_reallocation',
                        'severity': 'high',
                        'from_campaigns': [c['id'] for c in bottom_performers],
                        'to_campaigns': [c['id'] for c in top_performers],
                        'amount': bottom_spend * 0.5,
                        'expected_roas_improvement': top_roas
                    })

        # 3. Audience expansion opportunities
        has_lookalike = any(a.get('type') == 'lookalike' for a in audiences)
        has_custom = any(a.get('type') == 'custom' for a in audiences)

        if not has_lookalike and has_custom:
            # Has customer data but not using lookalikes
            opportunities.append({
                'type': 'create_lookalike_audience',
                'severity': 'medium',
                'reason': 'custom_audience_available',
                'custom_audience_count': len([a for a in audiences if a.get('type') == 'custom']),
                'message': 'Create Lookalike audiences from your customer list to reach similar high-value prospects'
            })

        if not has_custom:
            opportunities.append({
                'type': 'create_custom_audience',
                'severity': 'medium',
                'reason': 'no_first_party_data',
                'message': 'Upload customer list to create Custom Audiences for retargeting and Lookalike creation'
            })

        # 4. Check for scaling opportunities
        for campaign in campaigns:
            roas = campaign.get('roas', 0)
            cpa = campaign.get('cpa', 0)
            frequency = campaign.get('frequency', 0)
            reach_saturation = campaign.get('reach_saturation', 0)
            daily_budget = campaign.get('daily_budget', 0)

            # High performance + room to scale
            if (roas > target_roas * 1.2 or (cpa > 0 and cpa < target_cpa * 0.8)) and frequency < 3 and reach_saturation < 70:
                opportunities.append({
                    'type': 'scaling_opportunity',
                    'severity': 'medium',
                    'campaign_id': campaign['id'],
                    'campaign_name': campaign.get('name'),
                    'current_roas': roas,
                    'current_cpa': cpa,
                    'frequency': frequency,
                    'reach_saturation': reach_saturation,
                    'current_budget': daily_budget,
                    'recommended_increase': daily_budget * 0.5
                })

        # 5. Check for campaigns to pause (audience fatigue)
        for campaign in campaigns:
            frequency = campaign.get('frequency', 0)
            ctr_trend = campaign.get('ctr_trend_7d', 0)  # Negative = declining
            cpa_trend = campaign.get('cpa_trend_7d', 0)  # Positive = increasing cost

            if frequency > 5 and (ctr_trend < -0.1 or cpa_trend > 0.3):
                opportunities.append({
                    'type': 'audience_fatigue',
                    'severity': 'high',
                    'campaign_id': campaign['id'],
                    'campaign_name': campaign.get('name'),
                    'frequency': frequency,
                    'ctr_trend': ctr_trend,
                    'cpa_trend': cpa_trend,
                    'recommendation': 'Refresh creative or expand audience'
                })

        # 6. Campaign objective alignment
        for campaign in campaigns:
            objective = campaign.get('objective', '')
            has_pixel = campaign.get('has_pixel_events', False)

            if objective == 'TRAFFIC' and has_pixel:
                # Should be using conversions objective if pixel is set up
                opportunities.append({
                    'type': 'optimize_campaign_objective',
                    'severity': 'medium',
                    'campaign_id': campaign['id'],
                    'campaign_name': campaign.get('name'),
                    'current_objective': objective,
                    'recommended_objective': 'CONVERSIONS',
                    'reason': 'Pixel events detected - switch to Conversions for better optimization'
                })

        # 7. Placement optimization
        for campaign in campaigns:
            placements = campaign.get('placements', [])
            placement_performance = campaign.get('placement_performance', {})

            # Check if using automatic placements with poor performers
            if 'AUTOMATIC' in placements and placement_performance:
                poor_placements = [p for p, metrics in placement_performance.items()
                                 if metrics.get('cpa', 0) > target_cpa * 2]

                if poor_placements:
                    opportunities.append({
                        'type': 'exclude_poor_placements',
                        'severity': 'medium',
                        'campaign_id': campaign['id'],
                        'campaign_name': campaign.get('name'),
                        'poor_placements': poor_placements,
                        'reason': 'These placements have 2x+ higher CPA than target'
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
                    title=f"Reallocate ${opp['amount']:,.0f} from underperforming to top campaigns",
                    description=f"Move budget from {len(opp['from_campaigns'])} underperforming campaigns to {len(opp['to_campaigns'])} top performers",
                    reasoning=f"Bottom performers have ROAS < 1.0 while top performers average {opp['expected_roas_improvement']:.2f}x ROAS",
                    account_id=self.account_id or 0,
                    customer_id='',
                    action_data={
                        'from_campaigns': opp['from_campaigns'],
                        'to_campaigns': opp['to_campaigns'],
                        'amount': opp['amount']
                    },
                    risk_level=DecisionRiskLevel.HIGH,
                    requires_approval=True,
                    confidence=0.75,
                    expected_monthly_savings=opp['amount'] * 0.3,
                )
                decisions.append(decision)

            elif opp_type == 'scaling_opportunity':
                decision = AgentDecision(
                    agent_id=self.agent_id,
                    agent_type=self.agent_type,
                    decision_type='scale_campaign',
                    title=f"Scale '{opp['campaign_name']}' by 50%",
                    description=f"Increase daily budget from ${opp['current_budget']:,.0f} to ${opp['current_budget'] * 1.5:,.0f}",
                    reasoning=f"Campaign has {opp['current_roas']:.2f}x ROAS with only {opp['frequency']:.1f} frequency and {opp['reach_saturation']:.0f}% reach saturation",
                    account_id=self.account_id or 0,
                    customer_id='',
                    campaign_id=opp['campaign_id'],
                    action_data={
                        'current_budget': opp['current_budget'],
                        'new_budget': opp['current_budget'] * 1.5,
                        'increase_amount': opp['recommended_increase']
                    },
                    risk_level=DecisionRiskLevel.HIGH,
                    requires_approval=True,
                    confidence=0.80,
                    expected_monthly_leads=int(opp['recommended_increase'] / max(1, opp.get('current_cpa', 50))),
                )
                decisions.append(decision)

            elif opp_type == 'audience_fatigue':
                decision = AgentDecision(
                    agent_id=self.agent_id,
                    agent_type=self.agent_type,
                    decision_type='address_audience_fatigue',
                    title=f"Address audience fatigue in '{opp['campaign_name']}'",
                    description=f"Frequency at {opp['frequency']:.1f}x with declining performance",
                    reasoning=f"CTR trend: {opp['ctr_trend']*100:+.0f}%, CPA trend: {opp['cpa_trend']*100:+.0f}%",
                    account_id=self.account_id or 0,
                    customer_id='',
                    campaign_id=opp['campaign_id'],
                    action_data={
                        'options': [
                            'Refresh creative with new images/videos',
                            'Expand audience targeting',
                            'Create new lookalike at different %',
                            'Pause for 7 days to reset frequency'
                        ]
                    },
                    risk_level=DecisionRiskLevel.HIGH,
                    requires_approval=True,
                    confidence=0.85,
                )
                decisions.append(decision)

            elif opp_type == 'create_lookalike_audience':
                decision = AgentDecision(
                    agent_id=self.agent_id,
                    agent_type=self.agent_type,
                    decision_type='create_lookalike',
                    title="Create Lookalike Audiences from customer data",
                    description=f"You have {opp['custom_audience_count']} Custom Audience(s) that can be used as a source",
                    reasoning="Lookalike audiences typically outperform interest targeting by 2-5x for lead quality",
                    account_id=self.account_id or 0,
                    customer_id='',
                    action_data={
                        'recommended_sizes': ['1%', '1-2%', '2-5%'],
                        'source': 'custom_audience',
                        'steps': [
                            '1. Go to Audiences in Ads Manager',
                            '2. Click "Create Audience" > "Lookalike Audience"',
                            '3. Select your best Custom Audience as source',
                            '4. Choose location and size (start with 1%)',
                            '5. Create separate ad sets for 1%, 1-2%, and 2-5%'
                        ]
                    },
                    risk_level=DecisionRiskLevel.LOW,
                    requires_approval=False,
                    confidence=0.90,
                    expected_improvement_pct=25.0,
                )
                decisions.append(decision)

            elif opp_type == 'optimize_campaign_objective':
                decision = AgentDecision(
                    agent_id=self.agent_id,
                    agent_type=self.agent_type,
                    decision_type='change_campaign_objective',
                    title=f"Switch '{opp['campaign_name']}' to Conversions objective",
                    description=f"Currently using {opp['current_objective']} but pixel events are available",
                    reasoning="Conversions objective uses Facebook's ML to find people most likely to convert, not just click",
                    account_id=self.account_id or 0,
                    customer_id='',
                    campaign_id=opp['campaign_id'],
                    action_data={
                        'current_objective': opp['current_objective'],
                        'new_objective': opp['recommended_objective'],
                        'requires_new_campaign': True,  # Can't change objective on existing campaign
                    },
                    risk_level=DecisionRiskLevel.HIGH,
                    requires_approval=True,
                    confidence=0.88,
                    expected_improvement_pct=30.0,
                )
                decisions.append(decision)

        return decisions

    def _execute_impl(self, decision: AgentDecision, fb_ads_client: Any) -> Dict[str, Any]:
        """Execute strategic decisions via Facebook Marketing API."""
        decision_type = decision.decision_type

        # Most strategic decisions require manual setup in Facebook Ads Manager
        if decision_type in ['create_lookalike', 'change_campaign_objective', 'address_audience_fatigue']:
            return {
                'success': True,
                'note': 'This action requires manual setup in Facebook Ads Manager',
                'decision_type': decision_type,
                'requires_manual_work': True,
                'steps': decision.action_data.get('steps', decision.action_data.get('options', []))
            }

        if decision_type == 'reallocate_budget':
            return self._reallocate_budget(decision, fb_ads_client)

        if decision_type == 'scale_campaign':
            return self._scale_campaign(decision, fb_ads_client)

        return {'success': False, 'error': f'Unknown decision type: {decision_type}'}

    def _reallocate_budget(self, decision: AgentDecision, client: Any) -> Dict[str, Any]:
        """Reallocate budget: reduce underperformers, increase top performers."""
        account_id = decision.account_id
        from_campaigns = decision.action_data.get('from_campaigns', [])
        to_campaigns = decision.action_data.get('to_campaigns', [])
        amount = decision.action_data.get('amount', 0)

        results = []
        all_success = True

        # Reduce budget on underperformers (cut by 50% of reallocation amount spread evenly)
        if from_campaigns:
            per_campaign_reduction = amount / len(from_campaigns)
            for cid in from_campaigns:
                r = _fb_execute_action(
                    account_id=account_id,
                    entity_id=str(cid),
                    entity_type='campaign',
                    action='adjust_budget',
                    params={'daily_budget': max(1.0, per_campaign_reduction)},
                )
                results.append({'campaign_id': cid, 'direction': 'reduce', **r})
                if not r.get('success'):
                    all_success = False

        # Increase budget on top performers
        if to_campaigns:
            per_campaign_increase = amount / len(to_campaigns)
            for cid in to_campaigns:
                r = _fb_execute_action(
                    account_id=account_id,
                    entity_id=str(cid),
                    entity_type='campaign',
                    action='adjust_budget',
                    params={'daily_budget': per_campaign_increase},
                )
                results.append({'campaign_id': cid, 'direction': 'increase', **r})
                if not r.get('success'):
                    all_success = False

        return {
            'success': all_success,
            'from_campaigns_updated': len(from_campaigns),
            'to_campaigns_updated': len(to_campaigns),
            'amount_reallocated': amount,
            'details': results,
        }

    def _scale_campaign(self, decision: AgentDecision, client: Any) -> Dict[str, Any]:
        """Increase campaign daily budget via real API call."""
        account_id = decision.account_id
        campaign_id = decision.campaign_id or decision.action_data.get('campaign_id')
        new_budget = decision.action_data.get('new_budget')

        if not campaign_id:
            return {'success': False, 'error': 'No campaign_id in decision'}
        if not new_budget:
            return {'success': False, 'error': 'No new_budget in action_data'}

        result = _fb_execute_action(
            account_id=account_id,
            entity_id=str(campaign_id),
            entity_type='campaign',
            action='adjust_budget',
            params={'daily_budget': float(new_budget)},
        )
        return {
            **result,
            'campaign_id': campaign_id,
            'old_budget': decision.action_data.get('current_budget'),
            'new_budget': new_budget,
        }


class FBAccountStructureAgent(BaseAgent):
    """
    Facebook Ads Account Structure Agent - Evaluates campaign/ad set/ad organization.

    Responsibilities:
    - Analyze campaign structure (consolidation vs granularity)
    - Evaluate ad set audience overlap
    - Check ad creative diversity
    - Recommend structural improvements
    - Ensure proper campaign budget optimization (CBO) setup

    Operates on: Weekly cycles
    """

    def __init__(self, agent_id: str = "fb_account_structure", **kwargs):
        super().__init__(
            agent_id=agent_id,
            capabilities=[
                AgentCapability.STRATEGIC_PLANNING,
                AgentCapability.PERFORMANCE_MONITORING,
            ],
            auto_execute_threshold=0.80,
            **kwargs
        )

    def analyze(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Analyze Facebook Ads account structure."""
        opportunities = []

        campaigns = context.get('campaigns', [])
        ad_sets = context.get('ad_sets', [])
        ads = context.get('ads', [])

        # 1. Check for audience overlap
        for i, ad_set1 in enumerate(ad_sets):
            for ad_set2 in ad_sets[i+1:]:
                overlap = self._calculate_audience_overlap(ad_set1, ad_set2)
                if overlap > 30:  # More than 30% overlap
                    opportunities.append({
                        'type': 'audience_overlap',
                        'severity': 'medium',
                        'ad_set_1': ad_set1.get('name'),
                        'ad_set_2': ad_set2.get('name'),
                        'overlap_pct': overlap,
                        'recommendation': 'Consider consolidating or using exclusions'
                    })

        # 2. Check for too many ad sets (Facebook prefers consolidation)
        for campaign in campaigns:
            campaign_ad_sets = [a for a in ad_sets if a.get('campaign_id') == campaign.get('id')]
            if len(campaign_ad_sets) > 5:
                opportunities.append({
                    'type': 'too_many_ad_sets',
                    'severity': 'medium',
                    'campaign_id': campaign.get('id'),
                    'campaign_name': campaign.get('name'),
                    'ad_set_count': len(campaign_ad_sets),
                    'recommendation': 'Consolidate ad sets to let Facebook ML optimize better'
                })

        # 3. Check for CBO (Campaign Budget Optimization) usage
        for campaign in campaigns:
            uses_cbo = campaign.get('budget_optimization', '') == 'CAMPAIGN'
            daily_budget = campaign.get('daily_budget', 0)

            if not uses_cbo and daily_budget > 100:
                opportunities.append({
                    'type': 'enable_cbo',
                    'severity': 'medium',
                    'campaign_id': campaign.get('id'),
                    'campaign_name': campaign.get('name'),
                    'current_budget': daily_budget,
                    'recommendation': 'Enable Campaign Budget Optimization for better ML allocation'
                })

        # 4. Check for ad creative diversity
        for ad_set in ad_sets:
            ad_set_ads = [a for a in ads if a.get('ad_set_id') == ad_set.get('id')]

            if len(ad_set_ads) < 3:
                opportunities.append({
                    'type': 'need_more_creatives',
                    'severity': 'low',
                    'ad_set_id': ad_set.get('id'),
                    'ad_set_name': ad_set.get('name'),
                    'current_ad_count': len(ad_set_ads),
                    'recommendation': 'Add 3-6 ad variations for better testing'
                })

        return opportunities

    def decide(self, opportunities: List[Dict[str, Any]]) -> List[AgentDecision]:
        """Make structure improvement decisions."""
        decisions = []

        for opp in opportunities:
            opp_type = opp['type']

            if opp_type == 'enable_cbo':
                decision = AgentDecision(
                    agent_id=self.agent_id,
                    agent_type=self.agent_type,
                    decision_type='enable_cbo',
                    title=f"Enable Campaign Budget Optimization for '{opp['campaign_name']}'",
                    description=f"Current daily budget: ${opp['current_budget']:.0f}",
                    reasoning="CBO allows Facebook's ML to distribute budget to best-performing ad sets automatically",
                    account_id=self.account_id or 0,
                    customer_id='',
                    campaign_id=opp['campaign_id'],
                    action_data={
                        'campaign_id': opp['campaign_id']
                    },
                    risk_level=DecisionRiskLevel.HIGH,
                    requires_approval=True,
                    confidence=0.85,
                    expected_improvement_pct=15.0,
                )
                decisions.append(decision)

        return decisions

    def _calculate_audience_overlap(self, ad_set1: Dict, ad_set2: Dict) -> float:
        """Calculate estimated audience overlap between two ad sets."""
        # Simplified - would use Facebook's Audience Overlap API in production
        targeting1 = ad_set1.get('targeting', {})
        targeting2 = ad_set2.get('targeting', {})

        # Check interest overlap
        interests1 = set(targeting1.get('interests', []))
        interests2 = set(targeting2.get('interests', []))

        if not interests1 or not interests2:
            return 0

        overlap = len(interests1.intersection(interests2))
        total = len(interests1.union(interests2))

        return (overlap / total * 100) if total > 0 else 0

    def _execute_impl(self, decision: AgentDecision, fb_ads_client: Any) -> Dict[str, Any]:
        """Execute structure changes."""
        return {
            'success': True,
            'note': 'Structure changes require manual implementation in Ads Manager',
            'decision_type': decision.decision_type,
            'requires_manual_work': True
        }
