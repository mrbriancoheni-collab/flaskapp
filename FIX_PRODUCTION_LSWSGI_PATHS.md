# Fix LiteSpeed WSGI Path Configuration

## Problem
Your production server's LiteSpeed configuration is looking for Python in the wrong locations:
- Looking for: `/home/fieljtgr/virtualenv/flaskapp/3.9/bin/set_env_vars.py` (doesn't exist)
- Looking for: `/opt/alt/python39/bin/lswsgi` (doesn't exist)

## Actual Paths on Your Server
Based on the information you provided:
- Python: `/bin/python3` (version 3.10.12)
- Virtualenv: `/home/fieljtgr/` (contains bin/, lib/, pyvenv.cfg)
- Application: `/home/fieljtgr/flaskapp/passenger_wsgi.py`
- WSGI binary: Should be at `/home/fieljtgr/bin/lswsgi` or `/usr/local/bin/lswsgi`

## Steps to Fix

### 1. Find Your LiteSpeed Configuration

On your production server, run:
```bash
sudo find / -name "httpd_config.xml" 2>/dev/null
```

The file is typically at `/usr/local/lsws/conf/httpd_config.xml`

### 2. Locate the External App Configuration

Open the config file:
```bash
sudo nano /usr/local/lsws/conf/httpd_config.xml
```

Look for an `<extProcessorList>` section with an `<extProcessor>` entry for your Flask app. It might look like:

```xml
<extProcessor>
  <type>lsapi</type>
  <name>FlaskApp</name>
  <address>uds://tmp/lshttpd/flaskapp.sock</address>
  <maxConns>35</maxConns>
  <env>PYTHONPATH=/home/fieljtgr/virtualenv/flaskapp/3.9/lib/python3.9/site-packages</env>
  <initTimeout>60</initTimeout>
  <retryTimeout>0</retryTimeout>
  <persistConn>1</persistConn>
  <respBuffer>0</respBuffer>
  <autoStart>1</autoStart>
  <path>/opt/alt/python39/bin/lswsgi</path>
  <backlog>100</backlog>
  <instances>1</instances>
  <priority>0</priority>
  <memSoftLimit>2047M</memSoftLimit>
  <memHardLimit>2047M</memHardLimit>
  <procSoftLimit>400</procSoftLimit>
  <procHardLimit>500</procHardLimit>
</extProcessor>
```

### 3. Update the Paths

Change these lines to use your actual paths:

**OLD:**
```xml
<path>/opt/alt/python39/bin/lswsgi</path>
<env>PYTHONPATH=/home/fieljtgr/virtualenv/flaskapp/3.9/lib/python3.9/site-packages</env>
```

**NEW:**
```xml
<path>/home/fieljtgr/bin/lswsgi</path>
<env>PYTHONPATH=/home/fieljtgr/lib/python3.10/site-packages</env>
<env>LSAPI_CHILDREN=35</env>
<env>LSAPI_MAX_PROCESS_TIME=300</env>
<env>LSAPI_MAX_IDLE=120</env>
```

**Note:** If `/home/fieljtgr/bin/lswsgi` doesn't exist, you may need to install it:
```bash
cd /home/fieljtgr
source bin/activate
pip install litespeed-lsapi
```

### 4. Alternative: Check Virtual Host Configuration

The External App might also be configured in the Virtual Host section. Look for `<vhostList>` in the config:

```xml
<vhost>
  <name>fieldsprout.io</name>
  <vhRoot>/home/fieljtgr/flaskapp</vhRoot>
  <configFile>/usr/local/lsws/conf/vhosts/fieldsprout.io/vhconf.xml</configFile>
</vhost>
```

If you have a separate vhost config file, check it for the extProcessor configuration as well.

### 5. Restart LiteSpeed

After making changes:
```bash
sudo systemctl restart lsws
# OR
sudo /usr/local/lsws/bin/lswsctrl restart
```

### 6. Verify LSAPI Processes Started

Check that workers are running:
```bash
ps aux | grep lswsgi | grep -v grep
```

You should see 35 processes (or whatever LSAPI_CHILDREN is set to).

### 7. Check Error Logs

If still having issues, check:
```bash
sudo tail -f /usr/local/lsws/logs/error.log
sudo tail -f /home/fieljtgr/flaskapp/logs/error.log  # if you have app-specific logs
```

## Alternative: Passenger Configuration

If you're using Passenger instead of pure LiteSpeed LSAPI, the configuration might be in:
- `/etc/httpd/conf.d/passenger.conf` (Apache + Passenger)
- `.htaccess` in your app root
- Passenger standalone config

Check your Passenger configuration:
```bash
passenger-config about-projects
```

## Troubleshooting

### If lswsgi is not found
Install it in your virtualenv:
```bash
cd /home/fieljtgr
source bin/activate
pip install litespeed-lsapi
which lswsgi  # Should show /home/fieljtgr/bin/lswsgi
```

### If Python version is wrong
Your system has Python 3.10.12, but config references 3.9. Update all references to use:
- `/bin/python3` (system Python)
- `/home/fieljtgr/lib/python3.10/site-packages` (virtualenv packages)

### If set_env_vars.py is missing
This script is typically created by cPanel's Python app setup. If you're not using cPanel, you may need to:
1. Remove references to `set_env_vars.py` from the wrapper
2. Set environment variables directly in the extProcessor config using `<env>` tags

## Quick Fix Script

Save this as `fix_lswsgi_config.sh` and run with `sudo bash fix_lswsgi_config.sh`:

```bash
#!/bin/bash
# Backup original config
sudo cp /usr/local/lsws/conf/httpd_config.xml /usr/local/lsws/conf/httpd_config.xml.backup

# Update paths (adjust these paths to match your actual setup)
sudo sed -i 's|/opt/alt/python39/bin/lswsgi|/home/fieljtgr/bin/lswsgi|g' /usr/local/lsws/conf/httpd_config.xml
sudo sed -i 's|/home/fieljtgr/virtualenv/flaskapp/3.9|/home/fieljtgr|g' /usr/local/lsws/conf/httpd_config.xml
sudo sed -i 's|python3.9|python3.10|g' /usr/local/lsws/conf/httpd_config.xml

# Restart LiteSpeed
sudo systemctl restart lsws || sudo /usr/local/lsws/bin/lswsctrl restart

echo "LiteSpeed restarted. Check status:"
ps aux | grep lswsgi | grep -v grep | wc -l
echo "worker processes found (should be 35)"
```

## After Fixing

Once the paths are corrected and LiteSpeed restarted:

1. Verify workers are running: `ps aux | grep lswsgi | wc -l` should show 35+
2. Test the site: https://fieldsprout.io should load without 503 errors
3. Test scraping: https://fieldsprout.io/admin/lead-campaigns/ scrape buttons should work
4. Monitor logs for any remaining errors

## Need Help?

If you're still seeing errors after these changes, send me:
1. Output of: `sudo cat /usr/local/lsws/conf/httpd_config.xml | grep -A 20 extProcessor`
2. Output of: `ps aux | grep lswsgi`
3. Recent error log: `sudo tail -50 /usr/local/lsws/logs/error.log`
