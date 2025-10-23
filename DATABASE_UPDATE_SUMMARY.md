# Database Update Summary

## YES - You Need to Update the Database! 🚨

We've added a NEW table that needs to be created in your MySQL database.

---

## What Changed

### 1. New Database Table: `performance_metrics`

**Purpose**: Store historical performance data from ALL channels for YoY analysis and trend tracking

**Location**: Defined in `app/models_ads.py` line 392

**Why you need it**:
- Track monthly performance over time
- Compare current year to last year (YoY)
- Measure improvement after using FieldSprout
- Enable better AI insights with historical context

---

## How to Update the Database

### ✅ RECOMMENDED: Run the SQL Migration File

I've created a ready-to-run SQL file for you:

**File**: `migration_performance_metrics.sql` (in project root)

**Steps**:

```bash
# Option 1: Using mysql command line
mysql -u YOUR_USERNAME -p YOUR_DATABASE_NAME < migration_performance_metrics.sql

# Option 2: Using MySQL Workbench or phpMyAdmin
# 1. Open the SQL file
# 2. Copy the CREATE TABLE statement
# 3. Run it in your database

# Option 3: Direct command
mysql -u YOUR_USERNAME -p YOUR_DATABASE_NAME -e "$(cat migration_performance_metrics.sql)"
```

**What the migration does**:
- Creates `performance_metrics` table
- Adds all necessary indexes
- Sets up constraints
- Includes verification query

---

### Alternative: Using Flask-Migrate

If you have Flask-Migrate installed and configured:

```bash
# Generate migration
flask db migrate -m "Add PerformanceMetrics table"

# Review the generated migration in migrations/versions/

# Apply migration
flask db upgrade
```

---

## Verify the Migration Worked

After running the migration, verify it succeeded:

```sql
-- Check table exists
SHOW TABLES LIKE 'performance_metrics';

-- Check table structure
DESCRIBE performance_metrics;

-- Should see these columns:
-- id, account_id, source_type, source_id, date, timeframe,
-- entity_type, entity_id, entity_name, metrics_json,
-- impressions, clicks, spend, conversions, created_at, updated_at

-- Check indexes
SHOW INDEX FROM performance_metrics;
```

---

## Additional Database Setup (Optional but Recommended)

### Initialize AI Prompts

The Facebook Ads AI insights need prompts in the database:

**Method 1: Via Admin Panel**
1. Navigate to `/admin/ai-prompts`
2. Click "Initialize Prompts" button
3. Done!

**Method 2: Via Flask Shell**
```bash
flask shell

>>> from app.services.ai_prompts_init import initialize_ai_prompts
>>> initialize_ai_prompts(force=False)
>>> exit()
```

This creates the `fbads_profile_main` and `fbads_campaigns_main` prompts.

---

## What Tables You Should Have Now

After all updates, your database should have these key tables:

### Existing Tables (from before):
- `accounts`
- `users`
- `ads_campaigns`
- `ad_groups`
- `ads`
- `keywords`
- `gads_stats_daily` (Google Ads daily stats)
- `optimizer_recommendations`
- `optimizer_actions`
- `ai_prompts`

### NEW Table (added today):
- ✨ **`performance_metrics`** ← Run migration to create this!

---

## What If the Migration Fails?

### Common Issues:

**1. Table already exists**
```
ERROR 1050: Table 'performance_metrics' already exists
```
**Solution**: Table is already created, you're good! Skip migration.

**2. Permission denied**
```
ERROR 1142: CREATE command denied
```
**Solution**: Your MySQL user needs CREATE TABLE permission. Contact your DB admin or use a user with sufficient privileges.

**3. Unknown column type**
```
ERROR 1064: You have an error in your SQL syntax
```
**Solution**: Check MySQL version. The migration is for MySQL 5.7+. If using older version, let me know and I'll adjust.

---

## Schema Summary

### performance_metrics table structure:

```sql
CREATE TABLE performance_metrics (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  account_id BIGINT NOT NULL,

  -- What platform/channel is this from?
  source_type VARCHAR(32) NOT NULL,  -- 'google_ads', 'fbads', etc.
  source_id VARCHAR(255),             -- Customer ID, Page ID, etc.

  -- When is this data from?
  date DATE NOT NULL,
  timeframe VARCHAR(16) DEFAULT 'daily',

  -- What specific entity? (optional)
  entity_type VARCHAR(32),            -- 'campaign', 'ad', etc.
  entity_id VARCHAR(255),
  entity_name VARCHAR(255),

  -- The actual metrics (flexible JSON)
  metrics_json TEXT NOT NULL,

  -- Quick access fields (extracted from JSON)
  impressions BIGINT,
  clicks BIGINT,
  spend DECIMAL(10,2),
  conversions DECIMAL(10,2),

  -- Timestamps
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

  -- Constraints & Indexes
  UNIQUE KEY (account_id, source_type, source_id, entity_type, entity_id, date, timeframe),
  INDEX (account_id, source_type, date),
  INDEX (source_type, entity_type, date)
);
```

---

## Files Changed/Added Today

### 1. **Database Models**
- ✏️ Modified: `app/models_ads.py` (added PerformanceMetrics model)

### 2. **Services** (Helper Functions)
- ✨ New: `app/services/metrics_service.py` (save/retrieve metrics)
- ✨ New: `app/services/yoy_analysis.py` (YoY comparison functions)
- ✨ New: `app/services/baseline_import.py` (import historical data)

### 3. **Documentation**
- ✨ New: `METRICS_INTEGRATION_GUIDE.md` (how to integrate saving)
- ✨ New: `DATABASE_UPDATE_SUMMARY.md` (this file)

### 4. **Migration**
- ✨ New: `migration_performance_metrics.sql` (ready-to-run SQL)

### 5. **Templates** (from earlier work)
- ✏️ Modified: `templates/google/gsc.html` (fixed OAuth)

---

## Summary of Commits

All changes have been committed and pushed to branch:
`claude/read-repository-011CULaDxSCifXFCL6VwEEvs`

**Commits made**:
1. `9f8dd3f` - Fix Google Search Console connection error
2. `e846f39` - Add unified performance metrics storage system

---

## Next Steps (Your Action Items)

### 🔴 CRITICAL - Do These First:

1. **Run the database migration**
   ```bash
   mysql -u USERNAME -p DATABASE < migration_performance_metrics.sql
   ```

2. **Verify the table was created**
   ```sql
   DESCRIBE performance_metrics;
   ```

3. **Initialize AI prompts** (for Facebook Ads AI insights)
   - Go to `/admin/ai-prompts` and click "Initialize Prompts"

### 🟡 IMPORTANT - Do Soon:

4. **Import historical baseline data** (for YoY comparison)
   - See `app/services/baseline_import.py` for methods
   - Recommended: Import last 12 months from each channel

5. **Integrate metrics saving into your API calls**
   - See `METRICS_INTEGRATION_GUIDE.md` for step-by-step
   - Start with Google Ads and Facebook Ads (highest priority)

### 🟢 OPTIONAL - Do Later:

6. **Build YoY comparison dashboard**
   - Use functions from `app/services/yoy_analysis.py`
   - Create a page to visualize YoY improvements

7. **Set up automated metrics capture**
   - Add cron job to save metrics daily
   - Ensures continuous historical tracking

---

## Questions?

If you run into any issues with the migration or have questions about the new system, let me know!

The new performance tracking system is ready to go once you run the database migration. 🚀
