# Deployment Instructions for Google Ads Grader Feature

## ✅ All Code Pushed to GitHub

Branch: `claude/update-service-pages-011CUSGS9fe6inttCJvsBQgn`

All updates have been committed and pushed. Ready for deployment!

---

## 📦 What's Included in This Update

### New Files Added:
```
flaskapp/app/ads_grader/__init__.py          (Blueprint with routes)
flaskapp/app/models_ads_grader.py            (Database model)
flaskapp/templates/ads_grader/index.html     (Landing page)
flaskapp/templates/ads_grader/analyze.html   (Analysis page)
flaskapp/templates/ads_grader/report.html    (Report display)
flaskapp/templates/ads_grader/history.html   (Report history)
migrations_sql/001_add_google_ads_grader_report.sql
migrations_sql/001_add_google_ads_grader_report_rollback.sql
migrations_sql/README.md
run_migration.py
GOOGLE_ADS_GRADER_TODO.md
```

### Modified Files:
```
flaskapp/app/__init__.py                     (Register ads_grader_bp)
flaskapp/app/models.py                       (Import GoogleAdsGraderReport)
flaskapp/templates/base_app.html             (Add navigation links)
```

---

## 🚀 Deployment Steps on Your Production Server

### Step 1: Pull the Latest Code

```bash
cd ~/flaskapp

# Fetch and pull the latest changes
git fetch origin
git pull origin claude/update-service-pages-011CUSGS9fe6inttCJvsBQgn

# Or if you're merging into main/master
git checkout main  # or master
git merge claude/update-service-pages-011CUSGS9fe6inttCJvsBQgn
```

### Step 2: Verify Files Exist

```bash
# Check that new files were pulled
ls -la flaskapp/app/ads_grader/
ls -la flaskapp/templates/ads_grader/
ls -la migrations_sql/
```

### Step 3: Database Already Created ✅

You already ran the SQL migration in phpMyAdmin, so the `google_ads_grader_reports` table exists.

**Skip this step** - Database is ready!

### Step 4: Restart Flask Application

```bash
# Option 1: If using systemd service
sudo systemctl restart your-flask-service-name

# Option 2: If using Passenger (cPanel)
touch ~/flaskapp/tmp/restart.txt

# Option 3: If running manually
# Stop the process (Ctrl+C or kill PID) and restart
```

### Step 5: Verify Deployment

Visit these URLs to confirm:

1. **Landing Page**: `https://yourdomain.com/ads-grader`
   - Should show marketing page

2. **Generate Demo Report**:
   - Click "Generate Demo Report" button
   - Should create report and redirect

3. **Check Logs**:
   ```bash
   # Should see this in logs:
   # [INFO] app: ads_grader_bp registered at /ads-grader
   ```

4. **Verify Database**:
   ```sql
   SELECT COUNT(*) FROM google_ads_grader_reports;
   ```
   - Should show demo reports created

---

## 🔍 Post-Deployment Checklist

- [ ] Code pulled from GitHub
- [ ] New files exist in filesystem
- [ ] Flask app restarted successfully
- [ ] Logs show `ads_grader_bp registered at /ads-grader`
- [ ] `/ads-grader` URL loads landing page
- [ ] Demo report generation works
- [ ] Report displays with scores and recommendations
- [ ] Navigation shows "Free Tools" section
- [ ] Mobile view works correctly

---

## 🐛 Known Issues to Watch For

### Issue 1: Auth Endpoint Error (Seen in Your Logs)

**Error**: `BuildError: Could not build url for endpoint 'auth.login'`

**Location**: `flaskapp/app/auth/session_utils.py` line 45

**Fix**: Change `"auth.login"` to `"auth_bp.login"`

**This is an existing bug, not related to the Ads Grader** - but you should fix it.

### Issue 2: Team Blueprint Error (Seen in Your Logs)

**Error**: `Attribute name 'metadata' is reserved`

**Location**: `flaskapp/app/models_audit.py`

**Fix**: Rename the `metadata` column to `meta_data` or `audit_metadata`

**This is an existing bug, not related to the Ads Grader** - but it prevents team_bp from loading.

---

## 📊 Feature Summary

Once deployed, users can:

✅ Visit `/ads-grader` for free Google Ads analysis
✅ Generate demo reports with realistic mock data
✅ View comprehensive performance reports with:
  - Overall score (0-100) and letter grade (A+ to F)
  - 3 key metrics (Quality Score, CTR, Wasted Spend)
  - 10 performance section scores with progress bars
  - Account diagnostics dashboard
  - Best practices checklist
  - AI-powered recommendations
✅ Access from navigation "Free Tools" section
✅ Mobile responsive design

**Future enhancements** (not included yet):
- Google Ads API OAuth integration for real data
- PDF export functionality
- Chart visualizations (Quality Score distribution, etc.)

---

## 🔗 Branch Information

**Branch Name**: `claude/update-service-pages-011CUSGS9fe6inttCJvsBQgn`

**Recent Commits**:
```
efe1615 - Add database migration for Google Ads Grader table
517a121 - Add Google Ads Quality Checker foundation with blueprint and templates
d8b3f9e - Add individual and bulk emailing to /admin with links on customer detail pages
563973c - Add post scheduling to LinkedIn Thought Leader Post Generator
```

**All commits are pushed and ready for deployment!** ✅

---

## 📞 Support

If you encounter any issues during deployment:

1. Check Flask logs for errors
2. Verify all files were pulled from git
3. Confirm database table exists
4. Try restarting Flask app again

**The feature is production-ready with demo data!** 🎉
