# app/services/ai_client.py
"""
Unified AI client — Anthropic (Claude) primary, OpenAI fallback.

Usage
-----
from app.services.ai_client import generate_text, generate_json

# Returns parsed dict (JSON mode)
result = generate_json(system_prompt, user_prompt)

# Returns raw string
text = generate_text(system_prompt, user_prompt)

Provider selection
------------------
- Uses Anthropic if ANTHROPIC_API_KEY is set in env/config.
- Falls back to OpenAI if OPENAI_API_KEY is set.
- Raises RuntimeError if neither key is available.

Prompt caching
--------------
When using Anthropic, the system prompt is marked with cache_control
so repeated calls with the same system prompt hit the cache tier.
This is particularly valuable for the Google Ads insights prompt which
is the same across many accounts.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)

# Default models
ANTHROPIC_MODEL = "claude-sonnet-4-6"
OPENAI_MODEL_DEFAULT = "gpt-4o-mini"


def _get_anthropic_key() -> Optional[str]:
    try:
        from flask import current_app
        key = current_app.config.get("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_API_KEY")
    except RuntimeError:
        key = os.getenv("ANTHROPIC_API_KEY")
    return (key or "").strip() or None


def _get_openai_key() -> Optional[str]:
    try:
        from flask import current_app
        key = current_app.config.get("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
    except RuntimeError:
        key = os.getenv("OPENAI_API_KEY")
    return (key or "").strip() or None


def _call_anthropic(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 2000,
    temperature: float = 0.3,
    json_mode: bool = False,
) -> str:
    """Call Anthropic Claude with prompt caching on the system prompt."""
    import anthropic

    api_key = _get_anthropic_key()
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not configured")

    client = anthropic.Anthropic(api_key=api_key)

    # Append JSON instruction to user prompt when needed
    full_user = user_prompt
    if json_mode:
        full_user = user_prompt.rstrip() + "\n\nRespond ONLY with valid JSON — no markdown, no explanation."

    response = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=max_tokens,
        system=[
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},  # prompt caching
            }
        ],
        messages=[{"role": "user", "content": full_user}],
    )

    return response.content[0].text


def _call_openai(
    system_prompt: str,
    user_prompt: str,
    model: str = OPENAI_MODEL_DEFAULT,
    max_tokens: int = 2000,
    temperature: float = 0.3,
    json_mode: bool = False,
) -> str:
    """Call OpenAI (fallback)."""
    from openai import OpenAI

    api_key = _get_openai_key()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not configured")

    client = OpenAI(api_key=api_key)

    kwargs: Dict[str, Any] = dict(
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        timeout=30,
    )
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    response = client.chat.completions.create(**kwargs)
    return response.choices[0].message.content or ""


def generate_text(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 2000,
    temperature: float = 0.3,
    prefer_provider: Optional[str] = None,
) -> str:
    """
    Generate a text response using the best available AI provider.

    prefer_provider: 'anthropic' | 'openai' | None (auto-select)
    """
    use_anthropic = (prefer_provider == "anthropic") or (
        prefer_provider is None and bool(_get_anthropic_key())
    )

    if use_anthropic:
        try:
            return _call_anthropic(system_prompt, user_prompt, max_tokens, temperature)
        except Exception as exc:
            log.warning("Anthropic call failed, falling back to OpenAI: %s", exc)

    return _call_openai(system_prompt, user_prompt,
                        max_tokens=max_tokens, temperature=temperature)


def generate_json(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 2000,
    temperature: float = 0.3,
    prefer_provider: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Generate a JSON response. Parses and returns a dict.
    Raises ValueError if the response cannot be parsed as JSON.
    """
    use_anthropic = (prefer_provider == "anthropic") or (
        prefer_provider is None and bool(_get_anthropic_key())
    )

    raw = ""
    if use_anthropic:
        try:
            raw = _call_anthropic(system_prompt, user_prompt, max_tokens, temperature,
                                  json_mode=True)
        except Exception as exc:
            log.warning("Anthropic call failed, falling back to OpenAI: %s", exc)
            raw = ""

    if not raw:
        raw = _call_openai(system_prompt, user_prompt,
                           max_tokens=max_tokens, temperature=temperature,
                           json_mode=True)

    # Strip markdown fences if present
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    if text.endswith("```"):
        text = text[:-3].strip()

    return json.loads(text)


def active_provider() -> str:
    """Return which provider will be used ('anthropic' or 'openai')."""
    return "anthropic" if _get_anthropic_key() else "openai"
