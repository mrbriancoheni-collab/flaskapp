# app/services/alert_throttle_service.py
"""
Alert Throttling Service - Prevents email spam from repeated alerts.

Features:
- Deduplication: Prevents duplicate alerts for same issue
- Rate limiting: Limits notifications per alert type per time period
- Cooldown periods: Enforces minimum time between notifications
- Digest batching: Optional daily digest instead of immediate emails
"""

from datetime import datetime, timedelta
from typing import List, Dict, Optional
import logging
import hashlib

from app import db
from app.models_alerts import Alert, AlertSettings
from app.models import User

logger = logging.getLogger(__name__)


class AlertThrottleService:
    """Service for throttling and deduplicating alerts."""

    # Cooldown periods by severity (in minutes)
    COOLDOWN_PERIODS = {
        'critical': 60,      # 1 hour minimum between critical alerts
        'warning': 180,      # 3 hours minimum between warning alerts
        'info': 360,         # 6 hours minimum between info alerts
    }

    # Maximum alerts per type per day
    MAX_ALERTS_PER_TYPE_PER_DAY = {
        'paused_campaign': 3,
        'cpl_spike': 5,
        'quality_score_drop': 5,
        'custom': 10,
    }

    @classmethod
    def generate_alert_hash(cls, alert_type: str, account_id: int, data: Dict) -> str:
        """
        Generate a unique hash for an alert to detect duplicates.

        For example, if we already alerted about campaign X being paused,
        don't alert again until it's been resolved.
        """
        # Create a deterministic string from alert key data
        if alert_type == 'paused_campaign':
            key = f"{alert_type}:{account_id}:{data.get('campaign_id', '')}"
        elif alert_type == 'cpl_spike':
            key = f"{alert_type}:{account_id}:{data.get('campaign_id', '')}"
        elif alert_type == 'quality_score_drop':
            key = f"{alert_type}:{account_id}:{data.get('campaign_id', '')}"
        else:
            # For custom alerts, include title
            key = f"{alert_type}:{account_id}:{data.get('title', '')}"

        return hashlib.md5(key.encode()).hexdigest()

    @classmethod
    def should_create_alert(
        cls,
        alert_type: str,
        account_id: int,
        user_id: int,
        data: Dict
    ) -> bool:
        """
        Check if we should create a new alert or if it's a duplicate/too soon.

        Returns:
            True if alert should be created, False if it should be suppressed
        """
        # Generate hash for this alert
        alert_hash = cls.generate_alert_hash(alert_type, account_id, data)

        # Check for existing active alert with same hash
        existing_alert = Alert.query.filter_by(
            account_id=account_id,
            user_id=user_id,
            alert_type=alert_type,
            status='active'
        ).filter(
            Alert.data['alert_hash'].astext == alert_hash
        ).first()

        if existing_alert:
            logger.info(
                f"Suppressing duplicate alert: {alert_type} for account {account_id} "
                f"(existing alert #{existing_alert.id})"
            )
            return False

        # Check daily limit for this alert type
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        alerts_today = Alert.query.filter(
            Alert.account_id == account_id,
            Alert.user_id == user_id,
            Alert.alert_type == alert_type,
            Alert.created_at >= today_start
        ).count()

        max_allowed = cls.MAX_ALERTS_PER_TYPE_PER_DAY.get(alert_type, 10)
        if alerts_today >= max_allowed:
            logger.warning(
                f"Daily limit reached for {alert_type} alerts: {alerts_today}/{max_allowed} "
                f"for account {account_id}"
            )
            return False

        # All checks passed
        return True

    @classmethod
    def should_send_notification(cls, alert: Alert) -> bool:
        """
        Check if we should send an email notification for this alert.

        Enforces cooldown periods and checks user settings.
        """
        # Get user settings
        settings = AlertSettings.get_or_create_for_user(alert.user_id)

        # Check if email notifications are disabled
        if not settings.email_notifications_enabled:
            logger.info(f"Email notifications disabled for user {alert.user_id}")
            return False

        # Check if digest mode is enabled (batch notifications)
        if settings.email_digest_enabled:
            logger.info(f"Digest mode enabled for user {alert.user_id}, queuing for batch")
            return False

        # Check cooldown period for this severity
        cooldown_minutes = cls.COOLDOWN_PERIODS.get(alert.severity, 180)
        cooldown_cutoff = datetime.utcnow() - timedelta(minutes=cooldown_minutes)

        # Check if we recently sent a similar alert
        recent_alert = Alert.query.filter(
            Alert.account_id == alert.account_id,
            Alert.user_id == alert.user_id,
            Alert.alert_type == alert.alert_type,
            Alert.severity == alert.severity,
            Alert.email_sent == True,
            Alert.notified_at >= cooldown_cutoff
        ).first()

        if recent_alert:
            logger.info(
                f"Cooldown active for {alert.alert_type} (severity: {alert.severity}): "
                f"Last notification {alert.notified_at}, minimum wait {cooldown_minutes} min"
            )
            return False

        # All checks passed
        return True

    @classmethod
    def get_digest_alerts_for_user(cls, user_id: int) -> List[Alert]:
        """
        Get unsent alerts for user's daily digest.

        Returns alerts that haven't been sent yet and are ready for digest.
        """
        # Get alerts from last 24 hours that haven't been sent
        yesterday = datetime.utcnow() - timedelta(hours=24)

        alerts = Alert.query.filter(
            Alert.user_id == user_id,
            Alert.status == 'active',
            Alert.email_sent == False,
            Alert.created_at >= yesterday
        ).order_by(
            Alert.severity.desc(),  # Critical first
            Alert.created_at.desc()
        ).all()

        return alerts

    @classmethod
    def mark_alerts_as_stale(cls, hours: int = 72) -> int:
        """
        Automatically resolve alerts that are older than X hours and still active.

        This prevents old alerts from staying in "active" state forever.

        Args:
            hours: How many hours old before auto-resolving

        Returns:
            Number of alerts auto-resolved
        """
        cutoff = datetime.utcnow() - timedelta(hours=hours)

        stale_alerts = Alert.query.filter(
            Alert.status == 'active',
            Alert.created_at < cutoff
        ).all()

        count = 0
        for alert in stale_alerts:
            alert.status = 'resolved'
            alert.resolved_at = datetime.utcnow()
            count += 1
            logger.info(f"Auto-resolved stale alert #{alert.id} (age: {alert.age_hours:.1f} hours)")

        db.session.commit()

        logger.info(f"Auto-resolved {count} stale alerts older than {hours} hours")
        return count

    @classmethod
    def deduplicate_active_alerts(cls) -> int:
        """
        Find and resolve duplicate active alerts.

        If multiple active alerts exist for the same issue, keep only the newest.

        Returns:
            Number of duplicate alerts resolved
        """
        from sqlalchemy import func, and_

        # Find duplicate alerts (same type, account, and campaign_id)
        duplicates = db.session.query(
            Alert.alert_type,
            Alert.account_id,
            Alert.data['campaign_id'].astext,
            func.count(Alert.id).label('count')
        ).filter(
            Alert.status == 'active'
        ).group_by(
            Alert.alert_type,
            Alert.account_id,
            Alert.data['campaign_id'].astext
        ).having(
            func.count(Alert.id) > 1
        ).all()

        resolved_count = 0

        for alert_type, account_id, campaign_id, count in duplicates:
            # Get all alerts for this combination
            alerts = Alert.query.filter(
                Alert.alert_type == alert_type,
                Alert.account_id == account_id,
                Alert.status == 'active'
            ).filter(
                Alert.data['campaign_id'].astext == campaign_id
            ).order_by(Alert.created_at.desc()).all()

            # Keep the newest, resolve the rest
            for alert in alerts[1:]:  # Skip first (newest)
                alert.status = 'resolved'
                alert.resolved_at = datetime.utcnow()
                resolved_count += 1
                logger.info(
                    f"Resolved duplicate alert #{alert.id} "
                    f"(kept newer alert #{alerts[0].id})"
                )

        db.session.commit()

        logger.info(f"Deduplicated {resolved_count} duplicate active alerts")
        return resolved_count


def send_daily_digest(user_id: int) -> bool:
    """
    Send a daily digest email with all pending alerts for a user.

    Should be called once per day at the user's preferred time.
    """
    from app.services.email_service import send_email
    from app.models import User, Account

    user = User.query.get(user_id)
    if not user or not user.email:
        logger.warning(f"Cannot send digest: user {user_id} not found or no email")
        return False

    # Get settings
    settings = AlertSettings.get_or_create_for_user(user_id)
    if not settings.email_digest_enabled:
        logger.info(f"Digest not enabled for user {user_id}")
        return False

    # Get alerts for digest
    throttle = AlertThrottleService()
    alerts = throttle.get_digest_alerts_for_user(user_id)

    if not alerts:
        logger.info(f"No alerts to include in digest for user {user_id}")
        return True  # Not an error, just nothing to send

    # Group alerts by severity
    critical_alerts = [a for a in alerts if a.severity == 'critical']
    warning_alerts = [a for a in alerts if a.severity == 'warning']
    info_alerts = [a for a in alerts if a.severity == 'info']

    # Build HTML email
    html_body = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
    </head>
    <body style="font-family: system-ui, -apple-system, sans-serif; line-height: 1.6; color: #374151; max-width: 600px; margin: 0 auto; padding: 20px;">
        <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 30px; border-radius: 12px 12px 0 0; text-align: center;">
            <h1 style="margin: 0; font-size: 24px; font-weight: 700;">
                📊 Daily Google Ads Report
            </h1>
            <p style="margin: 10px 0 0 0; opacity: 0.9; font-size: 14px;">
                {len(alerts)} alert{"s" if len(alerts) != 1 else ""} from {datetime.utcnow().strftime('%B %d, %Y')}
            </p>
        </div>

        <div style="background: white; padding: 30px; border: 2px solid #e5e7eb; border-top: none; border-radius: 0 0 12px 12px;">
    """

    # Add critical alerts
    if critical_alerts:
        html_body += f"""
            <div style="margin-bottom: 30px;">
                <h2 style="color: #dc2626; font-size: 18px; margin-bottom: 15px;">
                    🚨 Critical ({len(critical_alerts)})
                </h2>
        """
        for alert in critical_alerts:
            html_body += f"""
                <div style="background: #fee2e2; border-left: 4px solid #dc2626; padding: 12px; margin-bottom: 10px; border-radius: 4px;">
                    <div style="font-weight: 600; color: #991b1b;">{alert.title}</div>
                    <div style="font-size: 14px; color: #7f1d1d; margin-top: 4px;">{alert.description}</div>
                </div>
            """
        html_body += "</div>"

    # Add warning alerts
    if warning_alerts:
        html_body += f"""
            <div style="margin-bottom: 30px;">
                <h2 style="color: #f59e0b; font-size: 18px; margin-bottom: 15px;">
                    ⚠️ Warnings ({len(warning_alerts)})
                </h2>
        """
        for alert in warning_alerts:
            html_body += f"""
                <div style="background: #fef3c7; border-left: 4px solid #f59e0b; padding: 12px; margin-bottom: 10px; border-radius: 4px;">
                    <div style="font-weight: 600; color: #92400e;">{alert.title}</div>
                    <div style="font-size: 14px; color: #78350f; margin-top: 4px;">{alert.description}</div>
                </div>
            """
        html_body += "</div>"

    # Add info alerts
    if info_alerts:
        html_body += f"""
            <div style="margin-bottom: 30px;">
                <h2 style="color: #3b82f6; font-size: 18px; margin-bottom: 15px;">
                    ℹ️ Info ({len(info_alerts)})
                </h2>
        """
        for alert in info_alerts:
            html_body += f"""
                <div style="background: #dbeafe; border-left: 4px solid #3b82f6; padding: 12px; margin-bottom: 10px; border-radius: 4px;">
                    <div style="font-weight: 600; color: #1e40af;">{alert.title}</div>
                    <div style="font-size: 14px; color: #1e3a8a; margin-top: 4px;">{alert.description}</div>
                </div>
            """
        html_body += "</div>"

    # Add footer
    html_body += f"""
            <div style="text-align: center; margin-top: 30px;">
                <a href="https://fieldsprout.io/account/google/ads/decision-screen"
                   style="display: inline-block; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; text-decoration: none; padding: 14px 32px; border-radius: 8px; font-weight: 600; font-size: 16px;">
                    View Dashboard
                </a>
            </div>

            <div style="margin-top: 30px; padding-top: 20px; border-top: 1px solid #e5e7eb; text-align: center; color: #6b7280; font-size: 12px;">
                <p style="margin: 0 0 10px 0;">
                    You're receiving this daily digest because you have alert notifications enabled.
                </p>
                <p style="margin: 0;">
                    <a href="https://fieldsprout.io/account/settings" style="color: #667eea; text-decoration: none;">
                        Manage alert settings
                    </a>
                </p>
            </div>
        </div>
    </body>
    </html>
    """

    # Plain text version
    text_body = f"""
Daily Google Ads Report - {datetime.utcnow().strftime('%B %d, %Y')}

{len(alerts)} alert{"s" if len(alerts) != 1 else ""} for today:

"""

    if critical_alerts:
        text_body += f"\n🚨 CRITICAL ({len(critical_alerts)}):\n\n"
        for alert in critical_alerts:
            text_body += f"- {alert.title}\n  {alert.description}\n\n"

    if warning_alerts:
        text_body += f"\n⚠️ WARNINGS ({len(warning_alerts)}):\n\n"
        for alert in warning_alerts:
            text_body += f"- {alert.title}\n  {alert.description}\n\n"

    if info_alerts:
        text_body += f"\nℹ️ INFO ({len(info_alerts)}):\n\n"
        for alert in info_alerts:
            text_body += f"- {alert.title}\n  {alert.description}\n\n"

    text_body += "\nView Dashboard: https://fieldsprout.io/account/google/ads/decision-screen\n"
    text_body += "Manage Settings: https://fieldsprout.io/account/settings\n"

    # Send email
    success = send_email(
        to=user.email,
        subject=f"📊 Daily Google Ads Report - {len(alerts)} Alert{'s' if len(alerts) != 1 else ''}",
        html_body=html_body,
        text_body=text_body
    )

    if success:
        # Mark all alerts as notified
        for alert in alerts:
            alert.mark_notified()
        db.session.commit()
        logger.info(f"Sent daily digest to user {user_id} with {len(alerts)} alerts")
    else:
        logger.error(f"Failed to send daily digest to user {user_id}")

    return success
