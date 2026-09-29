# app/agents/fbads_tactical.py
"""
Facebook Ads Tactical Layer - Specific optimizations and execution agents.

These agents perform focused, specialized tasks like managing audiences,
optimizing ad placements, and analyzing creative elements.
"""

from typing import Dict, List, Any
from .base import BaseAgent, AgentDecision, AgentCapability, DecisionRiskLevel
from .fb_agent_executor import _fb_execute_action

import logging
logger = logging.getLogger(__name__)


class FBAudienceOptimizerAgent(BaseAgent):
    """
    Facebook Audience Optimizer - Targeting and audience management.

    Responsibilities:
    - Optimize audience targeting based on performance
    - Manage custom audience updates
    - Recommend lookalike audience expansions
    - Identify exclusion opportunities
    - Monitor audience size changes

    Operates on: Daily cycles
    """

    def __init__(self, agent_id: str = "fb_audience_optimizer", **kwargs):
        super().__init__(
            agent_id=agent_id,
            capabilities=[
                AgentCapability.KEYWORD_MANAGEMENT,  # Repurposed for audience management
                AgentCapability.PERFORMANCE_MONITORING,
                AgentCapability.AUTONOMOUS_EXECUTION,
            ],
            auto_execute_threshold=0.88,
            **kwargs
        )

    def analyze(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Analyze audience performance."""
        opportunities = []

        ad_sets = context.get('ad_sets', [])
        audiences = context.get('audiences', [])
        target_cpa = context.get('target_cpa', 50)

        for ad_set in ad_sets:
            ad_set_id = ad_set.get('id')
            ad_set_name = ad_set.get('name', '')
            targeting = ad_set.get('targeting', {})

            # Get performance metrics
            cpa = ad_set.get('cpa_7d', 0)
            conversions = ad_set.get('conversions_7d', 0)
            reach = ad_set.get('reach_7d', 0)
            audience_size = ad_set.get('audience_size_estimate', 0)

            # 1. Audience too broad (high reach but poor conversion)
            if audience_size > 10000000 and cpa > target_cpa * 1.5 and conversions > 5:
                opportunities.append({
                    'type': 'narrow_audience',
                    'severity': 'medium',
                    'ad_set_id': ad_set_id,
                    'ad_set_name': ad_set_name,
                    'audience_size': audience_size,
                    'cpa': cpa,
                    'target_cpa': target_cpa,
                    'recommendation': 'Add interest layers or demographic restrictions'
                })

            # 2. Audience too narrow (limited reach)
            if audience_size < 100000 and conversions < 5:
                opportunities.append({
                    'type': 'expand_audience',
                    'severity': 'medium',
                    'ad_set_id': ad_set_id,
                    'ad_set_name': ad_set_name,
                    'audience_size': audience_size,
                    'conversions': conversions,
                    'recommendation': 'Expand targeting to get more data'
                })

            # 3. Age/gender breakdown performance
            age_breakdown = ad_set.get('age_breakdown', {})
            gender_breakdown = ad_set.get('gender_breakdown', {})

            # Find poorly performing demographics
            for age_range, metrics in age_breakdown.items():
                if metrics.get('cpa', 0) > target_cpa * 2 and metrics.get('spend', 0) > 50:
                    opportunities.append({
                        'type': 'exclude_demographic',
                        'severity': 'low',
                        'ad_set_id': ad_set_id,
                        'ad_set_name': ad_set_name,
                        'demographic_type': 'age',
                        'demographic_value': age_range,
                        'cpa': metrics.get('cpa'),
                        'spend': metrics.get('spend'),
                        'recommendation': f"Exclude {age_range} age group (CPA 2x+ target)"
                    })

            for gender, metrics in gender_breakdown.items():
                if metrics.get('cpa', 0) > target_cpa * 2 and metrics.get('spend', 0) > 50:
                    opportunities.append({
                        'type': 'exclude_demographic',
                        'severity': 'low',
                        'ad_set_id': ad_set_id,
                        'ad_set_name': ad_set_name,
                        'demographic_type': 'gender',
                        'demographic_value': gender,
                        'cpa': metrics.get('cpa'),
                        'spend': metrics.get('spend'),
                        'recommendation': f"Exclude {gender} (CPA 2x+ target)"
                    })

            # 4. Interest targeting analysis
            interests = targeting.get('interests', [])
            interest_performance = ad_set.get('interest_breakdown', {})

            for interest in interests:
                interest_name = interest if isinstance(interest, str) else interest.get('name', '')
                metrics = interest_performance.get(interest_name, {})

                if metrics.get('cpa', 0) > target_cpa * 2 and metrics.get('spend', 0) > 100:
                    opportunities.append({
                        'type': 'remove_interest',
                        'severity': 'medium',
                        'ad_set_id': ad_set_id,
                        'ad_set_name': ad_set_name,
                        'interest': interest_name,
                        'cpa': metrics.get('cpa'),
                        'spend': metrics.get('spend'),
                        'recommendation': f"Remove '{interest_name}' interest (poor performance)"
                    })

        # 5. Lookalike audience optimization
        for audience in audiences:
            if audience.get('type') == 'lookalike':
                size_pct = audience.get('size_percent', 0)
                performance = audience.get('performance', {})

                # If 1% lookalike is working well, suggest testing 1-2%
                if size_pct <= 1 and performance.get('cpa', float('inf')) < target_cpa:
                    opportunities.append({
                        'type': 'expand_lookalike',
                        'severity': 'low',
                        'audience_id': audience.get('id'),
                        'audience_name': audience.get('name'),
                        'current_size': f"{size_pct}%",
                        'cpa': performance.get('cpa'),
                        'recommendation': 'Test 1-2% lookalike for more scale at similar performance'
                    })

        return opportunities

    def decide(self, opportunities: List[Dict[str, Any]]) -> List[AgentDecision]:
        """Make audience optimization decisions."""
        decisions = []

        for opp in opportunities:
            opp_type = opp['type']

            if opp_type == 'narrow_audience':
                decision = AgentDecision(
                    agent_id=self.agent_id,
                    agent_type=self.agent_type,
                    decision_type='narrow_targeting',
                    title=f"Narrow audience for '{opp['ad_set_name']}'",
                    description=f"Audience size: {opp['audience_size']:,}, CPA ${opp['cpa']:.2f} vs target ${opp['target_cpa']:.2f}",
                    reasoning=opp['recommendation'],
                    account_id=self.account_id or 0,
                    customer_id='',
                    ad_group_id=opp['ad_set_id'],
                    action_data={
                        'suggestions': [
                            'Add income targeting (if B2C)',
                            'Layer additional interests',
                            'Restrict to engaged shoppers',
                            'Add homeowner/renter filter (if applicable)'
                        ]
                    },
                    risk_level=DecisionRiskLevel.LOW,
                    requires_approval=False,
                    confidence=0.85,
                    expected_monthly_savings=(opp['cpa'] - opp['target_cpa']) * 30
                )
                decisions.append(decision)

            elif opp_type == 'exclude_demographic':
                decision = AgentDecision(
                    agent_id=self.agent_id,
                    agent_type=self.agent_type,
                    decision_type='exclude_demographic',
                    title=f"Exclude {opp['demographic_type']}: {opp['demographic_value']}",
                    description=f"CPA ${opp['cpa']:.2f} on ${opp['spend']:.0f} spend - 2x+ above target",
                    reasoning=opp['recommendation'],
                    account_id=self.account_id or 0,
                    customer_id='',
                    ad_group_id=opp['ad_set_id'],
                    action_data={
                        'demographic_type': opp['demographic_type'],
                        'demographic_value': opp['demographic_value']
                    },
                    risk_level=DecisionRiskLevel.LOW,
                    requires_approval=False,
                    confidence=0.90,
                    expected_monthly_savings=opp['spend']
                )
                decisions.append(decision)

            elif opp_type == 'remove_interest':
                decision = AgentDecision(
                    agent_id=self.agent_id,
                    agent_type=self.agent_type,
                    decision_type='remove_interest',
                    title=f"Remove interest '{opp['interest']}'",
                    description=f"CPA ${opp['cpa']:.2f} on ${opp['spend']:.0f} spend",
                    reasoning=opp['recommendation'],
                    account_id=self.account_id or 0,
                    customer_id='',
                    ad_group_id=opp['ad_set_id'],
                    action_data={
                        'interest': opp['interest']
                    },
                    risk_level=DecisionRiskLevel.LOW,
                    requires_approval=False,
                    confidence=0.88,
                    expected_monthly_savings=opp['spend']
                )
                decisions.append(decision)

            elif opp_type == 'expand_lookalike':
                decision = AgentDecision(
                    agent_id=self.agent_id,
                    agent_type=self.agent_type,
                    decision_type='create_expanded_lookalike',
                    title=f"Test expanded lookalike from '{opp['audience_name']}'",
                    description=f"Current {opp['current_size']} performing well at ${opp['cpa']:.2f} CPA",
                    reasoning=opp['recommendation'],
                    account_id=self.account_id or 0,
                    customer_id='',
                    action_data={
                        'source_audience_id': opp['audience_id'],
                        'recommended_sizes': ['1-2%', '2-5%']
                    },
                    risk_level=DecisionRiskLevel.LOW,
                    requires_approval=False,
                    confidence=0.80,
                    expected_improvement_pct=20.0
                )
                decisions.append(decision)

        return decisions

    def _execute_impl(self, decision: AgentDecision, fb_ads_client: Any) -> Dict[str, Any]:
        """Execute audience changes."""
        decision_type = decision.decision_type

        # Most audience changes require Ads Manager
        return {
            'success': True,
            'decision_type': decision_type,
            'note': 'Audience changes require implementation in Ads Manager',
            'requires_manual_work': True,
            'suggestions': decision.action_data.get('suggestions', [])
        }


class FBPlacementOptimizerAgent(BaseAgent):
    """
    Facebook Placement Optimizer - Optimize ad delivery across placements.

    Responsibilities:
    - Analyze placement performance (Facebook, Instagram, Audience Network, Messenger)
    - Recommend placement exclusions
    - Optimize for specific placements
    - Monitor platform-specific metrics

    Operates on: Daily cycles
    """

    def __init__(self, agent_id: str = "fb_placement_optimizer", **kwargs):
        super().__init__(
            agent_id=agent_id,
            capabilities=[
                AgentCapability.PERFORMANCE_MONITORING,
                AgentCapability.AUTONOMOUS_EXECUTION,
            ],
            auto_execute_threshold=0.92,
            **kwargs
        )

        # Known placement categories
        self.placements = {
            'facebook_feed': 'Facebook Feed',
            'facebook_stories': 'Facebook Stories',
            'facebook_reels': 'Facebook Reels',
            'facebook_right_column': 'Facebook Right Column',
            'facebook_instant_articles': 'Instant Articles',
            'instagram_feed': 'Instagram Feed',
            'instagram_stories': 'Instagram Stories',
            'instagram_reels': 'Instagram Reels',
            'instagram_explore': 'Instagram Explore',
            'audience_network': 'Audience Network',
            'messenger_inbox': 'Messenger Inbox',
            'messenger_stories': 'Messenger Stories',
        }

    def analyze(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Analyze placement performance."""
        opportunities = []

        ad_sets = context.get('ad_sets', [])
        target_cpa = context.get('target_cpa', 50)

        for ad_set in ad_sets:
            ad_set_id = ad_set.get('id')
            ad_set_name = ad_set.get('name', '')
            placement_performance = ad_set.get('placement_breakdown', {})
            overall_cpa = ad_set.get('cpa_7d', 0)

            if not placement_performance:
                continue

            poor_placements = []
            good_placements = []

            for placement, metrics in placement_performance.items():
                placement_cpa = metrics.get('cpa', 0)
                placement_spend = metrics.get('spend', 0)
                placement_conversions = metrics.get('conversions', 0)

                # Poor performers: High CPA with significant spend
                if placement_cpa > target_cpa * 2 and placement_spend > 50:
                    poor_placements.append({
                        'name': self.placements.get(placement, placement),
                        'key': placement,
                        'cpa': placement_cpa,
                        'spend': placement_spend,
                        'conversions': placement_conversions
                    })

                # Good performers for potential focus
                if placement_cpa > 0 and placement_cpa < target_cpa * 0.8 and placement_conversions >= 3:
                    good_placements.append({
                        'name': self.placements.get(placement, placement),
                        'key': placement,
                        'cpa': placement_cpa,
                        'spend': placement_spend,
                        'conversions': placement_conversions
                    })

            # Recommend excluding poor placements
            for poor in poor_placements:
                opportunities.append({
                    'type': 'exclude_placement',
                    'severity': 'medium',
                    'ad_set_id': ad_set_id,
                    'ad_set_name': ad_set_name,
                    'placement': poor['name'],
                    'placement_key': poor['key'],
                    'cpa': poor['cpa'],
                    'spend': poor['spend'],
                    'conversions': poor['conversions'],
                    'target_cpa': target_cpa
                })

            # If clear winners, suggest focusing
            if len(good_placements) >= 2 and len(poor_placements) >= 2:
                opportunities.append({
                    'type': 'focus_on_winners',
                    'severity': 'low',
                    'ad_set_id': ad_set_id,
                    'ad_set_name': ad_set_name,
                    'winning_placements': good_placements,
                    'losing_placements': poor_placements
                })

            # Check for Audience Network specifically (often poor quality)
            an_metrics = placement_performance.get('audience_network', {})
            if an_metrics.get('cpa', 0) > target_cpa * 3 and an_metrics.get('spend', 0) > 30:
                opportunities.append({
                    'type': 'exclude_audience_network',
                    'severity': 'high',
                    'ad_set_id': ad_set_id,
                    'ad_set_name': ad_set_name,
                    'an_cpa': an_metrics.get('cpa'),
                    'an_spend': an_metrics.get('spend'),
                    'recommendation': 'Audience Network traffic is often low quality for lead gen'
                })

        return opportunities

    def decide(self, opportunities: List[Dict[str, Any]]) -> List[AgentDecision]:
        """Make placement optimization decisions."""
        decisions = []

        for opp in opportunities:
            opp_type = opp['type']

            if opp_type == 'exclude_placement':
                decision = AgentDecision(
                    agent_id=self.agent_id,
                    agent_type=self.agent_type,
                    decision_type='exclude_placement',
                    title=f"Exclude {opp['placement']} from '{opp['ad_set_name']}'",
                    description=f"CPA ${opp['cpa']:.2f} on ${opp['spend']:.0f} spend (target ${opp['target_cpa']:.2f})",
                    reasoning="Placement CPA is 2x+ above target with significant spend",
                    account_id=self.account_id or 0,
                    customer_id='',
                    ad_group_id=opp['ad_set_id'],
                    action_data={
                        'placement_to_exclude': opp['placement_key']
                    },
                    risk_level=DecisionRiskLevel.LOW,
                    requires_approval=False,
                    confidence=0.92,
                    expected_monthly_savings=opp['spend']
                )
                decisions.append(decision)

            elif opp_type == 'exclude_audience_network':
                decision = AgentDecision(
                    agent_id=self.agent_id,
                    agent_type=self.agent_type,
                    decision_type='exclude_audience_network',
                    title=f"Exclude Audience Network from '{opp['ad_set_name']}'",
                    description=f"AN CPA ${opp['an_cpa']:.2f} on ${opp['an_spend']:.0f} spend",
                    reasoning=opp['recommendation'],
                    account_id=self.account_id or 0,
                    customer_id='',
                    ad_group_id=opp['ad_set_id'],
                    action_data={
                        'placement_to_exclude': 'audience_network'
                    },
                    risk_level=DecisionRiskLevel.LOW,
                    requires_approval=False,
                    confidence=0.95,
                    expected_monthly_savings=opp['an_spend']
                )
                decisions.append(decision)

            elif opp_type == 'focus_on_winners':
                winner_names = [p['name'] for p in opp['winning_placements']]
                decision = AgentDecision(
                    agent_id=self.agent_id,
                    agent_type=self.agent_type,
                    decision_type='focus_placements',
                    title=f"Focus '{opp['ad_set_name']}' on winning placements",
                    description=f"Winners: {', '.join(winner_names)}",
                    reasoning="Clear performance difference between placements",
                    account_id=self.account_id or 0,
                    customer_id='',
                    ad_group_id=opp['ad_set_id'],
                    action_data={
                        'winning_placements': opp['winning_placements'],
                        'losing_placements': opp['losing_placements']
                    },
                    risk_level=DecisionRiskLevel.HIGH,
                    requires_approval=True,
                    confidence=0.85,
                    expected_improvement_pct=25.0
                )
                decisions.append(decision)

        return decisions

    def _execute_impl(self, decision: AgentDecision, fb_ads_client: Any) -> Dict[str, Any]:
        """Execute placement changes."""
        return {
            'success': True,
            'decision_type': decision.decision_type,
            'note': 'Placement changes require implementation in Ads Manager',
            'requires_manual_work': True
        }


class FBBidOptimizerAgent(BaseAgent):
    """
    Facebook Bid Optimizer - Manage bidding strategies and cost controls.

    Responsibilities:
    - Analyze bid strategy effectiveness
    - Recommend cost cap adjustments
    - Monitor bid competitiveness
    - Optimize for different conversion events

    Operates on: Daily cycles
    """

    def __init__(self, agent_id: str = "fb_bid_optimizer", **kwargs):
        super().__init__(
            agent_id=agent_id,
            capabilities=[
                AgentCapability.BID_OPTIMIZATION,
                AgentCapability.PERFORMANCE_MONITORING,
                AgentCapability.AUTONOMOUS_EXECUTION,
            ],
            auto_execute_threshold=0.90,
            **kwargs
        )

    def analyze(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Analyze bidding performance."""
        opportunities = []

        ad_sets = context.get('ad_sets', [])
        target_cpa = context.get('target_cpa', 50)

        for ad_set in ad_sets:
            ad_set_id = ad_set.get('id')
            ad_set_name = ad_set.get('name', '')
            bid_strategy = ad_set.get('bid_strategy', 'LOWEST_COST')
            cost_cap = ad_set.get('cost_cap', 0)
            actual_cpa = ad_set.get('cpa_7d', 0)
            conversions = ad_set.get('conversions_7d', 0)
            delivery_estimate = ad_set.get('delivery_estimate', '')

            # 1. Cost cap too restrictive (under-delivery)
            if cost_cap > 0 and delivery_estimate == 'LIMITED' and actual_cpa < cost_cap * 0.9:
                opportunities.append({
                    'type': 'increase_cost_cap',
                    'severity': 'medium',
                    'ad_set_id': ad_set_id,
                    'ad_set_name': ad_set_name,
                    'cost_cap': cost_cap,
                    'actual_cpa': actual_cpa,
                    'recommendation': 'Cost cap may be limiting delivery while actual CPA is well below'
                })

            # 2. Cost cap too loose (overspending)
            if cost_cap > 0 and actual_cpa > cost_cap * 1.2 and conversions >= 5:
                opportunities.append({
                    'type': 'tighten_cost_cap',
                    'severity': 'high',
                    'ad_set_id': ad_set_id,
                    'ad_set_name': ad_set_name,
                    'cost_cap': cost_cap,
                    'actual_cpa': actual_cpa,
                    'exceed_pct': ((actual_cpa - cost_cap) / cost_cap) * 100,
                    'recommendation': 'Facebook is spending above cost cap - tighten or use bid cap'
                })

            # 3. No cost control with high CPA
            if cost_cap == 0 and bid_strategy == 'LOWEST_COST' and actual_cpa > target_cpa * 1.3:
                opportunities.append({
                    'type': 'add_cost_control',
                    'severity': 'medium',
                    'ad_set_id': ad_set_id,
                    'ad_set_name': ad_set_name,
                    'actual_cpa': actual_cpa,
                    'target_cpa': target_cpa,
                    'recommendation': 'Add cost cap to control CPA on lowest cost bidding'
                })

            # 4. Consider bid cap for high-volume ad sets
            daily_conversions = conversions / 7
            if daily_conversions >= 10 and actual_cpa > target_cpa and bid_strategy != 'COST_CAP':
                opportunities.append({
                    'type': 'switch_to_cost_cap',
                    'severity': 'low',
                    'ad_set_id': ad_set_id,
                    'ad_set_name': ad_set_name,
                    'daily_conversions': daily_conversions,
                    'actual_cpa': actual_cpa,
                    'recommendation': 'High volume ad set could benefit from cost cap bidding'
                })

            # 5. Wrong optimization event
            optimization_goal = ad_set.get('optimization_goal', '')
            has_purchase_events = ad_set.get('has_purchase_events', False)

            if optimization_goal == 'LINK_CLICKS' and has_purchase_events:
                opportunities.append({
                    'type': 'optimize_for_conversions',
                    'severity': 'high',
                    'ad_set_id': ad_set_id,
                    'ad_set_name': ad_set_name,
                    'current_goal': optimization_goal,
                    'recommendation': 'Switch to conversion optimization for better results'
                })

        return opportunities

    def decide(self, opportunities: List[Dict[str, Any]]) -> List[AgentDecision]:
        """Make bid optimization decisions."""
        decisions = []

        for opp in opportunities:
            opp_type = opp['type']

            if opp_type == 'increase_cost_cap':
                new_cap = opp['cost_cap'] * 1.2
                decision = AgentDecision(
                    agent_id=self.agent_id,
                    agent_type=self.agent_type,
                    decision_type='adjust_cost_cap',
                    title=f"Increase cost cap for '{opp['ad_set_name']}'",
                    description=f"Current cap ${opp['cost_cap']:.2f}, actual CPA ${opp['actual_cpa']:.2f}",
                    reasoning=opp['recommendation'],
                    account_id=self.account_id or 0,
                    customer_id='',
                    ad_group_id=opp['ad_set_id'],
                    action_data={
                        'current_cap': opp['cost_cap'],
                        'new_cap': new_cap,
                        'direction': 'increase'
                    },
                    risk_level=DecisionRiskLevel.LOW,
                    requires_approval=False,
                    confidence=0.88,
                    expected_improvement_pct=15.0
                )
                decisions.append(decision)

            elif opp_type == 'tighten_cost_cap':
                new_cap = opp['cost_cap'] * 0.9
                decision = AgentDecision(
                    agent_id=self.agent_id,
                    agent_type=self.agent_type,
                    decision_type='adjust_cost_cap',
                    title=f"Tighten cost cap for '{opp['ad_set_name']}'",
                    description=f"Actual CPA ${opp['actual_cpa']:.2f} exceeds ${opp['cost_cap']:.2f} cap by {opp['exceed_pct']:.0f}%",
                    reasoning=opp['recommendation'],
                    account_id=self.account_id or 0,
                    customer_id='',
                    ad_group_id=opp['ad_set_id'],
                    action_data={
                        'current_cap': opp['cost_cap'],
                        'new_cap': new_cap,
                        'direction': 'decrease'
                    },
                    risk_level=DecisionRiskLevel.LOW,
                    requires_approval=False,
                    confidence=0.90,
                    expected_monthly_savings=(opp['actual_cpa'] - opp['cost_cap']) * 30
                )
                decisions.append(decision)

            elif opp_type == 'add_cost_control':
                decision = AgentDecision(
                    agent_id=self.agent_id,
                    agent_type=self.agent_type,
                    decision_type='add_cost_cap',
                    title=f"Add cost cap to '{opp['ad_set_name']}'",
                    description=f"Actual CPA ${opp['actual_cpa']:.2f} vs target ${opp['target_cpa']:.2f}",
                    reasoning=opp['recommendation'],
                    account_id=self.account_id or 0,
                    customer_id='',
                    ad_group_id=opp['ad_set_id'],
                    action_data={
                        'suggested_cap': opp['target_cpa']
                    },
                    risk_level=DecisionRiskLevel.HIGH,
                    requires_approval=True,
                    confidence=0.85,
                    expected_monthly_savings=(opp['actual_cpa'] - opp['target_cpa']) * 30
                )
                decisions.append(decision)

            elif opp_type == 'optimize_for_conversions':
                decision = AgentDecision(
                    agent_id=self.agent_id,
                    agent_type=self.agent_type,
                    decision_type='change_optimization_goal',
                    title=f"Switch '{opp['ad_set_name']}' to conversion optimization",
                    description=f"Currently optimizing for {opp['current_goal']}",
                    reasoning=opp['recommendation'],
                    account_id=self.account_id or 0,
                    customer_id='',
                    ad_group_id=opp['ad_set_id'],
                    action_data={
                        'current_goal': opp['current_goal'],
                        'new_goal': 'CONVERSIONS'
                    },
                    risk_level=DecisionRiskLevel.HIGH,
                    requires_approval=True,
                    confidence=0.92,
                    expected_improvement_pct=30.0
                )
                decisions.append(decision)

        return decisions

    def _execute_impl(self, decision: AgentDecision, fb_ads_client: Any) -> Dict[str, Any]:
        """Execute bid changes via Graph API where possible."""
        decision_type = decision.decision_type
        account_id = decision.account_id

        if decision_type == 'adjust_cost_cap':
            # ad_group_id holds the adset_id for FB agents
            adset_id = decision.ad_group_id
            new_cap = decision.action_data.get('new_cap')
            if adset_id and new_cap is not None:
                result = _fb_execute_action(
                    account_id=account_id,
                    entity_id=str(adset_id),
                    entity_type='adset',
                    action='adjust_bid',
                    params={'bid_amount': float(new_cap)},
                )
                return {
                    **result,
                    'decision_type': decision_type,
                    'adset_id': adset_id,
                    'old_cap': decision.action_data.get('current_cap'),
                    'new_cap': new_cap,
                }
            return {
                'success': False,
                'error': 'Missing adset_id or new_cap',
                'decision_type': decision_type,
            }

        # Non-mutating decision types (need manual setup)
        return {
            'success': True,
            'decision_type': decision_type,
            'note': 'Bid changes require implementation in Ads Manager',
            'requires_manual_work': True,
            'action_data': decision.action_data,
        }


class FBCreativeOptimizerAgent(BaseAgent):
    """
    Facebook Creative Optimizer - A/B tests and creative management.

    Responsibilities:
    - Manage ad variations and testing
    - Pause underperforming creatives
    - Identify winning creative patterns
    - Recommend creative refreshes
    - Analyze copy and visual performance

    Operates on: Weekly cycles
    """

    def __init__(self, agent_id: str = "fb_creative_optimizer", **kwargs):
        super().__init__(
            agent_id=agent_id,
            capabilities=[
                AgentCapability.AD_CREATION,
                AgentCapability.QUALITY_SCORE_OPTIMIZATION,
            ],
            auto_execute_threshold=0.85,
            **kwargs
        )

    def analyze(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Analyze creative performance."""
        opportunities = []

        ads = context.get('ads', [])
        ad_sets = context.get('ad_sets', [])

        # Group ads by ad set
        ads_by_set = {}
        for ad in ads:
            ad_set_id = ad.get('ad_set_id')
            if ad_set_id not in ads_by_set:
                ads_by_set[ad_set_id] = []
            ads_by_set[ad_set_id].append(ad)

        for ad_set_id, ad_set_ads in ads_by_set.items():
            ad_set = next((a for a in ad_sets if a.get('id') == ad_set_id), {})
            ad_set_name = ad_set.get('name', '')

            # 1. Need more creative variations
            active_ads = [a for a in ad_set_ads if a.get('status') == 'ACTIVE']
            if len(active_ads) < 3:
                opportunities.append({
                    'type': 'need_more_creatives',
                    'severity': 'medium',
                    'ad_set_id': ad_set_id,
                    'ad_set_name': ad_set_name,
                    'active_ad_count': len(active_ads),
                    'recommendation': 'Test 3-6 ad variations for better optimization'
                })

            # 2. Pause underperformers
            if len(active_ads) >= 3:
                # Sort by CTR
                sorted_ads = sorted(active_ads, key=lambda a: a.get('ctr_7d', 0), reverse=True)
                avg_ctr = sum(a.get('ctr_7d', 0) for a in active_ads) / len(active_ads)

                for ad in sorted_ads:
                    ad_ctr = ad.get('ctr_7d', 0)
                    impressions = ad.get('impressions_7d', 0)

                    # Underperformer with enough data
                    if impressions > 1000 and ad_ctr < avg_ctr * 0.7:
                        opportunities.append({
                            'type': 'pause_underperformer',
                            'severity': 'low',
                            'ad_id': ad.get('id'),
                            'ad_name': ad.get('name'),
                            'ad_set_id': ad_set_id,
                            'ctr': ad_ctr,
                            'avg_ctr': avg_ctr,
                            'impressions': impressions
                        })

            # 3. Identify winning patterns
            for ad in active_ads:
                if ad.get('ctr_7d', 0) > 2.0 and ad.get('conversions_7d', 0) >= 5:
                    opportunities.append({
                        'type': 'winning_creative',
                        'severity': 'info',
                        'ad_id': ad.get('id'),
                        'ad_name': ad.get('name'),
                        'ad_set_id': ad_set_id,
                        'ctr': ad.get('ctr_7d'),
                        'conversions': ad.get('conversions_7d'),
                        'creative_type': ad.get('creative_type'),
                        'headline': ad.get('headline'),
                        'recommendation': 'Create variations of this winning creative'
                    })

        return opportunities

    def decide(self, opportunities: List[Dict[str, Any]]) -> List[AgentDecision]:
        """Make creative optimization decisions."""
        decisions = []

        for opp in opportunities:
            opp_type = opp['type']

            if opp_type == 'need_more_creatives':
                decision = AgentDecision(
                    agent_id=self.agent_id,
                    agent_type=self.agent_type,
                    decision_type='add_creatives',
                    title=f"Add more ad variations to '{opp['ad_set_name']}'",
                    description=f"Currently only {opp['active_ad_count']} active ads",
                    reasoning=opp['recommendation'],
                    account_id=self.account_id or 0,
                    customer_id='',
                    ad_group_id=opp['ad_set_id'],
                    action_data={
                        'current_count': opp['active_ad_count'],
                        'recommended_count': 5,
                        'suggestions': [
                            'Test different headlines',
                            'Try image vs video',
                            'Test different CTAs',
                            'Use different value propositions'
                        ]
                    },
                    risk_level=DecisionRiskLevel.LOW,
                    requires_approval=False,
                    confidence=0.85,
                    expected_improvement_pct=15.0
                )
                decisions.append(decision)

            elif opp_type == 'pause_underperformer':
                decision = AgentDecision(
                    agent_id=self.agent_id,
                    agent_type=self.agent_type,
                    decision_type='pause_ad',
                    title=f"Pause underperforming ad '{opp['ad_name']}'",
                    description=f"CTR {opp['ctr']:.2f}% vs {opp['avg_ctr']:.2f}% average ({opp['impressions']:,} impressions)",
                    reasoning="Ad is 30%+ below average CTR with sufficient data",
                    account_id=self.account_id or 0,
                    customer_id='',
                    action_data={
                        'ad_id': opp['ad_id']
                    },
                    risk_level=DecisionRiskLevel.LOW,
                    requires_approval=False,
                    confidence=0.90
                )
                decisions.append(decision)

            elif opp_type == 'winning_creative':
                decision = AgentDecision(
                    agent_id=self.agent_id,
                    agent_type=self.agent_type,
                    decision_type='scale_creative',
                    title=f"Scale winning creative '{opp['ad_name']}'",
                    description=f"CTR {opp['ctr']:.2f}%, {opp['conversions']} conversions",
                    reasoning=opp['recommendation'],
                    account_id=self.account_id or 0,
                    customer_id='',
                    action_data={
                        'ad_id': opp['ad_id'],
                        'creative_type': opp['creative_type'],
                        'headline': opp['headline'],
                        'suggestions': [
                            'Duplicate to other ad sets',
                            'Create variations with same theme',
                            'Test in other audiences',
                            'Increase budget allocation'
                        ]
                    },
                    risk_level=DecisionRiskLevel.LOW,
                    requires_approval=False,
                    confidence=0.88,
                    expected_improvement_pct=20.0
                )
                decisions.append(decision)

        return decisions

    def _execute_impl(self, decision: AgentDecision, fb_ads_client: Any) -> Dict[str, Any]:
        """Execute creative changes via Graph API where possible."""
        decision_type = decision.decision_type
        account_id = decision.account_id

        if decision_type == 'pause_ad':
            ad_id = decision.action_data.get('ad_id')
            if ad_id:
                result = _fb_execute_action(
                    account_id=account_id,
                    entity_id=str(ad_id),
                    entity_type='ad',
                    action='pause',
                )
                return {**result, 'decision_type': decision_type, 'ad_id': ad_id}
            return {'success': False, 'error': 'Missing ad_id', 'decision_type': decision_type}

        # Non-mutating decision types
        return {
            'success': True,
            'decision_type': decision_type,
            'note': 'Creative changes require implementation in Ads Manager',
            'requires_manual_work': True,
            'suggestions': decision.action_data.get('suggestions', []),
        }
