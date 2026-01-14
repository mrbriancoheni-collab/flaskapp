# Google Ads Auto-Executor Deployment Guide

## 🎯 What This Enables

**Automatic 24/7 Budget Protection** for all your Google Ads customers:

✅ **Auto-blocks non-purchase intent searches** (jobs, DIY, how-to, reviews, etc.)
✅ **Runs every 4 hours** to catch wasteful spend quickly
✅ **Full transparency** - every action logged and visible in UI
✅ **One-click undo** - customers can reverse any action
✅ **Safety limits** - max 100 negative keywords/day per account

---

## 📋 Deployment Steps

### Step 1: Download Updated File from GitHub

1. Go to your repository: `mrbriancoheni-collab/flaskapp`
2. Switch to branch: `claude/limit-scraping-campaigns-0JNOv`
3. Navigate to: `flaskapp/app/background_jobs.py`
4. Click "Raw" and save the file

### Step 2: Upload to Production

1. Login to cPanel File Manager
2. Navigate to: `/home/fieljtgr/flaskapp/app/`
3. Upload the new `background_jobs.py` file (replace existing)
4. Verify file permissions: `chmod 644 background_jobs.py`

### Step 3: Restart Gunicorn

SSH into your server and run:

```bash
cd /home/fieljtgr/flaskapp
./restart_gunicorn.sh
```

Or manually:

```bash
./stop_gunicorn.sh
./start_gunicorn.sh
```

### Step 4: Verify Job is Running

Check the logs to see the new job registered:

```bash
tail -50 /home/fieljtgr/flaskapp/logs/gunicorn_error.log | grep "Registered 11 scheduled"
```

You should see: `Registered 11 scheduled background jobs` (was 10 before)

### Step 5: Manually Test the Job (Optional)

To test immediately without waiting 4 hours:

```bash
cd /home/fieljtgr/flaskapp
source /home/fieljtgr/virtualenv/flaskapp/3.9/bin/activate

# Run Python shell
python3

# In Python:
from app import create_app
from app.background_jobs import run_google_ads_auto_executor

app = create_app()
run_google_ads_auto_executor(app)
```

This will run the auto-executor once for all accounts and show you the results.

---

## 🔍 How to Verify It's Working

### Check the Logs

```bash
tail -100 /home/fieljtgr/flaskapp/logs/gunicorn_error.log | grep "Auto-Executor"
```

Look for messages like:
```
[JOB] Starting Google Ads Auto-Executor for all accounts
Account 3: Created 5 negative keyword actions
[JOB] Google Ads Auto-Executor complete: 5 actions created, 1 accounts succeeded, 0 errors
```

### Check the Database

```bash
mysql -u fieljtgr_team -p fieljtgr_xyz

SELECT COUNT(*) FROM ai_actions WHERE action_type = 'negative_keyword_added';
SELECT * FROM ai_actions ORDER BY created_at DESC LIMIT 5;
```

### Check the UI

1. Login to your account
2. Go to: https://fieldsprout.io/account/google/ads/decision-screen
3. Scroll to "What Changed?" timeline
4. You should see blocked search terms listed

---

## 📊 What Gets Logged

Every negative keyword addition creates an `AIAction` record with:

- **Exact search term** blocked (e.g., "plumber jobs")
- **Campaign & ad group** affected
- **Estimated monthly savings** calculated from historical data
- **Confidence score** (85%+ required to execute)
- **Reasoning** with matched patterns (e.g., "Matches 'jobs', 'career'")
- **Before/after values** for undo capability

Example action:
```json
{
  "title": "Block Non-Purchase Intent: 'plumber jobs near me'",
  "description": "Detected non-purchase intent based on patterns: job, jobs, near. This term has spent $45.20 with 0 conversions.",
  "reasoning": "Search term matches non-purchase intent patterns: job, jobs. Historical performance shows 0% conversion rate with $45.20 spend over 30 days.",
  "estimated_monthly_savings": 45.20,
  "confidence_score": 0.92,
  "action_type": "negative_keyword_added"
}
```

---

## 🔐 Safety Features

### Daily Limits
- Max 100 negative keywords per account per day
- Prevents runaway automation
- Logged in error log if limit hit

### Confidence Threshold
- Only executes if confidence >= 85%
- Based on pattern matching + historical performance
- Lower confidence = action created but not executed

### Undo Capability
- Every action can be undone with one click
- Reverts the negative keyword in Google Ads
- Updates AIAction status to 'undone'

---

## 📈 Customer Impact

Your customers will see:

### In Decision Screen
- **AI Actions Taken** count increases
- **Wasted Spend Prevented** dollar amount grows
- **Blocked Searches** count shows how many bad keywords caught

### In AI Change Log
- Full list of all actions taken
- Ability to undo any action
- Detailed reasoning for each decision

### In Email (if enabled)
- Weekly summary of budget protection
- List of top blocked search terms
- Total savings achieved

---

## 🛠️ Troubleshooting

### Job Not Running

Check if scheduler is active:
```bash
ps aux | grep gunicorn | grep -v grep
tail -50 /home/fieljtgr/flaskapp/logs/gunicorn_error.log | grep scheduler
```

### No Actions Being Created

Possible reasons:
1. No non-purchase intent search terms in last 30 days
2. All bad terms already added as negative keywords
3. Daily limit reached (check logs)
4. Google Ads API credentials expired

Check:
```bash
tail -200 /home/fieljtgr/flaskapp/logs/gunicorn_error.log | grep -A 5 "Auto-Executor"
```

### Actions Created But Not Executed

Check the `ai_actions` table:
```sql
SELECT status, COUNT(*) FROM ai_actions
WHERE action_type = 'negative_keyword_added'
GROUP BY status;
```

If status = 'pending' instead of 'executed', check error messages in the action records.

---

## 📅 Schedule

The auto-executor runs **every 4 hours**:
- 12:00 AM UTC
- 4:00 AM UTC
- 8:00 AM UTC
- 12:00 PM UTC
- 4:00 PM UTC
- 8:00 PM UTC

This catches wasteful spend quickly without overwhelming the Google Ads API.

---

## 🚀 Future Enhancements

The auto-executor is designed to be extended with:

1. **Auto-pause low performers** - Pause keywords with low CTR/conversion rate
2. **Auto-bid adjustments** - Increase bids on high converters, decrease on low
3. **Auto-budget reallocation** - Move budget from underperformers to winners
4. **Email notifications** - Daily summary of actions taken
5. **Custom rules per account** - Let customers configure their own thresholds

All of these use the same AIAction logging and undo infrastructure.

---

## ✅ Deployment Complete!

After completing these steps, your platform will automatically protect customer budgets 24/7 by blocking non-purchase intent searches. Customers can see every action in their dashboard with full transparency and control.
