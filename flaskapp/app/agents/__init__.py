# app/agents/__init__.py
"""
Multi-Agent AI System for Google Ads Optimization

Architecture:
- Strategic Layer: Long-term planning and goal-setting
- Operational Layer: Daily management and coordination
- Tactical Layer: Specific optimizations and execution
- Performance Max Layer: Performance Max campaign-specific optimization

Communication:
- Event Bus: Async messaging between agents
- Decision Log: Track all agent decisions and outcomes
"""

from .base import BaseAgent, AgentDecision, AgentCapability
from .event_bus import EventBus, AgentEvent
from .decision_log import DecisionLog
from .strategic import StrategicDirectorAgent
from .operational import CampaignManagerAgent, BudgetGuardianAgent, QualityScoreAgent
from .tactical import KeywordOptimizerAgent, AdCopyAgent, NegativeKeywordAgent, LandingPageAnalystAgent
from .pmax_agents import AssetPerformanceAgent, AudienceSignalAgent, PMaxCampaignStructureAgent

__all__ = [
    # Base
    'BaseAgent',
    'AgentDecision',
    'AgentCapability',
    # Infrastructure
    'EventBus',
    'AgentEvent',
    'DecisionLog',
    # Strategic Layer
    'StrategicDirectorAgent',
    # Operational Layer
    'CampaignManagerAgent',
    'BudgetGuardianAgent',
    'QualityScoreAgent',
    # Tactical Layer
    'KeywordOptimizerAgent',
    'AdCopyAgent',
    'NegativeKeywordAgent',
    'LandingPageAnalystAgent',
    # Performance Max Layer
    'AssetPerformanceAgent',
    'AudienceSignalAgent',
    'PMaxCampaignStructureAgent',
]
