# AI Agent Troubleshooting - Why No Data is Showing

## The Problem

You see **$0 saved**, **0 actions**, and **no recent changes** on:
- https://fieldsprout.io/account/google/ads/ai-change-log
- https://fieldsprout.io/account/google/ads/decision-screen

## Root Cause

The AI agents are **scheduled in crontab but failing silently** because:

### Issue #1: Wrong Flask Command
```bash
# ❌ BROKEN (what's in your crontab now)
/usr/bin/flask run-agents --layer tactical

# Problem: /usr/bin/flask doesn't exist
# Flask is only installed in your virtualenv, not system-wide
```

### Issue #2: No Error Logs
```bash
# Current cron sends output to /var/log/agents-*.log
# But these files don't exist because the command fails before logging starts
```

### Issue #3: No Database Connection
Even if Flask ran, it needs environment variables:
- `SQLALCHEMY_DATABASE_URI` - Database connection string
- `FLASK_APP` - Which app to run
- Google Ads API credentials

---

## The Solution

### Step 1: Run the Fix Script

On your production server:

```bash
cd /home/fieldsprout  # Or wherever your flaskapp is
bash fix_agent_cron.sh
```

This will:
- ✓ Detect correct paths
- ✓ Test if Flask commands work
- ✓ Show you the correct cron configuration
- ✓ Create log directories

### Step 2: Update Crontab

The script will show you the correct cron jobs. They should look like:

```bash
# Tactical agents (hourly) - Fast optimizations
0 * * * * cd /home/fieldsprout && FLASK_APP=app /home/fieldsprout/virtualenv/bin/python -m flask run-agents --layer tactical >> /home/fieldsprout/logs/agents-tactical.log 2>&1

# Operational agents (every 4 hours) - Budget/bid adjustments
0 */4 * * * cd /home/fieldsprout && FLASK_APP=app /home/fieldsprout/virtualenv/bin/python -m flask run-agents --layer operational >> /home/fieldsprout/logs/agents-operational.log 2>&1

# Strategic agents (daily at 6 AM) - Campaign structure changes
0 6 * * * cd /home/fieldsprout && FLASK_APP=app /home/fieldsprout/virtualenv/bin/python -m flask run-agents --layer strategic >> /home/fieldsprout/logs/agents-strategic.log 2>&1
```

**Key differences from broken version:**
1. Uses full path to Python in virtualenv
2. Sets `FLASK_APP=app` environment variable
3. Uses `python -m flask` instead of just `flask`
4. Logs to `~/logs/` instead of `/var/log/`

### Step 3: Test Manually

Before waiting for cron to run, test it yourself:

```bash
cd /home/fieldsprout
FLASK_APP=app virtualenv/bin/python -m flask run-agents --layer tactical
```

You should see output like:

```
============================================================
Running TACTICAL agents...
============================================================

Running agents for account 123...
✓ Connected to Google Ads (Customer ID: 123-456-7890)
✓ Analyzing keywords and search terms...
✓ Found 12 wasteful searches - adding negative keywords...
✓ Created AI action: Blocked 12 irrelevant searches ($47.50 saved)

✅ Completed for account 123

============================================================
✅ Completed: 1 succeeded, 0 failed
============================================================
```

### Step 4: Verify It Worked

After running (either manually or waiting for cron):

1. **Check logs:**
   ```bash
   tail -f /home/fieldsprout/logs/agents-tactical.log
   ```

2. **Check database:**
   ```sql
   SELECT
       action_type,
       action_description,
       estimated_monthly_savings,
       created_at
   FROM ai_actions
   WHERE status = 'executed'
   ORDER BY created_at DESC
   LIMIT 10;
   ```

3. **Check web pages:**
   - https://fieldsprout.io/account/google/ads/ai-change-log
   - https://fieldsprout.io/account/google/ads/decision-screen

   You should now see real data!

---

## What Each Agent Layer Does

### Tactical (Hourly)
**Fast, safe optimizations:**
- Add negative keywords for irrelevant searches
- Pause keywords with high spend, zero conversions
- Flag low-quality ads

**Why hourly?** Catches waste quickly, prevents bad spending

### Operational (Every 4 Hours)
**Medium-impact optimizations:**
- Adjust bids based on performance
- Reallocate budget between campaigns
- Optimize ad scheduling

**Why every 4 hours?** Enough data to make smart adjustments

### Strategic (Daily)
**Big-picture changes:**
- Create new campaigns for opportunities
- Consolidate redundant campaigns
- Major budget restructuring

**Why daily?** Needs full day of data, bigger changes need more caution

---

## Environment Variables Needed

The agents need these in your `.env` file:

```bash
# Database
SQLALCHEMY_DATABASE_URI=mysql+pymysql://user:pass@localhost/dbname

# Google Ads API
GOOGLE_ADS_DEVELOPER_TOKEN=your_dev_token
GOOGLE_ADS_CLIENT_ID=your_client_id
GOOGLE_ADS_CLIENT_SECRET=your_secret

# Flask
FLASK_APP=app
FLASK_ENV=production
```

---

## Common Errors and Fixes

### Error: "Could not locate a Flask application"
**Fix:** Add `FLASK_APP=app` before the flask command

### Error: "SQLALCHEMY_DATABASE_URI must be set"
**Fix:** Ensure `.env` file exists in your base directory with database credentials

### Error: "No module named 'app'"
**Fix:** Make sure you `cd` to the correct directory first

### Error: "Google Ads API credentials invalid"
**Fix:**
1. Check your `.env` has Google Ads credentials
2. Verify tokens haven't expired
3. Re-authenticate at https://fieldsprout.io/account/google

### Agents run but no AI actions created
**Possible reasons:**
1. **No Google Ads data** - Verify campaigns/keywords exist
2. **Already optimized** - AI found no waste to fix
3. **Thresholds too high** - AI only flags waste above certain $
4. **Short time window** - Needs at least 7 days of data

**Solution:** Check logs for what the agent analyzed:
```bash
grep -i "analyzed\|found\|created" /home/fieldsprout/logs/agents-tactical.log
```

---

## Quick Diagnosis Checklist

Run through this to identify the problem:

```bash
# 1. Can Python/Flask be found?
which python3
/home/fieldsprout/virtualenv/bin/python --version

# 2. Can Flask app load?
cd /home/fieldsprout
FLASK_APP=app /home/fieldsprout/virtualenv/bin/python -m flask --help

# 3. Is database accessible?
FLASK_APP=app /home/fieldsprout/virtualenv/bin/python -m flask shell
>>> from app import db
>>> db.session.execute('SELECT 1').scalar()
# Should return: 1

# 4. Is Google Ads connected?
SELECT * FROM google_oauth_tokens WHERE product = 'ads' LIMIT 1;

# 5. Can agents run?
FLASK_APP=app /home/fieldsprout/virtualenv/bin/python -m flask run-agents --layer tactical

# 6. Are AI actions being created?
SELECT COUNT(*) FROM ai_actions WHERE status = 'executed';

# 7. Are cron jobs running?
grep CRON /var/log/syslog | grep "flask"
# Or check: tail -f /home/fieldsprout/logs/agents-*.log
```

---

## Testing Without Waiting for Cron

Don't want to wait an hour? Run agents immediately:

```bash
# Run all agents now
cd /home/fieldsprout
FLASK_APP=app virtualenv/bin/python -m flask run-agents --all

# Or run specific layer
FLASK_APP=app virtualenv/bin/python -m flask run-agents --layer tactical

# Or run for specific account only
FLASK_APP=app virtualenv/bin/python -m flask run-agents --account 123
```

---

## Expected Results After Fix

Once cron jobs are fixed and running:

### After 1 Hour (Tactical runs)
- 5-20 negative keywords added
- 2-5 low-performing keywords paused
- $50-200 monthly waste prevented

### After 4 Hours (Operational runs)
- 3-10 bid adjustments
- 1-3 budget reallocations
- $100-500 optimization impact

### After 1 Day (Strategic runs)
- 0-2 campaigns created/consolidated
- Major budget restructuring if needed
- $500+ impact for major changes

### On Web Pages
- **AI Change Log**: Shows all actions with timestamps and savings
- **Decision Screen**: Shows recent changes timeline
- **Summary Stats**: Total saved, total actions, optimizations

---

## Summary

**The Problem:** Cron jobs use wrong paths, agents never actually run

**The Fix:** Use correct virtualenv Python path and set FLASK_APP

**How to Fix:**
1. Run `bash fix_agent_cron.sh`
2. Update crontab with correct commands
3. Test manually first
4. Check logs and database
5. Verify on web pages

**After Fix:**
- AI agents run automatically every hour/4 hours/day
- Create AI actions in database
- Show real data on AI Change Log and Decision Screen
- Actually prevent wasted ad spend!

---

## Need Help?

If you've fixed the cron jobs but still not seeing data:

1. Share the output of: `bash fix_agent_cron.sh`
2. Share last 50 lines of: `tail -50 /home/fieldsprout/logs/agents-tactical.log`
3. Share SQL result: `SELECT COUNT(*) FROM ai_actions;`
4. Share specific keywords you think are wasteful

Then we can diagnose why agents aren't finding optimizations.
