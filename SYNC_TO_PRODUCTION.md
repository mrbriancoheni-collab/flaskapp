# Sync Development Code to Production

## Important Discovery

You have TWO separate Flask installations:
1. **Development/Git Repository**: `/home/user/flaskapp/` (where code changes are made)
2. **Production Application**: `/home/fieljtgr/flaskapp/` (where LiteSpeed serves the app)

All the fixes I've made (source type mapping, retry logic, error handling, location fixes) were committed to the git repository at `/home/user/flaskapp/`, but your production server may be running from `/home/fieljtgr/flaskapp/`.

## Recent Fixes That Need to Be in Production

The following commits contain important fixes:
- `a3a1366` - Source type mapping (ads/maps → ad/map)
- `1608d16`, `77dbbe1` - SerpAPI retry logic with exponential backoff
- `1360b2f`, `1f7ef7b` - Enhanced error messages showing actual SerpAPI errors
- `5d36c7a`, `1b97764`, `4a11a6e` - Fixed JSON parse errors in frontend
- `7f853cc` - Comprehensive location format fix (SQL)

## Check If Production Needs Updates

On your production server, run:
```bash
cd /home/fieljtgr/flaskapp
git status
git log -1 --oneline
```

Compare to the latest commit in dev:
```bash
cd /home/user/flaskapp
git log -1 --oneline
# Should show: 7f853cc Add comprehensive SQL script to fix ALL campaign location formats
```

## Option 1: Pull Latest Code to Production

If `/home/fieljtgr/flaskapp/` is a git repository:

```bash
cd /home/fieljtgr/flaskapp

# Backup current code
tar -czf ~/backup-flaskapp-$(date +%Y%m%d-%H%M%S).tar.gz .

# Pull latest changes
git fetch origin
git checkout claude/fix-google-ads-modal-aaOS4
git pull origin claude/fix-google-ads-modal-aaOS4

# Restart the app
sudo systemctl restart lsws
```

## Option 2: Copy Files Manually

If production is not a git repo, copy the changed files:

```bash
# From dev to production (run on the server where both paths exist)
cp /home/user/flaskapp/flaskapp/app/admin/lead_campaigns_routes.py \
   /home/fieljtgr/flaskapp/app/admin/lead_campaigns_routes.py

cp /home/user/flaskapp/flaskapp/app/services/serpapi_scraper.py \
   /home/fieljtgr/flaskapp/app/services/serpapi_scraper.py

cp /home/user/flaskapp/flaskapp/templates/admin/lead_campaigns/view.html \
   /home/fieljtgr/flaskapp/templates/admin/lead_campaigns/view.html

# Restart
sudo systemctl restart lsws
```

## Option 3: Deploy via Git Push

If you're developing on a separate machine, push and pull:

```bash
# On dev machine
cd /home/user/flaskapp
git add -A
git commit -m "Production deployment $(date +%Y%m%d)"
git push origin claude/fix-google-ads-modal-aaOS4

# On production server
cd /home/fieljtgr/flaskapp
git pull origin claude/fix-google-ads-modal-aaOS4
sudo systemctl restart lsws
```

## Verify Production Has All Fixes

After syncing, check that the key fixes are present:

### 1. Source Type Mapping
```bash
grep -n "source_type_mapping" /home/fieljtgr/flaskapp/app/admin/lead_campaigns_routes.py
# Should show the mapping dict around line 694
```

### 2. Retry Logic
```bash
grep -n "max_retries = 3" /home/fieljtgr/flaskapp/app/services/serpapi_scraper.py
# Should show retry logic around line 131
```

### 3. JSON Error Handling
```bash
grep -n "contentType" /home/fieljtgr/flaskapp/templates/admin/lead_campaigns/view.html
# Should show content-type check around line 207
```

## Critical Files to Keep in Sync

These files have been modified with important fixes:
- `flaskapp/app/admin/lead_campaigns_routes.py` - Source mapping, auto-reset stuck campaigns
- `flaskapp/app/services/serpapi_scraper.py` - Retry logic, better error messages
- `flaskapp/templates/admin/lead_campaigns/view.html` - JSON parse error handling

## After Syncing

1. Restart LiteSpeed: `sudo systemctl restart lsws`
2. Clear browser cache (or hard refresh with Ctrl+Shift+R)
3. Test scraping: https://fieldsprout.io/admin/lead-campaigns/
4. Check logs: `sudo tail -f /usr/local/lsws/logs/error.log`

## Database Updates

The location format fix requires running SQL on production database:

```bash
# Run the comprehensive location fix
mysql -u root -p fieljtgr_xyz < /home/fieljtgr/flaskapp/fix_all_locations.sql

# Verify
mysql -u root -p fieljtgr_xyz -e "SELECT COUNT(*) as 'Campaigns with United States' FROM lead_campaigns WHERE location LIKE '%United States%';"
```

## Environment Variables

Make sure production has all required API keys:
```bash
# Check which .env file LiteSpeed is using
sudo grep -r "SERPAPI" /home/fieljtgr/flaskapp/.env

# Should have:
# SERPAPI_KEY=your_production_key_with_250_searches
# MAILGUN_API_KEY=...
# OPENAI_API_KEY=...
# etc.
```

## Common Deployment Issues

### Issue: Changes don't appear after restart
**Solution**: LiteSpeed may be caching bytecode. Clear Python cache:
```bash
find /home/fieljtgr/flaskapp -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null
sudo systemctl restart lsws
```

### Issue: Import errors after update
**Solution**: Reinstall dependencies in production virtualenv:
```bash
source /home/fieljtgr/bin/activate
pip install -r /home/fieljtgr/flaskapp/requirements.txt
deactivate
sudo systemctl restart lsws
```

### Issue: 500 errors after deployment
**Solution**: Check error logs and verify file permissions:
```bash
sudo chown -R fieljtgr:fieljtgr /home/fieljtgr/flaskapp
sudo chmod -R 755 /home/fieljtgr/flaskapp
sudo tail -100 /usr/local/lsws/logs/error.log
```
