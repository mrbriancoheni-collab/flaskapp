#!/usr/bin/env python3
"""
Create GoogleAdsAuth Table Migration

Creates the google_ads_auth table in the database.
Run this script once to add the table for Google Ads authentication.
"""

import sys
import os

# Load environment BEFORE importing anything from app
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from load_env import load_environment, ensure_app_can_initialize

# Load environment and ensure app can initialize
load_environment()
ensure_app_can_initialize()

# NOW we can safely import the app
from app import create_app, db
from app.models import GoogleAdsAuth


def main():
    """Create GoogleAdsAuth table."""
    print("=" * 70)
    print("  Creating GoogleAdsAuth Table")
    print("=" * 70)
    print()

    app = create_app()
    with app.app_context():
        print("Creating google_ads_auth table...")

        try:
            # Create only the GoogleAdsAuth table
            GoogleAdsAuth.__table__.create(db.engine, checkfirst=True)

            print("✓ Table created successfully!")
            print()
            print("Table created:")
            print("  - google_ads_auth")
            print()
            print("=" * 70)
            print("  Migration Complete!")
            print("=" * 70)

            return True

        except Exception as e:
            print(f"✗ Error creating table: {e}")
            import traceback
            traceback.print_exc()
            return False


if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
