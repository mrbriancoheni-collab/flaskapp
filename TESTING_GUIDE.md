# Lead Generation Automation - Testing Guide

## ✅ Pre-Flight Checklist

Before testing, verify these are ready:

### 1. Environment Variables
Check that these are set in your environment:
```bash
echo $SERPAPI_API_KEY     # Should show your SerpAPI key
echo $MAILGUN_API_KEY     # Should show your Mailgun key
echo $MAILGUN_DOMAIN      # Should show your domain
```

If any are missing, add them to your `.env` file or environment.

### 2. Database Connection
Your Flask app should be running and connected to the database.

### 3. Email Sequences
Create at least one email sequence before running automation:
- Go to: https://fieldsprout.io/admin/lead-campaigns/sequences/new
- Create a Step 1 email template
- This will be used for all campaigns

---

## 🧪 Testing Steps

### Step 1: Check Current Status

**Via Web Dashboard:**
1. Go to: https://fieldsprout.io/admin/lead-campaigns/
2. Look at the automation status widget at the top
3. Should show:
   - Campaigns Created: 0 (initially)
   - Progress: 0%
   - Today's Activity: 0/50, 0/100, 0/250

**Expected Result:** Dashboard loads successfully with automation widget visible.

---

### Step 2: Dry Run Test

Run a test without making changes:

```bash
cd /home/user/flaskapp
flask run-lead-automation --dry-run
```

**Expected Output:**
```
================================================================================
LEAD GENERATION AUTOMATION
================================================================================

Current Progress:
  Total Campaigns Planned: 4500
  Campaigns Created: 0
  Campaigns Scraped: 0
  Progress: 0.0%
  Leads Enriched: 0
  Emails Sent: 0
  Unique Domains: 0

Daily Stats (2025-12-02):
  Scrapes: 0
  Enrichments: 0
  Emails: 0
```

**Expected Result:** Shows current status without errors.

---

### Step 3: Run First Campaign (Small Test)

Now let's run the automation for real, but just 1 campaign to test:

```bash
cd /home/user/flaskapp

# Run the automation
flask run-lead-automation
```

**What Should Happen:**

1. **Campaign Creation**
   ```
   Created campaign: Auto: plumber - New York, NY
   ```

2. **Scraping**
   ```
   Scraping SERP for query='plumber New York, NY' location='New York, NY'
   Scraped campaign Auto: plumber - New York, NY: 15 new leads
   ```

3. **Summary**
   ```
   Results:
     Campaigns Scraped: 1
     Leads Enriched: 0
     Emails Sent: 0

   Total Progress:
     Total Campaigns: 1
     Total Emails: 0

   AUTOMATION COMPLETE
   ```

**Expected Result:**
- 1 campaign created
- 10-20 leads scraped
- No errors

---

### Step 4: Verify in Dashboard

Go back to: https://fieldsprout.io/admin/lead-campaigns/

**You should see:**

**Automation Widget (top):**
- Campaigns Created: 1
- Progress: 0.02% (1/4500)
- Today's Activity: 1/50 scrapes

**Campaign List (below):**
- New campaign: "Auto: plumber - New York, NY"
- Status: "READY"
- Leads Scraped: 10-20 (varies)
- Click "View" to see the leads

**Expected Result:** Dashboard shows updated numbers.

---

### Step 5: Check the Leads

Click on the campaign to view leads:

**You should see:**
- List of businesses (plumbers in NYC)
- Company names
- Websites
- Phone numbers
- Source type (ads, maps, lsa, organic)
- Enrichment status: "pending"

**Expected Result:** Leads display correctly with all data.

---

### Step 6: Test Enrichment

Run automation again to enrich the leads:

```bash
flask run-lead-automation
```

**What Should Happen:**

1. **Scraping:** Creates 1 more campaign (up to daily limit of 50)
2. **Enrichment:** Enriches up to 100 leads from previous campaign
   ```
   Enriched lead: ABC Plumbing with 3 contacts
   Enriched lead: XYZ Plumbing with 2 contacts
   ```

**Expected Result:**
- Another campaign scraped
- Some leads enriched with contact info

---

### Step 7: Verify Enrichment

Go to campaign view and check leads:

**You should see:**
- Enrichment Status: "completed" (for some leads)
- Decision Maker Name: Found
- Decision Maker Email: Found
- Contact details populated

**Expected Result:** Lead enrichment data appears.

---

### Step 8: Install Cron Job

If everything works, install the cron job:

```bash
cd /home/user/flaskapp
./setup_cron.sh
```

**You should see:**
```
================================================
Lead Generation Automation - Cron Setup
================================================

Configuration:
  App Directory: /home/user/flaskapp
  Log File: /home/user/flaskapp/logs/automation.log
  Flask Command: flask

Cron Job to be added:
  Schedule: Daily at 9:00 AM
  Command: cd /home/user/flaskapp && flask run-lead-automation
  Log: /home/user/flaskapp/logs/automation.log

✓ Cron job installed successfully!
```

Verify it was added:
```bash
crontab -l
```

Should show:
```
0 9 * * * cd /home/user/flaskapp && flask run-lead-automation >> /home/user/flaskapp/logs/automation.log 2>&1
```

**Expected Result:** Cron job installed successfully.

---

## 📊 Success Indicators

✅ **All Tests Pass If:**

1. Dashboard loads with automation widget
2. Dry run shows status without errors
3. First campaign creates successfully
4. Leads are scraped (10-20 per campaign)
5. Dashboard updates with correct numbers
6. Enrichment finds contact information
7. Cron job installs without errors

---

## ⚠️ Common Issues & Solutions

### Issue 1: "SERPAPI_API_KEY not configured"

**Solution:**
```bash
# Add to .env file
echo "SERPAPI_API_KEY=your_key_here" >> .env

# Or export in environment
export SERPAPI_API_KEY=your_key_here
```

### Issue 2: "400 Bad Request" from SerpAPI

**Cause:** Invalid search query (like "All US")

**Solution:** The validation prevents this now. If you see this:
1. Check the campaign's industry_service and location fields
2. Make sure they're specific (e.g., "plumber" and "Dallas, TX")
3. Edit the campaign to fix invalid values

### Issue 3: No leads found

**Cause:**
- SerpAPI might not return results for that query
- Daily limit might be reached

**Solution:**
1. Check SerpAPI dashboard for quota
2. Try a different city/keyword combination
3. Check logs for specific errors

### Issue 4: Enrichment fails

**Cause:**
- No website found for lead
- Enrichment service error

**Solution:**
1. Check that leads have websites
2. Review enrichment service logs
3. Some leads will fail - that's normal

### Issue 5: Automation widget shows all zeros

**Cause:**
- Automation hasn't run yet
- State file doesn't exist

**Solution:**
1. Run `flask run-lead-automation` once
2. Refresh the dashboard
3. Check `/home/user/flaskapp/automation_state.json` exists

### Issue 6: Cron job doesn't run

**Cause:**
- Cron service not running
- Wrong path in cron job
- Environment variables not available to cron

**Solution:**
```bash
# Check cron service
sudo systemctl status cron

# Check cron logs
grep CRON /var/log/syslog

# Make sure environment is loaded in cron job
```

---

## 📈 What to Monitor

### Daily
1. Check dashboard at: https://fieldsprout.io/admin/lead-campaigns/
2. Watch "Today's Activity" numbers
3. Look for campaigns in "READY" status

### Weekly
1. Review overall progress percentage
2. Check email open rates
3. Review failed enrichments

### View Logs
```bash
# Live logs
tail -f /home/user/flaskapp/logs/automation.log

# Today's activity
grep "$(date +%Y-%m-%d)" /home/user/flaskapp/logs/automation.log

# Errors only
grep ERROR /home/user/flaskapp/logs/automation.log
```

---

## 🎯 Expected Timeline

At default daily limits:

- **Day 1:** 50 campaigns, ~750 leads scraped
- **Week 1:** 350 campaigns, ~5,250 leads
- **Month 1:** 1,500 campaigns, ~22,500 leads
- **Day 90:** All 4,500 campaigns complete

Daily operations:
- **Scraping:** 50 campaigns/day
- **Enrichment:** 100 leads/day
- **Emails:** 250/day (skip Sundays)

---

## ✅ Test Complete Checklist

Mark each as you complete:

- [ ] Dashboard loads successfully
- [ ] Dry run completes without errors
- [ ] First campaign created
- [ ] Leads scraped successfully
- [ ] Dashboard shows updated numbers
- [ ] Leads appear in campaign view
- [ ] Enrichment runs and finds contacts
- [ ] Cron job installed
- [ ] Verified cron with `crontab -l`
- [ ] Know how to view logs

---

## 🚀 You're Ready!

Once all tests pass:

1. ✅ Automation is working
2. ✅ Cron job will run daily at 9 AM
3. ✅ Dashboard shows real-time progress
4. ✅ System will run for ~90 days to complete

Monitor progress at: https://fieldsprout.io/admin/lead-campaigns/

---

## 📞 Support Commands

```bash
# Check current status
flask run-lead-automation --dry-run

# Run manually
flask run-lead-automation

# View logs
tail -f logs/automation.log

# Check state
cat automation_state.json

# List cron jobs
crontab -l

# Edit cron jobs
crontab -e
```

---

**Next Steps:** Set up email sequences, customize templates, monitor results!
