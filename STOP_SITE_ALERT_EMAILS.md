# Stop "Site Alert" Emails

## Problem
Receiving "Site Alert" emails every 5 minutes with subject "Site Alert" and body "Site down".

## Root Cause
These emails are from **cPanel's HTTP Availability Monitoring**, not your Flask application.

## Solution: Disable in cPanel

### Quick Fix (2 minutes)

1. **Log into cPanel**
   - URL: `https://your-hosting-provider.com:2083`
   - Or through your hosting provider's client area

2. **Navigate to "Contact Information"**
   - Look in the **"Preferences"** section
   - Or search "contact" in cPanel search bar

3. **Disable Monitoring**
   - Find: **"Notify me when my site is down"** checkbox
   - **Uncheck it** or set to "Disabled"
   - May also be called: **"HTTP Availability Monitoring"**

4. **Save Changes**
   - Click "Save" or "Update Contact Information"
   - Emails will stop immediately!

---

## Alternative: Contact Support

If you can't find the setting:

**Email your hosting provider:**
> Subject: Disable HTTP monitoring alerts for fieldsprout.io
>
> Hello,
>
> Please disable the HTTP availability monitoring alerts for my domain fieldsprout.io.
> I'm receiving "Site Alert" emails every 5 minutes that I no longer need.
>
> Thank you!

---

## Verify Your Site is Actually Up

Before disabling, make sure your site isn't actually down!

**Run this on production:**
```bash
cd /home/fieljtgr/flaskapp
./check_site_status.sh
```

This will check:
- ✓ Gunicorn is running
- ✓ Port 8000 is listening
- ✓ Health endpoint responding
- ✓ Main site responding

---

## Common Causes of False "Site Down" Alerts

1. **Slow Response Times**
   - cPanel timeout might be too aggressive
   - Your app might be slow to respond under load

2. **SSL/HTTPS Issues**
   - Certificate expired or misconfigured
   - Monitor checking HTTP but site forces HTTPS

3. **Firewall/IP Blocking**
   - Monitor's IP address is being blocked
   - Rate limiting kicking in

4. **Resource Limits**
   - Hitting PHP/memory limits
   - Database connection pool exhausted

---

## If Site IS Actually Down

If `check_site_status.sh` shows your site is down:

**Restart Gunicorn:**
```bash
cd /home/fieljtgr/flaskapp
./stop_gunicorn.sh
./start_gunicorn.sh
```

**Check Logs:**
```bash
tail -100 /home/fieljtgr/flaskapp/logs/gunicorn_error.log
tail -100 /home/fieljtgr/flaskapp/logs/gunicorn_access.log
```

---

## Keep Monitoring (Optional)

If you WANT monitoring but fewer emails:

1. **Change frequency** in cPanel (e.g., every 30 minutes instead of 5)
2. **Use external monitoring** (better options):
   - [UptimeRobot](https://uptimerobot.com) - Free, 5min checks
   - [Pingdom](https://www.pingdom.com) - Free trial
   - [StatusCake](https://www.statuscake.com) - Free plan
   - [BetterUptime](https://betteruptime.com) - Modern, clean UI

These services send fewer emails and have better alerting logic.

---

## Files in This Repo

- `disable_alert_emails.py` - Disables Google Ads alert emails (different issue)
- `check_site_status.sh` - Checks if your site is actually up
- `STOP_SITE_ALERT_EMAILS.md` - This file
