# Production Deployment Guide

## 🚨 CRITICAL: Site is currently DOWN (503 Error)

The site is down because Gunicorn is not running on port 8000.

## Immediate Fix Steps

### Step 1: Upload Scripts to Production Server

Upload these files to `/home/fieljtgr/flaskapp/` via cPanel File Manager:
- `start_gunicorn.sh`
- `stop_gunicorn.sh`
- `restart_gunicorn.sh`

### Step 2: Make Scripts Executable

SSH into your server and run:

```bash
cd /home/fieljtgr/flaskapp
chmod +x start_gunicorn.sh stop_gunicorn.sh restart_gunicorn.sh
```

### Step 3: Find Your Virtualenv Path

The startup script needs to know where your Python virtualenv is located. Run:

```bash
find /home/fieljtgr -name "activate" -type f 2>/dev/null | grep -v ".local" | grep -v "__pycache__"
```

This will show paths like:
- `/home/fieljtgr/virtualenv/flaskapp/3.8/bin/activate`
- or `/home/fieljtgr/venv/bin/activate`

### Step 4: Edit start_gunicorn.sh

If your virtualenv path is different from `/home/fieljtgr/virtualenv/flaskapp/3.8`, edit line 7 in `start_gunicorn.sh`:

```bash
nano start_gunicorn.sh
# Change line 7:
VENV_DIR="/home/fieljtgr/YOUR_ACTUAL_PATH"
```

### Step 5: Start Gunicorn

```bash
cd /home/fieljtgr/flaskapp
./start_gunicorn.sh
```

You should see:
```
✓ Gunicorn started successfully (PID: XXXXX)
✓ Listening on 127.0.0.1:8000
✓ Access log: /home/fieljtgr/flaskapp/logs/gunicorn_access.log
✓ Error log: /home/fieljtgr/flaskapp/logs/gunicorn_error.log
```

### Step 6: Verify Site is Working

Visit your site - it should now be working!

Check the logs:
```bash
tail -f /home/fieljtgr/flaskapp/logs/gunicorn_error.log
```

---

## Alternative: Quick Start Without Scripts

If the scripts don't work, start Gunicorn manually:

```bash
cd /home/fieljtgr/flaskapp

# Activate virtualenv (adjust path as needed)
source /home/fieljtgr/virtualenv/flaskapp/3.8/bin/activate

# Start Gunicorn
gunicorn --bind 127.0.0.1:8000 \
         --workers 4 \
         --timeout 120 \
         --daemon \
         --access-logfile logs/gunicorn_access.log \
         --error-logfile logs/gunicorn_error.log \
         --pid gunicorn.pid \
         passenger_wsgi:application
```

---

## Troubleshooting

### Check if Gunicorn is Running

```bash
ps aux | grep gunicorn | grep -v grep
netstat -tlnp | grep :8000
```

### View Error Logs

```bash
tail -50 /home/fieljtgr/flaskapp/logs/gunicorn_error.log
tail -50 /home/fieljtgr/flaskapp/error.log
```

### Stop Gunicorn

```bash
cd /home/fieljtgr/flaskapp
./stop_gunicorn.sh
```

### Restart After Code Changes

```bash
cd /home/fieljtgr/flaskapp
./restart_gunicorn.sh
```

---

## Setting Up Auto-Start on Reboot

Since your server doesn't use systemd, add this to your crontab:

```bash
crontab -e
```

Add this line:
```
@reboot /home/fieljtgr/flaskapp/start_gunicorn.sh
```

---

## Common Issues

### Issue: "gunicorn: command not found"

Gunicorn is not installed or not in virtualenv. Install it:

```bash
source /home/fieljtgr/virtualenv/flaskapp/3.8/bin/activate
pip install gunicorn
```

### Issue: "Address already in use"

Another process is using port 8000:

```bash
netstat -tlnp | grep :8000
# Kill the process
kill -9 <PID>
```

### Issue: Import errors in logs

Make sure .env file exists:

```bash
ls -la /home/fieljtgr/flaskapp/.env
# Should point to /home/fieljtgr/.env
```

Install missing packages:

```bash
source /home/fieljtgr/virtualenv/flaskapp/3.8/bin/activate
pip install -r /home/fieljtgr/flaskapp/requirements.txt
```

---

## Next Steps After Site is Restored

1. ✅ Verify site is accessible
2. ✅ Check that login works
3. ✅ Test lead campaigns dashboard
4. ✅ Test Google Ads dashboard
5. Set up cron jobs for lead automation
6. Set up cron jobs for Google Ads optimization
