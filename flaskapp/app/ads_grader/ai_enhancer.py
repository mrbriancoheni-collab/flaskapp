# app/ads_grader/ai_enhancer.py
"""
AI enhancement layer for the Google Ads grader.

Takes the rule-based GoogleAdsAnalyzer output and augments it with
gpt-4o recommendations using the same google_ads_main prompt that
powers the full optimization tool. Falls back silently to rule-based
recommendations on any error so the grader always returns a result.
"""
import json
import os
import logging
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)


def enhance_report_with_ai(
    metrics: Dict[str, Any],
    analysis_results: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """
    Call gpt-4o with the grader's data and return the AI analysis.

    Args:
        metrics:          Raw account metrics (from GoogleAdsGraderClient or
                          a synthetic dict for demo mode).
        analysis_results: Output of GoogleAdsAnalyzer.analyze().

    Returns:
        AI analysis dict on success, None on any failure (caller falls back
        to rule-based recommendations).
    """
    try:
        return _call_ai(metrics, analysis_results)
    except Exception as e:
        logger.warning(f"AI enhancement failed, using rule-based fallback: {e}")
        return None


def merge_ai_recommendations(
    ai_analysis: Dict[str, Any],
    rule_based: List[Dict],
) -> List[Dict]:
    """
    Merge AI-generated recommendations into the grader's recommendation shape.

    Priority:
    1. AI top_5_recommendations (highest context, most actionable)
    2. AI recommendations array (supplementary)
    3. Rule-based recommendations as fallback if AI produced nothing

    Each item is normalised to the existing grader dict shape so templates
    don't need changes.
    """
    merged = []

    for rec in (ai_analysis.get("top_5_recommendations") or []):
        merged.append({
            "title": rec.get("title", ""),
            "description": rec.get("expected_impact", ""),
            "layman_summary": rec.get("implementation", ""),
            "category": rec.get("category", "general"),
            "severity": int(rec.get("rank", 3)),
            "roi": {},
            "effort": {},
            "action_steps": [rec.get("implementation", "")],
            "ai_generated": True,
        })

    for rec in (ai_analysis.get("recommendations") or []):
        action = rec.get("action") or {}
        merged.append({
            "title": rec.get("title", ""),
            "description": rec.get("description", ""),
            "layman_summary": rec.get("expected_impact", ""),
            "category": rec.get("category", "general"),
            "severity": int(rec.get("severity", 3)),
            "roi": {},
            "effort": {},
            "action_steps": [v for v in action.values() if v] if action else [],
            "ai_generated": True,
        })

    return merged if merged else rule_based


# ── Private helpers ──────────────────────────────────────────────────────────

def _safe_format(template: str, **kwargs) -> str:
    """
    Replace only the known {variable} placeholders without touching literal
    JSON braces in the template (avoids KeyError from str.format()).
    """
    result = template
    for key, value in kwargs.items():
        result = result.replace("{" + key + "}", str(value))
    return result


def _build_performance_summary(metrics: Dict, analysis_results: Dict) -> str:
    perf = metrics.get("performance", {})
    key = analysis_results.get("key_metrics", {})
    diag = analysis_results.get("account_diagnostics", {})

    cost = perf.get("cost", 0)
    monthly = diag.get("avg_monthly_spend", cost / 12 if cost else 0)

    return (
        f"- Monthly Spend (avg): ${monthly:,.0f}\n"
        f"- Period Total Spend: ${cost:,.0f}\n"
        f"- Period Conversions: {perf.get('conversions', 0):,.0f}\n"
        f"- Average CPA: ${perf.get('avg_cpa', 0):,.2f}\n"
        f"- Average CTR: {perf.get('ctr', 0):.2f}%\n"
        f"- Average CPC: ${perf.get('avg_cpc', 0):.2f}\n"
        f"- Quality Score (avg): {key.get('quality_score_avg', 0):.1f}/10\n"
        f"- Wasted Spend: {key.get('waste_percentage', 0):.1f}% "
        f"(${key.get('wasted_spend_90d', 0):,.0f} last 90 days)\n"
        f"- Overall Grade: {analysis_results.get('overall_grade', 'N/A')} "
        f"({analysis_results.get('overall_score', 0):.0f}/100)\n"
        f"- Section scores: "
        + ", ".join(
            f"{k.replace('_', ' ').title()} {v:.0f}"
            for k, v in (analysis_results.get("section_scores") or {}).items()
        )
    )


def _build_campaigns_data(metrics: Dict) -> str:
    campaigns = (metrics.get("campaigns") or {}).get("campaigns", [])
    return json.dumps(campaigns[:10], indent=2)


def _build_keywords_data(metrics: Dict) -> str:
    keywords = (metrics.get("keywords") or {}).get("keywords", [])
    return json.dumps(keywords[:20], indent=2)


def _call_ai(metrics: Dict, analysis_results: Dict) -> Dict:
    from flask import current_app
    from openai import OpenAI
    from app.services.ai_prompts_init import get_prompt_for_service

    api_key = current_app.config.get("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY not configured")

    prompt_config = get_prompt_for_service("google_ads_main")
    if not prompt_config:
        raise ValueError("google_ads_main prompt not found in DB")

    user_prompt = _safe_format(
        prompt_config["prompt_template"],
        performance_summary=_build_performance_summary(metrics, analysis_results),
        campaigns_data=_build_campaigns_data(metrics),
        keywords_data=_build_keywords_data(metrics),
        search_terms_data="[]",   # grader client doesn't fetch search terms
        ad_groups_data="[]",
    )

    openai_client = OpenAI(api_key=api_key)
    response = openai_client.chat.completions.create(
        model=prompt_config.get("model", "gpt-4o"),
        temperature=prompt_config.get("temperature", 0.3),
        max_tokens=prompt_config.get("max_tokens", 4000),
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": prompt_config["system_message"]},
            {"role": "user", "content": user_prompt},
        ],
        timeout=60,
    )

    return json.loads(response.choices[0].message.content)
