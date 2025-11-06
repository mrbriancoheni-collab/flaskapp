#!/bin/bash
# Mailgun SMTP Configuration for FieldSprout
# Domain: mg.fieldsprout.io

echo ""
echo "🔧 Setting up Mailgun SMTP for FieldSprout"
echo "============================================"
echo ""

# Mailgun SMTP settings (Port 587 - STARTTLS)
export MAIL_SERVER='smtp.mailgun.org'
export MAIL_PORT='587'
export MAIL_USE_TLS='true'
export MAIL_USE_SSL='false'  # CRITICAL: Must be false for port 587!

# Your Mailgun SMTP credentials for mg.fieldsprout.io
# IMPORTANT: Get SMTP password from https://app.mailgun.com/app/sending/domains/mg.fieldsprout.io
# Click "SMTP Credentials" section, then "Reset Password"
# NOTE: API key (f160ce6d************) is NOT the SMTP password!
export MAIL_USERNAME_DAVID='postmaster@mg.fieldsprout.io'
export MAIL_PASSWORD_DAVID='GET-FROM-MAILGUN-DASHBOARD'  # Replace with actual SMTP password

# Default sender email
export MAIL_DEFAULT_SENDER='noreply@mg.fieldsprout.io'
export MAIL_FROM='noreply@mg.fieldsprout.io'

# Optional: For custom from name
export EMAIL_FROM_NAME='FieldSprout'

echo "✓ Environment variables configured"
echo ""
echo "⚠️  IMPORTANT: You must replace MAIL_PASSWORD_DAVID with your actual SMTP password!"
echo ""
echo "📋 How to get your SMTP password:"
echo "   1. Visit: https://app.mailgun.com/app/sending/domains/mg.fieldsprout.io"
echo "   2. Scroll to 'SMTP Credentials' section"
echo "   3. Click 'Reset Password' to generate SMTP password"
echo "   4. Copy the password and update MAIL_PASSWORD_DAVID above"
echo ""
echo "🧪 Test your configuration:"
echo "   python3 test_smtp_connection.py"
echo ""
echo "📚 Full documentation: MAILGUN_SETUP.md"
echo ""
echo "💡 To make these permanent:"
echo "   - Production: Add to your hosting platform's environment variables"
echo "   - Development: Add to ~/.bashrc or ~/.zshrc"
echo ""
