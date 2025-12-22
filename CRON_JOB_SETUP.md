# How to Check and Fix Lead Automation Cron Job

## Issue
The lead campaigns page shows numbers aren't updating, indicating the cron job might not be running.

## Quick Diagnosis

### 1. Check if Timestamps Are Updating

Visit: https://fieldsprout.io/admin/lead-campaigns/

You should now see:
- **Last Scrape:** When leads were last scraped
- **Last Enrichment:** When leads were last enriched
- **Last Email Sent:** When emails were last sent

If these timestamps are **NOT updating daily**, the cron job is not running.

### 2. Check APScheduler Status

Visit: https://fieldsprout.io/admin/lead-campaigns/debug/scheduler-status

This will show:
- Is scheduler active?
- Is lead automation job registered?
- When is next run scheduled?

## How to Fix Cron Job Not Running

### Option 1: Check System Cron (Recommended for Production)

```bash
# View current crontab
crontab -l

# You should see something like:
# 0 9 * * * cd /home/fieljtgr/flaskapp && /home/fieljtgr/virtualenv/flaskapp/3.9/bin/python3 run_automation.py >> /tmp/lead_automation.log 2>&1
```

**If cron job is missing, add it:**

```bash
# Edit crontab
crontab -e

# Add this line (runs daily at 9 AM):
0 9 * * * export SQLALCHEMY_DATABASE_URI="mysql+pymysql://root:PASSWORD@localhost:3306/fieljtgr_xyz?charset=utf8mb4" && cd /home/fieljtgr/flaskapp && /home/fieljtgr/virtualenv/flaskapp/3.9/bin/python3 run_automation.py >> /tmp/lead_automation.log 2>&1

# Save and exit
```

**Replace `PASSWORD` with your actual MySQL password!**

### Option 2: Check APScheduler (Application-Level Scheduler)

The application has a built-in scheduler that runs automation daily.

**Check if it's running:**

```bash
# Look for the scheduler job in logs
grep -i "scheduler" /var/log/your-app.log

# Or check the diagnostic endpoint
curl https://fieldsprout.io/admin/lead-campaigns/debug/scheduler-status
```

**If scheduler is not active:**
- The app may need to be restarted
- Check `background_jobs.py` is properly initialized
- Verify app is running with scheduler enabled

### Option 3: Manual Run (For Testing)

To manually trigger the automation and verify it works:

```bash
# Activate virtualenv
source /home/fieljtgr/virtualenv/flaskapp/3.9/bin/activate

# Set database connection
export SQLALCHEMY_DATABASE_URI="mysql+pymysql://root:PASSWORD@localhost:3306/fieljtgr_xyz?charset=utf8mb4"

# Run automation
cd /home/fieljtgr/flaskapp
python3 run_automation.py
```

After running, refresh the lead campaigns page and check if timestamps updated.

## Verifying Automation is Working

### Check Today's Activity

The automation dashboard shows:
- **Scrapes:** X/50 (should increase daily)
- **Enrichments:** X/100 (should increase daily)
- **Emails:** X/250 (should increase daily)

Visit: https://fieldsprout.io/admin/lead-campaigns/automation-status

### Check Logs

```bash
# View automation log
tail -f /tmp/lead_automation.log

# Look for successful runs:
# "✅ AUTOMATION COMPLETE"
# "Campaigns Scraped: X"
# "Leads Enriched: X"
# "Emails Sent: X"
```

### Check Last Activity Times

On each campaign card, you should see:
- 🔵 **Last Scrape:** Recent timestamp (within 24 hours)
- 🟢 **Last Enrichment:** Recent timestamp (within 24 hours)
- 🟣 **Last Email Sent:** Recent timestamp (within 24 hours)

## Expected Behavior

When automation is running correctly:

**Daily (9 AM):**
1. Scrapes up to 50 new leads
2. Enriches up to 100 leads (finds contact emails)
3. Sends up to 250 emails

**What You Should See:**
- Timestamps update daily
- Lead counts increase
- Email counts increase
- "Today's Activity" shows progress

## Troubleshooting

### Problem: Timestamps not updating

**Causes:**
- Cron job not configured
- App scheduler not running
- Missing dependencies (bs4, requests, etc.)
- Database connection error
- API keys missing (SerpAPI, Apollo, Mailgun)

**Solutions:**
1. Run automation manually to test
2. Check logs for errors
3. Verify all dependencies installed
4. Verify environment variables set

### Problem: Numbers stay at 0

**Causes:**
- No campaigns set to 'ready' status
- Daily limits already reached
- Missing email sequences
- No enriched leads with email addresses

**Solutions:**
1. Check campaign status (should be 'ready')
2. Run diagnostic: `check_lead_automation_status.sql`
3. Create email sequences if missing
4. Check enrichment API is working

## Daily Limits

The system has these limits:
- **Scraping:** 50 campaigns/day
- **Enrichment:** 100 leads/day
- **Email Sending:** 250 emails/day

These limits prevent API rate limiting and ensure deliverability.

## Need Help?

1. Check scheduler status: `/admin/lead-campaigns/debug/scheduler-status`
2. Check automation progress: `/admin/lead-campaigns/automation-status`
3. View debug stats: `/admin/lead-campaigns/debug-stats`
4. Check logs: `tail -f /tmp/lead_automation.log`
