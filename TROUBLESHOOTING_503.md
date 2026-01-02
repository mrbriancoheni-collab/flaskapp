# Troubleshooting 503 Error on /lead-campaigns/

## Issue Summary
The `/admin/lead-campaigns/` route is returning a 503 (Service Unavailable) error.

## Root Cause Analysis

Based on the fixes applied, the most likely causes are:

### 1. **Missing BREVO_API_KEY Environment Variable** (MOST LIKELY)
The `BrevoOutreachService` requires `BREVO_API_KEY` to be set. While the class import won't fail, if ANY code path tries to instantiate `BrevoOutreachService()` during page load, it will raise a `ValueError` and cause a 503.

**Solution:**
```bash
# Add to your environment variables (wherever your app is deployed)
export BREVO_API_KEY="your_brevo_api_key_here"
export BREVO_FROM_EMAIL="noreply@fieldsprout.io"
export BREVO_FROM_NAME="FieldSprout"
```

### 2. **Application Not Restarted After Code Changes**
The templates were just created and Mailgun references were removed. The application needs to be restarted to load the new code.

**Solution:**
```bash
# Restart your Flask/WSGI server
# For example:
sudo systemctl restart gunicorn  # or
sudo service apache2 restart     # or
# kill and restart your Flask process
```

### 3. **Database Connection Issues**
The index route queries the database extensively. If the database is unreachable or timing out, it will cause a 503.

**Solution:**
- Check database connection string
- Verify database server is running
- Check firewall rules
- Review database logs for connection errors

### 4. **Missing Python Dependencies**
If the deployed environment is missing required packages (like `sib-api-v3-sdk` for Brevo), imports will fail.

**Solution:**
```bash
# Install all required dependencies
pip install -r requirements.txt

# Or specifically for Brevo:
pip install sib-api-v3-sdk
```

## Fixes Already Applied

✅ **Created Missing Templates:**
- `/app/templates/admin/lead_campaigns/index.html` - Main dashboard
- `/app/templates/admin/lead_campaigns/view.html` - Campaign details
- `/app/templates/admin/lead_campaigns/new.html` - Create campaign
- `/app/templates/admin/lead_campaigns/edit.html` - Edit campaign
- `/app/templates/admin/lead_campaigns/sequences_list.html` - Email sequences
- `/app/templates/admin/error.html` - Error page

✅ **Removed All Mailgun References:**
- `lead_campaigns_routes.py` - Now uses BrevoOutreachService exclusively
- `lead_automation_service.py` - Removed Mailgun import and initialization
- `email_service.py` - Changed default to Brevo

## Immediate Action Items

1. **Set Environment Variables:**
   ```bash
   # Check if BREVO_API_KEY is set
   echo $BREVO_API_KEY

   # If not set, add it to your environment
   # Location depends on deployment:
   # - Docker: Add to docker-compose.yml or Dockerfile
   # - Systemd: Add to service file
   # - .env file: Add to /home/user/flaskapp/.env
   ```

2. **Restart Application:**
   ```bash
   # Find your Flask process
   ps aux | grep flask

   # Restart it (method depends on how it's deployed)
   ```

3. **Check Application Logs:**
   ```bash
   # Check for specific error messages
   tail -f /home/user/flaskapp/flaskapp/stderr.log
   tail -f /var/log/gunicorn/error.log  # or wherever your logs are
   ```

4. **Test Imports Manually** (if you have access to Python with Flask installed):
   ```python
   from app.admin.lead_campaigns_routes import lead_campaigns_bp
   # Should succeed without errors
   ```

## Verification Steps

After applying fixes:

1. Access `/admin/lead-campaigns/` - Should show campaign dashboard
2. Check that bulk action buttons are visible
3. Verify no Mailgun-related errors appear
4. Test creating a new campaign (will need BREVO_API_KEY for email sending)

## Additional Notes

- The application is configured to use Brevo (EMAIL_PROVIDER='brevo' in config.py)
- All email sending now goes through BrevoOutreachService
- Bulk actions are available via API endpoints and UI buttons
- Only the 20 newest campaigns are displayed as requested

## If Still Getting 503

1. Check web server error logs (nginx, Apache, gunicorn, etc.)
2. Verify Python version compatibility
3. Check file permissions on template files
4. Review database query performance (the index route runs many queries)
5. Enable Flask debug mode temporarily to see detailed error traces

## Contact/Support

If the issue persists, collect:
- Full error traceback from application logs
- Web server error logs
- Output of `pip list` showing installed packages
- Environment variables (sanitized, no API keys)
