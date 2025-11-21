# app/services/budget_groups_service.py
"""
Budget Groups Service

Manages budget groups and campaign assignments.

Features:
- Create/edit/delete budget groups
- Assign campaigns to budget groups
- Track performance by budget group
- Validate assignments (no campaign in multiple groups)
"""

from typing import Dict, List, Any, Optional
from datetime import datetime, date
from decimal import Decimal
import logging

logger = logging.getLogger(__name__)


class BudgetGroupsService:
    """Service for managing budget groups."""

    def __init__(self, db_connection):
        """
        Initialize the service.

        Args:
            db_connection: Database connection object
        """
        self.db = db_connection

    def create_group(
        self,
        account_id: int,
        customer_id: str,
        name: str,
        monthly_budget_target: float,
        description: Optional[str] = None,
        industry: str = 'hvac_heating',
        color: str = '#3B82F6',
        **kwargs
    ) -> Optional[int]:
        """
        Create a new budget group.

        Args:
            account_id: Account ID
            customer_id: Google Ads customer ID
            name: Budget group name
            monthly_budget_target: Monthly budget target
            description: Optional description
            industry: Industry for seasonality
            color: Hex color for UI
            **kwargs: Additional settings

        Returns:
            Budget group ID if successful
        """
        cursor = self.db.cursor()

        try:
            cursor.execute("""
                INSERT INTO budget_groups (
                    account_id, customer_id, name, description,
                    monthly_budget_target, min_daily_budget, max_daily_budget,
                    enabled, adjustment_frequency, performance_weight,
                    seasonality_weight, capacity_weight, industry,
                    send_notifications, color
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                account_id,
                customer_id,
                name,
                description,
                monthly_budget_target,
                kwargs.get('min_daily_budget', 10.00),
                kwargs.get('max_daily_budget', 1000.00),
                kwargs.get('enabled', True),
                kwargs.get('adjustment_frequency', 'daily'),
                kwargs.get('performance_weight', 0.70),
                kwargs.get('seasonality_weight', 0.20),
                kwargs.get('capacity_weight', 0.10),
                industry,
                kwargs.get('send_notifications', True),
                color
            ))

            group_id = cursor.lastrowid
            self.db.commit()
            cursor.close()

            logger.info(f"Created budget group {group_id}: {name}")
            return group_id

        except Exception as e:
            logger.error(f"Error creating budget group: {e}")
            self.db.rollback()
            cursor.close()
            return None

    def get_group(self, group_id: int, account_id: int) -> Optional[Dict[str, Any]]:
        """
        Get a budget group by ID.

        Args:
            group_id: Budget group ID
            account_id: Account ID (for security)

        Returns:
            Budget group dict or None
        """
        cursor = self.db.cursor(dictionary=True)
        cursor.execute("""
            SELECT * FROM budget_groups
            WHERE id = %s AND account_id = %s
        """, (group_id, account_id))

        group = cursor.fetchone()
        cursor.close()

        if group:
            # Convert Decimal to float
            for key, value in group.items():
                if hasattr(value, '__float__'):
                    group[key] = float(value)

        return group

    def get_all_groups(
        self,
        account_id: int,
        customer_id: str,
        enabled_only: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Get all budget groups for an account.

        Args:
            account_id: Account ID
            customer_id: Google Ads customer ID
            enabled_only: Only return enabled groups

        Returns:
            List of budget groups
        """
        cursor = self.db.cursor(dictionary=True)

        query = """
            SELECT bg.*,
                   COUNT(DISTINCT bgc.campaign_id) as campaign_count,
                   COALESCE(SUM(bgp.total_spend), 0) as mtd_spend,
                   COALESCE(SUM(bgp.total_conversions), 0) as mtd_conversions
            FROM budget_groups bg
            LEFT JOIN budget_group_campaigns bgc ON bg.id = bgc.budget_group_id
            LEFT JOIN budget_group_performance bgp ON bg.id = bgp.budget_group_id
                AND bgp.snapshot_date >= DATE_FORMAT(CURDATE(), '%Y-%m-01')
            WHERE bg.account_id = %s AND bg.customer_id = %s
        """
        params = [account_id, customer_id]

        if enabled_only:
            query += " AND bg.enabled = TRUE"

        query += " GROUP BY bg.id ORDER BY bg.created_at DESC"

        cursor.execute(query, params)
        groups = cursor.fetchall()
        cursor.close()

        # Convert Decimal to float
        for group in groups:
            for key, value in group.items():
                if hasattr(value, '__float__'):
                    group[key] = float(value)
                elif isinstance(value, datetime):
                    group[key] = value.isoformat()

        return groups

    def update_group(
        self,
        group_id: int,
        account_id: int,
        updates: Dict[str, Any]
    ) -> bool:
        """
        Update a budget group.

        Args:
            group_id: Budget group ID
            account_id: Account ID (for security)
            updates: Dict of fields to update

        Returns:
            True if successful
        """
        cursor = self.db.cursor()

        try:
            # Build dynamic UPDATE query
            allowed_fields = [
                'name', 'description', 'monthly_budget_target', 'min_daily_budget',
                'max_daily_budget', 'enabled', 'adjustment_frequency',
                'performance_weight', 'seasonality_weight', 'capacity_weight',
                'industry', 'send_notifications', 'color'
            ]

            set_clauses = []
            values = []

            for field, value in updates.items():
                if field in allowed_fields:
                    set_clauses.append(f"{field} = %s")
                    values.append(value)

            if not set_clauses:
                return False

            set_clauses.append("updated_at = CURRENT_TIMESTAMP")
            values.extend([group_id, account_id])

            query = f"""
                UPDATE budget_groups
                SET {', '.join(set_clauses)}
                WHERE id = %s AND account_id = %s
            """

            cursor.execute(query, values)
            self.db.commit()
            cursor.close()

            logger.info(f"Updated budget group {group_id}")
            return True

        except Exception as e:
            logger.error(f"Error updating budget group: {e}")
            self.db.rollback()
            cursor.close()
            return False

    def delete_group(self, group_id: int, account_id: int) -> bool:
        """
        Delete a budget group.

        Args:
            group_id: Budget group ID
            account_id: Account ID (for security)

        Returns:
            True if successful
        """
        cursor = self.db.cursor()

        try:
            cursor.execute("""
                DELETE FROM budget_groups
                WHERE id = %s AND account_id = %s
            """, (group_id, account_id))

            self.db.commit()
            cursor.close()

            logger.info(f"Deleted budget group {group_id}")
            return True

        except Exception as e:
            logger.error(f"Error deleting budget group: {e}")
            self.db.rollback()
            cursor.close()
            return False

    def assign_campaign(
        self,
        group_id: int,
        account_id: int,
        customer_id: str,
        campaign_id: str,
        campaign_name: str
    ) -> bool:
        """
        Assign a campaign to a budget group.

        Args:
            group_id: Budget group ID
            account_id: Account ID
            customer_id: Google Ads customer ID
            campaign_id: Campaign ID
            campaign_name: Campaign name

        Returns:
            True if successful
        """
        cursor = self.db.cursor()

        try:
            # Check if campaign already assigned to another group
            cursor.execute("""
                SELECT budget_group_id FROM budget_group_campaigns
                WHERE account_id = %s AND campaign_id = %s
            """, (account_id, campaign_id))

            existing = cursor.fetchone()
            if existing and existing[0] != group_id:
                logger.warning(f"Campaign {campaign_id} already assigned to group {existing[0]}")
                cursor.close()
                return False

            # Insert or ignore if already exists
            cursor.execute("""
                INSERT INTO budget_group_campaigns (
                    budget_group_id, account_id, customer_id,
                    campaign_id, campaign_name
                ) VALUES (%s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE campaign_name = VALUES(campaign_name)
            """, (group_id, account_id, customer_id, campaign_id, campaign_name))

            self.db.commit()
            cursor.close()

            logger.info(f"Assigned campaign {campaign_id} to group {group_id}")
            return True

        except Exception as e:
            logger.error(f"Error assigning campaign: {e}")
            self.db.rollback()
            cursor.close()
            return False

    def unassign_campaign(
        self,
        group_id: int,
        account_id: int,
        campaign_id: str
    ) -> bool:
        """
        Remove a campaign from a budget group.

        Args:
            group_id: Budget group ID
            account_id: Account ID (for security)
            campaign_id: Campaign ID

        Returns:
            True if successful
        """
        cursor = self.db.cursor()

        try:
            cursor.execute("""
                DELETE FROM budget_group_campaigns
                WHERE budget_group_id = %s
                AND account_id = %s
                AND campaign_id = %s
            """, (group_id, account_id, campaign_id))

            self.db.commit()
            cursor.close()

            logger.info(f"Unassigned campaign {campaign_id} from group {group_id}")
            return True

        except Exception as e:
            logger.error(f"Error unassigning campaign: {e}")
            self.db.rollback()
            cursor.close()
            return False

    def get_group_campaigns(
        self,
        group_id: int,
        account_id: int
    ) -> List[Dict[str, Any]]:
        """
        Get all campaigns in a budget group.

        Args:
            group_id: Budget group ID
            account_id: Account ID (for security)

        Returns:
            List of campaigns
        """
        cursor = self.db.cursor(dictionary=True)
        cursor.execute("""
            SELECT * FROM budget_group_campaigns
            WHERE budget_group_id = %s AND account_id = %s
            ORDER BY campaign_name
        """, (group_id, account_id))

        campaigns = cursor.fetchall()
        cursor.close()

        # Convert datetime
        for campaign in campaigns:
            if 'added_at' in campaign and isinstance(campaign['added_at'], datetime):
                campaign['added_at'] = campaign['added_at'].isoformat()

        return campaigns

    def get_unassigned_campaigns(
        self,
        account_id: int,
        customer_id: str,
        all_campaigns: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Get campaigns not assigned to any budget group.

        Args:
            account_id: Account ID
            customer_id: Google Ads customer ID
            all_campaigns: List of all campaigns from Google Ads

        Returns:
            List of unassigned campaigns
        """
        cursor = self.db.cursor(dictionary=True)
        cursor.execute("""
            SELECT campaign_id FROM budget_group_campaigns
            WHERE account_id = %s
        """, (account_id,))

        assigned_ids = {row['campaign_id'] for row in cursor.fetchall()}
        cursor.close()

        unassigned = [
            camp for camp in all_campaigns
            if camp.get('id') not in assigned_ids
        ]

        return unassigned

    def record_performance_snapshot(
        self,
        group_id: int,
        account_id: int,
        snapshot_date: date,
        performance: Dict[str, Any]
    ) -> bool:
        """
        Record daily performance snapshot for a budget group.

        Args:
            group_id: Budget group ID
            account_id: Account ID
            snapshot_date: Date of snapshot
            performance: Performance metrics dict

        Returns:
            True if successful
        """
        cursor = self.db.cursor()

        try:
            cursor.execute("""
                INSERT INTO budget_group_performance (
                    budget_group_id, account_id, snapshot_date,
                    total_spend, total_conversions, avg_cpl,
                    total_clicks, total_impressions, avg_ctr,
                    avg_roas, campaigns_active, budget_utilization_pct
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    total_spend = VALUES(total_spend),
                    total_conversions = VALUES(total_conversions),
                    avg_cpl = VALUES(avg_cpl),
                    total_clicks = VALUES(total_clicks),
                    total_impressions = VALUES(total_impressions),
                    avg_ctr = VALUES(avg_ctr),
                    avg_roas = VALUES(avg_roas),
                    campaigns_active = VALUES(campaigns_active),
                    budget_utilization_pct = VALUES(budget_utilization_pct)
            """, (
                group_id,
                account_id,
                snapshot_date,
                performance.get('total_spend', 0),
                performance.get('total_conversions', 0),
                performance.get('avg_cpl', 0),
                performance.get('total_clicks', 0),
                performance.get('total_impressions', 0),
                performance.get('avg_ctr', 0),
                performance.get('avg_roas', 0),
                performance.get('campaigns_active', 0),
                performance.get('budget_utilization_pct', 0)
            ))

            self.db.commit()
            cursor.close()
            return True

        except Exception as e:
            logger.error(f"Error recording performance snapshot: {e}")
            self.db.rollback()
            cursor.close()
            return False
