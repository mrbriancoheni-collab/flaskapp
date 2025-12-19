# Lead Automation System Setup Guide

## Problem
You're seeing database errors because the lead automation tables haven't been created yet.

**Errors you're seeing:**
- ❌ `Table 'lead_emails' doesn't exist`
- ❌ `Unknown column 'created_at' in 'SELECT'`

## Solution: Run Database Migration

### Step 1: Create the Database Tables

Run this SQL migration to create all 10 required tables:

```bash
mysql -u root fieljtgr_xyz < migrations_sql/012_lead_automation_complete.sql
```

**What this creates:**
1. ✅ `lead_campaigns` - Campaign configurations
2. ✅ `leads` - Scraped company leads
3. ✅ `lead_contacts` - Contact info (decision makers)
4. ✅ `email_sequences` - Email templates
5. ✅ `lead_emails_sent` - Email tracking (legacy)
6. ✅ `lead_contact_emails` - Email tracking (new)
7. ✅ `email_unsubscribes` - CAN-SPAM compliance
8. ✅ `email_conversations` - AI auto-response threads
9. ✅ `email_conversation_messages` - Individual messages
10. ✅ `conversation_alerts` - Admin notifications

---

### Step 2: Verify Tables Were Created

Run this to check:

```sql
USE fieljtgr_xyz;
SHOW TABLES LIKE 'lead%';
SHOW TABLES LIKE 'email%';
```

You should see all 10 tables listed.

---

### Step 3: Run the Diagnostic

Now you can run the diagnostic to see why only 8 emails were sent:

```bash
mysql -u root fieljtgr_xyz < check_lead_automation_status.sql
```

This will show you:
- ✅ How many campaigns exist
- ✅ How many leads are scraped
- ✅ How many leads are enriched
- ✅ How many contacts have emails
- ✅ How many emails sent today
- ✅ **Where the bottleneck is**

---

### Step 4: Start the Automation

Once tables are created, you can start generating leads and sending emails:

```bash
# Run the full automation cycle
python3 run_automation.py
```

This will:
1. **Scrape** up to 50 campaigns/day (Google Maps, LSA, Ads, Organic)
2. **Enrich** up to 100 leads/day (get contact info from Apollo.io)
3. **Send** up to 250 emails/day (personalized outreach via Mailgun/Brevo)

---

## Expected Results

### After First Run:
- **Campaigns created:** 1-50 (depending on how many you configured)
- **Leads scraped:** 50-200 per campaign (from Google results)
- **Leads enriched:** 0-100 (limited by Apollo.io API and daily limit)
- **Emails sent:** 0-100 (can only send to enriched leads with emails)

### After 2-3 Days:
- **Campaigns:** 50-150 total
- **Enriched leads:** 200-300 total
- **Emails sent/day:** 50-250 (depending on available enriched leads)

---

## Why Only 8 Emails Sent?

The most likely reasons (in order):

### 1. **Only 8 Enriched Leads Available** ← MOST LIKELY
The system can only send emails to leads that have been:
- ✅ Scraped from Google
- ✅ Enriched with contact info (Apollo.io)
- ✅ Have valid email addresses
- ✅ Haven't been emailed yet

**Solution:** Run the automation daily to build up your enriched lead database.

### 2. **Enrichment Not Finding Emails**
Apollo.io might not find contact info for every lead.

**Success rate typically:**
- Small local businesses: 30-50% email discovery rate
- Mid-size companies: 60-80% email discovery rate
- Enterprise: 80-90% email discovery rate

**Solution:** Check Apollo.io credit balance and API key.

### 3. **Email Provider Rate Limiting**
Mailgun/Brevo free tiers have low limits.

**Free tier limits:**
- Mailgun: 100 emails/day (verification required for more)
- Brevo: 300 emails/day

**Solution:** Check your provider dashboard for sending limits.

### 4. **No Campaigns in 'Ready' Status**
Campaigns must be marked as 'ready' to send emails.

**Solution:**
```sql
UPDATE lead_campaigns SET status = 'ready' WHERE status = 'draft';
```

---

## Daily Automation Limits

Configured in `flaskapp/app/configs/lead_automation_config.py`:

```python
AUTOMATION_CONFIG = {
    "daily_scrape_limit": 50,      # Campaigns to scrape per day
    "daily_enrich_limit": 100,     # Leads to enrich per day
    "daily_email_limit": 250,      # Emails to send per day
    "skip_email_days": [6],        # Don't send on Sundays
}
```

These limits prevent:
- ❌ Overusing SerpAPI credits (scraping)
- ❌ Overusing Apollo.io credits (enrichment)
- ❌ Getting blocked by email providers (sending)

---

## Automation Schedule

Set up a daily cron job to run automation automatically:

```bash
# Edit crontab
crontab -e

# Add this line (runs daily at 9 AM):
0 9 * * * cd /path/to/flaskapp && python3 run_automation.py >> /tmp/automation.log 2>&1
```

---

## Monitoring Progress

### Option 1: SQL Diagnostic (Fast)
```bash
mysql -u root fieljtgr_xyz < check_lead_automation_status.sql
```

### Option 2: Python Diagnostic (Detailed)
```bash
python3 check_lead_automation_status.py
```

### Option 3: Web Dashboard
Visit: https://fieldsprout.io/admin/campaigns

---

## Troubleshooting

### "Cannot initialize scraper" Error
**Problem:** Missing SerpAPI key

**Solution:**
```bash
export SERPAPI_KEY="your_api_key_here"
# Or add to .env file:
echo "SERPAPI_KEY=your_api_key" >> .env
```

### "Cannot initialize mailgun outreach service" Error
**Problem:** Missing Mailgun/Brevo credentials

**Solution:**
```bash
# For Mailgun:
export MAILGUN_API_KEY="your_key_here"
export MAILGUN_DOMAIN="mg.yourdomain.com"

# OR for Brevo:
export EMAIL_PROVIDER="brevo"
export BREVO_API_KEY="your_key_here"
```

### "Apollo API error" During Enrichment
**Problem:** Invalid API key or out of credits

**Solution:**
```bash
# Check API key:
export APOLLO_API_KEY="your_key_here"

# Check credits at: https://app.apollo.io/settings/credits
```

---

## Next Steps After Setup

1. ✅ Run migration: `migrations_sql/012_lead_automation_complete.sql`
2. ✅ Run diagnostic: `check_lead_automation_status.sql`
3. ✅ Run automation: `python3 run_automation.py`
4. ✅ Check results: Review diagnostic output
5. ✅ Set up cron: Schedule daily automation
6. ✅ Monitor: Check dashboard regularly

---

## Expected Timeline to 50+ Emails/Day

| Day | Scraping | Enrichment | Email Sending |
|-----|----------|------------|---------------|
| 1   | 50 campaigns → 1000 leads | 100 enriched (10-50 emails found) | **10-50 emails** |
| 2   | 50 campaigns → 2000 leads | 100 enriched (10-50 emails found) | **20-100 emails** |
| 3   | 50 campaigns → 3000 leads | 100 enriched (10-50 emails found) | **30-150 emails** |
| 4+  | 50 campaigns → 4000+ leads | 100 enriched (10-50 emails found) | **50-250 emails** ✅ |

**Key factors:**
- Email discovery rate (30-80% depending on business type)
- Apollo.io credit availability
- Campaign targeting (local vs national)

You should reach 50+ emails/day by **Day 3-4** if enrichment is finding contacts consistently.

---

## Summary

**Current Issue:** Tables don't exist → Can't send emails

**Solution:** Run the migration SQL file

**Expected Outcome:**
- Day 1: 10-50 emails sent (building lead database)
- Day 3+: 50-250 emails sent (steady state)

The 250/day limit is configured correctly - you just need to build up your enriched lead database first!
