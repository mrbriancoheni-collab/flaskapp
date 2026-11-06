import time
from typing import Optional


SYSTEM_PROMPT = """You are a Google Ads and digital marketing assistant for a home-service contractor (trades like HVAC, plumbing, electrical, roofing, landscaping, etc.).

You help the user understand their ad performance, identify wasted spend, improve ad copy, manage budgets, and grow leads. Be concise, specific, and actionable. Avoid generic advice — tailor every recommendation to the trade and service area shown in the context.

When you don't have data, say so and suggest how to find it. Never make up numbers. Keep replies under 200 words unless the user asks for detail."""


def get_account_context(account_id: int) -> dict:
    """Return a compact dict of account info for use as chat context."""
    try:
        from app import db
        from sqlalchemy import text
        with db.engine.connect() as conn:
            row = conn.execute(
                text("""
                    SELECT a.business_name, a.detected_trade, a.detected_location,
                           a.website_url,
                           (SELECT SUM(spend) FROM google_ads_metrics
                            WHERE account_id = a.id
                              AND date >= NOW() - INTERVAL '30 days') AS monthly_spend,
                           (SELECT COUNT(*) FROM agent_decisions
                            WHERE account_id = a.id AND status = 'pending') AS pending_actions
                    FROM accounts a WHERE a.id = :aid
                """),
                {"aid": account_id},
            ).fetchone()
        if row:
            return {
                "business_name": row[0],
                "trade": row[1],
                "location": row[2],
                "website": row[3],
                "monthly_spend": float(row[4]) if row[4] else None,
                "pending_actions": row[5] or 0,
            }
    except Exception:
        pass
    return {}


def get_chat_response(
    account_id: int,
    user_id: int,
    conversation_id: str,
    user_message: str,
    history: Optional[list] = None,
) -> dict:
    """
    Send user_message to Claude Haiku with account context injected.
    Returns {"reply": str, "tokens_input": int, "tokens_output": int, "latency_ms": int}.
    """
    import anthropic
    from app.services.event_tracker import log_chat_message

    ctx = get_account_context(account_id)
    ctx_lines = []
    if ctx.get("business_name"):
        ctx_lines.append(f"Business: {ctx['business_name']}")
    if ctx.get("trade"):
        ctx_lines.append(f"Trade: {ctx['trade']}")
    if ctx.get("location"):
        ctx_lines.append(f"Service area: {ctx['location']}")
    if ctx.get("monthly_spend") is not None:
        ctx_lines.append(f"Monthly ad spend (last 30d): ${ctx['monthly_spend']:,.0f}")
    if ctx.get("pending_actions"):
        ctx_lines.append(f"Pending autopilot actions awaiting approval: {ctx['pending_actions']}")

    system = SYSTEM_PROMPT
    if ctx_lines:
        system += "\n\nAccount context:\n" + "\n".join(ctx_lines)

    messages = []
    for turn in (history or []):
        if turn.get("role") in ("user", "assistant"):
            messages.append({"role": turn["role"], "content": turn["content"]})
    messages.append({"role": "user", "content": user_message})

    t0 = time.time()
    client = anthropic.Anthropic()
    resp = client.messages.create(
        model="claude-haiku-5-5",
        max_tokens=512,
        system=system,
        messages=messages,
    )
    latency_ms = int((time.time() - t0) * 1000)

    reply = resp.content[0].text if resp.content else ""
    tokens_in = resp.usage.input_tokens
    tokens_out = resp.usage.output_tokens

    log_chat_message(
        account_id, user_id, conversation_id, "user", user_message,
        context_snapshot=ctx,
    )
    log_chat_message(
        account_id, user_id, conversation_id, "assistant", reply,
        model_used="claude-haiku-5-5",
        tokens_input=tokens_in,
        tokens_output=tokens_out,
        latency_ms=latency_ms,
    )

    return {
        "reply": reply,
        "tokens_input": tokens_in,
        "tokens_output": tokens_out,
        "latency_ms": latency_ms,
    }
