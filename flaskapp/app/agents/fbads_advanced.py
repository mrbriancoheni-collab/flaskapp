# app/agents/fbads_advanced.py
"""
Facebook Ads Advanced Agents - Specialized optimization agents.

These agents handle advanced optimization tasks:
- Spend optimization and budget pacing
- Dayparting (time-of-day optimization)
- Geographic targeting optimization
- Retargeting and audience management
- Pixel/Conversions API health monitoring
- Lead form optimization
"""

from typing import Dict, List, Any
from datetime import datetime, timedelta
from .base import BaseAgent, AgentDecision, AgentCapability, DecisionRiskLevel

import logging
logger = logging.getLogger(__name__)


class FBSpendOptimizerAgent(BaseAgent):
    """
    Facebook Spend Optimizer - Proactive budget management for maximum ROI.

    Responsibilities:
    - Daily budget adjustments based on performance trends
    - Automatic budget scaling for winners
    - Budget reduction for underperformers
    - Day-of-week spend optimization
    - End-of-month pacing adjustments
    - ROAS-based budget allocation
    - Spend velocity monitoring

    Operates on: Every 4 hours
    """

    def __init__(self, agent_id: str = "fb_spend_optimizer", **kwargs):
        super().__init__(
            agent_id=agent_id,
            capabilities=[
                AgentCapability.BUDGET_MANAGEMENT,
                AgentCapability.PERFORMANCE_MONITORING,
                AgentCapability.AUTONOMOUS_EXECUTION,
            ],
            auto_execute_threshold=0.88,
            **kwargs
        )

    def analyze(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Analyze spend patterns and optimization opportunities."""
        opportunities = []

        campaigns = context.get('campaigns', [])
        ad_sets = context.get('ad_sets', [])
        target_cpa = context.get('target_cpa', 50)
        target_roas = context.get('target_roas', 3.0)
        monthly_budget = context.get('monthly_budget', 0)
        spend_mtd = context.get('spend_mtd', 0)

        current_day = datetime.now().day
        days_in_month = 30
        days_remaining = days_in_month - current_day

        # 1. ROAS-based budget allocation
        if campaigns:
            high_roas_campaigns = [c for c in campaigns if c.get('roas_7d', 0) > target_roas * 1.2]
            low_roas_campaigns = [c for c in campaigns if 0 < c.get('roas_7d', 0) < target_roas * 0.7]

            for campaign in high_roas_campaigns:
                current_budget = campaign.get('daily_budget', 0)
                roas = campaign.get('roas_7d', 0)
                spend_velocity = campaign.get('spend_velocity', 1.0)  # % of budget being spent

                # High performer not fully spending budget = opportunity
                if spend_velocity < 0.9 and current_budget > 0:
                    opportunities.append({
                        'type': 'increase_budget_high_roas',
                        'severity': 'medium',
                        'campaign_id': campaign['id'],
                        'campaign_name': campaign.get('name'),
                        'current_budget': current_budget,
                        'roas': roas,
                        'spend_velocity': spend_velocity,
                        'recommended_increase': min(current_budget * 0.5, 100),  # Max $100 increase
                        'reason': f'High ROAS ({roas:.2f}x) campaign has room to scale'
                    })

            for campaign in low_roas_campaigns:
                current_budget = campaign.get('daily_budget', 0)
                roas = campaign.get('roas_7d', 0)
                spend_7d = campaign.get('spend_7d', 0)

                if spend_7d > 200:  # Has significant spend
                    opportunities.append({
                        'type': 'reduce_budget_low_roas',
                        'severity': 'high',
                        'campaign_id': campaign['id'],
                        'campaign_name': campaign.get('name'),
                        'current_budget': current_budget,
                        'roas': roas,
                        'spend_7d': spend_7d,
                        'recommended_reduction': current_budget * 0.3,
                        'reason': f'Low ROAS ({roas:.2f}x) - reduce to limit waste'
                    })

        # 2. CPA-based ad set budget optimization
        for ad_set in ad_sets:
            cpa = ad_set.get('cpa_7d', 0)
            conversions = ad_set.get('conversions_7d', 0)
            daily_budget = ad_set.get('daily_budget', 0)
            spend_velocity = ad_set.get('spend_velocity', 1.0)

            # High performer: low CPA with data
            if cpa > 0 and cpa < target_cpa * 0.7 and conversions >= 5:
                opportunities.append({
                    'type': 'scale_low_cpa_adset',
                    'severity': 'medium',
                    'ad_set_id': ad_set.get('id'),
                    'ad_set_name': ad_set.get('name'),
                    'current_budget': daily_budget,
                    'cpa': cpa,
                    'conversions': conversions,
                    'recommended_increase': daily_budget * 0.3,
                    'reason': f'CPA ${cpa:.2f} is 30%+ below target - scale up'
                })

            # Underperformer: high CPA with data
            elif cpa > target_cpa * 1.5 and conversions >= 3:
                opportunities.append({
                    'type': 'reduce_high_cpa_adset',
                    'severity': 'high',
                    'ad_set_id': ad_set.get('id'),
                    'ad_set_name': ad_set.get('name'),
                    'current_budget': daily_budget,
                    'cpa': cpa,
                    'conversions': conversions,
                    'recommended_reduction': daily_budget * 0.4,
                    'reason': f'CPA ${cpa:.2f} is 50%+ above target - reduce spend'
                })

        # 3. Monthly pacing optimization
        if monthly_budget > 0 and days_remaining > 0:
            expected_spend = monthly_budget * (current_day / days_in_month)
            pace_variance = (spend_mtd - expected_spend) / expected_spend if expected_spend > 0 else 0

            if pace_variance > 0.2:  # Overpacing by 20%+
                daily_adjustment = (spend_mtd - expected_spend) / days_remaining
                opportunities.append({
                    'type': 'monthly_pace_adjustment',
                    'severity': 'high',
                    'direction': 'reduce',
                    'monthly_budget': monthly_budget,
                    'spend_mtd': spend_mtd,
                    'expected_spend': expected_spend,
                    'pace_variance_pct': pace_variance * 100,
                    'daily_adjustment': -daily_adjustment,
                    'reason': f'Overpacing by {pace_variance*100:.0f}% - reduce daily budgets'
                })
            elif pace_variance < -0.2:  # Underpacing by 20%+
                daily_adjustment = (expected_spend - spend_mtd) / days_remaining
                opportunities.append({
                    'type': 'monthly_pace_adjustment',
                    'severity': 'medium',
                    'direction': 'increase',
                    'monthly_budget': monthly_budget,
                    'spend_mtd': spend_mtd,
                    'expected_spend': expected_spend,
                    'pace_variance_pct': pace_variance * 100,
                    'daily_adjustment': daily_adjustment,
                    'reason': f'Underpacing by {abs(pace_variance)*100:.0f}% - increase daily budgets'
                })

        # 4. Spend velocity alerts
        for campaign in campaigns:
            spend_velocity = campaign.get('spend_velocity', 1.0)
            daily_budget = campaign.get('daily_budget', 0)

            if spend_velocity < 0.5 and daily_budget > 50:
                opportunities.append({
                    'type': 'low_spend_velocity',
                    'severity': 'medium',
                    'campaign_id': campaign['id'],
                    'campaign_name': campaign.get('name'),
                    'daily_budget': daily_budget,
                    'spend_velocity': spend_velocity,
                    'reason': 'Campaign spending less than 50% of daily budget - check bid/audience'
                })

        return opportunities

    def decide(self, opportunities: List[Dict[str, Any]]) -> List[AgentDecision]:
        """Make spend optimization decisions."""
        decisions = []

        for opp in opportunities:
            opp_type = opp['type']

            if opp_type == 'increase_budget_high_roas':
                new_budget = opp['current_budget'] + opp['recommended_increase']
                decision = AgentDecision(
                    agent_id=self.agent_id,
                    agent_type=self.agent_type,
                    decision_type='increase_campaign_budget',
                    title=f"Increase budget for '{opp['campaign_name']}' (ROAS {opp['roas']:.2f}x)",
                    description=f"${opp['current_budget']:.0f} → ${new_budget:.0f}/day (+${opp['recommended_increase']:.0f})",
                    reasoning=opp['reason'],
                    account_id=self.account_id or 0,
                    customer_id='',
                    campaign_id=opp['campaign_id'],
                    action_data={
                        'current_budget': opp['current_budget'],
                        'new_budget': new_budget,
                        'increase_amount': opp['recommended_increase']
                    },
                    risk_level=DecisionRiskLevel.LOW,
                    requires_approval=False,
                    confidence=0.88,
                    expected_monthly_leads=int(opp['recommended_increase'] * 30 / 50)
                )
                decisions.append(decision)

            elif opp_type == 'reduce_budget_low_roas':
                new_budget = opp['current_budget'] - opp['recommended_reduction']
                decision = AgentDecision(
                    agent_id=self.agent_id,
                    agent_type=self.agent_type,
                    decision_type='reduce_campaign_budget',
                    title=f"Reduce budget for '{opp['campaign_name']}' (ROAS {opp['roas']:.2f}x)",
                    description=f"${opp['current_budget']:.0f} → ${new_budget:.0f}/day (-${opp['recommended_reduction']:.0f})",
                    reasoning=opp['reason'],
                    account_id=self.account_id or 0,
                    customer_id='',
                    campaign_id=opp['campaign_id'],
                    action_data={
                        'current_budget': opp['current_budget'],
                        'new_budget': new_budget,
                        'reduction_amount': opp['recommended_reduction']
                    },
                    risk_level=DecisionRiskLevel.LOW,
                    requires_approval=False,
                    confidence=0.90,
                    expected_monthly_savings=opp['recommended_reduction'] * 30
                )
                decisions.append(decision)

            elif opp_type == 'scale_low_cpa_adset':
                new_budget = opp['current_budget'] + opp['recommended_increase']
                decision = AgentDecision(
                    agent_id=self.agent_id,
                    agent_type=self.agent_type,
                    decision_type='increase_adset_budget',
                    title=f"Scale '{opp['ad_set_name']}' (CPA ${opp['cpa']:.2f})",
                    description=f"${opp['current_budget']:.0f} → ${new_budget:.0f}/day",
                    reasoning=opp['reason'],
                    account_id=self.account_id or 0,
                    customer_id='',
                    ad_group_id=opp['ad_set_id'],
                    action_data={
                        'current_budget': opp['current_budget'],
                        'new_budget': new_budget
                    },
                    risk_level=DecisionRiskLevel.LOW,
                    requires_approval=False,
                    confidence=0.85,
                    expected_monthly_leads=int(opp['recommended_increase'] * 30 / opp['cpa'])
                )
                decisions.append(decision)

            elif opp_type == 'reduce_high_cpa_adset':
                new_budget = opp['current_budget'] - opp['recommended_reduction']
                decision = AgentDecision(
                    agent_id=self.agent_id,
                    agent_type=self.agent_type,
                    decision_type='reduce_adset_budget',
                    title=f"Reduce '{opp['ad_set_name']}' budget (CPA ${opp['cpa']:.2f})",
                    description=f"${opp['current_budget']:.0f} → ${new_budget:.0f}/day",
                    reasoning=opp['reason'],
                    account_id=self.account_id or 0,
                    customer_id='',
                    ad_group_id=opp['ad_set_id'],
                    action_data={
                        'current_budget': opp['current_budget'],
                        'new_budget': new_budget
                    },
                    risk_level=DecisionRiskLevel.LOW,
                    requires_approval=False,
                    confidence=0.90,
                    expected_monthly_savings=opp['recommended_reduction'] * 30
                )
                decisions.append(decision)

            elif opp_type == 'monthly_pace_adjustment':
                decision = AgentDecision(
                    agent_id=self.agent_id,
                    agent_type=self.agent_type,
                    decision_type='adjust_monthly_pacing',
                    title=f"{'Reduce' if opp['direction'] == 'reduce' else 'Increase'} daily budgets for monthly pacing",
                    description=f"Spent ${opp['spend_mtd']:,.0f} of ${opp['monthly_budget']:,.0f} ({opp['pace_variance_pct']:+.0f}% vs expected)",
                    reasoning=opp['reason'],
                    account_id=self.account_id or 0,
                    customer_id='',
                    action_data={
                        'direction': opp['direction'],
                        'daily_adjustment': opp['daily_adjustment']
                    },
                    risk_level=DecisionRiskLevel.HIGH,
                    requires_approval=True,
                    confidence=0.85,
                    expected_monthly_savings=abs(opp['daily_adjustment']) * 10 if opp['direction'] == 'reduce' else 0
                )
                decisions.append(decision)

        return decisions

    def _execute_impl(self, decision: AgentDecision, fb_ads_client: Any) -> Dict[str, Any]:
        """Execute spend optimization changes."""
        return {
            'success': True,
            'decision_type': decision.decision_type,
            'note': 'Budget changes require implementation in Ads Manager',
            'requires_manual_work': True,
            'action_data': decision.action_data
        }


class FBDaypartingAgent(BaseAgent):
    """
    Facebook Dayparting Agent - Time-of-day and day-of-week optimization.

    Responsibilities:
    - Analyze performance by hour of day
    - Analyze performance by day of week
    - Recommend ad scheduling adjustments
    - Identify peak conversion times
    - Optimize for business hours vs all-day

    Operates on: Weekly cycles
    """

    def __init__(self, agent_id: str = "fb_dayparting", **kwargs):
        super().__init__(
            agent_id=agent_id,
            capabilities=[
                AgentCapability.PERFORMANCE_MONITORING,
                AgentCapability.BUDGET_MANAGEMENT,
            ],
            auto_execute_threshold=0.80,
            **kwargs
        )

    def analyze(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Analyze time-based performance patterns."""
        opportunities = []

        ad_sets = context.get('ad_sets', [])
        target_cpa = context.get('target_cpa', 50)

        for ad_set in ad_sets:
            ad_set_id = ad_set.get('id')
            ad_set_name = ad_set.get('name', '')

            # Hour of day analysis
            hourly_data = ad_set.get('hourly_breakdown', {})
            if hourly_data:
                best_hours = []
                worst_hours = []

                for hour, metrics in hourly_data.items():
                    cpa = metrics.get('cpa', 0)
                    conversions = metrics.get('conversions', 0)
                    spend = metrics.get('spend', 0)

                    if cpa > 0 and conversions >= 2:
                        if cpa < target_cpa * 0.8:
                            best_hours.append({'hour': hour, 'cpa': cpa, 'conversions': conversions})
                        elif cpa > target_cpa * 1.5 and spend > 20:
                            worst_hours.append({'hour': hour, 'cpa': cpa, 'spend': spend})

                if len(worst_hours) >= 3 and len(best_hours) >= 3:
                    opportunities.append({
                        'type': 'dayparting_opportunity',
                        'severity': 'medium',
                        'ad_set_id': ad_set_id,
                        'ad_set_name': ad_set_name,
                        'best_hours': best_hours,
                        'worst_hours': worst_hours,
                        'recommendation': 'Consider ad scheduling to focus on peak hours'
                    })

            # Day of week analysis
            daily_data = ad_set.get('daily_breakdown', {})
            if daily_data:
                best_days = []
                worst_days = []
                day_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

                for day, metrics in daily_data.items():
                    cpa = metrics.get('cpa', 0)
                    conversions = metrics.get('conversions', 0)
                    spend = metrics.get('spend', 0)

                    if cpa > 0 and conversions >= 2:
                        if cpa < target_cpa * 0.7:
                            best_days.append({'day': day, 'cpa': cpa, 'conversions': conversions})
                        elif cpa > target_cpa * 2 and spend > 30:
                            worst_days.append({'day': day, 'cpa': cpa, 'spend': spend})

                if worst_days:
                    opportunities.append({
                        'type': 'day_of_week_optimization',
                        'severity': 'medium',
                        'ad_set_id': ad_set_id,
                        'ad_set_name': ad_set_name,
                        'best_days': best_days,
                        'worst_days': worst_days,
                        'recommendation': 'Reduce or pause ads on underperforming days'
                    })

        return opportunities

    def decide(self, opportunities: List[Dict[str, Any]]) -> List[AgentDecision]:
        """Make dayparting decisions."""
        decisions = []

        for opp in opportunities:
            opp_type = opp['type']

            if opp_type == 'dayparting_opportunity':
                best_hours_str = ', '.join([f"{h['hour']}:00" for h in opp['best_hours'][:5]])
                worst_hours_str = ', '.join([f"{h['hour']}:00" for h in opp['worst_hours'][:5]])

                decision = AgentDecision(
                    agent_id=self.agent_id,
                    agent_type=self.agent_type,
                    decision_type='enable_ad_scheduling',
                    title=f"Enable ad scheduling for '{opp['ad_set_name']}'",
                    description=f"Best hours: {best_hours_str} | Worst: {worst_hours_str}",
                    reasoning=opp['recommendation'],
                    account_id=self.account_id or 0,
                    customer_id='',
                    ad_group_id=opp['ad_set_id'],
                    action_data={
                        'best_hours': opp['best_hours'],
                        'worst_hours': opp['worst_hours']
                    },
                    risk_level=DecisionRiskLevel.HIGH,
                    requires_approval=True,
                    confidence=0.80,
                    expected_improvement_pct=15.0
                )
                decisions.append(decision)

            elif opp_type == 'day_of_week_optimization':
                worst_days_str = ', '.join([d['day'] for d in opp['worst_days']])

                decision = AgentDecision(
                    agent_id=self.agent_id,
                    agent_type=self.agent_type,
                    decision_type='adjust_day_scheduling',
                    title=f"Reduce spend on {worst_days_str} for '{opp['ad_set_name']}'",
                    description=f"These days have 2x+ target CPA",
                    reasoning=opp['recommendation'],
                    account_id=self.account_id or 0,
                    customer_id='',
                    ad_group_id=opp['ad_set_id'],
                    action_data={
                        'best_days': opp['best_days'],
                        'worst_days': opp['worst_days']
                    },
                    risk_level=DecisionRiskLevel.LOW,
                    requires_approval=False,
                    confidence=0.85,
                    expected_monthly_savings=sum(d['spend'] for d in opp['worst_days']) * 4
                )
                decisions.append(decision)

        return decisions

    def _execute_impl(self, decision: AgentDecision, fb_ads_client: Any) -> Dict[str, Any]:
        """Execute dayparting changes."""
        return {
            'success': True,
            'decision_type': decision.decision_type,
            'note': 'Ad scheduling requires manual setup in Ads Manager',
            'requires_manual_work': True
        }


class FBGeoOptimizerAgent(BaseAgent):
    """
    Facebook Geo Optimizer - Location targeting optimization.

    Responsibilities:
    - Analyze performance by geographic region
    - Recommend location exclusions
    - Identify high-performing areas for expansion
    - Optimize radius targeting
    - Country/state/city level optimization

    Operates on: Weekly cycles
    """

    def __init__(self, agent_id: str = "fb_geo_optimizer", **kwargs):
        super().__init__(
            agent_id=agent_id,
            capabilities=[
                AgentCapability.PERFORMANCE_MONITORING,
                AgentCapability.AUTONOMOUS_EXECUTION,
            ],
            auto_execute_threshold=0.88,
            **kwargs
        )

    def analyze(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Analyze geographic performance patterns."""
        opportunities = []

        ad_sets = context.get('ad_sets', [])
        target_cpa = context.get('target_cpa', 50)

        for ad_set in ad_sets:
            ad_set_id = ad_set.get('id')
            ad_set_name = ad_set.get('name', '')
            geo_breakdown = ad_set.get('geo_breakdown', {})

            if not geo_breakdown:
                continue

            poor_regions = []
            strong_regions = []

            for region, metrics in geo_breakdown.items():
                cpa = metrics.get('cpa', 0)
                conversions = metrics.get('conversions', 0)
                spend = metrics.get('spend', 0)

                if cpa > 0 and conversions >= 2:
                    if cpa > target_cpa * 2 and spend > 50:
                        poor_regions.append({
                            'region': region,
                            'cpa': cpa,
                            'spend': spend,
                            'conversions': conversions
                        })
                    elif cpa < target_cpa * 0.7:
                        strong_regions.append({
                            'region': region,
                            'cpa': cpa,
                            'spend': spend,
                            'conversions': conversions
                        })

            if poor_regions:
                opportunities.append({
                    'type': 'exclude_poor_regions',
                    'severity': 'medium',
                    'ad_set_id': ad_set_id,
                    'ad_set_name': ad_set_name,
                    'poor_regions': poor_regions,
                    'total_wasted': sum(r['spend'] for r in poor_regions),
                    'recommendation': 'Exclude regions with 2x+ CPA'
                })

            if strong_regions and len(strong_regions) >= 2:
                opportunities.append({
                    'type': 'focus_on_strong_regions',
                    'severity': 'low',
                    'ad_set_id': ad_set_id,
                    'ad_set_name': ad_set_name,
                    'strong_regions': strong_regions,
                    'recommendation': 'Consider creating geo-focused ad sets for top regions'
                })

        return opportunities

    def decide(self, opportunities: List[Dict[str, Any]]) -> List[AgentDecision]:
        """Make geo optimization decisions."""
        decisions = []

        for opp in opportunities:
            opp_type = opp['type']

            if opp_type == 'exclude_poor_regions':
                regions_str = ', '.join([r['region'] for r in opp['poor_regions'][:5]])

                decision = AgentDecision(
                    agent_id=self.agent_id,
                    agent_type=self.agent_type,
                    decision_type='exclude_regions',
                    title=f"Exclude underperforming regions from '{opp['ad_set_name']}'",
                    description=f"Regions: {regions_str} (${opp['total_wasted']:.0f} wasted)",
                    reasoning=opp['recommendation'],
                    account_id=self.account_id or 0,
                    customer_id='',
                    ad_group_id=opp['ad_set_id'],
                    action_data={
                        'regions_to_exclude': [r['region'] for r in opp['poor_regions']]
                    },
                    risk_level=DecisionRiskLevel.LOW,
                    requires_approval=False,
                    confidence=0.90,
                    expected_monthly_savings=opp['total_wasted'] * 4
                )
                decisions.append(decision)

            elif opp_type == 'focus_on_strong_regions':
                regions_str = ', '.join([r['region'] for r in opp['strong_regions'][:3]])

                decision = AgentDecision(
                    agent_id=self.agent_id,
                    agent_type=self.agent_type,
                    decision_type='create_geo_campaign',
                    title=f"Create geo-focused ad set for top regions",
                    description=f"Strong performers: {regions_str}",
                    reasoning=opp['recommendation'],
                    account_id=self.account_id or 0,
                    customer_id='',
                    ad_group_id=opp['ad_set_id'],
                    action_data={
                        'strong_regions': opp['strong_regions']
                    },
                    risk_level=DecisionRiskLevel.HIGH,
                    requires_approval=True,
                    confidence=0.80,
                    expected_improvement_pct=20.0
                )
                decisions.append(decision)

        return decisions

    def _execute_impl(self, decision: AgentDecision, fb_ads_client: Any) -> Dict[str, Any]:
        """Execute geo targeting changes."""
        return {
            'success': True,
            'decision_type': decision.decision_type,
            'note': 'Geo targeting changes require implementation in Ads Manager',
            'requires_manual_work': True
        }


class FBRetargetingAgent(BaseAgent):
    """
    Facebook Retargeting Agent - Manage retargeting audiences and campaigns.

    Responsibilities:
    - Monitor website visitor audience health
    - Recommend retargeting audience creation
    - Optimize retargeting frequency
    - Manage exclusion audiences (converters)
    - Cart abandonment optimization
    - Engagement retargeting (video viewers, page engagers)

    Operates on: Daily cycles
    """

    def __init__(self, agent_id: str = "fb_retargeting", **kwargs):
        super().__init__(
            agent_id=agent_id,
            capabilities=[
                AgentCapability.PERFORMANCE_MONITORING,
                AgentCapability.STRATEGIC_PLANNING,
            ],
            auto_execute_threshold=0.85,
            **kwargs
        )

    def analyze(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Analyze retargeting opportunities."""
        opportunities = []

        audiences = context.get('audiences', [])
        campaigns = context.get('campaigns', [])
        pixel_data = context.get('pixel_data', {})

        # 1. Check if website custom audience exists
        website_audiences = [a for a in audiences if a.get('source') == 'website']
        if not website_audiences and pixel_data.get('has_pixel'):
            opportunities.append({
                'type': 'create_website_audience',
                'severity': 'high',
                'pixel_events': pixel_data.get('events', []),
                'recommendation': 'Create website visitor custom audience for retargeting'
            })

        # 2. Check retargeting campaign performance
        retargeting_campaigns = [c for c in campaigns if c.get('is_retargeting')]
        for campaign in retargeting_campaigns:
            frequency = campaign.get('frequency', 0)
            cpa = campaign.get('cpa_7d', 0)

            # High frequency = ad fatigue
            if frequency > 8:
                opportunities.append({
                    'type': 'retargeting_fatigue',
                    'severity': 'high',
                    'campaign_id': campaign['id'],
                    'campaign_name': campaign.get('name'),
                    'frequency': frequency,
                    'recommendation': 'Frequency too high - refresh creative or expand audience'
                })

        # 3. Check for converter exclusion
        converter_audience = next((a for a in audiences if 'converter' in a.get('name', '').lower() or 'purchase' in a.get('name', '').lower()), None)
        if not converter_audience:
            opportunities.append({
                'type': 'create_converter_exclusion',
                'severity': 'medium',
                'recommendation': 'Create converter audience to exclude from prospecting campaigns'
            })

        # 4. Engagement retargeting opportunities
        has_video_ads = any(c.get('has_video_ads') for c in campaigns)
        video_viewer_audience = next((a for a in audiences if 'video' in a.get('name', '').lower()), None)

        if has_video_ads and not video_viewer_audience:
            opportunities.append({
                'type': 'create_video_viewer_audience',
                'severity': 'low',
                'recommendation': 'Create video viewer audience (75%+ watched) for warm retargeting'
            })

        # 5. Lookalike from retargeting winners
        for audience in website_audiences:
            if audience.get('performance', {}).get('roas', 0) > 5:
                has_lookalike = any(a.get('source_audience_id') == audience.get('id') for a in audiences if a.get('type') == 'lookalike')
                if not has_lookalike:
                    opportunities.append({
                        'type': 'create_lookalike_from_retargeting',
                        'severity': 'medium',
                        'source_audience': audience.get('name'),
                        'source_roas': audience.get('performance', {}).get('roas'),
                        'recommendation': 'High-performing retargeting audience - create lookalike'
                    })

        return opportunities

    def decide(self, opportunities: List[Dict[str, Any]]) -> List[AgentDecision]:
        """Make retargeting decisions."""
        decisions = []

        for opp in opportunities:
            opp_type = opp['type']

            if opp_type == 'create_website_audience':
                decision = AgentDecision(
                    agent_id=self.agent_id,
                    agent_type=self.agent_type,
                    decision_type='create_website_audience',
                    title="Create website visitor retargeting audience",
                    description="Pixel is active but no website custom audience exists",
                    reasoning=opp['recommendation'],
                    account_id=self.account_id or 0,
                    customer_id='',
                    action_data={
                        'audience_types': [
                            {'name': 'All Website Visitors - 30 days', 'window': 30},
                            {'name': 'All Website Visitors - 7 days', 'window': 7},
                            {'name': 'High Intent - 14 days', 'window': 14, 'pages': 'pricing, contact, checkout'}
                        ]
                    },
                    risk_level=DecisionRiskLevel.LOW,
                    requires_approval=False,
                    confidence=0.95,
                    expected_improvement_pct=30.0
                )
                decisions.append(decision)

            elif opp_type == 'retargeting_fatigue':
                decision = AgentDecision(
                    agent_id=self.agent_id,
                    agent_type=self.agent_type,
                    decision_type='fix_retargeting_fatigue',
                    title=f"Fix ad fatigue in '{opp['campaign_name']}'",
                    description=f"Frequency at {opp['frequency']:.1f}x - users seeing ads too often",
                    reasoning=opp['recommendation'],
                    account_id=self.account_id or 0,
                    customer_id='',
                    campaign_id=opp['campaign_id'],
                    action_data={
                        'options': [
                            'Add new creative variations',
                            'Set frequency cap (3-5 per week)',
                            'Expand audience window (7d → 30d)',
                            'Pause for 1 week to reset frequency'
                        ]
                    },
                    risk_level=DecisionRiskLevel.LOW,
                    requires_approval=False,
                    confidence=0.90
                )
                decisions.append(decision)

            elif opp_type == 'create_converter_exclusion':
                decision = AgentDecision(
                    agent_id=self.agent_id,
                    agent_type=self.agent_type,
                    decision_type='create_exclusion_audience',
                    title="Create converter exclusion audience",
                    description="Stop showing ads to people who already converted",
                    reasoning=opp['recommendation'],
                    account_id=self.account_id or 0,
                    customer_id='',
                    action_data={
                        'steps': [
                            '1. Create Custom Audience from Purchase/Lead events',
                            '2. Set window to 180 days',
                            '3. Add as exclusion to all prospecting campaigns',
                            '4. Save as "Converters - Exclude" for easy reference'
                        ]
                    },
                    risk_level=DecisionRiskLevel.LOW,
                    requires_approval=False,
                    confidence=0.95,
                    expected_monthly_savings=100  # Stop wasting money on existing customers
                )
                decisions.append(decision)

        return decisions

    def _execute_impl(self, decision: AgentDecision, fb_ads_client: Any) -> Dict[str, Any]:
        """Execute retargeting changes."""
        return {
            'success': True,
            'decision_type': decision.decision_type,
            'note': 'Audience changes require implementation in Ads Manager',
            'requires_manual_work': True,
            'steps': decision.action_data.get('steps', decision.action_data.get('options', []))
        }


class FBPixelHealthAgent(BaseAgent):
    """
    Facebook Pixel Health Agent - Monitor tracking health.

    Responsibilities:
    - Monitor pixel event firing
    - Check Conversions API status
    - Detect tracking issues
    - Verify event match quality
    - Alert on conversion drops

    Operates on: Daily cycles
    """

    def __init__(self, agent_id: str = "fb_pixel_health", **kwargs):
        super().__init__(
            agent_id=agent_id,
            capabilities=[
                AgentCapability.PERFORMANCE_MONITORING,
            ],
            auto_execute_threshold=0.95,
            **kwargs
        )

    def analyze(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Analyze pixel and tracking health."""
        opportunities = []

        pixel_data = context.get('pixel_data', {})

        if not pixel_data.get('has_pixel'):
            opportunities.append({
                'type': 'no_pixel',
                'severity': 'critical',
                'recommendation': 'Install Facebook Pixel on your website for conversion tracking'
            })
            return opportunities

        # 1. Check event match quality
        emq_score = pixel_data.get('event_match_quality', 0)
        if emq_score < 6:  # Facebook recommends 6+ out of 10
            opportunities.append({
                'type': 'low_event_match_quality',
                'severity': 'high',
                'emq_score': emq_score,
                'recommendation': 'Improve Event Match Quality by passing more customer data (email, phone)'
            })

        # 2. Check Conversions API status
        has_capi = pixel_data.get('has_conversions_api', False)
        if not has_capi:
            opportunities.append({
                'type': 'no_conversions_api',
                'severity': 'high',
                'recommendation': 'Set up Conversions API for better tracking accuracy (iOS 14+ impact)'
            })

        # 3. Check for conversion drop
        conversions_7d = pixel_data.get('conversions_7d', 0)
        conversions_prior_7d = pixel_data.get('conversions_prior_7d', 0)

        if conversions_prior_7d > 0:
            change_pct = (conversions_7d - conversions_prior_7d) / conversions_prior_7d
            if change_pct < -0.3:  # 30%+ drop
                opportunities.append({
                    'type': 'conversion_drop',
                    'severity': 'critical',
                    'conversions_7d': conversions_7d,
                    'conversions_prior_7d': conversions_prior_7d,
                    'drop_pct': abs(change_pct) * 100,
                    'recommendation': 'Investigate potential tracking issue - conversions dropped significantly'
                })

        # 4. Check event deduplication
        browser_events = pixel_data.get('browser_events_7d', 0)
        server_events = pixel_data.get('server_events_7d', 0)
        dedupe_rate = pixel_data.get('deduplication_rate', 0)

        if has_capi and dedupe_rate < 80 and browser_events > 0 and server_events > 0:
            opportunities.append({
                'type': 'poor_deduplication',
                'severity': 'medium',
                'dedupe_rate': dedupe_rate,
                'recommendation': 'Improve event deduplication by using consistent event_id parameter'
            })

        # 5. Check for missing standard events
        standard_events = ['PageView', 'ViewContent', 'AddToCart', 'InitiateCheckout', 'Purchase', 'Lead']
        active_events = pixel_data.get('active_events', [])
        missing_events = [e for e in standard_events if e not in active_events]

        if 'Lead' not in active_events and 'Purchase' not in active_events:
            opportunities.append({
                'type': 'missing_conversion_events',
                'severity': 'high',
                'missing_events': missing_events,
                'recommendation': 'Set up Lead or Purchase event for conversion optimization'
            })

        return opportunities

    def decide(self, opportunities: List[Dict[str, Any]]) -> List[AgentDecision]:
        """Make pixel health decisions."""
        decisions = []

        for opp in opportunities:
            opp_type = opp['type']

            if opp_type == 'no_pixel':
                decision = AgentDecision(
                    agent_id=self.agent_id,
                    agent_type=self.agent_type,
                    decision_type='install_pixel',
                    title="Install Facebook Pixel",
                    description="No pixel detected - required for conversion tracking",
                    reasoning=opp['recommendation'],
                    account_id=self.account_id or 0,
                    customer_id='',
                    action_data={
                        'steps': [
                            '1. Go to Events Manager > Data Sources',
                            '2. Click "Add" and select "Web"',
                            '3. Enter website URL and create pixel',
                            '4. Install pixel code on all pages',
                            '5. Set up standard events (PageView, Lead/Purchase)'
                        ]
                    },
                    risk_level=DecisionRiskLevel.HIGH,
                    requires_approval=True,
                    confidence=0.99
                )
                decisions.append(decision)

            elif opp_type == 'no_conversions_api':
                decision = AgentDecision(
                    agent_id=self.agent_id,
                    agent_type=self.agent_type,
                    decision_type='setup_capi',
                    title="Set up Conversions API",
                    description="Improve tracking accuracy with server-side events",
                    reasoning=opp['recommendation'],
                    account_id=self.account_id or 0,
                    customer_id='',
                    action_data={
                        'options': [
                            'Partner integration (Shopify, WordPress, etc.)',
                            'Google Tag Manager server container',
                            'Direct API implementation',
                            'Facebook Gateway (easiest option)'
                        ],
                        'benefits': [
                            'Better attribution accuracy',
                            'Resilient to browser blocking',
                            'Required for iOS 14+ optimization',
                            'Improves ad delivery optimization'
                        ]
                    },
                    risk_level=DecisionRiskLevel.HIGH,
                    requires_approval=True,
                    confidence=0.95,
                    expected_improvement_pct=20.0
                )
                decisions.append(decision)

            elif opp_type == 'conversion_drop':
                decision = AgentDecision(
                    agent_id=self.agent_id,
                    agent_type=self.agent_type,
                    decision_type='investigate_conversion_drop',
                    title=f"Investigate {opp['drop_pct']:.0f}% conversion drop",
                    description=f"Conversions: {opp['conversions_prior_7d']} → {opp['conversions_7d']} (last 7 days)",
                    reasoning=opp['recommendation'],
                    account_id=self.account_id or 0,
                    customer_id='',
                    action_data={
                        'checks': [
                            'Verify pixel is still installed correctly',
                            'Check for website changes/errors',
                            'Review Events Manager for errors',
                            'Test conversion events with Pixel Helper',
                            'Check if landing pages are working'
                        ]
                    },
                    risk_level=DecisionRiskLevel.HIGH,
                    requires_approval=False,
                    confidence=0.95
                )
                decisions.append(decision)

            elif opp_type == 'low_event_match_quality':
                decision = AgentDecision(
                    agent_id=self.agent_id,
                    agent_type=self.agent_type,
                    decision_type='improve_emq',
                    title=f"Improve Event Match Quality (currently {opp['emq_score']}/10)",
                    description="Better matching = better ad delivery optimization",
                    reasoning=opp['recommendation'],
                    account_id=self.account_id or 0,
                    customer_id='',
                    action_data={
                        'improvements': [
                            'Pass hashed email with events',
                            'Pass hashed phone number',
                            'Include external_id parameter',
                            'Pass first/last name when available',
                            'Include city, state, zip code'
                        ]
                    },
                    risk_level=DecisionRiskLevel.LOW,
                    requires_approval=False,
                    confidence=0.90,
                    expected_improvement_pct=15.0
                )
                decisions.append(decision)

        return decisions

    def _execute_impl(self, decision: AgentDecision, fb_ads_client: Any) -> Dict[str, Any]:
        """Execute pixel health fixes."""
        return {
            'success': True,
            'decision_type': decision.decision_type,
            'note': 'Pixel changes require developer implementation',
            'requires_manual_work': True,
            'steps': decision.action_data.get('steps', decision.action_data.get('checks', decision.action_data.get('improvements', [])))
        }
