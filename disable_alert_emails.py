#!/usr/bin/env python3
"""
Disable Site Alert Emails

This script:
1. Disables email notifications for all users
2. Marks all active alerts as dismissed
3. Clears the email queue of alert emails

Run this on production to stop the alert emails immediately.
"""

import sys
import os

# Add the flaskapp directory to the path
sys.path.insert(0, '/home/fieldsprout/flaskapp')

from app import create_app, db
from app.models_alerts import Alert, AlertSettings
from app.models_billing import EmailQueue

def disable_alert_emails():
    """Disable all alert email notifications."""
    app = create_app()

    with app.app_context():
        print("=" * 60)
        print("DISABLING ALERT EMAILS")
        print("=" * 60)

        # 1. Disable email notifications for all users
        print("\n1. Disabling email notifications for all users...")
        settings = AlertSettings.query.all()
        disabled_count = 0
        for setting in settings:
            if setting.email_notifications_enabled:
                setting.email_notifications_enabled = False
                disabled_count += 1

        print(f"   ✓ Disabled email notifications for {disabled_count} users")

        # 2. Mark all active unsent alerts as dismissed
        print("\n2. Dismissing all active alerts...")
        active_alerts = Alert.query.filter_by(status='active', email_sent=False).all()
        for alert in active_alerts:
            alert.status = 'dismissed'
            alert.dismissed_at = db.func.now()

        print(f"   ✓ Dismissed {len(active_alerts)} active alerts")

        # 3. Clear email queue of alert-related emails
        print("\n3. Clearing alert emails from queue...")
        try:
            alert_emails = EmailQueue.query.filter(
                EmailQueue.status == 'pending',
                EmailQueue.subject.like('%Alert%')
            ).all()

            for email in alert_emails:
                email.status = 'cancelled'

            print(f"   ✓ Cancelled {len(alert_emails)} pending alert emails")
        except Exception as e:
            print(f"   ⚠ Could not clear email queue: {e}")

        # Commit all changes
        db.session.commit()

        print("\n" + "=" * 60)
        print("SUCCESS: All alert emails have been disabled!")
        print("=" * 60)
        print("\nTo re-enable alerts later:")
        print("  1. Go to https://fieldsprout.io/account/settings")
        print("  2. Enable 'Email Notifications' under Alert Settings")
        print()

if __name__ == '__main__':
    try:
        disable_alert_emails()
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
