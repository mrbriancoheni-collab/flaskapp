# app/agents/operational.py
"""
Operational Layer - Daily management and coordination agents.

These agents monitor day-to-day performance, catch problems early,
and delegate tactical work to specialist agents.
"""

from typing import Dict, List, Any
from datetime import datetime, timedelta
from .base import BaseAgent, AgentDecision, AgentCapability, DecisionRiskLevel


class CampaignManagerAgent(BaseAgent):
    """
    Campaign Manager - 24/7 performance monitoring.

    Responsibilities:
    - Track daily performance across all campaigns
    - Detect anomalies (CPL spikes, conversion drops, etc.)
    - Adjust bids to maintain target CPL
    - Delegate specific problems to tactical agents
    - Report issues to Strategic Director

    Operates on: Hourly/Daily cycles
    """

    def __init__(self, agent_id: str = "campaign_manager", **kwargs):
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
        target_cpl = context.get('target_cpl', 100)

        # Only make conversion-based suggestions when tracking is active
        total_conversions = sum(c.get('conversions', 0) for c in campaigns)
        conversions_tracked = total_conversions > 0

        for campaign in campaigns:
            campaign_id = campaign['id']
            campaign_name = campaign.get('name', '')

            # Get metrics
            current_cpl = campaign.get('cpl_7d', 0)
            baseline_cpl = self.baselines.get(campaign_id, {}).get('cpl', target_cpl)
            conversion_rate = campaign.get('conversion_rate_7d', 0)
            baseline_conv_rate = self.baselines.get(campaign_id, {}).get('conv_rate', 5.0)

            # 1. CPL spike detection
            if current_cpl > baseline_cpl * 1.3:  # 30% increase
                opportunities.append({
                    'type': 'cpl_spike',
                    'severity': 'high',
                    'campaign_id': campaign_id,
                    'campaign_name': campaign_name,
                    'current_cpl': current_cpl,
                    'baseline_cpl': baseline_cpl,
                    'spike_pct': ((current_cpl - baseline_cpl) / baseline_cpl) * 100
                })

            # 2. Conversion rate drop
            if conversion_rate < baseline_conv_rate * 0.7:  # 30% drop
                opportunities.append({
                    'type': 'conversion_rate_drop',
                    'severity': 'high',
                    'campaign_id': campaign_id,
                    'campaign_name': campaign_name,
                    'current_rate': conversion_rate,
                    'baseline_rate': baseline_conv_rate,
                    'drop_pct': ((baseline_conv_rate - conversion_rate) / baseline_conv_rate) * 100
                })

            # 3. Bid optimization opportunity
            if current_cpl > target_cpl * 1.1:  # 10% above target
                bid_reduction_pct = min(20, (current_cpl - target_cpl) / target_cpl * 100)
                opportunities.append({
                    'type': 'bid_adjustment',
                    'severity': 'medium',
                    'campaign_id': campaign_id,
                    'campaign_name': campaign_name,
                    'current_cpl': current_cpl,
                    'target_cpl': target_cpl,
                    'recommended_bid_change_pct': -bid_reduction_pct
                })

            if not conversions_tracked:
                continue

            spend_90d = campaign.get('spend_90d', 0)
            cpl_90d = campaign.get('cpl_90d', current_cpl)
            impression_share = campaign.get('impression_share', 0)
            monthly_spend = campaign.get('monthly_spend', 0)

            # 4. Pause campaigns that consistently spend far above target CPL after 90 days
            if (cpl_90d > target_cpl * 2.0 and spend_90d > 500
                    and campaign.get('conversions', 0) > 0):
                opportunities.append({
                    'type': 'pause_campaign',
                    'severity': 'high',
                    'campaign_id': campaign_id,
                    'campaign_name': campaign_name,
                    'cpl_90d': cpl_90d,
                    'target_cpl': target_cpl,
                    'spend_90d': spend_90d,
                })

            # 5. Scale campaigns performing significantly below target CPL with room to grow
            if (cpl_90d > 0 and cpl_90d < target_cpl * 0.7
                    and impression_share < 70 and monthly_spend > 0):
                opportunities.append({
                    'type': 'scale_campaign',
                    'severity': 'medium',
                    'campaign_id': campaign_id,
                    'campaign_name': campaign_name,
                    'cpl_90d': cpl_90d,
                    'target_cpl': target_cpl,
                    'impression_share': impression_share,
                    'current_spend': monthly_spend,
                    'recommended_increase': monthly_spend * 0.3,
                })

        return opportunities

    def decide(self, opportunities: List[Dict[str, Any]]) -> List[AgentDecision]:
        """Make operational decisions."""
        decisions = []

        for opp in opportunities:
            opp_type = opp['type']

            if opp_type == 'cpl_spike':
                # Delegate investigation to Quality Score Agent
                # Also make immediate bid adjustment
                decision = AgentDecision(
                    agent_id=self.agent_id,
                    agent_type=self.agent_type,
                    decision_type='investigate_cpl_spike',
                    title=f"Investigate CPL spike in '{opp['campaign_name']}'",
                    description=f"CPL increased {opp['spike_pct']:.0f}% from ${opp['baseline_cpl']:.2f} to ${opp['current_cpl']:.2f}",
                    reasoning="Sudden CPL spike requires investigation to prevent wasted spend",
                    account_id=0,
                    customer_id='',
                    campaign_id=opp['campaign_id'],
                    action_data={
                        'delegate_to': 'QualityScoreAgent',
                        'investigation_type': 'cpl_spike'
                    },
                    risk_level=DecisionRiskLevel.LOW,
                    requires_approval=False,
                    confidence=0.95
                )
                decisions.append(decision)

            elif opp_type == 'bid_adjustment':
                decision = AgentDecision(
                    agent_id=self.agent_id,
                    agent_type=self.agent_type,
                    decision_type='adjust_bids',
                    title=f"Reduce bids by {abs(opp['recommended_bid_change_pct']):.0f}% in '{opp['campaign_name']}'",
                    description=f"Current CPL ${opp['current_cpl']:.2f} is above target ${opp['target_cpl']:.2f}",
                    reasoning="Bid reduction will lower CPL toward target",
                    account_id=0,
                    customer_id='',
                    campaign_id=opp['campaign_id'],
                    action_data={
                        'bid_change_pct': opp['recommended_bid_change_pct']
                    },
                    risk_level=DecisionRiskLevel.LOW,
                    requires_approval=False,
                    confidence=0.92,
                    expected_monthly_savings=(opp['current_cpl'] - opp['target_cpl']) * 100,
                    predicted_outcome={
                        'cpl_reduction': opp['current_cpl'] - opp['target_cpl']
                    }
                )
                decisions.append(decision)

            elif opp_type == 'pause_campaign':
                overspend = opp['spend_90d'] * (1 - opp['target_cpl'] / opp['cpl_90d'])
                decision = AgentDecision(
                    agent_id=self.agent_id,
                    agent_type=self.agent_type,
                    decision_type='pause_campaign',
                    title=f"Pause underperforming campaign '{opp['campaign_name']}'",
                    description=f"90-day CPL ${opp['cpl_90d']:.2f} is {opp['cpl_90d'] / opp['target_cpl']:.1f}x the target ${opp['target_cpl']:.2f}",
                    reasoning=f"Consistently high CPL after 90 days — estimated ${overspend:,.0f} wasted vs target",
                    account_id=0,
                    customer_id='',
                    campaign_id=opp['campaign_id'],
                    action_data={'campaign_id': opp['campaign_id'], 'reason': 'high_cpl_90d'},
                    risk_level=DecisionRiskLevel.HIGH,
                    requires_approval=True,
                    confidence=0.82,
                    expected_monthly_savings=overspend / 3,
                )
                decisions.append(decision)

            elif opp_type == 'scale_campaign':
                decision = AgentDecision(
                    agent_id=self.agent_id,
                    agent_type=self.agent_type,
                    decision_type='scale_campaign',
                    title=f"Scale '{opp['campaign_name']}' — strong CPL, low impression share",
                    description=f"CPL ${opp['cpl_90d']:.2f} is {(1 - opp['cpl_90d'] / opp['target_cpl']) * 100:.0f}% below target with only {opp['impression_share']:.0f}% impression share",
                    reasoning="More budget here will capture reachable demand at a proven CPL",
                    account_id=0,
                    customer_id='',
                    campaign_id=opp['campaign_id'],
                    action_data={
                        'current_budget': opp['current_spend'],
                        'new_budget': opp['current_spend'] + opp['recommended_increase'],
                        'increase_amount': opp['recommended_increase'],
                    },
                    risk_level=DecisionRiskLevel.MEDIUM,
                    requires_approval=True,
                    confidence=0.78,
                    expected_monthly_leads=int(opp['recommended_increase'] / max(opp['cpl_90d'], 1)),
                )
                decisions.append(decision)

        return decisions

    def _execute_impl(self, decision: AgentDecision, google_ads_client: Any) -> Dict[str, Any]:
        """Execute operational decisions."""
        if decision.decision_type == 'adjust_bids':
            return self._adjust_campaign_bids(decision, google_ads_client)
        elif decision.decision_type == 'investigate_cpl_spike':
            # Emit delegation event
            if self.event_bus:
                self.event_bus.emit('delegation_request', {
                    'target_agent': decision.action_data['delegate_to'],
                    'task': decision.action_data['investigation_type'],
                    'campaign_id': decision.campaign_id
                })
            return {'success': True, 'delegated': True}

        return {'success': False, 'error': f'Unknown decision type: {decision.decision_type}'}

    def _adjust_campaign_bids(self, decision: AgentDecision, client: Any) -> Dict[str, Any]:
        """Adjust campaign-level bids."""
        from .executor import GoogleAdsAgentExecutor

        if isinstance(client, GoogleAdsAgentExecutor):
            return client.adjust_campaign_bids(
                campaign_id=decision.campaign_id,
                bid_change_pct=decision.action_data['bid_change_pct']
            )

        # Fallback mock response
        return {
            'success': True,
            'campaign_id': decision.campaign_id,
            'bid_change_pct': decision.action_data['bid_change_pct'],
            'keywords_updated': 0
        }


class BudgetGuardianAgent(BaseAgent):
    """
    Budget Guardian - Stops wasted spend before it happens.

    Responsibilities:
    - Monitor budget pacing (are we on track?)
    - Prevent budget overruns
    - Detect and pause runaway campaigns
    - Reallocate from losers to winners (tactical)
    - Alert on unusual spend patterns
    - Integrates with Auto-Budget Service for intelligent adjustments
    - Considers capacity utilization and seasonality

    Operates on: Hourly cycles
    """

    def __init__(self, agent_id: str = "budget_guardian", **kwargs):
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

        # Initialize budget intelligence services
        self.auto_budget_service = None
        self.capacity_service = None
        self.competitive_service = None

    def init_services(self, db_connection):
        """
        Initialize budget intelligence services.

        Args:
            db_connection: Database connection
        """
        try:
            from app.services.auto_budget_service import AutoBudgetService
            from app.services.capacity_tracking_service import CapacityTrackingService
            from app.services.competitive_intelligence_service import CompetitiveIntelligenceService

            self.auto_budget_service = AutoBudgetService(db_connection)
            self.capacity_service = CapacityTrackingService(db_connection)
            self.competitive_service = CompetitiveIntelligenceService(db_connection)

        except ImportError as e:
            # Services not available yet
            pass

    def analyze(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Analyze budget pacing and spend patterns using intelligent forecasting.

        Enhanced with:
        - Historical performance baselines
        - Seasonality adjustments
        - Weather impact analysis
        - Anomaly detection
        - Auto-budget intelligence
        - Capacity utilization data
        - Competitive pressure analysis
        """
        opportunities = []

        # Get additional intelligence if services are available
        account_id = context.get('account_id')
        customer_id = context.get('customer_id')
        capacity_utilization = None

        if self.capacity_service and account_id:
            try:
                capacity_utilization = self.capacity_service.get_current_utilization(account_id)
            except:
                pass

        campaigns = context.get('campaigns', [])
        budget_groups = context.get('budget_groups', [])
        current_day_of_month = datetime.now().day
        days_in_month = 30  # Simplified
        elapsed_pct = current_day_of_month / days_in_month

        # Enhanced: Check for detected anomalies
        try:
            from app.services.budget_forecasting_service import detect_budget_anomalies
            for campaign in campaigns:
                anomalies = detect_budget_anomalies(campaign['id'], lookback_days=3)
                for anomaly in anomalies:
                    if anomaly['severity'] in ['high', 'critical']:
                        opportunities.append({
                            'type': 'performance_anomaly',
                            'severity': 'high',
                            'campaign_id': campaign['id'],
                            'campaign_name': campaign.get('name', ''),
                            'anomaly_type': anomaly['anomaly_type'],
                            'metric': anomaly['metric_name'],
                            'baseline': anomaly['baseline_value'],
                            'actual': anomaly['actual_value'],
                            'deviation_pct': anomaly['deviation_pct']
                        })
        except Exception as e:
            # Silently fail if forecasting service not available
            pass

        # Enhanced: Check weather impact for budget adjustments
        service_type = context.get('service_type', 'hvac_ac')
        zip_code = context.get('zip_code', None)

        if zip_code:
            try:
                from app.services.weather_service import fetch_current_weather, calculate_weather_impact_multiplier
                weather = fetch_current_weather(zip_code)
                impact_multiplier = calculate_weather_impact_multiplier(weather, service_type)

                # If extreme weather (2x+ demand), recommend budget increase
                if impact_multiplier >= 2.0:
                    opportunities.append({
                        'type': 'weather_driven_demand_spike',
                        'severity': 'high',
                        'weather_condition': weather.get('condition'),
                        'temp_high': weather.get('temp_high'),
                        'impact_multiplier': impact_multiplier,
                        'recommendation': f"Increase budget by {int((impact_multiplier - 1) * 100)}% due to extreme weather"
                    })
            except Exception as e:
                # Silently fail if weather service not available
                pass

        # 1. Analyze budget groups (if enabled)
        if budget_groups:
            for group in budget_groups:
                group_id = group['id']
                group_name = group['name']
                monthly_budget = group['monthly_budget_cents'] / 100
                spend_mtd = group.get('current_spend_cents', 0) / 100
                alert_threshold = group.get('alert_threshold_pct', 0.80)
                auto_pause = group.get('auto_pause_on_overspend', True)

                if monthly_budget == 0:
                    continue

                # Budget pacing check for group
                expected_spend = monthly_budget * elapsed_pct
                spend_pct = spend_mtd / monthly_budget

                # Check if approaching alert threshold
                if spend_pct >= alert_threshold and spend_pct < 1.0:
                    opportunities.append({
                        'type': 'budget_group_alert',
                        'severity': 'medium',
                        'group_id': group_id,
                        'group_name': group_name,
                        'budget': monthly_budget,
                        'spend_mtd': spend_mtd,
                        'spend_pct': spend_pct * 100,
                        'alert_threshold_pct': alert_threshold * 100,
                        'campaign_ids': group.get('campaign_ids', [])
                    })

                # Check if budget exceeded
                if spend_pct >= 1.0:
                    opportunities.append({
                        'type': 'budget_group_exceeded',
                        'severity': 'critical',
                        'group_id': group_id,
                        'group_name': group_name,
                        'budget': monthly_budget,
                        'spend_mtd': spend_mtd,
                        'overspend_amount': spend_mtd - monthly_budget,
                        'auto_pause': auto_pause,
                        'campaign_ids': group.get('campaign_ids', [])
                    })

                # Check if overpacing (spending too fast)
                elif spend_mtd > expected_spend * 1.5:  # Spending 50% faster than expected
                    days_remaining = days_in_month - current_day_of_month
                    avg_daily_spend = spend_mtd / current_day_of_month
                    projected_spend = spend_mtd + (avg_daily_spend * days_remaining)

                    if projected_spend > monthly_budget:
                        opportunities.append({
                            'type': 'budget_group_overrun_risk',
                            'severity': 'high',
                            'group_id': group_id,
                            'group_name': group_name,
                            'budget': monthly_budget,
                            'spend_mtd': spend_mtd,
                            'projected_spend': projected_spend,
                            'overrun_amount': projected_spend - monthly_budget,
                            'campaign_ids': group.get('campaign_ids', [])
                        })

        # 2. Analyze individual campaigns (for non-grouped campaigns or runaway detection)
        for campaign in campaigns:
            campaign_id = campaign['id']
            campaign_name = campaign.get('name', '')
            budget_group_id = campaign.get('budget_group_id')  # Check if in a group
            monthly_budget = campaign.get('monthly_budget', 0)
            spend_mtd = campaign.get('spend_mtd', 0)
            daily_spend_avg = campaign.get('daily_spend_avg_7d', 0)

            # Runaway campaign detection (applies to ALL campaigns, grouped or not)
            daily_spend_yesterday = campaign.get('daily_spend_yesterday', 0)
            if daily_spend_yesterday > daily_spend_avg * 3:  # 3x normal spend in one day
                opportunities.append({
                    'type': 'runaway_spend',
                    'severity': 'critical',
                    'campaign_id': campaign_id,
                    'campaign_name': campaign_name,
                    'budget_group_id': budget_group_id,
                    'daily_avg': daily_spend_avg,
                    'yesterday_spend': daily_spend_yesterday
                })

            # Individual campaign budget checks (only for non-grouped campaigns)
            if budget_group_id is None and monthly_budget > 0:
                expected_spend = monthly_budget * elapsed_pct

                if spend_mtd > expected_spend * 1.5:  # Spending 50% faster than expected
                    days_remaining = days_in_month - current_day_of_month
                    projected_spend = spend_mtd + (daily_spend_avg * days_remaining)

                    opportunities.append({
                        'type': 'budget_overrun_risk',
                        'severity': 'critical',
                        'campaign_id': campaign_id,
                        'campaign_name': campaign_name,
                        'budget': monthly_budget,
                        'spend_mtd': spend_mtd,
                        'projected_spend': projected_spend,
                        'overrun_amount': projected_spend - monthly_budget
                    })

        return opportunities

    def decide(self, opportunities: List[Dict[str, Any]]) -> List[AgentDecision]:
        """Make budget protection decisions."""
        decisions = []

        for opp in opportunities:
            opp_type = opp['type']

            if opp_type == 'budget_group_alert':
                # Send alert that budget group is approaching limit
                decision = AgentDecision(
                    agent_id=self.agent_id,
                    agent_type=self.agent_type,
                    decision_type='budget_group_alert',
                    title=f"⚠️ Budget group '{opp['group_name']}' at {opp['spend_pct']:.0f}% of budget",
                    description=f"Spent ${opp['spend_mtd']:,.0f} of ${opp['budget']:,.0f} budget this month",
                    reasoning=f"Budget group has reached {opp['alert_threshold_pct']:.0f}% alert threshold",
                    account_id=0,
                    customer_id='',
                    action_data={
                        'group_id': opp['group_id'],
                        'alert_type': 'threshold_reached',
                        'campaign_ids': opp['campaign_ids']
                    },
                    risk_level=DecisionRiskLevel.LOW,
                    requires_approval=False,
                    confidence=0.99
                )
                decisions.append(decision)

            elif opp_type == 'budget_group_exceeded':
                # Budget exceeded - pause campaigns if auto_pause is enabled
                if opp['auto_pause']:
                    decision = AgentDecision(
                        agent_id=self.agent_id,
                        agent_type=self.agent_type,
                        decision_type='pause_budget_group',
                        title=f"🛑 Pause budget group '{opp['group_name']}' - budget exceeded",
                        description=f"Spent ${opp['spend_mtd']:,.0f} of ${opp['budget']:,.0f} budget (${opp['overspend_amount']:,.0f} over)",
                        reasoning="Budget group has exceeded monthly budget. Auto-pause is enabled.",
                        account_id=0,
                        customer_id='',
                        action_data={
                            'group_id': opp['group_id'],
                            'campaign_ids': opp['campaign_ids']
                        },
                        risk_level=DecisionRiskLevel.LOW,
                        requires_approval=False,
                        confidence=0.99,
                        expected_monthly_savings=opp['overspend_amount'] * 1.5  # Prevent further overspend
                    )
                    decisions.append(decision)
                else:
                    # Just send alert if auto-pause is disabled
                    decision = AgentDecision(
                        agent_id=self.agent_id,
                        agent_type=self.agent_type,
                        decision_type='budget_group_alert',
                        title=f"🚨 Budget group '{opp['group_name']}' has exceeded budget",
                        description=f"Spent ${opp['spend_mtd']:,.0f} of ${opp['budget']:,.0f} budget (${opp['overspend_amount']:,.0f} over)",
                        reasoning="Budget group has exceeded monthly budget. Auto-pause is disabled - manual review required.",
                        account_id=0,
                        customer_id='',
                        action_data={
                            'group_id': opp['group_id'],
                            'alert_type': 'budget_exceeded',
                            'campaign_ids': opp['campaign_ids']
                        },
                        risk_level=DecisionRiskLevel.HIGH,
                        requires_approval=True,  # Require approval since auto-pause is off
                        confidence=0.99
                    )
                    decisions.append(decision)

            elif opp_type == 'budget_group_overrun_risk':
                # Reduce daily budgets for campaigns in the group to prevent overrun
                days_remaining = 30 - datetime.now().day
                remaining_budget = opp['budget'] - opp['spend_mtd']
                safe_daily_budget = remaining_budget / max(1, days_remaining)

                decision = AgentDecision(
                    agent_id=self.agent_id,
                    agent_type=self.agent_type,
                    decision_type='adjust_group_daily_budget',
                    title=f"Reduce daily budget for budget group '{opp['group_name']}'",
                    description=f"On track to overspend by ${opp['overrun_amount']:,.0f} this month",
                    reasoning=f"Spent ${opp['spend_mtd']:,.0f} of ${opp['budget']:,.0f} budget with {days_remaining} days remaining. Projected spend: ${opp['projected_spend']:,.0f}",
                    account_id=0,
                    customer_id='',
                    action_data={
                        'group_id': opp['group_id'],
                        'campaign_ids': opp['campaign_ids'],
                        'new_daily_budget': safe_daily_budget
                    },
                    risk_level=DecisionRiskLevel.LOW,
                    requires_approval=False,
                    confidence=0.98,
                    expected_monthly_savings=opp['overrun_amount']
                )
                decisions.append(decision)

            elif opp_type == 'budget_overrun_risk':
                # Reduce daily budget to prevent overrun (individual campaign)
                days_remaining = 30 - datetime.now().day
                remaining_budget = opp['budget'] - opp['spend_mtd']
                safe_daily_budget = remaining_budget / max(1, days_remaining)

                decision = AgentDecision(
                    agent_id=self.agent_id,
                    agent_type=self.agent_type,
                    decision_type='adjust_daily_budget',
                    title=f"Reduce daily budget for '{opp['campaign_name']}' to prevent overrun",
                    description=f"On track to overspend by ${opp['overrun_amount']:,.0f}",
                    reasoning=f"Spent ${opp['spend_mtd']:,.0f} of ${opp['budget']:,.0f} budget with {days_remaining} days remaining",
                    account_id=0,
                    customer_id='',
                    campaign_id=opp['campaign_id'],
                    action_data={
                        'new_daily_budget': safe_daily_budget
                    },
                    risk_level=DecisionRiskLevel.LOW,  # Preventing waste is low risk
                    requires_approval=False,
                    confidence=0.98,
                    expected_monthly_savings=opp['overrun_amount']
                )
                decisions.append(decision)

            elif opp_type == 'runaway_spend':
                # Pause campaign immediately
                decision = AgentDecision(
                    agent_id=self.agent_id,
                    agent_type=self.agent_type,
                    decision_type='emergency_pause',
                    title=f"EMERGENCY: Pause runaway campaign '{opp['campaign_name']}'",
                    description=f"Spent ${opp['yesterday_spend']:,.0f} yesterday vs ${opp['daily_avg']:,.0f} average",
                    reasoning="3x normal daily spend indicates a problem - pause for investigation",
                    account_id=0,
                    customer_id='',
                    campaign_id=opp['campaign_id'],
                    action_data={},
                    risk_level=DecisionRiskLevel.LOW,  # Pausing waste is low risk
                    requires_approval=False,
                    confidence=0.99
                )
                decisions.append(decision)

        return decisions

    def _execute_impl(self, decision: AgentDecision, google_ads_client: Any) -> Dict[str, Any]:
        """Execute budget protection decisions."""
        from .executor import GoogleAdsAgentExecutor

        if isinstance(google_ads_client, GoogleAdsAgentExecutor):
            if decision.decision_type == 'adjust_daily_budget':
                return google_ads_client.adjust_daily_budget(
                    campaign_id=decision.campaign_id,
                    new_daily_budget=decision.action_data['new_daily_budget']
                )
            elif decision.decision_type == 'emergency_pause':
                return google_ads_client.pause_campaign(campaign_id=decision.campaign_id)

        # Fallback mock response
        if decision.decision_type == 'adjust_daily_budget':
            return {
                'success': True,
                'campaign_id': decision.campaign_id,
                'new_daily_budget': decision.action_data['new_daily_budget']
            }
        elif decision.decision_type == 'emergency_pause':
            return {
                'success': True,
                'campaign_id': decision.campaign_id,
                'status': 'PAUSED',
                'reason': 'runaway_spend_detected'
            }

        return {'success': False, 'error': f'Unknown decision type: {decision.decision_type}'}


class QualityScoreAgent(BaseAgent):
    """
    Quality Score Doctor - Lower your CPCs automatically.

    Responsibilities:
    - Monitor Quality Scores across all keywords
    - Diagnose QS issues (ad relevance, landing page, CTR)
    - Delegate fixes to appropriate agents (Ad Copy, Landing Page)
    - Track QS improvements over time

    Operates on: Daily cycles
    """

    def __init__(self, agent_id: str = "quality_score_doctor", **kwargs):
        super().__init__(
            agent_id=agent_id,
            capabilities=[
                AgentCapability.QUALITY_SCORE_OPTIMIZATION,
                AgentCapability.PERFORMANCE_MONITORING,
                AgentCapability.AUTONOMOUS_EXECUTION,
            ],
            auto_execute_threshold=0.80,
            **kwargs
        )

    def analyze(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Analyze Quality Scores and identify improvement opportunities."""
        opportunities = []

        keywords = context.get('keywords', [])

        # Threshold: flag low-QS keywords spending ≥1% of monthly budget (floor $10).
        # This ensures the agent fires on small accounts ($1k/mo → $10 floor)
        # and large ones ($100k/mo → $1,000) proportionally.
        monthly_budget = context.get('total_budget', 0) or 0
        qs_spend_threshold = max(10.0, monthly_budget * 0.01)

        # Group keywords by Quality Score
        low_qs_keywords = [k for k in keywords if k.get('quality_score', 10) < 5]
        medium_qs_keywords = [k for k in keywords if 5 <= k.get('quality_score', 10) < 7]

        # Focus on low-QS keywords with scaled meaningful spend
        for keyword in low_qs_keywords:
            if keyword.get('monthly_spend', 0) > qs_spend_threshold:
                keyword_id = keyword.get('id') or keyword.get('keyword_id') or keyword.get('criterion_id', '')
                opportunities.append({
                    'type': 'low_quality_score',
                    'severity': 'high',
                    'keyword_id': keyword_id,
                    'keyword_text': keyword.get('text', ''),
                    'quality_score': keyword.get('quality_score', 0),
                    'monthly_spend': keyword.get('monthly_spend', 0),
                    'ad_relevance': keyword.get('ad_relevance', 'AVERAGE'),
                    'landing_page_experience': keyword.get('landing_page_exp', 'AVERAGE'),
                    'expected_ctr': keyword.get('expected_ctr', 'AVERAGE')
                })

        return opportunities

    def decide(self, opportunities: List[Dict[str, Any]]) -> List[AgentDecision]:
        """Make QS improvement decisions."""
        decisions = []

        for opp in opportunities:
            # Diagnose root cause and delegate
            root_cause = self._diagnose_qs_issue(opp)

            if root_cause == 'ad_relevance':
                decision = AgentDecision(
                    agent_id=self.agent_id,
                    agent_type=self.agent_type,
                    decision_type='improve_ad_relevance',
                    title=f"Improve ad relevance for keyword '{opp['keyword_text']}'",
                    description=f"QS {opp['quality_score']}/10, spending ${opp['monthly_spend']:.0f}/month",
                    reasoning="Low ad relevance is primary QS issue",
                    account_id=0,
                    customer_id='',
                    action_data={
                        'delegate_to': 'AdCopyAgent',
                        'keyword_id': opp['keyword_id'],
                        'keyword_text': opp['keyword_text']
                    },
                    risk_level=DecisionRiskLevel.LOW,
                    requires_approval=False,
                    confidence=0.85,
                    expected_monthly_savings=opp['monthly_spend'] * 0.2  # 20% CPC reduction from QS improvement
                )
                decisions.append(decision)

        return decisions

    def _diagnose_qs_issue(self, opp: Dict[str, Any]) -> str:
        """Diagnose the root cause of low Quality Score."""
        # Simplified diagnosis based on component scores
        if opp['ad_relevance'] == 'BELOW_AVERAGE':
            return 'ad_relevance'
        elif opp['landing_page_experience'] == 'BELOW_AVERAGE':
            return 'landing_page'
        elif opp['expected_ctr'] == 'BELOW_AVERAGE':
            return 'ctr'
        return 'ad_relevance'  # Default

    def _execute_impl(self, decision: AgentDecision, google_ads_client: Any) -> Dict[str, Any]:
        """Execute QS improvements (usually via delegation)."""
        if decision.decision_type == 'improve_ad_relevance':
            # Emit delegation event
            if self.event_bus:
                self.event_bus.emit('delegation_request', {
                    'target_agent': decision.action_data['delegate_to'],
                    'task': 'create_relevant_ad',
                    'keyword_id': decision.action_data['keyword_id'],
                    'keyword_text': decision.action_data['keyword_text']
                })
            return {'success': True, 'delegated': True}

        return {'success': False, 'error': f'Unknown decision type: {decision.decision_type}'}
