# app/services/competitive_intelligence_service.py
"""
Competitive Intelligence Service

Analyzes competitive landscape from Google Ads Auction Insights API.

Features:
- Competitor impression share tracking
- Position above rate (how often they outrank you)
- Overlap rate (how often you compete)
- Threat level detection
- Budget recommendations based on competition
- Competitor budget estimation
"""

from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta, date
from decimal import Decimal
import logging

logger = logging.getLogger(__name__)


class CompetitiveIntelligenceService:
    """Service for competitive intelligence and auction insights."""

    def __init__(self, db_connection):
        """
        Initialize the service.

        Args:
            db_connection: Database connection object
        """
        self.db = db_connection

    def save_auction_insights(
        self,
        account_id: int,
        customer_id: str,
        campaign_id: str,
        report_date: date,
        competitors: List[Dict[str, Any]]
    ) -> bool:
        """
        Save auction insights data for competitors.

        Args:
            account_id: Account ID
            customer_id: Google Ads customer ID
            campaign_id: Campaign ID
            report_date: Date of the report
            competitors: List of competitor data dicts

        Returns:
            True if successful
        """
        cursor = self.db.cursor()

        try:
            for comp in competitors:
                # Calculate threat level and budget recommendation
                threat_level = self._calculate_threat_level(comp)
                budget_rec = self._get_budget_recommendation(comp, threat_level)

                # Estimate competitor budget
                estimated_budget = self._estimate_competitor_budget(comp)

                cursor.execute("""
                    INSERT INTO competitive_auction_insights (
                        account_id, customer_id, campaign_id, report_date,
                        competitor_domain, impression_share, overlap_rate,
                        position_above_rate, outranking_share, top_of_page_rate,
                        absolute_top_of_page_rate, estimated_daily_budget,
                        threat_level, budget_recommendation
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        impression_share = VALUES(impression_share),
                        overlap_rate = VALUES(overlap_rate),
                        position_above_rate = VALUES(position_above_rate),
                        outranking_share = VALUES(outranking_share),
                        top_of_page_rate = VALUES(top_of_page_rate),
                        absolute_top_of_page_rate = VALUES(absolute_top_of_page_rate),
                        estimated_daily_budget = VALUES(estimated_daily_budget),
                        threat_level = VALUES(threat_level),
                        budget_recommendation = VALUES(budget_recommendation),
                        updated_at = CURRENT_TIMESTAMP
                """, (
                    account_id,
                    customer_id,
                    campaign_id,
                    report_date,
                    comp.get('domain', ''),
                    comp.get('impression_share', 0),
                    comp.get('overlap_rate', 0),
                    comp.get('position_above_rate', 0),
                    comp.get('outranking_share', 0),
                    comp.get('top_of_page_rate', 0),
                    comp.get('absolute_top_of_page_rate', 0),
                    estimated_budget,
                    threat_level,
                    budget_rec
                ))

            self.db.commit()
            cursor.close()

            # Check for significant changes and create alerts
            self._check_for_alerts(account_id, customer_id, campaign_id, report_date, competitors)

            return True

        except Exception as e:
            logger.error(f"Error saving auction insights: {e}")
            self.db.rollback()
            cursor.close()
            return False

    def _calculate_threat_level(self, competitor: Dict[str, Any]) -> str:
        """
        Calculate threat level based on competitive metrics.

        Args:
            competitor: Competitor data dict

        Returns:
            Threat level: low, medium, high, critical
        """
        position_above = competitor.get('position_above_rate', 0)
        impression_share = competitor.get('impression_share', 0)
        overlap = competitor.get('overlap_rate', 0)

        # Critical threat: Outranking you >70% of time with high overlap
        if position_above >= 70 and overlap >= 50:
            return 'critical'

        # High threat: Outranking you >50% with moderate overlap
        if position_above >= 50 and overlap >= 30:
            return 'high'

        # Medium threat: Outranking you 30-50%
        if position_above >= 30:
            return 'medium'

        # Low threat: Minimal competitive pressure
        return 'low'

    def _get_budget_recommendation(self, competitor: Dict[str, Any], threat_level: str) -> str:
        """
        Get budget recommendation based on competitive position.

        Args:
            competitor: Competitor data
            threat_level: Calculated threat level

        Returns:
            Budget recommendation string
        """
        position_above = competitor.get('position_above_rate', 0)
        outranking_share = competitor.get('outranking_share', 0)
        domain = competitor.get('domain', 'competitor')

        if threat_level == 'critical':
            return f"HIGH PRIORITY: {domain} outranks you {position_above:.0f}% of the time. Increase budget 40-50% and improve Quality Scores."

        elif threat_level == 'high':
            return f"MODERATE THREAT: {domain} outranks you {position_above:.0f}% of the time. Consider increasing budget 30-40%."

        elif threat_level == 'medium':
            if outranking_share >= 60:
                return f"OPPORTUNITY: You outrank {domain} {outranking_share:.0f}% of the time. Maintain current strategy."
            else:
                return f"MONITOR: {domain} outranks you {position_above:.0f}% of the time. Consider increasing budget 15-25%."

        else:
            return f"LOW THREAT: You're competitive with {domain}. Maintain current budget."

    def _estimate_competitor_budget(self, competitor: Dict[str, Any]) -> float:
        """
        Estimate competitor's daily budget based on impression share.

        This is a rough estimate assuming:
        - Impression share correlates with budget
        - Market has finite daily search volume
        - Competitor bids are similar to yours

        Args:
            competitor: Competitor data

        Returns:
            Estimated daily budget
        """
        impression_share = competitor.get('impression_share', 0)

        # Rough estimation: If they have 50% impression share, they're spending
        # roughly proportional to that in the market
        # This is very approximate and would need tuning per market

        # Baseline: Assume $100/day per 10% impression share
        estimated_daily = (impression_share / 10) * 100

        return round(estimated_daily, 2)

    def _check_for_alerts(
        self,
        account_id: int,
        customer_id: str,
        campaign_id: str,
        report_date: date,
        competitors: List[Dict[str, Any]]
    ) -> None:
        """
        Check for significant competitive changes and create alerts.

        Args:
            account_id: Account ID
            customer_id: Google Ads customer ID
            campaign_id: Campaign ID
            report_date: Current report date
            competitors: List of current competitor data
        """
        # Get previous report (7 days ago)
        prev_date = report_date - timedelta(days=7)

        cursor = self.db.cursor(dictionary=True)

        for comp in competitors:
            domain = comp.get('domain', '')

            # Get previous data
            cursor.execute("""
                SELECT * FROM competitive_auction_insights
                WHERE account_id = %s
                AND customer_id = %s
                AND campaign_id = %s
                AND competitor_domain = %s
                AND report_date = %s
            """, (account_id, customer_id, campaign_id, domain, prev_date))

            prev_data = cursor.fetchone()

            if not prev_data:
                # New competitor detected
                if comp.get('impression_share', 0) >= 10:  # Only alert if significant
                    self._create_alert(
                        account_id, customer_id, campaign_id, domain,
                        'new_competitor', 'warning',
                        'impression_share', 0, comp.get('impression_share', 0),
                        f"New competitor {domain} detected with {comp.get('impression_share', 0):.0f}% impression share",
                        "Monitor this competitor closely"
                    )
                continue

            # Check for significant changes
            self._check_metric_change(
                account_id, customer_id, campaign_id, domain,
                'impression_share',
                prev_data.get('impression_share', 0),
                comp.get('impression_share', 0),
                threshold=10,  # Alert if >10 point change
                alert_type='increased_aggression' if comp.get('impression_share', 0) > prev_data.get('impression_share', 0) else 'decreased_presence'
            )

            self._check_metric_change(
                account_id, customer_id, campaign_id, domain,
                'position_above_rate',
                prev_data.get('position_above_rate', 0),
                comp.get('position_above_rate', 0),
                threshold=15,  # Alert if >15 point change
                alert_type='lost_position'
            )

        cursor.close()

    def _check_metric_change(
        self,
        account_id: int,
        customer_id: str,
        campaign_id: str,
        domain: str,
        metric_name: str,
        old_value: float,
        new_value: float,
        threshold: float,
        alert_type: str
    ) -> None:
        """Check if metric change exceeds threshold and create alert."""

        change = abs(new_value - old_value)
        change_pct = (change / old_value * 100) if old_value > 0 else 0

        if change >= threshold:
            severity = 'critical' if change >= threshold * 2 else 'warning'

            description = f"{domain}'s {metric_name.replace('_', ' ')} changed from {old_value:.1f}% to {new_value:.1f}% ({change:+.1f} points)"

            if metric_name == 'impression_share' and new_value > old_value:
                recommendation = f"Competitor increased budget. Consider increasing your budget by {change:.0f}% to maintain position."
            elif metric_name == 'position_above_rate' and new_value > old_value:
                recommendation = "Competitor improved their position. Review your bids and Quality Scores."
            else:
                recommendation = "Monitor this trend over the next week."

            self._create_alert(
                account_id, customer_id, campaign_id, domain,
                alert_type, severity, metric_name,
                old_value, new_value,
                description, recommendation
            )

    def _create_alert(
        self,
        account_id: int,
        customer_id: str,
        campaign_id: str,
        competitor_domain: str,
        alert_type: str,
        severity: str,
        metric_name: str,
        old_value: float,
        new_value: float,
        description: str,
        recommended_action: str
    ) -> bool:
        """Create a competitive alert."""

        cursor = self.db.cursor()

        try:
            change_pct = ((new_value - old_value) / old_value * 100) if old_value > 0 else 0

            cursor.execute("""
                INSERT INTO competitive_alerts (
                    account_id, customer_id, campaign_id, competitor_domain,
                    alert_type, severity, metric_name, old_value, new_value,
                    change_pct, description, recommended_action
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                account_id, customer_id, campaign_id, competitor_domain,
                alert_type, severity, metric_name, old_value, new_value,
                change_pct, description, recommended_action
            ))

            self.db.commit()
            cursor.close()
            return True

        except Exception as e:
            logger.error(f"Error creating competitive alert: {e}")
            self.db.rollback()
            cursor.close()
            return False

    def get_competitors(
        self,
        account_id: int,
        customer_id: str,
        campaign_id: Optional[str] = None,
        report_date: Optional[date] = None
    ) -> List[Dict[str, Any]]:
        """
        Get competitor data.

        Args:
            account_id: Account ID
            customer_id: Google Ads customer ID
            campaign_id: Optional campaign filter
            report_date: Optional specific date (defaults to latest)

        Returns:
            List of competitors
        """
        cursor = self.db.cursor(dictionary=True)

        query = """
            SELECT * FROM competitive_auction_insights
            WHERE account_id = %s AND customer_id = %s
        """
        params = [account_id, customer_id]

        if campaign_id:
            query += " AND campaign_id = %s"
            params.append(campaign_id)

        if report_date:
            query += " AND report_date = %s"
            params.append(report_date)
        else:
            # Get latest date
            query += " AND report_date = (SELECT MAX(report_date) FROM competitive_auction_insights WHERE account_id = %s AND customer_id = %s)"
            params.extend([account_id, customer_id])

        query += " ORDER BY impression_share DESC"

        cursor.execute(query, params)
        competitors = cursor.fetchall()
        cursor.close()

        return competitors

    def get_alerts(
        self,
        account_id: int,
        customer_id: str,
        unaddressed_only: bool = True,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Get competitive alerts.

        Args:
            account_id: Account ID
            customer_id: Google Ads customer ID
            unaddressed_only: Only return unaddressed alerts
            limit: Max number of records

        Returns:
            List of alerts
        """
        cursor = self.db.cursor(dictionary=True)

        query = """
            SELECT * FROM competitive_alerts
            WHERE account_id = %s AND customer_id = %s
        """
        params = [account_id, customer_id]

        if unaddressed_only:
            query += " AND is_addressed = FALSE"

        query += " ORDER BY created_at DESC LIMIT %s"
        params.append(limit)

        cursor.execute(query, params)
        alerts = cursor.fetchall()
        cursor.close()

        return alerts

    def get_market_share_analysis(
        self,
        account_id: int,
        customer_id: str,
        campaign_id: str,
        your_impression_share: float
    ) -> Dict[str, Any]:
        """
        Calculate your market share vs competitors.

        Args:
            account_id: Account ID
            customer_id: Google Ads customer ID
            campaign_id: Campaign ID
            your_impression_share: Your current impression share

        Returns:
            Market share analysis
        """
        competitors = self.get_competitors(account_id, customer_id, campaign_id)

        total_competitive_share = sum(c.get('impression_share', 0) for c in competitors)
        total_market = your_impression_share + total_competitive_share

        analysis = {
            'your_share': your_impression_share,
            'competitive_share': total_competitive_share,
            'total_market': total_market,
            'your_pct_of_market': (your_impression_share / total_market * 100) if total_market > 0 else 0,
            'num_competitors': len(competitors),
            'top_competitor': competitors[0] if competitors else None,
            'threats': [c for c in competitors if c.get('threat_level') in ['high', 'critical']],
            'opportunities': [c for c in competitors if c.get('outranking_share', 0) >= 60]
        }

        return analysis

    def mark_alert_addressed(self, alert_id: int, account_id: int) -> bool:
        """
        Mark an alert as addressed.

        Args:
            alert_id: Alert ID
            account_id: Account ID (for security)

        Returns:
            True if successful
        """
        cursor = self.db.cursor()

        try:
            cursor.execute("""
                UPDATE competitive_alerts
                SET is_addressed = TRUE, addressed_at = CURRENT_TIMESTAMP
                WHERE id = %s AND account_id = %s
            """, (alert_id, account_id))

            self.db.commit()
            cursor.close()
            return True

        except Exception as e:
            logger.error(f"Error marking alert as addressed: {e}")
            self.db.rollback()
            cursor.close()
            return False
