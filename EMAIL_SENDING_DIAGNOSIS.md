# Email Sending Diagnosis: Only 8 Sent Instead of 50+ Minimum

## Problem
Only 8 emails were sent today when the target minimum is 50/day (with a configured limit of 250/day).

## Configuration
From `flaskapp/app/configs/lead_automation_config.py`:
- **Daily email limit:** 250 emails/day
- **Daily enrichment limit:** 100 leads/day
- **Daily scrape limit:** 50 campaigns/day

## Most Likely Causes

### 1. ⚠️  **Insufficient Enriched Leads** (MOST LIKELY)
**Problem:** You may only have 8 leads that are:
- `enrichment_status = 'completed'`
- AND have pending contacts with email addresses
- AND campaign status = 'ready'

**How to diagnose:**
```sql
-- Run this SQL query to check:
SELECT COUNT(*) as enriched_leads
FROM leads
WHERE enrichment_status = 'completed';

SELECT COUNT(DISTINCT lead_id) as leads_with_pending_contacts
FROM lead_contacts
WHERE email_status = 'pending'
AND email IS NOT NULL;
```

**Solution:**
- Run enrichment: `python3 run_automation.py` (to enrich more leads)
- Check if enrichment is finding contacts (see below)

---

### 2. 🔴 **Rate Limiting from Email Provider**
**Problem:** Mailgun/Brevo may be rate limiting after 8 emails.

**How to diagnose:**
Check logs for this message:
```
"Mailgun rate limit hit. Stopping email sending. Retry after X seconds"
```

**Solution:**
- Check your Mailgun/Brevo dashboard for sending limits
- Verify API key is correct: `MAILGUN_API_KEY` or `BREVO_API_KEY` in environment
- Check if you're on a free tier with low limits

---

### 3. 📧 **Missing Email Sequences**
**Problem:** Campaigns may not have email sequences configured.

**How to diagnose:**
```sql
SELECT
    lc.id,
    lc.name,
    lc.status,
    COUNT(es.id) as sequence_count
FROM lead_campaigns lc
LEFT JOIN email_sequences es ON es.campaign_id = lc.id
WHERE lc.status = 'ready'
GROUP BY lc.id;
```

**Solution:**
- Email sequences are auto-created by the automation service
- If missing, the code should create them automatically (line 557 in lead_automation_service.py)
- Check logs for: "Could not get/create email sequence for campaign"

---

### 4. ⏸️  **Campaigns Not in 'Ready' Status**
**Problem:** Campaigns may not be marked as 'ready'.

**How to diagnose:**
```sql
SELECT status, COUNT(*) as count
FROM lead_campaigns
GROUP BY status;
```

**Solution:**
- Log into admin panel: https://fieldsprout.io/admin/campaigns
- Change campaign status to 'ready'

---

### 5. 🔍 **Enrichment Not Finding Contacts**
**Problem:** Enrichment may be completing but not finding email addresses.

**How to diagnose:**
```sql
-- Check enriched leads vs leads with contacts
SELECT
    (SELECT COUNT(*) FROM leads WHERE enrichment_status = 'completed') as enriched_leads,
    (SELECT COUNT(DISTINCT lead_id) FROM lead_contacts WHERE email IS NOT NULL) as leads_with_contacts;
```

**Solution:**
- Check if you have valid Apollo.io API key: `APOLLO_API_KEY`
- Check enrichment logs for errors
- May need to upgrade Apollo.io plan for more credits

---

## Diagnostic Steps

### Step 1: Run SQL Diagnostic
```bash
# From your database:
mysql -u root flaskapp < check_lead_automation_status.sql
```

This will show you:
- How many campaigns exist and their status
- How many leads are enriched
- How many contacts are pending
- How many emails sent today
- Bottleneck analysis

### Step 2: Run Automation Manually (with logging)
```bash
python3 run_automation.py
```

Watch the output for:
- How many campaigns are being scraped
- How many leads are being enriched
- How many emails are being sent
- Any error messages

### Step 3: Check Logs
Look for these specific log messages:
- `"Found X ready campaigns"`
- `"Campaign 'X': Y enriched leads"`
- `"Sent email to X"`
- `"Mailgun rate limit hit"`
- `"Could not get/create email sequence"`
- `"Cannot initialize mailgun outreach service"`

---

## Quick Fixes

### If you have < 50 enriched leads ready:
```bash
# Run the full automation cycle to scrape + enrich + send
python3 run_automation.py
```

### If enrichment is not running:
```bash
# Check if cron job is configured:
crontab -l | grep automation

# If not, add daily cron:
0 9 * * * cd /path/to/flaskapp && python3 run_automation.py >> /tmp/automation.log 2>&1
```

### If email provider failing:
```bash
# Verify environment variables are set:
echo $MAILGUN_API_KEY
echo $MAILGUN_DOMAIN
# OR
echo $BREVO_API_KEY

# Test Mailgun directly:
curl -s --user 'api:YOUR_MAILGUN_KEY' \
  https://api.mailgun.net/v3/YOUR_DOMAIN/messages \
  -F from='test@YOUR_DOMAIN' \
  -F to='you@example.com' \
  -F subject='Test' \
  -F text='Test email'
```

---

## Expected Flow

For 50+ emails/day, you need:

1. **At least 1 campaign** with status='ready'
2. **At least 50 enriched leads** in that campaign with:
   - `enrichment_status = 'completed'`
   - At least 1 contact with `email IS NOT NULL` and `email_status = 'pending'`
3. **Valid email provider** (Mailgun/Brevo) credentials
4. **Email sequence** (auto-created if missing)
5. **Under daily limit** (not already sent 250 emails today)
6. **Not Sunday** (configured to skip Sundays in `AUTOMATION_CONFIG`)

---

## Code Logic Summary

The automation runs in 3 stages:

### Stage 1: Scraping (up to 50/day)
- Creates campaigns from `TOP_CITIES` x `HOME_SERVICE_CATEGORIES`
- Scrapes Google Maps, LSA, Ads, Organic for each city
- Creates leads with basic info (company name, phone, address)

### Stage 2: Enrichment (up to 100/day)
- Takes leads with `enrichment_status = 'pending'`
- Calls Apollo.io API to get:
  - Decision maker names, titles, emails
  - Creates `lead_contacts` records
- Marks lead as `enrichment_status = 'completed'`

### Stage 3: Email Sending (up to 250/day)
- Gets campaigns with status='ready'
- For each campaign, gets enriched leads
- For each lead, gets pending contacts
- Sends personalized email via Mailgun/Brevo
- Marks contact as `email_status = 'sent'`

**The bottleneck is most likely between Stage 2 and Stage 3.**

---

## Next Steps

1. Run the SQL diagnostic: `check_lead_automation_status.sql`
2. Share the output with me
3. Based on the results, I can tell you exactly which stage is blocking

The diagnostic will tell us:
- ✅ Do you have campaigns?
- ✅ Are they in 'ready' status?
- ✅ Do you have scraped leads?
- ✅ Are leads being enriched?
- ✅ Are enriched leads getting contact info?
- ✅ Are contacts being emailed?

Once we identify the bottleneck, we can fix it specifically.
