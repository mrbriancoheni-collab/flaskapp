"""
Flask CLI commands for agent management.

Usage:
    flask run-agents --layer tactical
    flask run-agents --layer operational
    flask run-agents --layer strategic
    flask run-agents --all
"""
import click
from flask import current_app
from flask.cli import with_appcontext


@click.command('run-agents')
@click.option('--layer', default='all', type=click.Choice(['all', 'strategic', 'operational', 'tactical']),
              help='Which agent layer to run (default: all)')
@click.option('--account', type=int, help='Run for specific account ID only')
@with_appcontext
def run_agents_command(layer, account):
    """
    Run AI agents for Google Ads optimization.

    Examples:
        flask run-agents --layer tactical  # Run hourly tactical agents
        flask run-agents --layer operational  # Run 4-hourly operational agents
        flask run-agents --layer strategic  # Run daily strategic agent
        flask run-agents --all  # Run all agents
        flask run-agents --account 123  # Run for specific account only
    """
    from app.tasks.agent_scheduler import run_agents_for_all_accounts, run_agents_for_account
    from app import db
    from sqlalchemy import text
    import json

    click.echo(f"\n{'='*60}")
    click.echo(f"Running {layer.upper()} agents...")
    click.echo(f"{'='*60}\n")

    try:
        if account:
            # Run for specific account only
            query = text("""
                SELECT
                    a.id as account_id,
                    a.google_ads_customer_id as customer_id,
                    got.credentials_json
                FROM accounts a
                JOIN google_oauth_tokens got ON a.id = got.account_id
                WHERE a.id = :account_id AND got.product = 'ads'
                LIMIT 1
            """)

            with db.engine.connect() as conn:
                result = conn.execute(query, {"account_id": account})
                row = result.first()

                if not row:
                    click.echo(f"❌ Account {account} not found or Google Ads not connected", err=True)
                    return 1

            click.echo(f"Running agents for account {account}...")

            run_agents_for_account(
                account_id=row.account_id,
                customer_id=row.customer_id,
                credentials_json=row.credentials_json,
                layer=layer
            )

            click.echo(f"\n✅ Completed for account {account}")

        else:
            # Run for all accounts
            success_count, error_count = run_agents_for_all_accounts(layer)

            click.echo(f"\n{'='*60}")
            click.echo(f"✅ Completed: {success_count} succeeded, {error_count} failed")
            click.echo(f"{'='*60}\n")

            if error_count > 0:
                return 1

        return 0

    except Exception as e:
        click.echo(f"\n❌ Error: {str(e)}", err=True)
        import traceback
        click.echo(traceback.format_exc(), err=True)
        return 1


@click.command('run-lead-automation')
@click.option('--dry-run', is_flag=True, help='Show what would be done without making changes')
@with_appcontext
def run_lead_automation_command(dry_run):
    """
    Run automated lead generation and outreach.

    This command:
    - Creates campaigns for cities and service categories
    - Scrapes leads from Google (respects daily limits)
    - Enriches leads with decision maker info
    - Sends automated emails (skips Sundays)
    - Resumes from where it stopped previously

    Examples:
        flask run-lead-automation          # Run daily automation
        flask run-lead-automation --dry-run  # Preview what will be done
    """
    from app.services.lead_automation_service import LeadAutomationService

    click.echo(f"\n{'='*80}")
    click.echo("LEAD GENERATION AUTOMATION")
    click.echo(f"{'='*80}\n")

    try:
        service = LeadAutomationService()

        if dry_run:
            click.echo("DRY RUN MODE - No changes will be made\n")
            progress = service.get_progress_report()
            click.echo(f"Current Progress:")
            click.echo(f"  Total Campaigns Planned: {progress['total_campaigns_planned']}")
            click.echo(f"  Campaigns Created: {progress['campaigns_created']}")
            click.echo(f"  Campaigns Scraped: {progress['campaigns_scraped']}")
            click.echo(f"  Progress: {progress['progress_percent']:.1f}%")
            click.echo(f"  Leads Enriched: {progress['leads_enriched']}")
            click.echo(f"  Emails Sent: {progress['emails_sent']}")
            click.echo(f"  Unique Domains: {progress['unique_domains_processed']}")
            click.echo(f"\nDaily Stats ({progress['daily_stats']['date']}):")
            click.echo(f"  Scrapes: {progress['daily_stats']['scrapes']}")
            click.echo(f"  Enrichments: {progress['daily_stats']['enrichments']}")
            click.echo(f"  Emails: {progress['daily_stats']['emails']}")
            return 0

        # Run automation
        result = service.run_daily_automation()

        click.echo("\nResults:")
        click.echo(f"  Campaigns Scraped: {result['scraped']}")
        click.echo(f"  Leads Enriched: {result['enriched']}")
        click.echo(f"  Emails Sent: {result['sent']}")
        click.echo(f"\nTotal Progress:")
        click.echo(f"  Total Campaigns: {result['total_campaigns']}")
        click.echo(f"  Total Emails: {result['total_emails']}")

        click.echo(f"\n{'='*80}")
        click.echo("AUTOMATION COMPLETE")
        click.echo(f"{'='*80}\n")

        return 0

    except Exception as e:
        click.echo(f"\nError running automation: {e}", err=True)
        import traceback
        traceback.print_exc()
        return 1


@click.command('send-pending-emails')
@with_appcontext
def send_pending_emails_command():
    """
    Send emails to enriched leads without scraping or enrichment.

    This command:
    - Sends emails to all enriched leads with pending contacts
    - Auto-creates email sequences if missing
    - Respects daily email limit (250/day)
    - Skips scraping and enrichment steps

    Examples:
        flask send-pending-emails  # Send to all pending contacts
    """
    from app.services.lead_automation_service import LeadAutomationService

    click.echo(f"\n{'='*80}")
    click.echo("SENDING PENDING EMAILS ONLY")
    click.echo(f"{'='*80}\n")

    try:
        service = LeadAutomationService()

        # Show current progress
        progress = service.get_progress_report()
        click.echo(f"Current Stats:")
        click.echo(f"  Total Campaigns: {progress['campaigns_created']}")
        click.echo(f"  Leads Enriched: {progress['leads_enriched']}")
        click.echo(f"  Emails Sent: {progress['emails_sent']}")
        click.echo(f"\nToday's Stats ({progress['daily_stats']['date']}):")
        click.echo(f"  Emails: {progress['daily_stats']['emails']}/250")
        click.echo(f"\n{'='*80}\n")

        # Only send emails (skip scraping and enrichment)
        sent_count = service._process_email_sending()

        # Save state
        service._save_state()

        click.echo(f"\n{'='*80}")
        click.echo("EMAIL SENDING COMPLETE")
        click.echo(f"{'='*80}")
        click.echo(f"  Emails Sent: {sent_count}")
        click.echo(f"{'='*80}\n")

        return 0

    except Exception as e:
        click.echo(f"\nError sending emails: {e}", err=True)
        import traceback
        traceback.print_exc()
        return 1


@click.command('check-email-status')
@click.option('--days', default=1, type=int, help='Check emails from last N days (default: 1)')
@with_appcontext
def check_email_status_command(days):
    """
    Check email sending status and verify email provider configuration.

    Shows:
    - Total emails sent (today and last N days)
    - Breakdown by status (sent, failed, pending)
    - Email provider being used
    - Sample of recent emails

    Examples:
        flask check-email-status           # Today's emails
        flask check-email-status --days 7  # Last 7 days
    """
    import os
    from datetime import datetime, timedelta
    from app.models_leads import LeadContactEmail, LeadEmail

    click.echo(f"\n{'='*80}")
    click.echo("EMAIL STATUS DIAGNOSTIC")
    click.echo(f"{'='*80}\n")

    # Check email provider configuration
    email_provider = os.getenv('EMAIL_PROVIDER', 'mailgun').lower()
    click.echo(f"📧 Email Provider: {email_provider.upper()}")

    if email_provider == 'brevo':
        brevo_key = os.getenv('BREVO_API_KEY')
        brevo_email = os.getenv('BREVO_FROM_EMAIL', 'noreply@fieldsprout.io')
        brevo_name = os.getenv('BREVO_FROM_NAME', 'FieldSprout')
        click.echo(f"   API Key: {'✓ Set' if brevo_key else '✗ MISSING'}")
        click.echo(f"   From Email: {brevo_email}")
        click.echo(f"   From Name: {brevo_name}")
    else:
        mailgun_key = os.getenv('MAILGUN_API_KEY')
        mailgun_domain = os.getenv('MAILGUN_DOMAIN')
        click.echo(f"   API Key: {'✓ Set' if mailgun_key else '✗ MISSING'}")
        click.echo(f"   Domain: {mailgun_domain or '✗ MISSING'}")

    click.echo()

    # Calculate date range
    today = datetime.utcnow().date()
    start_date = today - timedelta(days=days-1)

    # Query contact emails (new system)
    contact_emails_all = LeadContactEmail.query.all()
    contact_emails_range = [e for e in contact_emails_all
                           if e.sent_at and e.sent_at.date() >= start_date]
    contact_emails_today = [e for e in contact_emails_all
                           if e.sent_at and e.sent_at.date() == today]

    # Query legacy emails
    legacy_emails_all = LeadEmail.query.all()
    legacy_emails_range = [e for e in legacy_emails_all
                          if e.sent_at and e.sent_at.date() >= start_date]
    legacy_emails_today = [e for e in legacy_emails_all
                          if e.sent_at and e.sent_at.date() == today]

    # Combined totals
    total_all_time = len(contact_emails_all) + len(legacy_emails_all)
    total_range = len(contact_emails_range) + len(legacy_emails_range)
    total_today = len(contact_emails_today) + len(legacy_emails_today)

    click.echo(f"📊 Email Counts:")
    click.echo(f"   All Time: {total_all_time} emails")
    click.echo(f"   Last {days} day(s): {total_range} emails")
    click.echo(f"   Today: {total_today} emails")
    click.echo()

    # Status breakdown (contact emails only, legacy doesn't have status)
    if contact_emails_range:
        statuses = {}
        for email in contact_emails_range:
            status = email.status or 'unknown'
            statuses[status] = statuses.get(status, 0) + 1

        click.echo(f"📈 Status Breakdown (last {days} day(s)):")
        for status, count in sorted(statuses.items()):
            click.echo(f"   {status}: {count}")
        click.echo()

    # Provider breakdown
    if contact_emails_range:
        providers = {}
        for email in contact_emails_range:
            provider = email.email_provider or 'unknown'
            providers[provider] = providers.get(provider, 0) + 1

        click.echo(f"🚀 Provider Breakdown (last {days} day(s)):")
        for provider, count in sorted(providers.items()):
            click.echo(f"   {provider}: {count}")
        click.echo()

    # Show recent emails
    click.echo(f"📬 Recent Emails (last 5):")
    recent_contact = LeadContactEmail.query.order_by(
        LeadContactEmail.sent_at.desc()
    ).limit(5).all()

    if recent_contact:
        for email in recent_contact:
            provider = email.email_provider or 'unknown'
            msg_id = email.brevo_message_id if email.email_provider == 'brevo' else email.mailgun_message_id
            click.echo(f"   • {email.to_email or '(no email stored)'}")
            click.echo(f"     Provider: {provider}")
            click.echo(f"     Sent: {email.sent_at}")
            click.echo(f"     Status: {email.status}")
            click.echo(f"     Message ID: {msg_id or 'N/A'}")
            click.echo(f"     Subject: {email.subject[:60]}...")
            click.echo()
    else:
        click.echo("   No emails found")
        click.echo()

    # Check for pending emails
    pending_contact = LeadContactEmail.query.filter_by(status='pending').count()
    click.echo(f"⏳ Pending Emails: {pending_contact}")
    click.echo()

    click.echo(f"{'='*80}\n")


@click.command('test-email-provider')
@click.option('--to', 'to_email', required=True, help='Email address to send test email to')
@click.option('--provider', type=click.Choice(['brevo', 'mailgun']), help='Override EMAIL_PROVIDER env var')
@with_appcontext
def test_email_provider_command(to_email, provider):
    """
    Test email provider connection by sending a test email.

    This validates:
    - API credentials are correct
    - API connection is working
    - Email sending functionality works
    - Provider returns proper message IDs

    Examples:
        flask test-email-provider --to your@email.com
        flask test-email-provider --to your@email.com --provider brevo
        flask test-email-provider --to your@email.com --provider mailgun
    """
    import os
    from datetime import datetime

    click.echo(f"\n{'='*80}")
    click.echo("EMAIL PROVIDER CONNECTION TEST")
    click.echo(f"{'='*80}\n")

    # Determine which provider to use
    email_provider = provider or os.getenv('EMAIL_PROVIDER', 'mailgun').lower()
    click.echo(f"🔧 Testing Provider: {email_provider.upper()}")
    click.echo(f"📧 Test Email To: {to_email}\n")

    # Initialize the provider
    try:
        if email_provider == 'brevo':
            from app.services.brevo_outreach import BrevoOutreachService

            # Check env vars
            api_key = os.getenv('BREVO_API_KEY')
            from_email = os.getenv('BREVO_FROM_EMAIL', 'noreply@fieldsprout.io')
            from_name = os.getenv('BREVO_FROM_NAME', 'FieldSprout')

            click.echo("📋 Configuration:")
            click.echo(f"   API Key: {'✓ Set (' + api_key[:20] + '...)' if api_key else '✗ MISSING'}")
            click.echo(f"   From Email: {from_email}")
            click.echo(f"   From Name: {from_name}\n")

            if not api_key:
                click.echo("❌ ERROR: BREVO_API_KEY environment variable not set", err=True)
                return 1

            click.echo("🔌 Initializing Brevo service...")
            service = BrevoOutreachService()

        else:
            from app.services.mailgun_outreach import MailgunOutreachService

            # Check env vars
            api_key = os.getenv('MAILGUN_API_KEY')
            domain = os.getenv('MAILGUN_DOMAIN')

            click.echo("📋 Configuration:")
            click.echo(f"   API Key: {'✓ Set (' + api_key[:20] + '...)' if api_key else '✗ MISSING'}")
            click.echo(f"   Domain: {domain or '✗ MISSING'}\n")

            if not api_key or not domain:
                click.echo("❌ ERROR: MAILGUN_API_KEY and MAILGUN_DOMAIN environment variables required", err=True)
                return 1

            click.echo("🔌 Initializing Mailgun service...")
            service = MailgunOutreachService()

        click.echo("✓ Service initialized successfully\n")

    except Exception as e:
        click.echo(f"❌ ERROR initializing {email_provider} service: {e}", err=True)
        import traceback
        traceback.print_exc()
        return 1

    # Send test email
    try:
        click.echo("📤 Sending test email...")

        subject = f"Test Email from {email_provider.title()} - {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}"
        body_text = f"""This is a test email from your FieldSprout lead generation system.

Provider: {email_provider.upper()}
Sent at: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}

If you received this email, your {email_provider.title()} integration is working correctly!

✓ API credentials are valid
✓ Connection is established
✓ Email sending is functional

You can now use this provider for your automated lead generation campaigns.
"""

        body_html = body_text.replace('\n', '<br>')

        result = service.send_email(
            to_email=to_email,
            subject=subject,
            body_html=body_html,
            body_text=body_text
        )

        click.echo(f"\n{'='*80}")
        click.echo("TEST RESULT")
        click.echo(f"{'='*80}\n")

        if result.get('success'):
            click.echo("✅ SUCCESS! Email sent successfully\n")
            click.echo(f"📊 Details:")
            click.echo(f"   Provider: {email_provider}")
            click.echo(f"   To: {to_email}")
            click.echo(f"   Message ID: {result.get('message_id', 'N/A')}")

            if result.get('rate_limited'):
                click.echo(f"   ⚠️  Rate Limited: Retry after {result.get('retry_after', 'unknown')} seconds")

            click.echo(f"\n✓ Your {email_provider.title()} integration is working correctly!")
            click.echo(f"✓ Check {to_email} for the test email")

        else:
            click.echo("❌ FAILED to send email\n")
            click.echo(f"Error: {result.get('error', 'Unknown error')}")

            if result.get('rate_limited'):
                click.echo(f"\n⚠️  Rate Limited: Retry after {result.get('retry_after', 'unknown')} seconds")
                click.echo("This is normal if you've been sending many emails.")

            return 1

        click.echo(f"\n{'='*80}\n")
        return 0

    except Exception as e:
        click.echo(f"\n❌ ERROR sending test email: {e}", err=True)
        import traceback
        traceback.print_exc()
        return 1


@click.command('seed-ai-actions')
@click.option('--account', type=int, required=True, help='Account ID to seed actions for (REQUIRED)')
@click.option('--count', type=int, default=15, help='Number of test actions to create (default: 15)')
@click.option('--clear', is_flag=True, help='Clear existing test actions before seeding')
@click.option('--force', is_flag=True, help='Skip confirmation (DEVELOPMENT ONLY)')
@with_appcontext
def seed_ai_actions_command(account, count, clear, force):
    """
    [DEVELOPMENT ONLY] Seed test AI action data for the /performance page.

    WARNING: This command creates FAKE sample data. Never use on real customer accounts.
    Sample data will confuse customers and misrepresent actual performance.

    This is strictly for local development and testing purposes.

    Examples:
        flask seed-ai-actions --account 999 --force   # Dev testing only
        flask seed-ai-actions --account 999 --clear   # Clear sample data
    """
    import os

    # Block in production
    if os.environ.get('FLASK_ENV') == 'production' or os.environ.get('PRODUCTION'):
        click.echo("\n❌ ERROR: This command is disabled in production.", err=True)
        click.echo("Sample data should never be shown to real customers.", err=True)
        return 1

    if not force:
        click.echo("\n⚠️  WARNING: This creates FAKE sample data.")
        click.echo("Never use this on real customer accounts.")
        click.echo("Sample data will confuse customers and misrepresent performance.\n")
        if not click.confirm(f"Are you sure you want to seed FAKE data for account {account}?"):
            click.echo("Aborted.")
            return 0
    from app import db
    from app.models_ai_actions import AIAction
    from datetime import datetime, timedelta
    import random

    click.echo(f"\n{'='*60}")
    click.echo(f"Seeding AI actions for account {account}...")
    click.echo(f"{'='*60}\n")

    if clear:
        deleted = AIAction.query.filter_by(account_id=account).delete()
        db.session.commit()
        click.echo(f"Cleared {deleted} existing actions for account {account}")

    # Realistic test action templates
    templates = [
        {
            "action_type": "negative_keyword_added",
            "title": "Blocked wasteful search term: '{term}'",
            "description": "Added negative keyword '{term}' to campaign '{campaign}' to prevent wasted spend on irrelevant searches.",
            "reasoning": "Search term '{term}' had 0 conversions over 30 days with ${spend:.2f} spend. CTR was {ctr:.1f}% indicating low intent.",
            "terms": ["free estimate near me", "diy plumbing repair", "plumber salary", "how to fix toilet", "plumbing school"],
            "savings_range": (15, 120),
            "confidence_range": (0.85, 0.98),
        },
        {
            "action_type": "bid_adjusted",
            "title": "Increased bid on high-converting keyword",
            "description": "Raised bid on '{term}' in '{campaign}' from ${before:.2f} to ${after:.2f} to capture more converting traffic.",
            "reasoning": "Keyword '{term}' has {conv} conversions at ${cpa:.2f} CPA, well below target. Increasing bid to gain impression share.",
            "terms": ["emergency plumber", "ac repair near me", "roof replacement cost", "electrician nearby", "pest control service"],
            "savings_range": (0, 50),
            "confidence_range": (0.75, 0.95),
        },
        {
            "action_type": "budget_reallocated",
            "title": "Shifted budget to top-performing campaign",
            "description": "Moved ${amount:.2f}/day from '{campaign_from}' to '{campaign_to}' based on conversion performance.",
            "reasoning": "'{campaign_to}' has 2.3x higher conversion rate than '{campaign_from}'. Reallocating budget to maximize ROI.",
            "savings_range": (50, 300),
            "confidence_range": (0.80, 0.95),
        },
        {
            "action_type": "keyword_paused",
            "title": "Paused underperforming keyword",
            "description": "Paused keyword '{term}' in '{campaign}' due to consistently poor performance over 30 days.",
            "reasoning": "Keyword '{term}' spent ${spend:.2f} with 0 conversions and {ctr:.1f}% CTR. Quality Score: {qs}/10.",
            "terms": ["general contractor", "home improvement", "handyman services", "renovation company"],
            "savings_range": (20, 80),
            "confidence_range": (0.82, 0.96),
        },
        {
            "action_type": "quality_score_fix",
            "title": "Improved Quality Score for '{term}'",
            "description": "Recommended ad copy and landing page improvements for '{term}' to boost Quality Score from {qs_before}/10 to {qs_after}/10.",
            "reasoning": "Low Quality Score on '{term}' is increasing CPC by ~40%. Ad relevance and landing page experience rated 'Below Average'.",
            "terms": ["water heater installation", "hvac maintenance", "roof inspection", "drain cleaning"],
            "savings_range": (30, 150),
            "confidence_range": (0.70, 0.90),
        },
    ]

    campaigns = [
        "Google Ads - Emergency Services",
        "Google Ads - Residential",
        "Google Ads - Commercial",
        "Google Ads - Brand",
        "Performance Max - Local",
    ]

    now = datetime.utcnow()
    created = 0

    for i in range(count):
        tmpl = random.choice(templates)
        term = random.choice(tmpl.get("terms", ["service keyword"]))
        campaign = random.choice(campaigns)
        savings = round(random.uniform(*tmpl["savings_range"]), 2)
        confidence = round(random.uniform(*tmpl["confidence_range"]), 3)
        hours_ago = random.randint(1, 72)
        executed_at = now - timedelta(hours=hours_ago)

        # Build title/description with template vars
        fmt_vars = {
            "term": term, "campaign": campaign,
            "spend": random.uniform(20, 200), "ctr": random.uniform(0.5, 3.0),
            "conv": random.randint(3, 25), "cpa": random.uniform(15, 80),
            "before": random.uniform(1.5, 4.0), "after": random.uniform(3.0, 7.0),
            "amount": random.uniform(5, 30),
            "campaign_from": random.choice(campaigns), "campaign_to": campaign,
            "qs": random.randint(2, 5), "qs_before": random.randint(3, 5), "qs_after": random.randint(6, 9),
        }

        action = AIAction(
            account_id=account,
            action_type=tmpl["action_type"],
            title=tmpl["title"].format(**fmt_vars),
            description=tmpl["description"].format(**fmt_vars),
            reasoning=tmpl["reasoning"].format(**fmt_vars),
            campaign_name=campaign,
            estimated_monthly_savings=savings,
            confidence_score=confidence,
            status="executed",
            executed_at=executed_at,
            executed_by="ai_agent",
            can_undo=True,
            created_at=executed_at,
        )
        db.session.add(action)
        created += 1

    db.session.commit()

    # Show summary
    total = AIAction.query.filter_by(account_id=account, status='executed').count()
    total_savings = db.session.query(
        db.func.sum(AIAction.estimated_monthly_savings)
    ).filter_by(account_id=account, status='executed').scalar() or 0

    click.echo(f"Created {created} test AI actions for account {account}")
    click.echo(f"Total executed actions: {total}")
    click.echo(f"Total estimated savings: ${total_savings:.2f}/mo")
    click.echo(f"\nVisit /account/google/ads/performance to see them.")
    click.echo(f"{'='*60}\n")


@click.command('clear-sample-data')
@click.option('--account', type=int, required=True, help='Account ID to clear sample data from')
@with_appcontext
def clear_sample_data_command(account):
    """
    Clear any sample/seeded AI actions from an account.

    Use this to remove accidentally seeded test data from real customer accounts.

    Examples:
        flask clear-sample-data --account 3    # Clear sample data from account 3
    """
    from app import db
    from app.models_ai_actions import AIAction

    click.echo(f"\nClearing sample data from account {account}...")

    # Delete all AI actions that were created by seeding (executed_by = 'ai_agent' with generic campaign names)
    # Real AI actions would come from actual agent runs with real campaign IDs
    deleted = AIAction.query.filter_by(account_id=account).delete()
    db.session.commit()

    click.echo(f"✓ Cleared {deleted} AI actions from account {account}")
    click.echo("The performance page will now only show real data from Google Ads API.\n")


@click.command('run-auto-executor')
@click.option('--account', type=int, required=True, help='Account ID to run auto-executor for')
@click.option('--dry-run', is_flag=True, help='Preview actions without executing')
@click.option('--lookback', type=int, default=30, help='Days of search term data to analyze (default: 30)')
@with_appcontext
def run_auto_executor_command(account, dry_run, lookback):
    """
    Manually trigger the Google Ads Auto-Executor for a specific account.

    This analyzes search term reports and automatically:
    - Adds negative keywords for wasteful searches
    - Creates AIAction records with full audit trail

    Examples:
        flask run-auto-executor --account 3              # Run for account 3
        flask run-auto-executor --account 3 --dry-run    # Preview without executing
        flask run-auto-executor --account 3 --lookback 7 # Only last 7 days
    """
    click.echo(f"\n{'='*60}")
    click.echo(f"Running Auto-Executor for account {account}")
    click.echo(f"Mode: {'DRY RUN (preview only)' if dry_run else 'EXECUTE'}")
    click.echo(f"Lookback: {lookback} days")
    click.echo(f"{'='*60}\n")

    try:
        from app.services.google_ads_auto_executor import GoogleAdsAutoExecutor
        from app.models import Account, GoogleAdsAuth
        from app.models_google import GoogleOAuthToken
        from app import db
        from sqlalchemy import text

        # Verify account exists and has Google Ads connected
        acct = Account.query.get(account)
        if not acct:
            click.echo(f"❌ Account {account} not found", err=True)
            return 1

        token = GoogleOAuthToken.query.filter_by(account_id=account, product='ads').first()
        if not token:
            click.echo(f"❌ Account {account} has no Google Ads connected", err=True)
            return 1

        # Get customer_id - try accounts table first, then GoogleAdsAuth
        customer_id = None
        with db.engine.connect() as conn:
            row = conn.execute(
                text("SELECT google_ads_customer_id FROM accounts WHERE id = :aid"),
                {"aid": account}
            ).first()
            if row and row[0]:
                customer_id = row[0]

        if not customer_id:
            ads_auth = GoogleAdsAuth.query.filter_by(account_id=account).first()
            customer_id = ads_auth.customer_id if ads_auth else None

        click.echo(f"✓ Account: {acct.name or acct.id}")
        click.echo(f"✓ Google Ads Customer ID: {customer_id or 'Not set'}")
        click.echo("")

        # Run the auto-executor
        executor = GoogleAdsAutoExecutor(account)
        actions = executor.auto_add_negative_keywords(lookback_days=lookback, dry_run=dry_run)

        if actions:
            click.echo(f"\n{'='*60}")
            click.echo(f"{'PREVIEW' if dry_run else 'CREATED'} {len(actions)} actions:")
            click.echo(f"{'='*60}")
            for action in actions[:10]:  # Show first 10
                click.echo(f"  • {action.get('title', action.get('keyword', 'Unknown'))}")
                if action.get('estimated_monthly_savings'):
                    click.echo(f"    Savings: ${action['estimated_monthly_savings']:.2f}/mo")
            if len(actions) > 10:
                click.echo(f"  ... and {len(actions) - 10} more")
        else:
            click.echo("\n✓ No wasteful search terms found - account looks clean!")

        click.echo(f"\n{'='*60}\n")

    except Exception as e:
        click.echo(f"\n❌ Error: {e}", err=True)
        import traceback
        traceback.print_exc()
        return 1


@click.command('run-all-ai')
@click.option('--account', type=int, required=True, help='Account ID to run all AI for')
@with_appcontext
def run_all_ai_command(account):
    """
    Run ALL AI agents and auto-executor for a specific account immediately.

    This triggers:
    1. Strategic agents (campaign structure, budget allocation)
    2. Operational agents (budget guardian, quality score)
    3. Tactical agents (keyword optimizer, negative keywords, ad copy)
    4. Auto-Executor (automatic negative keyword additions)

    Examples:
        flask run-all-ai --account 3    # Run everything for account 3
    """
    click.echo(f"\n{'='*60}")
    click.echo(f"Running ALL AI for account {account}")
    click.echo(f"{'='*60}\n")

    try:
        from app.tasks.agent_scheduler import run_agents_for_account
        from app.services.google_ads_auto_executor import GoogleAdsAutoExecutor
        from app.models import Account, GoogleAdsAuth
        from app.models_google import GoogleOAuthToken
        from app import db
        from sqlalchemy import text
        import json

        # Verify account
        acct = Account.query.get(account)
        if not acct:
            click.echo(f"❌ Account {account} not found", err=True)
            return 1

        token = GoogleOAuthToken.query.filter_by(account_id=account, product='ads').first()
        if not token:
            click.echo(f"❌ Account {account} has no Google Ads connected", err=True)
            return 1

        # Get customer_id - try accounts table first, then GoogleAdsAuth
        customer_id = None

        # First try accounts table (primary source)
        with db.engine.connect() as conn:
            row = conn.execute(
                text("SELECT google_ads_customer_id FROM accounts WHERE id = :aid"),
                {"aid": account}
            ).first()
            if row and row[0]:
                customer_id = row[0]

        # Fallback to GoogleAdsAuth table
        if not customer_id:
            ads_auth = GoogleAdsAuth.query.filter_by(account_id=account).first()
            customer_id = ads_auth.customer_id if ads_auth else None

        click.echo(f"✓ Account: {acct.name or acct.id}")
        click.echo(f"✓ Google Ads Customer ID: {customer_id or 'Not set'}\n")

        # Get credentials from token
        if not token.credentials_json:
            click.echo(f"❌ No valid credentials for account {account}", err=True)
            return 1

        credentials = json.loads(token.credentials_json) if isinstance(token.credentials_json, str) else token.credentials_json

        # 1. Run Strategic Agents
        click.echo("1️⃣  Running STRATEGIC agents...")
        try:
            run_agents_for_account(account, customer_id, credentials, layer='strategic')
            click.echo("   ✓ Strategic agents complete")
        except Exception as e:
            click.echo(f"   ⚠ Strategic agents error: {e}")

        # 2. Run Operational Agents
        click.echo("2️⃣  Running OPERATIONAL agents...")
        try:
            run_agents_for_account(account, customer_id, credentials, layer='operational')
            click.echo("   ✓ Operational agents complete")
        except Exception as e:
            click.echo(f"   ⚠ Operational agents error: {e}")

        # 3. Run Tactical Agents
        click.echo("3️⃣  Running TACTICAL agents...")
        try:
            run_agents_for_account(account, customer_id, credentials, layer='tactical')
            click.echo("   ✓ Tactical agents complete")
        except Exception as e:
            click.echo(f"   ⚠ Tactical agents error: {e}")

        # 4. Run Auto-Executor
        click.echo("4️⃣  Running AUTO-EXECUTOR...")
        try:
            executor = GoogleAdsAutoExecutor(account)
            actions = executor.auto_add_negative_keywords(lookback_days=30, dry_run=False)
            click.echo(f"   ✓ Auto-executor complete: {len(actions)} actions created")
        except Exception as e:
            click.echo(f"   ⚠ Auto-executor error: {e}")

        # Summary
        click.echo(f"\n{'='*60}")
        click.echo(f"✓ All AI processing complete for account {account}")
        click.echo("Visit /account/google/ads/performance to see results")
        click.echo(f"{'='*60}\n")

    except Exception as e:
        click.echo(f"\n❌ Error: {e}", err=True)
        import traceback
        traceback.print_exc()
        return 1


@click.command('train-ml')
@click.option('--account', type=int, help='Train models for specific account ID only')
@click.option('--model', type=str, help='Train specific model only (e.g., budget_roi, anomaly, spend_forecast)')
@with_appcontext
def train_ml_command(account, model):
    """
    Train ML models for Google Ads optimization.

    This trains predictive models using historical Google Ads data to help
    AI agents make better decisions. Models are retrained weekly automatically.

    Examples:
        flask train-ml                    # Train all models for all accounts
        flask train-ml --account 123      # Train for specific account only
        flask train-ml --model budget_roi # Train specific model type only
    """
    from app.ml.trainer import MLTrainer

    click.echo(f"\n{'='*60}")
    click.echo("Training ML Models for Google Ads Optimization")
    click.echo(f"{'='*60}\n")

    try:
        if account:
            click.echo(f"Training models for account {account}...")
            trainer = MLTrainer(account)

            if model:
                # Train specific model
                model_map = {
                    'budget_roi': trainer._train_budget_roi,
                    'anomaly': trainer._train_anomaly_detector,
                    'spend_forecast': trainer._train_spend_forecaster,
                    'quality_score': trainer._train_quality_score,
                    'cpa_predictor': trainer._train_cpa_predictor,
                    'waste_classifier': trainer._train_waste_classifier,
                    'ctr_predictor': trainer._train_ctr_predictor,
                }
                if model not in model_map:
                    click.echo(f"Unknown model: {model}", err=True)
                    click.echo(f"Available models: {', '.join(model_map.keys())}")
                    return 1
                result = model_map[model]()
                click.echo(f"  - {model}: {'trained' if result else 'skipped (insufficient data)'}")
            else:
                # Train all models
                results = trainer.train_all()
                for model_name, success in results.items():
                    status = 'trained' if success else 'skipped (insufficient data)'
                    click.echo(f"  - {model_name}: {status}")

            click.echo(f"\nTraining complete for account {account}")
        else:
            # Train all accounts
            click.echo("Training models for all Google Ads accounts...")
            from app.ml.trainer import train_all_accounts
            results = train_all_accounts()

            click.echo(f"\nTraining Summary:")
            click.echo(f"  Accounts processed: {results['accounts_processed']}")
            click.echo(f"  Models trained: {results['models_trained']}")
            click.echo(f"  Errors: {results['errors']}")

        click.echo(f"\n{'='*60}")
        click.echo("ML Training Complete")
        click.echo(f"{'='*60}\n")

    except Exception as e:
        click.echo(f"\nError during ML training: {e}", err=True)
        import traceback
        traceback.print_exc()
        return 1


def register_commands(app):
    """Register all CLI commands with the Flask app."""
    app.cli.add_command(run_agents_command)
    app.cli.add_command(run_lead_automation_command)
    app.cli.add_command(send_pending_emails_command)
    app.cli.add_command(check_email_status_command)
    app.cli.add_command(test_email_provider_command)
    app.cli.add_command(clear_sample_data_command)
    app.cli.add_command(run_auto_executor_command)
    app.cli.add_command(run_all_ai_command)
    app.cli.add_command(train_ml_command)
    # Note: seed_ai_actions_command intentionally not registered by default
    # It's a development-only tool that should not be used on real accounts
