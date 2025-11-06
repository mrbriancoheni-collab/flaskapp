#!/usr/bin/env python3
"""
Quick check of email configuration environment variables.
Shows what's currently set (without exposing full passwords).
"""
import os

def check_config():
    print("=" * 70)
    print("EMAIL CONFIGURATION CHECK")
    print("=" * 70)

    configs = [
        ("MAIL_SERVER", "smtp.mailgun.org", True),
        ("MAIL_PORT", "587", True),
        ("MAIL_USE_TLS", "true", True),
        ("MAIL_USE_SSL", "false", True),
        ("MAIL_USERNAME_DAVID", "postmaster@mg.fieldsprout.io", False),
        ("MAIL_PASSWORD_DAVID", None, False),
        ("MAIL_DEFAULT_SENDER", "noreply@mg.fieldsprout.io", False),
    ]

    all_good = True

    for key, expected, show_full in configs:
        value = os.getenv(key)

        if value:
            if key.endswith("PASSWORD") or key.endswith("PASSWORD_DAVID"):
                # Mask password but show length and first/last chars
                display = f"{'*' * (len(value) - 4)}{value[-4:]}" if len(value) > 4 else "****"
                status = "✓"
                detail = f"({len(value)} chars)"
            else:
                if show_full:
                    display = value
                else:
                    display = value[:30] + "..." if len(value) > 30 else value

                if expected and value.lower() == expected.lower():
                    status = "✓"
                    detail = ""
                elif expected:
                    status = "⚠️"
                    detail = f"(expected: {expected})"
                else:
                    status = "✓"
                    detail = ""

            print(f"{status} {key:25} = {display} {detail}")
        else:
            print(f"❌ {key:25} = NOT SET")
            if expected:
                print(f"   {'':25}   (should be: {expected})")
            all_good = False

    print("=" * 70)

    # Check for common mistakes
    print("\n🔍 Common Issues Check:")

    pwd = os.getenv("MAIL_PASSWORD_DAVID")
    if pwd:
        if len(pwd) == 56 and pwd.count('-') == 3:
            print("   ⚠️  Password looks like an API key (56 chars with dashes)")
            print("      You need SMTP password, not API key!")
            all_good = False
        else:
            print("   ✓ Password format looks correct (not an API key)")
    else:
        print("   ❌ No password set")
        all_good = False

    port = os.getenv("MAIL_PORT", "587")
    use_ssl = os.getenv("MAIL_USE_SSL", "false").lower() in ("1", "true", "yes")
    use_tls = os.getenv("MAIL_USE_TLS", "true").lower() in ("1", "true", "yes")

    if port == "587" and not use_tls:
        print("   ⚠️  Port 587 requires MAIL_USE_TLS=true")
        all_good = False
    elif port == "465" and not use_ssl:
        print("   ⚠️  Port 465 requires MAIL_USE_SSL=true")
        all_good = False
    else:
        print("   ✓ Port and TLS/SSL settings match")

    print("\n" + "=" * 70)

    if all_good:
        print("✅ Configuration looks good!")
        print("\nNext step: Run 'python3 test_smtp_verbose.py' to test connection")
    else:
        print("⚠️  Issues found - see above")
        print("\n📋 To fix:")
        print("   1. Get SMTP password: https://app.mailgun.com/app/sending/domains/mg.fieldsprout.io")
        print("   2. Set variables: source setup_mailgun_env.sh (after editing)")
        print("   3. Or set manually: export MAIL_PASSWORD_DAVID='your-smtp-password'")

    print("=" * 70)

if __name__ == "__main__":
    check_config()
