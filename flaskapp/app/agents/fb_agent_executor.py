# app/agents/fb_agent_executor.py
"""
Facebook Ads execution stub.

Facebook Ads API integration is not yet implemented.
All execution calls return a not-implemented response so FB agents
can be imported without error while Google Ads agents run normally.
"""
from typing import Any, Dict


def _fb_execute_action(
    account_id: Any,
    entity_id: str,
    entity_type: str,
    action: str,
    params: Dict[str, Any] = None,
) -> Dict[str, Any]:
    """Stub — Facebook Ads API execution not yet implemented."""
    return {
        "success": False,
        "error": "Facebook Ads API execution not yet implemented",
        "entity_type": entity_type,
        "entity_id": entity_id,
        "action": action,
    }
