#!/usr/bin/env python3
"""
Quick diagnostic script to test SMTP connection.
Tests both SSL (port 465) and STARTTLS (port 587) configurations.
"""
import os
import sys
import smtplib

def test_smtp():
    """Test SMTP connection with current environment variables."""

    # Read config from environment
    host = os.getenv("MAIL_SERVER", "smtp.mailgun.org")
    port = int(os.getenv("MAIL_PORT", "587"))
    user = os.getenv("MAIL_USERNAME_DAVID") or os.getenv("MAIL_USERNAME")
    pwd = os.getenv("MAIL_PASSWORD_DAVID") or os.getenv("MAIL_PASSWORD")
    use_tls = os.getenv("MAIL_USE_TLS", "true").lower() in ("1", "true", "yes")
    use_ssl = os.getenv("MAIL_USE_SSL", "false").lower() in ("1", "true", "yes")

    print("=" * 60)
    print("SMTP Configuration Test")
    print("=" * 60)
    print(f"Host:     {host}")
    print(f"Port:     {port}")
    print(f"User:     {user[:20]}..." if user and len(user) > 20 else f"User:     {user}")
    print(f"Password: {'*' * 16 if pwd else 'NOT SET'}")
    print(f"USE_TLS:  {use_tls}")
    print(f"USE_SSL:  {use_ssl}")
    print("=" * 60)

    if not user or not pwd:
        print("\n❌ ERROR: MAIL_USERNAME_DAVID and MAIL_PASSWORD_DAVID must be set!")
        print("\nSet these environment variables:")
        print("  export MAIL_USERNAME_DAVID='postmaster@sandbox...mailgun.org'")
        print("  export MAIL_PASSWORD_DAVID='your-mailgun-smtp-password'")
        return False

    # Detect recommended configuration based on port
    if port == 465:
        recommended_ssl = True
        recommended_tls = False
    elif port == 587:
        recommended_ssl = False
        recommended_tls = True
    else:
        recommended_ssl = False
        recommended_tls = True

    if use_ssl != recommended_ssl or use_tls != recommended_tls:
        print(f"\n⚠️  WARNING: Configuration mismatch detected!")
        print(f"   For port {port}, recommended settings are:")
        print(f"   MAIL_USE_SSL={str(recommended_ssl).lower()}")
        print(f"   MAIL_USE_TLS={str(recommended_tls).lower()}")
        print()

    # Test connection
    print("\n🔌 Testing connection...")
    try:
        if use_ssl:
            print(f"   Connecting via SMTP_SSL (port {port})...")
            smtp = smtplib.SMTP_SSL(host, port, timeout=10)
        else:
            print(f"   Connecting via SMTP (port {port})...")
            smtp = smtplib.SMTP(host, port, timeout=10)

        print("   ✓ Socket connected")

        smtp.ehlo()
        print("   ✓ EHLO successful")

        if use_tls and not use_ssl:
            print("   Starting TLS...")
            smtp.starttls()
            print("   ✓ STARTTLS successful")
            smtp.ehlo()
            print("   ✓ EHLO after STARTTLS successful")

        print(f"   Authenticating as {user}...")
        smtp.login(user, pwd)
        print("   ✓ Authentication successful")

        smtp.quit()
        print("   ✓ Connection closed cleanly")

        print("\n✅ SUCCESS: SMTP connection test passed!")
        print("\nYour email configuration is correct and ready to use.")
        return True

    except smtplib.SMTPAuthenticationError as e:
        print(f"\n❌ Authentication failed: {e}")
        print("\nPossible causes:")
        print("  - Wrong username or password")
        print("  - For Mailgun: verify your SMTP credentials at https://app.mailgun.com/")
        return False

    except Exception as e:
        error_type = type(e).__name__
        error_msg = str(e)
        print(f"\n❌ Connection failed: [{error_type}] {error_msg}")

        # Provide specific guidance based on error
        if "WRONG_VERSION_NUMBER" in error_msg or "SSL" in error_type:
            print("\n🔧 SSL/TLS Configuration Issue Detected!")
            print("\nFor Mailgun port 587, use:")
            print("  export MAIL_SERVER='smtp.mailgun.org'")
            print("  export MAIL_PORT='587'")
            print("  export MAIL_USE_TLS='true'")
            print("  export MAIL_USE_SSL='false'")
            print("\nAlternatively, for port 465 (SSL):")
            print("  export MAIL_PORT='465'")
            print("  export MAIL_USE_TLS='false'")
            print("  export MAIL_USE_SSL='true'")

        elif "Errno" in error_msg or "Connection" in error_type:
            print("\nPossible causes:")
            print("  - Wrong hostname or port")
            print(f"  - Firewall blocking port {port}")
            print("  - Network connectivity issue")

        return False

if __name__ == "__main__":
    success = test_smtp()
    sys.exit(0 if success else 1)
