# app/agents/tactical.py
"""
Tactical Layer - Specific optimizations and execution agents.

These agents perform focused, specialized tasks like managing keywords,
writing ad copy, and analyzing search terms.
"""

from typing import Dict, List, Any
from .base import BaseAgent, AgentDecision, AgentCapability, DecisionRiskLevel


class KeywordOptimizerAgent(BaseAgent):
    """
    Keyword Optimizer - Bid management and keyword additions.

    Responsibilities:
    - Optimize bids at keyword level
    - Add high-performing keywords
    - Pause low-performing keywords
    - Adjust match types based on performance
    - Monitor search term reports for new opportunities

    Operates on: Daily cycles
    """

    def __init__(self, agent_id: str = "keyword_optimizer", **kwargs):
        super().__init__(
            agent_id=agent_id,
            capabilities=[
                AgentCapability.KEYWORD_MANAGEMENT,
                AgentCapability.BID_OPTIMIZATION,
                AgentCapability.AUTONOMOUS_EXECUTION,
            ],
            auto_execute_threshold=0.92,
            **kwargs
        )

    def analyze(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Analyze keyword performance."""
        opportunities = []

        keywords = context.get('keywords', [])

        for keyword in keywords:
            keyword_id = keyword['id']
            keyword_text = keyword.get('text', '')
            cpa = keyword.get('cpa_30d', 0)
            conversions = keyword.get('conversions_30d', 0)
            spend = keyword.get('spend_30d', 0)

            # 1. Pause underperformers
            if spend > 200 and conversions == 0:  # Spent >$200 with 0 conversions
                opportunities.append({
                    'type': 'pause_keyword',
                    'severity': 'medium',
                    'keyword_id': keyword_id,
                    'keyword_text': keyword_text,
                    'spend_30d': spend,
                    'conversions_30d': conversions
                })

            # 2. Bid adjustments for converters
            target_cpa = context.get('target_cpa', 100)
            if conversions >= 5 and cpa != 0:  # Enough data
                if cpa < target_cpa * 0.8:  # CPA 20% below target
                    # Increase bids
                    bid_increase_pct = min(30, ((target_cpa - cpa) / cpa) * 100)
                    opportunities.append({
                        'type': 'increase_bid',
                        'severity': 'medium',
                        'keyword_id': keyword_id,
                        'keyword_text': keyword_text,
                        'current_cpa': cpa,
                        'target_cpa': target_cpa,
                        'recommended_bid_change_pct': bid_increase_pct
                    })
                elif cpa > target_cpa * 1.2:  # CPA 20% above target
                    # Decrease bids
                    bid_decrease_pct = -min(30, ((cpa - target_cpa) / target_cpa) * 100)
                    opportunities.append({
                        'type': 'decrease_bid',
                        'severity': 'medium',
                        'keyword_id': keyword_id,
                        'keyword_text': keyword_text,
                        'current_cpa': cpa,
                        'target_cpa': target_cpa,
                        'recommended_bid_change_pct': bid_decrease_pct
                    })

        # 3. Search term analysis for new keywords
        search_terms = context.get('search_terms', [])
        for term in search_terms:
            if term.get('conversions', 0) >= 2 and term.get('cost_per_conversion', 0) < target_cpa:
                # High-performing search term not yet a keyword
                if not self._is_already_keyword(term['query'], keywords):
                    opportunities.append({
                        'type': 'add_keyword',
                        'severity': 'low',
                        'search_query': term['query'],
                        'conversions': term['conversions'],
                        'cpa': term['cost_per_conversion']
                    })

        return opportunities

    def decide(self, opportunities: List[Dict[str, Any]]) -> List[AgentDecision]:
        """Make keyword optimization decisions."""
        decisions = []

        for opp in opportunities:
            opp_type = opp['type']

            if opp_type == 'pause_keyword':
                decision = AgentDecision(
                    agent_id=self.agent_id,
                    agent_type=self.agent_type,
                    decision_type='pause_keyword',
                    title=f"Pause keyword '{opp['keyword_text']}'",
                    description=f"Spent ${opp['spend_30d']:.0f} with 0 conversions in 30 days",
                    reasoning="No conversions after significant spend - not a fit",
                    account_id=0,
                    customer_id='',
                    action_data={
                        'keyword_id': opp['keyword_id']
                    },
                    risk_level=DecisionRiskLevel.LOW,
                    requires_approval=False,
                    confidence=0.95,
                    expected_monthly_savings=opp['spend_30d']
                )
                decisions.append(decision)

            elif opp_type in ['increase_bid', 'decrease_bid']:
                decision = AgentDecision(
                    agent_id=self.agent_id,
                    agent_type=self.agent_type,
                    decision_type='adjust_keyword_bid',
                    title=f"Adjust bid for '{opp['keyword_text']}' by {opp['recommended_bid_change_pct']:+.0f}%",
                    description=f"Current CPA ${opp['current_cpa']:.2f}, Target ${opp['target_cpa']:.2f}",
                    reasoning="Optimize bid to reach target CPA",
                    account_id=0,
                    customer_id='',
                    action_data={
                        'keyword_id': opp['keyword_id'],
                        'bid_change_pct': opp['recommended_bid_change_pct']
                    },
                    risk_level=DecisionRiskLevel.LOW,
                    requires_approval=False,
                    confidence=0.88
                )
                decisions.append(decision)

            elif opp_type == 'add_keyword':
                decision = AgentDecision(
                    agent_id=self.agent_id,
                    agent_type=self.agent_type,
                    decision_type='add_keyword',
                    title=f"Add new keyword '{opp['search_query']}'",
                    description=f"Search term has {opp['conversions']} conversions at ${opp['cpa']:.2f} CPA",
                    reasoning="Proven performer as search term - add as keyword",
                    account_id=0,
                    customer_id='',
                    action_data={
                        'keyword_text': opp['search_query'],
                        'match_type': 'PHRASE'
                    },
                    risk_level=DecisionRiskLevel.LOW,
                    requires_approval=False,
                    confidence=0.85,
                    expected_monthly_leads=2
                )
                decisions.append(decision)

        return decisions

    def _execute_impl(self, decision: AgentDecision, google_ads_client: Any) -> Dict[str, Any]:
        """Execute keyword optimizations."""
        decision_type = decision.decision_type

        if decision_type == 'pause_keyword':
            return {'success': True, 'keyword_id': decision.action_data['keyword_id'], 'status': 'PAUSED'}

        elif decision_type == 'adjust_keyword_bid':
            return {
                'success': True,
                'keyword_id': decision.action_data['keyword_id'],
                'bid_change_pct': decision.action_data['bid_change_pct']
            }

        elif decision_type == 'add_keyword':
            return {
                'success': True,
                'keyword_text': decision.action_data['keyword_text'],
                'match_type': decision.action_data['match_type']
            }

        return {'success': False, 'error': f'Unknown decision type: {decision_type}'}

    def _is_already_keyword(self, search_query: str, keywords: List[Dict]) -> bool:
        """Check if search query is already a keyword."""
        query_lower = search_query.lower()
        return any(k.get('text', '').lower() == query_lower for k in keywords)


class NegativeKeywordAgent(BaseAgent):
    """
    Negative Keyword Agent - Your search term detective.

    Responsibilities:
    - Review search term reports daily
    - Identify irrelevant searches
    - Add negative keywords to block waste
    - Build negative keyword lists
    - Monitor negative keyword performance

    Operates on: Daily cycles
    """

    def __init__(self, agent_id: str = "negative_keyword_agent", **kwargs):
        super().__init__(
            agent_id=agent_id,
            capabilities=[
                AgentCapability.KEYWORD_MANAGEMENT,
                AgentCapability.AUTONOMOUS_EXECUTION,
            ],
            auto_execute_threshold=0.95,  # Very confident - blocking waste is safe
            **kwargs
        )

        # Common irrelevant terms for home services
        self.waste_patterns = [
            'free',
            'diy',
            'how to',
            'jobs',
            'salary',
            'course',
            'training',
            'school',
            'cheap',
            'discount',
        ]

    def analyze(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Analyze search terms for waste."""
        opportunities = []

        search_terms = context.get('search_terms', [])

        for term in search_terms:
            query = term.get('query', '').lower()
            cost = term.get('cost', 0)
            conversions = term.get('conversions', 0)

            # 1. Obvious waste patterns
            for pattern in self.waste_patterns:
                if pattern in query:
                    opportunities.append({
                        'type': 'add_negative_keyword',
                        'severity': 'high',
                        'confidence': 0.99,
                        'search_query': term['query'],
                        'cost': cost,
                        'conversions': conversions,
                        'reason': f'Contains waste pattern: {pattern}'
                    })
                    break

            # 2. Spent money with no conversions
            if cost > 50 and conversions == 0:
                # Analyze if it's relevant to business
                if self._is_irrelevant(query, context):
                    opportunities.append({
                        'type': 'add_negative_keyword',
                        'severity': 'medium',
                        'confidence': 0.85,
                        'search_query': term['query'],
                        'cost': cost,
                        'conversions': conversions,
                        'reason': 'Irrelevant to business after spending >$50'
                    })

        return opportunities

    def decide(self, opportunities: List[Dict[str, Any]]) -> List[AgentDecision]:
        """Make negative keyword decisions."""
        decisions = []

        for opp in opportunities:
            decision = AgentDecision(
                agent_id=self.agent_id,
                agent_type=self.agent_type,
                decision_type='add_negative_keyword',
                title=f"Block search term '{opp['search_query']}'",
                description=f"Cost ${opp['cost']:.2f}, {opp['conversions']} conversions",
                reasoning=opp['reason'],
                account_id=0,
                customer_id='',
                action_data={
                    'keyword_text': opp['search_query'],
                    'match_type': 'PHRASE'
                },
                risk_level=DecisionRiskLevel.LOW,
                requires_approval=False,
                confidence=opp['confidence'],
                expected_monthly_savings=opp['cost']
            )
            decisions.append(decision)

        return decisions

    def _execute_impl(self, decision: AgentDecision, google_ads_client: Any) -> Dict[str, Any]:
        """Execute negative keyword additions."""
        return {
            'success': True,
            'negative_keyword': decision.action_data['keyword_text'],
            'match_type': decision.action_data['match_type']
        }

    def _is_irrelevant(self, query: str, context: Dict[str, Any]) -> bool:
        """Determine if search query is irrelevant to business."""
        # This would use NLP/ML in production
        # For now, simple heuristic
        business_type = context.get('business_type', 'hvac')

        if business_type == 'hvac':
            irrelevant_terms = ['parts', 'wholesale', 'diagram', 'manual']
            return any(term in query for term in irrelevant_terms)

        return False


class AdCopyAgent(BaseAgent):
    """
    Ad Copy Scientist - A/B tests while you sleep.

    Responsibilities:
    - Create new ad variations
    - Run A/B tests
    - Identify winning patterns
    - Pause underperforming ads
    - Improve ad relevance for Quality Score

    Operates on: Weekly cycles
    """

    def __init__(self, agent_id: str = "ad_copy_scientist", **kwargs):
        super().__init__(
            agent_id=agent_id,
            capabilities=[
                AgentCapability.AD_CREATION,
                AgentCapability.QUALITY_SCORE_OPTIMIZATION,
            ],
            auto_execute_threshold=0.80,
            **kwargs
        )

    def analyze(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Analyze ad performance."""
        opportunities = []

        ad_groups = context.get('ad_groups', [])

        for ad_group in ad_groups:
            ads = ad_group.get('ads', [])

            if len(ads) < 3:
                # Not enough ad variations for testing
                opportunities.append({
                    'type': 'create_ad_variations',
                    'severity': 'medium',
                    'ad_group_id': ad_group['id'],
                    'ad_group_name': ad_group.get('name', ''),
                    'current_ad_count': len(ads),
                    'target_ad_count': 3
                })

            # Find underperforming ads
            for ad in ads:
                if ad.get('impressions', 0) > 1000:  # Has enough data
                    ctr = ad.get('ctr', 0)
                    avg_ctr = ad_group.get('avg_ctr', 3.0)

                    if ctr < avg_ctr * 0.7:  # 30% below average
                        opportunities.append({
                            'type': 'pause_underperforming_ad',
                            'severity': 'low',
                            'ad_id': ad['id'],
                            'ad_group_id': ad_group['id'],
                            'ctr': ctr,
                            'avg_ctr': avg_ctr
                        })

        return opportunities

    def decide(self, opportunities: List[Dict[str, Any]]) -> List[AgentDecision]:
        """Make ad copy decisions."""
        decisions = []

        for opp in opportunities:
            opp_type = opp['type']

            if opp_type == 'create_ad_variations':
                decision = AgentDecision(
                    agent_id=self.agent_id,
                    agent_type=self.agent_type,
                    decision_type='create_ad_variations',
                    title=f"Create {opp['target_ad_count'] - opp['current_ad_count']} new ads for '{opp['ad_group_name']}'",
                    description=f"Currently only {opp['current_ad_count']} ads - need more for testing",
                    reasoning="Need 3+ ads per group for effective A/B testing",
                    account_id=0,
                    customer_id='',
                    ad_group_id=opp['ad_group_id'],
                    action_data={
                        'ad_group_id': opp['ad_group_id'],
                        'variations_needed': opp['target_ad_count'] - opp['current_ad_count']
                    },
                    risk_level=DecisionRiskLevel.MEDIUM,
                    requires_approval=True,
                    confidence=0.75,
                    expected_improvement_pct=10  # 10% CTR improvement from testing
                )
                decisions.append(decision)

            elif opp_type == 'pause_underperforming_ad':
                decision = AgentDecision(
                    agent_id=self.agent_id,
                    agent_type=self.agent_type,
                    decision_type='pause_ad',
                    title=f"Pause underperforming ad (CTR {opp['ctr']:.1f}% vs {opp['avg_ctr']:.1f}% avg)",
                    description="Ad is 30% below group average CTR",
                    reasoning="Keep only winning ads active",
                    account_id=0,
                    customer_id='',
                    action_data={
                        'ad_id': opp['ad_id']
                    },
                    risk_level=DecisionRiskLevel.LOW,
                    requires_approval=False,
                    confidence=0.90
                )
                decisions.append(decision)

        return decisions

    def _execute_impl(self, decision: AgentDecision, google_ads_client: Any) -> Dict[str, Any]:
        """Execute ad copy changes."""
        decision_type = decision.decision_type

        if decision_type == 'create_ad_variations':
            # In production, would use AI to generate ad copy
            return {
                'success': True,
                'ad_group_id': decision.action_data['ad_group_id'],
                'ads_created': decision.action_data['variations_needed']
            }

        elif decision_type == 'pause_ad':
            return {
                'success': True,
                'ad_id': decision.action_data['ad_id'],
                'status': 'PAUSED'
            }

        return {'success': False, 'error': f'Unknown decision type: {decision_type}'}
