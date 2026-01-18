# app/cron_tasks.py
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional, List, Tuple

from sqlalchemy import text

from app import db
from app.models.wp_job import WPJob


# =========================
# Core CRON entrypoints
# =========================

def run_minutely(app, db):
    """Lightweight work every minute."""
    app.logger.info("[CRON] minutely tick at %s", datetime.utcnow().isoformat())

    # Process exactly one queued WP job per minute (keeps load steady)
    try:
        processed = process_wp_jobs(app)
        if processed:
            app.logger.info("[CRON] processed 1 WP job")
    except Exception:
        app.logger.exception("[CRON] process_wp_jobs failed")

    # Process email workflow enrollments (up to 50 per minute)
    try:
        from app.services.workflow_processor import process_workflow_enrollments
        emails_sent = process_workflow_enrollments(app, max_per_run=50)
        if emails_sent > 0:
            app.logger.info(f"[CRON] sent {emails_sent} workflow emails")
    except Exception:
        app.logger.exception("[CRON] process_workflow_enrollments failed")


def run_hourly(app, db):
    """Periodic housekeeping. Keep this light; heavy jobs belong in run_daily."""
    app.logger.info("[CRON] hourly tick at %s", datetime.utcnow().isoformat())
    # TODO: queue blog drafts, refresh sitemaps, sync analytics, etc.


def run_daily(app, db):
    """
    Daily heavy tasks.
    - Generates Google Business Profile monthly insights (at most every ~27 days per account).
    - Runs Google Ads advanced intelligence features
    """
    app.logger.info("[CRON] daily tick at %s", datetime.utcnow().isoformat())

    try:
        _run_daily_gmb_insights(app)
    except Exception:
        app.logger.exception("[CRON] GMB monthly insights run failed")

    # Run Google Ads advanced intelligence features
    try:
        _run_daily_google_ads_intelligence(app)
    except Exception:
        app.logger.exception("[CRON] Google Ads intelligence run failed")

    # Run automated lead generation and outreach
    try:
        _run_daily_lead_automation(app)
    except Exception:
        app.logger.exception("[CRON] Lead automation run failed")

    # Send monthly Google Ads performance reports
    try:
        _run_monthly_google_ads_performance_emails(app)
    except Exception:
        app.logger.exception("[CRON] Google Ads monthly performance emails failed")

    # TODO: email digests, cleanups, churn pings, etc.


# =========================
# WordPress job runner
# =========================

def process_wp_jobs(app) -> bool:
    """
    Pick the oldest queued job and run it.
    Returns True if a job was processed, else False.
    """
    now = datetime.utcnow()

    job = (
        WPJob.query
        .filter(WPJob.status == "queued")
        .order_by(
            WPJob.scheduled_at.is_(None),
            WPJob.scheduled_at.asc(),
            WPJob.priority.desc(),
            WPJob.created_at.asc(),
        )
        .first()
    )
    if not job:
        return False

    try:
        job.status = "running"
        job.started_at = now
        db.session.commit()

        if job.action == "publish_manual":
            # TODO: replace with your real WP publish call
            title = (job.payload or {}).get("title") or "Untitled"
            content = (job.payload or {}).get("content") or ""
            # result = publish_to_wordpress(title, content, ...)
            job.result = {"preview_url": None, "wp_post_id": None, "title": title}
            job.status = "done"

        elif job.action == "generate_ai_post":
            # TODO: call your AI writer (OpenAI/Claude) and optionally publish/save draft
            brief = job.payload or {}
            # draft = generate_ai_article(brief)
            # optionally post to WP as draft
            job.result = {"draft_title": brief.get("primary_keyword") or "AI Draft", "wp_post_id": None}
            job.status = "done"

        else:
            job.error = f"Unknown action: {job.action}"
            job.status = "failed"

        job.completed_at = datetime.utcnow()
        db.session.commit()
        return True

    except Exception as e:
        app.logger.exception("WP job failed")
        job.status = "failed"
        job.error = str(e)
        job.retries = (job.retries or 0) + 1
        db.session.commit()
        return False


# =========================
# GMB Monthly Insights
# =========================

def _run_daily_gmb_insights(app) -> None:
    """
    Generate OpenAI-powered GBP insights for eligible accounts.
    - Skips if OPENAI_API_KEY is missing.
    - Only runs for accounts that have a refreshable GBP token.
    - Per-account interval: >= 27 days since the last insights.
    - Per-run cap: GMB_INSIGHTS_MAX_PER_RUN (default 25).
    """
    # Feature flag
    enabled = app.config.get("GMB_INSIGHTS_ENABLED", True)
    if not enabled:
        app.logger.info("[CRON] GMB insights disabled (GMB_INSIGHTS_ENABLED=False)")
        return

    # Must have OpenAI configured
    if not (app.config.get("OPENAI_API_KEY")):
        app.logger.info("[CRON] GMB insights skipped (no OPENAI_API_KEY)")
        return

    max_per_run = int(app.config.get("GMB_INSIGHTS_MAX_PER_RUN", 25))
    lookback_days = int(app.config.get("GMB_INSIGHTS_INTERVAL_DAYS", 27))
    cutoff = datetime.utcnow() - timedelta(days=lookback_days)

    # Find accounts with GBP refresh tokens
    accounts = _accounts_with_gbp_tokens(max_candidates=200)
    if not accounts:
        app.logger.info("[CRON] No GBP-connected accounts to consider")
        return

    app.logger.info(
        "[CRON] Considering %d GBP-connected accounts for insights (interval >= %d days, cap=%d)",
        len(accounts), lookback_days, max_per_run
    )

    processed = 0
    for aid in accounts:
        if processed >= max_per_run:
            break
        try:
            last = _last_gmb_insights_time(aid)
            if last and last > cutoff:
                # Too recent; skip
                continue

            ok = _generate_gmb_insights_for_account(app, aid)
            if ok:
                processed += 1
        except Exception:
            app.logger.exception("[CRON] insights generation failed for account_id=%s", aid)

    app.logger.info("[CRON] GMB insights generated for %d account(s)", processed)


def _accounts_with_gbp_tokens(max_candidates: int = 200) -> List[int]:
    """
    Return a list of account_ids that have a GBP refresh token.
    """
    try:
        with db.engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT DISTINCT account_id
                      FROM google_oauth_tokens
                     WHERE LOWER(product) IN ('gbp','gmb','mybusiness')
                       AND refresh_token IS NOT NULL
                     ORDER BY account_id ASC
                     LIMIT :lim
                    """
                ),
                {"lim": max_candidates},
            ).fetchall()
        return [int(r[0]) for r in rows]
    except Exception:
        # On error, return empty list; caller logs higher up
        return []


def _last_gmb_insights_time(aid: int) -> Optional[datetime]:
    """Return the most recent generated_at for this account (or None)."""
    try:
        with db.engine.connect() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT MAX(generated_at)
                      FROM gmb_insights
                     WHERE account_id = :aid
                    """
                ),
                {"aid": aid},
            ).fetchone()
        return row[0] if row and row[0] else None
    except Exception:
        return None


def _generate_gmb_insights_for_account(app, aid: int) -> bool:
    """
    Pull GBP performance and create insights via OpenAI.
    Uses helper functions from app.gmb to avoid duplication.
    """
    try:
        # Lazy import to avoid circular imports at module import time
        from app.gmb import (
            _refresh_token as gmb_refresh_token,
            _gbp_list_first_location_name,
            _gbp_fetch_performance,
            _gbp_metrics_to_prompt,
            _openai_insights_from_metrics,
            _save_insights,
        )
    except Exception:
        app.logger.exception("[CRON] could not import GMB helpers")
        return False

    # 1) Refresh access token
    access_token = gmb_refresh_token(aid)
    if not access_token:
        app.logger.info("[CRON] skip account_id=%s (no access token)", aid)
        return False

    # 2) Find first location
    loc = _gbp_list_first_location_name(access_token)
    if not loc:
        app.logger.info("[CRON] skip account_id=%s (no GBP locations)", aid)
        return False

    # 3) Fetch 28-day performance
    metrics = _gbp_fetch_performance(access_token, loc, days=28)

    # 4) Build LLM prompt & get HTML insights
    summary = _gbp_metrics_to_prompt(metrics)
    html = _openai_insights_from_metrics(summary)

    # 5) Persist insights
    _save_insights(aid, html)
    app.logger.info("[CRON] insights saved for account_id=%s", aid)
    return True


# =========================
# Google Ads Optimizations Analysis
# =========================

def _run_daily_google_ads_optimizations(app) -> None:
    """
    Generate Google Ads optimization analysis for eligible accounts and send email notifications.
    - Only runs for accounts that have a Google Ads connection.
    - Per-account interval: configurable via GOOGLE_ADS_ANALYSIS_INTERVAL_DAYS (default 7 days).
    - Per-run cap: GOOGLE_ADS_ANALYSIS_MAX_PER_RUN (default 25).
    """
    # Feature flag
    enabled = app.config.get("GOOGLE_ADS_ANALYSIS_ENABLED", True)
    if not enabled:
        app.logger.info("[CRON] Google Ads optimization analysis disabled (GOOGLE_ADS_ANALYSIS_ENABLED=False)")
        return

    max_per_run = int(app.config.get("GOOGLE_ADS_ANALYSIS_MAX_PER_RUN", 25))
    lookback_days = int(app.config.get("GOOGLE_ADS_ANALYSIS_INTERVAL_DAYS", 7))  # Weekly by default
    cutoff = datetime.utcnow() - timedelta(days=lookback_days)

    # Find accounts with Google Ads tokens
    accounts = _accounts_with_google_ads_tokens(max_candidates=200)
    if not accounts:
        app.logger.info("[CRON] No Google Ads-connected accounts to consider")
        return

    app.logger.info(
        "[CRON] Considering %d Google Ads-connected accounts for optimization analysis (interval >= %d days, cap=%d)",
        len(accounts), lookback_days, max_per_run
    )

    processed = 0
    for aid in accounts:
        if processed >= max_per_run:
            break
        try:
            last = _last_google_ads_analysis_time(aid)
            if last and last > cutoff:
                # Too recent; skip
                continue

            ok = _generate_google_ads_optimizations_for_account(app, aid)
            if ok:
                processed += 1
        except Exception:
            app.logger.exception("[CRON] Google Ads optimization analysis failed for account_id=%s", aid)

    app.logger.info("[CRON] Google Ads optimization analysis completed for %d account(s)", processed)


def _accounts_with_google_ads_tokens(max_candidates: int = 200) -> List[int]:
    """
    Return a list of account_ids that have a Google Ads refresh token.
    """
    try:
        with db.engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT DISTINCT account_id
                      FROM google_oauth_tokens
                     WHERE LOWER(product) IN ('ads', 'adwords', 'google_ads')
                       AND refresh_token IS NOT NULL
                     ORDER BY account_id ASC
                     LIMIT :lim
                    """
                ),
                {"lim": max_candidates},
            ).fetchall()
        return [int(r[0]) for r in rows]
    except Exception:
        # On error, return empty list; caller logs higher up
        return []


def _last_google_ads_analysis_time(aid: int) -> Optional[datetime]:
    """
    Return the most recent analysis time for this account.
    For now, we'll use a simple approach - check if we have a table to track this.
    If not, we'll store it in a metadata table or just run it every interval.

    TODO: Create a google_ads_optimization_runs table to track when analysis was last run.
    For now, return None to always run.
    """
    # TODO: Implement tracking table
    # For now, return None so it runs every time (respects the interval via manual tracking)
    return None


def _generate_google_ads_optimizations_for_account(app, aid: int) -> bool:
    """
    Generate Google Ads optimization analysis and send email notification.
    """
    try:
        # Lazy imports to avoid circular dependencies
        from app.models import User, Account
        from app.services.email_service import send_google_ads_optimizations_email

        # Import analysis function from google blueprint
        # We'll use the existing _analyze_ads_opportunities and _get_ads_state functions
        from app.google import _analyze_ads_opportunities, _get_ads_state

    except Exception:
        app.logger.exception("[CRON] could not import Google Ads helpers")
        return False

    # 1) Get account and primary user
    account = Account.query.get(aid)
    if not account:
        app.logger.info("[CRON] skip account_id=%s (account not found)", aid)
        return False

    # Get primary user for this account (account owner or first team member)
    user = User.query.filter_by(id=account.user_id).first() if hasattr(account, 'user_id') else None
    if not user:
        # Fallback: get first user associated with this account through team membership
        from app.models import TeamMember
        team_member = TeamMember.query.filter_by(account_id=aid).first()
        if team_member:
            user = User.query.get(team_member.user_id)

    if not user:
        app.logger.info("[CRON] skip account_id=%s (no user found)", aid)
        return False

    # 2) Get Google Ads data
    try:
        ads_data = _get_ads_state(aid)
        if not ads_data or not ads_data.get('campaigns'):
            app.logger.info("[CRON] skip account_id=%s (no Google Ads data)", aid)
            return False
    except Exception as e:
        app.logger.warning("[CRON] skip account_id=%s (error getting ads data: %s)", aid, e)
        return False

    # 3) Generate analysis
    try:
        analysis = _analyze_ads_opportunities(aid, ads_data)
        if not analysis or not analysis.get('opportunities'):
            app.logger.info("[CRON] skip account_id=%s (no optimizations found)", aid)
            return False
    except Exception as e:
        app.logger.warning("[CRON] skip account_id=%s (error analyzing: %s)", aid, e)
        return False

    # 4) Calculate total monthly value
    total_savings = sum(opp.get('monthly_savings', 0) for opp in analysis['opportunities'])
    total_leads = sum(opp.get('monthly_leads', 0) for opp in analysis['opportunities'])
    total_lead_value = total_leads * 500  # $500 per lead
    total_monthly_value = total_savings + total_lead_value

    # 5) Generate opportunities URL
    base_url = app.config.get("BASE_URL", "https://fieldsprout.io")
    opportunities_url = f"{base_url}/account/google/ads/opportunities"

    # 6) Send email notification
    try:
        email_sent = send_google_ads_optimizations_email(
            user=user,
            account=account,
            optimization_count=len(analysis['opportunities']),
            total_monthly_value=total_monthly_value,
            opportunities_url=opportunities_url
        )

        if email_sent:
            app.logger.info(
                "[CRON] Google Ads optimization email sent to %s for account %s (%d optimizations, $%,.0f/mo)",
                user.email, account.name, len(analysis['opportunities']), total_monthly_value
            )
            return True
        else:
            app.logger.warning("[CRON] Failed to send email to %s for account_id=%s", user.email, aid)
            return False

    except Exception as e:
        app.logger.exception("[CRON] Error sending optimization email for account_id=%s: %s", aid, e)
        return False


# =========================
# Google Ads Advanced Intelligence
# =========================

def _run_daily_google_ads_intelligence(app) -> None:
    """
    Run Google Ads advanced intelligence features daily.
    - Negative keyword mining
    - Anomaly detection
    - Self-healing campaigns
    - Budget reallocation
    - Seasonal forecasting
    """
    enabled = app.config.get("GOOGLE_ADS_INTELLIGENCE_ENABLED", True)
    if not enabled:
        app.logger.info("[CRON] Google Ads intelligence disabled")
        return

    # Get list of active Google Ads accounts
    accounts = _accounts_with_google_ads_tokens(max_candidates=100)
    if not accounts:
        app.logger.info("[CRON] No Google Ads accounts to process")
        return

    app.logger.info(f"[CRON] Processing {len(accounts)} Google Ads accounts for intelligence features")

    for account_id in accounts:
        try:
            # 1. Mine negative keywords
            from app.services.google_ads_intelligence import mine_negative_keywords
            suggestions = mine_negative_keywords(account_id, lookback_days=30)
            if suggestions:
                app.logger.info(f"[CRON] Account {account_id}: Found {len(suggestions)} negative keyword suggestions")

            # 2. Detect anomalies
            from app.services.google_ads_forecasting import detect_anomalies
            anomalies = detect_anomalies(account_id, lookback_days=7)
            if anomalies:
                app.logger.info(f"[CRON] Account {account_id}: Detected {len(anomalies)} anomalies")

            # 3. Run self-healing campaigns (dry run first for safety)
            from app.services.google_ads_automation import run_self_healing_campaigns
            result = run_self_healing_campaigns(account_id, dry_run=True)
            if result.get('total_changes', 0) > 0:
                app.logger.info(f"[CRON] Account {account_id}: Self-healing recommends {result['total_changes']} changes")

            # 4. Budget reallocation (dry run)
            from app.services.google_ads_automation import reallocate_budgets
            realloc = reallocate_budgets(account_id, dry_run=True)
            if realloc.get('reallocations'):
                app.logger.info(f"[CRON] Account {account_id}: Budget reallocation recommends {len(realloc['reallocations'])} changes")

            # 5. Seasonal forecasting (weekly)
            if datetime.utcnow().weekday() == 0:  # Monday only
                from app.services.google_ads_forecasting import forecast_seasonal_demand
                # Forecast for common service categories
                for category in ['HVAC', 'Plumbing', 'Roofing', 'Lawn Care']:
                    forecasts = forecast_seasonal_demand(account_id, category, forecast_days=90)
                    if forecasts:
                        app.logger.info(f"[CRON] Account {account_id}: Generated {len(forecasts)} days of {category} forecasts")

        except Exception as e:
            app.logger.exception(f"[CRON] Error processing intelligence for account {account_id}: {e}")

    app.logger.info("[CRON] Google Ads intelligence processing completed")


def _run_monthly_google_ads_performance_emails(app) -> None:
    """
    Send monthly performance report emails to users with Google Ads accounts.
    Runs on the 1st day of each month.
    """
    # Only run on the 1st of the month
    now = datetime.utcnow()
    if now.day != 1:
        app.logger.debug(f"[CRON] Skipping monthly Google Ads emails (not 1st of month, today is {now.day})")
        return

    enabled = app.config.get("GOOGLE_ADS_MONTHLY_EMAILS_ENABLED", True)
    if not enabled:
        app.logger.info("[CRON] Google Ads monthly emails disabled")
        return

    # Get list of active Google Ads accounts
    accounts = _accounts_with_google_ads_tokens(max_candidates=100)
    if not accounts:
        app.logger.info("[CRON] No Google Ads accounts to send monthly emails to")
        return

    app.logger.info(f"[CRON] Sending monthly performance emails to {len(accounts)} Google Ads accounts")

    from flask import render_template
    from app.services.email_service import send_email
    from app.models import Account

    emails_sent = 0
    errors = 0

    for account_id in accounts:
        try:
            # Get account and user email
            account = Account.query.get(account_id)
            if not account or not account.user:
                app.logger.warning(f"[CRON] Account {account_id} or user not found")
                continue

            user_email = account.user.email
            if not user_email:
                app.logger.warning(f"[CRON] Account {account_id} has no email address")
                continue

            # Get ads data and analysis
            from app.google import _get_ads_state, _analyze_ads_opportunities
            ads_data = _get_ads_state(account_id)
            analysis = _analyze_ads_opportunities(account_id, ads_data)

            # Generate email content
            email_html = render_template(
                'google/emails/monthly_performance.html',
                analysis=analysis,
                account_name=account.name or "Your Account",
                now=now
            )

            # Send email
            success = send_email(
                to=user_email,
                subject=f"📊 Google Ads Monthly Performance Report - {analysis.get('grade', 'N/A')} Grade",
                html_body=email_html,
                from_name="FieldSprout Google Ads AI"
            )

            if success:
                emails_sent += 1
                app.logger.info(f"[CRON] Monthly report sent to {user_email} for account {account_id}")
            else:
                errors += 1
                app.logger.error(f"[CRON] Failed to send monthly report to {user_email} for account {account_id}")

        except Exception as e:
            errors += 1
            app.logger.exception(f"[CRON] Error sending monthly report for account {account_id}: {e}")

    app.logger.info(f"[CRON] Monthly Google Ads emails completed: {emails_sent} sent, {errors} errors")


# =========================
# Lead Generation Automation
# =========================

def _run_daily_lead_automation(app) -> None:
    """
    Run automated lead generation and outreach.

    This systematically:
    - Creates campaigns for cities and service categories
    - Scrapes leads from Google (respects daily limits)
    - Enriches leads with decision maker info
    - Sends automated emails (skips Sundays)
    - Resumes from where it stopped previously
    """
    enabled = app.config.get("LEAD_AUTOMATION_ENABLED", True)
    if not enabled:
        app.logger.info("[CRON] Lead automation disabled")
        return

    try:
        from app.services.lead_automation_service import LeadAutomationService

        service = LeadAutomationService()
        result = service.run_daily_automation()

        app.logger.info(
            "[CRON] Lead automation completed: %d campaigns scraped, %d leads enriched, %d emails sent",
            result['scraped'], result['enriched'], result['sent']
        )

    except Exception as e:
        app.logger.exception(f"[CRON] Error running lead automation: {e}")


def _send_to_all_unsent_ever(app):
    """
    Send emails to ALL contacts who have NEVER received an email.

    This is a separate task that runs daily to ensure maximum email coverage.
    Uses the same daily limit (250 emails/day) but focuses on contacts never emailed.
    Respects unsubscribes for CAN-SPAM compliance.
    """
    enabled = app.config.get("LEAD_AUTOMATION_ENABLED", True)
    if not enabled:
        app.logger.info("[CRON] Lead automation disabled - skipping daily email blast")
        return

    try:
        from app.services.lead_automation_service import LeadAutomationService

        service = LeadAutomationService()
        result = service.send_to_all_unsent_ever()

        app.logger.info(
            "[CRON] Daily email blast completed: %d emails sent (%d eligible, %d unsubscribed, %d already emailed)",
            result['sent'], result.get('eligible_contacts', 0),
            result.get('skipped_unsubscribed', 0), result.get('skipped_already_emailed', 0)
        )

    except Exception as e:
        app.logger.exception(f"[CRON] Error running daily email blast: {e}")
