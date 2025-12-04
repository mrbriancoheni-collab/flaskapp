# Deployment Instructions for December 2025 Updates

## Summary of Changes

1. **Lead Campaign Consolidation**: Reduced from 4,507 campaigns to 100 campaigns (one per city with all keywords)
2. **Statistics Fix**: Campaign statistics now read from database instead of state file
3. **CRM Integration**: Leads and contacts now automatically sync to CRM after enrichment
4. **Podcast Page**: Added public-facing podcast promotion page at `/podcast`
5. **AI Ad Composer**: New tool for generating social media ads with AI (DALL-E 3 + Claude/GPT-4)

---

## Step 1: Run Database Migrations

### Migration 1: Ad Composer Tables

```bash
# Connect to MySQL
mysql -u fieljtgr_flaskuser -p fieljtgr_flaskapp

# Run the migration
source /home/fieljtgr/flaskapp/migrations/001_add_social_ad_composer_tables.sql

# Verify tables were created
SHOW TABLES LIKE 'ad_%';
```

### Migration 2: CRM Integration Columns

```bash
# Still in MySQL
source /home/fieljtgr/flaskapp/migrations/002_add_crm_integration_columns.sql

# Verify columns were added
DESCRIBE leads;
DESCRIBE lead_contacts;
```

---

## Step 2: Configure Environment Variables

Add the following to your `.env` file or set them in cPanel:

```bash
# OpenAI API Key (for DALL-E 3 image generation)
OPENAI_API_KEY=sk-your-openai-key-here

# Anthropic API Key (for Claude copywriting - optional, will fall back to GPT-4)
ANTHROPIC_API_KEY=sk-ant-your-anthropic-key-here
```

### To set environment variables in cPanel:
1. Go to cPanel → Setup Python App
2. Click on your Flask application
3. Scroll to "Environment variables"
4. Add the keys above

---

## Step 3: Restart the Application

### Method A: Via cPanel (Recommended)
1. Log into cPanel
2. Navigate to "Setup Python App"
3. Find your Flask application
4. Click "Stop App"
5. Wait 5 seconds
6. Click "Start App"

### Method B: Via SSH (Alternative)
```bash
# Navigate to app directory
cd /home/fieljtgr/flaskapp

# Touch passenger_wsgi.py to trigger restart
touch passenger_wsgi.py

# OR restart via Passenger
passenger-config restart-app /home/fieljtgr/flaskapp
```

### Method C: Via touch restart file
```bash
cd /home/fieljtgr/flaskapp
touch tmp/restart.txt
```

---

## Step 4: Verify Deployment

### Check Campaign Count
Visit: https://fieldsprout.io/admin/lead-campaigns/

**Expected result**: Should show ~100 campaigns instead of 4,507

### Check Statistics
Visit: https://fieldsprout.io/admin/lead-campaigns/automation-status

**Expected result**: Should show actual numbers from database, not zeros

### Check Podcast Page
Visit: https://fieldsprout.io/podcast

**Expected result**: Should display the podcast promotion page

### Check Ad Composer
Visit: https://fieldsprout.io/social/ad-composer

**Expected result**: Should display the AI Ad Composer interface

---

## Step 5: Run Lead Consolidation (One-Time)

The campaign consolidation code is in place, but existing campaigns need to be cleaned up:

```bash
# SSH into server
ssh fieljtgr@fieldsprout.io

# Activate virtualenv
source /home/fieljtgr/virtualenv/flaskapp/3.9/bin/activate

# Navigate to app
cd /home/fieljtgr/flaskapp

# Run Python shell
python3

# In Python:
from app import create_app, db
from app.models_leads import LeadCampaign

app = create_app()
with app.app_context():
    # Count current campaigns
    total = LeadCampaign.query.count()
    print(f"Total campaigns: {total}")

    # Delete campaigns with zero leads (safe cleanup)
    empty_campaigns = LeadCampaign.query.filter_by(total_leads=0).all()
    print(f"Empty campaigns to delete: {len(empty_campaigns)}")

    for campaign in empty_campaigns:
        db.session.delete(campaign)

    db.session.commit()
    print("Cleanup complete!")

    # Verify
    remaining = LeadCampaign.query.count()
    print(f"Remaining campaigns: {remaining}")
```

---

## Step 6: Test CRM Sync (Optional)

To sync existing enriched leads to CRM:

```bash
# In Python shell (from above)
from app.services.crm_sync_service import CRMSyncService

sync_service = CRMSyncService()

# Sync a batch of enriched leads
synced, failed = sync_service.sync_enriched_leads_batch(limit=50)
print(f"Synced: {synced}, Failed: {failed}")
```

---

## Step 7: Test Ad Composer

1. Log into https://fieldsprout.io
2. Navigate to https://fieldsprout.io/social/ad-composer
3. Try generating an ad:
   - Enter a business website URL
   - Select platform (Facebook, Instagram, LinkedIn)
   - Click "Generate from Website"
4. Verify image and copy are generated

---

## Troubleshooting

### Issue: Still showing 4,507 campaigns
**Solution**: Application server needs restart. Follow Step 3 above.

### Issue: Ad Composer shows "API key not configured"
**Solution**: Add OPENAI_API_KEY and ANTHROPIC_API_KEY to environment variables (Step 2)

### Issue: Database migration fails
**Solution**: Check if tables already exist. You can skip existing tables.

### Issue: 500 error on /social/ad-composer
**Solution**:
1. Check logs: `tail -f ~/app_error.log`
2. Verify social_bp is registered: `grep "social_bp registered" ~/app_error.log`
3. Restart app (Step 3)

### Issue: CRM sync not working
**Solution**: Ensure CRM tables exist (crm_contacts, company_contacts)

---

## Rollback Instructions (Emergency Only)

If you need to rollback:

```bash
# Rollback ad composer tables
mysql -u fieljtgr_flaskuser -p fieljtgr_flaskapp

DROP TABLE IF EXISTS ad_generation_jobs;
DROP TABLE IF EXISTS ad_creative_variations;
DROP TABLE IF EXISTS ad_creatives;
DROP TABLE IF EXISTS ad_templates;

# Rollback CRM columns
ALTER TABLE leads DROP COLUMN IF EXISTS crm_contact_id;
ALTER TABLE lead_contacts DROP COLUMN IF EXISTS company_contact_id;
```

---

## Support

If you encounter any issues:
1. Check logs: `tail -f ~/app_error.log`
2. Check application status in cPanel
3. Verify environment variables are set
4. Contact support with specific error messages

---

## Next Steps (Optional)

1. Add navigation link to Ad Composer in admin interface
2. Set up S3 for ad image storage (currently using OpenAI URLs)
3. Implement Facebook/Instagram/LinkedIn publishing APIs
4. Create sample ad templates for your specific industries
5. Set up automated CRM sync in cron job

---

## Files Modified/Created

### Modified:
- `flaskapp/app/__init__.py` - Registered social_bp blueprint
- `flaskapp/app/services/lead_automation_service.py` - Database-based statistics
- `flaskapp/app/configs/lead_automation_config.py` - Consolidated campaign generation
- `flaskapp/app/models_leads.py` - Added CRM foreign keys
- `flaskapp/app/public/__init__.py` - Added podcast route

### Created:
- `flaskapp/app/social/__init__.py` - Social media routes
- `flaskapp/app/services/ad_generation_service.py` - AI ad generation
- `flaskapp/app/services/crm_sync_service.py` - CRM sync service
- `flaskapp/app/models_social.py` - Ad composer models
- `flaskapp/templates/social/ad_composer.html` - Ad composer UI
- `flaskapp/templates/public/podcast.html` - Podcast page
- `migrations/001_add_social_ad_composer_tables.sql`
- `migrations/002_add_crm_integration_columns.sql`
