#!/usr/bin/env python3
"""
Create AI Action Tables Migration

Creates the ai_actions and ai_action_rules tables in the database.
Run this script once to add the new tables for Google Ads auto-execution.
"""

import sys
import os

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
            # Create all tables (only new ones will be created)
            db.create_all()

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
            return False


if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
