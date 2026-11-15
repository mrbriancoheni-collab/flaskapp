import hashlib
import json
from datetime import datetime


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:64]


def _run(sql, params):
    try:
        from app import db
        from sqlalchemy import text
        with db.engine.begin() as conn:
            conn.execute(text(sql), params)
    except Exception:
        pass  # fire-and-forget; never raise


def log_event(
    event_type: str,
    *,
    account_id=None,
    user_id=None,
    session_fingerprint=None,
    event_source=None,
    tool_name=None,
    detected_trade=None,
    properties=None,
    ip=None,
    user_agent=None,
):
    _run(
        """
        INSERT INTO user_events
            (account_id, user_id, session_fingerprint, event_type,
             event_source, tool_name, detected_trade, properties,
             ip_hash, user_agent_hash, created_at)
        VALUES
            (:account_id, :user_id, :session_fingerprint, :event_type,
             :event_source, :tool_name, :detected_trade, :properties,
             :ip_hash, :user_agent_hash, NOW())
        """,
        {
            "account_id": account_id,
            "user_id": user_id,
            "session_fingerprint": session_fingerprint,
            "event_type": event_type,
            "event_source": event_source,
            "tool_name": tool_name,
            "detected_trade": detected_trade,
            "properties": json.dumps(properties) if properties else None,
            "ip_hash": _hash(ip) if ip else None,
            "user_agent_hash": _hash(user_agent) if user_agent else None,
        },
    )


def log_tool_use(
    tool_name: str,
    inputs: dict,
    *,
    outputs=None,
    account_id=None,
    session_fingerprint=None,
    detected_trade=None,
    service_area=None,
    converted: bool = False,
):
    _run(
        """
        INSERT INTO tool_usage_log
            (tool_name, account_id, session_fingerprint, detected_trade,
             service_area, inputs, outputs, converted, created_at)
        VALUES
            (:tool_name, :account_id, :session_fingerprint, :detected_trade,
             :service_area, :inputs, :outputs, :converted, NOW())
        """,
        {
            "tool_name": tool_name,
            "account_id": account_id,
            "session_fingerprint": session_fingerprint,
            "detected_trade": detected_trade,
            "service_area": service_area,
            "inputs": json.dumps(inputs),
            "outputs": json.dumps(outputs) if outputs else None,
            "converted": converted,
        },
    )


def log_chat_message(
    account_id: int,
    user_id: int,
    conversation_id: str,
    role: str,
    content: str,
    *,
    context_snapshot=None,
    model_used=None,
    tokens_input=None,
    tokens_output=None,
    latency_ms=None,
):
    _run(
        """
        INSERT INTO chat_messages
            (account_id, user_id, conversation_id, role, content,
             context_snapshot, model_used, tokens_input, tokens_output,
             latency_ms, created_at)
        VALUES
            (:account_id, :user_id, :conversation_id, :role, :content,
             :context_snapshot, :model_used, :tokens_input, :tokens_output,
             :latency_ms, NOW())
        """,
        {
            "account_id": account_id,
            "user_id": user_id,
            "conversation_id": conversation_id,
            "role": role,
            "content": content,
            "context_snapshot": json.dumps(context_snapshot) if context_snapshot else None,
            "model_used": model_used,
            "tokens_input": tokens_input,
            "tokens_output": tokens_output,
            "latency_ms": latency_ms,
        },
    )
