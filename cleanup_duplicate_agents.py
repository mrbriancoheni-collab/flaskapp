#!/usr/bin/env python3
"""
Cleanup Script: Remove Duplicate Global Agent Configurations

This script identifies and removes duplicate global agent configurations
(where account_id IS NULL) from the agent_configurations table.

The issue: MySQL UNIQUE constraints allow multiple NULL values, so the
constraint UNIQUE(agent_id, account_id) doesn't prevent duplicates when
account_id IS NULL.

Solution: Keep only the most recent configuration for each agent_id.
"""

import sys
from pathlib import Path

# Add app directory to path
sys.path.insert(0, str(Path(__file__).parent / "flaskapp"))

from app import create_app, db
from sqlalchemy import text

def check_duplicates():
    """Check for duplicate global agent configurations."""
    app = create_app()
    with app.app_context():
        query = text("""
            SELECT agent_id, COUNT(*) as count
            FROM agent_configurations
            WHERE account_id IS NULL
            GROUP BY agent_id
            HAVING count > 1
        """)

        result = db.session.execute(query).fetchall()

        if result:
            print("🔍 Found duplicate global agent configurations:")
            print()
            for row in result:
                print(f"   {row[0]}: {row[1]} entries")
            print()
            return True
        else:
            print("✅ No duplicate global agent configurations found")
            return False


def show_all_global_configs():
    """Show all global agent configurations."""
    app = create_app()
    with app.app_context():
        query = text("""
            SELECT id, agent_id, enabled, auto_execute_threshold, created_at, updated_at
            FROM agent_configurations
            WHERE account_id IS NULL
            ORDER BY agent_id, id
        """)

        result = db.session.execute(query).fetchall()

        print(f"\n📋 All global agent configurations ({len(result)} total):")
        print()
        print(f"{'ID':<6} {'Agent ID':<25} {'Enabled':<8} {'Threshold':<10} {'Created':<20} {'Updated'}")
        print("-" * 100)

        for row in result:
            print(f"{row[0]:<6} {row[1]:<25} {str(row[2]):<8} {row[3]:<10} {str(row[4]):<20} {row[5]}")
        print()


def cleanup_duplicates(dry_run=True):
    """
    Remove duplicate global agent configurations.
    Keeps the most recent entry for each agent_id.

    Args:
        dry_run: If True, only shows what would be deleted. If False, actually deletes.
    """
    app = create_app()
    with app.app_context():
        # Find duplicates and identify which IDs to delete
        query = text("""
            SELECT ac1.id, ac1.agent_id, ac1.created_at
            FROM agent_configurations ac1
            INNER JOIN (
                SELECT agent_id, MAX(id) as max_id
                FROM agent_configurations
                WHERE account_id IS NULL
                GROUP BY agent_id
                HAVING COUNT(*) > 1
            ) ac2 ON ac1.agent_id = ac2.agent_id
            WHERE ac1.account_id IS NULL
            AND ac1.id != ac2.max_id
            ORDER BY ac1.agent_id, ac1.id
        """)

        to_delete = db.session.execute(query).fetchall()

        if not to_delete:
            print("✅ No duplicates to clean up")
            return

        print(f"\n{'🔍 DRY RUN - ' if dry_run else '🗑️  DELETING '} {len(to_delete)} duplicate configuration(s):")
        print()
        print(f"{'ID':<6} {'Agent ID':<25} {'Created'}")
        print("-" * 60)

        for row in to_delete:
            print(f"{row[0]:<6} {row[1]:<25} {row[2]}")

        if dry_run:
            print()
            print("This is a DRY RUN. No records were deleted.")
            print("Run with --execute to actually delete these records.")
        else:
            # Actually delete the duplicates
            ids_to_delete = [row[0] for row in to_delete]

            delete_query = text("""
                DELETE FROM agent_configurations
                WHERE id IN :ids
            """)

            db.session.execute(delete_query, {"ids": tuple(ids_to_delete)})
            db.session.commit()

            print()
            print(f"✅ Successfully deleted {len(to_delete)} duplicate configuration(s)")


def main():
    """Main function."""
    if len(sys.argv) > 1 and sys.argv[1] == "--execute":
        print("=" * 80)
        print("CLEANUP SCRIPT: Remove Duplicate Global Agent Configurations")
        print("=" * 80)
        print()

        # Show current state
        check_duplicates()
        show_all_global_configs()

        # Perform cleanup
        cleanup_duplicates(dry_run=False)

        # Show final state
        print()
        print("=" * 80)
        print("AFTER CLEANUP:")
        print("=" * 80)
        check_duplicates()
        show_all_global_configs()
    else:
        print("=" * 80)
        print("CLEANUP SCRIPT: Remove Duplicate Global Agent Configurations")
        print("=" * 80)
        print()

        # Show current state
        has_duplicates = check_duplicates()
        show_all_global_configs()

        if has_duplicates:
            # Show what would be deleted
            cleanup_duplicates(dry_run=True)
            print()
            print("=" * 80)
            print("To actually delete the duplicates, run:")
            print("  python cleanup_duplicate_agents.py --execute")
            print("=" * 80)


if __name__ == "__main__":
    main()
