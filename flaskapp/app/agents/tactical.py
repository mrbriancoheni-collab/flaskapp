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
        from .executor import GoogleAdsAgentExecutor

        decision_type = decision.decision_type

        if isinstance(google_ads_client, GoogleAdsAgentExecutor):
            if decision_type == 'pause_keyword':
                return google_ads_client.pause_keyword(
                    ad_group_id=decision.ad_group_id or '',
                    keyword_id=decision.action_data['keyword_id']
                )
            elif decision_type == 'adjust_keyword_bid':
                return google_ads_client.adjust_keyword_bid(
                    ad_group_id=decision.ad_group_id or '',
                    keyword_id=decision.action_data['keyword_id'],
                    bid_change_pct=decision.action_data['bid_change_pct']
                )
            elif decision_type == 'add_keyword':
                return google_ads_client.add_keyword(
                    ad_group_id=decision.ad_group_id or '',
                    keyword_text=decision.action_data['keyword_text'],
                    match_type=decision.action_data['match_type']
                )

        # Fallback mock responses
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
    - Identify irrelevant searches using pattern matching AND LLM business-relevance analysis
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
        """Analyze search terms for waste using pattern matching + LLM business relevance."""
        opportunities = []
        pattern_matched_queries = set()

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
                    pattern_matched_queries.add(query)
                    break

        # 2. LLM-based business relevance check for remaining terms
        business_desc = context.get('business_description', '')
        business_services = context.get('business_services', '')

        if business_desc:
            remaining_terms = [
                t for t in search_terms
                if t.get('query', '').lower() not in pattern_matched_queries
            ]

            if remaining_terms:
                llm_results = self._evaluate_terms_with_llm(
                    remaining_terms, business_desc, business_services
                )

                for term in remaining_terms:
                    query = term.get('query', '').lower()
                    cost = term.get('cost', 0)
                    conversions = term.get('conversions', 0)
                    result = llm_results.get(query, {})

                    if result.get('irrelevant', False):
                        opportunities.append({
                            'type': 'add_negative_keyword',
                            'severity': 'high',
                            'confidence': 0.92,
                            'search_query': term['query'],
                            'cost': cost,
                            'conversions': conversions,
                            'reason': f"AI: {result.get('reason', 'Irrelevant to business')}"
                        })
        else:
            # Fallback: flag high-spend zero-conversion terms
            for term in search_terms:
                query = term.get('query', '').lower()
                if query in pattern_matched_queries:
                    continue
                cost = term.get('cost', 0)
                conversions = term.get('conversions', 0)
                if cost > 50 and conversions == 0:
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

    def _evaluate_terms_with_llm(
        self,
        search_terms: List[Dict[str, Any]],
        business_desc: str,
        business_services: str
    ) -> Dict[str, Dict]:
        """Use LLM to evaluate search term relevance to the business."""
        import os
        import json

        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            return {}

        terms_list = "\n".join(
            f"- {t.get('query', '')}" for t in search_terms[:50]
        )

        business_context = f"Business: {business_desc}"
        if business_services:
            business_context += f"\nServices offered: {business_services}"

        prompt = f"""You are a Google Ads negative keyword analyst. Analyze each search term and determine if it is RELEVANT or IRRELEVANT to this business.

{business_context}

A term is RELEVANT if a person searching it could reasonably become a paying customer for the specific services listed. A term is IRRELEVANT if it relates to a different service, industry, or has no purchase intent for these services.

Foreign language terms that relate to the business services should be marked RELEVANT.

Search terms:
{terms_list}

Respond ONLY with valid JSON — an array of objects:
[{{"term": "the search term", "irrelevant": true/false, "reason": "brief explanation"}}]

Be conservative: when in doubt, mark as RELEVANT."""

        try:
            from openai import OpenAI
            client = OpenAI(api_key=api_key)

            resp = client.chat.completions.create(
                model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=4000,
            )

            content = (resp.choices[0].message.content or "").strip()
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
                content = content.strip()

            results_list = json.loads(content)
            return {
                item.get('term', '').lower().strip(): {
                    'irrelevant': item.get('irrelevant', False),
                    'reason': item.get('reason', '')
                }
                for item in results_list
            }

        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"NegativeKeywordAgent LLM evaluation failed: {e}")
            return {}

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
        from .executor import GoogleAdsAgentExecutor

        if isinstance(google_ads_client, GoogleAdsAgentExecutor):
            return google_ads_client.add_negative_keyword(
                campaign_id=decision.campaign_id or '',
                keyword_text=decision.action_data['keyword_text'],
                match_type=decision.action_data['match_type']
            )

        return {
            'success': True,
            'negative_keyword': decision.action_data['keyword_text'],
            'match_type': decision.action_data['match_type']
        }

    def _is_irrelevant(self, query: str, context: Dict[str, Any]) -> bool:
        """Determine if search query is irrelevant to business (fallback heuristic)."""
        # Generic irrelevant terms that apply across industries
        generic_irrelevant = [
            'parts', 'wholesale', 'diagram', 'manual', 'catalog',
            'near me jobs', 'intern', 'volunteer', 'degree',
            'for kids', 'toy', 'game', 'movie', 'song',
            'designs', 'ideas', 'inspiration', 'pinterest',
        ]
        return any(term in query for term in generic_irrelevant)


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
        from .executor import GoogleAdsAgentExecutor

        decision_type = decision.decision_type

        if isinstance(google_ads_client, GoogleAdsAgentExecutor):
            if decision_type == 'pause_ad':
                return google_ads_client.pause_ad(ad_id=decision.action_data['ad_id'])

        # Fallback mock responses
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

class LandingPageAnalystAgent(BaseAgent):
    """
    Landing Page Analyst - CRO Expert ensuring message match.

    Responsibilities:
    - Analyze landing page alignment with ad copy
    - Ensure keyword-to-page relevance for Quality Score
    - Identify CRO issues (page speed, form friction, trust signals)
    - Optimize conversion funnel elements
    - A/B test recommendations for landing pages
    - Monitor mobile vs desktop experience gaps

    Operates on: Weekly cycles
    """

    def __init__(self, agent_id: str = "landing_page_analyst", **kwargs):
        super().__init__(
            agent_id=agent_id,
            capabilities=[
                AgentCapability.LANDING_PAGE_OPTIMIZATION,
                AgentCapability.QUALITY_SCORE_OPTIMIZATION,
            ],
            auto_execute_threshold=0.75,  # Lower threshold since LPs require manual changes
            **kwargs
        )

    def analyze(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Analyze landing page performance and alignment."""
        opportunities = []

        campaigns = context.get('campaigns', [])
        keywords = context.get('keywords', [])

        for campaign in campaigns:
            campaign_id = campaign.get('id', '')
            landing_url = campaign.get('landing_url', '')

            if not landing_url:
                continue

            # 1. Message Match Analysis
            ad_headlines = campaign.get('ad_headlines', [])
            keywords_list = [k.get('text', '') for k in keywords if k.get('campaign_id') == campaign_id]

            # Check if landing page title matches ad copy
            page_title = campaign.get('page_title', '')
            headline_match = any(headline.lower() in page_title.lower() for headline in ad_headlines)

            if not headline_match and ad_headlines:
                opportunities.append({
                    'type': 'improve_message_match',
                    'severity': 'high',
                    'campaign_id': campaign_id,
                    'landing_url': landing_url,
                    'ad_headlines': ad_headlines,
                    'page_title': page_title,
                    'issue': 'Ad headline not reflected in landing page H1/title'
                })

            # 2. Keyword Relevance
            # Check if top keywords appear on landing page
            top_keywords = [k for k in keywords_list[:5]]  # Top 5 keywords
            page_content = campaign.get('page_content', '').lower()

            missing_keywords = [kw for kw in top_keywords if kw.lower() not in page_content]
            if len(missing_keywords) >= 2:  # 2+ top keywords missing
                opportunities.append({
                    'type': 'add_keywords_to_page',
                    'severity': 'medium',
                    'campaign_id': campaign_id,
                    'landing_url': landing_url,
                    'missing_keywords': missing_keywords,
                    'issue': 'Top keywords not found on landing page - hurts Quality Score'
                })

            # 3. Page Speed Issues
            load_time = campaign.get('page_load_time_seconds', 0)
            if load_time > 3.0:  # Google recommends <3 seconds
                mobile_load = campaign.get('mobile_load_time_seconds', 0)
                opportunities.append({
                    'type': 'improve_page_speed',
                    'severity': 'high',
                    'campaign_id': campaign_id,
                    'landing_url': landing_url,
                    'load_time': load_time,
                    'mobile_load_time': mobile_load,
                    'issue': f'Page loads in {load_time:.1f}s - should be <3s'
                })

            # 4. Form Friction
            form_fields = campaign.get('form_field_count', 0)
            if form_fields > 5:
                opportunities.append({
                    'type': 'reduce_form_friction',
                    'severity': 'medium',
                    'campaign_id': campaign_id,
                    'landing_url': landing_url,
                    'form_fields': form_fields,
                    'issue': f'Form has {form_fields} fields - recommended ≤5 for better conversion'
                })

            # 5. Trust Signals
            has_reviews = campaign.get('has_reviews', False)
            has_trust_badges = campaign.get('has_trust_badges', False)
            has_guarantees = campaign.get('has_guarantees', False)

            missing_trust = []
            if not has_reviews:
                missing_trust.append('customer reviews')
            if not has_trust_badges:
                missing_trust.append('trust badges (BBB, license #)')
            if not has_guarantees:
                missing_trust.append('service guarantee')

            if len(missing_trust) >= 2:
                opportunities.append({
                    'type': 'add_trust_signals',
                    'severity': 'medium',
                    'campaign_id': campaign_id,
                    'landing_url': landing_url,
                    'missing_signals': missing_trust,
                    'issue': 'Missing trust signals that increase conversion rates'
                })

            # 6. Mobile Experience Gap
            mobile_cvr = campaign.get('mobile_conversion_rate', 0)
            desktop_cvr = campaign.get('desktop_conversion_rate', 0)

            if desktop_cvr > 0 and mobile_cvr < desktop_cvr * 0.6:  # Mobile <60% of desktop
                opportunities.append({
                    'type': 'improve_mobile_experience',
                    'severity': 'high',
                    'campaign_id': campaign_id,
                    'landing_url': landing_url,
                    'mobile_cvr': mobile_cvr,
                    'desktop_cvr': desktop_cvr,
                    'issue': f'Mobile CVR ({mobile_cvr:.1%}) is {(1 - mobile_cvr/desktop_cvr)*100:.0f}% lower than desktop'
                })

            # 7. CTA Analysis
            cta_above_fold = campaign.get('cta_above_fold', False)
            cta_count = campaign.get('cta_count', 0)

            if not cta_above_fold or cta_count < 2:
                opportunities.append({
                    'type': 'optimize_cta_placement',
                    'severity': 'medium',
                    'campaign_id': campaign_id,
                    'landing_url': landing_url,
                    'cta_above_fold': cta_above_fold,
                    'cta_count': cta_count,
                    'issue': 'CTA not prominent - should be above fold + 2-3 total CTAs'
                })

        return opportunities

    def decide(self, opportunities: List[Dict[str, Any]]) -> List[AgentDecision]:
        """Make landing page optimization decisions."""
        decisions = []

        for opp in opportunities:
            opp_type = opp['type']
            severity = opp.get('severity', 'medium')

            # Map severity to risk level
            risk_map = {
                'low': DecisionRiskLevel.LOW,
                'medium': DecisionRiskLevel.MEDIUM,
                'high': DecisionRiskLevel.HIGH
            }
            risk_level = risk_map.get(severity, DecisionRiskLevel.MEDIUM)

            if opp_type == 'improve_message_match':
                decision = AgentDecision(
                    agent_id=self.agent_id,
                    agent_type=self.agent_type,
                    decision_type='improve_message_match',
                    title=f"Align landing page with ad copy",
                    description=f"Page title: '{opp['page_title']}' doesn't match ad headlines",
                    reasoning="Message match improves Quality Score and conversion rate by meeting user expectations",
                    account_id=0,
                    customer_id='',
                    campaign_id=opp['campaign_id'],
                    action_data={
                        'landing_url': opp['landing_url'],
                        'suggested_h1': opp['ad_headlines'][0] if opp['ad_headlines'] else '',
                        'ad_headlines': opp['ad_headlines']
                    },
                    risk_level=risk_level,
                    requires_approval=True,
                    confidence=0.85,
                    expected_improvement_pct=15
                )
                decisions.append(decision)

            elif opp_type == 'add_keywords_to_page':
                decision = AgentDecision(
                    agent_id=self.agent_id,
                    agent_type=self.agent_type,
                    decision_type='add_keywords_to_page',
                    title=f"Add missing keywords to landing page",
                    description=f"Keywords missing: {', '.join(opp['missing_keywords'])}",
                    reasoning="Including target keywords on landing page improves Quality Score",
                    account_id=0,
                    customer_id='',
                    campaign_id=opp['campaign_id'],
                    action_data={
                        'landing_url': opp['landing_url'],
                        'missing_keywords': opp['missing_keywords']
                    },
                    risk_level=risk_level,
                    requires_approval=True,
                    confidence=0.90,
                    expected_improvement_pct=10
                )
                decisions.append(decision)

            elif opp_type == 'improve_page_speed':
                decision = AgentDecision(
                    agent_id=self.agent_id,
                    agent_type=self.agent_type,
                    decision_type='improve_page_speed',
                    title=f"Optimize page speed ({opp['load_time']:.1f}s → <3s)",
                    description=f"Current load: {opp['load_time']:.1f}s desktop, {opp.get('mobile_load_time', 0):.1f}s mobile",
                    reasoning="Page speed directly impacts conversion rate and Quality Score",
                    account_id=0,
                    customer_id='',
                    campaign_id=opp['campaign_id'],
                    action_data={
                        'landing_url': opp['landing_url'],
                        'current_load_time': opp['load_time'],
                        'target_load_time': 2.5
                    },
                    risk_level=risk_level,
                    requires_approval=True,
                    confidence=0.95,
                    expected_improvement_pct=25
                )
                decisions.append(decision)

            elif opp_type == 'reduce_form_friction':
                decision = AgentDecision(
                    agent_id=self.agent_id,
                    agent_type=self.agent_type,
                    decision_type='reduce_form_friction',
                    title=f"Simplify form ({opp['form_fields']} → ≤5 fields)",
                    description=f"Each extra field reduces conversions ~11%",
                    reasoning="Forms with ≤5 fields convert 120% better than longer forms",
                    account_id=0,
                    customer_id='',
                    campaign_id=opp['campaign_id'],
                    action_data={
                        'landing_url': opp['landing_url'],
                        'current_fields': opp['form_fields'],
                        'recommended_fields': 5
                    },
                    risk_level=risk_level,
                    requires_approval=True,
                    confidence=0.88,
                    expected_improvement_pct=30
                )
                decisions.append(decision)

            elif opp_type == 'add_trust_signals':
                decision = AgentDecision(
                    agent_id=self.agent_id,
                    agent_type=self.agent_type,
                    decision_type='add_trust_signals',
                    title=f"Add trust signals to landing page",
                    description=f"Missing: {', '.join(opp['missing_signals'])}",
                    reasoning="Trust signals increase conversion rates by 12-42%",
                    account_id=0,
                    customer_id='',
                    campaign_id=opp['campaign_id'],
                    action_data={
                        'landing_url': opp['landing_url'],
                        'missing_signals': opp['missing_signals']
                    },
                    risk_level=risk_level,
                    requires_approval=True,
                    confidence=0.80,
                    expected_improvement_pct=20
                )
                decisions.append(decision)

            elif opp_type == 'improve_mobile_experience':
                decision = AgentDecision(
                    agent_id=self.agent_id,
                    agent_type=self.agent_type,
                    decision_type='improve_mobile_experience',
                    title=f"Fix mobile conversion gap",
                    description=f"Mobile CVR ({opp['mobile_cvr']:.1%}) vs desktop ({opp['desktop_cvr']:.1%})",
                    reasoning="Mobile users are >50% of traffic - fixing mobile UX unlocks major revenue",
                    account_id=0,
                    customer_id='',
                    campaign_id=opp['campaign_id'],
                    action_data={
                        'landing_url': opp['landing_url'],
                        'mobile_cvr': opp['mobile_cvr'],
                        'desktop_cvr': opp['desktop_cvr']
                    },
                    risk_level=risk_level,
                    requires_approval=True,
                    confidence=0.92,
                    expected_improvement_pct=40
                )
                decisions.append(decision)

            elif opp_type == 'optimize_cta_placement':
                decision = AgentDecision(
                    agent_id=self.agent_id,
                    agent_type=self.agent_type,
                    decision_type='optimize_cta_placement',
                    title=f"Improve CTA visibility and placement",
                    description=f"CTA above fold: {opp['cta_above_fold']}, Total: {opp['cta_count']}",
                    reasoning="Above-fold CTA + 2-3 strategic CTAs increases conversions 20-30%",
                    account_id=0,
                    customer_id='',
                    campaign_id=opp['campaign_id'],
                    action_data={
                        'landing_url': opp['landing_url'],
                        'cta_above_fold': opp['cta_above_fold'],
                        'recommended_cta_count': 3
                    },
                    risk_level=risk_level,
                    requires_approval=True,
                    confidence=0.87,
                    expected_improvement_pct=25
                )
                decisions.append(decision)

        return decisions

    def _execute_impl(self, decision: AgentDecision, google_ads_client: Any) -> Dict[str, Any]:
        """
        Landing page changes require manual implementation.
        This agent creates recommendations but does not auto-execute.
        """
        # Landing page optimizations cannot be automated via Google Ads API
        # They require developer/designer work on the actual website
        return {
            'success': True,
            'note': 'Landing page optimization requires manual implementation',
            'decision_type': decision.decision_type,
            'landing_url': decision.action_data.get('landing_url'),
            'requires_manual_work': True
        }
