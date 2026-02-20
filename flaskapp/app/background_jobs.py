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

    # Only run scheduler in one Gunicorn worker to prevent duplicate jobs
    # The worker that gets the lock file first becomes the scheduler worker
    import fcntl
    lock_file_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.scheduler.lock')

    try:
        # Try to acquire exclusive lock (non-blocking)
        lock_file = open(lock_file_path, 'w')
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        # Store lock file handle to prevent garbage collection closing it
        app._scheduler_lock = lock_file
        app.logger.info("This worker acquired scheduler lock - will run background jobs")
    except (IOError, OSError):
        # Another worker already has the lock - skip scheduler initialization
        app.logger.info("Another worker has scheduler lock - skipping scheduler in this worker")
        return None

    # Configuration - use in-memory job store (simpler, no pickling issues)
    # Using 1 worker to minimize resource usage on shared hosting
    executors = {
        'default': ThreadPoolExecutor(max_workers=1)
    }

    job_defaults = {
        'coalesce': True,  # Combine missed runs
        'max_instances': 1,  # Don't run same job concurrently
        'misfire_grace_time': 300  # 5 minutes grace period for missed jobs
    }

    # Create scheduler (no jobstores = uses MemoryJobStore by default)
    scheduler = BackgroundScheduler(
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

    # Generate Google Ads AI insights (weekly on Monday at 8 AM UTC)
    # Note: High-spend accounts are checked daily by a separate daily job
    scheduler.add_job(
        func=generate_google_ads_insights_weekly,
        trigger='cron',
        day_of_week='mon',
        hour=8,
        minute=0,
        id='generate_google_ads_insights_weekly',
        replace_existing=True,
        kwargs={'app': app}
    )

    # Daily check for high-spend Google Ads accounts (daily at 9 AM UTC)
    scheduler.add_job(
        func=generate_google_ads_insights_daily,
        trigger='cron',
        hour=9,
        minute=0,
        id='generate_google_ads_insights_daily',
        replace_existing=True,
        kwargs={'app': app}
    )

    # Lead generation automation (daily at 8 AM Pacific Time)
    # Scrapes leads, enriches with contact info, and sends outreach emails
    scheduler.add_job(
        func=run_lead_automation_daily,
        trigger='cron',
        hour=8,
        minute=0,
        timezone='America/Los_Angeles',  # Pacific Time
        id='run_lead_automation_daily',
        replace_existing=True,
        kwargs={'app': app}
    )

    # Daily email blast to all unsent contacts (daily at 12 PM Pacific Time)
    # Runs 4 hours after main automation (8am PT) to catch any remaining contacts
    scheduler.add_job(
        func=send_to_all_unsent_today,
        trigger='cron',
        hour=12,
        minute=0,
        timezone='America/Los_Angeles',  # Pacific Time
        id='send_to_all_unsent_today',
        replace_existing=True,
        kwargs={'app': app}
    )

    # Process email queue (every 1 minute)
    scheduler.add_job(
        func=process_email_queue,
        trigger='interval',
        minutes=1,
        id='process_email_queue',
        replace_existing=True,
        kwargs={'app': app}
    )

    # Google Ads AI Agents - Tactical (every 2 hours)
    # Quick wins: bid adjustments, pause low CTR ads
    # Note: NegativeKeywordAgent has its own daily job below (search term data
    # has a 24h delay — running every 2h just re-analyses stale data)
    scheduler.add_job(
        func=run_tactical_agents,
        trigger='interval',
        hours=2,
        id='run_tactical_agents',
        replace_existing=True,
        kwargs={'app': app}
    )

    # Google Ads AI Agents - Negative Keywords (daily at 7 AM UTC)
    # Runs after strategic (6 AM) so search term data from the previous day
    # is fresh and the account context is up to date
    scheduler.add_job(
        func=run_negative_keyword_agents,
        trigger='cron',
        hour=7,
        minute=0,
        id='run_negative_keyword_agents',
        replace_existing=True,
        kwargs={'app': app}
    )

    # Google Ads AI Agents - Operational (every 6 hours)
    # Budget redistribution, pause underperformers, scale winners
    scheduler.add_job(
        func=run_operational_agents,
        trigger='interval',
        hours=6,
        id='run_operational_agents',
        replace_existing=True,
        kwargs={'app': app}
    )

    # Google Ads AI Agents - Strategic (daily at 6 AM UTC)
    # Campaign structure changes, new keyword themes, A/B test decisions
    scheduler.add_job(
        func=run_strategic_agents,
        trigger='cron',
        hour=6,
        minute=0,
        id='run_strategic_agents',
        replace_existing=True,
        kwargs={'app': app}
    )

    # Google Ads Auto-Executor (every 4 hours)
    # Automatically adds negative keywords, pauses low performers, adjusts bids
    # All actions logged with full audit trail and undo capability
    scheduler.add_job(
        func=run_google_ads_auto_executor,
        trigger='interval',
        hours=4,
        id='run_google_ads_auto_executor',
        replace_existing=True,
        kwargs={'app': app}
    )

    app.logger.info("Registered 11 scheduled background jobs")


# ===== Scheduled Job Functions =====

def cleanup_expired_invites(app: Flask):
    """
    Clean up expired team invitations.

    Marks expired invitations as 'expired' status.
    """
    with app.app_context():
        from app import db
        from sqlalchemy import inspect

        try:
            # Check if team_invites table exists before querying
            inspector = inspect(db.engine)
            if 'team_invites' not in inspector.get_table_names():
                # Table doesn't exist yet - skip this job silently
                return

            from app.models_team import TeamInvite

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


def generate_google_ads_insights_weekly(app: Flask):
    """
    Generate AI insights for all Google Ads accounts (weekly schedule).

    Skips high-spend accounts that get daily analysis.
    """
    with app.app_context():
        from app.services.google_ads_insights import generate_ai_insights, should_run_daily_analysis, get_account_performance_data
        from app.models import Account
        from app import db

        try:
            current_app.logger.info("Starting weekly Google Ads insights generation")

            # Get all accounts with Google Ads connected
            from app.models_google import GoogleOAuthToken
            accounts = Account.query.join(
                GoogleOAuthToken, Account.id == GoogleOAuthToken.account_id
            ).filter(
                GoogleOAuthToken.product == 'ads',
                Account.status == 'active'
            ).all()

            if not accounts:
                current_app.logger.info("No active Google Ads accounts found")
                return

            processed_count = 0
            skipped_high_spend = 0
            error_count = 0

            for account in accounts:
                try:
                    # Get account spend to determine frequency
                    perf_data = get_account_performance_data(account.id, days=7)
                    daily_spend = perf_data.get("account_summary", {}).get("daily_spend_avg", 0)

                    # Skip high-spend accounts (they get daily analysis)
                    frequency_check = should_run_daily_analysis(account.id, daily_spend)
                    if frequency_check is True or frequency_check == "twice_weekly":
                        current_app.logger.info(
                            f"Skipping account {account.id} (high-spend: ${daily_spend:.2f}/day - gets daily/twice-weekly analysis)"
                        )
                        skipped_high_spend += 1
                        continue

                    # Generate insights
                    current_app.logger.info(f"Generating weekly insights for account {account.id}")
                    insights = generate_ai_insights(account.id, scope="all", regenerate=True)

                    processed_count += 1

                    # Send weekly email with performance summary and optimizations
                    critical_count = len([
                        r for r in insights.get("recommendations", [])
                        if r.get("severity") == 1
                    ])

                    # Always send weekly email (includes performance summary + optimizations)
                    from app.models import User
                    user = User.query.filter_by(id=account.user_id).first() if hasattr(account, 'user_id') else None
                    if user:
                        from app.services.google_ads_insights import send_insights_email
                        send_insights_email(account.id, user.email, insights)
                        current_app.logger.info(
                            f"Account {account.id}: Sent weekly email with {len(insights.get('recommendations', []))} optimizations"
                            f"{f' (including {critical_count} critical)' if critical_count > 0 else ''}"
                        )

                except Exception as e:
                    current_app.logger.error(
                        f"Error generating insights for account {account.id}: {e}",
                        exc_info=True
                    )
                    error_count += 1
                    continue

            current_app.logger.info(
                f"Weekly Google Ads insights complete: "
                f"processed={processed_count}, skipped_high_spend={skipped_high_spend}, errors={error_count}"
            )

        except Exception as e:
            current_app.logger.error(f"Error in weekly Google Ads insights job: {e}", exc_info=True)


def send_to_all_unsent_today(app: Flask):
    """
    Smart delay-based email sequencing system.

    This runs daily (2 PM UTC) to progress contacts through multi-step email sequences.

    For each contact, this:
    1. Finds which sequence steps they've already received
    2. Determines the next step in their campaign's sequence
    3. Checks if enough delay_days have passed since last email
    4. Sends the next step if eligible

    This automatically handles multi-step nurture campaigns:
    - Step 1 (initial outreach) → wait X days → Step 2 (follow-up) → wait Y days → Step 3, etc.
    - Respects delay_days configured in each EmailSequence
    - Respects daily limit (250 emails/day)
    - Respects unsubscribe list (CAN-SPAM compliance)
    """
    with app.app_context():
        try:
            # Check if automation is enabled
            enabled = current_app.config.get("LEAD_AUTOMATION_ENABLED", True)
            if not enabled:
                current_app.logger.info("[JOB] Lead automation disabled - skipping smart sequence progression")
                return

            from app.cron_tasks import _send_next_sequence_steps

            current_app.logger.info("[JOB] Starting smart sequence progression")
            _send_next_sequence_steps(current_app)
            current_app.logger.info("[JOB] Smart sequence progression completed")

        except Exception as e:
            current_app.logger.error(f"Error in smart sequence progression job: {e}", exc_info=True)


def process_email_queue(app: Flask):
    """
    Process pending emails in the queue.

    Sends queued emails with retry logic (max 3 attempts).
    """
    with app.app_context():
        from app.models_billing import EmailQueue
        from app.services.email_service import send_email
        from app import db

        try:
            # Get pending emails (oldest first, limit to 50 per run)
            pending_emails = EmailQueue.query.filter_by(status='pending').filter(
                EmailQueue.attempts < EmailQueue.max_attempts
            ).order_by(EmailQueue.created_at).limit(50).all()

            if not pending_emails:
                return

            sent_count = 0
            failed_count = 0

            for email_item in pending_emails:
                try:
                    # Attempt to send email
                    send_email(
                        to=email_item.to_email,
                        subject=email_item.subject,
                        html_body=email_item.html_body,
                        text_body=email_item.text_body,
                        use_bulk_credentials=email_item.use_bulk_credentials
                    )

                    # Mark as sent
                    email_item.status = 'sent'
                    email_item.sent_at = datetime.utcnow()
                    sent_count += 1

                    current_app.logger.info(
                        f"Sent queued email {email_item.id} to {email_item.to_email}"
                    )

                except Exception as e:
                    # Increment attempts
                    email_item.attempts += 1
                    email_item.error_message = str(e)[:1000]

                    # Mark as failed if max attempts reached
                    if email_item.attempts >= email_item.max_attempts:
                        email_item.status = 'failed'
                        failed_count += 1
                        current_app.logger.error(
                            f"Email {email_item.id} failed after {email_item.attempts} attempts: {e}"
                        )
                    else:
                        current_app.logger.warning(
                            f"Email {email_item.id} failed (attempt {email_item.attempts}): {e}"
                        )

                # Commit after each email to avoid losing progress
                db.session.commit()

            if sent_count > 0 or failed_count > 0:
                current_app.logger.info(
                    f"Email queue processed: sent={sent_count}, failed={failed_count}"
                )

        except Exception as e:
            current_app.logger.error(f"Error processing email queue: {e}", exc_info=True)
            db.session.rollback()


def generate_google_ads_insights_daily(app: Flask):
    """
    Generate AI insights for high-spend Google Ads accounts (daily schedule).

    Only processes accounts with spend >= $500/day.
    """
    with app.app_context():
        from app.services.google_ads_insights import generate_ai_insights, should_run_daily_analysis, get_account_performance_data
        from app.models import Account
        from app import db

        try:
            current_app.logger.info("Starting daily Google Ads insights generation for high-spend accounts")

            # Get all accounts with Google Ads connected
            from app.models_google import GoogleOAuthToken
            accounts = Account.query.join(
                GoogleOAuthToken, Account.id == GoogleOAuthToken.account_id
            ).filter(
                GoogleOAuthToken.product == 'ads',
                Account.status == 'active'
            ).all()

            if not accounts:
                current_app.logger.info("No active Google Ads accounts found")
                return

            processed_count = 0
            skipped_low_spend = 0
            error_count = 0

            for account in accounts:
                try:
                    # Get account spend to determine frequency
                    perf_data = get_account_performance_data(account.id, days=7)
                    daily_spend = perf_data.get("account_summary", {}).get("daily_spend_avg", 0)

                    # Only process high-spend accounts
                    frequency_check = should_run_daily_analysis(account.id, daily_spend)
                    if frequency_check is not True:
                        skipped_low_spend += 1
                        continue

                    # Generate insights
                    current_app.logger.info(
                        f"Generating daily insights for high-spend account {account.id} (${daily_spend:.2f}/day)"
                    )
                    insights = generate_ai_insights(account.id, scope="all", regenerate=True)

                    processed_count += 1

                    # Send email notification for high-spend accounts (always notify for daily)
                    from app.models import User
                    user = User.query.filter_by(id=account.user_id).first() if hasattr(account, 'user_id') else None
                    if user:
                        from app.services.google_ads_insights import send_insights_email
                        send_insights_email(account.id, user.email, insights)

                except Exception as e:
                    current_app.logger.error(
                        f"Error generating insights for account {account.id}: {e}",
                        exc_info=True
                    )
                    error_count += 1
                    continue

            current_app.logger.info(
                f"Daily Google Ads insights complete: "
                f"processed={processed_count}, skipped_low_spend={skipped_low_spend}, errors={error_count}"
            )

        except Exception as e:
            current_app.logger.error(f"Error in daily Google Ads insights job: {e}", exc_info=True)


def run_lead_automation_daily(app: Flask):
    """
    Run daily lead generation automation.

    This systematically:
    - Creates campaigns for cities and service categories
    - Scrapes leads from Google (respects daily limits: 50/day)
    - Enriches leads with decision maker info (respects daily limits: 100/day)
    - Sends automated emails (respects daily limits: 250/day, skips Sundays)
    - Resumes from where it stopped previously
    """
    with app.app_context():
        try:
            # Check if automation is enabled
            enabled = current_app.config.get("LEAD_AUTOMATION_ENABLED", True)
            if not enabled:
                current_app.logger.info("[JOB] Lead automation disabled via config")
                return

            from app.cron_tasks import _run_daily_lead_automation

            current_app.logger.info("[JOB] Starting daily lead automation")
            _run_daily_lead_automation(current_app)
            current_app.logger.info("[JOB] Daily lead automation completed")

        except Exception as e:
            current_app.logger.error(f"Error in daily lead automation job: {e}", exc_info=True)


def run_tactical_agents(app: Flask):
    """
    Run tactical-layer AI agents for all active Google Ads accounts.

    Tactical agents make quick, high-frequency optimizations:
    - Keyword bid adjustments based on performance
    - Pause low-performing ads (CTR < 1%)
    - Add high-performing broad match queries as exact match

    Runs every 2 hours. NegativeKeywordAgent runs separately at 7 AM daily
    because search term data has a ~24h reporting delay.
    """
    with app.app_context():
        try:
            current_app.logger.info("[JOB] Starting tactical agents for all accounts")

            from app.tasks.agent_scheduler import run_agents_for_all_accounts

            success_count, error_count = run_agents_for_all_accounts(layer='tactical')

            current_app.logger.info(
                f"[JOB] Tactical agents completed: {success_count} succeeded, {error_count} failed"
            )

        except Exception as e:
            current_app.logger.error(f"Error running tactical agents: {e}", exc_info=True)


def run_negative_keyword_agents(app: Flask):
    """
    Run NegativeKeywordAgent daily for all active Google Ads accounts.

    Runs once per day rather than every 2 hours because Google Ads search term
    data has a ~24 hour reporting delay — more frequent runs just re-analyse
    yesterday's data. A daily run ensures we always work on fresh data and
    systematically block wasteful queries before they burn more budget.
    """
    with app.app_context():
        try:
            current_app.logger.info("[JOB] Starting daily negative keyword analysis for all accounts")

            from app.tasks.agent_scheduler import run_agents_for_all_accounts

            success_count, error_count = run_agents_for_all_accounts(layer='negative_keyword')

            current_app.logger.info(
                f"[JOB] Negative keyword analysis completed: {success_count} succeeded, {error_count} failed"
            )

        except Exception as e:
            current_app.logger.error(f"Error running negative keyword agents: {e}", exc_info=True)


def run_operational_agents(app: Flask):
    """
    Run operational-layer AI agents for all active Google Ads accounts.

    Operational agents manage medium-term optimizations:
    - Budget redistribution between campaigns
    - Pause underperforming campaigns/ad groups
    - Scale winners by increasing budgets
    - A/B test analysis and winner selection
    - Quality score improvements

    Runs every 6 hours for balanced optimization.
    """
    with app.app_context():
        try:
            current_app.logger.info("[JOB] Starting operational agents for all accounts")

            from app.tasks.agent_scheduler import run_agents_for_all_accounts

            success_count, error_count = run_agents_for_all_accounts(layer='operational')

            current_app.logger.info(
                f"[JOB] Operational agents completed: {success_count} succeeded, {error_count} failed"
            )

        except Exception as e:
            current_app.logger.error(f"Error running operational agents: {e}", exc_info=True)


def run_strategic_agents(app: Flask):
    """
    Run strategic-layer AI agents for all active Google Ads accounts.

    Strategic agents make long-term, structural optimizations:
    - Campaign structure analysis and recommendations
    - New keyword theme discovery
    - Landing page optimization opportunities
    - Competitive analysis and positioning
    - Budget allocation strategy across campaigns
    - ROAS optimization decisions

    Runs daily at 6 AM UTC for strategic planning.
    """
    with app.app_context():
        try:
            current_app.logger.info("[JOB] Starting strategic agents for all accounts")

            from app.tasks.agent_scheduler import run_agents_for_all_accounts

            success_count, error_count = run_agents_for_all_accounts(layer='strategic')

            current_app.logger.info(
                f"[JOB] Strategic agents completed: {success_count} succeeded, {error_count} failed"
            )

        except Exception as e:
            current_app.logger.error(f"Error running strategic agents: {e}", exc_info=True)


def run_google_ads_auto_executor(app: Flask):
    """
    Run Google Ads Auto-Executor for all active accounts.

    Automatically executes safe optimizations:
    - Auto-adds negative keywords for non-purchase intent searches
    - Auto-pauses low-performing keywords (future)
    - Auto-adjusts bids based on performance (future)

    All actions are logged to AIAction table with full audit trail and undo capability.

    Runs every 4 hours to catch wasteful spend quickly.
    """
    with app.app_context():
        try:
            current_app.logger.info("[JOB] Starting Google Ads Auto-Executor for all accounts")

            from app.services.google_ads_auto_executor import GoogleAdsAutoExecutor
            from app.models import Account
            from app.models_google import GoogleOAuthToken
            from app import db

            # Get all accounts with Google Ads connected
            accounts = Account.query.join(
                GoogleOAuthToken, Account.id == GoogleOAuthToken.account_id
            ).filter(
                GoogleOAuthToken.product == 'ads',
                Account.status == 'active'
            ).all()

            if not accounts:
                current_app.logger.info("No active Google Ads accounts found")
                return

            total_actions = 0
            success_count = 0
            error_count = 0

            for account in accounts:
                try:
                    current_app.logger.info(f"Running auto-executor for account {account.id}")

                    executor = GoogleAdsAutoExecutor(account.id)

                    # Auto-add negative keywords (30 day lookback, execute mode)
                    actions = executor.auto_add_negative_keywords(lookback_days=30, dry_run=False)

                    total_actions += len(actions)
                    success_count += 1

                    if actions:
                        current_app.logger.info(
                            f"Account {account.id}: Created {len(actions)} negative keyword actions"
                        )

                except Exception as e:
                    current_app.logger.error(
                        f"Error running auto-executor for account {account.id}: {e}",
                        exc_info=True
                    )
                    error_count += 1
                    continue

            current_app.logger.info(
                f"[JOB] Google Ads Auto-Executor complete: "
                f"{total_actions} actions created, {success_count} accounts succeeded, {error_count} errors"
            )

        except Exception as e:
            current_app.logger.error(f"Error in Google Ads Auto-Executor job: {e}", exc_info=True)


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
