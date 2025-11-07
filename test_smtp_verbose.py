#!/usr/bin/env python3
"""
Enhanced SMTP diagnostic script with verbose debugging.
Shows exactly what's happening during the SMTP connection.
"""
import os
import sys
import smtplib

def test_smtp_verbose():
    """Test SMTP connection with detailed debugging output."""

    # Read config from environment
    host = os.getenv("MAIL_SERVER", "smtp.mailgun.org")
    port = int(os.getenv("MAIL_PORT", "587"))
    user = os.getenv("MAIL_USERNAME_DAVID") or os.getenv("MAIL_USERNAME")
    pwd = os.getenv("MAIL_PASSWORD_DAVID") or os.getenv("MAIL_PASSWORD")
    use_tls = os.getenv("MAIL_USE_TLS", "true").lower() in ("1", "true", "yes")
    use_ssl = os.getenv("MAIL_USE_SSL", "false").lower() in ("1", "true", "yes")

    print("=" * 70)
    print("ENHANCED SMTP CONNECTION TEST WITH VERBOSE DEBUGGING")
    print("=" * 70)
    print(f"Host:     {host}")
    print(f"Port:     {port}")
    print(f"User:     {user}")
    print(f"Password: {'SET (' + str(len(pwd)) + ' chars)' if pwd else '❌ NOT SET'}")
    print(f"USE_TLS:  {use_tls}")
    print(f"USE_SSL:  {use_ssl}")
    print("=" * 70)

    # Check for common mistakes
    if not user or not pwd:
        print("\n❌ CREDENTIALS NOT SET")
        print("\nYou need to set these environment variables:")
        print("  export MAIL_USERNAME_DAVID='postmaster@mg.fieldsprout.io'")
        print("  export MAIL_PASSWORD_DAVID='your-smtp-password-from-mailgun'")
        print("\n⚠️  IMPORTANT: Don't use the API key! You need the SMTP password.")
        print("   Get it from: https://app.mailgun.com/app/sending/domains/mg.fieldsprout.io")
        return False

    # Check if password looks like an API key (common mistake)
    if pwd and len(pwd) == 56 and pwd.count('-') == 3:
        print("\n⚠️  WARNING: Your password looks like a Mailgun API key!")
        print("   API Key format: xxxxxxxx-xxxxxxxx-xxxxxxxx (56 chars)")
        print("   SMTP password format: Usually different")
        print("\n   You need the SMTP PASSWORD, not the API key!")
        print("   Get SMTP password from: https://app.mailgun.com/app/sending/domains/mg.fieldsprout.io")
        print("   Look for 'SMTP Credentials' section → 'Reset Password'\n")

    # Auto-correct port/SSL mismatch
    if port == 587 and use_ssl:
        print("\n⚠️  Auto-correcting: Port 587 requires STARTTLS, not SSL")
        use_ssl = False
        use_tls = True
    elif port == 465 and not use_ssl:
        print("\n⚠️  Auto-correcting: Port 465 requires SSL")
        use_ssl = True
        use_tls = False

    print(f"\n🔌 Testing connection with VERBOSE debugging...\n")
    print("-" * 70)

    try:
        # Enable debug output
        smtp = None

        if use_ssl:
            print(f"Step 1: Connecting via SMTP_SSL to {host}:{port}...")
            smtp = smtplib.SMTP_SSL(host, port, timeout=15)
            smtp.set_debuglevel(2)  # Verbose debugging
        else:
            print(f"Step 1: Connecting via SMTP to {host}:{port}...")
            smtp = smtplib.SMTP(host, port, timeout=15)
            smtp.set_debuglevel(2)  # Verbose debugging

        print("\n✓ Socket connection established\n")
        print("-" * 70)

        print("\nStep 2: Sending EHLO...")
        smtp.ehlo()
        print("\n✓ EHLO successful\n")
        print("-" * 70)

        if use_tls and not use_ssl:
            print("\nStep 3: Starting TLS (STARTTLS)...")
            smtp.starttls()
            print("\n✓ STARTTLS successful\n")
            print("-" * 70)

            print("\nStep 4: Sending EHLO again after TLS...")
            smtp.ehlo()
            print("\n✓ EHLO after STARTTLS successful\n")
            print("-" * 70)

        print(f"\nStep 5: Authenticating as '{user}'...")
        print(f"Password length: {len(pwd)} characters")
        smtp.login(user, pwd)
        print("\n✓ Authentication successful!\n")
        print("-" * 70)

        print("\nStep 6: Closing connection...")
        smtp.quit()
        print("✓ Connection closed cleanly\n")
        print("-" * 70)

        print("\n" + "=" * 70)
        print("✅ SUCCESS! SMTP connection fully working!")
        print("=" * 70)
        print("\nYour Mailgun SMTP configuration is correct.")
        print("All email features should work now.")
        return True

    except smtplib.SMTPAuthenticationError as e:
        print("\n" + "=" * 70)
        print("❌ AUTHENTICATION FAILED")
        print("=" * 70)
        print(f"\nError: {e}")
        print("\n🔍 This means:")
        print("   1. Wrong username or password")
        print("   2. Username should be: postmaster@mg.fieldsprout.io")
        print("   3. Password should be SMTP password (not API key)")
        print("\n📋 To fix:")
        print("   1. Go to: https://app.mailgun.com/app/sending/domains/mg.fieldsprout.io")
        print("   2. Find 'SMTP Credentials' section")
        print("   3. Click 'Reset Password' to generate new SMTP password")
        print("   4. Use that password (not the API key!)")
        print("   5. Set: export MAIL_PASSWORD_DAVID='the-smtp-password'\n")
        return False

    except smtplib.SMTPServerDisconnected as e:
        print("\n" + "=" * 70)
        print("❌ CONNECTION UNEXPECTEDLY CLOSED")
        print("=" * 70)
        print(f"\nError: {e}")
        print("\n🔍 This usually means:")
        print("   1. Authentication failed (wrong username/password)")
        print("   2. Server rejected the connection")
        print("   3. TLS/SSL configuration issue")
        print("\n📋 Most likely cause:")
        print("   ⚠️  You may be using the API KEY instead of SMTP PASSWORD")
        print("\n   Mailgun API Key:    f160ce6d************ (56 chars)")
        print("   SMTP Password:      Different format from API key")
        print("\n   Get SMTP password from:")
        print("   https://app.mailgun.com/app/sending/domains/mg.fieldsprout.io\n")
        return False

    except smtplib.SMTPException as e:
        print("\n" + "=" * 70)
        print("❌ SMTP ERROR")
        print("=" * 70)
        print(f"\nError type: {type(e).__name__}")
        print(f"Error: {e}")
        return False

    except ConnectionRefusedError:
        print("\n" + "=" * 70)
        print("❌ CONNECTION REFUSED")
        print("=" * 70)
        print(f"\nCould not connect to {host}:{port}")
        print("\n🔍 This means:")
        print("   1. Wrong host or port")
        print("   2. Firewall blocking the connection")
        print("   3. Network connectivity issue")
        print("\n📋 Check:")
        print(f"   - MAIL_SERVER should be: smtp.mailgun.org")
        print(f"   - MAIL_PORT should be: 587 (or 465 for SSL)")
        return False

    except Exception as e:
        print("\n" + "=" * 70)
        print("❌ UNEXPECTED ERROR")
        print("=" * 70)
        print(f"\nError type: {type(e).__name__}")
        print(f"Error: {e}")
        import traceback
        print("\nFull traceback:")
        traceback.print_exc()
        return False

    finally:
        if smtp:
            try:
                smtp.quit()
            except:
                pass

if __name__ == "__main__":
    print("\nℹ️  This script will show detailed SMTP debugging output.")
    print("   The verbose output helps identify exactly where the connection fails.\n")

    success = test_smtp_verbose()

    if not success:
        print("\n💡 Quick troubleshooting steps:")
        print("   1. Verify credentials: Did you get SMTP password from Mailgun?")
        print("   2. Check it's not the API key: SMTP password ≠ API key")
        print("   3. Try resetting SMTP password in Mailgun dashboard")
        print("   4. Make sure port 587 and USE_TLS=true\n")

    sys.exit(0 if success else 1)
