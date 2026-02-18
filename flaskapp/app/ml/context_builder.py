# app/ml/context_builder.py
"""
Context Builder - Combines ML predictions with raw data into
structured prompts for LLM-based decision making.

This is the bridge between the statistical ML models and the
LLM advisor. It takes ML predictions and account data and
builds agent-specific context that guides the LLM's analysis.
"""
import json
import logging
from typing import Dict, List, Any

from app.ml.predictor import MLPredictor

logger = logging.getLogger(__name__)


class ContextBuilder:
    """
    Builds rich LLM context by combining ML predictions with account data.

    Each agent type gets a specialized context builder that formats
    the data and ML insights in a way that helps the LLM make
    better decisions for that specific purpose.
    """

    def __init__(self, account_id: int, context: Dict):
        """
        Args:
            account_id: The Google Ads account ID
            context: The raw context dict from agent_scheduler (live data)
        """
        self.account_id = account_id
        self.context = context
        self.predictor = MLPredictor(account_id)

    def build_strategic_context(self) -> str:
        """Build context for Strategic Director agent."""
        campaigns = self.context.get('campaigns', [])
        perf_90d = self.context.get('performance_90d', {})

        # Get ML insights
        budget_insights = self.predictor.get_budget_allocation_insights(campaigns)

        sections = [
            "## Account Performance (Last 90 Days)",
            f"- Total Spend: ${perf_90d.get('spend', 0):,.2f}",
            f"- Total Conversions: {perf_90d.get('conversions', 0)}",
            f"- Average CPA: ${perf_90d.get('cost_per_conversion', 0):,.2f}",
            f"- ROAS: {perf_90d.get('roas', 0):.2f}x",
            "",
            "## Campaign Performance",
        ]

        for c in campaigns:
            pred = self.predictor.predict_campaign_roas(c)
            sections.append(
                f"- **{c.get('name')}**: Spend=${c.get('monthly_spend', 0):,.0f}/mo, "
                f"ROAS={c.get('roas', 0):.2f}x, CPA=${c.get('cpa', 0):,.0f}, "
                f"ImpShare={c.get('impression_share', 0):.0f}%"
            )
            if pred.get('predicted_roas') is not None:
                sections.append(
                    f"  ML Prediction: Expected ROAS={pred['predicted_roas']:.2f}x "
                    f"(confidence: {pred['confidence']:.0%})"
                )

        # Budget allocation recommendation
        if budget_insights.get('recommendation'):
            sections.extend([
                "",
                "## ML Budget Allocation Recommendation",
                budget_insights['recommendation'],
                f"(Confidence: {budget_insights.get('confidence', 0):.0%})",
            ])

        sections.extend([
            "",
            "## Business Context",
            f"- Business: {self.context.get('business_description', 'Not specified')}",
            f"- Services: {self.context.get('business_services', 'Not specified')}",
            f"- Target CPA: ${self.context.get('target_cpa', 80)}",
            f"- Target ROAS: {self.context.get('business_goals', {}).get('target_roas', 3.0)}x",
        ])

        return '\n'.join(sections)

    def build_campaign_manager_context(self) -> str:
        """Build context for Campaign Manager agent."""
        campaigns = self.context.get('campaigns', [])

        sections = [
            "## Campaign Health Dashboard",
        ]

        for c in campaigns:
            # Get anomaly detection
            anomaly = self.predictor.detect_anomaly(c)
            trend = self.predictor.get_performance_trend(c)

            status = "ANOMALY DETECTED" if anomaly.get('is_anomaly') else "Normal"
            sections.append(
                f"\n### {c.get('name')} [{status}]"
            )
            sections.append(
                f"- CPL: ${c.get('cpa', 0):,.0f} | Conv Rate: {c.get('conversion_rate_7d', 0):.1f}%"
            )
            sections.append(
                f"- Spend: ${c.get('monthly_spend', 0):,.0f}/mo | Budget: ${c.get('monthly_budget', 0):,.0f}/mo"
            )

            if anomaly.get('is_anomaly'):
                sections.append(
                    f"- **ANOMALY**: Severity={anomaly['severity']}, "
                    f"Score={anomaly['score']:.3f} (confidence: {anomaly['confidence']:.0%})"
                )

            sections.append(
                f"- Trend: {trend['description']} "
                f"(cost {trend['cost_trend_pct']:+.1f}%, conv {trend['conv_trend_pct']:+.1f}%)"
            )

        sections.extend([
            "",
            f"## Targets",
            f"- Target CPL: ${self.context.get('target_cpl', 80)}",
            f"- Target ROAS: {self.context.get('business_goals', {}).get('target_roas', 3.0)}x",
        ])

        return '\n'.join(sections)

    def build_budget_guardian_context(self) -> str:
        """Build context for Budget Guardian agent."""
        campaigns = self.context.get('campaigns', [])

        sections = [
            "## Budget Status",
        ]

        total_spend = sum(c.get('spend_mtd', 0) for c in campaigns)
        total_budget = sum(c.get('monthly_budget', 0) for c in campaigns)

        sections.extend([
            f"- Total MTD Spend: ${total_spend:,.0f}",
            f"- Total Monthly Budget: ${total_budget:,.0f}",
            f"- Budget Utilization: {total_spend / total_budget * 100:.0f}%" if total_budget > 0 else "- Budget: Not set",
            "",
            "## Per-Campaign Budget Status",
        ])

        for c in campaigns:
            spend_pacing = self.predictor.predict_daily_spend({
                'spend_yesterday': c.get('daily_spend_yesterday', 0),
                'spend_avg_7d': c.get('daily_spend_avg_7d', 0),
                'spend_avg_30d': c.get('monthly_spend', 0) / 30 if c.get('monthly_spend') else 0,
            })

            sections.append(f"\n### {c.get('name')}")
            sections.append(
                f"- MTD Spend: ${c.get('spend_mtd', 0):,.0f} / ${c.get('monthly_budget', 0):,.0f}"
            )
            sections.append(
                f"- Daily Avg (7d): ${c.get('daily_spend_avg_7d', 0):,.0f}"
            )

            if spend_pacing.get('predicted_daily_spend') is not None:
                sections.append(
                    f"- ML Predicted Next Day: ${spend_pacing['predicted_daily_spend']:,.0f} "
                    f"(confidence: {spend_pacing.get('confidence', 0):.0%})"
                )

        return '\n'.join(sections)

    def build_quality_score_context(self) -> str:
        """Build context for Quality Score agent."""
        keywords = self.context.get('keywords', [])

        sections = [
            "## Quality Score Analysis",
            f"Total keywords analyzed: {len(keywords)}",
            "",
        ]

        low_qs = [kw for kw in keywords if kw.get('quality_score', 10) < 5]
        if low_qs:
            sections.append(f"### Low Quality Score Keywords ({len(low_qs)})")
            for kw in low_qs[:10]:
                qs_pred = self.predictor.predict_quality_score({
                    'current_ctr': kw.get('ctr', 0),
                    'avg_ctr_30d': kw.get('ctr', 0),
                    'impressions_30d': kw.get('clicks', 0),
                    'clicks_30d': kw.get('clicks', 0),
                })
                sections.append(
                    f"- **{kw.get('text')}** (QS={kw.get('quality_score', '?')}, "
                    f"CPA=${kw.get('cpa', 0):,.0f}, Spend=${kw.get('spend', 0):,.0f})"
                )
                if qs_pred.get('predicted_qs') is not None:
                    sections.append(
                        f"  ML: Predicted QS={qs_pred['predicted_qs']} "
                        f"(confidence: {qs_pred['confidence']:.0%})"
                    )

        return '\n'.join(sections)

    def build_keyword_optimizer_context(self) -> str:
        """Build context for Keyword Optimizer agent."""
        keywords = self.context.get('keywords', [])
        target_cpa = self.context.get('target_cpa', 80)

        sections = [
            "## Keyword Optimization Analysis",
            f"Target CPA: ${target_cpa}",
            "",
            "### Keyword Performance with ML Predictions",
        ]

        for kw in keywords[:15]:
            cpa_pred = self.predictor.predict_keyword_cpa(kw)
            bid_rec = self.predictor.get_bid_recommendation(kw, target_cpa)

            sections.append(
                f"\n**{kw.get('text')}** [{kw.get('match', '?')}]"
            )
            sections.append(
                f"- Actual: CPA=${kw.get('cpa', 0):,.0f}, "
                f"Spend=${kw.get('spend', 0):,.0f}, "
                f"Conv={kw.get('conversions', 0)}"
            )

            if cpa_pred.get('predicted_cpa') is not None:
                sections.append(
                    f"- ML Predicted CPA: ${cpa_pred['predicted_cpa']:,.0f} "
                    f"(confidence: {cpa_pred['confidence']:.0%})"
                )
            if bid_rec.get('recommended_bid') is not None:
                sections.append(
                    f"- ML Bid Recommendation: ${bid_rec['recommended_bid']:.2f} "
                    f"({bid_rec['bid_change_pct']:+.0f}% change)"
                )

        return '\n'.join(sections)

    def build_negative_keyword_context(self) -> str:
        """Build context for Negative Keyword agent."""
        search_terms = self.context.get('search_terms', [])

        sections = [
            "## Search Term Waste Analysis",
            f"Total search terms analyzed: {len(search_terms)}",
            "",
        ]

        waste_terms = []
        for st in search_terms:
            waste_pred = self.predictor.classify_search_term(st.get('text', ''), st)
            if waste_pred.get('probability', 0) > 0.4:
                waste_terms.append({
                    **st,
                    'waste_probability': waste_pred['probability'],
                })

        if waste_terms:
            waste_terms.sort(key=lambda x: x['waste_probability'], reverse=True)
            sections.append(f"### Potentially Wasteful Terms ({len(waste_terms)})")
            for wt in waste_terms[:15]:
                sections.append(
                    f"- **\"{wt.get('text')}\"**: "
                    f"Waste Prob={wt['waste_probability']:.0%}, "
                    f"Spend=${wt.get('spend', 0):,.2f}, "
                    f"Conv={wt.get('conversions', 0)}"
                )
        else:
            sections.append("No high-probability waste terms detected by ML model.")

        return '\n'.join(sections)

    def build_ad_copy_context(self) -> str:
        """Build context for Ad Copy agent."""
        sections = [
            "## Ad Copy Analysis",
            "",
            "### Current Ad Performance",
        ]

        # Ad-level data isn't in the standard context, but we can reference campaigns
        for c in self.context.get('campaigns', [])[:5]:
            sections.append(
                f"- **{c.get('name')}**: CTR={c.get('ctr', 0):.1%} (if available)"
            )

        sections.extend([
            "",
            "### ML CTR Prediction Capability",
        ])

        ctr_model = self.predictor._get_model(CTRPredictorModel)
        if ctr_model.is_trained():
            sections.append(
                f"CTR prediction model is trained (accuracy: R2={ctr_model.metrics.get('r2', 0):.3f}). "
                f"Can evaluate ad copy variations for expected CTR."
            )
        else:
            sections.append(
                "CTR prediction model not yet trained. Will use rule-based analysis."
            )

        return '\n'.join(sections)

    # ------------------------------------------------------------------
    # Unified context for any agent
    # ------------------------------------------------------------------

    def build_context_for_agent(self, agent_type: str) -> str:
        """Build context string for a specific agent type."""
        builders = {
            'strategic_director': self.build_strategic_context,
            'campaign_manager': self.build_campaign_manager_context,
            'budget_guardian': self.build_budget_guardian_context,
            'quality_score': self.build_quality_score_context,
            'keyword_optimizer': self.build_keyword_optimizer_context,
            'negative_keyword': self.build_negative_keyword_context,
            'ad_copy': self.build_ad_copy_context,
        }

        builder = builders.get(agent_type)
        if builder:
            try:
                return builder()
            except Exception as e:
                logger.error(f"Error building context for {agent_type}: {e}")
                return f"ML context unavailable: {e}"

        return "No specialized ML context for this agent type."
