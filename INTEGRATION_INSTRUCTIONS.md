# Integration Instructions - One-Click Campaign Automation

## ✅ What's Been Completed

All requested improvements have been **FULLY INTEGRATED** and committed:

1. **Lead Generation SQL Import Guide** ✅ - `LEAD_GENERATION_SETUP_GUIDE.md`
2. **Google Ads Navigation Dropdown Fix** ✅ - `flaskapp/templates/base_app.html`
3. **Google Ads Performance Stats** ✅ - Added to decision screen
4. **One-Click Campaign Automation System** ✅ - **FULLY INTEGRATED**

### Integration Completed:
- ✅ Backend routes added to `lead_campaigns_routes.py`
- ✅ Database models added to `models_leads.py`
- ✅ UI template created at `automation_one_click.html`
- ✅ Import statements updated

**Latest Commits**:
- Performance stats for Google Ads decision screen
- Full automation system integration

**Branch**: `claude/limit-scraping-campaigns-0JNOv`

---

## 📋 Remaining Manual Steps

### Step 1: Run Database Migration ⚠️ REQUIRED

A SQL migration file has been created for you. Run it to create the new tables and columns:

```bash
# Option A: Using MySQL command line
mysql -u YOUR_USERNAME -p YOUR_DATABASE < /home/user/flaskapp/MIGRATION_AUTOMATION.sql

# Option B: Using phpMyAdmin or other GUI
# - Open MIGRATION_AUTOMATION.sql
# - Copy and execute the SQL statements

# Option C: Using Flask migrations (if you have DB configured)
cd /home/user/flaskapp/flaskapp
source ../venv/bin/activate
flask db migrate -m "Add one-click automation tables and columns"
flask db upgrade
```

**File Location**: `/home/user/flaskapp/MIGRATION_AUTOMATION.sql`

The migration adds:
- `campaign_automation_config` table
- `automation_runs` table
- `is_core` column to `lead_campaigns`
- `last_automation_run` column to `lead_campaigns`

---

### Step 2: Mark Your Core 20 Campaigns ⚠️ REQUIRED

Identify and mark your core 20 campaigns in the database:

**Option A - Manual SQL Update** (if you know the campaign IDs):
```sql
UPDATE lead_campaigns
SET is_core = 1
WHERE id IN (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20);
```

**Option B - Mark Most Active Campaigns**:
```sql
UPDATE lead_campaigns
SET is_core = 1
WHERE id IN (
    SELECT id FROM lead_campaigns
    ORDER BY updated_at DESC
    LIMIT 20
);
```

**Option C - Via UI** (after integration):
You can later add a "Mark as Core" button to the campaigns list UI.

---

### Step 3: Add Navigation Link (Optional)

Add a link to the automation center in your admin navigation.

Find the Lead Campaigns section in your navigation (likely in `flaskapp/templates/base_app.html`) and add:

```html
<a href="{{ url_for('lead_campaigns_bp.automation_center') }}" class="nav-link">
    <i class="fas fa-robot"></i> Campaign Automation
</a>
```

Or add it to the Lead Campaigns dropdown menu if you have one.

---

### Step 4: Test the System

1. **Access the Dashboard**:
   ```
   http://localhost:5000/admin/lead-campaigns/automation-center
   ```

2. **Test Manual Run**:
   - Click "Run All Campaigns Now"
   - Watch the real-time progress
   - Check the activity log
   - Verify stats update correctly

3. **Test Scheduling**:
   - Configure a schedule (e.g., 9:00 AM, weekdays only)
   - Click "Save Schedule"
   - Click "Test Schedule Configuration"
   - Verify next run time is calculated correctly

4. **Check Database**:
   ```sql
   -- Check automation runs
   SELECT * FROM automation_runs ORDER BY started_at DESC LIMIT 5;

   -- Check automation config
   SELECT * FROM campaign_automation_config;

   -- Check core campaigns
   SELECT id, name, is_core FROM lead_campaigns WHERE is_core = 1;
   ```

---

## 🎯 How to Use

### Lead Import (SQL Templates)

1. Open `LEAD_GENERATION_SETUP_GUIDE.md`
2. Choose the appropriate import scenario:
   - **Option A**: Domain-only imports
   - **Option B**: Companies with emails
   - **Option C**: Full contact details
   - **Option D**: Bulk CSV import
3. Copy the SQL template
4. Replace the example data with your actual data
5. Run in your MySQL/MariaDB client

### One-Click Automation

**Manual Run**:
1. Go to `/admin/lead-campaigns/automation-center`
2. Click "Run All Campaigns Now"
3. Watch real-time progress
4. Check results in the activity log

**Scheduled Run** (Future Enhancement):
1. Configure schedule in the UI
2. Set run time (e.g., 09:00)
3. Select days to run (Mon-Fri)
4. Set daily email limit
5. Enable scheduling
6. System will run automatically at scheduled times

**Note**: For production scheduled runs, you'll need to implement a cron job or background scheduler (Celery, APScheduler) that checks `next_run_at` and triggers automation jobs.

---

## 📊 What the Automation Does

For each of the 20 core campaigns, it:

1. **Scrapes** (if campaign status = 'draft'):
   - Calls `SerpAPIScraperService.scrape_campaign()`
   - Creates new leads from search results
   - Updates campaign status to 'ready'

2. **Enriches** (if leads with enrichment_status = 'pending'):
   - Processes up to 50 leads per campaign
   - Calls `LeadEnrichmentService.enrich_lead()` for each
   - Finds decision maker emails and contact info

3. **Sends Emails** (if leads ready to email):
   - Processes leads with enrichment_status='completed' and email_status='pending'
   - Respects campaign daily_email_limit (default 50)
   - Only sends to leads with valid decision_maker_email
   - Calls `BrevoOutreachService.send_initial_email()`

---

## 🔧 Troubleshooting

### "Job not found" error
- Job tracking is in-memory and cleared on server restart
- For production, implement Redis-based job storage

### Automation runs but no progress
- Check background thread is running
- Check Flask app has `create_app()` function
- Verify services are imported correctly

### No campaigns shown
- Ensure you've marked campaigns as `is_core = 1`
- Check query: `SELECT * FROM lead_campaigns WHERE is_core = 1;`

### Schedule not calculating next run
- Verify `run_days` is a valid JSON array: `[0,1,2,3,4]`
- Check `run_time` format is `HH:MM` (e.g., '09:00')
- Ensure `skip_weekends` logic matches your needs

---

## 🚀 Production Recommendations

1. **Job Storage**: Replace in-memory `automation_jobs` dict with Redis
2. **Background Workers**: Use Celery for scheduled tasks
3. **Email Rate Limiting**: Implement per-campaign and global throttling
4. **Error Notifications**: Send admin alerts on automation failures
5. **Logging**: Add comprehensive logging for debugging
6. **UI Enhancements**: Add campaign priority ordering, custom schedules per campaign

---

## 📝 Summary

All three features are now ready for integration:

✅ **Google Ads Dropdown** - Already live (no further action needed)
✅ **SQL Import Templates** - Ready to use (see LEAD_GENERATION_SETUP_GUIDE.md)
✅ **One-Click Automation** - Requires Steps 1-7 above

Once you complete the integration steps, you'll have a fully functional automation dashboard that can process your entire lead pipeline with a single button click.
