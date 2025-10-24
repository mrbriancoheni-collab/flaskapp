# Sentry Error Tracking Setup Guide

Complete guide to setting up Sentry for error tracking, performance monitoring, and alerting.

## Table of Contents
- [Quick Start](#quick-start)
- [Installation](#installation)
- [Configuration](#configuration)
- [Features](#features)
- [Dashboard Setup](#dashboard-setup)
- [Alerting](#alerting)
- [Best Practices](#best-practices)
- [Troubleshooting](#troubleshooting)

---

## Quick Start

### 1. Create Sentry Account

1. Go to https://sentry.io/signup/
2. Choose "Create a new organization" or use existing
3. Create a new project:
   - Platform: **Flask**
   - Alert frequency: **On every new issue**
   - Name: `fieldsprout-production` (or your app name)

### 2. Get Your DSN

After creating the project, you'll see your DSN:
```
https://abc123def456@o123456.ingest.sentry.io/789012
```

**⚠️ Keep this secret!** This is your project's unique identifier.

### 3. Configure Environment

Add to your `.env` file:

```bash
# Sentry Configuration
SENTRY_DSN=https://abc123def456@o123456.ingest.sentry.io/789012
SENTRY_ENVIRONMENT=production  # or 'staging', 'development'
SENTRY_TRACES_SAMPLE_RATE=0.1  # 10% of requests (adjust for traffic)
```

### 4. Install and Restart

```bash
pip install sentry-sdk[flask]
# Restart your application
```

That's it! Errors will now be tracked automatically.

---

## Installation

### Requirements

```bash
pip install sentry-sdk[flask]>=1.40
```

This installs:
- `sentry-sdk` - Core Sentry SDK
- Flask integration
- SQLAlchemy integration
- Logging integration

### Verify Installation

```python
python -c "import sentry_sdk; print(sentry_sdk.VERSION)"
```

Should output: `1.40.0` or higher

---

## Configuration

### Environment Variables

#### Required

**`SENTRY_DSN`**
- Your Sentry project DSN
- Example: `https://abc123@o123456.ingest.sentry.io/789012`
- Where to find: Project Settings → Client Keys (DSN)

#### Optional

**`SENTRY_ENVIRONMENT`**
- Environment name for filtering/grouping
- Options: `production`, `staging`, `development`, `qa`
- Default: `production`
- **Best Practice:** Use different DSNs for each environment

**`SENTRY_RELEASE`**
- Release version or git commit hash
- Example: `fieldsprout@1.0.0` or git commit SHA
- Enables:
  - Release tracking
  - Regression detection
  - Deploy tracking
- Auto-detected from `GIT_COMMIT` env var

**`SENTRY_TRACES_SAMPLE_RATE`**
- Percentage of requests to track for performance
- Range: `0.0` to `1.0`
- Examples:
  - `1.0` - 100% (good for low traffic)
  - `0.1` - 10% (recommended for production)
  - `0.01` - 1% (high traffic apps)
- Default: `0.1`

**`SENTRY_PROFILES_SAMPLE_RATE`**
- Percentage of traced requests to profile
- Range: `0.0` to `1.0`
- Default: `0.1`
- **Note:** Profiling adds overhead, keep low

**`SENTRY_SAMPLE_RATE`**
- Percentage of error events to send
- Range: `0.0` to `1.0`
- Default: `1.0` (send all errors)
- **Use Case:** Rate limiting for very high error volumes

### Configuration Examples

#### Development
```bash
# .env.development
SENTRY_DSN=https://dev-key@sentry.io/dev-project
SENTRY_ENVIRONMENT=development
SENTRY_TRACES_SAMPLE_RATE=1.0  # Track all requests
SENTRY_PROFILES_SAMPLE_RATE=0.5
```

#### Staging
```bash
# .env.staging
SENTRY_DSN=https://staging-key@sentry.io/staging-project
SENTRY_ENVIRONMENT=staging
SENTRY_RELEASE=${GIT_COMMIT}
SENTRY_TRACES_SAMPLE_RATE=0.5  # Track 50%
```

#### Production
```bash
# .env.production
SENTRY_DSN=https://prod-key@sentry.io/prod-project
SENTRY_ENVIRONMENT=production
SENTRY_RELEASE=${GIT_COMMIT}
SENTRY_TRACES_SAMPLE_RATE=0.1  # Track 10%
SENTRY_PROFILES_SAMPLE_RATE=0.05  # Profile 5%
```

---

## Features

### 1. Automatic Error Tracking

All unhandled exceptions are automatically captured:

```python
# This error will be automatically sent to Sentry
def broken_endpoint():
    return 1 / 0  # ZeroDivisionError caught and reported
```

### 2. Manual Error Reporting

```python
from app.monitoring import capture_exception, capture_message

try:
    risky_operation()
except Exception as e:
    capture_exception(e, extra_context={
        "operation": "user_checkout",
        "user_id": user.id,
        "cart_total": 99.99
    })
```

### 3. Contextual Messages

```python
from app.monitoring import capture_message

capture_message(
    "Suspicious login attempt detected",
    level="warning",
    extra_context={
        "ip": request.remote_addr,
        "username": username,
        "attempts": 5
    }
)
```

### 4. Breadcrumbs (User Activity Trail)

```python
from app.monitoring import add_breadcrumb

# Track user actions leading up to errors
add_breadcrumb(
    message="User viewed pricing page",
    category="navigation",
    level="info"
)

add_breadcrumb(
    message="User clicked 'Subscribe' button",
    category="ui",
    data={"plan": "monthly", "price": 99}
)

# If an error occurs, breadcrumbs show the path
```

### 5. Performance Monitoring

#### Automatic Transaction Tracking

All HTTP requests are automatically tracked:
- Request duration
- Database queries
- External API calls
- Response status codes

#### Manual Transaction Tracking

```python
from app.monitoring import start_transaction

with start_transaction(name="checkout.process_payment", op="task") as transaction:
    validate_cart()
    charge_customer()
    send_confirmation_email()
```

#### Detailed Span Tracking

```python
from app.monitoring import start_span

with start_span("stripe.api", "Create Stripe customer"):
    customer = stripe.Customer.create(...)

with start_span("db.query", "Fetch user subscriptions"):
    subscriptions = Subscription.query.filter_by(user_id=user_id).all()
```

#### Decorator for Functions

```python
from app.monitoring import monitor_performance

@monitor_performance("email.send_invitation")
def send_team_invite(email, role):
    # Function execution time is tracked
    ...
```

### 6. User Context

User information is automatically attached to all errors:

```python
# Happens automatically when user is logged in
{
    "id": "12345",
    "email": "user@example.com",
    "username": "John Doe",
    "account": {
        "id": 67890,
        "role": "admin"
    }
}
```

Manual user context:

```python
from app.monitoring import set_user_context

set_user_context(
    user_id="12345",
    email="user@example.com",
    subscription="pro"
)
```

---

## Dashboard Setup

### 1. Project Configuration

#### General Settings
- **Project Name:** `FieldSprout Production`
- **Platform:** Flask
- **Default Environment:** production

#### Data Scrubbing
- Enable "Scrub sensitive data"
- Add custom patterns:
  - `password`
  - `api_key`
  - `token`
  - `secret`
  - `ssn`
  - `credit_card`

#### Issue Grouping
- **Grouping Algorithm:** Fingerprint
- **Custom Fingerprinting:** Enabled (handled in code)

### 2. Performance Monitoring

Navigate to **Performance** tab:

#### Transaction Settings
- **Retention:** 90 days
- **Aggregation:** By transaction name
- **Percentile Charts:** P50, P75, P95, P99

#### Threshold Alerts
Set alerts for slow transactions:
- **Database queries:** > 1 second
- **External API calls:** > 3 seconds
- **Page load time:** > 5 seconds

### 3. Release Tracking

Enable releases in Project Settings:

```bash
# Install Sentry CLI
npm install -g @sentry/cli

# Configure
export SENTRY_AUTH_TOKEN=your-auth-token
export SENTRY_ORG=your-org
export SENTRY_PROJECT=fieldsprout-production

# Create release on deploy
sentry-cli releases new $(git rev-parse HEAD)
sentry-cli releases set-commits $(git rev-parse HEAD) --auto
sentry-cli releases finalize $(git rev-parse HEAD)

# Associate deploys
sentry-cli releases deploys $(git rev-parse HEAD) new -e production
```

Or in your deployment script:

```python
import sentry_sdk

sentry_sdk.set_tag("deployment", "v1.2.3")
```

---

## Alerting

### 1. Alert Rules

Navigate to **Alerts** → **Create Alert Rule**

#### Critical Errors (Immediate)
```
Type: Issues
Condition: When an event is seen
  AND: Event Level is equal to fatal OR error
  AND: Event Environment is equal to production
Action: Send notification to #alerts-critical (Slack)
```

#### New Issue (First Occurrence)
```
Type: Issues
Condition: When an event is first seen
Action:
  - Email: ops@fieldsprout.com
  - Slack: #bugs
```

#### High Error Rate
```
Type: Metric Alert
Condition: Number of errors
  - Is above 100
  - In 5 minutes
Action: PagerDuty incident (Critical)
```

#### Performance Degradation
```
Type: Metric Alert
Condition: P95 duration
  - Is above 3000ms
  - In 10 minutes
Action: Email team
```

#### Payment Failures
```
Type: Issues
Condition: Event message contains "payment_failed"
  OR: Event tags payment_status equals failed
Action:
  - Slack: #billing-alerts
  - Email: finance@fieldsprout.com
```

### 2. Notification Channels

#### Slack Integration
1. Go to **Settings** → **Integrations** → **Slack**
2. Click "Add to Slack"
3. Authorize and select channels:
   - `#alerts-critical` - Fatal/Error
   - `#bugs` - New issues
   - `#performance` - Slow transactions

#### Email Notifications
1. **Settings** → **Notifications**
2. Enable:
   - New Issue Created
   - Issue Regression (reappeared)
   - Issue Assigned to Me

#### PagerDuty (On-Call)
1. **Settings** → **Integrations** → **PagerDuty**
2. Enter Integration Key
3. Map services:
   - Production errors → On-call engineer
   - Payment failures → Billing team

### 3. Scheduled Digests

Weekly summary email:
1. **Settings** → **Notifications** → **Weekly Reports**
2. Enable:
   - Top 10 errors
   - New issues this week
   - Performance trends

---

## Best Practices

### 1. Environment Separation

✅ **DO:** Use separate projects for each environment
```
- fieldsprout-development (DSN: dev-key)
- fieldsprout-staging (DSN: staging-key)
- fieldsprout-production (DSN: prod-key)
```

❌ **DON'T:** Use same DSN with environment tags (hard to filter)

### 2. Release Tracking

✅ **DO:** Set SENTRY_RELEASE on every deploy
```bash
export SENTRY_RELEASE=$(git rev-parse HEAD)
```

Benefits:
- See which deploy introduced a bug
- Track error frequency per release
- Roll back problematic releases

### 3. Sampling Rates

**Low Traffic (< 1,000 req/day):**
```bash
SENTRY_TRACES_SAMPLE_RATE=1.0  # 100%
```

**Medium Traffic (1,000 - 100,000 req/day):**
```bash
SENTRY_TRACES_SAMPLE_RATE=0.1  # 10%
```

**High Traffic (> 100,000 req/day):**
```bash
SENTRY_TRACES_SAMPLE_RATE=0.01  # 1%
```

### 4. Error Grouping

Use custom fingerprints for better grouping:

```python
import sentry_sdk

with sentry_sdk.configure_scope() as scope:
    scope.fingerprint = ['payment-failed', user.subscription_id]
```

Groups all payment failures for same subscription together.

### 5. PII Handling

✅ **DO:** Scrub PII before sending
```python
# Automatically scrubbed by Sentry:
# - Passwords
# - Credit card numbers
# - Social security numbers

# Manually scrub custom fields:
with sentry_sdk.configure_scope() as scope:
    scope.set_context("user_data", {
        "email": "***@***.com",  # Masked
        "user_id": user.id  # Safe
    })
```

### 6. Breadcrumb Best Practices

```python
# Good breadcrumbs (actionable)
add_breadcrumb("User clicked 'Subscribe'", category="ui", data={"plan": "pro"})
add_breadcrumb("Stripe customer created", category="billing", data={"customer_id": "cus_123"})

# Bad breadcrumbs (too noisy)
add_breadcrumb("Function called")  # Not useful
add_breadcrumb("Render template")  # Too granular
```

---

## Troubleshooting

### No errors appearing in Sentry?

1. **Check DSN is configured:**
   ```bash
   echo $SENTRY_DSN
   ```

2. **Test connection:**
   ```python
   import sentry_sdk
   sentry_sdk.init("your-dsn")
   sentry_sdk.capture_message("Test message")
   ```

3. **Check logs:**
   ```
   grep "Sentry" logs/app.log
   ```

4. **Verify network connectivity:**
   ```bash
   curl https://sentry.io
   ```

### Sentry SDK not installed?

```bash
pip install sentry-sdk[flask]
# Restart application
```

### Too many events / quota exceeded?

1. **Increase sample rates:**
   ```bash
   SENTRY_TRACES_SAMPLE_RATE=0.01  # Reduce to 1%
   ```

2. **Filter noisy errors:**
   Edit `app/monitoring/__init__.py`:
   ```python
   ignore_errors=[
       KeyboardInterrupt,
       SystemExit,
       "YourNoisyException",
   ]
   ```

3. **Upgrade Sentry plan** or request quota increase

### Performance data missing?

Check `SENTRY_TRACES_SAMPLE_RATE` is > 0:
```bash
export SENTRY_TRACES_SAMPLE_RATE=0.1
```

### User context not showing?

Ensure user is logged in before error occurs. Check:
```python
if hasattr(g, 'user') and g.user:
    # User context is set automatically
```

---

## Monitoring Checklist

### Initial Setup
- [ ] Create Sentry project
- [ ] Configure SENTRY_DSN
- [ ] Install sentry-sdk
- [ ] Test error reporting
- [ ] Set up Slack notifications

### Week 1
- [ ] Review all errors daily
- [ ] Set up alert rules
- [ ] Configure release tracking
- [ ] Adjust sample rates based on traffic

### Ongoing
- [ ] Review weekly error digest
- [ ] Monitor performance degradation
- [ ] Update alert thresholds as needed
- [ ] Track error trends over time

---

## Cost Estimation

### Sentry Pricing Tiers

**Developer (Free)**
- 5,000 errors/month
- 10,000 performance units/month
- 1 project
- **Best for:** Development/staging

**Team ($26/month)**
- 50,000 errors/month
- 100,000 performance units/month
- Unlimited projects
- **Best for:** Small apps (< 10k users)

**Business ($80/month)**
- 150,000 errors/month
- 500,000 performance units/month
- **Best for:** Medium apps (10k-100k users)

### Optimization Tips

1. Use separate projects (dev counts towards quota)
2. Lower sample rates in production
3. Filter out expected errors (404s, health checks)
4. Use on-demand debug (increase sample rate temporarily)

---

## Additional Resources

- **Official Docs:** https://docs.sentry.io/platforms/python/guides/flask/
- **Performance:** https://docs.sentry.io/product/performance/
- **Release Tracking:** https://docs.sentry.io/product/releases/
- **Alerts:** https://docs.sentry.io/product/alerts/

---

## Support

For questions:
- Sentry Support: https://sentry.io/support/
- Internal: ops@fieldsprout.com
- Docs: This file + `ENV_VARIABLES.md`
