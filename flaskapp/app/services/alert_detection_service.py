# app/services/alert_detection_service.py
"""
Alert Detection Service for Google Ads monitoring.

Detects and creates alerts for:
- Paused campaigns/ad groups
- CPL (Cost Per Lead) spikes
- Quality Score drops
- Budget thresholds (handled by BudgetTracker)
"""

from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple
import logging

from flask import current_app
from sqlalchemy import func, and_

from app import db
from app.models import Account
from app.models_alerts import Alert, AlertSettings
from app.services.google_ads_service import client_from_refresh
from app.services.alert_throttle_service import AlertThrottleService

logger = logging.getLogger(__name__)


class AlertDetectionService:
    """Service for detecting and creating Google Ads alerts."""

    def __init__(self):
        pass

    def _get_google_ads_client(self, account: Account):
        """Get Google Ads client for an account."""
        if not account.google_refresh_token:
            raise ValueError(f"Account {account.id} has no Google Ads connection")

        login_customer_id = account.google_login_customer_id or account.google_customer_id
        return client_from_refresh(account.google_refresh_token, login_customer_id)

    def _query_google_ads(self, account: Account, query: str):
        """Execute a Google Ads query."""
        client = self._get_google_ads_client(account)
        customer_id = account.google_customer_id

        if not customer_id:
            raise ValueError(f"Account {account.id} has no customer ID")

        ga_service = client.get_service("GoogleAdsService")
        stream = ga_service.search_stream(customer_id=customer_id, query=query)

        results = []
        for batch in stream:
            for row in batch.results:
                results.append(row)

        return results

    def check_all_alerts_for_user(self, user_id: int) -> Dict[str, Any]:
        """
        Check all alert types for all user's accounts.

        Returns summary of alerts created.
        """
        from app.models import User

        user = User.query.get(user_id)
        if not user:
            return {"error": "User not found", "alerts_created": 0}

        # Get user's alert settings
        settings = AlertSettings.get_or_create_for_user(user_id)

        # Check daily alert limit
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        alerts_today = Alert.query.filter(
            Alert.user_id == user_id,
            Alert.created_at >= today_start
        ).count()

        if alerts_today >= settings.max_alerts_per_day:
            logger.warning(f"User {user_id} has reached daily alert limit ({settings.max_alerts_per_day})")
            return {"alert": "Daily alert limit reached", "alerts_created": 0}

        alerts_created = []

        # Get all active Google Ads accounts for user
        accounts = Account.query.filter_by(user_id=user_id, is_active=True).all()

        for account in accounts:
            if not account.google_refresh_token:
                logger.debug(f"Account {account.id} has no Google Ads connection, skipping")
                continue

            try:
                # Check paused campaigns
                if settings.paused_campaign_enabled:
                    paused_alerts = self.check_paused_campaigns(account, user_id)
                    alerts_created.extend(paused_alerts)

                # Check CPL spikes
                if settings.cpl_spike_enabled:
                    cpl_alerts = self.check_cpl_spikes(
                        account,
                        user_id,
                        settings.cpl_spike_threshold_percent,
                        settings.cpl_spike_lookback_days
                    )
                    alerts_created.extend(cpl_alerts)

                # Check quality score drops
                if settings.quality_score_enabled:
                    qs_alerts = self.check_quality_score_drops(
                        account,
                        user_id,
                        settings.quality_score_threshold
                    )
                    alerts_created.extend(qs_alerts)

            except Exception as e:
                logger.error(f"Error checking alerts for account {account.id}: {e}")
                continue

            # Stop if we've hit the daily limit
            if len(alerts_created) >= (settings.max_alerts_per_day - alerts_today):
                break

        db.session.commit()

        return {
            "user_id": user_id,
            "accounts_checked": len(accounts),
            "alerts_created": len(alerts_created),
            "alert_ids": [a.id for a in alerts_created]
        }

    def check_paused_campaigns(self, account: Account, user_id: int) -> List[Alert]:
        """
        Check for paused campaigns and ad groups.

        Creates alerts for campaigns/ad groups that were recently paused
        (within last 24 hours).
        """
        alerts_created = []

        try:
            # Query paused campaigns from Google Ads
            query = """
                SELECT
                    campaign.id,
                    campaign.name,
                    campaign.status,
                    campaign.advertising_channel_type,
                    metrics.impressions,
                    metrics.clicks,
                    metrics.conversions
                FROM campaign
                WHERE campaign.status = 'PAUSED'
                AND segments.date DURING LAST_7_DAYS
            """

            customer_id = account.google_customer_id
            if not customer_id:
                return alerts_created

            # Get paused campaigns
            response = self._query_google_ads(account, query)

            for row in response:
                campaign_id = row.campaign.id
                campaign_name = row.campaign.name
                metrics = row.metrics

                # Check if we already have an active alert for this campaign
                existing_alert = Alert.query.filter_by(
                    account_id=account.id,
                    user_id=user_id,
                    alert_type="paused_campaign",
                    status="active"
                ).filter(
                    Alert.data["campaign_id"].astext == str(campaign_id)
                ).first()

                if existing_alert:
                    continue  # Don't create duplicate alerts

                # Prepare alert data
                alert_data = {
                    "campaign_id": str(campaign_id),
                    "campaign_name": campaign_name,
                    "channel_type": row.campaign.advertising_channel_type.name,
                    "last_7_days_impressions": metrics.impressions,
                    "last_7_days_clicks": metrics.clicks,
                    "last_7_days_conversions": metrics.conversions,
                    "detected_at": datetime.utcnow().isoformat()
                }

                # Check if we should create this alert (throttling)
                if not AlertThrottleService.should_create_alert(
                    alert_type="paused_campaign",
                    account_id=account.id,
                    user_id=user_id,
                    data=alert_data
                ):
                    logger.info(f"Throttled paused campaign alert for {campaign_name}")
                    continue

                # Add alert hash for deduplication
                alert_data["alert_hash"] = AlertThrottleService.generate_alert_hash(
                    "paused_campaign",
                    account.id,
                    alert_data
                )

                # Create alert
                alert = Alert(
                    account_id=account.id,
                    user_id=user_id,
                    alert_type="paused_campaign",
                    severity="warning",
                    title=f"Campaign Paused: {campaign_name}",
                    description=f"The campaign '{campaign_name}' is currently paused and not receiving traffic.",
                    data=alert_data,
                    action_url=f"/account/google/ads/campaigns/{campaign_id}",
                    action_text="Enable Campaign"
                )

                db.session.add(alert)
                alerts_created.append(alert)

        except Exception as e:
            logger.error(f"Error checking paused campaigns for account {account.id}: {e}")

        return alerts_created

    def check_cpl_spikes(
        self,
        account: Account,
        user_id: int,
        threshold_percent: int = 20,
        lookback_days: int = 7
    ) -> List[Alert]:
        """
        Check for CPL (Cost Per Lead) spikes.

        Compares current CPL to previous period and creates alerts
        if there's a significant increase.
        """
        alerts_created = []

        try:
            customer_id = account.google_customer_id
            if not customer_id:
                return alerts_created

            # Calculate date ranges
            end_date = datetime.utcnow().date()
            current_start = end_date - timedelta(days=lookback_days)
            previous_start = current_start - timedelta(days=lookback_days)
            previous_end = current_start - timedelta(days=1)

            # Query for current period CPL by campaign
            current_query = f"""
                SELECT
                    campaign.id,
                    campaign.name,
                    metrics.cost_micros,
                    metrics.conversions
                FROM campaign
                WHERE segments.date BETWEEN '{current_start}' AND '{end_date}'
                AND metrics.conversions > 0
            """

            # Query for previous period CPL by campaign
            previous_query = f"""
                SELECT
                    campaign.id,
                    campaign.name,
                    metrics.cost_micros,
                    metrics.conversions
                FROM campaign
                WHERE segments.date BETWEEN '{previous_start}' AND '{previous_end}'
                AND metrics.conversions > 0
            """

            current_data = self._aggregate_campaign_metrics(
                self._query_google_ads(account, current_query)
            )
            previous_data = self._aggregate_campaign_metrics(
                self._query_google_ads(account, previous_query)
            )

            # Compare CPL and create alerts for significant increases
            for campaign_id, current_metrics in current_data.items():
                if campaign_id not in previous_data:
                    continue  # No previous data to compare

                previous_metrics = previous_data[campaign_id]

                current_cpl = current_metrics["cpl"]
                previous_cpl = previous_metrics["cpl"]

                if previous_cpl == 0:
                    continue

                change_percent = ((current_cpl - previous_cpl) / previous_cpl) * 100

                if change_percent >= threshold_percent:
                    # Check for existing alert
                    existing_alert = Alert.query.filter_by(
                        account_id=account.id,
                        user_id=user_id,
                        alert_type="cpl_spike",
                        status="active"
                    ).filter(
                        Alert.data["campaign_id"].astext == str(campaign_id),
                        Alert.created_at >= datetime.utcnow() - timedelta(days=7)
                    ).first()

                    if existing_alert:
                        continue

                    # Determine severity
                    if change_percent >= 50:
                        severity = "critical"
                    elif change_percent >= 30:
                        severity = "warning"
                    else:
                        severity = "info"

                    alert = Alert(
                        account_id=account.id,
                        user_id=user_id,
                        alert_type="cpl_spike",
                        severity=severity,
                        title=f"CPL Spike: {current_metrics['campaign_name']}",
                        description=f"Cost per lead increased by {change_percent:.1f}% from ${previous_cpl:.2f} to ${current_cpl:.2f}",
                        data={
                            "campaign_id": str(campaign_id),
                            "campaign_name": current_metrics["campaign_name"],
                            "previous_cpl": round(previous_cpl, 2),
                            "current_cpl": round(current_cpl, 2),
                            "change_percent": round(change_percent, 1),
                            "current_period_days": lookback_days,
                            "current_conversions": current_metrics["conversions"],
                            "previous_conversions": previous_metrics["conversions"],
                            "detected_at": datetime.utcnow().isoformat()
                        },
                        action_url=f"/account/google/ads/campaigns/{campaign_id}",
                        action_text="Review Campaign"
                    )

                    db.session.add(alert)
                    alerts_created.append(alert)

        except Exception as e:
            logger.error(f"Error checking CPL spikes for account {account.id}: {e}")

        return alerts_created

    def check_quality_score_drops(
        self,
        account: Account,
        user_id: int,
        threshold: int = 5
    ) -> List[Alert]:
        """
        Check for Quality Score drops below threshold.

        Creates alerts when campaign average quality score drops below threshold.
        """
        alerts_created = []

        try:
            customer_id = account.google_customer_id
            if not customer_id:
                return alerts_created

            # Query for quality scores by campaign
            query = """
                SELECT
                    campaign.id,
                    campaign.name,
                    ad_group_criterion.quality_info.quality_score,
                    ad_group_criterion.keyword.text
                FROM keyword_view
                WHERE campaign.status = 'ENABLED'
                AND ad_group.status = 'ENABLED'
                AND ad_group_criterion.status = 'ENABLED'
                AND segments.date DURING LAST_30_DAYS
            """

            response = self._query_google_ads(account, query)

            # Aggregate quality scores by campaign
            campaign_qs_data = {}
            for row in response:
                campaign_id = row.campaign.id
                campaign_name = row.campaign.name
                quality_score = row.ad_group_criterion.quality_info.quality_score

                if campaign_id not in campaign_qs_data:
                    campaign_qs_data[campaign_id] = {
                        "campaign_name": campaign_name,
                        "scores": [],
                        "keywords": []
                    }

                if quality_score > 0:  # Exclude keywords without QS
                    campaign_qs_data[campaign_id]["scores"].append(quality_score)
                    if quality_score < threshold:
                        campaign_qs_data[campaign_id]["keywords"].append({
                            "keyword": row.ad_group_criterion.keyword.text,
                            "quality_score": quality_score
                        })

            # Create alerts for campaigns with low average QS
            for campaign_id, data in campaign_qs_data.items():
                if not data["scores"]:
                    continue

                avg_qs = sum(data["scores"]) / len(data["scores"])

                if avg_qs < threshold:
                    # Check for existing alert
                    existing_alert = Alert.query.filter_by(
                        account_id=account.id,
                        user_id=user_id,
                        alert_type="quality_score_drop",
                        status="active"
                    ).filter(
                        Alert.data["campaign_id"].astext == str(campaign_id),
                        Alert.created_at >= datetime.utcnow() - timedelta(days=7)
                    ).first()

                    if existing_alert:
                        continue

                    # Determine severity
                    if avg_qs < 3:
                        severity = "critical"
                    elif avg_qs < 5:
                        severity = "warning"
                    else:
                        severity = "info"

                    low_qs_keywords = [k for k in data["keywords"] if k["quality_score"] < threshold]

                    alert = Alert(
                        account_id=account.id,
                        user_id=user_id,
                        alert_type="quality_score_drop",
                        severity=severity,
                        title=f"Low Quality Score: {data['campaign_name']}",
                        description=f"Average quality score is {avg_qs:.1f}, below threshold of {threshold}. {len(low_qs_keywords)} keywords need attention.",
                        data={
                            "campaign_id": str(campaign_id),
                            "campaign_name": data["campaign_name"],
                            "average_quality_score": round(avg_qs, 2),
                            "threshold": threshold,
                            "keywords_below_threshold": len(low_qs_keywords),
                            "total_keywords": len(data["scores"]),
                            "sample_keywords": low_qs_keywords[:10],  # First 10 low QS keywords
                            "detected_at": datetime.utcnow().isoformat()
                        },
                        action_url=f"/account/google/ads/campaigns/{campaign_id}/keywords",
                        action_text="Review Keywords"
                    )

                    db.session.add(alert)
                    alerts_created.append(alert)

        except Exception as e:
            logger.error(f"Error checking quality scores for account {account.id}: {e}")

        return alerts_created

    def _aggregate_campaign_metrics(self, query_response) -> Dict[str, Dict[str, Any]]:
        """
        Aggregate metrics by campaign from Google Ads query response.

        Returns: {campaign_id: {campaign_name, cost, conversions, cpl}}
        """
        campaign_data = {}

        for row in query_response:
            campaign_id = row.campaign.id
            campaign_name = row.campaign.name

            if campaign_id not in campaign_data:
                campaign_data[campaign_id] = {
                    "campaign_name": campaign_name,
                    "cost_micros": 0,
                    "conversions": 0
                }

            campaign_data[campaign_id]["cost_micros"] += row.metrics.cost_micros
            campaign_data[campaign_id]["conversions"] += row.metrics.conversions

        # Calculate CPL
        for campaign_id, data in campaign_data.items():
            cost_dollars = data["cost_micros"] / 1_000_000
            conversions = data["conversions"]
            cpl = cost_dollars / conversions if conversions > 0 else 0

            campaign_data[campaign_id]["cost"] = cost_dollars
            campaign_data[campaign_id]["cpl"] = cpl

        return campaign_data

    def get_active_alerts_for_user(
        self,
        user_id: int,
        limit: int = 50,
        alert_type: Optional[str] = None
    ) -> List[Alert]:
        """Get active alerts for a user."""
        query = Alert.query.filter_by(user_id=user_id, status="active")

        if alert_type:
            query = query.filter_by(alert_type=alert_type)

        return query.order_by(Alert.created_at.desc()).limit(limit).all()

    def get_alert_summary_for_user(self, user_id: int) -> Dict[str, Any]:
        """Get summary of alerts for a user."""
        active_count = Alert.query.filter_by(user_id=user_id, status="active").count()

        critical_count = Alert.query.filter_by(
            user_id=user_id,
            status="active",
            severity="critical"
        ).count()

        # Count by type
        type_counts = db.session.query(
            Alert.alert_type,
            func.count(Alert.id)
        ).filter_by(
            user_id=user_id,
            status="active"
        ).group_by(Alert.alert_type).all()

        return {
            "active_alerts": active_count,
            "critical_alerts": critical_count,
            "alerts_by_type": {alert_type: count for alert_type, count in type_counts}
        }
