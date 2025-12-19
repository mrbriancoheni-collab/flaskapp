# Lead Automation Not Running - Diagnosis

## Status Check

**Automation State:** `automation_state.json` shows:
```json
{
  "last_run": null,
  "campaigns_created": 0,
  "campaigns_scraped": 0,
  "leads_enriched": 0,
  "emails_sent": 0
}
```

**Cron Job:** EXISTS but running WRONG COMMAND
- ❌ Current: `send-pending-emails`
- ✅ Needed: `run-lead-automation`

---

## Why Automation Hasn't Run

The cron job is scheduled for **9:00 AM daily**, but it's only sending emails to already-enriched leads. It's NOT:
- Creating new campaigns
- Scraping leads from Google
- Enriching leads with contact info

Since there are no enriched leads yet, the `send-pending-emails` command has nothing to send.

---

## The Fix (Already Provided)

Update cron job command from:
```bash
/home/fieljtgr/virtualenv/flaskapp/3.9/bin/python -m flask send-pending-emails
```

To:
```bash
/home/fieljtgr/virtualenv/flaskapp/3.9/bin/python -m flask run-lead-automation
```

---

## Manual Test (Run This Now)

Don't wait until 9 AM tomorrow. Test the automation manually via SSH:

```bash
# Dry run (preview only, makes no changes)
# Note: Replace with your actual API keys and database credentials
cd /home/fieljtgr/flaskapp && \
export EMAIL_PROVIDER="brevo" && \
export BREVO_API_KEY="YOUR_BREVO_API_KEY" && \
export BREVO_FROM_EMAIL="hi@fieldsprout.io" && \
export BREVO_FROM_NAME="FieldSprout" && \
export SERPAPI_API_KEY="YOUR_SERPAPI_KEY" && \
export SQLALCHEMY_DATABASE_URI="mysql+pymysql://USERNAME:PASSWORD@localhost/DATABASE?charset=utf8mb4" && \
/home/fieljtgr/virtualenv/flaskapp/3.9/bin/python -m flask run-lead-automation --dry-run
```

This will show you:
- How many campaigns will be created
- Current progress stats
- Daily limits status
- What would happen (without actually doing it)

---

## Check Logs

View the automation log to see if there were any previous attempts:

```bash
tail -100 /home/fieljtgr/flaskapp/logs/automation.log
```

Or check errors:
```bash
grep -i error /home/fieljtgr/flaskapp/logs/automation.log
```

---

## Verify After Fix

After updating the cron job and it runs (tomorrow at 9 AM or manually now), verify:

**1. Check automation state:**
```bash
cat /home/fieljtgr/flaskapp/automation_state.json
```

Should show:
```json
{
  "last_run": "2025-12-19T09:00:00",  ← Not null!
  "campaigns_created": 5,             ← Greater than 0
  "campaigns_scraped": 5,
  "leads_enriched": 10,
  "emails_sent": 25
}
```

**2. Check database for new leads:**
```sql
-- Count campaigns created today
SELECT COUNT(*) FROM lead_campaigns
WHERE DATE(created_at) = CURDATE();

-- Count leads scraped today
SELECT COUNT(*) FROM leads
WHERE DATE(created_at) = CURDATE();

-- Count leads enriched today
SELECT COUNT(*) FROM leads
WHERE DATE(enriched_at) = CURDATE();

-- Count emails sent today
SELECT COUNT(*) FROM lead_contact_emails
WHERE DATE(sent_at) = CURDATE();
```

**3. Check logs:**
```bash
tail -f /home/fieljtgr/flaskapp/logs/automation.log
```

Should show:
```
STARTING DAILY LEAD AUTOMATION
Scraped 5 campaigns today
Enriched 10 leads today
Sent 25 emails today
DAILY AUTOMATION COMPLETE
```

---

## Expected Daily Progress

Once running correctly, automation will create:

| Metric | Daily Limit | Progress |
|--------|-------------|----------|
| Campaigns Scraped | 50/day | ~100 campaigns total |
| Leads Enriched | 100/day | Growing database |
| Emails Sent | 250/day | Active outreach |

At this rate:
- **First week:** ~350 campaigns, ~700 enriched leads, ~1,750 emails
- **First month:** ~1,500 campaigns, ~3,000 enriched leads, ~7,500 emails

---

## Next Steps

1. ✅ **Update cron job** (change `send-pending-emails` to `run-lead-automation`)
2. ✅ **Test manually** (run the dry-run command above)
3. ⏳ **Wait for 9 AM** (or run full automation manually without `--dry-run`)
4. ✅ **Verify results** (check automation_state.json and database)

---

## Common Issues

### Issue: "No module named flask"
**Fix:** Make sure you're using the correct Python path:
```bash
/home/fieljtgr/virtualenv/flaskapp/3.9/bin/python
```

### Issue: "SERPAPI_API_KEY not set"
**Fix:** Your cron job already sets this. If running manually, use the full export commands above.

### Issue: "Daily limit reached"
**Fix:** This is normal if you've hit the daily scraping limit (50 campaigns). Check tomorrow.

### Issue: Automation runs but state file shows 0
**Fix:** Check permissions on automation_state.json:
```bash
ls -la /home/fieljtgr/flaskapp/automation_state.json
chmod 664 /home/fieljtgr/flaskapp/automation_state.json
```

---

## Summary

**Problem:** Cron job runs wrong command
**Solution:** Update to `run-lead-automation`
**Test:** Run manual dry-run first
**Verify:** Check state file and database after running
