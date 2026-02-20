# app/agents/pmax_agents.py
"""
Performance Max Layer - Specialized agents for Performance Max campaigns.

These agents handle Performance Max-specific optimizations including
asset performance, audience signals, and asset group structure.
"""

from typing import Dict, List, Any
from .base import BaseAgent, AgentDecision, AgentCapability, DecisionRiskLevel


class AssetPerformanceAgent(BaseAgent):
    """
    Asset Performance Optimizer - Analyzes and optimizes Performance Max assets.

    Responsibilities:
    - Analyze headline, description, image, and video performance
    - Recommend removing low-performing assets
    - Suggest new asset variations to test
    - Optimize asset diversity and coverage
    - Ensure minimum asset requirements are met

    Operates on: Daily cycles
    """

    def __init__(self, agent_id: str = "asset_performance_optimizer", **kwargs):
        super().__init__(
            agent_id=agent_id,
            capabilities=[
                AgentCapability.AD_CREATION,
                AgentCapability.PERFORMANCE_MONITORING,
                AgentCapability.AUTONOMOUS_EXECUTION,
            ],
            auto_execute_threshold=0.90,
            **kwargs
        )

    def analyze(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Analyze Performance Max asset performance."""
        opportunities = []

        # Only analyze if there are Performance Max campaigns
        if not context.get('has_pmax_campaigns', False):
            return opportunities

        pmax_assets = context.get('pmax_assets', [])
        pmax_summary = context.get('pmax_summary', {})
        asset_groups = context.get('asset_groups', [])

        # 1. Check minimum asset requirements
        headlines_count = pmax_summary.get('headlines_count', 0)
        descriptions_count = pmax_summary.get('descriptions_count', 0)
        images_count = pmax_summary.get('images_count', 0)

        if headlines_count < 5:
            opportunities.append({
                'type': 'add_pmax_headlines',
                'severity': 'high',
                'current_count': headlines_count,
                'required_count': 5,
                'gap': 5 - headlines_count,
                'asset_type': 'HEADLINE'
            })

        if descriptions_count < 4:
            opportunities.append({
                'type': 'add_pmax_descriptions',
                'severity': 'high',
                'current_count': descriptions_count,
                'required_count': 4,
                'gap': 4 - descriptions_count,
                'asset_type': 'DESCRIPTION'
            })

        if images_count < 15:
            opportunities.append({
                'type': 'add_pmax_images',
                'severity': 'medium',
                'current_count': images_count,
                'required_count': 15,
                'gap': 15 - images_count,
                'asset_type': 'IMAGE'
            })

        # 2. Recommend asset variety for better performance
        if headlines_count >= 5 and headlines_count < 10:
            opportunities.append({
                'type': 'improve_headline_variety',
                'severity': 'low',
                'current_count': headlines_count,
                'recommended_count': 10,
                'message': 'Add more headline variations for Google AI to test'
            })

        # 3. Check for duplicate assets
        headline_texts = [a.get('text', '') for a in pmax_assets if a.get('field_type') == 'HEADLINE']
        if len(headline_texts) != len(set(headline_texts)):
            opportunities.append({
                'type': 'remove_duplicate_assets',
                'severity': 'low',
                'asset_type': 'HEADLINE',
                'message': 'Duplicate headlines reduce testing variety'
            })

        # 4. Asset group coverage
        if len(asset_groups) > 0:
            # Check if all asset groups have sufficient assets
            for asset_group in asset_groups:
                ag_id = asset_group['id']
                ag_assets = [a for a in pmax_assets if a.get('asset_group_id') == ag_id]

                if len(ag_assets) < 10:  # Minimum 10 assets per asset group
                    opportunities.append({
                        'type': 'add_assets_to_asset_group',
                        'severity': 'medium',
                        'asset_group_id': ag_id,
                        'asset_group_name': asset_group.get('name', ''),
                        'current_asset_count': len(ag_assets),
                        'message': f'Asset group "{asset_group.get("name", "")}" needs more assets'
                    })

        return opportunities

    def decide(self, opportunities: List[Dict[str, Any]]) -> List[AgentDecision]:
        """Make decisions about asset optimizations."""
        decisions = []

        for opp in opportunities:
            opp_type = opp.get('type')
            severity = opp.get('severity', 'medium')

            if opp_type == 'add_pmax_headlines':
                decisions.append(AgentDecision(
                    agent_id=self.agent_id,
                    agent_type=self.agent_type,
                    decision_type='add_pmax_assets',
                    title=f"Add {opp['gap']} more headlines to Performance Max",
                    description=f"You have {opp['current_count']} headlines, need {opp['required_count']} minimum. Add {opp['gap']} more for better performance.",
                    reasoning="Performance Max needs 5+ headlines minimum. More headlines give Google's AI more combinations to test and find what works best.",
                    account_id=self.account_id or 0,
                    customer_id='',
                    risk_level=DecisionRiskLevel.HIGH,
                    requires_approval=False,  # Can be AI-generated automatically
                    confidence=0.95,
                    action_data={
                        'asset_type': 'HEADLINE',
                        'current_count': opp['current_count'],
                        'gap': opp['gap']
                    },
                ))

            elif opp_type == 'add_pmax_descriptions':
                decisions.append(AgentDecision(
                    agent_id=self.agent_id,
                    agent_type=self.agent_type,
                    decision_type='add_pmax_assets',
                    title=f"Add {opp['gap']} more descriptions to Performance Max",
                    description=f"You have {opp['current_count']} descriptions, need {opp['required_count']} minimum. Add {opp['gap']} more.",
                    reasoning="Performance Max needs 4+ descriptions minimum. Diverse descriptions improve ad relevance across different contexts.",
                    account_id=self.account_id or 0,
                    customer_id='',
                    risk_level=DecisionRiskLevel.HIGH,
                    requires_approval=False,  # Can be AI-generated automatically
                    confidence=0.95,
                    action_data={
                        'asset_type': 'DESCRIPTION',
                        'current_count': opp['current_count'],
                        'gap': opp['gap']
                    },
                ))

            elif opp_type == 'add_pmax_images':
                decisions.append(AgentDecision(
                    agent_id=self.agent_id,
                    agent_type=self.agent_type,
                    decision_type='add_pmax_assets',
                    title=f"Add {opp['gap']} more images to Performance Max",
                    description=f"You have {opp['current_count']} images, need {opp['required_count']} for best performance. Add {opp['gap']} more images (mix of landscape and square).",
                    reasoning="Performance Max recommends 15+ images (both landscape and square). More images = more visual variety = better performance across Display, YouTube, Discovery.",
                    account_id=self.account_id or 0,
                    customer_id='',
                    risk_level=DecisionRiskLevel.HIGH,
                    requires_approval=True,
                    confidence=0.90,
                    action_data={
                        'asset_type': 'IMAGE',
                        'current_count': opp['current_count'],
                        'gap': opp['gap']
                    },
                ))

            elif opp_type == 'improve_headline_variety':
                decisions.append(AgentDecision(
                    agent_id=self.agent_id,
                    agent_type=self.agent_type,
                    decision_type='add_pmax_assets',  # Changed from 'improve_asset_variety' to use existing handler
                    title="Add more headline variations to Performance Max for better testing",  # Clarified campaign type
                    description=f"You have {opp['current_count']} Performance Max headlines. Adding {opp['recommended_count'] - opp['current_count']} more gives Google's AI more combinations to test.",
                    reasoning="More asset variety = more testing combinations. With 10+ headlines, Google can find optimal combinations for different audiences and contexts.",
                    account_id=self.account_id or 0,
                    customer_id='',
                    risk_level=DecisionRiskLevel.LOW,
                    requires_approval=False,  # Can be AI-generated automatically
                    confidence=0.85,
                    expected_improvement_pct=5.0,  # 5% CTR improvement expected
                    action_data={
                        'asset_type': 'HEADLINE',
                        'current_count': opp['current_count'],
                        'recommended_count': opp['recommended_count'],
                        'gap': opp['recommended_count'] - opp['current_count']  # Add gap for consistency
                    },
                ))

        return decisions

    def _execute_impl(self, decision: AgentDecision, google_ads_client: Any) -> Dict[str, Any]:
        """
        Asset creation and management require manual implementation.
        This agent creates recommendations but does not auto-execute.
        """
        # Performance Max asset optimizations cannot be fully automated
        # They require manual asset creation (images, headlines, descriptions)
        return {
            'success': True,
            'note': 'Performance Max asset optimization requires manual asset creation',
            'decision_type': decision.decision_type,
            'requires_manual_work': True
        }


class AudienceSignalAgent(BaseAgent):
    """
    Audience Signal Optimizer - Optimizes Performance Max audience signals.

    Responsibilities:
    - Analyze audience segment performance
    - Recommend adding/removing audience signals
    - Optimize audience signal strength
    - Suggest audience expansion opportunities
    - Monitor signal saturation and reach

    Operates on: Weekly cycles
    """

    def __init__(self, agent_id: str = "audience_signal_optimizer", **kwargs):
        super().__init__(
            agent_id=agent_id,
            capabilities=[
                AgentCapability.STRATEGIC_PLANNING,
                AgentCapability.PERFORMANCE_MONITORING,
            ],
            auto_execute_threshold=0.88,
            **kwargs
        )

    def analyze(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Analyze Performance Max audience signal performance."""
        opportunities = []

        # Only analyze if there are Performance Max campaigns
        if not context.get('has_pmax_campaigns', False):
            return opportunities

        campaigns = context.get('campaigns', [])
        pmax_campaigns = [c for c in campaigns if c.get('type') == 'PERFORMANCE_MAX']

        # Check if campaigns have audience signals configured
        # Note: This would require additional API calls to fetch audience signals
        # For now, provide general recommendations

        if len(pmax_campaigns) > 0:
            # General audience signal recommendations
            opportunities.append({
                'type': 'configure_audience_signals',
                'severity': 'medium',
                'message': 'Add audience signals to guide Performance Max targeting',
                'recommendation': 'Upload customer lists, website visitors, and lookalike audiences'
            })

        return opportunities

    def decide(self, opportunities: List[Dict[str, Any]]) -> List[AgentDecision]:
        """Make decisions about audience signal optimizations."""
        decisions = []

        for opp in opportunities:
            if opp.get('type') == 'configure_audience_signals':
                decisions.append(AgentDecision(
                    agent_id=self.agent_id,
                    agent_type=self.agent_type,
                    decision_type='add_audience_signals',
                    title="Add audience signals to Performance Max campaigns",
                    description="Performance Max works best with audience signals. Add customer lists, website visitors, and custom segments to guide Google's AI.",
                    reasoning="Audience signals help Performance Max understand who your ideal customers are. While the campaign can run without them, signals improve targeting accuracy and reduce learning time.",
                    account_id=self.account_id or 0,
                    customer_id='',
                    risk_level=DecisionRiskLevel.HIGH,
                    requires_approval=True,
                    confidence=0.85,
                    expected_improvement_pct=10.0,  # 10% efficiency improvement
                    action_data={
                        'recommended_signals': [
                            'Customer list (past purchasers)',
                            'Website visitors (last 30 days)',
                            'In-market audiences',
                            'Custom intent audiences'
                        ]
                    },
                ))

        return decisions

    def _execute_impl(self, decision: AgentDecision, google_ads_client: Any) -> Dict[str, Any]:
        """
        Audience signal changes require manual implementation.
        This agent creates recommendations but does not auto-execute.
        """
        # Audience signal optimizations require manual configuration in Google Ads
        # Customer lists, audiences, etc. need to be uploaded/configured manually
        return {
            'success': True,
            'note': 'Audience signal optimization requires manual configuration in Google Ads',
            'decision_type': decision.decision_type,
            'requires_manual_work': True
        }


class PMaxCampaignStructureAgent(BaseAgent):
    """
    Performance Max Campaign Structure Optimizer.

    Responsibilities:
    - Analyze asset group organization
    - Recommend splitting by product/service category
    - Optimize budget allocation across asset groups
    - Monitor asset group performance
    - Suggest consolidation or expansion

    Operates on: Weekly cycles
    """

    def __init__(self, agent_id: str = "pmax_campaign_structure", **kwargs):
        super().__init__(
            agent_id=agent_id,
            capabilities=[
                AgentCapability.STRATEGIC_PLANNING,
                AgentCapability.PERFORMANCE_MONITORING,
            ],
            auto_execute_threshold=0.85,
            **kwargs
        )

    def analyze(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Analyze Performance Max campaign structure."""
        opportunities = []

        # Only analyze if there are Performance Max campaigns
        if not context.get('has_pmax_campaigns', False):
            return opportunities

        campaigns = context.get('campaigns', [])
        asset_groups = context.get('asset_groups', [])
        pmax_campaigns = [c for c in campaigns if c.get('type') == 'PERFORMANCE_MAX']

        # 1. Check if asset groups exist
        if len(pmax_campaigns) > 0 and len(asset_groups) == 0:
            opportunities.append({
                'type': 'create_asset_groups',
                'severity': 'high',
                'pmax_campaign_count': len(pmax_campaigns),
                'message': 'Performance Max campaigns need asset groups'
            })

        # 2. Check asset group count (best practice: 3-5 per campaign)
        if len(asset_groups) > 0:
            avg_asset_groups_per_campaign = len(asset_groups) / max(len(pmax_campaigns), 1)

            if avg_asset_groups_per_campaign < 2:
                opportunities.append({
                    'type': 'add_more_asset_groups',
                    'severity': 'medium',
                    'current_count': len(asset_groups),
                    'recommended_count': len(pmax_campaigns) * 3,
                    'message': 'Create 3-5 asset groups per campaign for better targeting'
                })

        # 3. Budget allocation analysis
        for campaign in pmax_campaigns:
            monthly_spend = campaign.get('monthly_spend', 0)
            conversions = campaign.get('conversions', 0)

            if monthly_spend > 1000 and conversions < 10:
                opportunities.append({
                    'type': 'optimize_pmax_budget',
                    'severity': 'high',
                    'campaign_id': campaign['id'],
                    'campaign_name': campaign.get('name', ''),
                    'monthly_spend': monthly_spend,
                    'conversions': conversions,
                    'message': 'Performance Max campaign spending without sufficient conversions'
                })

        return opportunities

    def decide(self, opportunities: List[Dict[str, Any]]) -> List[AgentDecision]:
        """Make decisions about Performance Max structure."""
        decisions = []

        for opp in opportunities:
            opp_type = opp.get('type')

            if opp_type == 'create_asset_groups':
                decisions.append(AgentDecision(
                    agent_id=self.agent_id,
                    agent_type=self.agent_type,
                    decision_type='create_asset_groups',
                    title="Create asset groups for Performance Max campaigns",
                    description=f"Your {opp['pmax_campaign_count']} Performance Max campaign(s) need asset groups. Create 3-5 asset groups per campaign, organized by product/service category.",
                    reasoning="Asset groups are required for Performance Max campaigns. Each asset group should target a specific product, service, or offering with relevant assets.",
                    account_id=self.account_id or 0,
                    customer_id='',
                    risk_level=DecisionRiskLevel.HIGH,
                    requires_approval=False,  # AI auto-generates asset groups with themes and assets
                    confidence=1.0,
                    action_data={
                        'pmax_campaign_count': opp['pmax_campaign_count'],
                        'recommended_asset_groups': 3
                    },
                ))

            elif opp_type == 'add_more_asset_groups':
                decisions.append(AgentDecision(
                    agent_id=self.agent_id,
                    agent_type=self.agent_type,
                    decision_type='add_asset_groups',
                    title="Add more asset groups to improve targeting",
                    description=f"You have {opp['current_count']} asset groups. Best practice is 3-5 per campaign. Add {opp['recommended_count'] - opp['current_count']} more asset groups.",
                    reasoning="Multiple asset groups allow you to target different product/service categories with specific messaging. This improves relevance and performance.",
                    account_id=self.account_id or 0,
                    customer_id='',
                    risk_level=DecisionRiskLevel.HIGH,
                    requires_approval=False,  # AI auto-generates asset groups with themes and assets
                    confidence=0.85,
                    expected_improvement_pct=15.0,
                    action_data={
                        'current_count': opp['current_count'],
                        'recommended_count': opp['recommended_count']
                    },
                ))

            elif opp_type == 'optimize_pmax_budget':
                decisions.append(AgentDecision(
                    agent_id=self.agent_id,
                    agent_type=self.agent_type,
                    decision_type='adjust_pmax_budget',
                    title=f"Optimize budget for '{opp['campaign_name']}'",
                    description=f"Campaign spending ${opp['monthly_spend']}/month with only {opp['conversions']} conversions. Consider reducing budget or improving conversion tracking.",
                    reasoning="Performance Max campaigns need sufficient conversion data to optimize. Low conversion counts indicate either tracking issues or targeting problems.",
                    account_id=self.account_id or 0,
                    customer_id='',
                    campaign_id=opp['campaign_id'],
                    risk_level=DecisionRiskLevel.HIGH,
                    requires_approval=True,
                    confidence=0.75,
                    expected_monthly_savings=opp['monthly_spend'] * 0.3,  # Suggest 30% reduction
                    action_data={
                        'current_budget': opp['monthly_spend'],
                        'conversions': opp['conversions'],
                        'recommended_action': 'reduce_budget_or_improve_tracking'
                    },
                ))

        return decisions

    def _execute_impl(self, decision: AgentDecision, google_ads_client: Any) -> Dict[str, Any]:
        """
        Performance Max structure changes require manual implementation.
        This agent creates recommendations but does not auto-execute.
        """
        # Campaign structure changes (asset groups, budget allocation) need manual setup
        return {
            'success': True,
            'note': 'Performance Max structure optimization requires manual configuration',
            'decision_type': decision.decision_type,
            'requires_manual_work': True
        }
