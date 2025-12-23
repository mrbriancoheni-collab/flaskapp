# Privacy Error - Troubleshooting Guide

## What is a Privacy Error?

When you see "Your connection is not private" or similar error on **all pages**, this typically means:

1. **SSL Certificate Issue** - Certificate expired, invalid, or self-signed
2. **Web Server Down** - App crashed or not responding
3. **HTTPS Configuration Issue** - Mixed content or wrong SSL settings
4. **Deployment Issue** - Recent code push broke the app

## Quick Diagnosis Steps

### Step 1: Check if App is Running

```bash
# SSH into your server
ssh user@server

# Check if Python/Flask app is running
ps aux | grep python

# Check web server (nginx/apache)
systemctl status nginx
# OR
systemctl status apache2

# Check app logs for errors
tail -100 /var/log/your-app/error.log
tail -100 /var/log/nginx/error.log
```

### Step 2: Check SSL Certificate

```bash
# Check certificate expiration
openssl s_client -connect fieldsprout.io:443 -servername fieldsprout.io 2>/dev/null | openssl x509 -noout -dates

# Should show:
# notBefore=... (start date)
# notAfter=...  (expiration date)
```

If certificate is expired, you need to renew it.

### Step 3: Test if App Starts

```bash
# Try starting the app manually
cd /home/fieljtgr/flaskapp
source /home/fieljtgr/virtualenv/flaskapp/3.9/bin/activate

# Set environment variables
export SQLALCHEMY_DATABASE_URI="mysql+pymysql://root:PASSWORD@localhost:3306/fieljtgr_xyz?charset=utf8mb4"

# Try to start Flask
python3 -c "from app import create_app; app = create_app(); print('✓ App created successfully')"
```

If this fails, there's a code error. Check the error message.

### Step 4: Check Web Server Logs

```bash
# Nginx error log
tail -50 /var/log/nginx/error.log

# App error log (varies by setup)
tail -50 /var/log/uwsgi/app/error.log
# OR
tail -50 /var/log/gunicorn/error.log
```

Look for:
- "Connection refused"
- "502 Bad Gateway"
- Python tracebacks
- Import errors

## Common Causes & Fixes

### Cause 1: App Crashed After Recent Deploy

**Symptoms:**
- Privacy error started after git pull/deploy
- Works locally but not on server

**Solution:**
```bash
# Check app logs for import errors
tail -100 /var/log/your-app/error.log

# Common issue: Missing dependencies
source /home/fieljtgr/virtualenv/flaskapp/3.9/bin/activate
pip install -r flaskapp/requirements.txt

# Restart app
sudo systemctl restart your-app-service
# OR
sudo supervisorctl restart your-app
```

### Cause 2: SSL Certificate Expired

**Symptoms:**
- "NET::ERR_CERT_DATE_INVALID" error
- "Certificate has expired" message

**Solution (Let's Encrypt):**
```bash
# Renew certificate
sudo certbot renew

# Restart nginx
sudo systemctl restart nginx
```

### Cause 3: Web Server Not Running

**Symptoms:**
- "ERR_CONNECTION_REFUSED"
- "This site can't be reached"

**Solution:**
```bash
# Restart nginx
sudo systemctl restart nginx

# If using apache
sudo systemctl restart apache2

# Check status
sudo systemctl status nginx
```

### Cause 4: Python Import Error

**Symptoms:**
- App worked before recent changes
- Logs show "ModuleNotFoundError" or "ImportError"

**Solution:**
```bash
# Install missing dependencies
source /home/fieljtgr/virtualenv/flaskapp/3.9/bin/activate
cd /home/fieljtgr/flaskapp
pip install -r flaskapp/requirements.txt

# Common missing dependencies:
pip install beautifulsoup4 requests

# Restart app
sudo systemctl restart your-app-service
```

### Cause 5: Database Connection Error

**Symptoms:**
- App tries to start but crashes immediately
- Logs show "Access denied" or "Unknown database"

**Solution:**
```bash
# Test database connection
mysql -u root -p fieljtgr_xyz -e "SELECT 1;"

# If connection fails, check credentials in environment variables
# Update systemd service file or .env file
```

## Roll Back Recent Changes (If Needed)

If the issue started after recent deploy:

```bash
cd /home/fieljtgr/flaskapp

# See recent commits
git log --oneline -5

# Roll back to previous commit (replace COMMIT_HASH)
git reset --hard COMMIT_HASH

# Restart app
sudo systemctl restart your-app-service
```

## Emergency: Force HTTPS Redirect Off

If SSL is the issue and you need the site working ASAP:

```bash
# Edit nginx config
sudo nano /etc/nginx/sites-available/your-site

# Comment out SSL redirect temporarily:
# rewrite ^(.*)$ https://$host$1 permanent;

# Reload nginx
sudo systemctl reload nginx
```

**Note:** This allows HTTP access temporarily. Fix SSL and re-enable HTTPS.

## Check These Files for Errors

Recent changes that could affect the site:

1. `/home/fieljtgr/flaskapp/flaskapp/app/admin/lead_campaigns_routes.py`
   - Added error handling and timestamps
   - Run: `python3 -m py_compile lead_campaigns_routes.py`

2. `/home/fieljtgr/flaskapp/flaskapp/templates/admin/lead_campaigns/index.html`
   - Updated template with timestamps
   - Check for Jinja2 syntax errors

## Most Likely Issue

Based on "privacy error on all pages":

**95% Chance:** SSL certificate issue or web server not serving HTTPS properly

**Quick Fix:**
```bash
# Restart everything
sudo systemctl restart nginx
sudo systemctl restart your-app-service

# Check if it works now
curl -I https://fieldsprout.io
```

## Get More Help

Run these diagnostic commands and share output:

```bash
# 1. Check if app process is running
ps aux | grep -E 'python|gunicorn|uwsgi' | grep -v grep

# 2. Check nginx status
sudo systemctl status nginx

# 3. Test app creation
cd /home/fieljtgr/flaskapp
source /home/fieljtgr/virtualenv/flaskapp/3.9/bin/activate
python3 -c "from app import create_app; create_app()"

# 4. Check SSL cert
openssl s_client -connect fieldsprout.io:443 -servername fieldsprout.io 2>/dev/null | openssl x509 -noout -dates

# 5. Check recent errors
sudo tail -50 /var/log/nginx/error.log
```

Share the output of these commands to diagnose the issue.
