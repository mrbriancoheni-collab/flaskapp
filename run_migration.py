#!/usr/bin/env python3
"""
Migration Runner for Google Ads Grader

Usage:
    python run_migration.py up    # Apply migration
    python run_migration.py down  # Rollback migration
    python run_migration.py check # Check if table exists
"""

import sys
import os
from pathlib import Path

# Add app directory to path
sys.path.insert(0, str(Path(__file__).parent / "flaskapp"))

from app import create_app, db
from sqlalchemy import text, inspect

def check_table_exists():
    """Check if google_ads_grader_reports table exists."""
    app = create_app()
    with app.app_context():
        inspector = inspect(db.engine)
        exists = 'google_ads_grader_reports' in inspector.get_table_names()

        if exists:
            print("✅ Table 'google_ads_grader_reports' EXISTS")

            # Get row count
            result = db.session.execute(text("SELECT COUNT(*) FROM google_ads_grader_reports")).scalar()
            print(f"   Rows: {result}")
        else:
            print("❌ Table 'google_ads_grader_reports' DOES NOT EXIST")

        return exists


def run_migration_up():
    """Apply the migration (create table)."""
    print("Running migration UP (creating google_ads_grader_reports table)...")

    # Read SQL file
    sql_file = Path(__file__).parent / "migrations_sql" / "001_add_google_ads_grader_report.sql"
    if not sql_file.exists():
        print(f"❌ Migration file not found: {sql_file}")
        return False

    sql = sql_file.read_text()

    # Run migration
    app = create_app()
    with app.app_context():
        try:
            # Check if table already exists
            if check_table_exists():
                print("⚠️  Table already exists. Skipping migration.")
                return True

            print("Executing SQL migration...")

            # Split by semicolon and execute each statement
            statements = [s.strip() for s in sql.split(';') if s.strip()]

            for i, statement in enumerate(statements, 1):
                # Skip comments
                if statement.startswith('--'):
                    continue

                print(f"  Executing statement {i}/{len(statements)}...")
                db.session.execute(text(statement))

            db.session.commit()
            print("✅ Migration completed successfully!")

            # Verify
            check_table_exists()
            return True

        except Exception as e:
            db.session.rollback()
            print(f"❌ Migration failed: {e}")
            return False


def run_migration_down():
    """Rollback the migration (drop table)."""
    print("Running migration DOWN (dropping google_ads_grader_reports table)...")

    # Confirm action
    response = input("⚠️  This will DELETE all Google Ads Grader data. Continue? (yes/no): ")
    if response.lower() != 'yes':
        print("Rollback cancelled.")
        return False

    # Read SQL file
    sql_file = Path(__file__).parent / "migrations_sql" / "001_add_google_ads_grader_report_rollback.sql"
    if not sql_file.exists():
        print(f"❌ Rollback file not found: {sql_file}")
        return False

    sql = sql_file.read_text()

    # Run rollback
    app = create_app()
    with app.app_context():
        try:
            print("Executing SQL rollback...")
            db.session.execute(text(sql))
            db.session.commit()
            print("✅ Rollback completed successfully!")

            # Verify
            check_table_exists()
            return True

        except Exception as e:
            db.session.rollback()
            print(f"❌ Rollback failed: {e}")
            return False


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1].lower()

    if command == 'up':
        success = run_migration_up()
    elif command == 'down':
        success = run_migration_down()
    elif command == 'check':
        success = check_table_exists()
    else:
        print(f"❌ Unknown command: {command}")
        print(__doc__)
        sys.exit(1)

    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
