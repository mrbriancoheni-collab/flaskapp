# app/agents/fbads_operational.py
"""
Facebook Ads Operational Layer - Daily management and coordination agents.

These agents monitor day-to-day performance, catch problems early,
and delegate tactical work to specialist agents.
"""

from typing import Dict, List, Any
from datetime import datetime, timedelta
from .base import BaseAgent, AgentDecision, AgentCapability, DecisionRiskLevel

import logging
logger = logging.getLogger(__name__)


class FBCampaignManagerAgent(BaseAgent):
    """
    Facebook Campaign Manager - 24/7 performance monitoring.

    Responsibilities:
    - Track daily performance across all campaigns and ad sets
    - Detect anomalies (CPA spikes, conversion drops, delivery issues)
    - Adjust budgets to maintain target CPA/ROAS
    - Monitor learning phase status
    - Report issues to Strategic Director

    Operates on: Hourly/Daily cycles
    """

    def __init__(self, agent_id: str = "fb_campaign_manager", **kwargs):
        super().__init__(
            agent_id=agent_id,
            capabilities=[
                AgentCapability.PERFORMANCE_MONITORING,
                AgentCapability.BID_OPTIMIZATION,
                AgentCapability.AUTONOMOUS_EXECUTION,
            ],
            auto_execute_threshold=0.90,
            **kwargs
        )

        # Performance baselines
        self.baselines = {}

    def analyze(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Analyze daily campaign performance."""
        opportunities = []

        campaigns = context.get('campaigns', [])
        ad_sets = context.get('ad_sets', [])
        target_cpa = context.get('target_cpa', 50)
        target_roas = context.get('target_roas', 3.0)

        for campaign in campaigns:
            campaign_id = campaign['id']
            campaign_name = campaign.get('name', '')

            # Get metrics
            current_cpa = campaign.get('cpa_7d', 0)
            baseline_cpa = self.baselines.get(campaign_id, {}).get('cpa', target_cpa)
            current_roas = campaign.get('roas_7d', 0)
            conversion_rate = campaign.get('conversion_rate_7d', 0)
            baseline_conv_rate = self.baselines.get(campaign_id, {}).get('conv_rate', 2.0)

            # 1. CPA spike detection
            if current_cpa > 0 and current_cpa > baseline_cpa * 1.3:
                opportunities.append({
                    'type': 'cpa_spike',
                    'severity': 'high',
                    'campaign_id': campaign_id,
                    'campaign_name': campaign_name,
                    'current_cpa': current_cpa,
                    'baseline_cpa': baseline_cpa,
                    'spike_pct': ((current_cpa - baseline_cpa) / baseline_cpa) * 100
                })

            # 2. Conversion rate drop
            if conversion_rate < baseline_conv_rate * 0.7 and baseline_conv_rate > 0:
                opportunities.append({
                    'type': 'conversion_rate_drop',
                    'severity': 'high',
                    'campaign_id': campaign_id,
                    'campaign_name': campaign_name,
                    'current_rate': conversion_rate,
                    'baseline_rate': baseline_conv_rate,
                    'drop_pct': ((baseline_conv_rate - conversion_rate) / baseline_conv_rate) * 100
                })

            # 3. Budget pacing issues
            daily_budget = campaign.get('daily_budget', 0)
            spend_today = campaign.get('spend_today', 0)
            hour_of_day = datetime.now().hour

            if daily_budget > 0 and hour_of_day >= 12:
                expected_spend_pct = hour_of_day / 24
                actual_spend_pct = spend_today / daily_budget

                if actual_spend_pct < expected_spend_pct * 0.5:
                    # Underspending significantly
                    opportunities.append({
                        'type': 'underspending',
                        'severity': 'medium',
                        'campaign_id': campaign_id,
                        'campaign_name': campaign_name,
                        'daily_budget': daily_budget,
                        'spend_today': spend_today,
                        'expected_spend': daily_budget * expected_spend_pct,
                        'reason': 'Budget not being utilized - may indicate audience, bid, or creative issues'
                    })

        # 4. Ad set learning phase monitoring
        for ad_set in ad_sets:
            learning_status = ad_set.get('learning_phase_status', '')
            conversions_7d = ad_set.get('conversions_7d', 0)

            if learning_status == 'LEARNING_LIMITED':
                opportunities.append({
                    'type': 'learning_limited',
                    'severity': 'medium',
                    'ad_set_id': ad_set.get('id'),
                    'ad_set_name': ad_set.get('name'),
                    'campaign_id': ad_set.get('campaign_id'),
                    'conversions_7d': conversions_7d,
                    'recommendation': 'Increase budget, broaden audience, or switch to higher-funnel event'
                })

            # Check for stuck in learning phase
            days_in_learning = ad_set.get('days_in_learning', 0)
            if learning_status == 'LEARNING' and days_in_learning > 7:
                opportunities.append({
                    'type': 'stuck_in_learning',
                    'severity': 'high',
                    'ad_set_id': ad_set.get('id'),
                    'ad_set_name': ad_set.get('name'),
                    'days_in_learning': days_in_learning,
                    'conversions_7d': conversions_7d,
                    'recommendation': 'Ad set needs 50 conversions/week to exit learning. Consider consolidation.'
                })

        # 5. Delivery issues
        for ad_set in ad_sets:
            delivery_status = ad_set.get('effective_status', '')

            if delivery_status in ['CAMPAIGN_PAUSED', 'ADSET_PAUSED', 'AD_PAUSED']:
                continue  # Intentionally paused

            if delivery_status == 'NOT_DELIVERING':
                opportunities.append({
                    'type': 'delivery_issue',
                    'severity': 'high',
                    'ad_set_id': ad_set.get('id'),
                    'ad_set_name': ad_set.get('name'),
                    'status': delivery_status,
                    'reason': ad_set.get('delivery_issue_reason', 'Unknown')
                })

        return opportunities

    def decide(self, opportunities: List[Dict[str, Any]]) -> List[AgentDecision]:
        """Make operational decisions."""
        decisions = []

        for opp in opportunities:
            opp_type = opp['type']

            if opp_type == 'cpa_spike':
                decision = AgentDecision(
                    agent_id=self.agent_id,
                    agent_type=self.agent_type,
                    decision_type='investigate_cpa_spike',
                    title=f"Investigate CPA spike in '{opp['campaign_name']}'",
                    description=f"CPA increased {opp['spike_pct']:.0f}% from ${opp['baseline_cpa']:.2f} to ${opp['current_cpa']:.2f}",
                    reasoning="Sudden CPA spike requires investigation - check audience, creative, or landing page issues",
                    account_id=self.account_id or 0,
                    customer_id='',
                    campaign_id=opp['campaign_id'],
                    action_data={
                        'investigation_steps': [
                            'Check audience overlap with other ad sets',
                            'Review creative performance breakdown',
                            'Analyze placement performance',
                            'Check for landing page issues',
                            'Review recent audience changes'
                        ]
                    },
                    risk_level=DecisionRiskLevel.LOW,
                    requires_approval=False,
                    confidence=0.95
                )
                decisions.append(decision)

            elif opp_type == 'learning_limited':
                decision = AgentDecision(
                    agent_id=self.agent_id,
                    agent_type=self.agent_type,
                    decision_type='fix_learning_limited',
                    title=f"Fix Learning Limited status on '{opp['ad_set_name']}'",
                    description=f"Only {opp['conversions_7d']} conversions in 7 days (need 50+)",
                    reasoning=opp['recommendation'],
                    account_id=self.account_id or 0,
                    customer_id='',
                    ad_group_id=opp['ad_set_id'],
                    campaign_id=opp['campaign_id'],
                    action_data={
                        'options': [
                            'Increase daily budget by 20-50%',
                            'Broaden audience targeting',
                            'Use a higher-funnel conversion event',
                            'Consolidate with similar ad sets'
                        ],
                        'conversions_needed': 50 - opp['conversions_7d']
                    },
                    risk_level=DecisionRiskLevel.MEDIUM,
                    requires_approval=True,
                    confidence=0.85,
                    expected_improvement_pct=20.0
                )
                decisions.append(decision)

            elif opp_type == 'delivery_issue':
                decision = AgentDecision(
                    agent_id=self.agent_id,
                    agent_type=self.agent_type,
                    decision_type='fix_delivery_issue',
                    title=f"Fix delivery issue on '{opp['ad_set_name']}'",
                    description=f"Status: {opp['status']}, Reason: {opp['reason']}",
                    reasoning="Ad set is not delivering - needs immediate attention",
                    account_id=self.account_id or 0,
                    customer_id='',
                    ad_group_id=opp['ad_set_id'],
                    action_data={
                        'status': opp['status'],
                        'reason': opp['reason']
                    },
                    risk_level=DecisionRiskLevel.LOW,
                    requires_approval=False,
                    confidence=0.95
                )
                decisions.append(decision)

            elif opp_type == 'underspending':
                decision = AgentDecision(
                    agent_id=self.agent_id,
                    agent_type=self.agent_type,
                    decision_type='investigate_underspending',
                    title=f"Investigate underspending in '{opp['campaign_name']}'",
                    description=f"Spent ${opp['spend_today']:.0f} of ${opp['daily_budget']:.0f} budget (expected ${opp['expected_spend']:.0f})",
                    reasoning=opp['reason'],
                    account_id=self.account_id or 0,
                    customer_id='',
                    campaign_id=opp['campaign_id'],
                    action_data={
                        'investigation_steps': [
                            'Check bid cap settings - may be too restrictive',
                            'Review audience size - may be too small',
                            'Check creative relevance scores',
                            'Review policy issues on ads',
                            'Check cost cap constraints'
                        ]
                    },
                    risk_level=DecisionRiskLevel.LOW,
                    requires_approval=False,
                    confidence=0.90
                )
                decisions.append(decision)

        return decisions

    def _execute_impl(self, decision: AgentDecision, fb_ads_client: Any) -> Dict[str, Any]:
        """Execute operational decisions."""
        decision_type = decision.decision_type

        # Most operational decisions are investigations or require manual action
        return {
            'success': True,
            'decision_type': decision_type,
            'action_taken': 'investigation_initiated' if 'investigate' in decision_type else 'recommendation_generated',
            'steps': decision.action_data.get('investigation_steps', decision.action_data.get('options', []))
        }


class FBBudgetGuardianAgent(BaseAgent):
    """
    Facebook Budget Guardian - Stops wasted spend before it happens.

    Responsibilities:
    - Monitor budget pacing across campaigns
    - Prevent budget overruns on daily/lifetime budgets
    - Detect and pause runaway spending
    - Monitor cost cap effectiveness
    - Alert on unusual spend patterns

    Operates on: Hourly cycles
    """

    def __init__(self, agent_id: str = "fb_budget_guardian", **kwargs):
        super().__init__(
            agent_id=agent_id,
            capabilities=[
                AgentCapability.BUDGET_MANAGEMENT,
                AgentCapability.PERFORMANCE_MONITORING,
                AgentCapability.AUTONOMOUS_EXECUTION,
            ],
            auto_execute_threshold=0.95,  # Very confident for budget protection
            **kwargs
        )

    def analyze(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Analyze budget pacing and spend patterns."""
        opportunities = []

        campaigns = context.get('campaigns', [])
        ad_sets = context.get('ad_sets', [])
        account_spending_limit = context.get('account_spending_limit', 0)
        account_spend_mtd = context.get('account_spend_mtd', 0)

        current_day_of_month = datetime.now().day
        days_in_month = 30
        elapsed_pct = current_day_of_month / days_in_month

        # 1. Account-level spending limit check
        if account_spending_limit > 0:
            spend_pct = account_spend_mtd / account_spending_limit

            if spend_pct >= 0.90:
                opportunities.append({
                    'type': 'account_limit_approaching',
                    'severity': 'critical',
                    'spending_limit': account_spending_limit,
                    'spend_mtd': account_spend_mtd,
                    'spend_pct': spend_pct * 100
                })

        # 2. Campaign budget pacing
        for campaign in campaigns:
            campaign_id = campaign['id']
            campaign_name = campaign.get('name', '')
            budget_type = campaign.get('budget_type', 'daily')
            budget_amount = campaign.get('daily_budget', 0) if budget_type == 'daily' else campaign.get('lifetime_budget', 0)
            spend_today = campaign.get('spend_today', 0)
            spend_lifetime = campaign.get('spend_lifetime', 0)

            # Runaway spend detection (daily budget)
            if budget_type == 'daily' and budget_amount > 0:
                spend_7d_avg = campaign.get('daily_spend_avg_7d', 0)

                if spend_today > budget_amount * 1.2:  # Spending more than budget (Facebook can overspend 25%)
                    opportunities.append({
                        'type': 'overspending_daily',
                        'severity': 'high',
                        'campaign_id': campaign_id,
                        'campaign_name': campaign_name,
                        'daily_budget': budget_amount,
                        'spend_today': spend_today,
                        'overspend_pct': ((spend_today - budget_amount) / budget_amount) * 100
                    })

                # Anomaly: spending way more than average
                if spend_today > spend_7d_avg * 2 and spend_7d_avg > 0:
                    opportunities.append({
                        'type': 'spend_anomaly',
                        'severity': 'high',
                        'campaign_id': campaign_id,
                        'campaign_name': campaign_name,
                        'spend_today': spend_today,
                        'avg_daily_spend': spend_7d_avg
                    })

            # Lifetime budget pacing
            if budget_type == 'lifetime' and budget_amount > 0:
                campaign_end_date = campaign.get('end_date')
                if campaign_end_date:
                    days_remaining = (campaign_end_date - datetime.now()).days
                    remaining_budget = budget_amount - spend_lifetime

                    if days_remaining > 0:
                        daily_pace_needed = remaining_budget / days_remaining
                        actual_daily_spend = campaign.get('daily_spend_avg_7d', 0)

                        if actual_daily_spend > daily_pace_needed * 1.5:
                            opportunities.append({
                                'type': 'lifetime_overpacing',
                                'severity': 'high',
                                'campaign_id': campaign_id,
                                'campaign_name': campaign_name,
                                'lifetime_budget': budget_amount,
                                'spend_to_date': spend_lifetime,
                                'days_remaining': days_remaining,
                                'needed_daily_pace': daily_pace_needed,
                                'actual_daily_pace': actual_daily_spend
                            })

        # 3. Cost cap effectiveness
        for ad_set in ad_sets:
            cost_cap = ad_set.get('cost_cap', 0)
            actual_cpa = ad_set.get('cpa_7d', 0)

            if cost_cap > 0 and actual_cpa > cost_cap * 1.2:
                opportunities.append({
                    'type': 'cost_cap_exceeded',
                    'severity': 'medium',
                    'ad_set_id': ad_set.get('id'),
                    'ad_set_name': ad_set.get('name'),
                    'cost_cap': cost_cap,
                    'actual_cpa': actual_cpa,
                    'exceed_pct': ((actual_cpa - cost_cap) / cost_cap) * 100
                })

        return opportunities

    def decide(self, opportunities: List[Dict[str, Any]]) -> List[AgentDecision]:
        """Make budget protection decisions."""
        decisions = []

        for opp in opportunities:
            opp_type = opp['type']

            if opp_type == 'account_limit_approaching':
                decision = AgentDecision(
                    agent_id=self.agent_id,
                    agent_type=self.agent_type,
                    decision_type='account_limit_warning',
                    title=f"Account spending limit at {opp['spend_pct']:.0f}%",
                    description=f"Spent ${opp['spend_mtd']:,.0f} of ${opp['spending_limit']:,.0f} account limit",
                    reasoning="Account will stop delivering when limit is reached",
                    account_id=self.account_id or 0,
                    customer_id='',
                    action_data={
                        'options': [
                            'Increase account spending limit',
                            'Prioritize top-performing campaigns',
                            'Pause low-performers to preserve budget'
                        ]
                    },
                    risk_level=DecisionRiskLevel.HIGH,
                    requires_approval=True,
                    confidence=0.99
                )
                decisions.append(decision)

            elif opp_type == 'spend_anomaly':
                decision = AgentDecision(
                    agent_id=self.agent_id,
                    agent_type=self.agent_type,
                    decision_type='investigate_spend_anomaly',
                    title=f"Unusual spending in '{opp['campaign_name']}'",
                    description=f"Today's spend ${opp['spend_today']:.0f} is 2x+ the ${opp['avg_daily_spend']:.0f} average",
                    reasoning="Sudden spend increase may indicate issue or opportunity",
                    account_id=self.account_id or 0,
                    customer_id='',
                    campaign_id=opp['campaign_id'],
                    action_data={
                        'investigation_steps': [
                            'Check if CPA is still within target',
                            'Review audience changes',
                            'Check for competitor changes',
                            'Verify bid strategy settings'
                        ]
                    },
                    risk_level=DecisionRiskLevel.MEDIUM,
                    requires_approval=False,
                    confidence=0.90
                )
                decisions.append(decision)

            elif opp_type == 'lifetime_overpacing':
                decision = AgentDecision(
                    agent_id=self.agent_id,
                    agent_type=self.agent_type,
                    decision_type='adjust_pacing',
                    title=f"Reduce daily spend for '{opp['campaign_name']}'",
                    description=f"Spending ${opp['actual_daily_pace']:.0f}/day but need ${opp['needed_daily_pace']:.0f}/day to last {opp['days_remaining']} days",
                    reasoning="Campaign will exhaust lifetime budget early at current pace",
                    account_id=self.account_id or 0,
                    customer_id='',
                    campaign_id=opp['campaign_id'],
                    action_data={
                        'current_pace': opp['actual_daily_pace'],
                        'needed_pace': opp['needed_daily_pace'],
                        'days_remaining': opp['days_remaining']
                    },
                    risk_level=DecisionRiskLevel.LOW,
                    requires_approval=False,
                    confidence=0.95,
                    expected_monthly_savings=opp['actual_daily_pace'] - opp['needed_daily_pace']
                )
                decisions.append(decision)

            elif opp_type == 'cost_cap_exceeded':
                decision = AgentDecision(
                    agent_id=self.agent_id,
                    agent_type=self.agent_type,
                    decision_type='review_cost_cap',
                    title=f"Cost cap exceeded on '{opp['ad_set_name']}'",
                    description=f"Actual CPA ${opp['actual_cpa']:.2f} is {opp['exceed_pct']:.0f}% above ${opp['cost_cap']:.2f} cap",
                    reasoning="Cost cap isn't being respected - may need adjustment or ad set pause",
                    account_id=self.account_id or 0,
                    customer_id='',
                    ad_group_id=opp['ad_set_id'],
                    action_data={
                        'options': [
                            'Lower cost cap further',
                            'Broaden audience for more opportunity',
                            'Pause ad set and reallocate budget',
                            'Switch to lowest cost bidding'
                        ]
                    },
                    risk_level=DecisionRiskLevel.MEDIUM,
                    requires_approval=True,
                    confidence=0.85
                )
                decisions.append(decision)

        return decisions

    def _execute_impl(self, decision: AgentDecision, fb_ads_client: Any) -> Dict[str, Any]:
        """Execute budget protection decisions."""
        decision_type = decision.decision_type

        # Most budget decisions require approval or investigation
        return {
            'success': True,
            'decision_type': decision_type,
            'action_taken': 'alert_generated',
            'requires_action': True
        }


class FBCreativeAnalystAgent(BaseAgent):
    """
    Facebook Creative Analyst - Monitor and optimize ad creative performance.

    Responsibilities:
    - Track creative performance metrics (CTR, hook rate, hold rate)
    - Identify creative fatigue
    - Monitor relevance scores
    - Compare video vs image performance
    - Track ad approval status

    Operates on: Daily cycles
    """

    def __init__(self, agent_id: str = "fb_creative_analyst", **kwargs):
        super().__init__(
            agent_id=agent_id,
            capabilities=[
                AgentCapability.PERFORMANCE_MONITORING,
                AgentCapability.AD_CREATION,
            ],
            auto_execute_threshold=0.85,
            **kwargs
        )

    def analyze(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Analyze creative performance."""
        opportunities = []

        ads = context.get('ads', [])

        for ad in ads:
            ad_id = ad.get('id')
            ad_name = ad.get('name', '')
            ad_set_id = ad.get('ad_set_id')

            # 1. Low relevance score
            relevance_score = ad.get('quality_ranking', '')
            if relevance_score in ['BELOW_AVERAGE_10', 'BELOW_AVERAGE_20', 'BELOW_AVERAGE_35']:
                opportunities.append({
                    'type': 'low_relevance',
                    'severity': 'high',
                    'ad_id': ad_id,
                    'ad_name': ad_name,
                    'ad_set_id': ad_set_id,
                    'quality_ranking': relevance_score,
                    'recommendation': 'Improve ad relevance to target audience or narrow targeting'
                })

            # 2. Creative fatigue (high frequency + declining CTR)
            frequency = ad.get('frequency', 0)
            ctr_7d = ad.get('ctr_7d', 0)
            ctr_14d = ad.get('ctr_14d', 0)

            if frequency > 3 and ctr_14d > 0 and ctr_7d < ctr_14d * 0.8:
                opportunities.append({
                    'type': 'creative_fatigue',
                    'severity': 'medium',
                    'ad_id': ad_id,
                    'ad_name': ad_name,
                    'ad_set_id': ad_set_id,
                    'frequency': frequency,
                    'ctr_7d': ctr_7d,
                    'ctr_14d': ctr_14d,
                    'ctr_decline_pct': ((ctr_14d - ctr_7d) / ctr_14d) * 100
                })

            # 3. Video metrics (if applicable)
            if ad.get('creative_type') == 'VIDEO':
                hook_rate = ad.get('video_hook_rate', 0)  # % watched 3+ seconds
                hold_rate = ad.get('video_hold_rate', 0)  # % watched 15+ seconds
                thumb_stop = ad.get('thumb_stop_ratio', 0)

                if hook_rate < 20:
                    opportunities.append({
                        'type': 'poor_hook_rate',
                        'severity': 'high',
                        'ad_id': ad_id,
                        'ad_name': ad_name,
                        'hook_rate': hook_rate,
                        'recommendation': 'First 3 seconds need to be more attention-grabbing'
                    })

                if hold_rate < 10 and hook_rate > 20:
                    opportunities.append({
                        'type': 'poor_hold_rate',
                        'severity': 'medium',
                        'ad_id': ad_id,
                        'ad_name': ad_name,
                        'hook_rate': hook_rate,
                        'hold_rate': hold_rate,
                        'recommendation': 'Hook is working but content after 3s is losing viewers'
                    })

            # 4. Ad disapproval/policy issues
            review_status = ad.get('review_status', '')
            if review_status in ['DISAPPROVED', 'PREAPPROVED']:
                opportunities.append({
                    'type': 'ad_disapproved',
                    'severity': 'critical',
                    'ad_id': ad_id,
                    'ad_name': ad_name,
                    'status': review_status,
                    'reason': ad.get('disapproval_reasons', ['Unknown'])
                })

        return opportunities

    def decide(self, opportunities: List[Dict[str, Any]]) -> List[AgentDecision]:
        """Make creative optimization decisions."""
        decisions = []

        for opp in opportunities:
            opp_type = opp['type']

            if opp_type == 'creative_fatigue':
                decision = AgentDecision(
                    agent_id=self.agent_id,
                    agent_type=self.agent_type,
                    decision_type='refresh_creative',
                    title=f"Refresh fatigued creative '{opp['ad_name']}'",
                    description=f"Frequency: {opp['frequency']:.1f}x, CTR dropped {opp['ctr_decline_pct']:.0f}%",
                    reasoning="Audience has seen this ad too many times - performance is declining",
                    account_id=self.account_id or 0,
                    customer_id='',
                    action_data={
                        'ad_id': opp['ad_id'],
                        'ad_set_id': opp['ad_set_id'],
                        'options': [
                            'Create new creative variation',
                            'Update headline or copy',
                            'Test new image/video',
                            'Pause and rotate in fresh creative'
                        ]
                    },
                    risk_level=DecisionRiskLevel.LOW,
                    requires_approval=False,
                    confidence=0.90,
                    expected_improvement_pct=20.0
                )
                decisions.append(decision)

            elif opp_type == 'poor_hook_rate':
                decision = AgentDecision(
                    agent_id=self.agent_id,
                    agent_type=self.agent_type,
                    decision_type='improve_video_hook',
                    title=f"Improve video hook for '{opp['ad_name']}'",
                    description=f"Only {opp['hook_rate']:.0f}% watch past 3 seconds (target: 30%+)",
                    reasoning=opp['recommendation'],
                    account_id=self.account_id or 0,
                    customer_id='',
                    action_data={
                        'ad_id': opp['ad_id'],
                        'tips': [
                            'Start with movement or action',
                            'Use text overlay in first 2 seconds',
                            'Open with a question or bold claim',
                            'Show the product/result immediately'
                        ]
                    },
                    risk_level=DecisionRiskLevel.LOW,
                    requires_approval=False,
                    confidence=0.85,
                    expected_improvement_pct=30.0
                )
                decisions.append(decision)

            elif opp_type == 'ad_disapproved':
                decision = AgentDecision(
                    agent_id=self.agent_id,
                    agent_type=self.agent_type,
                    decision_type='fix_disapproved_ad',
                    title=f"Fix disapproved ad '{opp['ad_name']}'",
                    description=f"Status: {opp['status']}, Reasons: {', '.join(opp['reason'])}",
                    reasoning="Ad is not delivering due to policy violation",
                    account_id=self.account_id or 0,
                    customer_id='',
                    action_data={
                        'ad_id': opp['ad_id'],
                        'status': opp['status'],
                        'reasons': opp['reason']
                    },
                    risk_level=DecisionRiskLevel.CRITICAL,
                    requires_approval=True,
                    confidence=0.99
                )
                decisions.append(decision)

        return decisions

    def _execute_impl(self, decision: AgentDecision, fb_ads_client: Any) -> Dict[str, Any]:
        """Execute creative decisions."""
        return {
            'success': True,
            'decision_type': decision.decision_type,
            'note': 'Creative changes require manual implementation',
            'requires_manual_work': True,
            'tips': decision.action_data.get('tips', decision.action_data.get('options', []))
        }
