# Setting Mailgun Environment Variables in Your Hosting Platform

## The Problem

"Connection unexpectedly closed" means SMTP authentication is failing.

**Most common cause:** Using the Mailgun API Key instead of SMTP Password.

```
❌ API Key:      f160ce6d************ (56 chars, NOT for SMTP)
✅ SMTP Password: Different format, get from Mailgun dashboard
```

---

## Step-by-Step Fix

### 1. Get Your SMTP Password

1. Visit: https://app.mailgun.com/app/sending/domains/mg.fieldsprout.io
2. Scroll to **"SMTP Credentials"** section
3. Click **"Reset Password"** button
4. **Copy the new password** (this is your SMTP password!)

⚠️ **Important:** This is NOT the same as the API key!

### 2. Update Environment Variables

Set these in your hosting platform's dashboard:

```bash
MAIL_SERVER=smtp.mailgun.org
MAIL_PORT=587
MAIL_USE_TLS=true
MAIL_USE_SSL=false

# Use the SMTP password you just got (Step 1)
MAIL_USERNAME_DAVID=postmaster@mg.fieldsprout.io
MAIL_PASSWORD_DAVID=YOUR-SMTP-PASSWORD-HERE

# Sender addresses
MAIL_DEFAULT_SENDER=noreply@mg.fieldsprout.io
MAIL_FROM=noreply@mg.fieldsprout.io
```

### 3. Restart Your Application

After updating environment variables, **restart your app** for changes to take effect.

### 4. Test Email

Visit: https://fieldsprout.io/admin/test-email

Send a test email to yourself. It should now work!

---

## Platform-Specific Instructions

### Railway

1. Go to your project dashboard
2. Click on your service
3. Go to **"Variables"** tab
4. Click **"+ New Variable"** for each variable
5. Click **"Deploy"** to restart

### Render

1. Go to your web service dashboard
2. Click **"Environment"** in left sidebar
3. Click **"Add Environment Variable"** for each variable
4. Click **"Save Changes"**
5. Render will automatically redeploy

### Heroku

```bash
heroku config:set MAIL_SERVER=smtp.mailgun.org
heroku config:set MAIL_PORT=587
heroku config:set MAIL_USE_TLS=true
heroku config:set MAIL_USE_SSL=false
heroku config:set MAIL_USERNAME_DAVID=postmaster@mg.fieldsprout.io
heroku config:set MAIL_PASSWORD_DAVID=your-smtp-password
heroku config:set MAIL_DEFAULT_SENDER=noreply@mg.fieldsprout.io
```

### Docker / Docker Compose

Add to your `.env` file or docker-compose.yml:

```yaml
environment:
  - MAIL_SERVER=smtp.mailgun.org
  - MAIL_PORT=587
  - MAIL_USE_TLS=true
  - MAIL_USE_SSL=false
  - MAIL_USERNAME_DAVID=postmaster@mg.fieldsprout.io
  - MAIL_PASSWORD_DAVID=your-smtp-password
  - MAIL_DEFAULT_SENDER=noreply@mg.fieldsprout.io
```

Then: `docker-compose down && docker-compose up -d`

### VPS / Direct Server

Add to your systemd service file or supervisor config:

```ini
Environment="MAIL_SERVER=smtp.mailgun.org"
Environment="MAIL_PORT=587"
Environment="MAIL_USE_TLS=true"
Environment="MAIL_USE_SSL=false"
Environment="MAIL_USERNAME_DAVID=postmaster@mg.fieldsprout.io"
Environment="MAIL_PASSWORD_DAVID=your-smtp-password"
Environment="MAIL_DEFAULT_SENDER=noreply@mg.fieldsprout.io"
```

Then restart: `sudo systemctl restart your-app`

---

## Verification Checklist

✅ Got SMTP password from Mailgun (not API key)
✅ Set MAIL_USERNAME_DAVID=postmaster@mg.fieldsprout.io
✅ Set MAIL_PASSWORD_DAVID to SMTP password
✅ Set MAIL_USE_TLS=true (required for port 587)
✅ Set MAIL_USE_SSL=false (must be false for port 587)
✅ Restarted application
✅ Tested at /admin/test-email

---

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Using API key as password | Get SMTP password from dashboard |
| MAIL_USE_SSL=true with port 587 | Change to MAIL_USE_SSL=false |
| Wrong username | Use: postmaster@mg.fieldsprout.io |
| Forgot to restart app | Restart after changing env vars |
| Not saving changes | Click Save/Deploy in dashboard |

---

## Still Not Working?

If you continue to see "Connection unexpectedly closed":

1. **Double-check the password:**
   - Log in to Mailgun
   - Reset SMTP password again
   - Make sure you're copying the full password

2. **Verify it's set:**
   - Check your hosting dashboard
   - Look for MAIL_PASSWORD_DAVID variable
   - Make sure it's not truncated

3. **Check the username:**
   - Should be: postmaster@mg.fieldsprout.io
   - NOT your personal email address

4. **View app logs:**
   - Look for authentication errors
   - Check for detailed error messages

---

## Test Locally (Optional)

To test on your local machine:

```bash
export MAIL_SERVER=smtp.mailgun.org
export MAIL_PORT=587
export MAIL_USE_TLS=true
export MAIL_USE_SSL=false
export MAIL_USERNAME_DAVID=postmaster@mg.fieldsprout.io
export MAIL_PASSWORD_DAVID=your-smtp-password

python3 test_smtp_verbose.py
```

This will show exactly what's happening during the SMTP connection.
