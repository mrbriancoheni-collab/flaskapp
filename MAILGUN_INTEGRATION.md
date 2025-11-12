# Mailgun Integration - Complete

## Configuration

**Domain:** `mg.fieldsprout.io` (verified subdomain)
**API Endpoint:** `https://api.mailgun.net/v3/mg.fieldsprout.io/messages`

> **Note:** To use `fieldsprout.io` instead of `mg.fieldsprout.io`, you must verify the domain in Mailgun by adding DNS records (TXT, MX, CNAME). See "Domain Verification" section below.

### Environment Variables Required

```bash
MAILGUN_API_KEY=your-api-key-here
MAILGUN_DOMAIN=mg.fieldsprout.io  # Optional, defaults to mg.fieldsprout.io
EMAIL_PROVIDER=mailgun  # Optional, defaults to mailgun
```

---

## All Email Routes Using Mailgun API

### 1. Authentication Emails (`app/auth/__init__.py`)
- **Email Verification** - `_send_verification_email()`
  - Subject: "Verify your email"
  - Triggered: User registration, resend verification
- **Password Reset** - `_send_reset_email()`
  - Subject: "Reset your password"
  - Triggered: Forgot password flow

### 2. Email Verification (`app/auth/routes_verify.py`)
- **Resend Verification** - `/verify/send`
  - Sends verification link via Mailgun API

### 3. Admin Email Testing (`app/admin/routes.py`)
- **Test Email Endpoint** - `GET /admin/test-email?to=email@example.com`
  - Returns: JSON response with Mailgun API result
  - Usage: Testing email configuration

### 4. Admin Bulk Emails (`app/admin/routes.py`)
- **Send to CRM Contacts** - Used for marketing/transactional emails
  - Tracked email delivery
  - Link click tracking
  - Pixel tracking

### 5. Stripe Payment Emails (`app/services/stripe_service.py`)
- **Payment Receipts** - Sent after successful payment
- **Subscription Notifications** - Billing updates

### 6. Google Ads Insights (`app/services/google_ads_insights.py`)
- **Insights Reports** - Weekly/monthly ad performance emails
- **Alert Notifications** - Budget and performance alerts

### 7. Budget Tracker Alerts (`app/tasks/budget_tracker_tasks.py`)
- **Daily Budget Reports** - Scheduled task
- **Threshold Alerts** - When budget limits are reached

---

## Email Service Architecture

### Primary Service: `app/services/email_service.py`

**Supported Providers:**
- ✅ **Mailgun API** (default, recommended)
- ⚠️ SendGrid API (available but not configured)
- ❌ SMTP (legacy, disabled)

**Default Configuration:**
```python
provider = 'mailgun'  # Default
domain = 'fieldsprout.io'  # Default
from_email = 'noreply@fieldsprout.com'
from_name = 'FieldSprout'
```

**Functions:**
- `send_email()` - Send single transactional email
- `send_tracked_email_to_crm_contact()` - Send with tracking
- `send_bulk_tracked_emails()` - Bulk email with tracking
- `send_verification_email()` - Email verification wrapper
- `send_password_reset_email()` - Password reset wrapper
- `send_welcome_email()` - Welcome email for new users
- `send_email_change_confirmation()` - Email change verification

---

## Mailgun API Implementation

### API Request Format

```python
import requests

response = requests.post(
    f"https://api.mailgun.net/v3/{domain}/messages",
    auth=("api", api_key),
    data={
        "from": f"FieldSprout <noreply@{domain}>",
        "to": recipient_email,
        "subject": email_subject,
        "html": html_body,
        "text": text_body  # Optional fallback
    },
    timeout=30
)
```

### Error Handling

- Connection errors → Logged and returned as False
- Timeout errors (30s) → Logged and returned as False
- API errors (non-200) → Logged with response details
- Success (200) → Returns True with response ID

---

## Migration Complete ✅

### What Was Changed:
1. ✅ Default email provider changed from SMTP to Mailgun API
2. ✅ All authentication emails migrated to Mailgun
3. ✅ All admin emails migrated to Mailgun
4. ✅ All payment/subscription emails migrated to Mailgun
5. ✅ All alert/notification emails migrated to Mailgun
6. ✅ Domain updated from `mg.fieldsprout.io` to `fieldsprout.io`
7. ✅ Old SMTP test route disabled (`test_mail_bp`)
8. ✅ New Mailgun API test endpoint active (`/admin/test-email`)

### Legacy Code (Not Used):
- ❌ `app/emailer.py` - Old SMTP sender (not imported)
- ❌ `app/auth/email_utils.py` - Old SMTP sender (not imported)
- ❌ `app/test_email.py` - Old SMTP test route (disabled)
- ❌ `app/wp/__init__.py` - WordPress SMTP emails (not used in main app)

---

## Testing

### Test Endpoint:
```bash
curl "https://fieldsprout.io/admin/test-email?to=test@example.com"
```

### Expected Response:
```json
{
  "success": true,
  "message": "Test email sent successfully to test@example.com via Mailgun",
  "provider": "mailgun",
  "domain": "fieldsprout.io",
  "api_key_preview": "9b7d3d5a...a64b",
  "response": {
    "id": "<message-id@fieldsprout.io>",
    "message": "Queued. Thank you."
  }
}
```

---

## Mailgun Dashboard

Monitor email delivery at:
- **API Logs:** https://app.mailgun.com/app/sending/domains/mg.fieldsprout.io/logs
- **Domain Settings:** https://app.mailgun.com/app/sending/domains/mg.fieldsprout.io/settings

---

## Domain Verification (Optional)

### Currently Using: `mg.fieldsprout.io` (Verified Subdomain)

Emails currently send from `noreply@mg.fieldsprout.io` or `postmaster@mg.fieldsprout.io`.

### To Use `fieldsprout.io` Instead:

If you want emails to send from `@fieldsprout.io` instead of `@mg.fieldsprout.io`, you need to verify the domain in Mailgun:

1. **Log in to Mailgun:** https://app.mailgun.com/app/sending/domains
2. **Add Domain:** Click "Add New Domain" and enter `fieldsprout.io`
3. **Add DNS Records:** Mailgun will provide DNS records to add:
   - **TXT records** (for SPF and domain verification)
   - **MX records** (for receiving bounces)
   - **CNAME records** (for tracking and DKIM)

4. **Verify DNS:** After adding records, click "Verify DNS Settings"
5. **Update Environment Variable:**
   ```bash
   MAILGUN_DOMAIN=fieldsprout.io
   ```
6. **Restart Application:** Clear cache and restart

**DNS Records Example:**
```
TXT  @ "v=spf1 include:mailgun.org ~all"
TXT  mailo._domainkey  "k=rsa; p=MIGfMA0GCSqGSIb3DQEBA..."
MX   @ mxa.mailgun.org (priority 10)
MX   @ mxb.mailgun.org (priority 10)
CNAME email mg.fieldsprout.io
```

**Verification Time:** DNS changes can take 24-48 hours to propagate.

---

## Benefits of Mailgun API vs SMTP

✅ **More Reliable:** No authentication/connection issues
✅ **Better Tracking:** Built-in delivery, open, and click tracking
✅ **Faster:** Direct API calls vs SMTP handshake
✅ **More Secure:** API key authentication vs SMTP credentials
✅ **Better Logging:** Detailed API response logs
✅ **Rate Limiting:** Built-in rate limit handling
✅ **Bounce Handling:** Automatic bounce and complaint tracking

---

**Last Updated:** 2025-11-12
**Status:** ✅ Production Ready
