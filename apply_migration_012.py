#!/usr/bin/env python3
"""
Apply migration 012: Create admin_audit_logs table

This script applies the admin_audit_logs table migration to enable
tracking of admin user actions.
"""
import sys
import os

# Add the flaskapp directory to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'flaskapp'))

from app import create_app, db

def apply_migration():
    """Apply the admin_audit_logs table migration"""
    app = create_app()

    with app.app_context():
        # Read the migration SQL
        migration_file = os.path.join(
            os.path.dirname(__file__),
            'migrations_sql',
            '012_add_admin_audit_logs_table.sql'
        )

        with open(migration_file, 'r') as f:
            sql = f.read()

        # Execute the migration
        print(f"Applying migration: 012_add_admin_audit_logs_table.sql")

        # Split by semicolons and execute each statement
        statements = [s.strip() for s in sql.split(';') if s.strip() and not s.strip().startswith('--')]

        for statement in statements:
            if statement:
                print(f"Executing: {statement[:80]}...")
                db.session.execute(db.text(statement))

        db.session.commit()
        print("✓ Migration applied successfully!")

        # Verify the table was created
        result = db.session.execute(db.text("SHOW TABLES LIKE 'admin_audit_logs'"))
        if result.fetchone():
            print("✓ Table 'admin_audit_logs' verified in database")
        else:
            print("✗ Warning: Table not found after migration")
            return False

    return True

if __name__ == '__main__':
    try:
        success = apply_migration()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"✗ Error applying migration: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
