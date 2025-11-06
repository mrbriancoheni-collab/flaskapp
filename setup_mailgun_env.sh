#!/bin/bash
# Mailgun SMTP Configuration for FieldSprout
# Copy this file and fill in your credentials

echo "Setting up Mailgun SMTP environment variables..."
echo ""
echo "⚙️  Mailgun SMTP Configuration"
echo "================================"
echo ""

# Mailgun SMTP settings (Port 587 - STARTTLS)
export MAIL_SERVER='smtp.mailgun.org'
export MAIL_PORT='587'
export MAIL_USE_TLS='true'
export MAIL_USE_SSL='false'  # CRITICAL: Must be false for port 587!

# Your Mailgun credentials
# Replace with your actual Mailgun SMTP credentials from https://app.mailgun.com/
export MAIL_USERNAME_DAVID='postmaster@sandboxXXXXXXXX.mailgun.org'
export MAIL_PASSWORD_DAVID='your-mailgun-smtp-password-here'

# Default sender email (optional)
export MAIL_DEFAULT_SENDER='noreply@yourdomain.com'
export MAIL_FROM='noreply@yourdomain.com'

echo "✓ Environment variables set for current shell session"
echo ""
echo "To make these permanent, add them to:"
echo "  - ~/.bashrc (for bash)"
echo "  - ~/.zshrc (for zsh)"
echo "  - Your hosting platform's environment variables dashboard"
echo ""
echo "Test your configuration with:"
echo "  python3 test_smtp_connection.py"
echo ""
