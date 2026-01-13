#!/usr/bin/env python3
"""Quick script to check database schema."""

import sys
import os

# Load environment BEFORE importing anything from app
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from load_env import load_environment, ensure_app_can_initialize

load_environment()
ensure_app_can_initialize()

from app import create_app, db
from sqlalchemy import text, inspect

app = create_app()
with app.app_context():
    inspector = inspect(db.engine)

    # Get all tables
    tables = inspector.get_table_names()

    # Show Google/Ads related tables
    print("\n=== Google/Ads Related Tables ===")
    google_tables = [t for t in tables if 'google' in t.lower() or 'ads' in t.lower()]
    for t in sorted(google_tables):
        print(f"  ✓ {t}")

    # Check accounts table schema
    print("\n=== Accounts Table Schema ===")
    if 'accounts' in tables:
        columns = inspector.get_columns('accounts')
        for col in columns:
            if col['name'] == 'id':
                print(f"  id: {col['type']} (primary key)")
                break

    # Check if google_oauth_tokens exists
    print("\n=== OAuth Tokens Tables ===")
    oauth_tables = [t for t in tables if 'oauth' in t.lower() or 'token' in t.lower()]
    for t in sorted(oauth_tables):
        print(f"  ✓ {t}")
        if 'google' in t.lower():
            columns = inspector.get_columns(t)
            print(f"    Columns: {', '.join([c['name'] for c in columns])}")
