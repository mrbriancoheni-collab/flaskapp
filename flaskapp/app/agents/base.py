# app/agents/base.py
"""
Base Agent classes and interfaces for the multi-agent system.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from datetime import datetime
from enum import Enum


class AgentCapability(Enum):
    """Capabilities that an agent can have."""
    STRATEGIC_PLANNING = "strategic_planning"
    BUDGET_MANAGEMENT = "budget_management"
    BID_OPTIMIZATION = "bid_optimization"
    KEYWORD_MANAGEMENT = "keyword_management"
    AD_CREATION = "ad_creation"
    QUALITY_SCORE_OPTIMIZATION = "quality_score_optimization"
    PERFORMANCE_MONITORING = "performance_monitoring"
    AUTONOMOUS_EXECUTION = "autonomous_execution"


class DecisionRiskLevel(Enum):
    """Risk level of a decision."""
    LOW = "low"  # Auto-execute (e.g., add negative keyword for "free")
    MEDIUM = "medium"  # Suggest but don't execute (e.g., bid adjustment)
    HIGH = "high"  # Always require approval (e.g., budget change)
    CRITICAL = "critical"  # Require approval + confirmation (e.g., pause campaign)


@dataclass
class AgentDecision:
    """
    Represents a decision made by an agent.

    This is the core output of agent reasoning - what action to take,
    why, expected impact, and whether it requires approval.
    """
    # Identification
    agent_id: str
    agent_type: str
    decision_type: str  # e.g., "add_negative_keyword", "adjust_bid", "pause_campaign"

    # Decision details
    title: str
    description: str
    reasoning: str  # Why this decision was made

    # Target
    account_id: int
    customer_id: str
    campaign_id: Optional[str] = None
    ad_group_id: Optional[str] = None

    # Action details
    action_data: Dict[str, Any] = field(default_factory=dict)  # Specific params for execution

    # Risk & Approval
    risk_level: DecisionRiskLevel = DecisionRiskLevel.MEDIUM
    requires_approval: bool = True
    confidence: float = 0.5  # 0.0-1.0, how confident the agent is

    # Expected Impact
    expected_monthly_savings: Optional[float] = None
    expected_monthly_leads: Optional[int] = None
    expected_improvement_pct: Optional[float] = None

    # Timeline
    created_at: datetime = field(default_factory=datetime.utcnow)
    execute_after: Optional[datetime] = None  # Scheduled execution
    expires_at: Optional[datetime] = None  # Decision expires if not acted on

    # Status
    status: str = "pending"  # pending, approved, rejected, executed, failed
    executed_at: Optional[datetime] = None
    execution_result: Optional[Dict[str, Any]] = None

    # Learning
    predicted_outcome: Optional[Dict[str, float]] = None
    actual_outcome: Optional[Dict[str, float]] = None
    prediction_accuracy: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage/serialization."""
        return {
            'agent_id': self.agent_id,
            'agent_type': self.agent_type,
            'decision_type': self.decision_type,
            'title': self.title,
            'description': self.description,
            'reasoning': self.reasoning,
            'account_id': self.account_id,
            'customer_id': self.customer_id,
            'campaign_id': self.campaign_id,
            'ad_group_id': self.ad_group_id,
            'action_data': self.action_data,
            'risk_level': self.risk_level.value,
            'requires_approval': self.requires_approval,
            'confidence': self.confidence,
            'expected_monthly_savings': self.expected_monthly_savings,
            'expected_monthly_leads': self.expected_monthly_leads,
            'expected_improvement_pct': self.expected_improvement_pct,
            'created_at': self.created_at.isoformat(),
            'execute_after': self.execute_after.isoformat() if self.execute_after else None,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'status': self.status,
            'executed_at': self.executed_at.isoformat() if self.executed_at else None,
            'execution_result': self.execution_result,
            'predicted_outcome': self.predicted_outcome,
            'actual_outcome': self.actual_outcome,
            'prediction_accuracy': self.prediction_accuracy,
        }


class BaseAgent(ABC):
    """
    Abstract base class for all AI agents.

    All agents must implement:
    - analyze(): Observe the environment and identify opportunities
    - decide(): Make decisions about what actions to take
    - execute(): Carry out approved decisions
    - learn(): Update models based on outcomes
    """

    def __init__(
        self,
        agent_id: str,
        capabilities: List[AgentCapability],
        auto_execute_threshold: float = 0.95,
        event_bus: Optional[Any] = None,
        decision_log: Optional[Any] = None,
    ):
        """
        Initialize agent.

        Args:
            agent_id: Unique identifier for this agent instance
            capabilities: List of capabilities this agent has
            auto_execute_threshold: Confidence threshold for auto-execution
            event_bus: Event bus for inter-agent communication
            decision_log: Decision log for tracking all decisions
        """
        self.agent_id = agent_id
        self.agent_type = self.__class__.__name__
        self.capabilities = capabilities
        self.auto_execute_threshold = auto_execute_threshold
        self.event_bus = event_bus
        self.decision_log = decision_log

        # Learning
        self.confidence_model = {}  # Track prediction accuracy per decision type
        self.last_analysis_time = None

    @abstractmethod
    def analyze(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Analyze the current state and identify opportunities.

        Args:
            context: Environment context (account data, performance metrics, etc.)

        Returns:
            List of identified opportunities/issues
        """
        pass

    @abstractmethod
    def decide(self, opportunities: List[Dict[str, Any]]) -> List[AgentDecision]:
        """
        Make decisions based on identified opportunities.

        Args:
            opportunities: List of opportunities from analyze()

        Returns:
            List of decisions to take
        """
        pass

    def execute(self, decision: AgentDecision, google_ads_client: Any) -> Dict[str, Any]:
        """
        Execute an approved decision.

        Args:
            decision: The decision to execute
            google_ads_client: Google Ads API client

        Returns:
            Execution result with status and details
        """
        # Default implementation - subclasses can override
        if decision.status != "approved":
            return {
                'success': False,
                'error': f'Decision not approved (status: {decision.status})'
            }

        try:
            # Call subclass-specific execution
            result = self._execute_impl(decision, google_ads_client)

            # Update decision
            decision.status = "executed"
            decision.executed_at = datetime.utcnow()
            decision.execution_result = result

            # Log to decision log
            if self.decision_log:
                self.decision_log.log_execution(decision, result)

            # Emit event
            if self.event_bus:
                self.event_bus.emit('decision_executed', {
                    'agent_id': self.agent_id,
                    'decision': decision.to_dict(),
                    'result': result
                })

            return result

        except Exception as e:
            error_result = {
                'success': False,
                'error': str(e)
            }
            decision.status = "failed"
            decision.execution_result = error_result

            if self.decision_log:
                self.decision_log.log_execution(decision, error_result)

            return error_result

    @abstractmethod
    def _execute_impl(self, decision: AgentDecision, google_ads_client: Any) -> Dict[str, Any]:
        """
        Subclass-specific execution logic.

        Must be implemented by each agent type.
        """
        pass

    def learn(self, decision: AgentDecision, actual_outcome: Dict[str, float]):
        """
        Update confidence model based on actual outcome.

        Args:
            decision: The decision that was executed
            actual_outcome: The actual results (e.g., {'cpl_reduction': 15.2})
        """
        if not decision.predicted_outcome:
            return

        # Calculate prediction accuracy
        accuracy = self._calculate_prediction_accuracy(
            decision.predicted_outcome,
            actual_outcome
        )

        # Update decision with actual outcome
        decision.actual_outcome = actual_outcome
        decision.prediction_accuracy = accuracy

        # Update confidence model for this decision type
        decision_type = decision.decision_type
        if decision_type not in self.confidence_model:
            self.confidence_model[decision_type] = {
                'predictions': [],
                'avg_accuracy': 0.0,
                'count': 0
            }

        model = self.confidence_model[decision_type]
        model['predictions'].append(accuracy)
        model['count'] += 1
        model['avg_accuracy'] = sum(model['predictions']) / model['count']

        # Adjust auto-execute threshold if accuracy is consistently low
        if model['count'] >= 5 and model['avg_accuracy'] < 0.7:
            self.auto_execute_threshold = min(0.99, self.auto_execute_threshold + 0.05)

        # Log learning
        if self.decision_log:
            self.decision_log.log_learning(decision, actual_outcome, accuracy)

        # Emit event
        if self.event_bus:
            self.event_bus.emit('agent_learned', {
                'agent_id': self.agent_id,
                'decision_type': decision_type,
                'accuracy': accuracy,
                'avg_accuracy': model['avg_accuracy']
            })

    def _calculate_prediction_accuracy(
        self,
        predicted: Dict[str, float],
        actual: Dict[str, float]
    ) -> float:
        """Calculate how accurate predictions were (0.0-1.0)."""
        if not predicted or not actual:
            return 0.0

        # Compare each metric
        accuracies = []
        for key in predicted:
            if key in actual:
                pred_val = predicted[key]
                actual_val = actual[key]

                if pred_val == 0 and actual_val == 0:
                    accuracies.append(1.0)
                elif pred_val == 0 or actual_val == 0:
                    accuracies.append(0.0)
                else:
                    # Calculate % difference
                    diff = abs(pred_val - actual_val) / max(pred_val, actual_val)
                    accuracy = max(0.0, 1.0 - diff)
                    accuracies.append(accuracy)

        return sum(accuracies) / len(accuracies) if accuracies else 0.0

    def should_auto_execute(self, decision: AgentDecision) -> bool:
        """
        Determine if a decision should be auto-executed.

        Criteria:
        - Risk level is LOW
        - Confidence exceeds threshold
        - Agent has autonomous execution capability
        """
        return (
            decision.risk_level == DecisionRiskLevel.LOW and
            decision.confidence >= self.auto_execute_threshold and
            AgentCapability.AUTONOMOUS_EXECUTION in self.capabilities
        )

    def run_cycle(self, context: Dict[str, Any], google_ads_client: Any) -> Dict[str, Any]:
        """
        Run a complete agent cycle: Analyze → Decide → Execute (if approved).

        This is the main entry point for agent operation.
        """
        cycle_start = datetime.utcnow()

        # 1. Analyze
        opportunities = self.analyze(context)

        # 2. Decide
        decisions = self.decide(opportunities)

        # 3. Auto-execute low-risk decisions
        auto_executed = []
        pending_approval = []

        for decision in decisions:
            # Log decision
            if self.decision_log:
                self.decision_log.log_decision(decision)

            # Auto-execute or queue for approval
            if self.should_auto_execute(decision):
                decision.status = "approved"
                result = self.execute(decision, google_ads_client)
                auto_executed.append({
                    'decision': decision.to_dict(),
                    'result': result
                })
            else:
                pending_approval.append(decision.to_dict())

        cycle_duration = (datetime.utcnow() - cycle_start).total_seconds()

        return {
            'agent_id': self.agent_id,
            'agent_type': self.agent_type,
            'cycle_start': cycle_start.isoformat(),
            'cycle_duration_seconds': cycle_duration,
            'opportunities_found': len(opportunities),
            'decisions_made': len(decisions),
            'auto_executed': auto_executed,
            'pending_approval': pending_approval,
        }
