# Database Migrations

This directory contains SQL migrations for the FieldSprout application.

## Running Migrations

### Method 1: Using Python Script (Recommended)

The Python script uses Flask's database connection and is the safest method:

```bash
# Check if table exists
python run_migration.py check

# Apply migration (create table)
python run_migration.py up

# Rollback migration (drop table)
python run_migration.py down
```

### Method 2: Direct MySQL Execution

If you prefer to run SQL directly:

```bash
# Apply migration
mysql -u username -p database_name < migrations_sql/001_add_google_ads_grader_report.sql

# Rollback migration
mysql -u username -p database_name < migrations_sql/001_add_google_ads_grader_report_rollback.sql
```

## Migration Files

### 001_add_google_ads_grader_report.sql

Creates the `google_ads_grader_reports` table for storing Google Ads Quality Checker analysis results.

**Table Structure:**
- Primary key: `id`
- Foreign keys: `account_id`, `user_id`
- Score fields: Overall score + 10 section scores
- Metrics: Quality Score avg, CTR, wasted spend, etc.
- JSON fields: `detailed_metrics`, `best_practices`, `recommendations`
- Tracking: `view_count`, `pdf_download_count`

**Indexes:**
- `account_id` - Fast lookup by account
- `user_id` - Fast lookup by user
- `google_ads_customer_id` - Fast lookup by Google Ads customer
- `created_at` - Fast date range queries

### 001_add_google_ads_grader_report_rollback.sql

Drops the `google_ads_grader_reports` table (destructive - deletes all data).

## Troubleshooting

### Foreign Key Errors

If you get foreign key constraint errors, it means the `accounts` or `users` tables don't exist. Options:

1. Create those tables first
2. Remove the foreign key constraints from the SQL file
3. Modify the SQL to use `ON DELETE SET NULL` (already configured)

### JSON Column Errors

If using MySQL < 5.7.8, JSON columns are not supported. Options:

1. Upgrade MySQL to 5.7.8+
2. Replace `JSON` with `TEXT` in the migration file

### Character Set Errors

The migration uses `utf8mb4` for full Unicode support (including emojis). If you get errors:

1. Ensure MySQL is configured for `utf8mb4`
2. Change to `utf8` in the migration file if needed

## Verifying Migration

After running the migration, verify it worked:

```bash
# Using Python script
python run_migration.py check

# Using MySQL directly
mysql -u username -p -e "DESCRIBE google_ads_grader_reports" database_name
mysql -u username -p -e "SELECT COUNT(*) FROM google_ads_grader_reports" database_name
```

## Next Steps After Migration

1. Restart Flask application
2. Visit `/ads-grader` to test the feature
3. Generate a demo report to verify database writes
4. Check logs for any errors

## Migration History

| # | Name | Date | Description |
|---|------|------|-------------|
| 001 | add_google_ads_grader_report | 2025-10-25 | Create google_ads_grader_reports table |
