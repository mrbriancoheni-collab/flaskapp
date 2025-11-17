# app/services/auto_budget_service.py
"""
Auto-Budget Adjustment Service

Automatically adjusts campaign budgets to hit monthly targets without overspending.

Features:
- Performance-based budget distribution (high ROAS campaigns get more)
- Seasonality integration (HVAC AC gets 2.5x in July)
- Overspend prevention (projects monthly spend and reduces if needed)
- User notifications for all changes
- Full audit trail
"""

from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
from decimal import Decimal
import logging

logger = logging.getLogger(__name__)


class AutoBudgetService:
    """Service for automatic budget adjustments."""

    def __init__(self, db_connection):
        """
        Initialize the service.

        Args:
            db_connection: Database connection object
        """
        self.db = db_connection

    def get_settings(self, account_id: int, customer_id: str) -> Optional[Dict[str, Any]]:
        """
        Get auto-budget settings for an account.

        Args:
            account_id: Account ID
            customer_id: Google Ads customer ID

        Returns:
            Settings dict or None if not configured
        """
        cursor = self.db.cursor(dictionary=True)
        cursor.execute("""
            SELECT * FROM auto_budget_settings
            WHERE account_id = %s AND customer_id = %s
        """, (account_id, customer_id))

        settings = cursor.fetchone()
        cursor.close()
        return settings

    def save_settings(self, account_id: int, customer_id: str, settings: Dict[str, Any]) -> bool:
        """
        Save or update auto-budget settings.

        Args:
            account_id: Account ID
            customer_id: Google Ads customer ID
            settings: Settings to save

        Returns:
            True if successful
        """
        cursor = self.db.cursor()

        try:
            cursor.execute("""
                INSERT INTO auto_budget_settings (
                    account_id, customer_id, enabled, monthly_budget_target,
                    min_daily_budget, max_daily_budget, adjustment_frequency,
                    performance_weight, seasonality_weight, capacity_weight,
                    send_notifications
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    enabled = VALUES(enabled),
                    monthly_budget_target = VALUES(monthly_budget_target),
                    min_daily_budget = VALUES(min_daily_budget),
                    max_daily_budget = VALUES(max_daily_budget),
                    adjustment_frequency = VALUES(adjustment_frequency),
                    performance_weight = VALUES(performance_weight),
                    seasonality_weight = VALUES(seasonality_weight),
                    capacity_weight = VALUES(capacity_weight),
                    send_notifications = VALUES(send_notifications),
                    updated_at = CURRENT_TIMESTAMP
            """, (
                account_id,
                customer_id,
                settings.get('enabled', False),
                settings.get('monthly_budget_target', 0),
                settings.get('min_daily_budget', 10),
                settings.get('max_daily_budget', 1000),
                settings.get('adjustment_frequency', 'daily'),
                settings.get('performance_weight', 0.70),
                settings.get('seasonality_weight', 0.20),
                settings.get('capacity_weight', 0.10),
                settings.get('send_notifications', True)
            ))

            self.db.commit()
            cursor.close()
            return True

        except Exception as e:
            logger.error(f"Error saving auto-budget settings: {e}")
            self.db.rollback()
            cursor.close()
            return False

    def calculate_budget_adjustments(
        self,
        account_id: int,
        customer_id: str,
        campaigns: List[Dict[str, Any]],
        seasonality_data: Optional[Dict[str, float]] = None,
        capacity_utilization: Optional[float] = None
    ) -> List[Dict[str, Any]]:
        """
        Calculate recommended budget adjustments for all campaigns.

        Args:
            account_id: Account ID
            customer_id: Google Ads customer ID
            campaigns: List of campaign performance data
            seasonality_data: Optional seasonality multipliers by campaign
            capacity_utilization: Optional capacity utilization (0-100)

        Returns:
            List of recommended adjustments
        """
        settings = self.get_settings(account_id, customer_id)
        if not settings or not settings.get('enabled'):
            return []

        monthly_target = float(settings['monthly_budget_target'])
        perf_weight = float(settings['performance_weight'])
        season_weight = float(settings['seasonality_weight'])
        capacity_weight = float(settings['capacity_weight'])

        # Calculate month progress
        now = datetime.now()
        days_in_month = 30  # Simplified
        current_day = now.day
        days_remaining = days_in_month - current_day
        elapsed_pct = current_day / days_in_month

        # Calculate total spend so far this month
        total_spend_mtd = sum(c.get('spend_mtd', 0) for c in campaigns)

        # Project end-of-month spend if we continue at current pace
        total_daily_avg = sum(c.get('daily_spend_avg_7d', 0) for c in campaigns)
        projected_total_spend = total_spend_mtd + (total_daily_avg * days_remaining)

        # Remaining budget to allocate
        remaining_budget = monthly_target - total_spend_mtd

        if remaining_budget <= 0:
            # Already over budget - reduce all campaigns proportionally
            return self._create_reduction_plan(campaigns, settings)

        # Score each campaign for budget allocation
        scored_campaigns = []
        for campaign in campaigns:
            score = self._calculate_campaign_score(
                campaign,
                perf_weight,
                season_weight,
                capacity_weight,
                seasonality_data,
                capacity_utilization
            )
            scored_campaigns.append({
                'campaign': campaign,
                'score': score
            })

        # Sort by score (highest first)
        scored_campaigns.sort(key=lambda x: x['score'], reverse=True)

        # Calculate total score
        total_score = sum(sc['score'] for sc in scored_campaigns)

        if total_score == 0:
            return []

        # Allocate remaining budget based on scores
        adjustments = []
        for sc in scored_campaigns:
            campaign = sc['campaign']
            score = sc['score']

            # Calculate this campaign's share of remaining budget
            budget_share = (score / total_score) * remaining_budget

            # Convert to daily budget
            recommended_daily = budget_share / days_remaining if days_remaining > 0 else 0

            # Apply min/max constraints
            recommended_daily = max(float(settings['min_daily_budget']),
                                   min(float(settings['max_daily_budget']), recommended_daily))

            current_daily = campaign.get('daily_budget', 0)

            if abs(recommended_daily - current_daily) > 5:  # Only adjust if >$5 difference
                change_pct = ((recommended_daily - current_daily) / current_daily * 100) if current_daily > 0 else 0

                adjustments.append({
                    'campaign_id': campaign['id'],
                    'campaign_name': campaign.get('name', ''),
                    'current_daily_budget': current_daily,
                    'recommended_daily_budget': recommended_daily,
                    'change_amount': recommended_daily - current_daily,
                    'change_pct': change_pct,
                    'reason': self._get_adjustment_reason(campaign, score, projected_total_spend, monthly_target),
                    'score': score
                })

        return adjustments

    def _calculate_campaign_score(
        self,
        campaign: Dict[str, Any],
        perf_weight: float,
        season_weight: float,
        capacity_weight: float,
        seasonality_data: Optional[Dict[str, float]],
        capacity_utilization: Optional[float]
    ) -> float:
        """Calculate a weighted score for budget allocation."""

        # Performance component (ROAS and conversion rate)
        roas = campaign.get('roas_7d', 0)
        conv_rate = campaign.get('conversion_rate_7d', 0)
        performance_score = (roas * 0.7) + (conv_rate * 0.3)  # Weighted

        # Seasonality component
        campaign_id = campaign.get('id', '')
        seasonality_multiplier = 1.0
        if seasonality_data and campaign_id in seasonality_data:
            seasonality_multiplier = seasonality_data[campaign_id]

        # Capacity component
        capacity_multiplier = 1.0
        if capacity_utilization is not None:
            if capacity_utilization >= 90:
                capacity_multiplier = 0.3  # Reduce budget if near full capacity
            elif capacity_utilization >= 80:
                capacity_multiplier = 0.7
            elif capacity_utilization < 50:
                capacity_multiplier = 1.3  # Increase if low capacity

        # Weighted final score
        final_score = (
            (performance_score * perf_weight) +
            (seasonality_multiplier * season_weight) +
            (capacity_multiplier * capacity_weight)
        )

        return max(0, final_score)  # Never negative

    def _create_reduction_plan(
        self,
        campaigns: List[Dict[str, Any]],
        settings: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Create a plan to reduce budgets when over target."""

        adjustments = []

        for campaign in campaigns:
            current_daily = campaign.get('daily_budget', 0)
            roas = campaign.get('roas_7d', 0)

            # Reduce more for low-performing campaigns
            if roas < 1.0:
                reduction_pct = 40  # Reduce by 40%
            elif roas < 2.0:
                reduction_pct = 25  # Reduce by 25%
            else:
                reduction_pct = 10  # Reduce by 10% even for good performers

            new_daily = current_daily * (1 - reduction_pct / 100)
            new_daily = max(float(settings['min_daily_budget']), new_daily)

            adjustments.append({
                'campaign_id': campaign['id'],
                'campaign_name': campaign.get('name', ''),
                'current_daily_budget': current_daily,
                'recommended_daily_budget': new_daily,
                'change_amount': new_daily - current_daily,
                'change_pct': -reduction_pct,
                'reason': f"Overspend prevention: Reduce budget {reduction_pct}% (ROAS: {roas:.2f}x)",
                'score': 0
            })

        return adjustments

    def _get_adjustment_reason(
        self,
        campaign: Dict[str, Any],
        score: float,
        projected_spend: float,
        target_spend: float
    ) -> str:
        """Generate a human-readable reason for the adjustment."""

        roas = campaign.get('roas_7d', 0)
        conv_rate = campaign.get('conversion_rate_7d', 0)

        reasons = []

        if roas > 3.0:
            reasons.append(f"High ROAS ({roas:.2f}x)")
        elif roas < 1.0:
            reasons.append(f"Low ROAS ({roas:.2f}x)")

        if conv_rate > 5.0:
            reasons.append(f"Strong conv rate ({conv_rate:.1f}%)")

        if projected_spend > target_spend:
            reasons.append("Preventing overspend")

        if not reasons:
            reasons.append(f"Score: {score:.2f}")

        return "; ".join(reasons)

    def log_budget_change(
        self,
        account_id: int,
        customer_id: str,
        campaign_id: str,
        campaign_name: str,
        change_type: str,
        old_budget: float,
        new_budget: float,
        reason: str,
        triggered_by: str = 'auto',
        agent_id: Optional[str] = None,
        confidence_score: Optional[float] = None
    ) -> bool:
        """
        Log a budget change to the audit trail.

        Args:
            account_id: Account ID
            customer_id: Google Ads customer ID
            campaign_id: Campaign ID
            campaign_name: Campaign name
            change_type: Type of change (increase, decrease, etc)
            old_budget: Previous budget
            new_budget: New budget
            reason: Why the change was made
            triggered_by: Who/what triggered it
            agent_id: Optional agent that made the decision
            confidence_score: Optional confidence score

        Returns:
            True if successful
        """
        cursor = self.db.cursor()

        try:
            change_amount = new_budget - old_budget
            change_pct = (change_amount / old_budget * 100) if old_budget > 0 else 0

            cursor.execute("""
                INSERT INTO budget_change_log (
                    account_id, customer_id, campaign_id, campaign_name,
                    change_type, old_budget, new_budget, change_amount,
                    change_pct, reason, triggered_by, agent_id, confidence_score
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                account_id, customer_id, campaign_id, campaign_name,
                change_type, old_budget, new_budget, change_amount,
                change_pct, reason, triggered_by, agent_id, confidence_score
            ))

            self.db.commit()
            cursor.close()
            return True

        except Exception as e:
            logger.error(f"Error logging budget change: {e}")
            self.db.rollback()
            cursor.close()
            return False

    def get_budget_change_history(
        self,
        account_id: int,
        customer_id: str,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Get recent budget change history.

        Args:
            account_id: Account ID
            customer_id: Google Ads customer ID
            limit: Max number of records

        Returns:
            List of budget changes
        """
        cursor = self.db.cursor(dictionary=True)
        cursor.execute("""
            SELECT * FROM budget_change_log
            WHERE account_id = %s AND customer_id = %s
            ORDER BY created_at DESC
            LIMIT %s
        """, (account_id, customer_id, limit))

        changes = cursor.fetchall()
        cursor.close()
        return changes

    def create_notification(
        self,
        account_id: int,
        user_id: Optional[int],
        notification_type: str,
        severity: str,
        title: str,
        message: str,
        action_url: Optional[str] = None,
        related_entity_type: Optional[str] = None,
        related_entity_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Create a user notification.

        Args:
            account_id: Account ID
            user_id: User ID (can be None for account-level)
            notification_type: Type of notification
            severity: info, warning, or critical
            title: Notification title
            message: Notification message
            action_url: Optional URL to take action
            related_entity_type: Optional entity type (campaign, etc)
            related_entity_id: Optional entity ID
            metadata: Optional additional data as JSON

        Returns:
            True if successful
        """
        cursor = self.db.cursor()

        try:
            import json
            metadata_json = json.dumps(metadata) if metadata else None

            cursor.execute("""
                INSERT INTO user_notifications (
                    account_id, user_id, notification_type, severity,
                    title, message, action_url, related_entity_type,
                    related_entity_id, metadata
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                account_id, user_id, notification_type, severity,
                title, message, action_url, related_entity_type,
                related_entity_id, metadata_json
            ))

            self.db.commit()
            cursor.close()
            return True

        except Exception as e:
            logger.error(f"Error creating notification: {e}")
            self.db.rollback()
            cursor.close()
            return False

    def get_notifications(
        self,
        account_id: int,
        user_id: Optional[int] = None,
        unread_only: bool = False,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Get notifications for an account/user.

        Args:
            account_id: Account ID
            user_id: Optional user ID filter
            unread_only: Only return unread notifications
            limit: Max number of records

        Returns:
            List of notifications
        """
        cursor = self.db.cursor(dictionary=True)

        query = """
            SELECT * FROM user_notifications
            WHERE account_id = %s
        """
        params = [account_id]

        if user_id is not None:
            query += " AND (user_id = %s OR user_id IS NULL)"
            params.append(user_id)

        if unread_only:
            query += " AND is_read = FALSE AND is_dismissed = FALSE"

        query += " ORDER BY created_at DESC LIMIT %s"
        params.append(limit)

        cursor.execute(query, params)
        notifications = cursor.fetchall()
        cursor.close()

        # Parse JSON metadata
        import json
        for notif in notifications:
            if notif.get('metadata'):
                try:
                    notif['metadata'] = json.loads(notif['metadata'])
                except:
                    notif['metadata'] = None

        return notifications
