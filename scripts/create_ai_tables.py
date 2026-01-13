#!/usr/bin/env python3
"""
Create AI Action Tables Migration

Creates the ai_actions and ai_action_rules tables in the database.
Run this script once to add the new tables for Google Ads auto-execution.
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
from app.models_ai_actions import AIAction, AIActionRule


def main():
    """Create AI action tables."""
    print("=" * 70)
    print("  Creating AI Action Tables")
    print("=" * 70)
    print()

    app = create_app()
    with app.app_context():
        print("Creating tables...")

        try:
            # Create only the AI action tables (not all tables)
            # This avoids foreign key constraint errors from other pending migrations
            AIAction.__table__.create(db.engine, checkfirst=True)
            AIActionRule.__table__.create(db.engine, checkfirst=True)

            print("✓ Tables created successfully!")
            print()
            print("Tables created:")
            print("  - ai_actions")
            print("  - ai_action_rules")
            print()
            print("=" * 70)
            print("  Migration Complete!")
            print("=" * 70)

            return True

        except Exception as e:
            print(f"✗ Error creating tables: {e}")
            import traceback
            traceback.print_exc()
            return False


if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
