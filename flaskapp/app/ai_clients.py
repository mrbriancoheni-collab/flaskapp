# app/ai_clients.py
import os
from typing import Optional, Dict
from openai import OpenAI
import anthropic

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-3-haiku-20240307")


def _profile_prefix(profile: Optional[Dict]) -> str:
    """Format the (optional) business profile for better prompting."""
    if not profile:
        return ""
    lines = []
    for k, v in profile.items():
        if v:
            lines.append(f"{k.replace('_',' ').title()}: {v}")
    return "Use the following business profile when helpful:\n" + "\n".join(lines) + "\n\n"


def chatgpt_response(prompt: str, profile: Optional[Dict] = None) -> str:
    """Call OpenAI Chat Completions API (OpenAI Python >= 1.x)."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return "OpenAI API key not configured."

    client = OpenAI(api_key=api_key)
    content = _profile_prefix(profile) + prompt

    try:
        resp = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "user", "content": content}],
            temperature=0.4,
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as e:
        return f"Error (OpenAI): {e}"


def claude_response(prompt: str, profile: Optional[Dict] = None) -> str:
    """Call Anthropic Messages API (latest style; no deprecated Completion)."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return "Anthropic API key not configured."

    client = anthropic.Anthropic(api_key=api_key)
    content = _profile_prefix(profile) + prompt

    try:
        resp = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=4000,
            temperature=0.4,
            messages=[{"role": "user", "content": content}],
        )
        # resp.content is a list of blocks; gather their text
        parts = []
        for block in getattr(resp, "content", []):
            text = getattr(block, "text", None)
            if text is None and isinstance(block, dict):
                text = block.get("text")
            if text:
                parts.append(text)
        return ("\n".join(parts) or str(resp)).strip()
    except Exception as e:
        return f"Error (Anthropic): {e}"
