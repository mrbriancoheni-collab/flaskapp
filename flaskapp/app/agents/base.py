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
    LANDING_PAGE_OPTIMIZATION = "landing_page_optimization"


class DecisionRiskLevel(Enum):
    """Risk level of a decision."""
    LOW = "low"    # Auto-execute immediately (e.g., add negative keyword, small bid adjustment)
    HIGH = "high"  # Always require manual approval (e.g., budget changes, campaign creation)


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

    # Optional fields (must come after required fields)
    id: Optional[int] = None  # Database ID (set after log_decision)
    campaign_id: Optional[str] = None
    ad_group_id: Optional[str] = None

    # Action details
    action_data: Dict[str, Any] = field(default_factory=dict)  # Specific params for execution

    # Risk & Approval
    risk_level: DecisionRiskLevel = DecisionRiskLevel.HIGH
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
            'risk_level': self.risk_level.value if hasattr(self.risk_level, 'value') else str(self.risk_level),
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
        auto_execute_threshold: float = 0.80,
        event_bus: Optional[Any] = None,
        decision_log: Optional[Any] = None,
        account_id: Optional[int] = None,
        autonomy_level: int = 2,
    ):
        """
        Initialize agent.

        Args:
            agent_id: Unique identifier for this agent instance
            capabilities: List of capabilities this agent has
            auto_execute_threshold: Confidence threshold for auto-execution
            event_bus: Event bus for inter-agent communication
            decision_log: Decision log for tracking all decisions
            account_id: Account ID for loading account-specific configuration
        """
        self.agent_id = agent_id
        self.agent_type = self.__class__.__name__
        self.capabilities = capabilities
        self.auto_execute_threshold = auto_execute_threshold
        self.event_bus = event_bus
        self.decision_log = decision_log
        self.account_id = account_id
        self.autonomy_level = autonomy_level  # 1=Assistive, 2=Semi-Auto, 3=Fully Autonomous

        # Load configuration from database (global or account-specific)
        self.config = self._load_configuration(account_id)

        # Apply configuration overrides
        if not self.config.get('enabled', True):
            # Agent is disabled for this account
            pass  # Could raise exception or just skip analysis

        if 'auto_execute_threshold' in self.config:
            self.auto_execute_threshold = self.config['auto_execute_threshold']

        self.custom_prompt = self.config.get('custom_prompt')
        self.risk_overrides = self.config.get('risk_overrides', {})
        self.business_rules = self.config.get('business_rules', [])

        # Learning
        self.confidence_model = {}  # Track prediction accuracy per decision type
        self.last_analysis_time = None

    def _load_configuration(self, account_id: Optional[int] = None) -> Dict[str, Any]:
        """
        Load agent configuration from database.

        Tries account-specific first, falls back to global defaults.
        """
        try:
            from app.admin.agent_config_routes import get_agent_configuration
            return get_agent_configuration(self.agent_id, account_id)
        except Exception:
            # If loading fails, return defaults
            return {
                'enabled': True,
                'auto_execute_threshold': self.auto_execute_threshold,
                'custom_prompt': None,
                'risk_overrides': {},
                'business_rules': []
            }

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

    def apply_configuration_to_decision(self, decision: AgentDecision, context: Dict[str, Any] = None) -> AgentDecision:
        """
        Apply agent configuration to a decision (risk overrides, business rules).

        This should be called by subclasses after creating a decision.
        """
        # Apply risk level override
        if decision.decision_type in self.risk_overrides:
            override_risk = self.risk_overrides[decision.decision_type]
            # Map legacy medium/critical values to high for backward compatibility
            if override_risk in ('medium', 'critical'):
                override_risk = 'high'
            try:
                decision.risk_level = DecisionRiskLevel(override_risk)
            except ValueError:
                decision.risk_level = DecisionRiskLevel.HIGH

            # Update requires_approval based on risk level
            if decision.risk_level == DecisionRiskLevel.LOW:
                decision.requires_approval = False
            else:
                decision.requires_approval = True

        # Apply business rules
        if context:
            for rule in self.business_rules:
                if self._evaluate_business_rule(rule, context, decision):
                    action = rule.get('then', '')

                    if action == 'require_approval':
                        decision.requires_approval = True
                    elif action == 'auto_execute':
                        decision.requires_approval = False
                    elif action.startswith('set_risk_'):
                        risk_level = action.replace('set_risk_', '')
                        decision.risk_level = DecisionRiskLevel(risk_level)

        return decision

    def _evaluate_business_rule(self, rule: Dict, context: Dict[str, Any], decision: AgentDecision) -> bool:
        """Evaluate if a business rule applies to this context/decision."""
        condition = rule.get('if', '')

        if not condition:
            return False

        try:
            import ast
            import operator as _op

            eval_context = {
                **context,
                'decision_type': decision.decision_type,
                'confidence': decision.confidence,
                'expected_savings': decision.expected_monthly_savings or 0,
            }

            _BINOPS = {
                ast.Add: _op.add, ast.Sub: _op.sub,
                ast.Mult: _op.mul, ast.Div: _op.truediv,
            }
            _CMPOPS = {
                ast.Lt: _op.lt, ast.LtE: _op.le,
                ast.Gt: _op.gt, ast.GtE: _op.ge,
                ast.Eq: _op.eq, ast.NotEq: _op.ne,
            }

            def _eval(node):
                if isinstance(node, ast.Constant):
                    return node.value
                if isinstance(node, ast.Name):
                    if node.id not in eval_context:
                        raise ValueError(f"Unknown variable: {node.id}")
                    return eval_context[node.id]
                if isinstance(node, ast.BoolOp):
                    if isinstance(node.op, ast.And):
                        return all(_eval(v) for v in node.values)
                    return any(_eval(v) for v in node.values)
                if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
                    return not _eval(node.operand)
                if isinstance(node, ast.BinOp):
                    fn = _BINOPS.get(type(node.op))
                    if fn:
                        return fn(_eval(node.left), _eval(node.right))
                if isinstance(node, ast.Compare):
                    left = _eval(node.left)
                    for op, comp in zip(node.ops, node.comparators):
                        fn = _CMPOPS.get(type(op))
                        if not fn:
                            raise ValueError(f"Unsupported op: {op}")
                        if not fn(left, _eval(comp)):
                            return False
                        left = _eval(comp)
                    return True
                raise ValueError(f"Unsupported node: {type(node).__name__}")

            expr = condition.replace(" AND ", " and ").replace(" OR ", " or ")
            tree = ast.parse(expr, mode='eval')
            return bool(_eval(tree.body))

        except Exception:
            return False

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
        Determine if a decision should be auto-executed based on autonomy_level.

        L1 — Assistive:        Never auto-execute; everything goes to approval queue.
        L2 — Semi-Auto:        Auto-execute LOW risk only (default behavior).
        L3 — Fully Autonomous: Auto-execute LOW risk normally; also auto-execute HIGH
                               risk if confidence >= 0.92 (stricter threshold).
        """
        if self.autonomy_level == 1:
            return False

        if AgentCapability.AUTONOMOUS_EXECUTION not in self.capabilities:
            return False

        risk = decision.risk_level
        is_low_risk = (
            risk == DecisionRiskLevel.LOW
            or (isinstance(risk, str) and risk.lower() == 'low')
            or (hasattr(risk, 'value') and risk.value == 'low')
        )
        is_high_risk = (
            risk == DecisionRiskLevel.HIGH
            or (isinstance(risk, str) and risk.lower() == 'high')
            or (hasattr(risk, 'value') and risk.value == 'high')
        )

        if is_low_risk:
            return decision.confidence >= self.auto_execute_threshold

        # Level 3: also auto-execute high-risk actions with elevated confidence
        if self.autonomy_level == 3 and is_high_risk:
            return decision.confidence >= 0.92

        return False

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

        # 2b. Fill in account_id/customer_id from context on every decision
        ctx_account_id = context.get('account_id', 0)
        ctx_customer_id = context.get('customer_id', '')
        for decision in decisions:
            if not decision.account_id or decision.account_id == 0:
                decision.account_id = ctx_account_id
            if not decision.customer_id:
                decision.customer_id = str(ctx_customer_id)

        # 3. Auto-execute low-risk decisions
        auto_executed = []
        pending_approval = []

        # --- Safety gate: check for spend anomaly once per cycle ---
        # If anomaly detected, cap this cycle at L2 (no high-risk auto-execution)
        _effective_autonomy = self.autonomy_level
        if self.autonomy_level == 3:
            try:
                from app.services.safety_layer import check_anomaly_gate
                anomaly, anomaly_msg = check_anomaly_gate(context.get('account_id', 0))
                if anomaly:
                    _effective_autonomy = 2
                    import logging as _log
                    _log.getLogger(__name__).warning(
                        "Anomaly gate activated for account %s — downgrading to L2 for this cycle: %s",
                        context.get('account_id'), anomaly_msg,
                    )
            except Exception:
                pass  # never let safety checks block execution

        for decision in decisions:
            # Log decision
            if self.decision_log:
                self.decision_log.log_decision(decision)

            # --- Cooldown check ---
            _blocked = False
            try:
                from app.services.safety_layer import is_in_cooldown
                _blocked, _reason = is_in_cooldown(context.get('account_id', 0), decision)
                if _blocked:
                    import logging as _log
                    _log.getLogger(__name__).info("Cooldown blocked: %s", _reason)
                    decision.status = "skipped_cooldown"
            except Exception:
                pass  # never let safety checks block execution

            if _blocked:
                continue

            # Auto-execute or queue for approval (using effective autonomy level)
            _original_level = self.autonomy_level
            self.autonomy_level = _effective_autonomy
            should_exec = self.should_auto_execute(decision)
            self.autonomy_level = _original_level

            if should_exec:
                decision.status = "approved"
                result = self.execute(decision, google_ads_client)

                # Update status based on execution result
                if result.get('success'):
                    decision.status = "executed"
                    decision.executed_at = datetime.utcnow()
                    decision.execution_result = result
                else:
                    decision.status = "execution_failed"
                    decision.execution_result = result

                # Update database with execution result
                if self.decision_log:
                    self.decision_log.log_execution(decision, result)

                # Create AIAction record for transparency on AI Change Log page
                if result.get('success'):
                    self._create_ai_action_record(decision, result)

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

    def _create_ai_action_record(self, decision: AgentDecision, result: Dict[str, Any]) -> None:
        """
        Create an AIAction record for transparency on the AI Change Log page.

        This bridges the agent_decisions table with the ai_actions table that
        the AI Change Log page uses for displaying executed actions.
        """
        try:
            from app.models_ai_actions import AIAction
            from app import db

            # Map decision_type to AIAction action_type
            action_type_map = {
                'add_negative_keyword': 'negative_keyword_added',
                'pause_keyword': 'keyword_paused',
                'adjust_keyword_bid': 'bid_adjusted',
                'adjust_campaign_bids': 'bid_adjusted',
                'adjust_daily_budget': 'budget_adjusted',
                'pause_campaign': 'campaign_paused',
                'scale_campaign_budget': 'budget_adjusted',
                'reallocate_budget': 'budget_reallocated',
                'add_keyword': 'keyword_added',
                'pause_ad': 'ad_paused',
            }

            action_type = action_type_map.get(decision.decision_type, decision.decision_type)

            # Create the AIAction record
            ai_action = AIAction(
                account_id=decision.account_id,
                action_type=action_type,
                title=decision.title,
                description=decision.description,
                campaign_id=decision.campaign_id,
                ad_group_id=decision.ad_group_id,
                before_value=decision.action_data,
                after_value=result,
                estimated_monthly_savings=decision.expected_monthly_savings,
                confidence_score=decision.confidence,
                reasoning=decision.reasoning,
                data_used={
                    'agent_id': decision.agent_id,
                    'agent_type': decision.agent_type,
                    'risk_level': decision.risk_level.value if hasattr(decision.risk_level, 'value') else str(decision.risk_level),
                },
                status='executed',
                executed_by='ai_agent',
            )

            db.session.add(ai_action)
            db.session.commit()

        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Failed to create AIAction record: {e}")
