#!/usr/bin/env python3
"""
Fix Alert Spam - Cleanup Script

Resolves the "site alert" email spam issue by:
1. Deduplicating active alerts
2. Resolving stale alerts (>72 hours old)
3. Disabling immediate notifications (enable digest mode)
4. Displaying statistics

Run this script once to clean up existing spam alerts.
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from app.services.alert_throttle_service import AlertThrottleService
from app.models_alerts import Alert, AlertSettings
from app.models import User
from datetime import datetime, timedelta

def print_header(text):
    """Print a formatted header."""
    print("\n" + "=" * 70)
    print(f"  {text}")
    print("=" * 70 + "\n")

def print_stats():
    """Print current alert statistics."""
    print_header("Current Alert Statistics")

    total_alerts = Alert.query.count()
    active_alerts = Alert.query.filter_by(status='active').count()
    resolved_alerts = Alert.query.filter_by(status='resolved').count()
    dismissed_alerts = Alert.query.filter_by(status='dismissed').count()

    unsent_emails = Alert.query.filter_by(email_sent=False, status='active').count()

    print(f"Total Alerts:     {total_alerts}")
    print(f"  ├─ Active:      {active_alerts}")
    print(f"  ├─ Resolved:    {resolved_alerts}")
    print(f"  └─ Dismissed:   {dismissed_alerts}")
    print(f"\nUnsent Emails:    {unsent_emails}")

    # Group by type
    print("\nAlerts by Type:")
    from sqlalchemy import func
    alert_types = db.session.query(
        Alert.alert_type,
        func.count(Alert.id)
    ).filter(
        Alert.status == 'active'
    ).group_by(Alert.alert_type).all()

    for alert_type, count in alert_types:
        print(f"  ├─ {alert_type}: {count}")

    # Recent alerts
    recent_cutoff = datetime.utcnow() - timedelta(hours=24)
    recent_alerts = Alert.query.filter(Alert.created_at >= recent_cutoff).count()
    print(f"\nAlerts in Last 24h: {recent_alerts}")

def fix_duplicates():
    """Deduplicate active alerts."""
    print_header("Step 1: Deduplicating Active Alerts")

    throttle = AlertThrottleService()
    resolved = throttle.deduplicate_active_alerts()

    print(f"✓ Resolved {resolved} duplicate alerts")

def fix_stale_alerts():
    """Resolve stale alerts."""
    print_header("Step 2: Resolving Stale Alerts (>72 hours)")

    throttle = AlertThrottleService()
    resolved = throttle.mark_alerts_as_stale(hours=72)

    print(f"✓ Auto-resolved {resolved} stale alerts")

def enable_digest_mode():
    """Enable digest mode for all users."""
    print_header("Step 3: Enabling Daily Digest Mode")

    users = User.query.all()
    updated = 0

    for user in users:
        settings = AlertSettings.get_or_create_for_user(user.id)

        # Enable digest mode, disable immediate notifications
        if not settings.email_digest_enabled:
            settings.email_digest_enabled = True
            settings.email_digest_time = "09:00"  # 9 AM daily
            updated += 1

    db.session.commit()

    print(f"✓ Enabled digest mode for {updated} users")
    print("  └─ Users will now receive one daily email at 9 AM instead of immediate alerts")

def mark_pending_as_sent():
    """Mark all pending alerts as sent to stop spam."""
    print_header("Step 4: Marking Pending Alerts as Sent")

    pending = Alert.query.filter_by(
        email_sent=False,
        status='active'
    ).all()

    for alert in pending:
        alert.mark_notified()

    db.session.commit()

    print(f"✓ Marked {len(pending)} pending alerts as sent")
    print("  └─ This prevents backlog from triggering spam")

def main():
    """Main execution."""
    print_header("FieldSprout Alert Spam Fix")
    print("This script will:")
    print("  1. Remove duplicate active alerts")
    print("  2. Resolve stale alerts (>72 hours old)")
    print("  3. Enable daily digest mode for all users")
    print("  4. Mark pending alerts as sent")
    print("\nThis will prevent future email spam from alerts.")

    response = input("\nProceed? (yes/no): ").strip().lower()
    if response not in ['yes', 'y']:
        print("\nAborted.")
        return

    app = create_app()
    with app.app_context():
        # Show current stats
        print_stats()

        # Run fixes
        fix_duplicates()
        fix_stale_alerts()
        enable_digest_mode()
        mark_pending_as_sent()

        # Show updated stats
        print_stats()

        print_header("Fix Complete!")
        print("✓ Alert spam should now be resolved")
        print("\nNext Steps:")
        print("  1. Users will receive ONE daily email at 9 AM with all alerts")
        print("  2. Critical alerts still create notifications (but throttled)")
        print("  3. Duplicates are automatically prevented")
        print("\nTo customize settings per user:")
        print("  - Visit: https://fieldsprout.io/account/settings")
        print("  - Adjust alert preferences and digest time")

if __name__ == '__main__':
    main()
