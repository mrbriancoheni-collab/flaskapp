#!/usr/bin/env python3
"""
Google Ads AI Agents Runner

Runs AI agents for all active accounts with Google Ads connected.
Agents analyze performance data and auto-execute low-risk optimizations.

Usage:
    python3 run_agents.py                    # run all layers
    python3 run_agents.py --layer tactical   # quick bid/keyword adjustments (hourly)
    python3 run_agents.py --layer operational  # budget/campaign management (every 4h)
    python3 run_agents.py --layer strategic  # structural decisions (daily)
"""
import sys
import os
import argparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'flaskapp'))

# Load .env before importing app (searches parent dir too)
from scripts.load_env import load_environment
load_environment(os.path.dirname(os.path.abspath(__file__)))


def main():
    parser = argparse.ArgumentParser(description='Run Google Ads AI agents')
    parser.add_argument('--layer', choices=['tactical', 'operational', 'strategic', 'negative_keyword', 'all'],
                        default='all', help='Which agent layer to run')
    parser.add_argument('--force', action='store_true',
                        help='Ignore cadence throttle and run immediately (for testing)')
    args = parser.parse_args()

    from app import create_app
    app = create_app()

    with app.app_context():
        if args.force:
            from app.services.agent_cadence import force_due
            from sqlalchemy import text
            from app import db
            layers = [args.layer] if args.layer != 'all' else ['tactical', 'operational', 'strategic', 'negative_keyword']
            try:
                with db.engine.connect() as conn:
                    rows = conn.execute(text("SELECT DISTINCT id FROM accounts WHERE status IN ('active','trial')"))
                    account_ids = [r[0] for r in rows]
                for aid in account_ids:
                    for ly in layers:
                        force_due(aid, 'google', ly)
                print(f"Force-reset cadence for {len(account_ids)} accounts ({', '.join(layers)})")
            except Exception as e:
                print(f"Warning: could not reset cadence: {e}")

        from app.tasks.agent_scheduler import run_agents_for_all_accounts

        print(f"Running {args.layer} agents...")
        success_count, error_count = run_agents_for_all_accounts(layer=args.layer)
        print(f"Done: {success_count} accounts succeeded, {error_count} failed")
        return 0 if error_count == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
