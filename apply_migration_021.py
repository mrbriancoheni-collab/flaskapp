#!/usr/bin/env python3
"""
Apply Migration 021: Rename audit_logs.metadata to context_data

Usage:
    python apply_migration_021.py
"""

import sys
from pathlib import Path

# Add app directory to path
sys.path.insert(0, str(Path(__file__).parent / "flaskapp"))

from app import create_app, db
from sqlalchemy import text, inspect

def check_column_exists(table_name, column_name):
    """Check if a column exists in a table."""
    app = create_app()
    with app.app_context():
        inspector = inspect(db.engine)

        # Check if table exists
        if table_name not in inspector.get_table_names():
            print(f"⚠️  Table '{table_name}' does not exist yet. Skipping migration.")
            return None

        # Get columns
        columns = inspector.get_columns(table_name)
        column_names = [col['name'] for col in columns]

        return column_name in column_names

def run_migration():
    """Apply the migration."""
    print("Checking current state...")

    # Check if old column exists
    has_metadata = check_column_exists('audit_logs', 'metadata')
    has_context_data = check_column_exists('audit_logs', 'context_data')

    if has_metadata is None:
        print("✅ Migration not needed - table doesn't exist yet")
        return True

    if not has_metadata and has_context_data:
        print("✅ Migration already applied - context_data column exists")
        return True

    if not has_metadata and not has_context_data:
        print("⚠️  Neither column exists - table schema is different than expected")
        return True

    # Apply migration
    print("Running migration: Renaming metadata to context_data...")

    # Read SQL file
    sql_file = Path(__file__).parent / "migrations_sql" / "021_rename_audit_log_metadata_to_context_data.sql"
    if not sql_file.exists():
        print(f"❌ Migration file not found: {sql_file}")
        return False

    sql = sql_file.read_text()

    # Run migration
    app = create_app()
    with app.app_context():
        try:
            print("Executing SQL migration...")

            # Execute the ALTER TABLE statement
            db.session.execute(text(sql))
            db.session.commit()

            print("✅ Migration completed successfully!")

            # Verify
            has_context_data = check_column_exists('audit_logs', 'context_data')
            if has_context_data:
                print("✅ Verified: context_data column exists")
            else:
                print("⚠️  Warning: context_data column not found after migration")

            return True

        except Exception as e:
            db.session.rollback()
            print(f"❌ Migration failed: {e}")
            return False

if __name__ == '__main__':
    success = run_migration()
    sys.exit(0 if success else 1)
