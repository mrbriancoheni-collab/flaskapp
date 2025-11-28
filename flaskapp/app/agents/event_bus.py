# app/agents/event_bus.py
"""
Event Bus for inter-agent communication.

Enables agents to:
- Publish events (agent decisions, discoveries, alerts)
- Subscribe to events from other agents
- Coordinate multi-agent workflows
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Callable, Any, Optional
from collections import defaultdict
import logging

logger = logging.getLogger(__name__)


@dataclass
class AgentEvent:
    """
    Represents an event in the agent system.

    Events enable asynchronous communication between agents.
    """
    # Event identification
    event_type: str  # e.g., "budget_alert", "campaign_paused", "opportunity_found"
    source_agent_id: str
    source_agent_type: str

    # Event data
    data: Dict[str, Any]

    # Context
    account_id: int
    customer_id: str

    # Metadata
    timestamp: datetime = field(default_factory=datetime.utcnow)
    event_id: Optional[str] = None
    priority: int = 5  # 1 (highest) to 10 (lowest)
    tags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            'event_id': self.event_id,
            'event_type': self.event_type,
            'source_agent_id': self.source_agent_id,
            'source_agent_type': self.source_agent_type,
            'data': self.data,
            'account_id': self.account_id,
            'customer_id': self.customer_id,
            'timestamp': self.timestamp.isoformat(),
            'priority': self.priority,
            'tags': self.tags,
        }


class EventBus:
    """
    Central event bus for agent communication.

    Implements publish-subscribe pattern for event-driven architecture.
    """

    def __init__(self):
        """Initialize the event bus."""
        # Subscribers: event_type -> [callback functions]
        self._subscribers: Dict[str, List[Callable]] = defaultdict(list)

        # Event history (in-memory, could be persisted to DB)
        self._event_history: List[AgentEvent] = []
        self._max_history = 1000  # Keep last N events

        # Statistics
        self._event_count = 0
        self._events_by_type: Dict[str, int] = defaultdict(int)

    def emit(self, event_type: str, data: Dict[str, Any], **kwargs) -> AgentEvent:
        """
        Emit an event to all subscribers.

        Args:
            event_type: Type of event (e.g., "budget_alert")
            data: Event payload
            **kwargs: Additional event metadata (priority, tags, etc.)

        Returns:
            The created AgentEvent
        """
        # Create event
        event = AgentEvent(
            event_type=event_type,
            source_agent_id=kwargs.get('source_agent_id', 'system'),
            source_agent_type=kwargs.get('source_agent_type', 'system'),
            data=data,
            account_id=kwargs.get('account_id', 0),
            customer_id=kwargs.get('customer_id', ''),
            priority=kwargs.get('priority', 5),
            tags=kwargs.get('tags', [])
        )

        # Generate event ID
        self._event_count += 1
        event.event_id = f"evt_{self._event_count}_{datetime.utcnow().timestamp()}"

        # Log event
        logger.info(
            f"Event emitted: {event_type} from {event.source_agent_id} "
            f"(account={event.account_id}, priority={event.priority})"
        )

        # Store in history
        self._event_history.append(event)
        if len(self._event_history) > self._max_history:
            self._event_history.pop(0)

        # Update statistics
        self._events_by_type[event_type] += 1

        # Notify subscribers
        subscribers = self._subscribers.get(event_type, [])
        wildcard_subscribers = self._subscribers.get('*', [])  # Subscribe to all events

        for callback in subscribers + wildcard_subscribers:
            try:
                callback(event)
            except Exception as e:
                logger.error(f"Error in event subscriber for {event_type}: {e}")

        return event

    def subscribe(self, event_type: str, callback: Callable[[AgentEvent], None]):
        """
        Subscribe to an event type.

        Args:
            event_type: Event type to listen for (use '*' for all events)
            callback: Function to call when event is emitted
        """
        self._subscribers[event_type].append(callback)
        logger.debug(f"Subscribed to event: {event_type}")

    def unsubscribe(self, event_type: str, callback: Callable[[AgentEvent], None]):
        """
        Unsubscribe from an event type.

        Args:
            event_type: Event type to stop listening for
            callback: The callback function to remove
        """
        if event_type in self._subscribers:
            self._subscribers[event_type].remove(callback)
            logger.debug(f"Unsubscribed from event: {event_type}")

    def get_recent_events(
        self,
        event_type: Optional[str] = None,
        source_agent_id: Optional[str] = None,
        limit: int = 100
    ) -> List[AgentEvent]:
        """
        Get recent events, optionally filtered.

        Args:
            event_type: Filter by event type
            source_agent_id: Filter by source agent
            limit: Maximum number of events to return

        Returns:
            List of matching events (most recent first)
        """
        events = self._event_history[::-1]  # Reverse to get newest first

        # Apply filters
        if event_type:
            events = [e for e in events if e.event_type == event_type]
        if source_agent_id:
            events = [e for e in events if e.source_agent_id == source_agent_id]

        return events[:limit]

    def get_statistics(self) -> Dict[str, Any]:
        """Get event bus statistics."""
        return {
            'total_events': self._event_count,
            'events_by_type': dict(self._events_by_type),
            'active_subscribers': {
                event_type: len(callbacks)
                for event_type, callbacks in self._subscribers.items()
            },
            'history_size': len(self._event_history),
        }

    def clear_history(self):
        """Clear event history (useful for testing)."""
        self._event_history.clear()


# Example event types used in the system
class EventTypes:
    """Standard event types for the agent system."""

    # Strategic events
    GOAL_SET = "goal_set"
    GOAL_ACHIEVED = "goal_achieved"
    GOAL_MISSED = "goal_missed"
    BUDGET_REALLOCATED = "budget_reallocated"

    # Operational events
    CAMPAIGN_PERFORMANCE_ALERT = "campaign_performance_alert"
    BUDGET_ALERT = "budget_alert"
    QUALITY_SCORE_DROP = "quality_score_drop"
    CPL_SPIKE = "cpl_spike"
    CONVERSION_RATE_DROP = "conversion_rate_drop"

    # Tactical events
    KEYWORD_ADDED = "keyword_added"
    KEYWORD_PAUSED = "keyword_paused"
    NEGATIVE_KEYWORD_ADDED = "negative_keyword_added"
    AD_CREATED = "ad_created"
    AD_PAUSED = "ad_paused"
    BID_ADJUSTED = "bid_adjusted"

    # Agent coordination events
    DECISION_MADE = "decision_made"
    DECISION_EXECUTED = "decision_executed"
    DECISION_FAILED = "decision_failed"
    AGENT_LEARNED = "agent_learned"
    DELEGATION_REQUEST = "delegation_request"  # Agent requests help from another agent
    DELEGATION_COMPLETE = "delegation_complete"

    # System events
    ANALYSIS_COMPLETE = "analysis_complete"
    OPPORTUNITY_FOUND = "opportunity_found"
    ERROR = "error"


# Example: Agent coordination workflow
"""
Example workflow showing how agents use the event bus:

1. Strategic Director detects declining ROAS:
   event_bus.emit('campaign_performance_alert', {
       'campaign_id': '12345',
       'roas': 1.2,
       'threshold': 2.0,
       'action_needed': True
   })

2. Campaign Manager subscribes to performance alerts:
   def handle_performance_alert(event):
       campaign_id = event.data['campaign_id']
       # Investigate and delegate to tactical agents
       event_bus.emit('delegation_request', {
           'target_agent': 'QualityScoreAgent',
           'task': 'diagnose_quality_score_issues',
           'campaign_id': campaign_id
       })

3. Quality Score Agent completes diagnosis:
   event_bus.emit('delegation_complete', {
       'original_event': original_event_id,
       'findings': { ... },
       'recommendations': [ ... ]
   })

4. Campaign Manager receives results and makes decisions
"""

# Global singleton instance for use across agents
_global_event_bus = EventBus()

# Alias for compatibility with existing code
# AgentEventBus can be used as a singleton instance
AgentEventBus = _global_event_bus
