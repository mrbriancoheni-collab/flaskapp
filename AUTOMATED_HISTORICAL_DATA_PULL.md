# Automated Historical Data Pull

## Overview

FieldSprout now includes **automated historical data pulling** from all connected APIs. Instead of manually importing data, the system pulls the last 12 months directly from:

- Google Ads API
- Facebook Ads Graph API
- Google Analytics API
- Google Search Console API
- GLSA (from leads database)
- GMB (coming soon)

This establishes a baseline for Year-over-Year (YoY) analysis to prove ROI.

---

## How It Works

### The Magic ✨

1. **You connect your channels** (Google Ads, Facebook Ads, etc.)
2. **Click one button** or run one command
3. **System automatically pulls** last 12 months from each API
4. **Data is stored** in `performance_metrics` table
5. **YoY analysis enabled** - compare this month to last year

### What Gets Pulled

**Google Ads:**
- Daily campaign performance
- Impressions, clicks, cost, conversions
- Last 12 months

**Facebook Ads:**
- Daily account/campaign insights
- Spend, impressions, clicks, leads
- Last 12 months

**Google Analytics:**
- Daily site metrics
- Sessions, pageviews, bounce rate, goals
- Last 12 months

**Google Search Console:**
- Daily search performance
- Impressions, clicks, CTR, position
- Last 12 months

**GLSA:**
- Daily lead counts from your database
- Grouped by date

---

## Three Ways to Pull Historical Data

### Method 1: Admin Panel (Easiest) 🎯

**Steps:**
1. Go to `/admin/performance-metrics`
2. Select account from dropdown
3. Choose number of months (default: 12)
4. Click "Pull Historical Data"
5. Wait 2-5 minutes (depending on data volume)
6. Done! Data is now available for YoY analysis

**When to use:**
- First time setup
- Adding a new channel
- Filling gaps in data
- Non-technical users

### Method 2: Flask CLI Command (Recommended for automation)

**Interactive mode:**
```bash
flask pull-historical-data

# You'll be prompted for:
# - Account ID: 1
# - Number of months: 12
# - Force re-import: No

# Output:
# 🔄 Pulling 12 months of historical data for account 1...
# This may take a few minutes...
#
# ============================================================
# ✅ Historical Data Pull Complete!
# ============================================================
# Period: 2024-10-23 to 2025-10-23
# Total records imported: 365
#
# Results by channel:
#   ✅ google_ads           :  365 records
#   ✅ fbads                :  365 records
#   ❌ google_analytics     :    0 records (Error: Not connected)
#   ✅ search_console       :  365 records
#   ✅ glsa                 :  248 records
#   ❌ gmb                  :    0 records (Error: Not yet implemented)
```

**Check what data you already have:**
```bash
flask check-historical-data

# Output:
# 📊 Historical Data Status for Account 1
# ============================================================
# ✅ google_ads           :   365 records (2024-10-23 to 2025-10-23)
# ✅ fbads                :   365 records (2024-10-23 to 2025-10-23)
# ❌ google_analytics     : No data
# ✅ search_console       :   365 records (2024-10-23 to 2025-10-23)
# ✅ glsa                 :   248 records (2024-12-01 to 2025-10-23)
# ❌ gmb                  : No data
```

**When to use:**
- Scheduled cron jobs
- During deployment
- Bulk operations
- Server administration

### Method 3: Python Code (For custom scripts)

```python
from app.services.historical_data_pull import pull_all_historical_data

# Pull 12 months for account 1
results = pull_all_historical_data(
    account_id=1,
    months=12,
    force=False  # Skip existing data
)

print(f"Imported {results['total_imported']} records")

# Pull specific channel only
from app.services.historical_data_pull import pull_google_ads_historical
import datetime as dt

result = pull_google_ads_historical(
    account_id=1,
    start_date=dt.date(2024, 1, 1),
    end_date=dt.date(2024, 12, 31),
    force=False
)

print(f"Google Ads: {result['imported']} records")
```

**When to use:**
- Custom automation scripts
- Integration with other systems
- Advanced use cases

---

## API Requirements

### What You Need Connected

For each channel you want historical data from, you need:

**Google Ads:**
- ✅ OAuth connected
- ✅ `GoogleAdsAuth` record in database
- ✅ Valid refresh token
- ✅ Customer ID configured

**Facebook Ads:**
- ✅ Facebook App connected
- ✅ Access token in `facebook_tokens` table
- ✅ Ad account access

**Google Analytics:**
- ✅ OAuth connected
- ✅ `GoogleAnalyticsAuth` record
- ✅ View ID configured

**Google Search Console:**
- ✅ OAuth connected
- ✅ `GoogleSearchConsoleAuth` record
- ✅ Site URL verified

**GLSA:**
- ✅ Leads in `crm_contacts` table with `source='glsa'`

---

## Data Storage

All historical data is stored in the `performance_metrics` table:

```sql
SELECT
  source_type,
  date,
  impressions,
  clicks,
  spend,
  conversions
FROM performance_metrics
WHERE account_id = 1
  AND source_type = 'google_ads'
  AND date >= '2024-10-01'
ORDER BY date;
```

**Fields stored:**
- `account_id` - Which account
- `source_type` - Which channel (google_ads, fbads, etc.)
- `source_id` - Customer ID, Page ID, etc.
- `date` - Date of metrics
- `impressions`, `clicks`, `spend`, `conversions` - Quick access fields
- `metrics_json` - Full metrics in flexible JSON format

---

## Performance & Timing

**Expected duration:**
- Google Ads (12 months): ~2-3 minutes
- Facebook Ads (12 months): ~1-2 minutes
- Google Analytics (12 months): ~2-3 minutes
- Search Console (12 months): ~3-5 minutes
- GLSA (all time): ~10 seconds
- **Total for all channels: 5-10 minutes**

**Factors affecting speed:**
- Volume of campaigns/data
- API rate limits
- Network latency
- Database write speed

**Best practices:**
- Run during off-peak hours
- Use `force=false` to skip existing data
- Monitor logs for errors
- Start with smaller date ranges if issues occur

---

## Troubleshooting

### "Error: Not connected"

**Cause:** Channel not connected for this account

**Fix:**
1. Go to account dashboard
2. Click "Connect" for the channel
3. Complete OAuth flow
4. Try pull again

### "Error: Invalid grant"

**Cause:** OAuth refresh token expired

**Fix:**
1. Disconnect and reconnect the channel
2. Complete OAuth flow again
3. New refresh token will be stored

### "Error: API quota exceeded"

**Cause:** Hit API rate limits

**Fix:**
1. Wait 24 hours for quota to reset
2. Pull smaller date ranges
3. Contact Google/Facebook to increase quota

### No data returned (0 records)

**Possible causes:**
1. Account has no activity in that period
2. Campaigns were paused/deleted
3. Wrong customer ID or property ID
4. Permissions issue

**Fix:**
- Check account actually has data for that period
- Verify customer ID / property ID is correct
- Check OAuth scopes include historical data access

---

## Automation Ideas

### Cron Job (Daily)

Pull yesterday's data automatically:

```bash
# Add to crontab
0 2 * * * cd /path/to/app && flask pull-historical-data --account-id 1 --months 0 --days 1
```

### On New Account Signup

```python
# In your account creation code
from app.services.historical_data_pull import pull_all_historical_data

def after_account_created(account_id):
    # Pull 12 months of historical data in background
    pull_all_historical_data(account_id, months=12)
```

### Scheduled Task (Weekly)

```python
# In your scheduler
@scheduler.task('cron', day_of_week='sun', hour=3)
def weekly_historical_backfill():
    """Backfill any missing data weekly"""
    accounts = Account.query.filter_by(active=True).all()
    for account in accounts:
        pull_all_historical_data(account.id, months=1, force=False)
```

---

## What's Next?

After pulling historical data:

1. **View YoY reports** - Compare this month to last year
2. **See trends** - Month-by-month performance charts
3. **Prove ROI** - Show improvement after using FieldSprout
4. **Better AI insights** - AI can analyze patterns over time

See `yoy_analysis.py` for functions to generate YoY comparisons.

---

## FAQ

**Q: Will this overwrite my existing data?**
A: No, by default (`force=false`) it skips dates that already have data. Use `force=true` to overwrite.

**Q: Can I pull more than 12 months?**
A: Yes! Set `months=24` or any number. Note: Some APIs limit historical data (e.g., Facebook typically allows 2 years).

**Q: Does this cost money (API calls)?**
A: Google Ads API calls are free within daily quota. Facebook Graph API is free. Google Analytics has free tier. You should be fine for typical usage.

**Q: What if I connect a new channel later?**
A: Just run the pull again for that account. It will fetch data for newly connected channels.

**Q: Can I pull data for multiple accounts at once?**
A: Use a script to loop through accounts:
```python
for account_id in [1, 2, 3, 4, 5]:
    pull_all_historical_data(account_id, months=12)
```

**Q: How do I know if it worked?**
A: Run `flask check-historical-data` to see what data exists.

---

## Summary

✅ **Before:** Manual CSV imports, no historical context
✅ **Now:** One-click automatic pull from all APIs
✅ **Result:** Complete 12-month baseline for YoY analysis

**Get started:**
1. Run database migration (create `performance_metrics` table)
2. Connect your channels (Google Ads, FB Ads, etc.)
3. Go to `/admin/performance-metrics` and click "Pull Historical Data"
4. Wait 5-10 minutes
5. View YoY reports!

That's it! 🎉
