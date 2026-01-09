# app/tasks/alert_tasks.py
"""
Background tasks for alert detection and notification.

These tasks should be run periodically (e.g., via cron or Celery) to:
- Check for new alerts
- Send email notifications
- Clean up old resolved alerts
"""

import logging
from datetime import datetime, timedelta
from typing import List

from app import create_app, db
from app.models import User
from app.models_alerts import Alert, AlertSettings
from app.services.alert_detection_service import AlertDetectionService
from app.services.alert_throttle_service import AlertThrottleService
from app.services.email_service import send_email

logger = logging.getLogger(__name__)


def check_alerts_for_all_users():
    """
    Check alerts for all active users with Google Ads connections.

    Should be run hourly via cron.
    """
    app = create_app()
    with app.app_context():
        logger.info("Starting alert check for all users")

        detection_service = AlertDetectionService()

        # Get all active users with Google Ads accounts
        users_with_ads = db.session.query(User).join(
            User.accounts
        ).filter(
            User.accounts.any(google_refresh_token__ne=None)
        ).distinct().all()

        total_alerts_created = 0
        users_checked = 0

        for user in users_with_ads:
            try:
                result = detection_service.check_all_alerts_for_user(user.id)
                total_alerts_created += result.get("alerts_created", 0)
                users_checked += 1

                logger.info(
                    f"Checked alerts for user {user.id}: "
                    f"{result.get('alerts_created', 0)} new alerts"
                )

            except Exception as e:
                logger.error(f"Error checking alerts for user {user.id}: {e}")
                continue

        logger.info(
            f"Alert check complete: {users_checked} users checked, "
            f"{total_alerts_created} total alerts created"
        )

        return {
            "users_checked": users_checked,
            "total_alerts_created": total_alerts_created
        }


def send_alert_notifications():
    """
    Send email notifications for unsent alerts.

    Should be run every 15 minutes via cron.
    """
    app = create_app()
    with app.app_context():
        logger.info("Starting alert notification sending")

        # Get all active alerts that haven't been notified
        unsent_alerts = Alert.query.filter_by(
            status="active",
            email_sent=False
        ).order_by(Alert.created_at.asc()).limit(100).all()

        notifications_sent = 0
        notifications_failed = 0

        for alert in unsent_alerts:
            try:
                # Check if user has email notifications enabled
                settings = AlertSettings.get_or_create_for_user(alert.user_id)

                if not settings.email_notifications_enabled:
                    alert.mark_notified()  # Mark as notified even if disabled
                    continue

                # Check throttling (cooldown periods, etc.)
                if not AlertThrottleService.should_send_notification(alert):
                    logger.info(f"Notification throttled for alert {alert.id} (cooldown active)")
                    continue

                # Send email notification
                success = _send_alert_email(alert)

                if success:
                    alert.mark_notified()
                    notifications_sent += 1
                    logger.info(f"Sent notification for alert {alert.id}")
                else:
                    notifications_failed += 1
                    logger.error(f"Failed to send notification for alert {alert.id}")

            except Exception as e:
                logger.error(f"Error sending notification for alert {alert.id}: {e}")
                notifications_failed += 1
                continue

        db.session.commit()

        logger.info(
            f"Alert notifications complete: {notifications_sent} sent, "
            f"{notifications_failed} failed"
        )

        return {
            "notifications_sent": notifications_sent,
            "notifications_failed": notifications_failed
        }


def _send_alert_email(alert: Alert) -> bool:
    """Send email notification for an alert."""
    try:
        from app.models import User, Account

        user = User.query.get(alert.user_id)
        account = Account.query.get(alert.account_id)

        if not user or not user.email:
            logger.warning(f"No email for user {alert.user_id}")
            return False

        # Determine email severity styling
        if alert.severity == "critical":
            severity_color = "#dc2626"  # red-600
            severity_emoji = "🚨"
        elif alert.severity == "warning":
            severity_color = "#f59e0b"  # yellow-500
            severity_emoji = "⚠️"
        else:
            severity_color = "#3b82f6"  # blue-500
            severity_emoji = "ℹ️"

        # Build email HTML
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
                    {severity_emoji} Google Ads Alert
                </h1>
                <p style="margin: 10px 0 0 0; opacity: 0.9; font-size: 14px;">
                    FieldSprout Monitoring
                </p>
            </div>

            <div style="background: white; padding: 30px; border: 2px solid #e5e7eb; border-top: none; border-radius: 0 0 12px 12px;">
                <!-- Alert Header -->
                <div style="background: {severity_color}15; border-left: 4px solid {severity_color}; padding: 15px; border-radius: 8px; margin-bottom: 20px;">
                    <div style="font-size: 12px; text-transform: uppercase; font-weight: 600; color: {severity_color}; margin-bottom: 5px;">
                        {alert.severity.upper()} ALERT
                    </div>
                    <div style="font-size: 20px; font-weight: 700; color: #1f2937;">
                        {alert.title}
                    </div>
                </div>

                <!-- Alert Description -->
                <div style="margin-bottom: 20px; color: #4b5563; font-size: 15px;">
                    {alert.description}
                </div>

                <!-- Alert Details -->
                <div style="background: #f9fafb; padding: 15px; border-radius: 8px; margin-bottom: 20px;">
                    <table style="width: 100%; font-size: 14px;">
                        <tr>
                            <td style="padding: 5px 0; color: #6b7280; font-weight: 600;">Account:</td>
                            <td style="padding: 5px 0; color: #1f2937;">{account.business_name if account else 'N/A'}</td>
                        </tr>
                        <tr>
                            <td style="padding: 5px 0; color: #6b7280; font-weight: 600;">Alert Type:</td>
                            <td style="padding: 5px 0; color: #1f2937;">{alert.alert_type.replace('_', ' ').title()}</td>
                        </tr>
                        <tr>
                            <td style="padding: 5px 0; color: #6b7280; font-weight: 600;">Detected:</td>
                            <td style="padding: 5px 0; color: #1f2937;">{alert.created_at.strftime('%Y-%m-%d %H:%M UTC')}</td>
                        </tr>
                    </table>
                </div>

                <!-- Action Button -->
                {f'''
                <div style="text-align: center; margin: 30px 0;">
                    <a href="https://fieldsprout.io{alert.action_url}"
                       style="display: inline-block; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; text-decoration: none; padding: 14px 32px; border-radius: 8px; font-weight: 600; font-size: 16px;">
                        {alert.action_text}
                    </a>
                </div>
                ''' if alert.action_url else ''}

                <!-- Footer -->
                <div style="margin-top: 30px; padding-top: 20px; border-top: 1px solid #e5e7eb; text-align: center; color: #6b7280; font-size: 12px;">
                    <p style="margin: 0 0 10px 0;">
                        You're receiving this alert because you have monitoring enabled for your Google Ads accounts.
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
{severity_emoji} Google Ads Alert

{alert.severity.upper()}: {alert.title}

{alert.description}

Account: {account.business_name if account else 'N/A'}
Alert Type: {alert.alert_type.replace('_', ' ').title()}
Detected: {alert.created_at.strftime('%Y-%m-%d %H:%M UTC')}

{f"Take Action: https://fieldsprout.io{alert.action_url}" if alert.action_url else ''}

---
You're receiving this alert because you have monitoring enabled for your Google Ads accounts.
Manage settings: https://fieldsprout.io/account/settings
        """

        # Send email
        success = send_email(
            to=user.email,
            subject=f"{severity_emoji} {alert.title}",
            html_body=html_body,
            text_body=text_body
        )

        return success

    except Exception as e:
        logger.error(f"Error sending alert email: {e}")
        return False


def cleanup_old_alerts():
    """
    Clean up resolved/dismissed alerts older than 30 days.

    Should be run daily via cron.
    """
    app = create_app()
    with app.app_context():
        logger.info("Starting alert cleanup")

        cutoff_date = datetime.utcnow() - timedelta(days=30)

        # Delete old resolved alerts
        resolved_deleted = Alert.query.filter(
            Alert.status == "resolved",
            Alert.resolved_at < cutoff_date
        ).delete()

        # Delete old dismissed alerts
        dismissed_deleted = Alert.query.filter(
            Alert.status == "dismissed",
            Alert.dismissed_at < cutoff_date
        ).delete()

        db.session.commit()

        total_deleted = resolved_deleted + dismissed_deleted

        logger.info(
            f"Alert cleanup complete: {total_deleted} old alerts deleted "
            f"({resolved_deleted} resolved, {dismissed_deleted} dismissed)"
        )

        return {
            "resolved_deleted": resolved_deleted,
            "dismissed_deleted": dismissed_deleted,
            "total_deleted": total_deleted
        }


# ========== Cron Job Setup Instructions ==========
# Add these lines to your crontab (crontab -e):
#
# # Check alerts every hour
# 0 * * * * cd /path/to/flaskapp && python -c "from app.tasks.alert_tasks import check_alerts_for_all_users; check_alerts_for_all_users()"
#
# # Send notifications every 15 minutes
# */15 * * * * cd /path/to/flaskapp && python -c "from app.tasks.alert_tasks import send_alert_notifications; send_alert_notifications()"
#
# # Clean up old alerts daily at 2 AM
# 0 2 * * * cd /path/to/flaskapp && python -c "from app.tasks.alert_tasks import cleanup_old_alerts; cleanup_old_alerts()"
