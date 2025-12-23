# Lead Automation - Command Reference

## Shell Script (Recommended)

### 1. Make the script executable:
```bash
chmod +x /home/fieljtgr/flaskapp/run_daily_automation.sh
```

### 2. Run manually:
```bash
/home/fieljtgr/flaskapp/run_daily_automation.sh
```

### 3. View logs:
```bash
tail -f /home/fieljtgr/flaskapp/logs/automation.log
```

---

## One-Liner for Terminal

**IMPORTANT:** Replace placeholder values with your actual credentials before running!

```bash
cd /home/fieljtgr/flaskapp && \
export EMAIL_PROVIDER="brevo" && \
export BREVO_API_KEY="YOUR_BREVO_API_KEY" && \
export BREVO_FROM_EMAIL="your-email@fieldsprout.io" && \
export BREVO_FROM_NAME="Your Name" && \
export SERPAPI_API_KEY="YOUR_SERPAPI_KEY" && \
export SQLALCHEMY_DATABASE_URI="mysql+pymysql://username:password@localhost/database?charset=utf8mb4" && \
/home/fieljtgr/virtualenv/flaskapp/3.9/bin/python -m flask run-lead-automation >> /home/fieljtgr/flaskapp/logs/automation.log 2>&1
```

---

## Cron Job Entry

### Daily at 9 AM:
```bash
0 9 * * * /home/fieljtgr/flaskapp/run_daily_automation.sh
```

### To install:
```bash
crontab -e

# Add this line:
0 9 * * * /home/fieljtgr/flaskapp/run_daily_automation.sh
```

---

## Alternative: Run with Python Script Directly

**IMPORTANT:** Replace placeholder values with your actual credentials before running!

```bash
cd /home/fieljtgr/flaskapp && \
export EMAIL_PROVIDER="brevo" && \
export BREVO_API_KEY="YOUR_BREVO_API_KEY" && \
export BREVO_FROM_EMAIL="your-email@fieldsprout.io" && \
export BREVO_FROM_NAME="Your Name" && \
export SERPAPI_API_KEY="YOUR_SERPAPI_KEY" && \
export SQLALCHEMY_DATABASE_URI="mysql+pymysql://username:password@localhost/database?charset=utf8mb4" && \
/home/fieljtgr/virtualenv/flaskapp/3.9/bin/python3 run_automation.py >> /home/fieljtgr/flaskapp/logs/automation.log 2>&1
```

---

## View Logs

```bash
# View entire log
cat /home/fieljtgr/flaskapp/logs/automation.log

# Follow log in real-time
tail -f /home/fieljtgr/flaskapp/logs/automation.log

# View last 100 lines
tail -100 /home/fieljtgr/flaskapp/logs/automation.log

# View last successful run
grep -A 20 "AUTOMATION COMPLETE" /home/fieljtgr/flaskapp/logs/automation.log | tail -25
```

---

## Troubleshooting

### If automation fails to run:

1. **Check script permissions:**
   ```bash
   ls -la /home/fieljtgr/flaskapp/run_daily_automation.sh
   # Should show: -rwxr-xr-x (executable)
   ```

2. **Test environment variables:**
   ```bash
   /home/fieljtgr/flaskapp/run_daily_automation.sh
   echo $?  # Should be 0 on success
   ```

3. **Check Flask CLI command is available:**
   ```bash
   /home/fieljtgr/virtualenv/flaskapp/3.9/bin/python -m flask --help | grep run-lead-automation
   ```

4. **Verify logs directory exists:**
   ```bash
   mkdir -p /home/fieljtgr/flaskapp/logs
   chmod 755 /home/fieljtgr/flaskapp/logs
   ```

---

## Environment Variables Configured

- ✅ **EMAIL_PROVIDER:** brevo
- ✅ **BREVO_API_KEY:** (configured)
- ✅ **BREVO_FROM_EMAIL:** brian.cohen@fieldsprout.io
- ✅ **BREVO_FROM_NAME:** Brian from FieldSprout
- ✅ **SERPAPI_API_KEY:** (configured)
- ✅ **SQLALCHEMY_DATABASE_URI:** mysql+pymysql://fieljtgr_team:***@localhost/fieljtgr_xyz

---

## Expected Output

```
========================================
LEAD GENERATION AUTOMATION
========================================

📊 Current Progress:
   Campaigns: 5/100
   Progress: 5.0%
   Leads Enriched: 150
   Emails Sent: 75
   Unique Domains: 120

📅 Today's Activity (2025-12-23):
   Scrapes: 0/50
   Enrichments: 0/100
   Emails: 0/250

========================================

🚀 Starting automation cycle...

[Automation runs...]

========================================
✅ AUTOMATION COMPLETE
========================================
   Campaigns Scraped: 5
   Leads Enriched: 20
   Emails Sent: 35

📈 Total Progress:
   Total Campaigns: 10
   Total Emails: 110
========================================
```
