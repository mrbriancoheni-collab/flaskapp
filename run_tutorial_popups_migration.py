#!/usr/bin/env python3
"""
Migration Runner for Tutorial Popups - Add page_element column

Usage:
    python run_tutorial_popups_migration.py
"""

import sys
import os
from pathlib import Path

# Add app directory to path
sys.path.insert(0, str(Path(__file__).parent / "flaskapp"))

from app import create_app, db
from sqlalchemy import text, inspect

def check_column_exists():
    """Check if page_element column exists in tutorial_popups table."""
    app = create_app()
    with app.app_context():
        inspector = inspect(db.engine)

        # Check if table exists
        if 'tutorial_popups' not in inspector.get_table_names():
            print("❌ Table 'tutorial_popups' DOES NOT EXIST")
            return False

        # Get columns
        columns = [col['name'] for col in inspector.get_columns('tutorial_popups')]
        exists = 'page_element' in columns

        if exists:
            print("✅ Column 'page_element' EXISTS in tutorial_popups")
        else:
            print("❌ Column 'page_element' DOES NOT EXIST in tutorial_popups")
            print(f"   Existing columns: {', '.join(columns)}")

        return exists


def run_migration():
    """Add page_element column to tutorial_popups table."""
    print("Running migration to add page_element column to tutorial_popups...")

    app = create_app()
    with app.app_context():
        try:
            # Check if column already exists
            if check_column_exists():
                print("⚠️  Column already exists. Skipping migration.")
                return True

            print("Adding page_element column...")

            # For MySQL - ALTER TABLE to add column
            sql = """
            ALTER TABLE tutorial_popups
            ADD COLUMN page_element VARCHAR(500) DEFAULT NULL
            COMMENT 'CSS selector to highlight during tutorial (optional)'
            """

            db.session.execute(text(sql))
            db.session.commit()
            print("✅ Migration completed successfully!")

            # Verify
            check_column_exists()
            return True

        except Exception as e:
            db.session.rollback()
            print(f"❌ Migration failed: {e}")
            import traceback
            traceback.print_exc()
            return False


def main():
    success = run_migration()
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
