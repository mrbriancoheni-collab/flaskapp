#!/usr/bin/env python3
"""
Standalone Mailgun test script to diagnose email sending issues.

Usage:
    python test_mailgun.py testemail@gmail.com

Environment variables required:
    MAILGUN_API_KEY - Your Mailgun API key
"""

import os
import sys
import requests
from datetime import datetime


def test_mailgun_connection(recipient_email):
    """Test Mailgun API connection and send test email."""

    # Get configuration from environment
    api_key = os.getenv('MAILGUN_API_KEY')
    domain = os.getenv('MAILGUN_DOMAIN', 'mg.fieldsprout.io')

    print("=" * 70)
    print("Mailgun Email Test")
    print("=" * 70)
    print(f"Recipient: {recipient_email}")
    print(f"Domain: {domain}")

    # Check API key
    if not api_key:
        print("\n❌ ERROR: MAILGUN_API_KEY environment variable not set")
        print("\nSet it with:")
        print("  export MAILGUN_API_KEY='your-api-key-here'")
        return False

    # Mask API key for security
    api_key_preview = f"{api_key[:8]}...{api_key[-4:]}" if len(api_key) > 12 else "***"
    print(f"API Key: {api_key_preview}")
    print("\n" + "-" * 70)

    # Prepare request
    url = f"https://api.mailgun.net/v3/{domain}/messages"
    print(f"URL: {url}")

    data = {
        "from": f"FieldSprout Test <postmaster@{domain}>",
        "to": recipient_email,
        "subject": f"Test Email from FieldSprout - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "text": f"This is a test email.\n\nRecipient: {recipient_email}\nTime: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "html": f"""
        <html>
        <body style="font-family: Arial, sans-serif; padding: 20px;">
            <h2 style="color: #7c3aed;">✅ Test Email Successful!</h2>
            <p>This is a test email from FieldSprout.</p>
            <p><strong>Recipient:</strong> {recipient_email}<br>
            <strong>Domain:</strong> {domain}<br>
            <strong>Time:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        </body>
        </html>
        """
    }

    print("\nSending request to Mailgun API...")
    print(f"Timeout: 30 seconds")
    print(f"SSL Verification: Enabled")

    try:
        # Make request
        response = requests.post(
            url,
            auth=("api", api_key),
            data=data,
            timeout=30,
            verify=True
        )

        print(f"\n✅ Request completed!")
        print(f"Status Code: {response.status_code}")
        print(f"Response Headers: {dict(response.headers)}")

        # Check status
        if response.status_code == 200:
            print(f"\n✅ SUCCESS! Email sent successfully!")
            print(f"Response: {response.json()}")
            return True
        else:
            print(f"\n❌ ERROR: Mailgun returned status {response.status_code}")
            print(f"Response body: {response.text}")
            return False

    except requests.exceptions.ConnectionError as e:
        print(f"\n❌ CONNECTION ERROR: Unable to connect to Mailgun API")
        print(f"Details: {e}")
        print("\nPossible causes:")
        print("  1. Firewall blocking outbound HTTPS to api.mailgun.net")
        print("  2. Network connectivity issues")
        print("  3. DNS resolution problems")
        print("\nTry testing with curl:")
        print(f"  curl -v -u 'api:{api_key}' https://api.mailgun.net/v3/{domain}/messages")
        return False

    except requests.exceptions.Timeout as e:
        print(f"\n❌ TIMEOUT ERROR: Request timed out after 30 seconds")
        print(f"Details: {e}")
        print("\nPossible causes:")
        print("  1. Very slow network connection")
        print("  2. Mailgun API temporarily unavailable")
        return False

    except requests.exceptions.SSLError as e:
        print(f"\n❌ SSL ERROR: SSL certificate verification failed")
        print(f"Details: {e}")
        print("\nPossible causes:")
        print("  1. System CA certificates are outdated or missing")
        print("  2. Corporate proxy intercepting SSL")
        print("\nTry with SSL verification disabled (for debugging only):")
        print("  response = requests.post(..., verify=False)")
        return False

    except requests.exceptions.RequestException as e:
        print(f"\n❌ REQUEST ERROR: {type(e).__name__}")
        print(f"Details: {e}")
        return False

    except Exception as e:
        print(f"\n❌ UNEXPECTED ERROR: {type(e).__name__}")
        print(f"Details: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_mailgun.py <recipient_email>")
        print("Example: python test_mailgun.py test@example.com")
        sys.exit(1)

    recipient = sys.argv[1]
    success = test_mailgun_connection(recipient)

    print("\n" + "=" * 70)
    if success:
        print("✅ Test completed successfully!")
    else:
        print("❌ Test failed - see error details above")
    print("=" * 70)

    sys.exit(0 if success else 1)
