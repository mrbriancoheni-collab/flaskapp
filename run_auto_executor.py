#!/usr/bin/env python3
"""
Google Ads Auto-Executor Runner

Runs the three-pass negative keyword pipeline (pattern → ML → LLM) for all
active accounts that have Google Ads OAuth tokens connected.

Usage:
    python3 run_auto_executor.py              # run for all accounts
    python3 run_auto_executor.py --account 3  # run for account 3 only
    python3 run_auto_executor.py --dry-run    # preview without executing
"""
import sys
import os
import argparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'flaskapp'))


def main():
    parser = argparse.ArgumentParser(description='Run Google Ads auto-executor (negative keywords)')
    parser.add_argument('--account', type=int, default=None,
                        help='Account ID to run for (default: all active accounts)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Preview actions without executing against Google Ads')
    parser.add_argument('--lookback', type=int, default=30,
                        help='Days of search term history to analyse (default: 30)')
    args = parser.parse_args()

    from app import create_app
    app = create_app()

    with app.app_context():
        from app.extensions import db
        from sqlalchemy import text

        if args.account:
            account_ids = [args.account]
        else:
            with db.engine.connect() as conn:
                rows = conn.execute(text("""
                    SELECT DISTINCT a.id
                    FROM accounts a
                    JOIN google_oauth_tokens got
                      ON a.id = got.account_id AND got.product = 'ads'
                    WHERE got.credentials_json IS NOT NULL
                """)).fetchall()
            account_ids = [r[0] for r in rows]

        if not account_ids:
            print("No accounts with Google Ads connected.")
            return 0

        print(f"Running auto-executor for {len(account_ids)} account(s): {account_ids}")
        print(f"Lookback: {args.lookback} days | Dry-run: {args.dry_run}")

        success, errors = 0, 0
        for account_id in account_ids:
            try:
                from app.services.google_ads_auto_executor import GoogleAdsAutoExecutor
                executor = GoogleAdsAutoExecutor(account_id)
                actions = executor.auto_add_negative_keywords(
                    lookback_days=args.lookback,
                    dry_run=args.dry_run,
                )
                print(f"  Account {account_id}: {len(actions)} action(s) created")
                success += 1
            except Exception as e:
                print(f"  Account {account_id}: ERROR — {e}")
                errors += 1

        print(f"\nDone: {success} succeeded, {errors} failed")
        return 0 if errors == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
