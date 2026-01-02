# Configuration Summary - Brevo Email & 20 Campaigns

## Changes Made

### 1. Email Provider Configuration ✅
**File**: `flaskapp/app/config.py`

- Set EMAIL_PROVIDER to default to "brevo"
- Added BREVO_API_KEY configuration
- Added BREVO_FROM_EMAIL (defaults to noreply@fieldsprout.io)
- Added BREVO_FROM_NAME (defaults to FieldSprout)
- Lead automation enabled by default

**Required Environment Variables**:
```bash
BREVO_API_KEY=your_brevo_api_key_here
EMAIL_PROVIDER=brevo  # Set automatically via config default
```

### 2. Campaign Display Limited to 20 ✅
**File**: `flaskapp/app/admin/lead_campaigns_routes.py:407`

Changed campaign query from:
```python
campaigns = LeadCampaign.query.order_by(desc(LeadCampaign.created_at)).all()
```

To:
```python
campaigns = LeadCampaign.query.order_by(desc(LeadCampaign.created_at)).limit(20).all()
```

This shows only the **newest 20 campaigns**, matching our new structure of 20 business types.

### 3. Automation Configuration ✅
**File**: `flaskapp/app/configs/lead_automation_config.py`

**Campaign Structure**:
- 20 campaigns (one per business type)
- Each campaign scrapes all 100 top US cities
- Total coverage: 20 business types × 100 cities

**20 Business Types**:
1. Plumbing
2. HVAC
3. Electrical
4. Roofing
5. Landscaping
6. Pest Control
7. Cleaning
8. Painting
9. Locksmith
10. Garage Door
11. Handyman
12. Window Cleaning
13. Pool Service
14. Tree Service
15. Carpet Cleaning
16. Flooring
17. Concrete
18. Fencing
19. Gutter
20. Appliance Repair

**Automation Settings**:
```python
daily_scrape_limit: 50       # Max leads to scrape per day
daily_enrich_limit: 100      # Max leads to enrich per day
daily_email_limit: 250       # Max emails to send per day
skip_email_days: [6]         # Skip Sundays (6 = Sunday)
```

**Email Sources**:
- ✅ Search Ads (Google Ads)
- ✅ Google Maps / Local Pack
- ✅ Local Services Ads (LSA)
- ✅ Organic Results (top 20)

**URL Filtering** (Directories Excluded):
- Yelp, YellowPages, Thumbtack
- Angi, HomeAdvisor, BBB
- Porch, Houzz, Nextdoor
- Facebook, Instagram, Twitter, LinkedIn
- .gov and .org domains

## How Automation Works

### Daily Automation Cycle
The system runs automatically via cron job (`run_daily()`):

1. **Scraping** (up to 50 leads/day)
   - Creates campaigns for each business type
   - Scrapes across all 100 cities per business type
   - Deduplicates domains globally and within campaigns
   - Tracks which cities each business appears in

2. **Enrichment** (up to 100 leads/day)
   - Finds decision maker contact information
   - Extracts multiple contacts per company
   - Syncs to CRM system

3. **Email Sending** (up to 250 emails/day)
   - Uses Brevo email service
   - Sends personalized outreach emails
   - Skips Sundays
   - Respects daily limits

### State Management
Progress is tracked in `automation_state.json`:
- Resumes from where it stopped
- Tracks processed domains to avoid duplicates
- Maintains daily statistics

## Testing the Configuration

### 1. Verify Email Provider
```bash
# Check if Brevo is configured
python -c "from flaskapp.app.config import Config; print(f'Email Provider: {Config.EMAIL_PROVIDER}')"
```

### 2. Test Email Sending
```bash
flask test-email-provider --to your@email.com --provider brevo
```

### 3. Check Automation Status
Visit: `/admin/lead-campaigns/automation-status`

### 4. View Campaigns
Visit: `/admin/lead-campaigns/`
- Should show only the newest 20 campaigns

## Next Steps

1. **Set BREVO_API_KEY** in your environment:
   ```bash
   export BREVO_API_KEY="your_actual_brevo_api_key"
   ```

2. **Restart the application** to pick up config changes

3. **Monitor automation**:
   - Check `/admin/lead-campaigns/automation-status`
   - View logs for scraping progress
   - Verify emails are being sent via Brevo

4. **Optional**: Adjust daily limits in `lead_automation_config.py` if needed

## Files Modified

1. `/home/user/flaskapp/flaskapp/app/config.py` - Added Brevo configuration
2. `/home/user/flaskapp/flaskapp/app/admin/lead_campaigns_routes.py` - Limited campaign display to 20
3. `/home/user/flaskapp/flaskapp/app/configs/lead_automation_config.py` - Already updated to 20 business types
4. `/home/user/flaskapp/flaskapp/app/services/lead_automation_service.py` - Already updated for city iteration

## Status: Ready to Deploy ✅

All configuration changes are complete. The system will:
- Use Brevo for email sending (no Mailgun errors)
- Display only the newest 20 campaigns
- Automatically scrape, enrich, and send emails daily
- Cover 20 business types across 100 top US cities
