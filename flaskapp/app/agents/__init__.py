# app/agents/__init__.py
"""
Multi-Agent AI System for Ads Optimization (Google Ads & Facebook Ads)

Architecture:
- Strategic Layer: Long-term planning and goal-setting
- Operational Layer: Daily management and coordination
- Tactical Layer: Specific optimizations and execution
- Performance Max Layer: Performance Max campaign-specific optimization (Google)
- Facebook Ads Layer: Facebook/Instagram/Meta ads optimization

Communication:
- Event Bus: Async messaging between agents
- Decision Log: Track all agent decisions and outcomes
"""

from .base import BaseAgent, AgentDecision, AgentCapability
from .event_bus import EventBus, AgentEvent
from .decision_log import DecisionLog

# Google Ads Agents
from .strategic import StrategicDirectorAgent
from .account_structure_agent import AccountStructureAgent
from .operational import CampaignManagerAgent, BudgetGuardianAgent, QualityScoreAgent
from .tactical import KeywordOptimizerAgent, AdCopyAgent, NegativeKeywordAgent, LandingPageAnalystAgent
from .pmax_agents import AssetPerformanceAgent, AudienceSignalAgent, PMaxCampaignStructureAgent

# Facebook Ads Agents
from .fbads_strategic import FBStrategicDirectorAgent, FBAccountStructureAgent
from .fbads_operational import FBCampaignManagerAgent, FBBudgetGuardianAgent, FBCreativeAnalystAgent
from .fbads_tactical import (
    FBAudienceOptimizerAgent,
    FBPlacementOptimizerAgent,
    FBBidOptimizerAgent,
    FBCreativeOptimizerAgent,
)

__all__ = [
    # Base
    'BaseAgent',
    'AgentDecision',
    'AgentCapability',
    # Infrastructure
    'EventBus',
    'AgentEvent',
    'DecisionLog',
    # Google Ads - Strategic Layer
    'StrategicDirectorAgent',
    'AccountStructureAgent',
    # Google Ads - Operational Layer
    'CampaignManagerAgent',
    'BudgetGuardianAgent',
    'QualityScoreAgent',
    # Google Ads - Tactical Layer
    'KeywordOptimizerAgent',
    'AdCopyAgent',
    'NegativeKeywordAgent',
    'LandingPageAnalystAgent',
    # Google Ads - Performance Max Layer
    'AssetPerformanceAgent',
    'AudienceSignalAgent',
    'PMaxCampaignStructureAgent',
    # Facebook Ads - Strategic Layer
    'FBStrategicDirectorAgent',
    'FBAccountStructureAgent',
    # Facebook Ads - Operational Layer
    'FBCampaignManagerAgent',
    'FBBudgetGuardianAgent',
    'FBCreativeAnalystAgent',
    # Facebook Ads - Tactical Layer
    'FBAudienceOptimizerAgent',
    'FBPlacementOptimizerAgent',
    'FBBidOptimizerAgent',
    'FBCreativeOptimizerAgent',
]
