"""
Budget Tracker Background Tasks

Scheduled tasks for budget tracking:
- Hourly spend updates
- Daily budget check reports
- Alert notifications
"""
import logging
from datetime import datetime

from app import create_app, db
from app.ads_grader.budget_tracker_service import update_all_active_trackers

logger = logging.getLogger(__name__)


def update_budget_trackers():
    """
    Update all active budget trackers with latest spend data.

    This task should be scheduled to run hourly via cron.
    Example cron entry:
        0 * * * * cd /path/to/app && python -m app.tasks.budget_tracker_tasks update
    """
    app = create_app()
    with app.app_context():
        logger.info("Starting budget tracker update task")

        try:
            results = update_all_active_trackers()

            logger.info(
                f"Budget tracker update completed: "
                f"{results['success']}/{results['total']} trackers updated, "
                f"{results['alerts_created']} alerts created, "
                f"{results['failed']} failed"
            )

            if results['errors']:
                logger.error(f"Errors during update: {results['errors']}")

            return results

        except Exception as e:
            logger.exception(f"Budget tracker update task failed: {e}")
            raise


def send_daily_budget_report():
    """
    Send daily budget status report to users.

    This task should be scheduled to run once daily via cron.
    Example cron entry:
        0 8 * * * cd /path/to/app && python -m app.tasks.budget_tracker_tasks daily_report
    """
    app = create_app()
    with app.app_context():
        logger.info("Starting daily budget report task")

        from app.models import BudgetTracker, User
        from app.services.email_service import send_email

        # Get all active trackers that are approaching their threshold
        active_trackers = BudgetTracker.query.filter_by(status="active").all()

        # Group by user
        users_to_notify = {}
        for tracker in active_trackers:
            if tracker.spend_percentage >= 50:  # Only notify if >50% spent
                if tracker.user_id not in users_to_notify:
                    users_to_notify[tracker.user_id] = []
                users_to_notify[tracker.user_id].append(tracker)

        # Send emails
        emails_sent = 0
        for user_id, trackers in users_to_notify.items():
            try:
                user = User.query.get(user_id)
                if user and user.email:
                    # TODO: Implement email template and sending
                    logger.info(f"Would send budget report to {user.email} for {len(trackers)} trackers")
                    emails_sent += 1
            except Exception as e:
                logger.error(f"Failed to send budget report to user {user_id}: {e}")

        logger.info(f"Daily budget report completed: {emails_sent} emails sent")
        return {"emails_sent": emails_sent, "users_notified": len(users_to_notify)}


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m app.tasks.budget_tracker_tasks <command>")
        print("Commands:")
        print("  update       - Update all budget trackers")
        print("  daily_report - Send daily budget reports")
        sys.exit(1)

    command = sys.argv[1]

    if command == "update":
        update_budget_trackers()
    elif command == "daily_report":
        send_daily_budget_report()
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)
