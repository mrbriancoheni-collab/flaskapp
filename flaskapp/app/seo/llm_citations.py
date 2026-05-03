# app/seo/llm_citations.py
"""
LLM Citation Tracker (GEO — Generative Engine Optimization).

Fires a set of queries at Claude and checks whether the brand / domain
appears in the responses. Returns per-query results plus an overall
visibility score and content recommendations.
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse


def _brand_patterns(brand: str, domain: str) -> List[re.Pattern]:
    """Return compiled patterns to detect brand/domain mentions."""
    patterns = []
    if brand:
        escaped = re.escape(brand.strip())
        patterns.append(re.compile(escaped, re.IGNORECASE))
    if domain:
        host = urlparse(domain).netloc or domain
        host = host.lstrip("www.").lower()
        patterns.append(re.compile(re.escape(host), re.IGNORECASE))
    return patterns


def _check_mention(text: str, patterns: List[re.Pattern]) -> bool:
    return any(p.search(text) for p in patterns)


def _extract_snippet(text: str, patterns: List[re.Pattern], window: int = 120) -> Optional[str]:
    for p in patterns:
        m = p.search(text)
        if m:
            start = max(0, m.start() - window // 2)
            end = min(len(text), m.end() + window // 2)
            return "…" + text[start:end].strip() + "…"
    return None


def run_citation_check(
    brand: str,
    domain: str,
    queries: List[str],
    industry: str = "",
) -> Dict[str, Any]:
    """
    Fires each query at Claude Haiku acting as a neutral information assistant,
    then checks if the brand/domain is mentioned.

    Returns:
        results: per-query dicts with {query, cited, snippet, response_excerpt}
        score:   0-100 citation visibility score
        recommendations: list of content gap recommendations
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return {"error": "ANTHROPIC_API_KEY not configured."}

    import anthropic
    client = anthropic.Anthropic(api_key=api_key)

    patterns = _brand_patterns(brand, domain)
    if not patterns:
        return {"error": "Provide a brand name or domain to check."}

    queries = [q.strip() for q in queries if q.strip()][:10]
    if not queries:
        return {"error": "No queries provided."}

    results: List[Dict] = []
    cited_count = 0

    system_prompt = (
        "You are a helpful, neutral information assistant. "
        "Answer the user's question factually and concisely, mentioning specific "
        "companies, tools, services, or websites that are genuinely relevant and "
        "well-known in the space. Be specific — name real brands."
    )

    for query in queries:
        try:
            msg = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=400,
                system=system_prompt,
                messages=[{"role": "user", "content": query}],
            )
            response_text = msg.content[0].text if msg.content else ""
            cited = _check_mention(response_text, patterns)
            snippet = _extract_snippet(response_text, patterns) if cited else None
            if cited:
                cited_count += 1

            results.append({
                "query": query,
                "cited": cited,
                "snippet": snippet,
                "response_preview": response_text[:300] + ("…" if len(response_text) > 300 else ""),
            })
        except Exception as exc:
            results.append({
                "query": query,
                "cited": False,
                "snippet": None,
                "response_preview": None,
                "error": str(exc)[:100],
            })

    score = round(cited_count / len(results) * 100) if results else 0

    # Generate recommendations via Claude
    recommendations: List[str] = []
    uncited_queries = [r["query"] for r in results if not r["cited"]]
    if uncited_queries:
        try:
            industry_ctx = f" in the {industry} industry" if industry else ""
            rec_prompt = (
                f"A brand called '{brand}' ({domain}) was NOT mentioned by an AI assistant "
                f"when asked these queries{industry_ctx}:\n"
                + "\n".join(f"- {q}" for q in uncited_queries[:5])
                + "\n\nSuggest 3 specific content pieces (blog posts, landing pages, or guides) "
                "they should create to increase the chance of being cited by AI systems "
                "like ChatGPT, Gemini, and Claude. Be concrete — give title suggestions."
                " Reply with a numbered list only."
            )
            rec_msg = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=300,
                messages=[{"role": "user", "content": rec_prompt}],
            )
            rec_text = rec_msg.content[0].text if rec_msg.content else ""
            recommendations = [
                line.lstrip("0123456789. ").strip()
                for line in rec_text.splitlines()
                if line.strip() and line.strip()[0].isdigit()
            ]
        except Exception:
            pass

    return {
        "brand": brand,
        "domain": domain,
        "results": results,
        "score": score,
        "cited_count": cited_count,
        "total_queries": len(results),
        "recommendations": recommendations,
    }
