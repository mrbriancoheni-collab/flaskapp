# Admin Audit Log Migration

## Overview
This migration adds the `admin_audit_logs` table to capture and track all admin user actions in the system. Previously, admin actions were not being recorded because the `AdminAuditLog` model was missing from the database.

## Problem Fixed
The admin routes (`/admin/*`) were attempting to log all actions using an `AdminAuditLog` model that didn't exist in the database. This caused all admin action logging to silently fail, resulting in no audit trail of admin activities.

## Changes Made

### 1. Model Addition
Added `AdminAuditLog` model to `/flaskapp/app/models.py`:
- Tracks admin user actions with full context
- Records target users and accounts
- Captures IP address and user agent for security
- Includes detailed action notes

### 2. Database Migration
Created migration files in `/migrations_sql/`:
- `012_add_admin_audit_logs_table.sql` - Creates the table
- `012_add_admin_audit_logs_table_rollback.sql` - Rollback script

## Applying the Migration

### Method 1: Using the provided Python script (Recommended)
```bash
cd /home/user/flaskapp
python3 apply_migration_012.py
```

### Method 2: Using MySQL CLI directly
```bash
# Make sure you're in the flaskapp directory
cd /home/user/flaskapp

# Run the migration SQL file
mysql -u [username] -p [database_name] < migrations_sql/012_add_admin_audit_logs_table.sql
```

### Method 3: Using Flask shell
```python
from app import create_app, db
app = create_app()

with app.app_context():
    with open('migrations_sql/012_add_admin_audit_logs_table.sql', 'r') as f:
        sql = f.read()

    # Execute the migration
    for statement in sql.split(';'):
        if statement.strip() and not statement.strip().startswith('--'):
            db.session.execute(db.text(statement))

    db.session.commit()
    print("Migration applied!")
```

## Verification

After applying the migration, verify the table exists:

```sql
SHOW TABLES LIKE 'admin_audit_logs';
DESCRIBE admin_audit_logs;
```

You should see a table with the following columns:
- `id` - Primary key
- `admin_user_id` - Foreign key to users table
- `action` - Action type (e.g., 'impersonate_start', 'crm_create')
- `target_user_id` - User affected by the action
- `target_account_id` - Account affected by the action
- `note` - Additional context
- `ip` - IP address
- `user_agent` - Browser/client identifier
- `created_at` - Timestamp

## Admin Actions Tracked

Once the migration is applied, the following admin actions will be automatically logged:

1. **User Management**
   - `impersonate_start` - When admin impersonates a user
   - `impersonate_stop` - When admin stops impersonation

2. **CRM Operations**
   - `crm_create` - Creating CRM contacts
   - `crm_update` - Updating CRM contacts
   - `serp_scrape` - Running SERP scraper
   - `serp_manual_import` - Manual SERP import
   - `serp_add_selected` - Adding selected SERP results
   - `domain_crawl` - Running domain crawler

3. **Email Campaigns**
   - `email_sent` - Sending emails
   - `bulk_email_sent` - Bulk email campaigns

4. **Configuration**
   - `roi_settings_updated` - ROI settings changes
   - `pricing_tier_created` - New pricing tier
   - `pricing_tier_updated` - Pricing tier updates

5. **Customer Impact**
   - `customer_baseline_set` - Setting customer baselines
   - `customer_impact_updated` - Updating impact metrics
   - `customer_impact_bulk_update` - Bulk impact updates

## Rollback

If you need to rollback this migration:

```bash
mysql -u [username] -p [database_name] < migrations_sql/012_add_admin_audit_logs_table_rollback.sql
```

Or using Python:
```bash
cd /home/user/flaskapp
# Create a rollback script similar to apply_migration_012.py but using the rollback SQL
```

## Testing

After applying the migration, test that admin actions are being logged:

1. Log in as an admin user
2. Perform any admin action (e.g., view CRM, send an email)
3. Check the audit logs table:
   ```sql
   SELECT * FROM admin_audit_logs ORDER BY created_at DESC LIMIT 10;
   ```

4. Or view through the admin UI:
   - Navigate to `/admin/logs`
   - You should see recent admin actions listed

## Important Notes

- **Foreign Keys**: The table uses ON DELETE SET NULL for foreign keys, so deleting users or accounts won't break audit records
- **Performance**: All columns used for filtering are indexed
- **Data Retention**: Consider implementing a data retention policy for old audit logs
- **Privacy**: Audit logs contain sensitive information - restrict access appropriately

## Related Files

- Model: `/flaskapp/app/models.py` (AdminAuditLog class)
- Routes: `/flaskapp/app/admin/routes.py` (_audit function)
- Migration: `/migrations_sql/012_add_admin_audit_logs_table.sql`
- Rollback: `/migrations_sql/012_add_admin_audit_logs_table_rollback.sql`
- Application Script: `/apply_migration_012.py`
