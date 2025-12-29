# Production Server Setup Checklist

Your production server is experiencing 503 errors due to misconfigured Python paths. Follow this checklist to get everything working.

## ✅ Critical Fixes (Do These First)

### 1. Fix LiteSpeed WSGI Paths ⚠️ BLOCKING ISSUE
**Problem**: LiteSpeed looking for Python 3.9 at wrong paths, causing 503 errors and 0 worker processes

**Solution**: See detailed steps in `FIX_PRODUCTION_LSWSGI_PATHS.md`

**Quick version**:
```bash
# On production server, edit LiteSpeed config
sudo nano /usr/local/lsws/conf/httpd_config.xml

# Find <extProcessor> section and update paths:
# OLD: /opt/alt/python39/bin/lswsgi
# NEW: /home/fieljtgr/bin/lswsgi
#
# OLD: /home/fieljtgr/virtualenv/flaskapp/3.9/lib/python3.9/site-packages
# NEW: /home/fieljtgr/lib/python3.10/site-packages

# Restart LiteSpeed
sudo systemctl restart lsws

# Verify workers started
ps aux | grep lswsgi | wc -l
# Should show 35+ processes
```

**Status**: ⏳ PENDING

---

### 2. Sync Latest Code to Production
**Problem**: Production may be running old code without recent fixes

**Solution**: See detailed steps in `SYNC_TO_PRODUCTION.md`

**Quick version**:
```bash
# If /home/fieljtgr/flaskapp is a git repo:
cd /home/fieljtgr/flaskapp
git pull origin claude/fix-google-ads-modal-aaOS4
sudo systemctl restart lsws

# If not a git repo, copy files from /home/user/flaskapp
```

**Status**: ⏳ PENDING

---

### 3. Verify Database Location Format
**Problem**: Campaigns with "City, ST" format get rejected by SerpAPI

**Solution**: Run the comprehensive SQL fix

```bash
mysql -u root -p fieljtgr_xyz < /home/fieljtgr/flaskapp/fix_all_locations.sql

# Verify it worked
mysql -u root -p fieljtgr_xyz -e "SELECT id, name, location FROM lead_campaigns WHERE location LIKE '%United States%' LIMIT 5;"
```

**Status**: ✅ DONE (you mentioned DB was updated)

---

### 4. Verify SerpAPI Key
**Problem**: Production was using wrong API key with 0 searches

**Solution**: Check production .env file has correct key

```bash
grep SERPAPI_KEY /home/fieljtgr/flaskapp/.env
# Should show key with 250 searches (currently at 11/250 used)
```

**Status**: ✅ DONE (you confirmed 11/250 searches used)

---

## 🔧 Optional Optimizations (Do After Critical Fixes)

### 5. Set Up Cron Jobs for Automation
**Purpose**: Automatically run lead automation and AI agents

**Solution**: See `crontab-agents.txt` and `RUN_AUTOMATION.md`

```bash
# Edit crontab on production
crontab -e

# Add automation jobs (update paths first):
# Lead automation - every hour
0 * * * * cd /home/fieljtgr/flaskapp && /home/fieljtgr/bin/python run_automation.py >> /var/log/lead-automation.log 2>&1

# AI agents - tactical (hourly), operational (4hr), strategic (daily)
# See crontab-agents.txt for full setup
```

**Status**: ⏳ PENDING

---

### 6. Increase LSAPI Worker Processes
**Purpose**: Handle more concurrent requests, prevent 503 errors under load

**Current**: You found `<maxConns>35</maxConns>` in config (good!)

**Verify**: After fixing paths in step 1, check that 35 workers are actually running:
```bash
ps aux | grep lswsgi | wc -l
```

**Status**: ⏳ PENDING (blocked by path fix in step 1)

---

### 7. Set Up Background Workers
**Purpose**: Handle async tasks (enrichment, email sending) without blocking web requests

**Options**:
- **Celery** (recommended): Full-featured task queue
- **Python-RQ**: Simpler Redis-based queue
- **Cron jobs**: Simplest, use what you already have

**For now**: Cron jobs are sufficient. See step 5.

**Status**: ⏳ PENDING

---

## 📊 Testing Checklist

After completing critical fixes, test these features:

- [ ] Site loads: https://fieldsprout.io
- [ ] Admin loads: https://fieldsprout.io/admin/
- [ ] Campaign list loads: https://fieldsprout.io/admin/lead-campaigns/
- [ ] Campaign detail page loads: https://fieldsprout.io/admin/lead-campaigns/4602
- [ ] Scraping works: Click "Scrape Ads" button on a campaign
- [ ] No console errors: Check browser console (F12) for JavaScript errors
- [ ] Leads appear: After scraping, leads show in campaign detail page
- [ ] 35+ workers running: `ps aux | grep lswsgi | wc -l`
- [ ] No 503 errors in logs: `sudo tail -50 /usr/local/lsws/logs/error.log`

---

## 🚨 If Things Break

### Emergency Rollback
If something goes wrong, restore from backup:

```bash
# Restore LiteSpeed config
sudo cp /usr/local/lsws/conf/httpd_config.xml.backup /usr/local/lsws/conf/httpd_config.xml
sudo systemctl restart lsws

# Restore code
tar -xzf ~/backup-flaskapp-YYYYMMDD-HHMMSS.tar.gz -C /home/fieljtgr/flaskapp
sudo systemctl restart lsws
```

### Get Help
If you're stuck, send me:

1. **LiteSpeed config**: `sudo cat /usr/local/lsws/conf/httpd_config.xml | grep -A 30 extProcessor`
2. **Worker count**: `ps aux | grep lswsgi`
3. **Recent errors**: `sudo tail -100 /usr/local/lsws/logs/error.log`
4. **Git status**: `cd /home/fieljtgr/flaskapp && git log -1 --oneline`

---

## 📝 Summary

**Root Cause**: LiteSpeed configured with Python 3.9 paths, but server has Python 3.10 at different location

**Fix Priority**:
1. ⚠️ **CRITICAL**: Fix LiteSpeed WSGI paths (step 1) - this is blocking everything
2. 🔄 **IMPORTANT**: Sync latest code to production (step 2)
3. ✅ **DONE**: Database location formats (step 3)
4. ✅ **DONE**: SerpAPI key verification (step 4)
5. 📅 **OPTIONAL**: Cron jobs and workers (steps 5-7)

**Expected Outcome**: After steps 1-2, you should have:
- Site loads without 503 errors
- 35 LSAPI workers running
- Scraping works with proper retry logic
- Clear error messages when things fail
- All location formats compatible with SerpAPI

---

## Next Steps

Start with step 1 (fix LSWSGI paths) and let me know the results. Once workers are running, we can move on to syncing code and setting up automation.
