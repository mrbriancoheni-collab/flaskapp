# New Paying Customer Email Notifications

## Overview

Automatically sends email notifications to `hi@fieldsprout.io` and `mrbriancoheni@gmail.com` whenever a new paying customer completes their first successful payment.

## How It Works

### Trigger Event
The notification is triggered when Stripe sends an `invoice.paid` webhook event and it's determined to be the customer's **first successful payment**.

### Notification Recipients
- `hi@fieldsprout.io`
- `mrbriancoheni@gmail.com`

### Email Content
The notification includes:
- Customer name
- Customer email address
- Plan name (Growth Monthly, Growth Annual, etc.)
- Payment amount
- Invoice ID
- Account creation date

### Implementation Details

**File:** `/flaskapp/app/services/stripe_service.py`

**Function:** `_notify_new_paying_customer(user_id, invoice)`
- Lines 237-401

**Integration Point:** `handle_invoice_paid(event_data)`
- Lines 412-452
- Checks if this is the first successful payment before sending notification
- Only sends notification for new paying customers (not recurring payments)

### Flow

```
1. Customer completes payment in Stripe
   ↓
2. Stripe sends invoice.paid webhook
   ↓
3. Webhook handler records payment in database
   ↓
4. Check if this is first successful payment
   ↓
5. If YES → Send notification emails
   ↓
6. Email sent to hi@fieldsprout.io
   ↓
7. Email sent to mrbriancoheni@gmail.com
```

### First Payment Detection

The system determines a "new paying customer" by:
1. Querying the `payments` table for the customer's user_id
2. Counting previous successful payments with status="paid"
3. If count = 0, this is a new paying customer
4. Notification is sent BEFORE recording the current payment
5. Subsequent payments for the same customer will NOT trigger notifications

### Email Format

**Subject:** `🎉 New Paying Customer: [Customer Name]`

**Content:** Professional HTML email with:
- Green success theme
- Formatted table with customer details
- Clean, responsive design
- Plain text fallback for compatibility

### Email Service Configuration

The notification uses the existing email service with bulk credentials:
- Uses `send_email()` function from `app.services.email_service`
- Parameter `use_bulk_credentials=True` ensures David credentials are used
- Falls back gracefully if email sending fails
- Errors are logged but don't crash the webhook handler

### Error Handling

The notification system is fault-tolerant:
- Wrapped in try/except to prevent webhook failures
- Each email sent individually (if one fails, other still sends)
- All errors logged with `current_app.logger.error()`
- Failed notifications don't affect payment processing

### Testing

To test the notification system:

#### Option 1: Stripe Test Mode
1. Configure Stripe webhook in test mode
2. Create a test subscription using Stripe test cards
3. Complete payment with card: `4242 4242 4242 4242`
4. Check that emails were sent to both addresses

#### Option 2: Manual Trigger (Development)
```python
from flask import Flask
from app import create_app, db
from app.services.stripe_service import _notify_new_paying_customer

app = create_app()
with app.app_context():
    # Mock invoice data
    test_invoice = {
        "id": "in_test123",
        "amount_paid": 9900,  # $99.00
        "currency": "usd"
    }

    # Replace 1 with actual user_id from your database
    _notify_new_paying_customer(user_id=1, invoice=test_invoice)
```

#### Option 3: Stripe CLI Webhook Testing
```bash
# Install Stripe CLI
stripe listen --forward-to localhost:5000/account/stripe/webhook

# Trigger test event
stripe trigger invoice.payment_succeeded
```

### Monitoring

Check application logs for notification activity:

```bash
# Success logs
grep "Sent new paying customer notification" app.log

# Error logs
grep "Error in _notify_new_paying_customer" app.log
grep "Failed to send notification" app.log
```

### Configuration Requirements

**Environment Variables:**
- `SMTP_HOST` or `MAIL_SERVER` - SMTP server address
- `SMTP_PORT` or `MAIL_PORT` - SMTP port (usually 587)
- `SMTP_USER` or `MAIL_USERNAME` - SMTP username
- `SMTP_PASSWORD` or `MAIL_PASSWORD` - SMTP password
- `MAIL_USERNAME_DAVID` (optional) - Bulk email credentials
- `MAIL_PASSWORD_DAVID` (optional) - Bulk email credentials
- `STRIPE_WEBHOOK_SECRET` - Stripe webhook signing secret

See `ENV_VARIABLES.md` for complete email configuration details.

### Stripe Webhook Configuration

The webhook must be configured in Stripe to send events to:
```
https://yourdomain.com/account/stripe/webhook
```

**Required Events:**
- `invoice.paid` (triggers new customer notifications)
- `customer.subscription.created` (creates subscription records)
- `customer.subscription.updated` (updates subscription records)
- `customer.subscription.deleted` (marks subscriptions as canceled)
- `invoice.payment_failed` (tracks failed payments)

### Troubleshooting

**Notifications not sending:**
1. Check SMTP configuration is correct
2. Verify webhook is receiving events from Stripe
3. Check application logs for errors
4. Ensure email service is not blocked by firewall
5. Verify user_id exists in database

**Duplicate notifications:**
- Should not happen due to first-payment check
- If occurring, check Payment table for duplicate records
- Review webhook retry behavior in Stripe dashboard

**Wrong plan name showing:**
- Plan name is inferred from price_id
- Update logic in `_notify_new_paying_customer()` if needed
- Consider adding a Plan model to store proper names

### Future Enhancements

Potential improvements:
1. Add configurable notification email addresses (via env vars)
2. Include customer's business profile details
3. Add Slack/Discord webhook notifications
4. Track notification delivery status
5. Add admin dashboard for notification history
6. Customize email template per plan tier
7. Include customer LTV projections
8. Add link to admin panel for customer details

### Related Files

- **Implementation:** `/flaskapp/app/services/stripe_service.py`
- **Email Service:** `/flaskapp/app/services/email_service.py`
- **Webhook Route:** `/flaskapp/app/account/__init__.py` (line 389-430)
- **Models:** `/flaskapp/app/models_billing.py`
- **Configuration:** `/flaskapp/app/config.py`

### Security Considerations

- Webhook endpoint is CSRF exempt (required for Stripe)
- Webhook signature verification ensures authenticity
- Email addresses are hardcoded (not user-controllable)
- No sensitive data exposed in notification emails
- Payment amounts and invoice IDs are safe to include

### Compliance Notes

Email notifications contain:
- ✅ Customer name (business need)
- ✅ Customer email (business need)
- ✅ Payment amount (business need)
- ✅ Plan information (business need)
- ❌ No credit card information
- ❌ No authentication tokens
- ❌ No password hashes

This notification is sent to internal team members only, not to external parties.
