#!/usr/bin/env python3
"""
Check if Google Ads cache columns exist in the database.

Usage:
    python check_cache_setup.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flaskapp.app import create_app, db
from sqlalchemy import text, inspect

def check_cache_setup():
    """Check if cache columns exist and are properly configured."""

    app = create_app()

    with app.app_context():
        print("Checking Google Ads cache setup...\n")

        try:
            # Check if accounts table exists
            inspector = inspect(db.engine)
            tables = inspector.get_table_names()

            if 'accounts' not in tables:
                print("❌ ERROR: 'accounts' table does not exist!")
                return False

            print("✓ Accounts table exists")

            # Check columns
            columns = {col['name']: col for col in inspector.get_columns('accounts')}

            required_columns = {
                'ads_data_cache': 'LONGTEXT or TEXT',
                'ads_data_cached_at': 'DATETIME'
            }

            all_exist = True
            for col_name, col_type in required_columns.items():
                if col_name in columns:
                    actual_type = str(columns[col_name]['type'])
                    print(f"✓ Column '{col_name}' exists (type: {actual_type})")
                else:
                    print(f"❌ Column '{col_name}' MISSING (expected: {col_type})")
                    all_exist = False

            if not all_exist:
                print("\n⚠️  Missing columns! Run this SQL:")
                print("""
ALTER TABLE accounts
ADD COLUMN ads_data_cache LONGTEXT NULL COMMENT 'Cached Google Ads data as JSON',
ADD COLUMN ads_data_cached_at DATETIME NULL COMMENT 'When ads_data was last cached';

CREATE INDEX idx_accounts_ads_cache_time ON accounts(id, ads_data_cached_at);
""")
                return False

            # Check if any accounts exist
            with db.engine.connect() as conn:
                result = conn.execute(text("SELECT COUNT(*) FROM accounts")).first()
                account_count = result[0]

            print(f"\n✓ Found {account_count} account(s) in database")

            # Check if any have cached data
            with db.engine.connect() as conn:
                result = conn.execute(
                    text("SELECT COUNT(*) FROM accounts WHERE ads_data_cache IS NOT NULL")
                ).first()
                cached_count = result[0]

            if cached_count > 0:
                print(f"✓ {cached_count} account(s) have cached data")

                # Show cache ages
                with db.engine.connect() as conn:
                    results = conn.execute(
                        text("""
                            SELECT id, ads_data_cached_at,
                                   LENGTH(ads_data_cache) as cache_size
                            FROM accounts
                            WHERE ads_data_cache IS NOT NULL
                        """)
                    ).fetchall()

                    for row in results:
                        cache_size_kb = row[2] / 1024 if row[2] else 0
                        print(f"  - Account {row[0]}: cached at {row[1]}, size: {cache_size_kb:.1f}KB")
            else:
                print(f"⚠️  No accounts have cached data yet")
                print(f"\nTo populate cache for account ID 3:")
                print(f"  python populate_ads_cache.py --account-id 3")

            print("\n✅ Cache setup is correct!")
            return True

        except Exception as e:
            print(f"\n❌ ERROR: {e}")
            import traceback
            traceback.print_exc()
            return False

if __name__ == "__main__":
    success = check_cache_setup()
    sys.exit(0 if success else 1)
