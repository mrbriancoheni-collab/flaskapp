# Lead Generation System - Setup & Usage Guide

## 1. Bulk Import Companies to Lead Database

### Database Structure

Your lead generation system uses these main tables:
- **`lead_campaigns`** - Campaign configuration (industry, location, email settings)
- **`leads`** - Company records with scraping source and enrichment data
- **`lead_contacts`** - Individual decision makers at companies
- **`email_sequences`** - Email templates for outreach
- **`lead_contact_emails`** - Sent email tracking

### SQL Query Templates for Bulk Import

#### Option A: Import with Domain Only
```sql
-- Insert companies with just domains (most common scenario)
INSERT INTO leads (
    campaign_id,
    company_name,
    website,
    source_type,
    enrichment_status,
    email_status,
    created_at,
    updated_at
)
VALUES
    (1, 'ABC Plumbing Inc', 'https://abcplumbing.com', 'manual', 'pending', 'pending', NOW(), NOW()),
    (1, 'XYZ HVAC Services', 'https://xyzhvac.com', 'manual', 'pending', 'pending', NOW(), NOW()),
    (1, 'Best Electric Co', 'https://bestelectric.com', 'manual', 'pending', 'pending', NOW(), NOW());

-- Notes:
-- campaign_id: ID of the campaign (find with: SELECT id, name FROM lead_campaigns;)
-- source_type: Use 'manual' for manually added leads
-- enrichment_status: Always 'pending' for new imports (system will enrich them)
-- email_status: Always 'pending' for new imports
```

#### Option B: Import with Name + Email (Skip Enrichment)
```sql
-- Insert companies with contact emails already known
INSERT INTO leads (
    campaign_id,
    company_name,
    website,
    decision_maker_email,
    source_type,
    enrichment_status,
    email_status,
    created_at,
    updated_at
)
VALUES
    (1, 'ABC Plumbing Inc', 'https://abcplumbing.com', 'john@abcplumbing.com', 'manual', 'completed', 'pending', NOW(), NOW()),
    (1, 'XYZ HVAC Services', 'https://xyzhvac.com', 'sarah@xyzhvac.com', 'manual', 'completed', 'pending', NOW(), NOW());

-- Note: enrichment_status is 'completed' since we already have the email
```

#### Option C: Import with Full Contact Details
```sql
-- Step 1: Insert the lead company
INSERT INTO leads (
    campaign_id,
    company_name,
    website,
    phone,
    address,
    decision_maker_name,
    decision_maker_title,
    decision_maker_email,
    source_type,
    enrichment_status,
    email_status,
    created_at,
    updated_at
)
VALUES
    (1, 'ABC Plumbing Inc', 'https://abcplumbing.com', '555-123-4567', '123 Main St, New York, NY', 'John Smith', 'Owner', 'john@abcplumbing.com', 'manual', 'completed', 'pending', NOW(), NOW());

-- Step 2: Insert the contact (optional, for multiple contacts per company)
INSERT INTO lead_contacts (
    lead_id,
    name,
    title,
    email,
    role_category,
    is_primary,
    email_status,
    created_at,
    updated_at
)
VALUES
    (LAST_INSERT_ID(), 'John Smith', 'Owner', 'john@abcplumbing.com', 'owner', 1, 'pending', NOW(), NOW());
```

#### Option D: Bulk Import from CSV Structure
```sql
-- If you have a CSV with: company_name, website, email, phone
-- Use this template and generate multiple VALUES rows

INSERT INTO leads (
    campaign_id,
    company_name,
    website,
    decision_maker_email,
    phone,
    source_type,
    enrichment_status,
    email_status,
    created_at,
    updated_at
)
VALUES
    (1, 'Company Name 1', 'https://domain1.com', 'contact1@domain1.com', '555-111-1111', 'manual', CASE WHEN 'contact1@domain1.com' IS NOT NULL THEN 'completed' ELSE 'pending' END, 'pending', NOW(), NOW()),
    (1, 'Company Name 2', 'https://domain2.com', NULL, '555-222-2222', 'manual', 'pending', 'pending', NOW(), NOW()),
    (1, 'Company Name 3', 'https://domain3.com', 'contact3@domain3.com', NULL, 'manual', 'completed', 'pending', NOW(), NOW());
```

### Finding Your Campaign ID
```sql
-- List all campaigns
SELECT id, name, industry_service, location, status
FROM lead_campaigns
ORDER BY created_at DESC;

-- Example output:
-- id | name                          | industry_service | location      | status
-- 1  | NYC Plumbers Outreach         | plumbing         | New York, NY  | ready
-- 2  | LA HVAC Lead Generation       | hvac             | Los Angeles   | sending
```

### Complete Import Workflow

1. **Create or identify your campaign:**
   ```sql
   -- Create new campaign
   INSERT INTO lead_campaigns (
       name, industry_service, location,
       scrape_ads, scrape_maps, scrape_lsa, scrape_organic,
       daily_email_limit, sequence_delay_days,
       status, created_at, updated_at
   )
   VALUES (
       'My Custom Lead List',
       'plumbing',
       'New York, NY',
       0, 0, 0, 0,  -- Disable scraping since we're manually importing
       250, 3,      -- 250 emails/day, 3 days between sequence emails
       'ready',
       NOW(), NOW()
   );

   -- Get the ID
   SELECT LAST_INSERT_ID();  -- Use this ID in next step
   ```

2. **Import your companies** (using Option A, B, C, or D above)

3. **Verify import:**
   ```sql
   SELECT
       l.id,
       l.company_name,
       l.website,
       l.decision_maker_email,
       l.enrichment_status,
       l.email_status
   FROM leads l
   WHERE l.campaign_id = 1  -- Replace with your campaign_id
   ORDER BY l.created_at DESC
   LIMIT 50;
   ```

4. **System will automatically:**
   - Enrich pending leads (find contact emails if missing)
   - Send emails to enriched leads based on campaign schedule
   - Track opens, clicks, and replies

### Advanced: Update Existing Leads
```sql
-- Update website for a lead
UPDATE leads
SET website = 'https://newdomain.com', updated_at = NOW()
WHERE company_name = 'ABC Plumbing Inc';

-- Add email to unenriched lead
UPDATE leads
SET
    decision_maker_email = 'found@email.com',
    enrichment_status = 'completed',
    enriched_at = NOW(),
    updated_at = NOW()
WHERE id = 123;

-- Mark lead as ready for emailing
UPDATE leads
SET email_status = 'pending', updated_at = NOW()
WHERE enrichment_status = 'completed'
  AND email_status NOT IN ('sent', 'replied', 'unsubscribed');
```

### Pro Tips

1. **Domain Format:** Always include `https://` in website URLs
2. **Email Validation:** System validates emails before sending
3. **Duplicate Check:** Check for duplicates before import:
   ```sql
   SELECT company_name, website FROM leads
   WHERE campaign_id = 1 AND website = 'https://example.com';
   ```

4. **Bulk Operations:** Use the admin dashboard at `/admin/lead-campaigns` for:
   - Bulk scrape all draft campaigns
   - Bulk enrich all pending leads
   - Bulk send emails to ready leads

---

## 2. Google Ads Dropdown Navigation Fix

### Issue
The Google Ads dropdown in the navigation sidebar is not expanding/collapsing properly.

### Root Cause
The chevron icon transform is being set via inline styles instead of using CSS classes, and there may be timing issues with DOM element availability.

### Fix Applied
Updated `/flaskapp/templates/base_app.html` to:
1. Remove inline style manipulation for icon rotation
2. Use CSS class toggling instead (`.expanded` class handles the rotation)
3. Ensure icon element ID matches the expected pattern

---

## 3. One-Click Campaign Automation System

### Overview
Streamlined automation that processes your core 20 campaigns with a single button click and scheduled execution.

### Features
- **One-Click Execution:** Run scrape → enrich → email pipeline for all campaigns
- **Scheduled Automation:** Auto-run at specified time (e.g., 9 AM daily)
- **Core 20 Campaigns:** Focus on your top-performing campaign configurations
- **Progress Tracking:** Real-time status updates and completion metrics
- **Error Handling:** Automatic retry logic and detailed error logs

### Implementation Components

1. **Campaign Automation Dashboard** (`/admin/campaigns/automation`)
   - Single "Run All Campaigns" button
   - Schedule configuration (time of day, frequency)
   - Real-time progress bar showing:
     - Campaigns processed (X/20)
     - Leads scraped, enriched, emailed
     - Current operation status
   - Historical run logs with success/failure metrics

2. **Automation Workflow**
   ```
   Click "Run All" →

   FOR EACH of 20 campaigns:
     1. Scrape leads (if status = 'draft')
     2. Enrich leads (if enrichment_status = 'pending')
     3. Send emails (if email_status = 'pending' and enriched)

   → Update dashboard with results
   ```

3. **Scheduling System**
   - Cron job or Celery Beat scheduler
   - Configurable time (default: 9:00 AM daily)
   - Respects email sending limits (250/day per campaign)
   - Pauses on weekends (optional)

4. **Core 20 Campaigns List**
   - Predefined in database with `is_core=True` flag
   - Industries: Plumbing, HVAC, Electrical, Roofing, Landscaping, etc.
   - Geographic diversity: Major US cities
   - Automatically created during setup

---

## Quick Start Checklist

### Import Your First Batch of Leads

1. **Find your campaign ID:**
   ```sql
   SELECT id, name FROM lead_campaigns ORDER BY created_at DESC LIMIT 10;
   ```

2. **Import companies** (choose your scenario):
   - **Have domains only?** Use Option A
   - **Have emails already?** Use Option B
   - **Have full contact info?** Use Option C

3. **Run the import query** in your MySQL client

4. **Trigger processing** from admin dashboard:
   - Go to `/admin/lead-campaigns`
   - Click "Enrich All Pending Leads" (finds emails)
   - Click "Send Emails to Ready Leads" (starts outreach)

5. **Monitor results:**
   - Check campaign view for sent emails
   - Track opens and replies in real-time

---

## Database Connection Examples

### Using MySQL Command Line
```bash
mysql -u your_username -p your_database_name

# Then paste your INSERT queries
```

### Using MySQL Workbench
1. Connect to your database
2. Open SQL Editor
3. Paste your INSERT query
4. Click Execute (⚡️ icon)
5. Verify with SELECT query

### Using phpMyAdmin
1. Select your database
2. Click "SQL" tab
3. Paste your query
4. Click "Go"

---

## Troubleshooting

### "No campaign found with ID X"
```sql
-- Check if campaign exists
SELECT * FROM lead_campaigns WHERE id = X;

-- List all campaigns
SELECT id, name, status FROM lead_campaigns;
```

### "Duplicate entry for website"
```sql
-- Check for existing lead
SELECT * FROM leads WHERE website = 'https://example.com';

-- Option 1: Update existing lead
UPDATE leads SET updated_at = NOW() WHERE website = 'https://example.com';

-- Option 2: Use different campaign_id
```

### "Enrichment not running"
```sql
-- Check pending enrichment count
SELECT COUNT(*) FROM leads WHERE enrichment_status = 'pending';

-- Manually trigger enrichment from admin dashboard
-- Or check enrichment service logs
```

### "Emails not sending"
```sql
-- Check leads ready for email
SELECT COUNT(*) FROM leads
WHERE enrichment_status = 'completed'
  AND email_status = 'pending'
  AND decision_maker_email IS NOT NULL;

-- Check email sequences exist
SELECT * FROM email_sequences WHERE campaign_id = 1;
```

---

## Next Steps

1. **Import your first batch** of 10-20 companies using the SQL templates
2. **Test the enrichment** by clicking "Enrich All Pending Leads"
3. **Review enriched contacts** in the campaign view
4. **Set up email sequences** for your campaign
5. **Start sending** with the bulk email button
6. **Monitor results** in the dashboard

For automated daily execution, the new one-click system will handle all of this automatically!
