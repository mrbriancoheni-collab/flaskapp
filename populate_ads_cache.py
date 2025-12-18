#!/usr/bin/env python3
"""
Populate Google Ads cache via command line (bypasses web server memory limits).

Usage:
    python populate_ads_cache.py --account-id 3

This script runs OUTSIDE the web server, so it has different memory constraints.
It fetches Google Ads data and stores it in the database cache for the web app to use.
"""
import sys
import os
import json
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flaskapp.app import create_app, db
from sqlalchemy import text

def populate_cache(account_id: int):
    """Fetch Google Ads data and cache it in the database."""

    app = create_app()

    with app.app_context():
        print(f"Populating cache for account {account_id}...")

        # Import the fetch function
        from flaskapp.app.google import _get_ads_state

        try:
            print("Fetching data from Google Ads API...")
            ads_data = _get_ads_state(account_id)

            if not ads_data:
                print("ERROR: No data returned from Google Ads API")
                return False

            # Convert to JSON
            cache_json = json.dumps(ads_data)
            cache_size_kb = len(cache_json) / 1024
            now = datetime.utcnow()

            print(f"Data fetched successfully: {cache_size_kb:.1f}KB")
            print(f"Campaigns: {len(ads_data.get('campaigns', []))}")
            print(f"Ad Groups: {len(ads_data.get('ad_groups', []))}")
            print(f"Keywords: {len(ads_data.get('keywords', []))}")
            print(f"Ads: {len(ads_data.get('ads', []))}")

            # Save to database
            print(f"\nSaving to database cache...")
            with db.engine.begin() as conn:
                result = conn.execute(
                    text("""
                        UPDATE accounts
                        SET ads_data_cache = :cache,
                            ads_data_cached_at = :now
                        WHERE id = :aid
                    """),
                    {
                        "aid": account_id,
                        "cache": cache_json,
                        "now": now
                    }
                )
                rows_updated = result.rowcount

            if rows_updated > 0:
                print(f"✓ Successfully cached {cache_size_kb:.1f}KB in database")
                print(f"✓ Cache timestamp: {now}")
                print(f"✓ Cache will expire in 1 hour")
                print(f"\nYou can now load the Google Ads page without API calls!")
                return True
            else:
                print(f"ERROR: Account {account_id} not found in accounts table")
                return False

        except Exception as e:
            print(f"ERROR: {e}")
            import traceback
            traceback.print_exc()
            return False

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Populate Google Ads cache")
    parser.add_argument("--account-id", type=int, required=True, help="Account ID to cache")
    args = parser.parse_args()

    success = populate_cache(args.account_id)
    sys.exit(0 if success else 1)
