"""
Account Structure Agent - Strategic Layer
Analyzes and optimizes Google Ads account structure for maximum performance.

This agent evaluates:
- Campaign organization and naming conventions
- Ad group structure and theme coherence
- Keyword distribution and match type balance
- Budget allocation across campaigns
- Campaign type diversity (Search vs Performance Max)
- Account hierarchy and segmentation strategy
"""

from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
import anthropic
from flask import current_app

from .base import BaseAgent, AgentDecision
from .event_bus import AgentEventBus


class AccountStructureAgent(BaseAgent):
    """
    Analyzes account structure and recommends improvements.

    Capabilities:
    - Audit existing account structure
    - Identify structural inefficiencies
    - Recommend campaign consolidation or expansion
    - Suggest optimal ad group themes
    - Balance campaign type portfolio
    - Design greenfield account structure
    """

    def __init__(self, account_id: str, agent_config: Dict[str, Any] = None):
        super().__init__(
            agent_id="account_structure_agent",
            agent_type="strategic",
            account_id=account_id,
            agent_config=agent_config
        )
        self.name = "Account Structure Agent"
        self.description = "Analyzes and optimizes Google Ads account architecture"
        # Strategic decisions require higher approval threshold
        self.auto_execute_threshold = agent_config.get('auto_execute_threshold', 0.70) if agent_config else 0.70

    def analyze(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Analyze account structure and identify opportunities.

        Context should include:
        - campaigns: List of campaigns with performance data
        - ad_groups: List of ad groups with structure data
        - keywords: Keyword distribution data
        - account_age_days: How long the account has been active
        - business_type: Industry/business category
        - monthly_budget: Available monthly budget
        """
        opportunities = []

        campaigns = context.get('campaigns', [])
        ad_groups = context.get('ad_groups', [])
        keywords = context.get('keywords', [])
        account_age_days = context.get('account_age_days', 0)
        business_type = context.get('business_type', 'general')
        monthly_budget = context.get('monthly_budget', 0)

        # Analysis 1: Campaign Type Diversity
        campaign_type_analysis = self._analyze_campaign_types(campaigns)
        if campaign_type_analysis:
            opportunities.append(campaign_type_analysis)

        # Analysis 2: Campaign Structure Efficiency
        structure_efficiency = self._analyze_structure_efficiency(campaigns, ad_groups)
        if structure_efficiency:
            opportunities.append(structure_efficiency)

        # Analysis 3: Ad Group Theme Coherence
        theme_analysis = self._analyze_ad_group_themes(ad_groups, keywords)
        if theme_analysis:
            opportunities.append(theme_analysis)

        # Analysis 4: Budget Distribution
        budget_distribution = self._analyze_budget_distribution(campaigns, monthly_budget)
        if budget_distribution:
            opportunities.append(budget_distribution)

        # Analysis 5: Keyword Distribution
        keyword_distribution = self._analyze_keyword_distribution(ad_groups, keywords)
        if keyword_distribution:
            opportunities.append(keyword_distribution)

        # Analysis 6: New Account Setup (if empty or minimal account)
        if len(campaigns) == 0 or (len(campaigns) < 3 and account_age_days < 30):
            greenfield_structure = self._design_greenfield_structure(
                business_type=business_type,
                monthly_budget=monthly_budget,
                existing_campaigns=campaigns
            )
            if greenfield_structure:
                opportunities.append(greenfield_structure)

        self.log(f"Identified {len(opportunities)} account structure opportunities")
        return opportunities

    def _analyze_campaign_types(self, campaigns: List[Dict]) -> Optional[Dict]:
        """Analyze campaign type diversity and recommend additions."""
        if not campaigns:
            return None

        type_counts = {'SEARCH': 0, 'PERFORMANCE_MAX': 0, 'DISPLAY': 0, 'SHOPPING': 0}
        total_budget = 0
        type_budgets = {'SEARCH': 0, 'PERFORMANCE_MAX': 0, 'DISPLAY': 0, 'SHOPPING': 0}

        for campaign in campaigns:
            campaign_type = campaign.get('advertising_channel_type', 'SEARCH')
            type_counts[campaign_type] = type_counts.get(campaign_type, 0) + 1

            budget = campaign.get('daily_budget_cents', 0) * 30 / 100  # Monthly estimate
            total_budget += budget
            type_budgets[campaign_type] = type_budgets.get(campaign_type, 0) + budget

        issues = []
        recommendations = []

        # Check for missing campaign types
        if type_counts['SEARCH'] == 0 and type_counts['PERFORMANCE_MAX'] > 0:
            issues.append("Account only uses Performance Max campaigns")
            recommendations.append("Add Search campaigns for better keyword control and brand protection")

        if type_counts['PERFORMANCE_MAX'] == 0 and type_counts['SEARCH'] > 0:
            issues.append("Account only uses Search campaigns")
            recommendations.append("Add Performance Max campaigns to expand reach and leverage automation")

        # Check budget imbalance
        if total_budget > 0:
            search_pct = (type_budgets['SEARCH'] / total_budget) * 100
            pmax_pct = (type_budgets['PERFORMANCE_MAX'] / total_budget) * 100

            if search_pct > 80 and type_counts['PERFORMANCE_MAX'] > 0:
                issues.append(f"Search campaigns receive {search_pct:.0f}% of budget")
                recommendations.append("Allocate 30-40% budget to Performance Max for diversification")

            if pmax_pct > 80 and type_counts['SEARCH'] > 0:
                issues.append(f"Performance Max receives {pmax_pct:.0f}% of budget")
                recommendations.append("Maintain 40-50% budget in Search for strategic control")

        if not issues:
            return None

        return {
            'type': 'campaign_type_diversity',
            'priority': 'high',
            'issues': issues,
            'recommendations': recommendations,
            'data': {
                'type_counts': type_counts,
                'type_budgets': type_budgets,
                'total_budget': total_budget
            }
        }

    def _analyze_structure_efficiency(self, campaigns: List[Dict], ad_groups: List[Dict]) -> Optional[Dict]:
        """Analyze campaign and ad group structure efficiency."""
        if not campaigns:
            return None

        issues = []
        recommendations = []

        # Calculate ad groups per campaign
        campaign_ad_groups = {}
        for ag in ad_groups:
            cid = ag.get('campaign_id')
            if cid:
                campaign_ad_groups[cid] = campaign_ad_groups.get(cid, 0) + 1

        # Check for overcrowded campaigns
        for campaign in campaigns:
            cid = campaign.get('id')
            ag_count = campaign_ad_groups.get(cid, 0)

            if ag_count > 20:
                issues.append(f"Campaign '{campaign.get('name')}' has {ag_count} ad groups")
                recommendations.append(f"Consider splitting into multiple campaigns by theme or product category")

            if ag_count == 1 and len(campaigns) > 5:
                issues.append(f"Campaign '{campaign.get('name')}' has only 1 ad group")
                recommendations.append("Single ad group campaigns should be consolidated for easier management")

        # Check for too many campaigns
        if len(campaigns) > 15:
            issues.append(f"Account has {len(campaigns)} campaigns - may be over-segmented")
            recommendations.append("Consider consolidating similar campaigns to reduce management overhead")

        # Check for naming consistency
        campaign_names = [c.get('name', '') for c in campaigns]
        has_consistent_naming = self._check_naming_consistency(campaign_names)

        if not has_consistent_naming and len(campaigns) > 5:
            issues.append("Campaign naming lacks consistency")
            recommendations.append("Implement naming convention: [Type] - [Theme] - [Geo/Modifier]")

        if not issues:
            return None

        return {
            'type': 'structure_efficiency',
            'priority': 'medium',
            'issues': issues,
            'recommendations': recommendations,
            'data': {
                'campaign_count': len(campaigns),
                'ad_group_count': len(ad_groups),
                'avg_ad_groups_per_campaign': len(ad_groups) / len(campaigns) if campaigns else 0
            }
        }

    def _analyze_ad_group_themes(self, ad_groups: List[Dict], keywords: List[Dict]) -> Optional[Dict]:
        """Analyze ad group theme coherence and keyword relevance."""
        if not ad_groups or not keywords:
            return None

        issues = []
        recommendations = []

        # Group keywords by ad group
        ag_keywords = {}
        for kw in keywords:
            ag_id = kw.get('ad_group_id')
            if ag_id:
                if ag_id not in ag_keywords:
                    ag_keywords[ag_id] = []
                ag_keywords[ag_id].append(kw)

        # Check ad group sizes
        for ag in ad_groups:
            ag_id = ag.get('id')
            kw_count = len(ag_keywords.get(ag_id, []))

            if kw_count > 30:
                issues.append(f"Ad group '{ag.get('name')}' has {kw_count} keywords")
                recommendations.append("Split large ad groups into tighter themes (10-15 keywords each)")

            if kw_count < 5 and len(ad_groups) > 10:
                issues.append(f"Ad group '{ag.get('name')}' has only {kw_count} keywords")
                recommendations.append("Consolidate small ad groups or expand keyword lists")

        if not issues:
            return None

        return {
            'type': 'ad_group_themes',
            'priority': 'medium',
            'issues': issues,
            'recommendations': recommendations,
            'data': {
                'ad_group_count': len(ad_groups),
                'avg_keywords_per_ad_group': sum(len(kws) for kws in ag_keywords.values()) / len(ad_groups) if ad_groups else 0
            }
        }

    def _analyze_budget_distribution(self, campaigns: List[Dict], monthly_budget: float) -> Optional[Dict]:
        """Analyze budget allocation across campaigns."""
        if not campaigns or monthly_budget <= 0:
            return None

        issues = []
        recommendations = []

        # Calculate budget allocation
        total_allocated = sum(c.get('daily_budget_cents', 0) * 30 / 100 for c in campaigns)

        if total_allocated > monthly_budget * 1.1:  # 10% buffer
            issues.append(f"Allocated budget (${total_allocated:,.0f}) exceeds monthly limit (${monthly_budget:,.0f})")
            recommendations.append("Reduce campaign budgets or pause underperforming campaigns")

        if total_allocated < monthly_budget * 0.7:  # Using less than 70%
            issues.append(f"Only ${total_allocated:,.0f} of ${monthly_budget:,.0f} budget allocated")
            recommendations.append("Increase budgets for high-performing campaigns or launch new campaigns")

        # Check for extreme budget concentration
        if campaigns:
            max_budget = max(c.get('daily_budget_cents', 0) * 30 / 100 for c in campaigns)
            if total_allocated > 0 and (max_budget / total_allocated) > 0.5:
                issues.append("Over 50% of budget concentrated in single campaign")
                recommendations.append("Diversify budget across multiple campaigns to reduce risk")

        if not issues:
            return None

        return {
            'type': 'budget_distribution',
            'priority': 'high',
            'issues': issues,
            'recommendations': recommendations,
            'data': {
                'monthly_budget': monthly_budget,
                'total_allocated': total_allocated,
                'utilization_rate': (total_allocated / monthly_budget * 100) if monthly_budget > 0 else 0
            }
        }

    def _analyze_keyword_distribution(self, ad_groups: List[Dict], keywords: List[Dict]) -> Optional[Dict]:
        """Analyze keyword match type distribution."""
        if not keywords:
            return None

        issues = []
        recommendations = []

        # Count match types
        match_types = {'EXACT': 0, 'PHRASE': 0, 'BROAD': 0}
        for kw in keywords:
            match_type = kw.get('match_type', 'BROAD')
            match_types[match_type] = match_types.get(match_type, 0) + 1

        total = sum(match_types.values())
        if total == 0:
            return None

        exact_pct = (match_types['EXACT'] / total) * 100
        broad_pct = (match_types['BROAD'] / total) * 100

        if exact_pct > 80:
            issues.append(f"{exact_pct:.0f}% of keywords are Exact match")
            recommendations.append("Add Phrase and Broad match keywords to expand reach")

        if broad_pct > 60:
            issues.append(f"{broad_pct:.0f}% of keywords are Broad match")
            recommendations.append("Increase Exact and Phrase match keywords for better control and lower CPC")

        if not issues:
            return None

        return {
            'type': 'keyword_distribution',
            'priority': 'medium',
            'issues': issues,
            'recommendations': recommendations,
            'data': {
                'match_type_counts': match_types,
                'match_type_percentages': {
                    'EXACT': exact_pct,
                    'PHRASE': (match_types['PHRASE'] / total) * 100,
                    'BROAD': broad_pct
                }
            }
        }

    def _design_greenfield_structure(self, business_type: str, monthly_budget: float,
                                     existing_campaigns: List[Dict]) -> Optional[Dict]:
        """Design optimal account structure for new or minimal accounts."""

        if monthly_budget < 1000:
            return None  # Too small to recommend structural changes

        issues = ["Account needs foundational campaign structure"]
        recommendations = []

        # Determine optimal structure based on budget
        if monthly_budget >= 5000:
            # Full structure: Brand + Non-Brand Search + PMax
            recommendations.append("Create comprehensive account structure:")
            recommendations.append("1. Brand Protection Campaign (Search) - 15% of budget")
            recommendations.append("2. Non-Brand Search Campaigns (2-3 themes) - 45% of budget")
            recommendations.append("3. Performance Max Campaign - 40% of budget")

            structure_plan = {
                'campaigns': [
                    {'type': 'SEARCH', 'theme': 'Brand', 'budget_pct': 15},
                    {'type': 'SEARCH', 'theme': 'Core Services', 'budget_pct': 25},
                    {'type': 'SEARCH', 'theme': 'High Intent', 'budget_pct': 20},
                    {'type': 'PERFORMANCE_MAX', 'theme': 'All Products', 'budget_pct': 40}
                ]
            }
        elif monthly_budget >= 2000:
            # Mid-tier: Brand Search + PMax
            recommendations.append("Create balanced starter structure:")
            recommendations.append("1. Brand Protection Campaign (Search) - 25% of budget")
            recommendations.append("2. Core Keywords Campaign (Search) - 35% of budget")
            recommendations.append("3. Performance Max Campaign - 40% of budget")

            structure_plan = {
                'campaigns': [
                    {'type': 'SEARCH', 'theme': 'Brand', 'budget_pct': 25},
                    {'type': 'SEARCH', 'theme': 'Core Keywords', 'budget_pct': 35},
                    {'type': 'PERFORMANCE_MAX', 'theme': 'All Products', 'budget_pct': 40}
                ]
            }
        else:
            # Small budget: Focused approach
            recommendations.append("Create focused starter structure:")
            recommendations.append("1. High-Intent Keywords Campaign (Search) - 60% of budget")
            recommendations.append("2. Performance Max Campaign - 40% of budget")

            structure_plan = {
                'campaigns': [
                    {'type': 'SEARCH', 'theme': 'High Intent', 'budget_pct': 60},
                    {'type': 'PERFORMANCE_MAX', 'theme': 'All Products', 'budget_pct': 40}
                ]
            }

        return {
            'type': 'greenfield_structure',
            'priority': 'critical',
            'issues': issues,
            'recommendations': recommendations,
            'data': {
                'business_type': business_type,
                'monthly_budget': monthly_budget,
                'structure_plan': structure_plan,
                'existing_campaigns_count': len(existing_campaigns)
            }
        }

    def _check_naming_consistency(self, campaign_names: List[str]) -> bool:
        """Check if campaign names follow a consistent pattern."""
        if len(campaign_names) < 3:
            return True  # Too few to judge

        # Check for common patterns
        has_separators = sum(1 for name in campaign_names if '-' in name or '|' in name or '_' in name)
        separator_consistency = (has_separators / len(campaign_names)) > 0.7

        # Check for common prefixes
        if len(campaign_names) > 0:
            first_word_counts = {}
            for name in campaign_names:
                first_word = name.split()[0] if name else ''
                first_word_counts[first_word] = first_word_counts.get(first_word, 0) + 1

            # If most campaigns start with same word, likely consistent
            max_count = max(first_word_counts.values()) if first_word_counts else 0
            has_consistent_prefix = (max_count / len(campaign_names)) > 0.5

            return separator_consistency or has_consistent_prefix

        return False

    def decide(self, opportunities: List[Dict[str, Any]]) -> List[AgentDecision]:
        """
        Convert opportunities into actionable decisions.
        """
        decisions = []

        for opp in opportunities:
            opp_type = opp.get('type')
            priority = opp.get('priority', 'medium')

            # Map priority to risk level
            risk_map = {'critical': 'high', 'high': 'high', 'medium': 'medium', 'low': 'low'}
            risk_level = risk_map.get(priority, 'medium')

            if opp_type == 'greenfield_structure':
                decision = self._create_greenfield_decision(opp, risk_level)
                if decision:
                    decisions.append(decision)

            elif opp_type == 'campaign_type_diversity':
                decision = self._create_diversity_decision(opp, risk_level)
                if decision:
                    decisions.append(decision)

            elif opp_type == 'structure_efficiency':
                decision = self._create_efficiency_decision(opp, risk_level)
                if decision:
                    decisions.append(decision)

            elif opp_type == 'budget_distribution':
                decision = self._create_budget_decision(opp, risk_level)
                if decision:
                    decisions.append(decision)

            elif opp_type in ['ad_group_themes', 'keyword_distribution']:
                decision = self._create_optimization_decision(opp, risk_level)
                if decision:
                    decisions.append(decision)

        return decisions

    def _create_greenfield_decision(self, opp: Dict, risk_level: str) -> Optional[AgentDecision]:
        """Create decision for greenfield account structure."""
        structure_plan = opp['data'].get('structure_plan', {})
        monthly_budget = opp['data'].get('monthly_budget', 0)

        return AgentDecision(
            agent_id=self.agent_id,
            agent_type=self.agent_type,
            decision_type='setup_account_structure',
            title=f"Set Up Complete Account Structure",
            description=f"Create optimized campaign structure with ${monthly_budget:,.0f}/month budget",
            reasoning='\n'.join(opp['recommendations']),
            confidence=0.85,
            risk_level=risk_level,
            expected_monthly_savings=0,
            expected_monthly_leads=int(monthly_budget * 0.15),  # Estimate 15% conversion improvement
            action_data={
                'structure_plan': structure_plan,
                'monthly_budget': monthly_budget,
                'business_type': opp['data'].get('business_type')
            },
            account_id=self.account_id
        )

    def _create_diversity_decision(self, opp: Dict, risk_level: str) -> Optional[AgentDecision]:
        """Create decision for campaign type diversity."""
        type_counts = opp['data'].get('type_counts', {})

        # Determine what to add
        if type_counts.get('SEARCH', 0) == 0:
            decision_type = 'add_search_campaigns'
            title = "Add Search Campaigns for Better Control"
        elif type_counts.get('PERFORMANCE_MAX', 0) == 0:
            decision_type = 'add_pmax_campaigns'
            title = "Add Performance Max for Expanded Reach"
        else:
            decision_type = 'rebalance_campaign_types'
            title = "Rebalance Campaign Type Budget Mix"

        return AgentDecision(
            agent_id=self.agent_id,
            agent_type=self.agent_type,
            decision_type=decision_type,
            title=title,
            description=f"Improve campaign portfolio diversity",
            reasoning='\n'.join(opp['recommendations']),
            confidence=0.80,
            risk_level=risk_level,
            expected_monthly_savings=0,
            expected_monthly_leads=int(opp['data'].get('total_budget', 0) * 0.10),
            action_data={
                'current_mix': type_counts,
                'budget_data': opp['data']
            },
            account_id=self.account_id
        )

    def _create_efficiency_decision(self, opp: Dict, risk_level: str) -> Optional[AgentDecision]:
        """Create decision for structure efficiency improvements."""
        campaign_count = opp['data'].get('campaign_count', 0)

        return AgentDecision(
            agent_id=self.agent_id,
            agent_type=self.agent_type,
            decision_type='optimize_campaign_structure',
            title="Optimize Campaign Structure",
            description=f"Improve efficiency of {campaign_count} campaigns",
            reasoning='\n'.join(opp['recommendations']),
            confidence=0.75,
            risk_level='medium',
            expected_monthly_savings=int(campaign_count * 50),  # Estimate time savings
            expected_monthly_leads=0,
            action_data={
                'structure_data': opp['data'],
                'issues': opp['issues']
            },
            account_id=self.account_id
        )

    def _create_budget_decision(self, opp: Dict, risk_level: str) -> Optional[AgentDecision]:
        """Create decision for budget distribution optimization."""
        monthly_budget = opp['data'].get('monthly_budget', 0)
        utilization = opp['data'].get('utilization_rate', 0)

        return AgentDecision(
            agent_id=self.agent_id,
            agent_type=self.agent_type,
            decision_type='optimize_budget_distribution',
            title=f"Optimize Budget Allocation ({utilization:.0f}% utilized)",
            description=f"Improve distribution of ${monthly_budget:,.0f} monthly budget",
            reasoning='\n'.join(opp['recommendations']),
            confidence=0.80,
            risk_level=risk_level,
            expected_monthly_savings=int(monthly_budget * 0.05),  # 5% efficiency gain
            expected_monthly_leads=int(monthly_budget * 0.08),
            action_data={
                'budget_data': opp['data'],
                'issues': opp['issues']
            },
            account_id=self.account_id
        )

    def _create_optimization_decision(self, opp: Dict, risk_level: str) -> Optional[AgentDecision]:
        """Create decision for ad group/keyword optimizations."""
        opp_type = opp.get('type', 'optimization')

        return AgentDecision(
            agent_id=self.agent_id,
            agent_type=self.agent_type,
            decision_type=f'optimize_{opp_type}',
            title=f"Optimize {opp_type.replace('_', ' ').title()}",
            description=f"Improve account organization",
            reasoning='\n'.join(opp['recommendations']),
            confidence=0.70,
            risk_level='low',
            expected_monthly_savings=100,
            expected_monthly_leads=50,
            action_data={
                'optimization_data': opp['data'],
                'issues': opp['issues']
            },
            account_id=self.account_id
        )

    def _execute_impl(self, decision: AgentDecision, google_ads_client: Any) -> Dict[str, Any]:
        """
        Execute the approved decision.
        Account structure changes require manual implementation or wizard execution.

        Args:
            decision: The decision to execute
            google_ads_client: Google Ads client or executor instance

        Returns:
            Dict indicating that manual implementation is required
        """
        self.log(f"AccountStructureAgent decisions require manual implementation")
        return {
            'success': False,
            'message': 'Account structure changes require manual implementation or wizard execution',
            'requires_manual_action': True,
            'decision_type': decision.decision_type
        }

    def execute(self, decision: AgentDecision) -> Dict[str, Any]:
        """
        Execute the approved decision.
        This should be called by GoogleAdsAgentExecutor.
        """
        self.log(f"AccountStructureAgent decisions should be executed by GoogleAdsAgentExecutor")
        return {
            'success': False,
            'message': 'Account structure changes require manual implementation or wizard execution'
        }
