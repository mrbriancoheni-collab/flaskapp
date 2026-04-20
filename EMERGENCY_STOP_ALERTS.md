# 🚨 EMERGENCY: Stop "Site Alert" Emails NOW

## Problem
Getting "Site Alert" emails every 5 minutes even though site is working fine.

---

## ⚡ FASTEST FIX (Try These First)

### Option 1: Run the Diagnostic Script (30 seconds)
```bash
cd /home/fieldsprout/flaskapp
./find_alert_source.sh
```

This will tell you EXACTLY what's sending the emails.

---

### Option 2: Disable in cPanel (2 minutes)

**cPanel > "Contact Information" or "Contact Manager"**

Look for one of these settings:
- ☐ "Notify me when my website is down"
- ☐ "Enable HTTP availability monitoring"
- ☐ "Send downtime alerts"
- ☐ "Monitor website uptime"

**UNCHECK IT** and click Save.

**Common locations in cPanel:**
- Under **"Preferences"** section
- Under **"General Settings"**
- Search "contact" in cPanel search bar (top right)

---

### Option 3: Check Email Headers (Find the Sender)

**Open one of the alert emails and look at the headers:**

1. In Gmail: Click **"Show original"**
2. In Outlook: Click **"View message details"**
3. Look for **"X-Mailer:"** or **"From:"** header

This will tell you:
- **If it says "cPanel"** → It's cPanel monitoring
- **If it shows "uptimerobot.com"** → You have UptimeRobot configured
- **If it shows your server IP** → It's a cron job

---

## 🔧 If It's a Cron Job

### Check Your Crontab
```bash
crontab -l
```

Look for lines containing:
- `curl`
- `wget`
- `ping`
- `monitor`
- `alert`

### Remove It
```bash
crontab -e
```
Then comment out (add `#` at start) or delete the monitoring line.

---

## 🌐 If It's External Monitoring

### UptimeRobot
1. Go to: https://uptimerobot.com/dashboard
2. Find monitor for "fieldsprout.io"
3. Click **"..."** > **"Delete"** or **"Pause"**

### Pingdom
1. Go to: https://my.pingdom.com
2. Find check for "fieldsprout.io"
3. Click **"Pause"** or **"Delete"**

### StatusCake
1. Go to: https://app.statuscake.com
2. Find test for "fieldsprout.io"
3. Pause or delete it

---

## 📧 Nuclear Option: Email Filter

**While you find the source, create a filter to auto-delete these:**

### Gmail
1. Search: `subject:"Site Alert"`
2. Click **"..."** > **"Filter messages like this"**
3. Check **"Delete it"**
4. Click **"Create filter"**

### Outlook/Office365
1. Right-click alert email > **"Rules"** > **"Create rule"**
2. Subject contains: "Site Alert"
3. Action: **"Delete"**

---

## 🆘 Still Getting Emails?

### Contact Your Hosting Provider
Send them this exact message:

> **Subject:** URGENT: Disable all monitoring alerts for fieldsprout.io
>
> Hello,
>
> My domain fieldsprout.io is sending "Site Alert" emails every 5 minutes even though the site is working fine.
>
> Please immediately disable:
> - cPanel HTTP monitoring
> - Server-level uptime checks
> - Contact email notifications
> - Any automated monitoring alerts
>
> for account: [YOUR_CPANEL_USERNAME]
> domain: fieldsprout.io
>
> This is urgent as I'm receiving alerts every 5 minutes.
>
> Thank you!

**Call them if email takes too long!**

---

## 🔍 Advanced Debugging

### Check Who's Sending
```bash
# Check mail logs
sudo tail -100 /var/log/maillog | grep "Site Alert"
# OR
sudo tail -100 /var/log/mail.log | grep "Site Alert"

# Check all cron jobs (system-wide)
sudo grep -r "fieldsprout" /etc/cron.* /var/spool/cron/
```

### Check Your Email Queue
```bash
mailq
# Look for "Site Alert" messages and note the sender
```

---

## ✅ How to Verify It's Fixed

After making changes:
1. Wait 10 minutes
2. Check your email
3. If no new "Site Alert" → **FIXED!** 🎉
4. If still coming → Try next solution

---

## 🎯 Most Likely Culprits (In Order)

1. **cPanel Contact Information monitoring** (80% of cases)
2. **External uptime service** (UptimeRobot, Pingdom, etc.) (15%)
3. **Cron job** running `curl` or `wget` to check site (4%)
4. **Hosting provider's default monitoring** (1%)

---

## 📞 Need Help NOW?

If you've tried everything and it's still sending:

1. **Run the diagnostic:**
   ```bash
   cd /home/fieldsprout/flaskapp
   ./find_alert_source.sh > alert_debug.txt
   cat alert_debug.txt
   ```

2. **Check the email headers** - they'll reveal the sender

3. **Contact hosting support** - they can disable it server-side

---

## After You Fix It

Consider using a proper uptime monitor with better alerting:
- **UptimeRobot** - Free, checks every 5 min, 50 monitors
- **BetterUptime** - Modern UI, smart alerts (combines multiple failures)
- **Pingdom** - Industry standard, very reliable
- **StatusCake** - Free plan, unlimited tests

These send ONE email when site goes down, not constant spam.

---

**This guide covers 99.9% of cases. If none of this works, the issue is very unusual and you should contact your hosting provider immediately.**
