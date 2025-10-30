# Email Configuration Guide

## Overview
FieldSprout's email system requires SMTP configuration to send emails for:
- Email verification
- Password reset
- Test emails from admin panel
- Automated notifications

## Required Environment Variables

Set these environment variables in your `.env` file or hosting environment:

```bash
# SMTP Server Configuration
MAIL_SERVER=smtp.gmail.com                    # Your SMTP server
MAIL_PORT=587                                  # SMTP port (usually 587 for TLS, 465 for SSL)
MAIL_USE_TLS=true                             # Enable TLS (recommended)

# SMTP Authentication
MAIL_USERNAME_DAVID=your-email@gmail.com      # SMTP username (usually your email)
MAIL_PASSWORD_DAVID=your-app-password         # SMTP password or app-specific password

# Email Sender
MAIL_DEFAULT_SENDER=noreply@fieldsprout.com   # From address for emails
MAIL_FROM=noreply@fieldsprout.com             # Alternative from address
```

## Gmail Setup Example

If using Gmail:

1. **Enable 2-Factor Authentication** on your Google account
2. **Generate an App Password**:
   - Go to [Google Account Settings](https://myaccount.google.com/security)
   - Navigate to "2-Step Verification" → "App passwords"
   - Generate a new app password for "Mail"
   - Use this password (not your regular Gmail password)

3. **Set environment variables**:
```bash
MAIL_SERVER=smtp.gmail.com
MAIL_PORT=587
MAIL_USE_TLS=true
MAIL_USERNAME_DAVID=your-email@gmail.com
MAIL_PASSWORD_DAVID=your-16-char-app-password
MAIL_DEFAULT_SENDER=your-email@gmail.com
```

## Testing Email Configuration

1. **Login as admin**
2. **Navigate to**: `/admin/test-email`
3. **Send a test email** to verify configuration

Or use the CLI:
```bash
python3 -c "
from app import create_app
from app.emailer import send_mail
app = create_app()
with app.app_context():
    send_mail('test@example.com', 'Test', 'Hello!')
"
```

## Troubleshooting

### Emails Not Sending

**Check configuration is set:**
```bash
env | grep MAIL_
```

**Common issues:**
1. **Wrong credentials**: Verify MAIL_USERNAME_DAVID and MAIL_PASSWORD_DAVID
2. **App password not used**: Gmail requires app-specific passwords when 2FA is enabled
3. **Firewall/port blocked**: Ensure port 587 (or 465) is not blocked
4. **Wrong server**: Verify MAIL_SERVER matches your email provider

### Error: "MAIL_SERVER not configured"
- Set `MAIL_SERVER` environment variable

### Error: "MAIL credentials not configured"
- Set `MAIL_USERNAME_DAVID` and `MAIL_PASSWORD_DAVID` environment variables

### Error: "Authentication failed"
- For Gmail: Use app password, not regular password
- Verify credentials are correct
- Check if account has 2FA enabled (required for Gmail)

## Alternative Email Providers

### SendGrid
```bash
MAIL_SERVER=smtp.sendgrid.net
MAIL_PORT=587
MAIL_USE_TLS=true
MAIL_USERNAME_DAVID=apikey
MAIL_PASSWORD_DAVID=your-sendgrid-api-key
MAIL_DEFAULT_SENDER=verified-sender@yourdomain.com
```

### AWS SES
```bash
MAIL_SERVER=email-smtp.us-east-1.amazonaws.com
MAIL_PORT=587
MAIL_USE_TLS=true
MAIL_USERNAME_DAVID=your-smtp-username
MAIL_PASSWORD_DAVID=your-smtp-password
MAIL_DEFAULT_SENDER=verified-sender@yourdomain.com
```

### Mailgun
```bash
MAIL_SERVER=smtp.mailgun.org
MAIL_PORT=587
MAIL_USE_TLS=true
MAIL_USERNAME_DAVID=postmaster@your-domain.mailgun.org
MAIL_PASSWORD_DAVID=your-mailgun-smtp-password
MAIL_DEFAULT_SENDER=noreply@your-domain.com
```

## Production Best Practices

1. **Use environment variables** - Never commit credentials to git
2. **Use app-specific passwords** - Don't use your personal email password
3. **Monitor email sending** - Check logs for failed email attempts
4. **Set up SPF/DKIM/DMARC** - For better deliverability with custom domains
5. **Use a dedicated email service** - SendGrid, Mailgun, or AWS SES for production

## Support

If emails still aren't working after following this guide:
1. Check application logs for error messages
2. Verify environment variables are loaded: `env | grep MAIL_`
3. Test SMTP connection manually using telnet or openssl
4. Contact support at cs@fieldsprout.io
