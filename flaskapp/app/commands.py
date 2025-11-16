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


def register_commands(app):
    """Register all CLI commands with the Flask app."""
    app.cli.add_command(run_agents_command)
