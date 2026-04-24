# app/agents/decision_log.py
"""
Decision Log for tracking all agent decisions and outcomes.

Provides:
- Audit trail of all agent decisions
- Learning data for improving agent performance
- Transparency into what agents are doing
- Analytics on agent effectiveness
"""

import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from collections import defaultdict
from sqlalchemy import text
from app import db
import logging

logger = logging.getLogger(__name__)


class DecisionLog:
    """
    Centralized log for all agent decisions.

    Tracks:
    - What decisions agents made
    - When they were made
    - Why they were made
    - What the predicted impact was
    - What the actual impact was
    - Whether predictions were accurate
    """

    def __init__(self, session=None):
        """
        Initialize decision log.

        Args:
            session: Database session (defaults to main db.session)
        """
        self.session = session or db.session

        # In-memory cache for recent decisions
        self._recent_decisions: List[Dict[str, Any]] = []
        self._max_cache_size = 100

    def log_decision(self, decision: 'AgentDecision') -> int:
        """
        Log a new decision to the database.

        Args:
            decision: The agent decision to log

        Returns:
            Decision ID in database
        """
        try:
            # Deduplication: skip if a pending decision with the same signature already exists.
            # Match on title (not just decision_type) so different agents can't duplicate the
            # same recommendation, and also deduplicate within the same agent_type.
            dedup_check = text("""
                SELECT id FROM agent_decisions
                WHERE account_id = :account_id
                  AND title = :title
                  AND (campaign_id = :campaign_id OR (campaign_id IS NULL AND :campaign_id IS NULL))
                  AND status = 'pending'
                LIMIT 1
            """)
            existing = self.session.execute(dedup_check, {
                'account_id': decision.account_id,
                'title': decision.title,
                'campaign_id': decision.campaign_id,
            }).fetchone()

            if existing:
                existing_id = existing[0]
                logger.info(
                    f"Skipping duplicate decision: {decision.decision_type} by {decision.agent_id} "
                    f"(existing ID: {existing_id})"
                )
                decision.id = existing_id
                return existing_id

            # Insert into database
            query = text("""
                INSERT INTO agent_decisions (
                    agent_id,
                    agent_type,
                    decision_type,
                    title,
                    description,
                    reasoning,
                    account_id,
                    customer_id,
                    campaign_id,
                    ad_group_id,
                    action_data,
                    risk_level,
                    requires_approval,
                    confidence,
                    expected_monthly_savings,
                    expected_monthly_leads,
                    expected_improvement_pct,
                    status,
                    created_at
                )
                VALUES (
                    :agent_id,
                    :agent_type,
                    :decision_type,
                    :title,
                    :description,
                    :reasoning,
                    :account_id,
                    :customer_id,
                    :campaign_id,
                    :ad_group_id,
                    :action_data,
                    :risk_level,
                    :requires_approval,
                    :confidence,
                    :expected_monthly_savings,
                    :expected_monthly_leads,
                    :expected_improvement_pct,
                    :status,
                    :created_at
                )
            """)

            self.session.execute(query, {
                'agent_id': decision.agent_id,
                'agent_type': decision.agent_type,
                'decision_type': decision.decision_type,
                'title': decision.title,
                'description': decision.description,
                'reasoning': decision.reasoning,
                'account_id': decision.account_id,
                'customer_id': decision.customer_id,
                'campaign_id': decision.campaign_id,
                'ad_group_id': decision.ad_group_id,
                'action_data': json.dumps(decision.action_data) if isinstance(decision.action_data, (dict, list)) else str(decision.action_data),
                'risk_level': decision.risk_level.value if hasattr(decision.risk_level, 'value') else str(decision.risk_level),
                'requires_approval': decision.requires_approval,
                'confidence': decision.confidence,
                'expected_monthly_savings': decision.expected_monthly_savings,
                'expected_monthly_leads': decision.expected_monthly_leads,
                'expected_improvement_pct': decision.expected_improvement_pct,
                'status': decision.status,
                'created_at': decision.created_at,
            })

            # Get the auto-generated ID (MariaDB/MySQL)
            result = self.session.execute(text("SELECT LAST_INSERT_ID()"))
            decision_id = result.scalar()
            self.session.commit()

            # Add to cache
            self._recent_decisions.append(decision.to_dict())
            if len(self._recent_decisions) > self._max_cache_size:
                self._recent_decisions.pop(0)

            logger.info(f"Logged decision: {decision.decision_type} by {decision.agent_id} (ID: {decision_id})")

            # Store the ID on the decision object for later updates
            decision.id = decision_id

            return decision_id

        except Exception as e:
            logger.error(f"Failed to log decision: {e}")
            self.session.rollback()
            raise

    def log_execution(self, decision: 'AgentDecision', result: Dict[str, Any]):
        """
        Log the execution result of a decision.

        Args:
            decision: The decision that was executed
            result: Execution result
        """
        try:
            # Prefer ID-based update if available (more reliable)
            if hasattr(decision, 'id') and decision.id:
                query = text("""
                    UPDATE agent_decisions
                    SET
                        status = :status,
                        executed_at = :executed_at,
                        execution_result = :execution_result
                    WHERE id = :id
                """)
                params = {
                    'id': decision.id,
                    'status': decision.status,
                    'executed_at': decision.executed_at,
                    'execution_result': json.dumps(result) if isinstance(result, (dict, list)) else str(result),
                }
            else:
                # Fallback to matching on agent_id + decision_type + account_id
                query = text("""
                    UPDATE agent_decisions
                    SET
                        status = :status,
                        executed_at = :executed_at,
                        execution_result = :execution_result
                    WHERE
                        agent_id = :agent_id
                        AND decision_type = :decision_type
                        AND account_id = :account_id
                        AND status IN ('pending', 'approved')
                    ORDER BY created_at DESC
                    LIMIT 1
                """)
                params = {
                    'status': decision.status,
                    'executed_at': decision.executed_at,
                    'execution_result': json.dumps(result) if isinstance(result, (dict, list)) else str(result),
                    'agent_id': decision.agent_id,
                    'decision_type': decision.decision_type,
                    'account_id': decision.account_id,
                }

            self.session.execute(query, params)
            self.session.commit()

            logger.info(
                f"Logged execution: {decision.decision_type} by {decision.agent_id} "
                f"(status: {decision.status})"
            )

        except Exception as e:
            logger.error(f"Failed to log execution: {e}")
            self.session.rollback()

    def log_learning(
        self,
        decision: 'AgentDecision',
        actual_outcome: Dict[str, float],
        accuracy: float
    ):
        """
        Log learning outcomes (predicted vs actual).

        Args:
            decision: The decision that was executed
            actual_outcome: Actual measured outcomes
            accuracy: Prediction accuracy (0.0-1.0)
        """
        try:
            query = text("""
                UPDATE agent_decisions
                SET
                    predicted_outcome = :predicted_outcome,
                    actual_outcome = :actual_outcome,
                    prediction_accuracy = :prediction_accuracy
                WHERE
                    agent_id = :agent_id
                    AND decision_type = :decision_type
                    AND created_at = :created_at
            """)

            self.session.execute(query, {
                'predicted_outcome': json.dumps(decision.predicted_outcome) if isinstance(decision.predicted_outcome, (dict, list)) else str(decision.predicted_outcome),
                'actual_outcome': json.dumps(actual_outcome) if isinstance(actual_outcome, (dict, list)) else str(actual_outcome),
                'prediction_accuracy': accuracy,
                'agent_id': decision.agent_id,
                'decision_type': decision.decision_type,
                'created_at': decision.created_at,
            })

            self.session.commit()

            logger.info(
                f"Logged learning: {decision.decision_type} by {decision.agent_id} "
                f"(accuracy: {accuracy:.2%})"
            )

        except Exception as e:
            logger.error(f"Failed to log learning: {e}")
            self.session.rollback()

    def get_decisions_for_approval(
        self,
        account_id: int,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Get decisions pending approval for an account.

        Args:
            account_id: Account ID
            limit: Maximum number to return

        Returns:
            List of pending decisions
        """
        try:
            query = text("""
                SELECT *
                FROM agent_decisions
                WHERE account_id = :account_id
                  AND status = 'pending'
                  AND requires_approval = TRUE
                ORDER BY
                  risk_level DESC,
                  expected_monthly_savings DESC NULLS LAST,
                  created_at DESC
                LIMIT :limit
            """)

            result = self.session.execute(query, {
                'account_id': account_id,
                'limit': limit
            })

            return [dict(row) for row in result.mappings()]

        except Exception as e:
            logger.error(f"Failed to get decisions for approval: {e}")
            return []

    def get_agent_performance(
        self,
        agent_id: str,
        days: int = 30
    ) -> Dict[str, Any]:
        """
        Get performance metrics for an agent.

        Args:
            agent_id: Agent ID
            days: Look back period in days

        Returns:
            Performance statistics
        """
        try:
            since = datetime.utcnow() - timedelta(days=days)

            query = text("""
                SELECT
                    COUNT(*) as total_decisions,
                    COUNT(CASE WHEN status = 'executed' THEN 1 END) as executed_count,
                    COUNT(CASE WHEN status = 'approved' THEN 1 END) as approved_count,
                    COUNT(CASE WHEN status = 'rejected' THEN 1 END) as rejected_count,
                    COUNT(CASE WHEN status = 'failed' THEN 1 END) as failed_count,
                    AVG(confidence) as avg_confidence,
                    AVG(prediction_accuracy) as avg_accuracy,
                    SUM(expected_monthly_savings) as total_expected_savings,
                    SUM(expected_monthly_leads) as total_expected_leads,
                    COUNT(DISTINCT decision_type) as unique_decision_types
                FROM agent_decisions
                WHERE agent_id = :agent_id
                  AND created_at >= :since
            """)

            result = self.session.execute(query, {
                'agent_id': agent_id,
                'since': since
            }).mappings().first()

            if not result:
                return {}

            return dict(result)

        except Exception as e:
            logger.error(f"Failed to get agent performance: {e}")
            return {}

    def get_system_statistics(self, days: int = 30) -> Dict[str, Any]:
        """
        Get system-wide agent statistics.

        Args:
            days: Look back period in days

        Returns:
            System statistics
        """
        try:
            since = datetime.utcnow() - timedelta(days=days)

            query = text("""
                SELECT
                    COUNT(*) as total_decisions,
                    COUNT(DISTINCT agent_id) as active_agents,
                    COUNT(CASE WHEN status = 'executed' THEN 1 END) as auto_executed,
                    COUNT(CASE WHEN requires_approval = TRUE THEN 1 END) as required_approval,
                    SUM(expected_monthly_savings) as total_expected_savings,
                    SUM(expected_monthly_leads) as total_expected_leads,
                    AVG(prediction_accuracy) as system_avg_accuracy
                FROM agent_decisions
                WHERE created_at >= :since
            """)

            result = self.session.execute(query, {
                'since': since
            }).mappings().first()

            if not result:
                return {}

            stats = dict(result)

            # Get breakdown by agent type
            agent_breakdown_query = text("""
                SELECT
                    agent_type,
                    COUNT(*) as decisions,
                    AVG(confidence) as avg_confidence,
                    AVG(prediction_accuracy) as avg_accuracy
                FROM agent_decisions
                WHERE created_at >= :since
                GROUP BY agent_type
                ORDER BY decisions DESC
            """)

            agent_breakdown = self.session.execute(agent_breakdown_query, {
                'since': since
            }).mappings().all()

            stats['by_agent_type'] = [dict(row) for row in agent_breakdown]

            return stats

        except Exception as e:
            logger.error(f"Failed to get system statistics: {e}")
            return {}

    def get_learning_insights(self, decision_type: str) -> Dict[str, Any]:
        """
        Get learning insights for a specific decision type.

        Helps answer: "How good are we at predicting outcomes for this type of decision?"

        Args:
            decision_type: Type of decision to analyze

        Returns:
            Learning insights
        """
        try:
            query = text("""
                SELECT
                    COUNT(*) as total_predictions,
                    AVG(prediction_accuracy) as avg_accuracy,
                    STDDEV(prediction_accuracy) as accuracy_stddev,
                    MIN(prediction_accuracy) as worst_prediction,
                    MAX(prediction_accuracy) as best_prediction,
                    AVG(confidence) as avg_confidence,
                    CORR(confidence, prediction_accuracy) as confidence_accuracy_correlation
                FROM agent_decisions
                WHERE decision_type = :decision_type
                  AND prediction_accuracy IS NOT NULL
            """)

            result = self.session.execute(query, {
                'decision_type': decision_type
            }).mappings().first()

            if not result:
                return {}

            insights = dict(result)

            # Recommendation based on accuracy
            avg_accuracy = insights.get('avg_accuracy', 0)
            if avg_accuracy >= 0.8:
                insights['recommendation'] = "High accuracy - safe to increase auto-execution threshold"
            elif avg_accuracy >= 0.6:
                insights['recommendation'] = "Moderate accuracy - continue monitoring"
            else:
                insights['recommendation'] = "Low accuracy - reduce auto-execution or improve model"

            return insights

        except Exception as e:
            logger.error(f"Failed to get learning insights: {e}")
            return {}
