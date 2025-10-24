from __future__ import annotations

import os
from typing import Dict, Any, List

# OpenAI SDK (reads OPENAI_API_KEY from environment)
try:
    from openai import OpenAI
    _HAS_OPENAI = True
except Exception:
    _HAS_OPENAI = False


OPTIMIZER_MODEL = os.getenv("GMB_OPTIMIZER_MODEL", "gpt-4o-mini")


def _fallback(profile: Dict[str, Any]) -> Dict[str, Any]:
    name = (profile.get("name") or "Your Business").strip()
    primary = (profile.get("primary_category") or "Local Service").strip()
    return {
        "title": f"{name} · {primary}",
        "description": (
            "Clear, keyword-rich overview of services and service areas. Add trust signals "
            "(years in business, guarantees, licensing/insurance). End with a direct call to action."
        ),
        "categories": [primary],
        "keywords": [
            "local service", "near me", "top rated", "reliable", "same day",
            "licensed", "insured", "free estimate"
        ],
    }


def ai_optimize_profile(profile: Dict[str, Any]) -> Dict[str, Any]:
    """
    Returns a dict:
      {
        "title": str,
        "description": str,
        "categories": [str,...],
        "keywords": [str,...]
      }
    """
    # If the SDK isn't available or key missing, return a safe default
    if not _HAS_OPENAI or not os.getenv("OPENAI_API_KEY"):
        return _fallback(profile)

    client = OpenAI()

    system = (
        "You are a Google Business Profile optimizer. Improve clarity, local SEO, and conversion. "
        "Respect GBP content guidelines; no false claims, no keyword stuffing."
    )
    user = f"""Return optimized fields for this Business Profile JSON:

PROFILE:
{profile}

Requirements:
- title: <= 80 chars; business name plus key differentiator if helpful.
- description: <= 750 chars; plain text; include services, geo areas, trust signals, CTA.
- categories: up to 3 suggestions total; include the primary category first when reasonable.
- keywords: 8–12 concise, lowercase phrases; no punctuation.
"""

    schema = {
        "name": "GmbOptimizerOutput",
        "schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "description": {"type": "string"},
                "categories": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
                "keywords": {"type": "array", "items": {"type": "string"}, "minItems": 8, "maxItems": 12},
            },
            "required": ["title", "description", "categories", "keywords"],
            "additionalProperties": False,
        },
        "strict": True,
    }

    try:
        resp = client.responses.create(
            model=OPTIMIZER_MODEL,
            input=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format={"type": "json_schema", "json_schema": schema},
        )
        # Parse structured output
        data = resp.output[0].content[0].parsed  # type: ignore[attr-defined]
        title = str(data["title"]).strip()
        desc = str(data["description"]).strip()
        categories: List[str] = [str(c).strip() for c in data.get("categories", [])]
        keywords: List[str] = [str(k).strip() for k in data.get("keywords", [])]
        return {
            "title": title,
            "description": desc,
            "categories": categories[:3],
            "keywords": keywords[:12],
        }
    except Exception:
        # Keep UI functional on any error
        return _fallback(profile)
