#!/usr/bin/env python3
"""
Google Ads Auto-Execution Script

Automatically executes safe Google Ads optimizations across all active accounts.
Should be run hourly via cron.

Actions performed:
- Auto-add negative keywords for non-purchase intent searches
- Future: Auto-pause low-performing keywords
- Future: Auto-adjust bids based on performance

All actions are logged to the AIAction model with undo capability.
"""

import sys
import os
import logging
from datetime import datetime

# Add parent directory to path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PROJECT_ROOT)

# Change to project root directory
os.chdir(PROJECT_ROOT)

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    env_path = os.path.join(PROJECT_ROOT, '.env')
    if os.path.exists(env_path):
        load_dotenv(env_path)
        print(f"Loaded environment from {env_path}")
    else:
        print(f"Warning: .env file not found at {env_path}")
except ImportError:
    print("Warning: python-dotenv not installed, environment variables must be set manually")

from app import create_app, db
from app.models import Account
from app.services.google_ads_auto_executor import GoogleAdsAutoExecutor

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('/tmp/google_ads_auto_execute.log')
    ]
)
logger = logging.getLogger(__name__)


def print_header(text):
    """Print a formatted header."""
    print("\n" + "=" * 70)
    print(f"  {text}")
    print("=" * 70 + "\n")


def get_active_google_ads_accounts():
    """Get all accounts with active Google Ads connections."""
    accounts = Account.query.filter(
        Account.google_refresh_token.isnot(None),
        Account.google_customer_id.isnot(None)
    ).all()

    logger.info(f"Found {len(accounts)} accounts with Google Ads connections")
    return accounts


def auto_execute_for_account(account):
    """
    Run auto-execution for a single account.

    Returns:
        dict: Execution results
    """
    logger.info(f"Processing account {account.id}: {account.business_name}")

    try:
        executor = GoogleAdsAutoExecutor(account.id)

        # Auto-add negative keywords
        logger.info("Running auto-add negative keywords...")
        negative_keyword_actions = executor.auto_add_negative_keywords(
            lookback_days=30,
            dry_run=False
        )

        logger.info(f"  ✓ Created/executed {len(negative_keyword_actions)} negative keyword actions")

        # TODO: Add more auto-execution methods here
        # - Auto-pause low-performing keywords
        # - Auto-adjust bids
        # - Auto-reallocate budget

        return {
            'account_id': account.id,
            'account_name': account.business_name,
            'success': True,
            'negative_keywords_added': len(negative_keyword_actions),
            'total_actions': len(negative_keyword_actions),
            'error': None
        }

    except Exception as e:
        logger.error(f"Error processing account {account.id}: {e}", exc_info=True)
        return {
            'account_id': account.id,
            'account_name': account.business_name,
            'success': False,
            'negative_keywords_added': 0,
            'total_actions': 0,
            'error': str(e)
        }


def print_summary(results):
    """Print execution summary."""
    print_header("Execution Summary")

    total_accounts = len(results)
    successful = sum(1 for r in results if r['success'])
    failed = total_accounts - successful
    total_actions = sum(r['total_actions'] for r in results)
    total_negative_keywords = sum(r['negative_keywords_added'] for r in results)

    print(f"Accounts Processed:     {total_accounts}")
    print(f"  ├─ Successful:        {successful}")
    print(f"  └─ Failed:            {failed}")
    print(f"\nTotal Actions:          {total_actions}")
    print(f"  └─ Negative Keywords: {total_negative_keywords}")

    # Show per-account breakdown
    if results:
        print("\nPer-Account Breakdown:")
        for result in results:
            status_icon = "✓" if result['success'] else "✗"
            print(f"  {status_icon} {result['account_name']} (ID: {result['account_id']})")
            if result['success']:
                print(f"      ├─ Negative Keywords: {result['negative_keywords_added']}")
                print(f"      └─ Total Actions: {result['total_actions']}")
            else:
                print(f"      └─ Error: {result['error']}")

    # Show failures in detail
    failures = [r for r in results if not r['success']]
    if failures:
        print("\nFailed Accounts:")
        for result in failures:
            print(f"  ✗ {result['account_name']} (ID: {result['account_id']})")
            print(f"    Error: {result['error']}")


def main():
    """Main execution function."""
    print_header(f"Google Ads Auto-Execution - {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")

    app = create_app()
    with app.app_context():
        logger.info("Starting Google Ads auto-execution")

        # Get all active accounts
        accounts = get_active_google_ads_accounts()

        if not accounts:
            logger.warning("No active Google Ads accounts found")
            print("No active Google Ads accounts found. Exiting.")
            return

        # Process each account
        results = []
        for account in accounts:
            result = auto_execute_for_account(account)
            results.append(result)

        # Print summary
        print_summary(results)

        # Log completion
        logger.info(
            f"Auto-execution complete: {len(results)} accounts processed, "
            f"{sum(r['total_actions'] for r in results)} total actions"
        )

        print_header("Execution Complete")
        print(f"View action log: https://fieldsprout.io/account/google/ads")
        print(f"All actions can be undone from the UI.")


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        logger.critical(f"Fatal error during auto-execution: {e}", exc_info=True)
        sys.exit(1)
