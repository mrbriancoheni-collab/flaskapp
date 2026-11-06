# app/social_listen/drafter.py
"""
AI content drafter for social listening opportunities.

draft_content() takes a scored opportunity dict and returns it augmented
with draft_comment and draft_post fields.
"""
from __future__ import annotations

import logging
import textwrap
from typing import Dict

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a B2B marketing thought leader who writes punchy, insight-driven
LinkedIn and Twitter content. You never use emojis, hashtags, or hollow
phrases like "game-changer" or "excited to share".

You will receive a JSON object describing a post. Return ONLY valid JSON
with exactly two keys:
  "draft_comment": A 2-3 sentence comment for the original post. First
      person. Adds a specific insight or a contrarian POV. Under 280 chars.
      No hashtags, no emojis.
  "draft_post": A 150-250 word standalone LinkedIn post on the same topic.
      Structure: hook sentence on its own line, blank line, three short
      insight bullets each on its own line (no bullet symbols — just newline
      separation), blank line, one CTA/question sentence. No hashtags, no
      emojis.
"""


def draft_content(item: Dict, user_context: str = "") -> Dict:
    """
    Returns item dict augmented with draft_comment and draft_post.
    Falls back to template-based drafts if AI is unavailable.
    """
    try:
        from app.services.ai_client import generate_json  # deferred import
        return _ai_draft(item, user_context, generate_json)
    except Exception as exc:
        logger.warning("AI drafting failed, using template fallback: %s", exc)
        return _template_draft(item)


def _ai_draft(item: Dict, user_context: str, generate_json) -> Dict:
    import json

    payload = {
        "source": item.get("source", ""),
        "topic": item.get("topic", ""),
        "original_content": (item.get("original_content") or "")[:800],
        "ai_reason": item.get("ai_reason", ""),
    }
    user_prompt = json.dumps(payload, ensure_ascii=False)
    if user_context:
        user_prompt = f"User context: {user_context}\n\n{user_prompt}"

    result = generate_json(_SYSTEM_PROMPT, user_prompt)

    draft_comment = ""
    draft_post = ""
    if isinstance(result, dict):
        draft_comment = str(result.get("draft_comment", "")).strip()
        draft_post = str(result.get("draft_post", "")).strip()

    if not draft_comment or not draft_post:
        fallback = _template_draft(item)
        draft_comment = draft_comment or fallback["draft_comment"]
        draft_post = draft_post or fallback["draft_post"]

    return dict(item, draft_comment=draft_comment, draft_post=draft_post)


def _template_draft(item: Dict) -> Dict:
    topic = item.get("topic", "marketing")
    snippet = (item.get("original_content") or "")[:150]
    source = item.get("source", "online")

    draft_comment = (
        f"This is an important discussion in the {topic} space. "
        f"From my experience, the practitioners who get this right focus on "
        f"fundamentals rather than tactics. Worth reading carefully."
    )[:280]

    draft_post = textwrap.dedent(f"""\
        The conversation around {topic} is shifting — and most teams are behind.

        The signal from {source} is clear: buyers care more about outcomes than features.

        Demand gen leaders who win in this environment share three traits:
        they measure pipeline quality, not just volume;
        they align content to buying stage, not personas;
        they treat sales feedback as a primary data source.

        What's the one change you've made recently that moved the needle?
    """).strip()

    return dict(item, draft_comment=draft_comment, draft_post=draft_post)
