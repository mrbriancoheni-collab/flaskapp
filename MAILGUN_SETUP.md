# Mailgun Email Configuration for FieldSprout

## Current Status

Your Mailgun account is set up with domain: **mg.fieldsprout.io**

- **Mailgun API Key**: `f160ce6d************` (stored securely)
- **Mailgun Domain**: `mg.fieldsprout.io`
- **Base URL**: `https://api.mailgun.net`

## 🔧 SMTP Configuration (Recommended)

FieldSprout is configured to use **SMTP** (not REST API) for email sending. This provides better compatibility with all email features.

### Required Environment Variables

```bash
# Mailgun SMTP Settings
export MAIL_SERVER='smtp.mailgun.org'
export MAIL_PORT='587'                    # Use 587 for STARTTLS
export MAIL_USE_TLS='true'                # Required for port 587
export MAIL_USE_SSL='false'               # Must be false for port 587

# Mailgun SMTP Credentials (NOT the API key!)
# Get these from: https://app.mailgun.com/app/sending/domains/mg.fieldsprout.io
export MAIL_USERNAME_DAVID='postmaster@mg.fieldsprout.io'
export MAIL_PASSWORD_DAVID='[YOUR_SMTP_PASSWORD_HERE]'

# Default sender
export MAIL_DEFAULT_SENDER='noreply@mg.fieldsprout.io'
export MAIL_FROM='noreply@mg.fieldsprout.io'
```

### ⚠️ Important: API Key vs SMTP Password

**These are DIFFERENT credentials:**

1. **Mailgun API Key**: `f160ce6dc8a102e7ca2e5c9d05edef95...`
   - Used for: REST API calls
   - Not used by FieldSprout (we use SMTP)

2. **SMTP Password**: (You need to get this)
   - Used for: SMTP email sending
   - Found at: https://app.mailgun.com/app/sending/domains/mg.fieldsprout.io
   - Look for "SMTP Credentials" section
   - Click "Reset Password" if you don't have it

### How to Get Your SMTP Password

1. Go to: https://app.mailgun.com/app/sending/domains/mg.fieldsprout.io
2. Scroll to **"SMTP Credentials"** section
3. You'll see username: `postmaster@mg.fieldsprout.io`
4. Click **"Reset Password"** to generate a new SMTP password
5. Copy that password to `MAIL_PASSWORD_DAVID`

## 📧 Sending from @fieldsprout.io (Not @mg.fieldsprout.io)

To send emails from **@fieldsprout.io** addresses (instead of @mg.fieldsprout.io):

### Step 1: Add fieldsprout.io as a Domain in Mailgun

1. Go to: https://app.mailgun.com/app/sending/domains/new
2. Add domain: `fieldsprout.io`
3. Choose "US" region (or EU if preferred)

### Step 2: Configure DNS Records

Add these DNS records to your `fieldsprout.io` domain at your DNS provider (Cloudflare, Route53, etc.):

```
# SPF Record (for email authentication)
Type: TXT
Name: fieldsprout.io
Value: v=spf1 include:mailgun.org ~all

# DKIM Records (2 records - Mailgun will give you exact values)
Type: TXT
Name: smtp._domainkey.fieldsprout.io
Value: [Mailgun will provide this - starts with k=rsa; p=...]

Type: TXT
Name: k1._domainkey.fieldsprout.io
Value: [Mailgun will provide this - starts with k=rsa; p=...]

# MX Records (for receiving email - optional)
Type: MX
Name: fieldsprout.io
Priority: 10
Value: mxa.mailgun.org

Type: MX
Name: fieldsprout.io
Priority: 10
Value: mxb.mailgun.org

# Tracking Domain (optional - for click/open tracking)
Type: CNAME
Name: email.fieldsprout.io
Value: mailgun.org
```

**Important**: Mailgun will show you the **exact DNS records** to add when you set up the domain. Use those values!

### Step 3: Verify Domain

1. After adding DNS records, wait 5-10 minutes for DNS propagation
2. In Mailgun dashboard, click **"Verify DNS Settings"**
3. Once verified, you can send from `@fieldsprout.io` addresses

### Step 4: Update Environment Variables

```bash
# After fieldsprout.io is verified, update these:
export MAIL_USERNAME_DAVID='brian@fieldsprout.io'  # or any email@fieldsprout.io
export MAIL_DEFAULT_SENDER='noreply@fieldsprout.io'
export MAIL_FROM='noreply@fieldsprout.io'
```

## 🧪 Testing Your Configuration

### Test 1: Check Current Settings

```bash
cd /home/user/flaskapp
python3 test_smtp_connection.py
```

This will:
- Show your current configuration
- Test the SMTP connection
- Verify authentication
- Provide specific error guidance if it fails

### Test 2: Send Test Email from Admin Panel

1. Go to: https://fieldsprout.io/admin/test-email
2. Enter your email address
3. Click "Send Test Email"
4. Check your inbox (and spam folder)

## 📊 Email Sending Summary

| Email Type | Sender | Credentials Used |
|------------|--------|------------------|
| Login/Verification | System | `MAIL_USERNAME_DAVID` |
| Team Invites | System | `MAIL_USERNAME_DAVID` |
| CRM Bulk Emails | David | `MAIL_USERNAME_DAVID` |
| Individual CRM Emails | Logged-in User | User's email (authenticated with David credentials) |
| Test Emails | Logged-in Admin | Admin's email (authenticated with David credentials) |

## 🔍 Current Email Sending Code

All email sending in FieldSprout now uses Mailgun SMTP:

1. **`app/emailer.py`** - Core email function (✓ Fixed)
2. **`app/auth/email_utils.py`** - Auth emails (✓ Fixed)
3. **`app/services/email_service.py`** - CRM & bulk emails (✓ Fixed)
4. **`app/test_email.py`** - Test email UI (✓ Fixed)

All files now support both port 587 (STARTTLS) and port 465 (SSL) with auto-correction.

## ⚡ Quick Start Checklist

- [ ] Get SMTP password from Mailgun dashboard
- [ ] Set `MAIL_USERNAME_DAVID` and `MAIL_PASSWORD_DAVID` environment variables
- [ ] Set `MAIL_USE_TLS=true` and `MAIL_USE_SSL=false` (for port 587)
- [ ] Run `python3 test_smtp_connection.py` to verify
- [ ] Send test email from admin panel
- [ ] (Optional) Add `fieldsprout.io` domain to Mailgun for @fieldsprout.io sending
- [ ] (Optional) Configure DNS records for fieldsprout.io

## 🆘 Troubleshooting

### Error: "SSL: WRONG_VERSION_NUMBER"
- **Cause**: Port/TLS mismatch
- **Fix**: Ensure `MAIL_USE_SSL=false` for port 587

### Error: "Authentication failed"
- **Cause**: Wrong SMTP password (API key doesn't work for SMTP!)
- **Fix**: Get SMTP password from Mailgun dashboard

### Error: "Connection refused"
- **Cause**: Wrong host or port, or firewall blocking
- **Fix**: Verify `MAIL_SERVER='smtp.mailgun.org'` and `MAIL_PORT='587'`

### Emails sent from @mg.fieldsprout.io instead of @fieldsprout.io
- **Cause**: DNS not configured for fieldsprout.io
- **Fix**: Follow "Sending from @fieldsprout.io" section above

## 📚 Resources

- [Mailgun Dashboard](https://app.mailgun.com/)
- [Mailgun SMTP Documentation](https://documentation.mailgun.com/en/latest/user_manual.html#smtp)
- [Mailgun DNS Setup Guide](https://documentation.mailgun.com/en/latest/user_manual.html#verifying-your-domain)

## 💡 Pro Tips

1. **Use port 587**, not 465 - Better firewall compatibility
2. **Keep API key separate** - It's not used for SMTP, store it for future API use
3. **Verify DNS first** - Don't try to send from @fieldsprout.io until DNS is verified
4. **Monitor sending** - Check Mailgun dashboard for delivery stats and bounces
5. **Set up webhooks** - Mailgun can notify your app about opens, clicks, bounces (see `/admin/email-tracking`)
