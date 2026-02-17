#!/usr/bin/env python3
"""
Terminal script to test email sending functionality.

This standalone script tests email sending via Brevo API without requiring
the full Flask app context.

Usage:
    python test_email_send.py --to your@email.com
    python test_email_send.py --to your@email.com --subject "Test Subject"
    python test_email_send.py --check-config

Environment Variables Required:
    BREVO_API_KEY - Your Brevo API key
    BREVO_FROM_EMAIL - Sender email address (default: noreply@fieldsprout.io)
    BREVO_FROM_NAME - Sender name (default: FieldSprout)
"""

import argparse
import os
import sys
import json
from datetime import datetime

# Try to load .env file if python-dotenv is available
try:
    from dotenv import load_dotenv
    # Try multiple possible .env locations
    env_paths = [
        os.path.join(os.path.dirname(__file__), '.env'),
        os.path.join(os.path.dirname(__file__), 'flaskapp', '.env'),
        os.path.join(os.path.dirname(__file__), 'flaskapp', 'app', '.env'),
    ]
    for env_path in env_paths:
        if os.path.exists(env_path):
            load_dotenv(env_path)
            print(f"Loaded environment from: {env_path}")
            break
except ImportError:
    print("Note: python-dotenv not installed, using system environment variables only")

try:
    import requests
except ImportError:
    print("ERROR: 'requests' library required. Install with: pip install requests")
    sys.exit(1)


class BrevoEmailTester:
    """Test email sending via Brevo API"""

    def __init__(self):
        self.api_key = os.getenv('BREVO_API_KEY') or os.getenv('SENDINBLUE_API_KEY')
        self.from_email = os.getenv('BREVO_FROM_EMAIL', 'noreply@fieldsprout.io')
        self.from_name = os.getenv('BREVO_FROM_NAME', 'FieldSprout')
        self.base_url = "https://api.brevo.com/v3"

    def check_config(self):
        """Check and display current configuration."""
        print(f"\n{'='*60}")
        print("BREVO EMAIL CONFIGURATION")
        print(f"{'='*60}\n")

        api_key_display = '***' + self.api_key[-4:] if self.api_key and len(self.api_key) > 4 else 'NOT SET'

        print(f"BREVO_API_KEY:    {api_key_display}")
        print(f"BREVO_FROM_EMAIL: {self.from_email}")
        print(f"BREVO_FROM_NAME:  {self.from_name}")
        print(f"API Endpoint:     {self.base_url}")
        print()

        if not self.api_key:
            print("WARNING: BREVO_API_KEY is not set!")
            print("\nTo set it, either:")
            print("  1. Export it: export BREVO_API_KEY='your-api-key'")
            print("  2. Add to .env file: BREVO_API_KEY=your-api-key")
            return False

        # Test API key validity
        print("Testing API key...")
        headers = {
            'accept': 'application/json',
            'api-key': self.api_key
        }

        try:
            response = requests.get(f"{self.base_url}/account", headers=headers, timeout=10)
            if response.status_code == 200:
                account = response.json()
                print(f"✓ API key is valid!")
                print(f"  Account Email: {account.get('email', 'N/A')}")
                print(f"  Company Name: {account.get('companyName', 'N/A')}")

                # Check email credits
                plan = account.get('plan', [])
                if plan:
                    for p in plan:
                        print(f"  Plan Type: {p.get('type', 'N/A')}")
                        print(f"  Credits: {p.get('credits', 'N/A')}")
                return True
            else:
                print(f"✗ API key validation failed: {response.status_code}")
                print(f"  Response: {response.text}")
                return False
        except Exception as e:
            print(f"✗ Error validating API key: {e}")
            return False

    def send_test_email(self, to_email, subject, body_html, to_name=None):
        """Send a test email via Brevo API."""
        print(f"\n{'='*60}")
        print("SENDING TEST EMAIL VIA BREVO")
        print(f"{'='*60}")
        print(f"To:      {to_email}")
        print(f"From:    {self.from_name} <{self.from_email}>")
        print(f"Subject: {subject}")
        print(f"Time:    {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*60}\n")

        if not self.api_key:
            print("✗ BREVO_API_KEY is not configured!")
            return False

        headers = {
            'accept': 'application/json',
            'api-key': self.api_key,
            'content-type': 'application/json'
        }

        payload = {
            'sender': {
                'name': self.from_name,
                'email': self.from_email
            },
            'to': [
                {
                    'email': to_email,
                    'name': to_name or to_email.split('@')[0]
                }
            ],
            'subject': subject,
            'htmlContent': body_html
        }

        try:
            print("Sending email...")
            response = requests.post(
                f"{self.base_url}/smtp/email",
                headers=headers,
                json=payload,
                timeout=30
            )

            if response.status_code == 201:
                result = response.json()
                print(f"\n✓ Email sent successfully!")
                print(f"  Message ID: {result.get('messageId', 'N/A')}")
                return True
            elif response.status_code == 429:
                print(f"\n✗ Rate limited! Too many emails sent.")
                print(f"  Wait and try again later.")
                return False
            else:
                print(f"\n✗ Failed to send email: HTTP {response.status_code}")
                try:
                    error = response.json()
                    print(f"  Error: {error.get('message', response.text)}")
                except:
                    print(f"  Response: {response.text}")
                return False

        except requests.exceptions.Timeout:
            print("\n✗ Request timed out!")
            return False
        except requests.exceptions.RequestException as e:
            print(f"\n✗ Request error: {e}")
            return False
        except Exception as e:
            print(f"\n✗ Unexpected error: {e}")
            import traceback
            traceback.print_exc()
            return False

    def get_email_stats(self, days=7):
        """Get email sending statistics."""
        print(f"\n{'='*60}")
        print(f"EMAIL STATISTICS (Last {days} days)")
        print(f"{'='*60}\n")

        if not self.api_key:
            print("✗ BREVO_API_KEY is not configured!")
            return False

        headers = {
            'accept': 'application/json',
            'api-key': self.api_key
        }

        try:
            response = requests.get(
                f"{self.base_url}/smtp/statistics/aggregatedReport",
                headers=headers,
                params={'days': days},
                timeout=10
            )

            if response.status_code == 200:
                stats = response.json()
                print(f"Requests:     {stats.get('requests', 0)}")
                print(f"Delivered:    {stats.get('delivered', 0)}")
                print(f"Opens:        {stats.get('uniqueOpens', 0)} unique / {stats.get('opens', 0)} total")
                print(f"Clicks:       {stats.get('uniqueClicks', 0)} unique / {stats.get('clicks', 0)} total")
                print(f"Hard Bounces: {stats.get('hardBounces', 0)}")
                print(f"Soft Bounces: {stats.get('softBounces', 0)}")
                print(f"Complaints:   {stats.get('spamComplaints', 0)}")
                print(f"Unsubscribes: {stats.get('unsubscriptions', 0)}")
                print(f"Blocked:      {stats.get('blocked', 0)}")
                print(f"Invalid:      {stats.get('invalid', 0)}")
                return True
            else:
                print(f"✗ Failed to get stats: HTTP {response.status_code}")
                return False

        except Exception as e:
            print(f"✗ Error getting stats: {e}")
            return False


def get_default_test_html():
    """Get default test email HTML content."""
    return """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
        .container { max-width: 600px; margin: 0 auto; padding: 20px; }
        .header { background: #4CAF50; color: white; padding: 20px; text-align: center; border-radius: 8px 8px 0 0; }
        .content { background: #f9f9f9; padding: 30px; border: 1px solid #ddd; }
        .footer { background: #333; color: #999; padding: 15px; text-align: center; font-size: 12px; border-radius: 0 0 8px 8px; }
        .button { display: inline-block; background: #4CAF50; color: white; padding: 12px 24px; text-decoration: none; border-radius: 4px; margin: 10px 0; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>Test Email</h1>
        </div>
        <div class="content">
            <h2>Email System Test</h2>
            <p>This is a test email from the FieldSprout email system.</p>
            <p>If you received this message, it means:</p>
            <ul>
                <li>✓ Your Brevo API key is working</li>
                <li>✓ Email delivery is functioning</li>
                <li>✓ The sender email is configured correctly</li>
            </ul>
            <p>
                <a href="https://fieldsprout.io" class="button">Visit FieldSprout</a>
            </p>
            <p><strong>Sent at:</strong> """ + datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC') + """</p>
        </div>
        <div class="footer">
            <p>This is an automated test email from FieldSprout.</p>
        </div>
    </div>
</body>
</html>
"""


def main():
    parser = argparse.ArgumentParser(
        description='Test email sending via Brevo API',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --check-config              Check API configuration
  %(prog)s --to user@example.com       Send test email
  %(prog)s --to user@example.com \\
           --subject "Custom Subject"  Send with custom subject
  %(prog)s --stats                     Show email statistics
        """
    )

    # Actions
    parser.add_argument('--check-config', action='store_true',
                        help='Check Brevo API configuration')
    parser.add_argument('--stats', action='store_true',
                        help='Show email sending statistics')

    # Email options
    parser.add_argument('--to', type=str,
                        help='Recipient email address')
    parser.add_argument('--to-name', type=str,
                        help='Recipient name (optional)')
    parser.add_argument('--subject', type=str,
                        default='Test Email from FieldSprout',
                        help='Email subject line')
    parser.add_argument('--body', type=str,
                        help='Custom HTML body (uses default test template if not provided)')

    # Stats options
    parser.add_argument('--days', type=int, default=7,
                        help='Number of days for statistics (default: 7)')

    args = parser.parse_args()

    tester = BrevoEmailTester()

    # Check config
    if args.check_config:
        success = tester.check_config()
        sys.exit(0 if success else 1)

    # Show stats
    if args.stats:
        success = tester.get_email_stats(args.days)
        sys.exit(0 if success else 1)

    # Send test email
    if args.to:
        body_html = args.body or get_default_test_html()
        success = tester.send_test_email(
            to_email=args.to,
            subject=args.subject,
            body_html=body_html,
            to_name=args.to_name
        )
        sys.exit(0 if success else 1)

    # No action specified - show help and quick start
    parser.print_help()
    print("\n" + "="*60)
    print("QUICK START")
    print("="*60)
    print("\n1. First, check your configuration:")
    print("   python test_email_send.py --check-config")
    print("\n2. If API key is not set, export it:")
    print("   export BREVO_API_KEY='your-api-key-here'")
    print("\n3. Send a test email:")
    print("   python test_email_send.py --to your@email.com")
    print("\n4. View email statistics:")
    print("   python test_email_send.py --stats")
    print()


if __name__ == '__main__':
    main()
