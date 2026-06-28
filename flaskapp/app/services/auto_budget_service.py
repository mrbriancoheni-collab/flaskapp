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

    def calculate_budget_adjustments_for_group(
        self,
        account_id: int,
        customer_id: str,
        budget_group: Dict[str, Any],
        group_campaigns: List[Dict[str, Any]],
        seasonality_data: Optional[Dict[str, float]] = None,
        capacity_utilization: Optional[float] = None
    ) -> List[Dict[str, Any]]:
        """
        Calculate recommended budget adjustments for a specific budget group.

        Args:
            account_id: Account ID
            customer_id: Google Ads customer ID
            budget_group: Budget group settings dict
            group_campaigns: List of campaigns in this group
            seasonality_data: Optional seasonality multipliers by campaign
            capacity_utilization: Optional capacity utilization (0-100)

        Returns:
            List of recommended adjustments
        """
        if not budget_group.get('enabled'):
            return []

        monthly_target = float(budget_group['monthly_budget_target'])
        perf_weight = float(budget_group.get('performance_weight', 0.70))
        season_weight = float(budget_group.get('seasonality_weight', 0.20))
        capacity_weight = float(budget_group.get('capacity_weight', 0.10))

        # Calculate month progress
        now = datetime.now()
        days_in_month = 30  # Simplified
        current_day = now.day
        days_remaining = days_in_month - current_day
        elapsed_pct = current_day / days_in_month

        # Calculate total spend so far this month for this group
        total_spend_mtd = sum(c.get('spend_mtd', 0) for c in group_campaigns)

        # Project end-of-month spend if we continue at current pace
        total_daily_avg = sum(c.get('daily_spend_avg_7d', 0) for c in group_campaigns)
        projected_total_spend = total_spend_mtd + (total_daily_avg * days_remaining)

        # Remaining budget to allocate
        remaining_budget = monthly_target - total_spend_mtd

        if remaining_budget <= 0:
            # Already over budget - reduce all campaigns proportionally
            return self._create_reduction_plan_for_group(
                group_campaigns,
                budget_group
            )

        # Score each campaign for budget allocation
        scored_campaigns = []
        for campaign in group_campaigns:
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
            min_daily = float(budget_group.get('min_daily_budget', 10))
            max_daily = float(budget_group.get('max_daily_budget', 1000))
            recommended_daily = max(min_daily, min(max_daily, recommended_daily))

            current_daily = campaign.get('daily_budget', 0)

            if abs(recommended_daily - current_daily) > 5:  # Only adjust if >$5 difference
                change_pct = ((recommended_daily - current_daily) / current_daily * 100) if current_daily > 0 else 0

                adjustments.append({
                    'budget_group_id': budget_group['id'],
                    'budget_group_name': budget_group['name'],
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

    def _create_reduction_plan_for_group(
        self,
        campaigns: List[Dict[str, Any]],
        budget_group: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Create a plan to reduce budgets for a specific budget group when over target."""

        adjustments = []
        min_daily = float(budget_group.get('min_daily_budget', 10))

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
            new_daily = max(min_daily, new_daily)

            adjustments.append({
                'budget_group_id': budget_group['id'],
                'budget_group_name': budget_group['name'],
                'campaign_id': campaign['id'],
                'campaign_name': campaign.get('name', ''),
                'current_daily_budget': current_daily,
                'recommended_daily_budget': new_daily,
                'change_amount': new_daily - current_daily,
                'change_pct': -reduction_pct,
                'reason': f"Overspend prevention for {budget_group['name']}: Reduce budget {reduction_pct}% (ROAS: {roas:.2f}x)",
                'score': 0
            })

        return adjustments

    # ============================================
    # SAFEGUARD ENFORCEMENT METHODS
    # ============================================

    def _get_weekly_budget_change(
        self,
        account_id: int,
        customer_id: str,
        campaign_id: str
    ) -> Dict[str, Any]:
        """
        Get total budget changes for the current week.

        Returns:
            Dict with starting_budget, current_budget, total_change_pct
        """
        from datetime import date, timedelta

        # Calculate current week (Monday-Sunday)
        today = date.today()
        week_start = today - timedelta(days=today.weekday())  # Monday
        week_end = week_start + timedelta(days=6)  # Sunday

        cursor = self.db.cursor(dictionary=True)
        cursor.execute("""
            SELECT * FROM budget_weekly_changes
            WHERE account_id = %s AND customer_id = %s
            AND campaign_id = %s AND week_start_date = %s
        """, (account_id, customer_id, campaign_id, week_start))

        result = cursor.fetchone()
        cursor.close()

        if result:
            return {
                'starting_budget': float(result['starting_budget']),
                'current_budget': float(result['current_budget']),
                'total_change_pct': float(result['total_change_pct']),
                'num_changes': result['num_changes']
            }
        else:
            return {
                'starting_budget': 0,
                'current_budget': 0,
                'total_change_pct': 0,
                'num_changes': 0
            }

    def _update_weekly_budget_tracking(
        self,
        account_id: int,
        customer_id: str,
        campaign_id: str,
        old_budget: float,
        new_budget: float
    ) -> bool:
        """Update weekly budget change tracking."""
        from datetime import date, timedelta

        today = date.today()
        week_start = today - timedelta(days=today.weekday())
        week_end = week_start + timedelta(days=6)

        cursor = self.db.cursor(dictionary=True)

        try:
            # Get existing record or create new
            cursor.execute("""
                SELECT * FROM budget_weekly_changes
                WHERE account_id = %s AND customer_id = %s
                AND campaign_id = %s AND week_start_date = %s
            """, (account_id, customer_id, campaign_id, week_start))

            existing = cursor.fetchone()

            if existing:
                # Update existing record
                starting_budget = float(existing['starting_budget'])
                total_change_pct = ((new_budget - starting_budget) / starting_budget * 100) if starting_budget > 0 else 0

                cursor.execute("""
                    UPDATE budget_weekly_changes
                    SET current_budget = %s,
                        total_change_amount = %s,
                        total_change_pct = %s,
                        num_changes = num_changes + 1
                    WHERE id = %s
                """, (new_budget, new_budget - starting_budget, total_change_pct, existing['id']))
            else:
                # Create new record
                cursor.execute("""
                    INSERT INTO budget_weekly_changes (
                        account_id, customer_id, campaign_id, week_start_date, week_end_date,
                        starting_budget, current_budget, total_change_amount, total_change_pct, num_changes
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    account_id, customer_id, campaign_id, week_start, week_end,
                    old_budget, new_budget, new_budget - old_budget,
                    ((new_budget - old_budget) / old_budget * 100) if old_budget > 0 else 0, 1
                ))

            self.db.commit()
            cursor.close()
            return True

        except Exception as e:
            logger.error(f"Error updating weekly budget tracking: {e}")
            self.db.rollback()
            cursor.close()
            return False

    def _check_change_limits(
        self,
        account_id: int,
        customer_id: str,
        campaign_id: str,
        current_budget: float,
        proposed_budget: float,
        settings: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Check if proposed change exceeds daily/weekly limits.

        Returns:
            Dict with 'allowed', 'reason', 'capped_budget', 'exceeds_daily', 'exceeds_weekly'
        """
        if current_budget <= 0:
            return {
                'allowed': True,
                'reason': 'Current budget is 0',
                'capped_budget': proposed_budget,
                'exceeds_daily': False,
                'exceeds_weekly': False
            }

        change_pct = abs((proposed_budget - current_budget) / current_budget * 100)
        max_daily_pct = float(settings.get('max_daily_change_pct', 20))
        max_weekly_pct = float(settings.get('max_weekly_change_pct', 40))

        # Check daily limit
        exceeds_daily = change_pct > max_daily_pct

        # Check weekly limit
        weekly_data = self._get_weekly_budget_change(account_id, customer_id, campaign_id)

        # Calculate what the new weekly change would be
        if weekly_data['starting_budget'] > 0:
            new_weekly_change_pct = abs((proposed_budget - weekly_data['starting_budget']) / weekly_data['starting_budget'] * 100)
        else:
            new_weekly_change_pct = 0

        exceeds_weekly = new_weekly_change_pct > max_weekly_pct

        # Determine capped budget
        capped_budget = proposed_budget

        if exceeds_daily:
            # Cap to max daily change
            if proposed_budget > current_budget:
                capped_budget = current_budget * (1 + max_daily_pct / 100)
            else:
                capped_budget = current_budget * (1 - max_daily_pct / 100)

        if exceeds_weekly:
            # Cap to max weekly change
            if weekly_data['starting_budget'] > 0:
                if proposed_budget > weekly_data['starting_budget']:
                    max_allowed = weekly_data['starting_budget'] * (1 + max_weekly_pct / 100)
                else:
                    max_allowed = weekly_data['starting_budget'] * (1 - max_weekly_pct / 100)

                capped_budget = min(capped_budget, max_allowed) if proposed_budget > current_budget else max(capped_budget, max_allowed)

        allowed = not (exceeds_daily or exceeds_weekly)
        reason = []
        if exceeds_daily:
            reason.append(f"Exceeds daily limit of {max_daily_pct}%")
        if exceeds_weekly:
            reason.append(f"Exceeds weekly limit of {max_weekly_pct}%")

        return {
            'allowed': allowed,
            'reason': '; '.join(reason) if reason else 'Within limits',
            'capped_budget': capped_budget,
            'exceeds_daily': exceeds_daily,
            'exceeds_weekly': exceeds_weekly,
            'change_pct': change_pct
        }

    def _apply_gradual_ramp(
        self,
        current_budget: float,
        target_budget: float,
        settings: Dict[str, Any]
    ) -> float:
        """
        Apply gradual ramping to spread changes over multiple days.

        Returns:
            Budget for today (first step of ramp)
        """
        if not settings.get('enable_gradual_ramp', True):
            return target_budget

        ramp_days = int(settings.get('ramp_days', 3))
        if ramp_days <= 1:
            return target_budget

        # Calculate daily increment
        total_change = target_budget - current_budget
        daily_increment = total_change / ramp_days

        # Return budget after first day of ramp
        return current_budget + daily_increment

    def _requires_approval(
        self,
        change_pct: float,
        settings: Dict[str, Any]
    ) -> bool:
        """Determine if a change requires manual approval."""
        threshold = float(settings.get('require_approval_threshold_pct', 30))
        return abs(change_pct) > threshold

    def _create_pending_change(
        self,
        account_id: int,
        customer_id: str,
        budget_group_id: Optional[int],
        adjustment: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Create a pending change awaiting approval.

        Args:
            account_id: Account ID
            customer_id: Google Ads customer ID
            budget_group_id: Budget group ID (None for account-level)
            adjustment: Adjustment dict with campaign info and proposed budget
            metadata: Additional context

        Returns:
            True if successful
        """
        cursor = self.db.cursor()

        try:
            import json
            from datetime import datetime, timedelta

            metadata_json = json.dumps(metadata) if metadata else None
            expires_at = datetime.now() + timedelta(hours=48)  # 48 hour expiration

            cursor.execute("""
                INSERT INTO budget_pending_changes (
                    account_id, customer_id, budget_group_id, campaign_id, campaign_name,
                    current_daily_budget, proposed_daily_budget, change_amount, change_pct,
                    reason, triggered_by, status, requires_approval, expires_at, metadata
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                account_id, customer_id, budget_group_id,
                adjustment['campaign_id'], adjustment.get('campaign_name', ''),
                adjustment['current_daily_budget'], adjustment['recommended_daily_budget'],
                adjustment['change_amount'], adjustment['change_pct'],
                adjustment.get('reason', ''), 'auto', 'pending', True, expires_at, metadata_json
            ))

            self.db.commit()
            cursor.close()

            # Create notification for user
            self.create_notification(
                account_id=account_id,
                user_id=None,  # Account-level notification
                notification_type='budget_change',
                severity='warning',
                title=f'Budget Change Approval Required',
                message=f'Campaign "{adjustment.get("campaign_name", "")}" needs approval for {adjustment["change_pct"]:.1f}% budget change',
                action_url='/account/auto-budget?tab=pending',
                related_entity_type='campaign',
                related_entity_id=adjustment['campaign_id'],
                metadata={'change_pct': adjustment['change_pct'], 'reason': adjustment.get('reason', '')}
            )

            return True

        except Exception as e:
            logger.error(f"Error creating pending change: {e}")
            self.db.rollback()
            cursor.close()
            return False

    def apply_budget_adjustments_with_safeguards(
        self,
        account_id: int,
        customer_id: str,
        adjustments: List[Dict[str, Any]],
        settings: Dict[str, Any],
        budget_group_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Apply budget adjustments with safeguard enforcement.

        Args:
            account_id: Account ID
            customer_id: Google Ads customer ID
            adjustments: List of proposed adjustments
            settings: Settings dict with safeguard configuration
            budget_group_id: Optional budget group ID

        Returns:
            Dict with 'applied', 'pending_approval', 'blocked', 'alerts'
        """
        applied = []
        pending_approval = []
        blocked = []
        alerts = []

        for adjustment in adjustments:
            campaign_id = adjustment['campaign_id']
            current_budget = adjustment['current_daily_budget']
            proposed_budget = adjustment['recommended_daily_budget']
            change_pct = adjustment['change_pct']

            # Check limits
            limit_check = self._check_change_limits(
                account_id, customer_id, campaign_id,
                current_budget, proposed_budget, settings
            )

            # Apply gradual ramp if enabled
            if settings.get('enable_gradual_ramp', True):
                ramped_budget = self._apply_gradual_ramp(
                    current_budget, limit_check['capped_budget'], settings
                )
            else:
                ramped_budget = limit_check['capped_budget']

            # Recalculate change with ramped budget
            actual_change_pct = ((ramped_budget - current_budget) / current_budget * 100) if current_budget > 0 else 0

            # Check if approval required
            needs_approval = self._requires_approval(actual_change_pct, settings)

            # Check alert threshold
            alert_threshold = float(settings.get('alert_threshold_pct', 15))
            if abs(actual_change_pct) > alert_threshold:
                alerts.append({
                    'campaign_id': campaign_id,
                    'campaign_name': adjustment.get('campaign_name', ''),
                    'change_pct': actual_change_pct,
                    'reason': adjustment.get('reason', '')
                })

            # Create updated adjustment
            final_adjustment = adjustment.copy()
            final_adjustment['recommended_daily_budget'] = ramped_budget
            final_adjustment['change_amount'] = ramped_budget - current_budget
            final_adjustment['change_pct'] = actual_change_pct
            final_adjustment['limit_check'] = limit_check

            if limit_check['exceeds_daily'] or limit_check['exceeds_weekly']:
                # Budget was capped or blocked
                if ramped_budget != current_budget:
                    final_adjustment['reason'] += f" (Capped: {limit_check['reason']})"
                    if needs_approval:
                        self._create_pending_change(
                            account_id, customer_id, budget_group_id,
                            final_adjustment,
                            metadata={'limit_check': limit_check, 'original_proposed': proposed_budget}
                        )
                        pending_approval.append(final_adjustment)
                    else:
                        applied.append(final_adjustment)
                else:
                    # Change completely blocked
                    blocked.append({
                        **final_adjustment,
                        'block_reason': limit_check['reason']
                    })
            elif needs_approval:
                # Within limits but needs approval
                self._create_pending_change(
                    account_id, customer_id, budget_group_id,
                    final_adjustment,
                    metadata={'requires_approval': True}
                )
                pending_approval.append(final_adjustment)
            else:
                # Safe to apply immediately
                applied.append(final_adjustment)

        # Send alerts if any
        if alerts:
            for alert in alerts:
                self.create_notification(
                    account_id=account_id,
                    user_id=None,
                    notification_type='budget_change',
                    severity='info',
                    title=f'Significant Budget Change',
                    message=f'Campaign "{alert["campaign_name"]}" budget changed by {alert["change_pct"]:.1f}%',
                    action_url='/account/auto-budget',
                    related_entity_type='campaign',
                    related_entity_id=alert['campaign_id']
                )

        return {
            'applied': applied,
            'pending_approval': pending_approval,
            'blocked': blocked,
            'alerts': alerts,
            'summary': {
                'total_adjustments': len(adjustments),
                'applied_count': len(applied),
                'pending_count': len(pending_approval),
                'blocked_count': len(blocked),
                'alert_count': len(alerts)
            }
        }

    def get_pending_changes(
        self,
        account_id: int,
        customer_id: str,
        status: str = 'pending'
    ) -> List[Dict[str, Any]]:
        """Get pending budget changes awaiting approval."""
        cursor = self.db.cursor(dictionary=True)
        cursor.execute("""
            SELECT * FROM budget_pending_changes
            WHERE account_id = %s AND customer_id = %s AND status = %s
            ORDER BY created_at DESC
        """, (account_id, customer_id, status))

        changes = cursor.fetchall()
        cursor.close()

        # Parse JSON metadata
        import json
        for change in changes:
            if change.get('metadata'):
                try:
                    change['metadata'] = json.loads(change['metadata'])
                except:
                    change['metadata'] = None

        return changes

    def approve_pending_change(
        self,
        change_id: int,
        user_id: int,
        execute_immediately: bool = True
    ) -> bool:
        """
        Approve a pending budget change.

        Args:
            change_id: Pending change ID
            user_id: User approving the change
            execute_immediately: Whether to apply the change now

        Returns:
            True if successful
        """
        cursor = self.db.cursor(dictionary=True)

        try:
            # Get the pending change
            cursor.execute("SELECT * FROM budget_pending_changes WHERE id = %s", (change_id,))
            change = cursor.fetchone()

            if not change or change['status'] != 'pending':
                cursor.close()
                return False

            # Update status to approved
            cursor.execute("""
                UPDATE budget_pending_changes
                SET status = 'approved', approved_by = %s, approved_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (user_id, change_id))

            if execute_immediately:
                # Log the budget change
                self.log_budget_change(
                    account_id=change['account_id'],
                    customer_id=change['customer_id'],
                    campaign_id=change['campaign_id'],
                    campaign_name=change['campaign_name'],
                    change_type='increase' if change['change_amount'] > 0 else 'decrease',
                    old_budget=float(change['current_daily_budget']),
                    new_budget=float(change['proposed_daily_budget']),
                    reason=f"Manual approval: {change['reason']}",
                    triggered_by='manual'
                )

                # Update weekly tracking
                self._update_weekly_budget_tracking(
                    change['account_id'],
                    change['customer_id'],
                    change['campaign_id'],
                    float(change['current_daily_budget']),
                    float(change['proposed_daily_budget'])
                )

            self.db.commit()
            cursor.close()
            return True

        except Exception as e:
            logger.error(f"Error approving pending change: {e}")
            self.db.rollback()
            cursor.close()
            return False

    def reject_pending_change(
        self,
        change_id: int,
        user_id: int,
        rejection_reason: str
    ) -> bool:
        """Reject a pending budget change."""
        cursor = self.db.cursor()

        try:
            cursor.execute("""
                UPDATE budget_pending_changes
                SET status = 'rejected', rejected_by = %s, rejected_at = CURRENT_TIMESTAMP,
                    rejection_reason = %s
                WHERE id = %s AND status = 'pending'
            """, (user_id, rejection_reason, change_id))

            self.db.commit()
            cursor.close()
            return cursor.rowcount > 0

        except Exception as e:
            logger.error(f"Error rejecting pending change: {e}")
            self.db.rollback()
            cursor.close()
            return False

    def check_for_rollback(
        self,
        account_id: int,
        customer_id: str,
        campaign_id: str,
        settings: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Check if a recent budget change should be rolled back due to performance drop.

        Returns:
            Rollback info dict if rollback needed, None otherwise
        """
        if not settings.get('enable_rollback', False):
            return None

        rollback_window_hours = int(settings.get('rollback_window_hours', 24))
        performance_drop_threshold = float(settings.get('rollback_performance_drop_pct', 20))

        cursor = self.db.cursor(dictionary=True)

        # Get recent budget changes within rollback window
        cursor.execute("""
            SELECT * FROM budget_change_log
            WHERE account_id = %s AND customer_id = %s AND campaign_id = %s
            AND created_at >= DATE_SUB(NOW(), INTERVAL %s HOUR)
            ORDER BY created_at DESC
            LIMIT 1
        """, (account_id, customer_id, campaign_id, rollback_window_hours))

        recent_change = cursor.fetchone()
        cursor.close()

        if not recent_change:
            return None

        # Compare current ROAS with ROAS at time of the last budget change
        try:
            cursor2 = self.db.cursor(dictionary=True)
            # Average ROAS over the last 24 h from campaign_performance_history
            cursor2.execute(
                """
                SELECT AVG(roas) AS current_roas
                FROM campaign_performance_history
                WHERE campaign_id = %s
                  AND date >= DATE_SUB(CURDATE(), INTERVAL 1 DAY)
                """,
                (campaign_id,),
            )
            row_roas = cursor2.fetchone()
            cursor2.close()
            current_roas = (row_roas or {}).get("current_roas") or 0.0

            # Baseline ROAS: 7-day average before the change was made
            change_ts = recent_change.get("created_at")
            if change_ts and current_roas:
                cursor3 = self.db.cursor(dictionary=True)
                cursor3.execute(
                    """
                    SELECT AVG(roas) AS baseline_roas
                    FROM campaign_performance_history
                    WHERE campaign_id = %s
                      AND date BETWEEN DATE_SUB(%s, INTERVAL 8 DAY) AND DATE_SUB(%s, INTERVAL 1 DAY)
                    """,
                    (campaign_id, change_ts, change_ts),
                )
                row_base = cursor3.fetchone()
                cursor3.close()
                baseline_roas = (row_base or {}).get("baseline_roas") or 0.0

                if baseline_roas > 0:
                    pct_drop = (baseline_roas - current_roas) / baseline_roas * 100
                    if pct_drop >= performance_drop_threshold:
                        return {
                            "budget_change_log_id": recent_change["id"],
                            "reason": (
                                f"ROAS dropped {pct_drop:.1f}% "
                                f"(was {baseline_roas:.2f}x, now {current_roas:.2f}x) "
                                f"after budget change"
                            ),
                        }
        except Exception as exc:
            logger.warning("check_for_rollback ROAS query failed: %s", exc)

        return None

    def execute_rollback(
        self,
        budget_change_log_id: int,
        reason: str
    ) -> bool:
        """Execute a budget rollback."""
        cursor = self.db.cursor(dictionary=True)

        try:
            # Get the original change
            cursor.execute("SELECT * FROM budget_change_log WHERE id = %s", (budget_change_log_id,))
            original_change = cursor.fetchone()

            if not original_change:
                cursor.close()
                return False

            # Log the rollback
            cursor.execute("""
                INSERT INTO budget_rollback_tracking (
                    account_id, customer_id, campaign_id, campaign_name,
                    budget_change_log_id, old_budget, new_budget, rollback_budget,
                    trigger_reason, rollback_executed, executed_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            """, (
                original_change['account_id'],
                original_change['customer_id'],
                original_change['campaign_id'],
                original_change['campaign_name'],
                budget_change_log_id,
                float(original_change['old_budget']),
                float(original_change['new_budget']),
                float(original_change['old_budget']),  # Rollback to old budget
                reason,
                True
            ))

            # Log the new budget change (rollback)
            self.log_budget_change(
                account_id=original_change['account_id'],
                customer_id=original_change['customer_id'],
                campaign_id=original_change['campaign_id'],
                campaign_name=original_change['campaign_name'],
                change_type='rollback',
                old_budget=float(original_change['new_budget']),
                new_budget=float(original_change['old_budget']),
                reason=f"Automatic rollback: {reason}",
                triggered_by='auto'
            )

            self.db.commit()
            cursor.close()
            return True

        except Exception as e:
            logger.error(f"Error executing rollback: {e}")
            self.db.rollback()
            cursor.close()
            return False
