"""
Budget Tracker Service

Handles budget tracking logic including:
- Fetching spend data from Google Ads API
- Checking budget thresholds
- Generating alerts
- Calculating pacing metrics
"""
import logging
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException
from flask import current_app
import os

from app import db
from app.models import BudgetTracker, BudgetAlert, User

logger = logging.getLogger(__name__)


def _get_config(key: str) -> Optional[str]:
    """Get configuration value from environment or Flask config."""
    return os.getenv(key) or current_app.config.get(key)


class BudgetTrackerService:
    """Service for budget tracking operations."""

    def __init__(self, refresh_token: str):
        """
        Initialize the budget tracker service.

        Args:
            refresh_token: OAuth refresh token for the user
        """
        self.refresh_token = refresh_token

        # Build credentials dictionary for Google Ads client
        credentials = {
            "developer_token": _get_config("GOOGLE_ADS_DEVELOPER_TOKEN"),
            "client_id": _get_config("GOOGLE_ADS_CLIENT_ID"),
            "client_secret": _get_config("GOOGLE_ADS_CLIENT_SECRET"),
            "refresh_token": refresh_token,
            "use_proto_plus": True,
        }

        try:
            self.client = GoogleAdsClient.load_from_dict(credentials)
        except Exception as e:
            logger.exception(f"Failed to initialize Google Ads client: {e}")
            raise

    def fetch_current_spend(
        self,
        customer_id: str,
        start_date: datetime,
        end_date: datetime,
        campaign_id: Optional[str] = None
    ) -> float:
        """
        Fetch current spend for a budget period.

        Args:
            customer_id: Google Ads customer ID
            start_date: Budget period start date
            end_date: Budget period end date (or today if sooner)
            campaign_id: Optional campaign ID to filter by

        Returns:
            Total spend in dollars
        """
        # Ensure we don't query future dates
        today = datetime.now().date()
        query_end_date = min(end_date.date(), today)

        # Remove dashes from customer ID
        customer_id = customer_id.replace("-", "")

        # Build query based on whether we're tracking a campaign or account
        if campaign_id:
            query = """
                SELECT
                    metrics.cost_micros
                FROM campaign
                WHERE campaign.id = {campaign_id}
                  AND segments.date BETWEEN '{start}' AND '{end}'
            """.format(
                campaign_id=campaign_id,
                start=start_date.strftime("%Y-%m-%d"),
                end=query_end_date.strftime("%Y-%m-%d")
            )
        else:
            query = """
                SELECT
                    metrics.cost_micros
                FROM customer
                WHERE segments.date BETWEEN '{start}' AND '{end}'
            """.format(
                start=start_date.strftime("%Y-%m-%d"),
                end=query_end_date.strftime("%Y-%m-%d")
            )

        try:
            ga_service = self.client.get_service("GoogleAdsService")
            response = ga_service.search_stream(
                customer_id=customer_id,
                query=query
            )

            # Sum up all cost
            total_cost_micros = 0
            for batch in response:
                for row in batch.results:
                    total_cost_micros += row.metrics.cost_micros

            # Convert micros to dollars
            total_cost = total_cost_micros / 1_000_000

            return total_cost

        except GoogleAdsException as ex:
            logger.error(f"Google Ads API error fetching spend: {ex}")
            raise
        except Exception as e:
            logger.exception(f"Failed to fetch spend data: {e}")
            raise

    def update_tracker_spend(self, tracker: BudgetTracker) -> Dict:
        """
        Update spend for a single budget tracker.

        Args:
            tracker: BudgetTracker instance

        Returns:
            Dictionary with update status and any alerts created
        """
        try:
            # Fetch current spend
            current_spend = self.fetch_current_spend(
                customer_id=tracker.customer_id,
                start_date=tracker.start_date,
                end_date=tracker.end_date,
                campaign_id=tracker.campaign_id
            )

            # Convert to cents
            current_spend_cents = int(current_spend * 100)

            # Store previous spend for comparison
            previous_spend_cents = tracker.last_spend_amount or 0

            # Update tracker
            tracker.last_spend_amount = current_spend_cents
            tracker.last_checked_at = datetime.utcnow()
            db.session.commit()

            # Check if we should send alerts
            alerts_created = []
            if tracker.alert_enabled and tracker.status == "active":
                alerts = self._check_and_create_alerts(
                    tracker,
                    previous_spend_cents,
                    current_spend_cents
                )
                alerts_created.extend(alerts)

            return {
                "success": True,
                "tracker_id": tracker.id,
                "current_spend": current_spend,
                "spend_percentage": tracker.spend_percentage,
                "alerts_created": len(alerts_created)
            }

        except Exception as e:
            logger.error(f"Failed to update tracker {tracker.id}: {e}")
            return {
                "success": False,
                "tracker_id": tracker.id,
                "error": str(e)
            }

    def _check_and_create_alerts(
        self,
        tracker: BudgetTracker,
        previous_spend_cents: int,
        current_spend_cents: int
    ) -> List[BudgetAlert]:
        """
        Check if alerts should be sent and create them.

        Args:
            tracker: BudgetTracker instance
            previous_spend_cents: Previous spend amount
            current_spend_cents: Current spend amount

        Returns:
            List of created BudgetAlert instances
        """
        alerts = []

        # Calculate percentages
        budget_amount = tracker.budget_amount
        previous_pct = (previous_spend_cents / budget_amount * 100) if budget_amount > 0 else 0
        current_pct = (current_spend_cents / budget_amount * 100) if budget_amount > 0 else 0

        # Check if we crossed the alert threshold
        if previous_pct < tracker.alert_threshold_percent <= current_pct:
            alert = self._create_alert(
                tracker=tracker,
                alert_type="threshold_reached",
                severity="warning",
                message=f"Your budget has reached {tracker.alert_threshold_percent}% ({tracker.spend_percentage:.1f}%). "
                       f"You've spent ${tracker.last_spend_dollars:,.2f} of ${tracker.budget_amount_dollars:,.2f}."
            )
            alerts.append(alert)

        # Check if we exceeded 100%
        if previous_pct < 100 <= current_pct:
            alert = self._create_alert(
                tracker=tracker,
                alert_type="budget_depleted",
                severity="critical",
                message=f"Your budget has been depleted! You've spent ${tracker.last_spend_dollars:,.2f} "
                       f"of your ${tracker.budget_amount_dollars:,.2f} budget ({current_pct:.1f}%)."
            )
            alerts.append(alert)

        # Check for overspend (>110%)
        if previous_pct <= 110 < current_pct:
            overspend_amount = tracker.last_spend_dollars - tracker.budget_amount_dollars
            alert = self._create_alert(
                tracker=tracker,
                alert_type="overspend",
                severity="critical",
                message=f"You're overspending! You've exceeded your budget by ${overspend_amount:,.2f}. "
                       f"Total spend: ${tracker.last_spend_dollars:,.2f} (Budget: ${tracker.budget_amount_dollars:,.2f})."
            )
            alerts.append(alert)

        # Check pacing (only if we're not yet at threshold)
        if current_pct < tracker.alert_threshold_percent:
            pacing_alert = self._check_pacing(tracker, current_spend_cents)
            if pacing_alert:
                alerts.append(pacing_alert)

        return alerts

    def _check_pacing(
        self,
        tracker: BudgetTracker,
        current_spend_cents: int
    ) -> Optional[BudgetAlert]:
        """
        Check if budget pacing is on track.

        Args:
            tracker: BudgetTracker instance
            current_spend_cents: Current spend in cents

        Returns:
            BudgetAlert if pacing is off, None otherwise
        """
        # Calculate how much of the period has elapsed
        now = datetime.now()
        total_days = (tracker.end_date - tracker.start_date).days
        elapsed_days = (now - tracker.start_date).days

        if total_days <= 0 or elapsed_days < 0:
            return None

        # Calculate expected spend based on time elapsed
        time_elapsed_pct = (elapsed_days / total_days) * 100
        actual_spend_pct = (current_spend_cents / tracker.budget_amount) * 100 if tracker.budget_amount > 0 else 0

        # Check if we're pacing significantly ahead (>20% ahead of schedule)
        if actual_spend_pct > time_elapsed_pct + 20:
            expected_spend = (tracker.budget_amount * time_elapsed_pct / 100) / 100  # Convert to dollars
            return self._create_alert(
                tracker=tracker,
                alert_type="pacing_ahead",
                severity="warning",
                message=f"You're spending faster than expected! You're {actual_spend_pct - time_elapsed_pct:.1f}% "
                       f"ahead of schedule. Expected: ${expected_spend:,.2f}, Actual: ${tracker.last_spend_dollars:,.2f}."
            )

        # Check if we're pacing significantly behind (<20% behind schedule)
        if actual_spend_pct < time_elapsed_pct - 20:
            expected_spend = (tracker.budget_amount * time_elapsed_pct / 100) / 100  # Convert to dollars
            return self._create_alert(
                tracker=tracker,
                alert_type="pacing_behind",
                severity="info",
                message=f"You're spending slower than expected. You're {time_elapsed_pct - actual_spend_pct:.1f}% "
                       f"behind schedule. Expected: ${expected_spend:,.2f}, Actual: ${tracker.last_spend_dollars:,.2f}."
            )

        return None

    def _create_alert(
        self,
        tracker: BudgetTracker,
        alert_type: str,
        severity: str,
        message: str
    ) -> BudgetAlert:
        """
        Create and save a budget alert.

        Args:
            tracker: BudgetTracker instance
            alert_type: Type of alert
            severity: Severity level (info, warning, critical)
            message: Alert message

        Returns:
            Created BudgetAlert instance
        """
        alert = BudgetAlert(
            budget_tracker_id=tracker.id,
            alert_type=alert_type,
            alert_message=message,
            severity=severity,
            spend_amount=tracker.last_spend_amount,
            budget_amount=tracker.budget_amount,
            spend_percentage=tracker.spend_percentage
        )
        db.session.add(alert)
        db.session.commit()

        logger.info(f"Created {severity} alert for tracker {tracker.id}: {alert_type}")
        return alert


def update_all_active_trackers() -> Dict:
    """
    Update spend for all active budget trackers.

    This function should be called periodically (e.g., every hour) via a cron job.

    Returns:
        Dictionary with update statistics
    """
    # Get all active trackers
    active_trackers = BudgetTracker.query.filter_by(status="active").all()

    results = {
        "total": len(active_trackers),
        "success": 0,
        "failed": 0,
        "alerts_created": 0,
        "errors": []
    }

    for tracker in active_trackers:
        try:
            # Get user's refresh token
            user = User.query.get(tracker.user_id)
            if not user or not hasattr(user, 'google_refresh_token'):
                logger.error(f"No refresh token for user {tracker.user_id}")
                results["failed"] += 1
                continue

            # Initialize service and update
            service = BudgetTrackerService(refresh_token=user.google_refresh_token)
            result = service.update_tracker_spend(tracker)

            if result["success"]:
                results["success"] += 1
                results["alerts_created"] += result["alerts_created"]
            else:
                results["failed"] += 1
                results["errors"].append(result)

        except Exception as e:
            logger.exception(f"Error updating tracker {tracker.id}: {e}")
            results["failed"] += 1
            results["errors"].append({
                "tracker_id": tracker.id,
                "error": str(e)
            })

    logger.info(f"Budget tracker update complete: {results['success']}/{results['total']} successful, "
               f"{results['alerts_created']} alerts created")

    return results
