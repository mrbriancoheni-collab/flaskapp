#!/usr/bin/env python3
"""
Budget Tracker Migration Runner

Usage:
    python run_budget_tracker_migration.py up    # Apply migration
    python run_budget_tracker_migration.py down  # Rollback migration
    python run_budget_tracker_migration.py check # Check if tables exist
"""

import sys
import os
from pathlib import Path

# Add app directory to path
sys.path.insert(0, str(Path(__file__).parent / "flaskapp"))

from app import create_app, db
from sqlalchemy import text, inspect


def check_tables_exist():
    """Check if budget tracker tables exist."""
    app = create_app()
    with app.app_context():
        inspector = inspect(db.engine)
        table_names = inspector.get_table_names()

        budget_trackers_exists = 'budget_trackers' in table_names
        budget_alerts_exists = 'budget_alerts' in table_names

        print("\n=== Budget Tracker Tables Status ===")

        if budget_trackers_exists:
            print("✅ Table 'budget_trackers' EXISTS")
            result = db.session.execute(text("SELECT COUNT(*) FROM budget_trackers")).scalar()
            print(f"   Rows: {result}")
        else:
            print("❌ Table 'budget_trackers' DOES NOT EXIST")

        if budget_alerts_exists:
            print("✅ Table 'budget_alerts' EXISTS")
            result = db.session.execute(text("SELECT COUNT(*) FROM budget_alerts")).scalar()
            print(f"   Rows: {result}")
        else:
            print("❌ Table 'budget_alerts' DOES NOT EXIST")

        print()
        return budget_trackers_exists and budget_alerts_exists


def run_migration_up():
    """Apply the migration (create tables)."""
    print("Running migration UP (creating budget tracker tables)...")

    # Read SQL file
    sql_file = Path(__file__).parent / "migrations_sql" / "013_add_budget_tracker_tables.sql"
    if not sql_file.exists():
        print(f"❌ Migration file not found: {sql_file}")
        return False

    sql = sql_file.read_text()

    # Run migration
    app = create_app()
    with app.app_context():
        try:
            # Check if tables already exist
            inspector = inspect(db.engine)
            if 'budget_trackers' in inspector.get_table_names():
                print("⚠️  Tables already exist. Skipping migration.")
                check_tables_exist()
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
            check_tables_exist()
            return True

        except Exception as e:
            db.session.rollback()
            print(f"❌ Migration failed: {e}")
            import traceback
            traceback.print_exc()
            return False


def run_migration_down():
    """Rollback the migration (drop tables)."""
    print("Running migration DOWN (dropping budget tracker tables)...")

    # Confirm action
    response = input("⚠️  This will DELETE all budget tracker data. Continue? (yes/no): ")
    if response.lower() != 'yes':
        print("Rollback cancelled.")
        return False

    # Read SQL file
    sql_file = Path(__file__).parent / "migrations_sql" / "013_add_budget_tracker_tables_rollback.sql"
    if not sql_file.exists():
        print(f"❌ Rollback file not found: {sql_file}")
        return False

    sql = sql_file.read_text()

    # Run rollback
    app = create_app()
    with app.app_context():
        try:
            print("Executing SQL rollback...")

            # Split by semicolon and execute each statement
            statements = [s.strip() for s in sql.split(';') if s.strip()]

            for statement in statements:
                # Skip comments
                if statement.startswith('--'):
                    continue
                db.session.execute(text(statement))

            db.session.commit()
            print("✅ Rollback completed successfully!")

            # Verify
            check_tables_exist()
            return True

        except Exception as e:
            db.session.rollback()
            print(f"❌ Rollback failed: {e}")
            import traceback
            traceback.print_exc()
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
        success = check_tables_exist()
    else:
        print(f"❌ Unknown command: {command}")
        print(__doc__)
        sys.exit(1)

    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
