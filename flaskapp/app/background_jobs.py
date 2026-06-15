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


def _safe_db_cleanup():
    """Remove the scoped DB session after a background-thread job completes.

    SQLAlchemy's scoped_session is thread-local. Background threads that use
    app_context() but are NOT Passenger request threads will hold a DB
    connection open indefinitely unless we explicitly call session.remove().
    This is the primary cause of connection-pool exhaustion and worker OOM.
    """
    try:
        from app import db
        db.session.remove()
    except Exception:
        pass


def init_scheduler(app: Flask):
    """
    Initialize APScheduler with the Flask app.

    Set DISABLE_SCHEDULER=1 in your environment to skip starting the in-process
    scheduler (recommended for Passenger/shared-hosting deployments — use system
    cron + run_job.py instead).
    """
    # ── Hard kill-switch for Passenger / shared-hosting deployments ──────────
    if os.environ.get('DISABLE_SCHEDULER', '').strip() in ('1', 'true', 'yes'):
        app.logger.info(
            "DISABLE_SCHEDULER is set — skipping in-process scheduler. "
            "Use system cron + run_job.py to run jobs externally."
        )
        # Still run ensure_columns so new model tables are created on deploy
        _ensure_new_model_columns(app)
        return None

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
        return None

    # ── Single-worker lock: only one Passenger/Gunicorn worker runs the scheduler
    import fcntl
    lock_file_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.scheduler.lock')

    try:
        lock_file = open(lock_file_path, 'w')
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        app._scheduler_lock = lock_file
        app.logger.info("Acquired scheduler lock — running background jobs in this worker")
    except (IOError, OSError):
        app.logger.info("Scheduler lock held by another worker — skipping scheduler here")
        return None

    # ── Conservative config for shared hosting ───────────────────────────────
    # max_workers=1: only one job runs at a time; no thread-pool growth
    executors = {'default': ThreadPoolExecutor(max_workers=1)}
    job_defaults = {
        'coalesce': True,       # merge missed firings into one run
        'max_instances': 1,     # never run the same job twice concurrently
        'misfire_grace_time': 600,  # 10-minute grace so slow jobs aren't skipped
    }

    scheduler = BackgroundScheduler(
        executors=executors,
        job_defaults=job_defaults,
        timezone='UTC'
    )

    register_scheduled_jobs(scheduler, app)

    # After every job finishes (success or error), release the SQLAlchemy
    # scoped session so the thread's DB connection returns to the pool.
    # Without this, background threads hold connections open indefinitely,
    # exhausting the pool and eventually crashing the worker.
    from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR

    def _after_job(event):
        _safe_db_cleanup()

    scheduler.add_listener(_after_job, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)

    scheduler.start()
    app.logger.info("Background job scheduler started with %d jobs",
                    len(scheduler.get_jobs()))

    _ensure_new_model_columns(app)

    app.scheduler = scheduler

    import atexit
    atexit.register(lambda: scheduler.shutdown(wait=False))

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

    # Google Ads AI Agents - Operational (every 4 hours)
    # CPL monitoring, bid adjustments, pause/scale campaigns, budget pacing
    scheduler.add_job(
        func=run_operational_agents,
        trigger='interval',
        hours=4,
        id='run_operational_agents',
        replace_existing=True,
        kwargs={'app': app}
    )

    # Cross-Channel Strategic Orchestrator (weekly, Monday 5 AM UTC)
    # The umbrella over ALL channels: ranks each channel by efficiency and shifts
    # budget/priority across them. Runs BEFORE the channel operational/strategic
    # jobs (6 AM) so each channel picks up fresh directives the same morning.
    scheduler.add_job(
        func=run_strategic_orchestrator_all_accounts,
        trigger='cron',
        day_of_week='mon',
        hour=5,
        minute=0,
        id='run_strategic_orchestrator_all_accounts',
        replace_existing=True,
        kwargs={'app': app}
    )

    # Google Ads AI Agents - Strategic (weekly, Monday 6 AM UTC)
    # Portfolio-level decisions: campaign type diversity, major budget reallocation.
    # Runs weekly so structural suggestions don't flood the approval queue.
    scheduler.add_job(
        func=run_strategic_agents,
        trigger='cron',
        day_of_week='mon',
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

    # Facebook Ads daily sync (daily at 3:30 AM UTC)
    # Pulls campaigns, adsets, ads, and last-30-day insights into local DB
    scheduler.add_job(
        func=sync_fb_all_accounts,
        trigger='cron',
        hour=3,
        minute=30,
        id='sync_fb_all_accounts',
        replace_existing=True,
        kwargs={'app': app}
    )

    # Facebook Ads AI Agents - Operational (every 6 hours)
    # Runs FBStrategicDirectorAgent, FBAccountStructureAgent, FBCampaignManagerAgent,
    # FBBudgetGuardianAgent, FBCreativeAnalystAgent, FBSpendOptimizerAgent,
    # FBDaypartingAgent, FBGeoOptimizerAgent, FBRetargetingAgent, FBPixelHealthAgent
    # Each account is cadence-gated (backs off on quiet accounts, up to 2 days)
    scheduler.add_job(
        func=run_fb_operational_agents,
        trigger='interval',
        hours=6,
        id='run_fb_operational_agents',
        replace_existing=True,
        kwargs={'app': app}
    )

    # Facebook Ads AI Agents - Tactical (every 4 hours)
    # Runs FBAudienceOptimizerAgent, FBPlacementOptimizerAgent,
    # FBBidOptimizerAgent, FBCreativeOptimizerAgent
    # Each account is cadence-gated (backs off on quiet accounts)
    scheduler.add_job(
        func=run_fb_tactical_agents,
        trigger='interval',
        hours=4,
        id='run_fb_tactical_agents',
        replace_existing=True,
        kwargs={'app': app}
    )

    # Google Ads Call View sync — daily at 4:30 AM UTC
    scheduler.add_job(
        func=sync_call_view_all_accounts,
        trigger='cron',
        hour=4,
        minute=30,
        id='sync_call_view_all_accounts',
        replace_existing=True,
        kwargs={'app': app}
    )

    # Dayparting analysis + auto-apply — daily at 5:00 AM UTC
    scheduler.add_job(
        func=sync_dayparting_all_accounts,
        trigger='cron',
        hour=5,
        minute=0,
        id='sync_dayparting_all_accounts',
        replace_existing=True,
        kwargs={'app': app}
    )

    # Auction insights sync — daily at 5:30 AM UTC
    scheduler.add_job(
        func=sync_auction_insights_all_accounts,
        trigger='cron',
        hour=5,
        minute=30,
        id='sync_auction_insights_all_accounts',
        replace_existing=True,
        kwargs={'app': app}
    )

    # RSA asset performance sync — daily at 6:00 AM UTC
    scheduler.add_job(
        func=sync_rsa_assets_all_accounts,
        trigger='cron',
        hour=6,
        minute=0,
        id='sync_rsa_assets_all_accounts',
        replace_existing=True,
        kwargs={'app': app}
    )

    # Full structure sync (all entities, no date filter) — daily at 4:00 AM UTC
    scheduler.add_job(
        func=sync_structure_all_accounts,
        trigger='cron',
        hour=4,
        minute=0,
        id='sync_structure_all_accounts',
        replace_existing=True,
        kwargs={'app': app}
    )

    # Skimmer CRM sync (jobs → GCLID match → offline conversions → review emails) — daily at 7:00 AM UTC
    scheduler.add_job(
        func=sync_skimmer_all_accounts,
        trigger='cron',
        hour=7,
        minute=0,
        id='sync_skimmer_all_accounts',
        replace_existing=True,
        kwargs={'app': app}
    )

    # Multi-location keyword overlap detection — daily at 7:30 AM UTC
    scheduler.add_job(
        func=run_overlap_detection_all_groups,
        trigger='cron',
        hour=7,
        minute=30,
        id='overlap_detection_daily',
        replace_existing=True,
        kwargs={'app': app}
    )

    # Upload pending offline conversions to Google Ads — every 4 hours
    scheduler.add_job(
        func=upload_offline_conversions_all_accounts,
        trigger='interval',
        hours=4,
        id='upload_offline_conversions_all_accounts',
        replace_existing=True,
        kwargs={'app': app}
    )

    # Weekly plain-English performance digest email (Monday 1 PM UTC / morning US)
    scheduler.add_job(
        func=send_weekly_digest_all_accounts,
        trigger='cron',
        day_of_week='mon',
        hour=13,
        minute=0,
        id='send_weekly_digest_all_accounts',
        replace_existing=True,
        kwargs={'app': app}
    )

    # Keyword ranking snapshots (weekly, Monday 06:30 UTC)
    # Runs after strategic agents (6 AM) so GSC data is already fresh
    scheduler.add_job(
        func=snapshot_keyword_rankings_all_accounts,
        trigger='cron',
        day_of_week='mon',
        hour=6,
        minute=30,
        id='snapshot_keyword_rankings_all_accounts',
        replace_existing=True,
        kwargs={'app': app}
    )

    # WordPress operational agents (daily at 02:00 UTC)
    # Checks site health, queues content based on organic directive from orchestrator
    scheduler.add_job(
        func=run_wp_operational_agents,
        trigger='cron',
        hour=2,
        minute=0,
        id='run_wp_operational_agents',
        replace_existing=True,
        kwargs={'app': app}
    )

    app.logger.info("Registered 26 scheduled background jobs")


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


def run_strategic_orchestrator_all_accounts(app: Flask):
    """
    Run the cross-channel strategic orchestrator for every active/trial account.

    This is the umbrella over ALL channels. For each account it ranks the
    connected channels by efficiency (cost per lead) and shifts budget/priority
    from the weakest toward the strongest, writing per-channel directives that
    each channel's operational agents pick up automatically.

    Cadence-gated via should_run_agent(account_id, 'strategic', 'strategic') so
    it effectively runs weekly per account and backs off quiet accounts.
    Registered: weekly, Monday 05:00 UTC (before the channel operational jobs).
    """
    with app.app_context():
        from app import db
        from sqlalchemy import text
        from app.services.agent_cadence import should_run_agent, record_agent_run
        from app.services.strategic_orchestrator import run_strategic_orchestrator

        try:
            current_app.logger.info("[JOB] Starting cross-channel strategic orchestrator")

            try:
                with db.engine.connect() as conn:
                    rows = conn.execute(text("""
                        SELECT id AS account_id
                        FROM accounts
                        WHERE status IN ('active', 'trial')
                    """)).fetchall()
            except Exception as exc:
                current_app.logger.error(
                    "[JOB] strategic orchestrator: could not query accounts — %s", exc
                )
                return

            account_ids = [r[0] for r in rows]
            current_app.logger.info(
                "[JOB] strategic orchestrator: %d active/trial account(s)", len(account_ids)
            )

            ran = 0
            skipped = 0
            errors = 0

            for account_id in account_ids:
                run_now, reason = should_run_agent(account_id, 'strategic', 'strategic')
                if not run_now:
                    skipped += 1
                    continue
                try:
                    result = run_strategic_orchestrator(account_id) or {}
                    channels = int(result.get('channels', 0) or 0)
                    changed = int(result.get('changed', 0) or 0)
                    record_agent_run(
                        account_id, 'strategic', 'strategic',
                        decisions_made=changed, opportunities_found=channels,
                    )
                    ran += 1
                    if channels:
                        current_app.logger.info(
                            "[JOB] account %s: %d channel(s), %d directive change(s)",
                            account_id, channels, changed,
                        )
                except Exception as exc:
                    current_app.logger.error(
                        "[JOB] strategic orchestrator failed for account %s — %s",
                        account_id, exc, exc_info=True,
                    )
                    errors += 1

            current_app.logger.info(
                "[JOB] Strategic orchestrator complete: ran=%d, skipped=%d, errors=%d",
                ran, skipped, errors,
            )

        except Exception as exc:
            current_app.logger.error(
                "[JOB] run_strategic_orchestrator_all_accounts error: %s", exc, exc_info=True
            )


def sync_fb_all_accounts(app: Flask):
    """
    Daily sync of Facebook campaigns, adsets, ads, and insights.

    Iterates over every app account that has a non-expired Facebook token
    and calls sync_fb_account(account_id) for each one.
    """
    with app.app_context():
        from app import db
        from sqlalchemy import text

        try:
            current_app.logger.info("[JOB] Starting FB Ads daily sync for all accounts")

            # Find all accounts with a non-expired FB token
            try:
                with db.engine.connect() as conn:
                    rows = conn.execute(
                        text(
                            "SELECT account_id FROM facebook_tokens "
                            "WHERE expires_at IS NULL OR expires_at > NOW()"
                        )
                    ).fetchall()
            except Exception as exc:
                current_app.logger.error(
                    "[JOB] sync_fb_all_accounts: could not query facebook_tokens — %s", exc
                )
                return

            account_ids = [r[0] for r in rows]
            current_app.logger.info(
                "[JOB] sync_fb_all_accounts: found %d account(s) with valid FB token",
                len(account_ids),
            )

            success_count = 0
            error_count = 0
            for account_id in account_ids:
                try:
                    from app.services.fbads_sync import sync_fb_account
                    sync_fb_account(account_id)
                    success_count += 1
                except Exception as exc:
                    current_app.logger.error(
                        "[JOB] sync_fb_all_accounts: error syncing account %s — %s",
                        account_id, exc,
                        exc_info=True,
                    )
                    error_count += 1

            current_app.logger.info(
                "[JOB] FB Ads daily sync complete: %d succeeded, %d failed",
                success_count, error_count,
            )

        except Exception as exc:
            current_app.logger.error(
                "[JOB] sync_fb_all_accounts: unexpected error — %s", exc, exc_info=True
            )


def run_fb_operational_agents(app: Flask):
    """
    Run Facebook Ads operational-layer AI agents for all accounts with a valid
    Facebook token.

    Agents run at operational layer (base interval 6 h, cadence-adaptive):
    FBStrategicDirectorAgent, FBAccountStructureAgent, FBCampaignManagerAgent,
    FBBudgetGuardianAgent, FBCreativeAnalystAgent, FBSpendOptimizerAgent,
    FBDaypartingAgent, FBGeoOptimizerAgent, FBRetargetingAgent, FBPixelHealthAgent.

    Each agent reads the strategy_directive_facebook written by the cross-channel
    strategic orchestrator so its decisions are aligned with the top-level channel
    priority (grow / maintain / cut).
    """
    with app.app_context():
        try:
            current_app.logger.info("[JOB] Starting FB operational agents for all accounts")

            from app.tasks.fb_agent_scheduler import run_fb_operational_agents as _run

            success_count, error_count = _run(app)

            current_app.logger.info(
                "[JOB] FB operational agents completed: %d succeeded, %d failed",
                success_count, error_count,
            )

        except Exception as exc:
            current_app.logger.error(
                "[JOB] run_fb_operational_agents failed: %s", exc, exc_info=True
            )


def run_fb_tactical_agents(app: Flask):
    """
    Run Facebook Ads tactical-layer AI agents for all accounts with a valid
    Facebook token.

    Agents run at tactical layer (base interval 4 h, cadence-adaptive):
    FBAudienceOptimizerAgent, FBPlacementOptimizerAgent,
    FBBidOptimizerAgent, FBCreativeOptimizerAgent.
    """
    with app.app_context():
        try:
            current_app.logger.info("[JOB] Starting FB tactical agents for all accounts")

            from app.tasks.fb_agent_scheduler import run_fb_tactical_agents as _run

            success_count, error_count = _run(app)

            current_app.logger.info(
                "[JOB] FB tactical agents completed: %d succeeded, %d failed",
                success_count, error_count,
            )

        except Exception as exc:
            current_app.logger.error(
                "[JOB] run_fb_tactical_agents failed: %s", exc, exc_info=True
            )


def snapshot_keyword_rankings_all_accounts(app: Flask):
    """
    Weekly keyword ranking snapshot for all accounts with GSC connected.

    Pulls this week's GSC top-100 keyword positions for every account that
    has Google Search Console connected and stores them as KeywordRankSnapshot
    rows so trending data accumulates over time.

    Registered: weekly, Monday 06:30 UTC.
    """
    with app.app_context():
        try:
            current_app.logger.info("[JOB] Starting weekly keyword ranking snapshots")

            from app.models import Account
            from app.models_google import GoogleOAuthToken
            from app.services.keyword_rank_tracker import snapshot_rankings

            # Find all active accounts with GSC connected
            accounts = Account.query.join(
                GoogleOAuthToken, Account.id == GoogleOAuthToken.account_id
            ).filter(
                GoogleOAuthToken.product == 'gsc',
                Account.status == 'active',
            ).all()

            if not accounts:
                current_app.logger.info("[JOB] No active GSC accounts found — skipping keyword snapshots")
                return

            success_count = 0
            error_count = 0
            total_snapshots = 0

            for account in accounts:
                try:
                    result = snapshot_rankings(account.id)
                    if "error" in result:
                        current_app.logger.warning(
                            f"[JOB] Keyword snapshot skipped for account {account.id}: {result['error']}"
                        )
                        error_count += 1
                    else:
                        total_snapshots += result.get("snapshots", 0)
                        success_count += 1
                        current_app.logger.info(
                            f"[JOB] Account {account.id}: {result['snapshots']} snapshots across {result['urls']} URLs"
                        )
                except Exception as e:
                    current_app.logger.error(
                        f"[JOB] Error snapshotting rankings for account {account.id}: {e}",
                        exc_info=True,
                    )
                    error_count += 1
                    continue

            current_app.logger.info(
                f"[JOB] Keyword ranking snapshots complete: "
                f"{total_snapshots} rows written, {success_count} accounts succeeded, {error_count} errors"
            )

        except Exception as e:
            current_app.logger.error(f"Error in keyword ranking snapshot job: {e}", exc_info=True)


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


# ---------------------------------------------------------------------------
# New automation jobs — Google Ads intelligence + Skimmer CRM + multiloc
# ---------------------------------------------------------------------------

def run_overlap_detection_all_groups(app: Flask):
    """Daily job: detect keyword overlap between locations in the same group."""
    with app.app_context():
        try:
            from app.services.overlap_detection import detect_overlaps_for_all_groups
            results = detect_overlaps_for_all_groups()
            total = sum(results.values())
            current_app.logger.info(
                f"Overlap detection complete: {len(results)} groups, {total} overlaps found"
            )
        except Exception:
            current_app.logger.exception("Overlap detection job failed")


# ---------------------------------------------------------------------------

def _ensure_new_model_columns(app: Flask):
    """Call ensure_columns on all models added after initial schema creation."""
    with app.app_context():
        try:
            from app.models_ads import (
                GadsHourlyStats, AuctionInsight, RsaAsset,
                OfflineConversionImport, DaypartBidAdjustment, AdsAccountGoal,
            )
            for model in (GadsHourlyStats, AuctionInsight, RsaAsset,
                          OfflineConversionImport, DaypartBidAdjustment, AdsAccountGoal):
                try:
                    model.ensure_columns()
                except Exception as exc:
                    current_app.logger.warning("ensure_columns failed for %s: %s", model.__tablename__, exc)
        except Exception as exc:
            current_app.logger.warning("_ensure_new_model_columns (ads): %s", exc)

        try:
            from app.models_skimmer import SkimmerAuth, PhoneGclidMap, EmailGclidMap, SkimmerJob
            for model in (SkimmerAuth, PhoneGclidMap, EmailGclidMap, SkimmerJob):
                try:
                    model.ensure_columns()
                except Exception as exc:
                    current_app.logger.warning("ensure_columns failed for %s: %s", model.__tablename__, exc)
        except Exception as exc:
            current_app.logger.warning("_ensure_new_model_columns (skimmer): %s", exc)

        try:
            from app.models_multiloc import LocationGroup, LocationGroupMember, KeywordOverlap
            LocationGroup.ensure_columns()
            LocationGroupMember.ensure_columns()
            KeywordOverlap.ensure_columns()
            current_app.logger.info("multiloc model columns ensured")
        except Exception:
            current_app.logger.exception("Failed to ensure multiloc model columns")


def sync_call_view_all_accounts(app: Flask):
    """Pull Google Ads Call View data for all connected accounts."""
    with app.app_context():
        try:
            from app.models import GoogleAdsAuth
            auths = GoogleAdsAuth.query.all()
            for auth in auths:
                try:
                    from app.services.google_ads_call_view_sync import sync_call_view
                    result = sync_call_view(auth.account_id)
                    current_app.logger.info("call_view sync account %s: %s", auth.account_id, result)
                except Exception as exc:
                    current_app.logger.warning("call_view sync failed account %s: %s", auth.account_id, exc)
        except Exception as exc:
            current_app.logger.error("sync_call_view_all_accounts error: %s", exc, exc_info=True)


def sync_dayparting_all_accounts(app: Flask):
    """Sync hourly stats, compute bid adjustments, and auto-apply for all accounts."""
    with app.app_context():
        try:
            from app.models import GoogleAdsAuth
            from app.services.google_ads_dayparting import (
                sync_hourly_stats, compute_daypart_adjustments, apply_daypart_adjustments,
            )
            auths = GoogleAdsAuth.query.all()
            for auth in auths:
                try:
                    sync_hourly_stats(auth.account_id)
                    adjustments = compute_daypart_adjustments(auth.account_id)
                    if adjustments:
                        result = apply_daypart_adjustments(auth.account_id, adjustments)
                        current_app.logger.info(
                            "dayparting account %s: %d adjustments applied", auth.account_id, result.get("applied", 0)
                        )
                except Exception as exc:
                    current_app.logger.warning("dayparting failed account %s: %s", auth.account_id, exc)
        except Exception as exc:
            current_app.logger.error("sync_dayparting_all_accounts error: %s", exc, exc_info=True)


def sync_auction_insights_all_accounts(app: Flask):
    """Sync competitor auction insights and auto-create recommendations for all accounts."""
    with app.app_context():
        try:
            from app.models import GoogleAdsAuth
            from app.services.google_ads_auction_insights import (
                sync_auction_insights, auto_respond_to_impression_loss,
            )
            auths = GoogleAdsAuth.query.all()
            for auth in auths:
                try:
                    sync_auction_insights(auth.account_id)
                    auto_respond_to_impression_loss(auth.account_id)
                except Exception as exc:
                    current_app.logger.warning("auction insights failed account %s: %s", auth.account_id, exc)
        except Exception as exc:
            current_app.logger.error("sync_auction_insights_all_accounts error: %s", exc, exc_info=True)


def sync_rsa_assets_all_accounts(app: Flask):
    """Sync RSA asset performance and auto-flag winners/losers for all accounts."""
    with app.app_context():
        try:
            from app.models import GoogleAdsAuth
            from app.services.google_ads_rsa_sync import sync_rsa_assets, auto_promote_winners
            auths = GoogleAdsAuth.query.all()
            for auth in auths:
                try:
                    sync_rsa_assets(auth.account_id)
                    auto_promote_winners(auth.account_id)
                except Exception as exc:
                    current_app.logger.warning("RSA sync failed account %s: %s", auth.account_id, exc)
        except Exception as exc:
            current_app.logger.error("sync_rsa_assets_all_accounts error: %s", exc, exc_info=True)


def sync_skimmer_all_accounts(app: Flask):
    """Run full Skimmer sync pipeline for all connected accounts."""
    with app.app_context():
        try:
            from app.models_skimmer import SkimmerAuth
            from app.services.skimmer_sync import run_full_sync
            auths = SkimmerAuth.query.filter_by(sync_enabled=True).all()
            for auth in auths:
                try:
                    result = run_full_sync(auth.account_id)
                    current_app.logger.info("skimmer sync account %s: %s", auth.account_id, result)
                except Exception as exc:
                    current_app.logger.warning("skimmer sync failed account %s: %s", auth.account_id, exc)
        except Exception as exc:
            current_app.logger.error("sync_skimmer_all_accounts error: %s", exc, exc_info=True)


def upload_offline_conversions_all_accounts(app: Flask):
    """Upload pending offline conversion imports to Google Ads for all accounts."""
    with app.app_context():
        try:
            from app.models_ads import OfflineConversionImport
            from app import db
            account_ids = [
                row[0] for row in
                db.session.execute(
                    db.text("SELECT DISTINCT account_id FROM offline_conversion_imports WHERE status='pending'")
                ).fetchall()
            ]
            from app.services.google_ads_offline_conversions import upload_pending_conversions
            for aid in account_ids:
                try:
                    result = upload_pending_conversions(aid)
                    current_app.logger.info("offline conv upload account %s: %s", aid, result)
                except Exception as exc:
                    current_app.logger.warning("offline conv upload failed account %s: %s", aid, exc)
        except Exception as exc:
            current_app.logger.error("upload_offline_conversions_all_accounts error: %s", exc, exc_info=True)


def send_weekly_digest_all_accounts(app: Flask):
    """
    Generate the weekly plain-English performance digest for every Google
    Ads-connected account, store it, and queue an email to the account owner.

    Runs Monday mornings (1 PM UTC). Accounts with no data, no history, and
    no agent activity are skipped so brand-new accounts don't get empty emails.
    """
    with app.app_context():
        from flask import render_template
        from app import db
        from app.models import Account, User
        from app.models_google import GoogleOAuthToken
        from app.models_billing import EmailQueue
        from app.services.google_ads_digest import generate_weekly_digest, render_digest_text

        try:
            accounts = Account.query.join(
                GoogleOAuthToken, Account.id == GoogleOAuthToken.account_id
            ).filter(
                GoogleOAuthToken.product == 'ads',
                Account.status == 'active'
            ).all()

            if not accounts:
                current_app.logger.info("No active Google Ads accounts for weekly digest")
                return

            queued = 0
            skipped = 0
            errors = 0

            for account in accounts:
                try:
                    digest = generate_weekly_digest(account.id)

                    quiet_week = (
                        not digest.get("has_data")
                        and not digest.get("prior_week")
                        and not (digest.get("agent") or {}).get("total_actions")
                    )
                    if quiet_week:
                        skipped += 1
                        continue

                    user = (
                        User.query.filter_by(account_id=account.id, role='owner').first()
                        or User.query.filter_by(account_id=account.id).order_by(User.id).first()
                    )
                    if not user:
                        skipped += 1
                        continue

                    text_parts = render_digest_text(digest)

                    tw = digest.get("this_week") or {}
                    leads = int(round(float(tw.get("leads") or 0)))
                    spend = float(tw.get("spend") or 0)
                    if spend > 0 and leads > 0:
                        subject = (
                            f"Your week in review: {leads} lead{'s' if leads != 1 else ''} "
                            f"for ${spend:,.0f}"
                        )
                    elif spend > 0:
                        subject = f"Your week in review: ${spend:,.0f} spent, still working on those leads"
                    else:
                        subject = "Your week in review: your ads didn't run last week"

                    def _friendly(iso_date):
                        d = datetime.fromisoformat(iso_date)
                        return f"{d.strftime('%b')} {d.day}"

                    html_body = render_template(
                        'emails/google_ads_weekly_digest.html',
                        text=text_parts,
                        week_start=_friendly(digest["week_start"]),
                        week_end=_friendly(digest["week_end"]),
                        dashboard_url=f"{current_app.config.get('BASE_URL', 'https://app.fieldsprout.com')}/account/google/ads/?tab=cockpit",
                        current_year=datetime.utcnow().year,
                    )

                    db.session.add(EmailQueue(
                        to_email=user.email,
                        subject=subject,
                        html_body=html_body,
                    ))
                    db.session.commit()
                    queued += 1

                except Exception as e:
                    db.session.rollback()
                    current_app.logger.error(
                        f"Error building weekly digest for account {account.id}: {e}",
                        exc_info=True
                    )
                    errors += 1
                    continue

            current_app.logger.info(
                f"[JOB] Weekly digest complete: queued={queued}, skipped={skipped}, errors={errors}"
            )

        except Exception as e:
            current_app.logger.error(f"Error in weekly digest job: {e}", exc_info=True)


def sync_structure_all_accounts(app: Flask):
    """
    Sync full account structure (campaigns, ad groups, keywords, ads, negatives)
    for all connected accounts — without a date filter so zero-impression keywords
    and newly created entities are captured.
    """
    with app.app_context():
        try:
            from app.models import GoogleAdsAuth
            from app.services.google_ads_sync import sync_structure
            auths = GoogleAdsAuth.query.all()
            for auth in auths:
                try:
                    result = sync_structure(auth.account_id)
                    current_app.logger.info(
                        "structure sync account %s: campaigns=%s kw=%s ads=%s errors=%s",
                        auth.account_id,
                        result.get("campaigns"), result.get("keywords"),
                        result.get("ads"), result.get("errors"),
                    )
                except Exception as exc:
                    current_app.logger.warning("structure sync failed account %s: %s", auth.account_id, exc)
        except Exception as exc:
            current_app.logger.error("sync_structure_all_accounts error: %s", exc, exc_info=True)


def run_wp_operational_agents(app: Flask):
    """Run WordPress site health and content strategy agents for all WP accounts.

    Delegates to app.tasks.wp_agent_scheduler.run_wp_operational_agents which
    handles cadence gating, directive reading, and agent orchestration.
    """
    try:
        from app.tasks.wp_agent_scheduler import run_wp_operational_agents as _run
        result = _run(app)
        with app.app_context():
            current_app.logger.info(
                "run_wp_operational_agents: checked=%s ran=%s skipped=%s errors=%s",
                result.get("accounts_checked"),
                result.get("accounts_run"),
                result.get("accounts_skipped"),
                result.get("errors"),
            )
    except Exception as exc:
        with app.app_context():
            current_app.logger.error(
                "run_wp_operational_agents failed: %s", exc, exc_info=True
            )
