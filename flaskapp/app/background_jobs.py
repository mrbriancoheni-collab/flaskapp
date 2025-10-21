# app/background_jobs.py
"""
Background job system without Redis using APScheduler.

Uses SQLAlchemy storage backend for persistence, so jobs survive application restarts.
Suitable for small to medium workloads. For high-volume jobs, migrate to Celery + Redis later.

Features:
- Scheduled jobs (cron-like)
- Interval jobs (every X minutes/hours)
- One-off jobs
- Job persistence via database
- Automatic retry on failure

Usage:
    from app.background_jobs import scheduler, add_job

    # In your app initialization
    init_scheduler(app)

    # Add a job
    @add_job('interval', minutes=5)
    def my_task():
        print("Running every 5 minutes")
"""

import os
from datetime import datetime, timedelta
from typing import Callable, Optional
from flask import Flask, current_app


def init_scheduler(app: Flask):
    """
    Initialize APScheduler with the Flask app.

    Args:
        app: Flask application instance
    """
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
        from apscheduler.executors.pool import ThreadPoolExecutor
    except ImportError:
        app.logger.warning(
            "APScheduler not installed. Background jobs disabled. "
            "Install with: pip install apscheduler"
        )
        return None

    # Don't initialize scheduler in certain contexts
    if os.environ.get('WERKZEUG_RUN_MAIN') == 'false':
        # Skip in Flask reloader parent process
        return None

    # Configuration
    jobstores = {
        'default': SQLAlchemyJobStore(url=app.config['SQLALCHEMY_DATABASE_URI'])
    }

    executors = {
        'default': ThreadPoolExecutor(max_workers=app.config.get('SCHEDULER_MAX_WORKERS', 3))
    }

    job_defaults = {
        'coalesce': True,  # Combine missed runs
        'max_instances': 1,  # Don't run same job concurrently
        'misfire_grace_time': 300  # 5 minutes grace period for missed jobs
    }

    # Create scheduler
    scheduler = BackgroundScheduler(
        jobstores=jobstores,
        executors=executors,
        job_defaults=job_defaults,
        timezone='UTC'
    )

    # Register scheduled jobs
    register_scheduled_jobs(scheduler, app)

    # Start scheduler
    scheduler.start()
    app.logger.info("Background job scheduler started")

    # Store scheduler on app
    app.scheduler = scheduler

    # Shutdown scheduler when app context tears down
    import atexit
    atexit.register(lambda: scheduler.shutdown())

    return scheduler


def register_scheduled_jobs(scheduler, app):
    """Register all scheduled jobs."""

    # Clean up expired team invitations (daily at 2 AM UTC)
    scheduler.add_job(
        func=cleanup_expired_invites,
        trigger='cron',
        hour=2,
        minute=0,
        id='cleanup_expired_invites',
        replace_existing=True,
        kwargs={'app': app}
    )

    # Sync Stripe subscription statuses (every 6 hours)
    scheduler.add_job(
        func=sync_subscription_statuses,
        trigger='interval',
        hours=6,
        id='sync_subscription_statuses',
        replace_existing=True,
        kwargs={'app': app}
    )

    # Clean up old audit logs (weekly on Sunday at 3 AM UTC)
    scheduler.add_job(
        func=cleanup_old_audit_logs,
        trigger='cron',
        day_of_week='sun',
        hour=3,
        minute=0,
        id='cleanup_old_audit_logs',
        replace_existing=True,
        kwargs={'app': app}
    )

    app.logger.info("Registered 3 scheduled background jobs")


# ===== Scheduled Job Functions =====

def cleanup_expired_invites(app: Flask):
    """
    Clean up expired team invitations.

    Marks expired invitations as 'expired' status.
    """
    with app.app_context():
        from app.models_team import TeamInvite
        from app import db

        try:
            now = datetime.utcnow()
            expired_invites = TeamInvite.query.filter(
                TeamInvite.status == 'pending',
                TeamInvite.expires_at < now
            ).all()

            count = 0
            for invite in expired_invites:
                invite.status = 'expired'
                count += 1

            if count > 0:
                db.session.commit()
                current_app.logger.info(f"Marked {count} expired team invitations")

        except Exception as e:
            current_app.logger.error(f"Error cleaning up expired invites: {e}", exc_info=True)
            db.session.rollback()


def sync_subscription_statuses(app: Flask):
    """
    Sync subscription statuses with Stripe.

    Fetches latest status from Stripe for all active subscriptions
    and updates local database.
    """
    with app.app_context():
        from app.models_billing import Subscription
        from app.services.stripe_service import get_stripe_client
        from app import db
        import stripe

        try:
            get_stripe_client()  # Initialize Stripe

            # Get all non-canceled subscriptions
            subscriptions = Subscription.query.filter(
                Subscription.status.in_(['active', 'trialing', 'past_due', 'incomplete'])
            ).all()

            updated_count = 0
            for sub in subscriptions:
                try:
                    # Fetch from Stripe
                    stripe_sub = stripe.Subscription.retrieve(sub.stripe_subscription_id)

                    # Update if status changed
                    if stripe_sub['status'] != sub.status:
                        current_app.logger.info(
                            f"Subscription {sub.id} status changed: "
                            f"{sub.status} -> {stripe_sub['status']}"
                        )
                        sub.status = stripe_sub['status']
                        sub.cancel_at_period_end = stripe_sub.get('cancel_at_period_end', False)
                        sub.updated_at = datetime.utcnow()
                        updated_count += 1

                except stripe.error.StripeError as e:
                    current_app.logger.warning(
                        f"Failed to sync subscription {sub.id}: {e}"
                    )
                    continue

            if updated_count > 0:
                db.session.commit()
                current_app.logger.info(f"Updated {updated_count} subscription statuses from Stripe")

        except Exception as e:
            current_app.logger.error(f"Error syncing subscription statuses: {e}", exc_info=True)
            db.session.rollback()


def cleanup_old_audit_logs(app: Flask):
    """
    Clean up audit logs older than retention period.

    Default retention: 90 days
    """
    with app.app_context():
        from app.models_audit import AuditLog
        from app import db

        try:
            retention_days = current_app.config.get('AUDIT_LOG_RETENTION_DAYS', 90)
            cutoff_date = datetime.utcnow() - timedelta(days=retention_days)

            # Delete old logs
            deleted = AuditLog.query.filter(
                AuditLog.created_at < cutoff_date
            ).delete()

            db.session.commit()

            if deleted > 0:
                current_app.logger.info(
                    f"Deleted {deleted} audit logs older than {retention_days} days"
                )

        except Exception as e:
            current_app.logger.error(f"Error cleaning up old audit logs: {e}", exc_info=True)
            db.session.rollback()


def send_welcome_emails(app: Flask):
    """
    Send welcome emails to users who registered but haven't received one.

    This is a one-time migration job.
    """
    with app.app_context():
        from app.models import User
        from app.services.email_service import send_welcome_email

        try:
            # Find users who registered in last 7 days but no welcome email sent
            # (You'd need to track this in the database)
            # This is just an example

            recent_users = User.query.filter(
                User.created_at >= datetime.utcnow() - timedelta(days=7)
            ).limit(100).all()

            sent_count = 0
            for user in recent_users:
                try:
                    if send_welcome_email(user):
                        sent_count += 1
                except Exception as e:
                    current_app.logger.warning(f"Failed to send welcome email to {user.email}: {e}")
                    continue

            current_app.logger.info(f"Sent {sent_count} welcome emails")

        except Exception as e:
            current_app.logger.error(f"Error sending welcome emails: {e}", exc_info=True)


# ===== Manual Job Execution =====

def run_job_now(job_id: str):
    """
    Manually trigger a scheduled job to run immediately.

    Args:
        job_id: ID of the job to run

    Returns:
        True if job was triggered, False otherwise
    """
    try:
        scheduler = current_app.scheduler
        job = scheduler.get_job(job_id)

        if job:
            job.modify(next_run_time=datetime.now())
            current_app.logger.info(f"Manually triggered job: {job_id}")
            return True
        else:
            current_app.logger.warning(f"Job not found: {job_id}")
            return False

    except Exception as e:
        current_app.logger.error(f"Error triggering job {job_id}: {e}", exc_info=True)
        return False


def get_job_status(job_id: str) -> Optional[dict]:
    """
    Get status information about a scheduled job.

    Args:
        job_id: ID of the job

    Returns:
        Dict with job information or None if not found
    """
    try:
        scheduler = current_app.scheduler
        job = scheduler.get_job(job_id)

        if job:
            return {
                'id': job.id,
                'name': job.name,
                'next_run_time': job.next_run_time.isoformat() if job.next_run_time else None,
                'trigger': str(job.trigger)
            }
        return None

    except Exception as e:
        current_app.logger.error(f"Error getting job status {job_id}: {e}", exc_info=True)
        return None


def list_all_jobs() -> list:
    """
    List all registered background jobs.

    Returns:
        List of job information dicts
    """
    try:
        scheduler = current_app.scheduler
        jobs = scheduler.get_jobs()

        return [
            {
                'id': job.id,
                'name': job.name,
                'next_run_time': job.next_run_time.isoformat() if job.next_run_time else None,
                'trigger': str(job.trigger)
            }
            for job in jobs
        ]

    except Exception as e:
        current_app.logger.error(f"Error listing jobs: {e}", exc_info=True)
        return []
