#!/usr/bin/env python3
"""
Check if admin panel database tables exist.

Tables checked:
- ai_prompts (for AI Prompts page)
- agent_configurations (for AI Agents page)
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'flaskapp'))

from app import create_app, db
from sqlalchemy import text, inspect

def check_tables():
    """Check if required tables exist."""
    app = create_app()

    with app.app_context():
        print("\n" + "="*80)
        print("ADMIN PANEL DATABASE TABLES CHECK")
        print("="*80 + "\n")

        inspector = inspect(db.engine)
        existing_tables = inspector.get_table_names()

        required_tables = {
            'ai_prompts': 'AI Prompts management page',
            'agent_configurations': 'AI Agents configuration page'
        }

        missing_tables = []

        for table, description in required_tables.items():
            if table in existing_tables:
                print(f"✓ {table:25} EXISTS - {description}")

                # Show row count
                with db.engine.connect() as conn:
                    result = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).first()
                    count = result[0] if result else 0
                    print(f"  └─ {count} row(s)")
            else:
                print(f"✗ {table:25} MISSING - {description}")
                missing_tables.append(table)

        print("\n" + "="*80)

        if missing_tables:
            print(f"❌ ISSUE FOUND: {len(missing_tables)} table(s) missing")
            print("\nThis explains why the navigation links don't work:")
            print("- Clicking 'AI Prompts' or 'AI Agents' causes silent redirect")
            print("- Routes catch the error and redirect to dashboard")
            print("\nTO FIX: Run these SQL migration files:")
            print()

            for table in missing_tables:
                if table == 'ai_prompts':
                    print("  mysql -u USERNAME -p DATABASE < migrations_sql/010_add_ai_prompts_table.sql")
                elif table == 'agent_configurations':
                    print("  mysql -u USERNAME -p DATABASE < flaskapp/migrations/create_agent_configurations_table.sql")

            print("\nOR copy and paste the SQL directly in your database management tool.")
            print("="*80 + "\n")
            return False
        else:
            print("✅ ALL TABLES EXIST")
            print("\nIf navigation links still don't work, check:")
            print("1. Browser console for JavaScript errors")
            print("2. Flask logs for permission/authentication errors")
            print("3. Try logging out and back in")
            print("="*80 + "\n")
            return True

if __name__ == "__main__":
    try:
        success = check_tables()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
