# Fix: Database Schema Sync Issues (models_ads.py)

## Problems
The application is experiencing multiple SQL errors due to missing columns:

### Error 1: ad_groups.google_ad_group_id
```
(pymysql.err.OperationalError) (1054, "Unknown column 'ad_groups.google_ad_group_id' in 'SELECT'")
```

### Error 2: keywords.max_cpc_cents
```
(pymysql.err.OperationalError) (1054, "Unknown column 'keywords.max_cpc_cents' in 'SELECT'")
```

**Root Cause**: The database tables are out of sync with the SQLAlchemy models defined in `app/models_ads.py`. The models define columns that don't exist in the actual database tables.

## Solution

### Option 1: Run All Migrations Script (Recommended)

This applies all pending migrations automatically:

```bash
python3 run_all_pending_migrations.py
```

This script will:
- Check which columns are missing
- Apply only the necessary migrations
- Verify the results
- Show the final table structure

### Option 2: Manual SQL (Quick Fix)

Connect to your MySQL database and run these commands:

```sql
-- Fix ad_groups table
ALTER TABLE ad_groups ADD COLUMN google_ad_group_id VARCHAR(64) DEFAULT NULL AFTER max_cpc_cents;
CREATE INDEX idx_ad_groups_google_ad_group_id ON ad_groups(google_ad_group_id);

-- Fix keywords table
ALTER TABLE keywords ADD COLUMN max_cpc_cents INT DEFAULT NULL AFTER status;
```

### Option 3: Individual Migration Files

The migrations are also available as separate SQL files in `flaskapp/migrations/`:
- `add_google_ad_group_id_to_ad_groups.sql`
- `add_max_cpc_cents_to_keywords.sql`

## Verification

After applying the migrations, verify with:

```sql
-- Check ad_groups table
DESCRIBE ad_groups;

-- Check keywords table
DESCRIBE keywords;
```

You should see:
- `google_ad_group_id` (VARCHAR(64)) in ad_groups table
- `max_cpc_cents` (INT) in keywords table

## Impact

These fixes resolve critical SQL errors that prevent the application from:
- Querying ad groups and keywords
- Syncing Google Ads data
- Displaying campaign/ad group analytics

**Priority**: HIGH - Application functionality is broken without these migrations.
