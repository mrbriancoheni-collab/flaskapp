# app/social_listen/scorer.py
"""
AI-powered scorer for social listening opportunities.

score_and_filter() sends all raw items to the AI in one batch call,
asks it to score each 1-10 on relevance, engagement opportunity, and
timeliness, then returns the top 5 sorted by score.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a marketing strategist who scores social-media content for
engagement opportunity. You will receive a JSON array of posts. For each,
score it 1-10 on three criteria:
  1. relevance    – How relevant is it to marketing and demand-generation practitioners?
  2. engagement   – Does this post invite a strong, opinionated response?
  3. timeliness   – Is this discussing something current or trending right now?

Return ONLY a valid JSON array with one object per input item, in the same
order. Each object must have:
  { "index": <int>, "ai_score": <float 1-10>, "ai_reason": "<one sentence>" }

The ai_score should be the average of the three sub-scores. No markdown, no
explanation outside the JSON.
"""


def score_and_filter(
    raw_items: List[Dict],
    user_context: str = "",
) -> List[Dict]:
    """
    Score raw items with AI and return the top 5.

    Falls back gracefully if AI is unavailable.
    """
    if not raw_items:
        return []

    try:
        from app.services.ai_client import generate_json  # deferred import
        scored = _ai_score(raw_items, user_context, generate_json)
    except Exception as exc:
        logger.warning("AI scoring failed, using fallback: %s", exc)
        scored = _fallback_score(raw_items)

    scored.sort(key=lambda x: x.get("ai_score", 0), reverse=True)
    return scored[:5]


def _ai_score(
    items: List[Dict],
    user_context: str,
    generate_json: Any,
) -> List[Dict]:
    payload = [
        {
            "index": i,
            "source": item.get("source", ""),
            "topic": item.get("topic", ""),
            "content_snippet": (item.get("original_content") or "")[:500],
        }
        for i, item in enumerate(items)
    ]

    user_prompt = json.dumps(payload, ensure_ascii=False)
    if user_context:
        user_prompt = f"User context: {user_context}\n\n{user_prompt}"

    raw = generate_json(_SYSTEM_PROMPT, user_prompt)

    # generate_json may return a dict or a list; normalise to list
    if isinstance(raw, dict):
        scores = raw.get("items") or raw.get("results") or list(raw.values())
        if scores and not isinstance(scores[0], dict):
            scores = []
    elif isinstance(raw, list):
        scores = raw
    else:
        scores = []

    enriched = list(items)  # shallow copy
    for score_obj in scores:
        idx = score_obj.get("index")
        if idx is None or not (0 <= idx < len(enriched)):
            continue
        enriched[idx] = dict(enriched[idx])
        enriched[idx]["ai_score"] = float(score_obj.get("ai_score", 5.0))
        enriched[idx]["ai_reason"] = str(score_obj.get("ai_reason", ""))

    # Fill any items the AI didn't touch
    for item in enriched:
        if "ai_score" not in item:
            item["ai_score"] = 5.0
            item["ai_reason"] = "Auto-selected"

    return enriched


def _fallback_score(items: List[Dict]) -> List[Dict]:
    return [
        dict(item, ai_score=5.0, ai_reason="Auto-selected")
        for item in items
    ]
