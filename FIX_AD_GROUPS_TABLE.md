# Fix: Add missing google_ad_group_id column to ad_groups table

## Problem
The application is experiencing a SQL error:
```
(pymysql.err.OperationalError) (1054, "Unknown column 'ad_groups.google_ad_group_id' in 'SELECT'")
```

This error occurs because the `ad_groups` table in the database is missing the `google_ad_group_id` column that is defined in the SQLAlchemy model (`app/models_ads.py`).

## Solution

### Option 1: Run SQL Migration Directly (Quickest)

Connect to your MySQL database and run:

```sql
ALTER TABLE ad_groups ADD COLUMN google_ad_group_id VARCHAR(64) DEFAULT NULL AFTER max_cpc_cents;
CREATE INDEX idx_ad_groups_google_ad_group_id ON ad_groups(google_ad_group_id);
```

### Option 2: Use Migration Script (Recommended for Development)

If you have Flask and dependencies installed:

```bash
python3 run_ad_groups_migration.py check  # Check if column exists
python3 run_ad_groups_migration.py up     # Apply migration
```

### Option 3: Manual SQL File

The migration SQL is also available in:
`flaskapp/migrations/add_google_ad_group_id_to_ad_groups.sql`

You can apply it manually or through your deployment pipeline.

## Verification

After applying the migration, verify with:

```sql
DESCRIBE ad_groups;
```

You should see the `google_ad_group_id` column in the output.

## Impact

This fix resolves SQL errors when querying ad_groups table and allows proper syncing of Google Ads ad group IDs.
