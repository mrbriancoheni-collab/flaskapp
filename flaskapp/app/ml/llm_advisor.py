# app/ml/llm_advisor.py
"""
LLM Advisor - Uses an LLM to interpret ML predictions and make decisions.

This module sends structured prompts to an LLM (OpenAI/Claude) with:
1. Account performance data
2. ML model predictions
3. Agent-specific analysis context

The LLM returns structured decisions that agents can act on.
"""
import json
import logging
import os
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


class LLMAdvisor:
    """
    LLM-powered decision advisor for Google Ads agents.

    Combines ML predictions with LLM reasoning to produce
    actionable optimization decisions.
    """

    def __init__(self):
        self.api_key = os.getenv('OPENAI_API_KEY')
        self.model = os.getenv('ADS_LLM_MODEL', 'gpt-4o-mini')

    def _call_llm(self, system_prompt: str, user_prompt: str) -> Optional[str]:
        """Call the LLM API and return the response text."""
        if not self.api_key:
            logger.warning("No OPENAI_API_KEY set, LLM advisor unavailable")
            return None

        try:
            import openai
            client = openai.OpenAI(api_key=self.api_key)

            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.2,
                max_tokens=2000,
                response_format={"type": "json_object"},
            )

            return response.choices[0].message.content

        except Exception as e:
            logger.error(f"LLM API call failed: {e}")
            return None

    def _parse_json_response(self, text: Optional[str]) -> Dict:
        """Parse JSON from LLM response, handling edge cases."""
        if not text:
            return {}
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Try to extract JSON from markdown code blocks
            if '```json' in text:
                start = text.index('```json') + 7
                end = text.index('```', start)
                return json.loads(text[start:end].strip())
            elif '```' in text:
                start = text.index('```') + 3
                end = text.index('```', start)
                return json.loads(text[start:end].strip())
            logger.warning(f"Could not parse LLM response as JSON")
            return {}

    # ------------------------------------------------------------------
    # Agent-specific advisors
    # ------------------------------------------------------------------

    def advise_strategic(self, ml_context: str, account_context: Dict) -> Dict:
        """Get strategic budget allocation and goal-setting advice."""
        system = """You are a Google Ads strategic advisor. Analyze the account data
and ML predictions to recommend strategic optimizations.

Respond with JSON containing:
{
    "decisions": [
        {
            "type": "budget_reallocation|goal_adjustment|campaign_structure",
            "description": "What to do and why",
            "campaigns_affected": ["campaign names"],
            "expected_impact": "Expected improvement",
            "risk_level": "low|medium|high",
            "confidence": 0.0-1.0,
            "priority": 1-5
        }
    ],
    "overall_assessment": "Brief account health summary",
    "key_opportunities": ["Top 3 opportunities"]
}"""

        user = f"""Account data with ML predictions:

{ml_context}

Based on this data and the ML model predictions, what strategic
decisions should be made? Focus on budget allocation, campaign
structure, and overall strategy. Only recommend changes with
clear data support."""

        response = self._call_llm(system, user)
        return self._parse_json_response(response)

    def advise_campaign_manager(self, ml_context: str, account_context: Dict) -> Dict:
        """Get campaign performance optimization advice."""
        system = """You are a Google Ads campaign performance analyst. Analyze the
campaign health data and ML anomaly detection to identify issues.

Respond with JSON containing:
{
    "decisions": [
        {
            "type": "bid_adjustment|pause_campaign|increase_budget|alert",
            "campaign": "campaign name",
            "description": "What to do and why",
            "urgency": "immediate|soon|monitor",
            "risk_level": "low|medium|high",
            "confidence": 0.0-1.0,
            "expected_impact_monthly": 0.00
        }
    ],
    "anomalies_found": ["List of detected anomalies"],
    "campaigns_needing_attention": ["Campaign names"]
}"""

        user = f"""Campaign health data with ML analysis:

{ml_context}

Identify campaigns with performance issues. Use ML anomaly scores
and trends to prioritize. Only flag issues backed by data."""

        response = self._call_llm(system, user)
        return self._parse_json_response(response)

    def advise_budget_guardian(self, ml_context: str, account_context: Dict) -> Dict:
        """Get budget pacing and allocation advice."""
        system = """You are a Google Ads budget management specialist. Analyze spending
patterns and ML predictions to optimize budget utilization.

Respond with JSON containing:
{
    "decisions": [
        {
            "type": "adjust_daily_budget|redistribute_budget|set_pacing_rule",
            "campaign": "campaign name",
            "description": "What to adjust and why",
            "current_value": 0.00,
            "recommended_value": 0.00,
            "risk_level": "low|medium|high",
            "confidence": 0.0-1.0
        }
    ],
    "pacing_status": "on_track|underspending|overspending",
    "projected_month_end_spend": 0.00,
    "budget_efficiency_score": 0.0-1.0
}"""

        user = f"""Budget status with ML spend predictions:

{ml_context}

Analyze budget pacing and recommend adjustments. Use ML spend
predictions for forward-looking recommendations."""

        response = self._call_llm(system, user)
        return self._parse_json_response(response)

    def advise_quality_score(self, ml_context: str, account_context: Dict) -> Dict:
        """Get quality score optimization advice."""
        system = """You are a Google Ads quality score optimization specialist.
Analyze keyword quality scores and ML predictions to prioritize improvements.

Respond with JSON containing:
{
    "decisions": [
        {
            "type": "improve_ad_relevance|improve_landing_page|improve_ctr",
            "keyword": "keyword text",
            "current_qs": 0,
            "predicted_qs_after": 0,
            "description": "Specific improvement recommendation",
            "expected_cpc_reduction": 0.00,
            "risk_level": "low",
            "confidence": 0.0-1.0
        }
    ],
    "account_avg_qs": 0.0,
    "biggest_impact_keywords": ["keyword texts"]
}"""

        user = f"""Quality score data with ML predictions:

{ml_context}

Identify keywords where quality score improvements would have
the biggest impact on costs and performance."""

        response = self._call_llm(system, user)
        return self._parse_json_response(response)

    def advise_keyword_optimizer(self, ml_context: str, account_context: Dict) -> Dict:
        """Get keyword bid and management advice."""
        system = """You are a Google Ads keyword optimization specialist. Analyze
keyword performance and ML CPA predictions to optimize bids.

Respond with JSON containing:
{
    "decisions": [
        {
            "type": "adjust_bid|pause_keyword|add_keyword|change_match_type",
            "keyword": "keyword text",
            "description": "What to do and why",
            "current_bid": 0.00,
            "recommended_bid": 0.00,
            "predicted_cpa_impact": 0.00,
            "risk_level": "low|medium|high",
            "confidence": 0.0-1.0
        }
    ],
    "keywords_to_pause": ["keywords with high spend, zero conversions"],
    "keywords_to_boost": ["keywords with good CPA, low impression share"]
}"""

        user = f"""Keyword performance with ML predictions:

{ml_context}

Optimize keyword bids using ML CPA predictions. Focus on keywords
where bid changes can measurably improve CPA."""

        response = self._call_llm(system, user)
        return self._parse_json_response(response)

    def advise_negative_keyword(self, ml_context: str, account_context: Dict) -> Dict:
        """Get negative keyword recommendations."""
        system = """You are a Google Ads negative keyword specialist. Analyze search
terms and ML waste predictions to identify terms to block.

Respond with JSON containing:
{
    "decisions": [
        {
            "type": "add_negative_exact|add_negative_phrase|add_negative_broad",
            "search_term": "the search term to block",
            "reason": "Why this is wasteful",
            "wasted_spend": 0.00,
            "match_type": "exact|phrase|broad",
            "scope": "campaign|ad_group|account",
            "risk_level": "low",
            "confidence": 0.0-1.0
        }
    ],
    "total_potential_savings_monthly": 0.00,
    "waste_categories": {"category": count}
}"""

        user = f"""Search term waste analysis with ML classifications:

{ml_context}

Identify search terms that should be added as negative keywords.
Use ML waste probability scores to prioritize. Be conservative -
only recommend blocking terms that are clearly irrelevant."""

        response = self._call_llm(system, user)
        return self._parse_json_response(response)

    def advise_ad_copy(self, ml_context: str, account_context: Dict) -> Dict:
        """Get ad copy optimization advice."""
        system = """You are a Google Ads ad copy optimization specialist. Analyze
ad performance and recommend improvements.

Respond with JSON containing:
{
    "decisions": [
        {
            "type": "update_headlines|update_descriptions|pause_ad|create_variation",
            "ad_group": "ad group name",
            "description": "What to change and why",
            "current_ctr": 0.00,
            "expected_ctr_improvement": 0.00,
            "risk_level": "low|medium|high",
            "confidence": 0.0-1.0,
            "suggested_copy": {
                "headlines": ["headline1", "headline2"],
                "descriptions": ["description1"]
            }
        }
    ],
    "best_performing_elements": ["What's working well"],
    "improvement_areas": ["What needs work"]
}"""

        user = f"""Ad copy analysis with ML predictions:

{ml_context}

Recommend ad copy improvements. Use ML CTR predictions to guide
recommendations. Focus on changes likely to improve click-through rates."""

        response = self._call_llm(system, user)
        return self._parse_json_response(response)

    # ------------------------------------------------------------------
    # Unified advisor
    # ------------------------------------------------------------------

    def get_advice(self, agent_type: str, ml_context: str, account_context: Dict) -> Dict:
        """Get LLM advice for any agent type."""
        advisors = {
            'strategic_director': self.advise_strategic,
            'campaign_manager': self.advise_campaign_manager,
            'budget_guardian': self.advise_budget_guardian,
            'quality_score': self.advise_quality_score,
            'keyword_optimizer': self.advise_keyword_optimizer,
            'negative_keyword': self.advise_negative_keyword,
            'ad_copy': self.advise_ad_copy,
        }

        advisor = advisors.get(agent_type)
        if not advisor:
            logger.warning(f"No LLM advisor for agent type: {agent_type}")
            return {}

        try:
            result = advisor(ml_context, account_context)
            if result:
                logger.info(
                    f"LLM advisor returned {len(result.get('decisions', []))} decisions "
                    f"for {agent_type}"
                )
            return result
        except Exception as e:
            logger.error(f"LLM advisor error for {agent_type}: {e}")
            return {}
