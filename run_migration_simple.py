#!/usr/bin/env python3
"""
Simple migration script to add google_ad_group_id column
Uses mysql-connector-python (no cryptography dependencies)
"""

import mysql.connector
from pathlib import Path

def main():
    print("=" * 70)
    print("Adding google_ad_group_id column to ad_groups table")
    print("=" * 70)

    try:
        # Connect
        print("\n1. Connecting to database...")
        conn = mysql.connector.connect(
            host='localhost',
            user='fieljtgr_team',
            password='Jcl3QewSX8mQUj35w8QE',
            database='fieljtgr_xyz'
        )
        cursor = conn.cursor()
        print("   ✅ Connected")

        # Check if column exists
        print("\n2. Checking current table structure...")
        cursor.execute("SHOW COLUMNS FROM ad_groups LIKE 'google_ad_group_id'")
        if cursor.fetchone():
            print("   ⚠️  Column already exists. Skipping.")
            return True

        print("   Column not found. Adding...")

        # Execute migration
        print("\n3. Adding column...")
        cursor.execute("ALTER TABLE ad_groups ADD COLUMN google_ad_group_id VARCHAR(64) DEFAULT NULL AFTER max_cpc_cents")
        print("   ✅ Column added")

        print("\n4. Creating index...")
        cursor.execute("CREATE INDEX idx_ad_groups_google_ad_group_id ON ad_groups(google_ad_group_id)")
        print("   ✅ Index created")

        conn.commit()

        # Verify
        print("\n5. Verifying...")
        cursor.execute("DESCRIBE ad_groups")
        print("\n   Current table structure:")
        print("   " + "-" * 66)
        for row in cursor.fetchall():
            print(f"   {row[0]:<25} {row[1]:<20} {row[2]:<10}")
        print("   " + "-" * 66)

        cursor.close()
        conn.close()

        print("\n✅ MIGRATION COMPLETED SUCCESSFULLY\n")
        return True

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    import sys
    sys.exit(0 if main() else 1)
