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
                    got.customer_id,
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


def register_commands(app):
    """Register all CLI commands with the Flask app."""
    app.cli.add_command(run_agents_command)
    app.cli.add_command(run_lead_automation_command)
    app.cli.add_command(send_pending_emails_command)
    app.cli.add_command(check_email_status_command)
