#!/usr/bin/env python3
"""
Run all pending database migrations for models_ads.py schema sync

Fixes:
1. ad_groups.google_ad_group_id - Missing column
2. keywords.max_cpc_cents - Missing column
"""

import pymysql
from pathlib import Path

def connect_db():
    """Connect to database"""
    return pymysql.connect(
        host='localhost',
        user='fieljtgr_team',
        password='Jcl3QewSX8mQUj35w8QE',
        database='fieljtgr_xyz',
        autocommit=False,
    )

def check_column_exists(cursor, table, column):
    """Check if a column exists in a table"""
    cursor.execute(f"SHOW COLUMNS FROM {table} LIKE '{column}'")
    return cursor.fetchone() is not None

def apply_migration(cursor, conn, table, column, sql):
    """Apply a migration if needed"""
    print(f"\n{'='*70}")
    print(f"Migration: {table}.{column}")
    print('='*70)

    if check_column_exists(cursor, table, column):
        print(f"✅ Column '{table}.{column}' already exists. Skipping.")
        return True

    print(f"❌ Column missing. Adding {table}.{column}...")

    try:
        cursor.execute(sql)
        conn.commit()

        if check_column_exists(cursor, table, column):
            print(f"✅ Successfully added {table}.{column}")
            return True
        else:
            print(f"❌ Failed to add {table}.{column}")
            return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

def main():
    print("\n" + "="*70)
    print("DATABASE SCHEMA MIGRATION - models_ads.py sync")
    print("="*70)

    migrations = [
        {
            'table': 'ad_groups',
            'column': 'google_ad_group_id',
            'sql': "ALTER TABLE ad_groups ADD COLUMN google_ad_group_id VARCHAR(64) DEFAULT NULL AFTER max_cpc_cents"
        },
        {
            'table': 'ad_groups',
            'column': 'idx_ad_groups_google_ad_group_id',
            'sql': "CREATE INDEX idx_ad_groups_google_ad_group_id ON ad_groups(google_ad_group_id)",
            'is_index': True
        },
        {
            'table': 'keywords',
            'column': 'max_cpc_cents',
            'sql': "ALTER TABLE keywords ADD COLUMN max_cpc_cents INT DEFAULT NULL AFTER status"
        },
        {
            'table': 'keywords',
            'column': 'google_keyword_id',
            'sql': "ALTER TABLE keywords ADD COLUMN google_keyword_id VARCHAR(64) DEFAULT NULL AFTER max_cpc_cents"
        },
        {
            'table': 'keywords',
            'column': 'idx_keywords_google_keyword_id',
            'sql': "CREATE INDEX idx_keywords_google_keyword_id ON keywords(google_keyword_id)",
            'is_index': True
        }
    ]

    try:
        conn = connect_db()
        cursor = conn.cursor()
        print("\n✅ Connected to database")

        success_count = 0
        skip_count = 0

        for migration in migrations:
            # Skip index checks for now (different check method needed)
            if migration.get('is_index'):
                try:
                    cursor.execute(migration['sql'])
                    conn.commit()
                    print(f"\n✅ Index created: {migration['column']}")
                    success_count += 1
                except pymysql.Error as e:
                    if 'Duplicate key name' in str(e):
                        print(f"\n✅ Index already exists: {migration['column']}")
                        skip_count += 1
                    else:
                        print(f"\n❌ Index creation failed: {e}")
                continue

            result = apply_migration(cursor, conn, migration['table'], migration['column'], migration['sql'])
            if result:
                success_count += 1

        # Show final table structures
        print("\n" + "="*70)
        print("VERIFICATION - Current table structures:")
        print("="*70)

        for table in ['ad_groups', 'keywords']:
            print(f"\n{table} table:")
            print("-" * 66)
            cursor.execute(f"DESCRIBE {table}")
            for row in cursor.fetchall():
                print(f"  {row[0]:<25} {row[1]:<20} {row[2]:<10}")

        cursor.close()
        conn.close()

        print("\n" + "="*70)
        print(f"✅ MIGRATION COMPLETED - {success_count} changes applied")
        print("="*70)
        return True

    except Exception as e:
        print(f"\n❌ Database connection failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    import sys
    sys.exit(0 if main() else 1)
