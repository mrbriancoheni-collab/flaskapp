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

            # Calculate metrics for quick querying
            campaigns = ads_data.get("campaigns", [])
            campaigns_count = len(campaigns)
            ad_groups_count = len(ads_data.get("ad_groups", []))
            keywords_count = len(ads_data.get("keywords", []))
            total_cost = sum(c.get("cost_30d", 0) or 0 for c in campaigns)
            total_conversions = sum(c.get("conversions", 0) or 0 for c in campaigns)

            # Save to historical snapshots database
            print(f"\nSaving to historical snapshots database...")
            with db.engine.begin() as conn:
                conn.execute(
                    text("""
                        INSERT INTO google_ads_snapshots
                        (account_id, fetched_at, snapshot_data, campaigns_count, ad_groups_count,
                         keywords_count, total_cost_30d, total_conversions_30d)
                        VALUES (:aid, :fetched_at, :snapshot, :campaigns, :ad_groups,
                                :keywords, :cost, :conversions)
                    """),
                    {
                        "aid": account_id,
                        "fetched_at": now,
                        "snapshot": cache_json,
                        "campaigns": campaigns_count,
                        "ad_groups": ad_groups_count,
                        "keywords": keywords_count,
                        "cost": total_cost,
                        "conversions": int(total_conversions)
                    }
                )

            print(f"✓ Successfully stored snapshot: {cache_size_kb:.1f}KB")
            print(f"✓ Timestamp: {now}")
            print(f"✓ Campaigns: {campaigns_count}")
            print(f"✓ Ad Groups: {ad_groups_count}")
            print(f"✓ Keywords: {keywords_count}")
            print(f"✓ Cost (30d): ${total_cost:.2f}")
            print(f"✓ Conversions (30d): {int(total_conversions)}")
            print(f"\nYou can now load the Google Ads page - it will use this snapshot!")
            return True

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
