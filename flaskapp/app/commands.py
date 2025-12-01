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


def register_commands(app):
    """Register all CLI commands with the Flask app."""
    app.cli.add_command(run_agents_command)
    app.cli.add_command(run_lead_automation_command)
