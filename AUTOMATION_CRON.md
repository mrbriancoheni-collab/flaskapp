# Lead Generation Automation - Cron Setup Guide

## Quick Setup

Run the automated setup script:

```bash
cd /home/user/flaskapp
./setup_cron.sh
```

This will set up a cron job to run the automation **daily at 9:00 AM**.

## Manual Setup

If you prefer to set it up manually:

```bash
# Edit your crontab
crontab -e

# Add this line:
0 9 * * * cd /home/user/flaskapp && flask run-lead-automation >> /home/user/flaskapp/logs/automation.log 2>&1
```

## Different Schedule Options

### Run at Different Times

```bash
# Run at 6:00 AM
0 6 * * * cd /home/user/flaskapp && flask run-lead-automation >> /home/user/flaskapp/logs/automation.log 2>&1

# Run at 2:00 PM
0 14 * * * cd /home/user/flaskapp && flask run-lead-automation >> /home/user/flaskapp/logs/automation.log 2>&1

# Run at midnight
0 0 * * * cd /home/user/flaskapp && flask run-lead-automation >> /home/user/flaskapp/logs/automation.log 2>&1
```

### Run Multiple Times Per Day

```bash
# Run every 6 hours (0:00, 6:00, 12:00, 18:00)
0 */6 * * * cd /home/user/flaskapp && flask run-lead-automation >> /home/user/flaskapp/logs/automation.log 2>&1

# Run twice daily (9 AM and 9 PM)
0 9,21 * * * cd /home/user/flaskapp && flask run-lead-automation >> /home/user/flaskapp/logs/automation.log 2>&1
```

### Run on Specific Days

```bash
# Run only on weekdays (Monday-Friday) at 9 AM
0 9 * * 1-5 cd /home/user/flaskapp && flask run-lead-automation >> /home/user/flaskapp/logs/automation.log 2>&1

# Skip weekends (Monday-Friday)
0 9 * * 1-5 cd /home/user/flaskapp && flask run-lead-automation >> /home/user/flaskapp/logs/automation.log 2>&1
```

## Cron Schedule Format

```
* * * * * command
│ │ │ │ │
│ │ │ │ └─── Day of week (0-7, where 0 and 7 are Sunday)
│ │ │ └───── Month (1-12)
│ │ └─────── Day of month (1-31)
│ └───────── Hour (0-23)
└─────────── Minute (0-59)
```

## Managing Cron Jobs

### View Current Cron Jobs
```bash
crontab -l
```

### Edit Cron Jobs
```bash
crontab -e
```

### Remove All Cron Jobs
```bash
crontab -r
```

### Remove Specific Cron Job
```bash
crontab -e
# Delete the line with 'run-lead-automation'
```

## Monitoring

### View Live Logs
```bash
tail -f /home/user/flaskapp/logs/automation.log
```

### View Last 100 Lines
```bash
tail -100 /home/user/flaskapp/logs/automation.log
```

### Search Logs for Errors
```bash
grep -i error /home/user/flaskapp/logs/automation.log
```

### Check Today's Activity
```bash
grep "$(date +%Y-%m-%d)" /home/user/flaskapp/logs/automation.log
```

## Testing

### Test the Command Manually
```bash
cd /home/user/flaskapp
flask run-lead-automation
```

### Dry Run (Preview Only)
```bash
cd /home/user/flaskapp
flask run-lead-automation --dry-run
```

## Troubleshooting

### Cron Job Not Running?

1. **Check if cron service is running:**
   ```bash
   sudo systemctl status cron
   # or
   sudo service cron status
   ```

2. **Check cron logs:**
   ```bash
   grep CRON /var/log/syslog
   ```

3. **Verify environment variables:**
   Cron runs with minimal environment. If you need environment variables, add them to the cron job:
   ```bash
   0 9 * * * cd /home/user/flaskapp && export $(cat .env | xargs) && flask run-lead-automation >> /home/user/flaskapp/logs/automation.log 2>&1
   ```

4. **Check permissions:**
   ```bash
   ls -la /home/user/flaskapp/setup_cron.sh
   ```

### No Output in Log File?

Make sure the log directory exists:
```bash
mkdir -p /home/user/flaskapp/logs
chmod 755 /home/user/flaskapp/logs
```

## What the Automation Does Daily

When the cron job runs, it will:

1. **Create & Scrape Campaigns** (up to 50/day)
   - Creates campaigns from the 4,500 campaign queue
   - Scrapes Google Ads, Maps, LSA, and Organic results
   - Saves leads to database
   - Skips duplicate domains

2. **Enrich Leads** (up to 100/day)
   - Finds decision makers (CEO, President, Owner, Marketing)
   - Discovers email addresses
   - Saves contact information

3. **Send Emails** (up to 250/day)
   - Sends personalized outreach emails
   - Uses email sequence templates
   - Skips Sundays automatically
   - Tracks sent emails

4. **Save State**
   - Saves progress to `/home/user/flaskapp/automation_state.json`
   - Resumes from where it stopped
   - Tracks daily limits

## Daily Limits

The automation respects these daily limits:

- **Scraping:** 50 campaigns/day (SerpAPI limit)
- **Enrichment:** 100 leads/day
- **Emails:** 250/day (Mailgun limit)
- **Sundays:** No emails sent (configurable)

At this rate:
- **4,500 campaigns** will take ~90 days to complete
- Continuous lead generation and outreach
- Automated follow-up sequences

## Environment Variables Required

Make sure these are set in your environment or `.env` file:

```bash
SERPAPI_API_KEY=your_serpapi_key
MAILGUN_API_KEY=your_mailgun_key
MAILGUN_DOMAIN=your_domain
SQLALCHEMY_DATABASE_URI=your_database_url
```

## Support

View automation status anytime at:
- **Dashboard:** https://fieldsprout.io/admin/lead-campaigns/
- **Full Status:** https://fieldsprout.io/admin/automation-status/
- **Activity Feed:** https://fieldsprout.io/admin/activity/

Or run:
```bash
flask run-lead-automation --dry-run
```
