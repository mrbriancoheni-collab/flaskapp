# Lead Automation Cron Jobs for cPanel

This guide provides the cron job configurations to run scraping, enrichment, and email outreach separately.

## Overview

Three separate operations run independently:
1. **Scraping** - Discovers new leads from campaigns
2. **Enrichment** - Enriches lead data (contact info, company details)
3. **Email Outreach** - Sends personalized emails to enriched leads

## Recommended Schedule

| Operation | Frequency | Time | Reason |
|-----------|-----------|------|--------|
| Scraping | Every 4 hours | :00 | Discover new leads regularly |
| Enrichment | Every 4 hours | :30 | Process scraped leads (offset 30 mins) |
| Email Outreach | 3x per day | 9am, 1pm, 5pm | Send during business hours |

## cPanel Cron Job Configuration

### 1. Lead Scraping (Every 4 Hours)

```bash
# Minute Hour Day Month Weekday Command
0 */4 * * * cd /home/fieljtgr/flaskapp && /usr/local/bin/python3 scripts/run_lead_scraping.py >> /home/fieljtgr/logs/lead_scraping.log 2>&1
```

**Schedule**: Runs at 12am, 4am, 8am, 12pm, 4pm, 8pm daily
**Log Location**: `/home/fieljtgr/logs/lead_scraping.log`

---

### 2. Lead Enrichment (Every 4 Hours, 30 Minutes After Scraping)

```bash
# Minute Hour Day Month Weekday Command
30 */4 * * * cd /home/fieljtgr/flaskapp && /usr/local/bin/python3 scripts/run_lead_enrichment.py >> /home/fieljtgr/logs/lead_enrichment.log 2>&1
```

**Schedule**: Runs at 12:30am, 4:30am, 8:30am, 12:30pm, 4:30pm, 8:30pm daily
**Log Location**: `/home/fieljtgr/logs/lead_enrichment.log`

---

### 3. Email Outreach (3 Times Daily - Business Hours)

```bash
# Minute Hour Day Month Weekday Command
0 9,13,17 * * * cd /home/fieljtgr/flaskapp && /usr/local/bin/python3 scripts/run_lead_outreach.py >> /home/fieljtgr/logs/lead_outreach.log 2>&1
```

**Schedule**: Runs at 9:00am, 1:00pm, 5:00pm daily (EST/EDT)
**Log Location**: `/home/fieljtgr/logs/lead_outreach.log`

---

## How to Add in cPanel

### Step 1: Create Log Directory

SSH into your server and create the logs directory:

```bash
mkdir -p /home/fieljtgr/logs
chmod 755 /home/fieljtgr/logs
```

### Step 2: Add Cron Jobs in cPanel

1. Log into **cPanel**
2. Navigate to **Advanced** → **Cron Jobs**
3. Under "Add New Cron Job", set:
   - **Common Settings**: Custom
   - **Minute, Hour, Day, Month, Weekday**: As specified above
   - **Command**: Copy the full command from above

4. Click **Add New Cron Job**
5. Repeat for all three jobs

---

## Alternative Schedules

### High-Frequency (For Active Lead Generation)

```bash
# Scraping - Every 2 hours
0 */2 * * * cd /home/fieljtgr/flaskapp && /usr/local/bin/python3 scripts/run_lead_scraping.py >> /home/fieljtgr/logs/lead_scraping.log 2>&1

# Enrichment - Every 2 hours (offset 20 mins)
20 */2 * * * cd /home/fieljtgr/flaskapp && /usr/local/bin/python3 scripts/run_lead_enrichment.py >> /home/fieljtgr/logs/lead_enrichment.log 2>&1

# Outreach - Every 2 hours during business hours (9am-5pm)
0 9-17/2 * * 1-5 cd /home/fieljtgr/flaskapp && /usr/local/bin/python3 scripts/run_lead_outreach.py >> /home/fieljtgr/logs/lead_outreach.log 2>&1
```

### Low-Frequency (For Budget-Conscious Usage)

```bash
# Scraping - Twice daily (8am, 4pm)
0 8,16 * * * cd /home/fieljtgr/flaskapp && /usr/local/bin/python3 scripts/run_lead_scraping.py >> /home/fieljtgr/logs/lead_scraping.log 2>&1

# Enrichment - Twice daily (9am, 5pm)
0 9,17 * * * cd /home/fieljtgr/flaskapp && /usr/local/bin/python3 scripts/run_lead_enrichment.py >> /home/fieljtgr/logs/lead_enrichment.log 2>&1

# Outreach - Once daily (10am)
0 10 * * * cd /home/fieljtgr/flaskapp && /usr/local/bin/python3 scripts/run_lead_outreach.py >> /home/fieljtgr/logs/lead_outreach.log 2>&1
```

---

## Monitoring & Logs

### View Live Logs

```bash
# Watch scraping in real-time
tail -f /home/fieljtgr/logs/lead_scraping.log

# Watch enrichment in real-time
tail -f /home/fieljtgr/logs/lead_enrichment.log

# Watch email outreach in real-time
tail -f /home/fieljtgr/logs/lead_outreach.log
```

### Check Last Run

```bash
# See last 50 lines of each log
tail -50 /home/fieljtgr/logs/lead_scraping.log
tail -50 /home/fieljtgr/logs/lead_enrichment.log
tail -50 /home/fieljtgr/logs/lead_outreach.log
```

### Log Rotation (Prevent Disk Space Issues)

Add this to crontab to rotate logs weekly:

```bash
# Rotate logs every Sunday at 2am
0 2 * * 0 find /home/fieljtgr/logs/lead_*.log -type f -exec sh -c 'mv "$1" "$1.$(date +\%Y\%m\%d)"' _ {} \; && find /home/fieljtgr/logs/lead_*.log.* -mtime +30 -delete
```

---

## Testing Cron Jobs

Before adding to cron, test each script manually:

```bash
# Test scraping
cd /home/fieljtgr/flaskapp
python3 scripts/run_lead_scraping.py

# Test enrichment
python3 scripts/run_lead_enrichment.py

# Test outreach
python3 scripts/run_lead_outreach.py
```

Each should complete without errors and show results.

---

## Troubleshooting

### Cron Job Not Running

1. Check cron is active:
   ```bash
   systemctl status cron
   ```

2. Check cron logs:
   ```bash
   grep CRON /var/log/syslog | tail -20
   ```

3. Verify Python path:
   ```bash
   which python3
   # Should output: /usr/local/bin/python3 or /usr/bin/python3
   ```

### Script Errors

1. Check if environment loads:
   ```bash
   cd /home/fieljtgr/flaskapp
   python3 scripts/run_lead_scraping.py
   ```

2. Verify .env file exists:
   ```bash
   ls -la /home/fieljtgr/.env
   ```

3. Check file permissions:
   ```bash
   chmod +x /home/fieljtgr/flaskapp/scripts/run_lead_*.py
   ```

---

## Manual Trigger (Web Interface)

You can also trigger these operations manually from the admin panel:

**URL**: https://fieldsprout.io/admin/lead-campaigns/

**Endpoints**:
- POST `/admin/lead-campaigns/trigger-scraping`
- POST `/admin/lead-campaigns/trigger-enrichment`
- POST `/admin/lead-campaigns/trigger-outreach`

---

## Daily Limits

The automation service has built-in daily limits to prevent runaway operations:

- **Campaigns Created**: 50 per day
- **Leads Enriched**: 500 per day
- **Emails Sent**: 200 per day

These reset at midnight UTC. Adjust limits in `app/services/lead_automation_service.py` if needed.

---

## Production Deployment Checklist

- [ ] Create log directory: `/home/fieljtgr/logs/`
- [ ] Test each script manually
- [ ] Verify .env file location: `/home/fieljtgr/.env`
- [ ] Add 3 cron jobs in cPanel
- [ ] Wait for first scheduled run
- [ ] Check logs for success
- [ ] Set up log rotation (optional)
- [ ] Monitor first week for any issues

---

**Documentation Created**: 2026-01-13
**Scripts Location**: `/home/fieljtgr/flaskapp/scripts/`
**Logs Location**: `/home/fieljtgr/logs/`
