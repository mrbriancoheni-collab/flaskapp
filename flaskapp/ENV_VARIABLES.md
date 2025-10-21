# Environment Variables Documentation

Complete reference for all environment variables used in the FieldSprout application.

## Table of Contents
- [Core Application](#core-application)
- [Database](#database)
- [Security & Authentication](#security--authentication)
- [Email](#email)
- [Stripe Billing](#stripe-billing)
- [Google Integrations](#google-integrations)
- [Encryption](#encryption)
- [Background Jobs](#background-jobs)
- [Optional Features](#optional-features)

---

## Core Application

### `SECRET_KEY` (Required)
**Description:** Flask secret key for session encryption and CSRF protection
**Example:** `your-secret-key-change-this-in-production`
**Generation:**
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```
**⚠️ Critical:** Must be changed in production and kept secret

### `BASE_URL` (Optional)
**Description:** Base URL of your application (for email links, webhooks, etc.)
**Example:** `https://app.fieldsprout.com`
**Default:** Empty string
**Notes:** Required for proper email links and OAuth callbacks

---

## Database

### `SQLALCHEMY_DATABASE_URI` (Required)
**Description:** Database connection string
**Format:** `mysql://username:password@host:port/database`
**Example:** `mysql://root:password@localhost:3306/fieldsprout`
**Notes:**
- Supports MySQL/MariaDB
- URL-encode special characters in password
- Use connection pooling for production: `?pool_size=10&max_overflow=20`

**Production Example:**
```
mysql://fs_user:SecurePass123!@db.example.com:3306/fieldsprout_prod?charset=utf8mb4
```

---

## Security & Authentication

### `APP_FERNET_KEY` (Required for Encryption)
**Description:** Encryption key for sensitive data (API credentials, OAuth tokens)
**Example:** `vL8Km9x_2nJ4p...` (44-character base64 string)
**Generation:**
```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```
**⚠️ Critical:**
- Required if you use credential encryption
- Changing this key will make existing encrypted data unreadable
- Store in secure vault (AWS Secrets Manager, HashiCorp Vault, etc.)

### Password Policy Configuration

#### `PASSWORD_MIN_LENGTH`
**Default:** 12
**Description:** Minimum password length

#### `PASSWORD_REQUIRE_UPPER`
**Default:** True
**Description:** Require uppercase letters

#### `PASSWORD_REQUIRE_LOWER`
**Default:** True
**Description:** Require lowercase letters

#### `PASSWORD_REQUIRE_DIGIT`
**Default:** True
**Description:** Require numbers

#### `PASSWORD_REQUIRE_SPECIAL`
**Default:** True
**Description:** Require special characters

---

## Email

### Email Provider Configuration

#### `EMAIL_PROVIDER`
**Description:** Email service provider
**Options:** `smtp` or `sendgrid`
**Default:** `smtp`

#### `EMAIL_FROM`
**Description:** Sender email address
**Example:** `noreply@fieldsprout.com`
**Default:** `noreply@fieldsprout.com`

#### `EMAIL_FROM_NAME`
**Description:** Sender display name
**Example:** `FieldSprout`
**Default:** `FieldSprout`

### SMTP Configuration (if EMAIL_PROVIDER=smtp)

#### `SMTP_HOST`
**Description:** SMTP server hostname
**Example:** `smtp.gmail.com`, `smtp.sendgrid.net`, `smtp.mailgun.org`
**Default:** `localhost`

#### `SMTP_PORT`
**Description:** SMTP server port
**Common Values:**
- `587` - TLS (recommended)
- `465` - SSL
- `25` - Unencrypted (not recommended)
**Default:** `587`

#### `SMTP_USER`
**Description:** SMTP username/email
**Example:** `your-email@gmail.com`
**Default:** Empty

#### `SMTP_PASSWORD`
**Description:** SMTP password or app-specific password
**Example:** `your-app-specific-password`
**Default:** Empty
**Notes:** For Gmail, use App Passwords: https://myaccount.google.com/apppasswords

#### `SMTP_USE_TLS`
**Description:** Use TLS encryption
**Options:** `true` or `false`
**Default:** `true`
**Notes:** Use `true` for port 587, `false` for port 465 with SSL

### SendGrid Configuration (if EMAIL_PROVIDER=sendgrid)

#### `SENDGRID_API_KEY`
**Description:** SendGrid API key
**Example:** `SG.abc123...`
**Where to get:** https://app.sendgrid.com/settings/api_keys
**Default:** Empty

**SendGrid Setup:**
```bash
pip install sendgrid
export SENDGRID_API_KEY="your-api-key"
export EMAIL_PROVIDER="sendgrid"
```

---

## Stripe Billing

### Required Keys

#### `STRIPE_SECRET_KEY`
**Description:** Stripe secret API key
**Example:** `sk_live_...` or `sk_test_...`
**Where to get:** https://dashboard.stripe.com/apikeys
**⚠️ Critical:** Use `sk_test_*` for development, `sk_live_*` for production

#### `STRIPE_PUBLISHABLE_KEY`
**Description:** Stripe publishable API key
**Example:** `pk_live_...` or `pk_test_...`
**Where to get:** https://dashboard.stripe.com/apikeys
**Notes:** Safe to expose in frontend

#### `STRIPE_WEBHOOK_SECRET`
**Description:** Stripe webhook signing secret
**Example:** `whsec_...`
**Where to get:** https://dashboard.stripe.com/webhooks
**Notes:**
- Create webhook endpoint: `https://your-domain.com/stripe/webhook`
- Listen for: `customer.subscription.*`, `invoice.*`

### Price Configuration

#### `STRIPE_MONTHLY_PRICE_ID`
**Description:** Stripe price ID for monthly plan
**Example:** `price_1ABC123...`
**Where to get:** https://dashboard.stripe.com/products
**Notes:** Create a recurring price for your product

#### `STRIPE_YEARLY_PRICE_ID`
**Description:** Stripe price ID for annual plan
**Example:** `price_1XYZ789...`
**Where to get:** https://dashboard.stripe.com/products

### Checkout URLs

#### `STRIPE_SUCCESS_URL`
**Description:** Redirect URL after successful checkout
**Default:** `/account/dashboard?payment=success`
**Example:** `/billing/success`

#### `STRIPE_CANCEL_URL`
**Description:** Redirect URL if checkout is canceled
**Default:** `/account/dashboard?payment=cancelled`
**Example:** `/billing/choose-plan`

---

## Google Integrations

### Google Ads API

#### `GOOGLE_ADS_DEVELOPER_TOKEN`
**Description:** Google Ads API developer token
**Example:** `abc123def456...`
**Where to get:** https://ads.google.com/aw/apicenter

#### `GOOGLE_ADS_CLIENT_ID`
**Description:** OAuth 2.0 client ID
**Example:** `123456789-abcdef.apps.googleusercontent.com`
**Where to get:** https://console.cloud.google.com/apis/credentials

#### `GOOGLE_ADS_CLIENT_SECRET`
**Description:** OAuth 2.0 client secret
**Example:** `GOCSPX-...`
**Where to get:** https://console.cloud.google.com/apis/credentials

#### `GOOGLE_ADS_REDIRECT_URI`
**Description:** OAuth callback URL
**Example:** `https://app.fieldsprout.com/oauth/google-ads/callback`
**Default:** `http://localhost:8000/oauth/google-ads/callback`
**Notes:** Must match authorized redirect URI in Google Cloud Console

#### `GOOGLE_ADS_LOGIN_CUSTOMER_ID`
**Description:** Manager account customer ID (without dashes)
**Example:** `1234567890`
**Format:** 10 digits, no dashes
**Notes:** Only needed if using MCC account

### Google OAuth Scopes

#### `GOOGLE_OAUTH_SCOPES`
**Description:** Comma-separated list of OAuth scopes
**Default:** `https://www.googleapis.com/auth/webmasters.readonly`
**Example:**
```
https://www.googleapis.com/auth/webmasters.readonly,https://www.googleapis.com/auth/analytics.readonly
```

### Google Business Profile / GMB

#### `GMB_INSIGHTS_MAX_PER_RUN`
**Description:** Maximum accounts to process per daily insights run
**Default:** 25

#### `GMB_INSIGHTS_INTERVAL_DAYS`
**Description:** Minimum days between insights updates per account
**Default:** 27

---

## Encryption

### `APP_FERNET_KEY` (See Security section)
Used for encrypting:
- Google OAuth refresh tokens
- Google Ads API credentials
- Any other sensitive API keys

**Migration:** Run this script after setting the key:
```bash
python migrate_encrypt_credentials.py --dry-run  # Preview
python migrate_encrypt_credentials.py            # Encrypt existing data
```

---

## Background Jobs

### `SCHEDULER_MAX_WORKERS`
**Description:** Maximum concurrent background job threads
**Default:** 3
**Recommendations:**
- Development: 1-2
- Small production: 3-5
- Large production: 10-20

**Notes:** Uses APScheduler with SQLAlchemy backend (no Redis required)

### `AUDIT_LOG_RETENTION_DAYS`
**Description:** Number of days to keep audit logs
**Default:** 90
**Notes:** Old logs are automatically deleted weekly

---

## Optional Features

### OpenAI Integration

#### `OPENAI_API_KEY`
**Description:** OpenAI API key for AI features
**Example:** `sk-...`
**Where to get:** https://platform.openai.com/api-keys
**Features:** AI campaign suggestions, content optimization

### Account/Plan Configuration

#### `ACCOUNT_STRIPE_FIELD`
**Description:** Database field to check for Stripe status
**Default:** `stripe_status`

#### `PAID_STRIPE_STATES`
**Description:** Comma-separated list of statuses considered "paid"
**Default:** `active,trialing`
**Example:** `active,trialing,past_due`

---

## Complete Example: Production .env File

```bash
# Core
SECRET_KEY=generated-secret-key-64-characters-long-change-this
BASE_URL=https://app.fieldsprout.com

# Database
SQLALCHEMY_DATABASE_URI=mysql://fs_user:SecurePassword123!@db-prod.internal:3306/fieldsprout?charset=utf8mb4&pool_size=10

# Encryption
APP_FERNET_KEY=vL8Km9x_2nJ4pQrT5wY8zA1bC3dE6fG7hI9jK0lM2nO=

# Email (SendGrid)
EMAIL_PROVIDER=sendgrid
SENDGRID_API_KEY=SG.abc123def456ghi789jkl012mno345pqr.678stu901vwx234yz
EMAIL_FROM=noreply@fieldsprout.com
EMAIL_FROM_NAME=FieldSprout

# Stripe
STRIPE_SECRET_KEY=sk_live_51ABC...
STRIPE_PUBLISHABLE_KEY=pk_live_51ABC...
STRIPE_WEBHOOK_SECRET=whsec_123abc...
STRIPE_MONTHLY_PRICE_ID=price_1monthly123
STRIPE_YEARLY_PRICE_ID=price_1annual456
STRIPE_SUCCESS_URL=/billing/success
STRIPE_CANCEL_URL=/billing/choose-plan

# Google Ads
GOOGLE_ADS_DEVELOPER_TOKEN=your-developer-token
GOOGLE_ADS_CLIENT_ID=123456-abc.apps.googleusercontent.com
GOOGLE_ADS_CLIENT_SECRET=GOCSPX-secret
GOOGLE_ADS_REDIRECT_URI=https://app.fieldsprout.com/oauth/google-ads/callback

# Background Jobs
SCHEDULER_MAX_WORKERS=5
AUDIT_LOG_RETENTION_DAYS=90

# Optional
OPENAI_API_KEY=sk-proj-abc123...
```

---

## Complete Example: Development .env File

```bash
# Core
SECRET_KEY=dev-secret-key-change-for-production
BASE_URL=http://localhost:5000

# Database
SQLALCHEMY_DATABASE_URI=mysql://root:password@localhost:3306/fieldsprout_dev

# Encryption (Generate your own!)
APP_FERNET_KEY=generate-using-fernet-generate-key-command

# Email (SMTP with Gmail)
EMAIL_PROVIDER=smtp
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-email@gmail.com
SMTP_PASSWORD=your-app-specific-password
SMTP_USE_TLS=true
EMAIL_FROM=your-email@gmail.com
EMAIL_FROM_NAME=FieldSprout Dev

# Stripe (Test mode)
STRIPE_SECRET_KEY=sk_test_51ABC...
STRIPE_PUBLISHABLE_KEY=pk_test_51ABC...
STRIPE_WEBHOOK_SECRET=whsec_test_...
STRIPE_MONTHLY_PRICE_ID=price_test_monthly
STRIPE_YEARLY_PRICE_ID=price_test_annual

# Google Ads (Test)
GOOGLE_ADS_CLIENT_ID=test-client-id.apps.googleusercontent.com
GOOGLE_ADS_CLIENT_SECRET=test-secret
GOOGLE_ADS_REDIRECT_URI=http://localhost:5000/oauth/google-ads/callback

# Background Jobs (Minimal for dev)
SCHEDULER_MAX_WORKERS=1
```

---

## Security Best Practices

1. **Never commit .env files to git**
   - Add `.env` to `.gitignore`
   - Use `.env.example` as template

2. **Use different keys for each environment**
   - Development, staging, production should have unique keys

3. **Rotate secrets regularly**
   - API keys: Every 90 days
   - Stripe keys: Annually or when team members leave
   - Database passwords: Quarterly

4. **Use secret management services**
   - AWS Secrets Manager
   - Azure Key Vault
   - HashiCorp Vault
   - Doppler

5. **Limit access**
   - Only give production keys to necessary personnel
   - Use read-only keys where possible
   - Enable 2FA on all service accounts

---

## Troubleshooting

### Email not sending?
1. Check `SMTP_HOST` and `SMTP_PORT` are correct
2. Verify `SMTP_USER` and `SMTP_PASSWORD` are set
3. For Gmail, use App Passwords, not your regular password
4. Check logs: `tail -f logs/error.log | grep email`

### Stripe webhooks failing?
1. Verify `STRIPE_WEBHOOK_SECRET` matches Dashboard
2. Check webhook URL is publicly accessible
3. Test with Stripe CLI: `stripe listen --forward-to localhost:5000/stripe/webhook`

### Background jobs not running?
1. Check `APScheduler` is installed: `pip install apscheduler`
2. Verify database connection works
3. Check logs: `tail -f logs/app.log | grep scheduler`

### Encryption errors?
1. Ensure `APP_FERNET_KEY` is set
2. Key must be valid Fernet key (44 characters, base64)
3. Run migration script: `python migrate_encrypt_credentials.py`

---

## Support

For questions or issues:
- Documentation: https://docs.fieldsprout.com
- Support: support@fieldsprout.com
- GitHub Issues: https://github.com/your-org/fieldsprout/issues
