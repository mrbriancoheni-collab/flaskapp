# app/services/email_service.py
"""
Email service for sending transactional emails.

Supports multiple providers:
- SMTP (via Flask-Mail or standard smtplib)
- SendGrid API
- AWS SES (future)

Configuration via environment variables:
- EMAIL_PROVIDER: 'smtp' or 'sendgrid'
- For SMTP:
  - SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_USE_TLS
- For SendGrid:
  - SENDGRID_API_KEY
"""

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional, List, Dict, Any
from flask import current_app, render_template_string


def get_email_config() -> Dict[str, Any]:
    """Get email configuration from app config or environment."""
    return {
        'provider': current_app.config.get('EMAIL_PROVIDER', os.getenv('EMAIL_PROVIDER', 'smtp')),
        'from_email': current_app.config.get('EMAIL_FROM', os.getenv('EMAIL_FROM', 'noreply@fieldsprout.com')),
        'from_name': current_app.config.get('EMAIL_FROM_NAME', os.getenv('EMAIL_FROM_NAME', 'FieldSprout')),

        # SMTP settings
        'smtp_host': current_app.config.get('SMTP_HOST', os.getenv('SMTP_HOST', 'localhost')),
        'smtp_port': int(current_app.config.get('SMTP_PORT', os.getenv('SMTP_PORT', '587'))),
        'smtp_user': current_app.config.get('SMTP_USER', os.getenv('SMTP_USER', '')),
        'smtp_password': current_app.config.get('SMTP_PASSWORD', os.getenv('SMTP_PASSWORD', '')),
        'smtp_use_tls': current_app.config.get('SMTP_USE_TLS', os.getenv('SMTP_USE_TLS', 'true').lower() == 'true'),

        # SendGrid settings
        'sendgrid_api_key': current_app.config.get('SENDGRID_API_KEY', os.getenv('SENDGRID_API_KEY', '')),
    }


def send_email(
    to: str,
    subject: str,
    html_body: str,
    text_body: Optional[str] = None,
    reply_to: Optional[str] = None
) -> bool:
    """
    Send an email using configured provider.

    Args:
        to: Recipient email address
        subject: Email subject
        html_body: HTML email body
        text_body: Plain text fallback (optional, generated from HTML if not provided)
        reply_to: Reply-to address (optional)

    Returns:
        True if email sent successfully, False otherwise
    """
    config = get_email_config()
    provider = config['provider']

    try:
        if provider == 'sendgrid':
            return _send_via_sendgrid(to, subject, html_body, text_body, reply_to, config)
        else:  # Default to SMTP
            return _send_via_smtp(to, subject, html_body, text_body, reply_to, config)
    except Exception as e:
        current_app.logger.error(f"Failed to send email to {to}: {e}", exc_info=True)
        return False


def _send_via_smtp(
    to: str,
    subject: str,
    html_body: str,
    text_body: Optional[str],
    reply_to: Optional[str],
    config: Dict[str, Any]
) -> bool:
    """Send email via SMTP."""
    from_email = f"{config['from_name']} <{config['from_email']}>"

    # Create message
    msg = MIMEMultipart('alternative')
    msg['From'] = from_email
    msg['To'] = to
    msg['Subject'] = subject

    if reply_to:
        msg['Reply-To'] = reply_to

    # Add text and HTML parts
    if text_body:
        text_part = MIMEText(text_body, 'plain')
        msg.attach(text_part)

    html_part = MIMEText(html_body, 'html')
    msg.attach(html_part)

    # Send via SMTP
    smtp_host = config['smtp_host']
    smtp_port = config['smtp_port']

    if not smtp_host or smtp_host == 'localhost':
        current_app.logger.warning(f"SMTP not configured, email to {to} not sent: {subject}")
        return False

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        if config['smtp_use_tls']:
            server.starttls()

        if config['smtp_user'] and config['smtp_password']:
            server.login(config['smtp_user'], config['smtp_password'])

        server.send_message(msg)

    current_app.logger.info(f"Email sent via SMTP to {to}: {subject}")
    return True


def _send_via_sendgrid(
    to: str,
    subject: str,
    html_body: str,
    text_body: Optional[str],
    reply_to: Optional[str],
    config: Dict[str, Any]
) -> bool:
    """Send email via SendGrid API."""
    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail, Email, To, Content
    except ImportError:
        current_app.logger.error("SendGrid library not installed. Run: pip install sendgrid")
        return False

    api_key = config['sendgrid_api_key']
    if not api_key:
        current_app.logger.warning(f"SendGrid API key not configured, email to {to} not sent")
        return False

    # Create message
    from_email = Email(config['from_email'], config['from_name'])
    to_email = To(to)
    content = Content("text/html", html_body)

    message = Mail(from_email, to_email, subject, content)

    if text_body:
        message.add_content(Content("text/plain", text_body))

    if reply_to:
        message.reply_to = Email(reply_to)

    # Send via SendGrid
    sg = SendGridAPIClient(api_key)
    response = sg.send(message)

    if response.status_code in [200, 201, 202]:
        current_app.logger.info(f"Email sent via SendGrid to {to}: {subject}")
        return True
    else:
        current_app.logger.error(f"SendGrid returned status {response.status_code} for {to}")
        return False


# ===== Specific Email Templates =====

def send_team_invite_email(invite, inviter) -> bool:
    """
    Send team invitation email.

    Args:
        invite: TeamInvite model instance
        inviter: User who sent the invite

    Returns:
        True if sent successfully
    """
    from app.models import Account

    account = Account.query.get(invite.account_id)
    account_name = account.name if account else "a team"

    base_url = current_app.config.get("BASE_URL", "http://localhost:5000")
    invite_url = f"{base_url}/team/invite/{invite.token}"

    html_body = render_template_string("""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Team Invitation</title>
</head>
<body style="margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f9fafb;">
    <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #f9fafb; padding: 40px 20px;">
        <tr>
            <td align="center">
                <table width="600" cellpadding="0" cellspacing="0" style="background-color: #ffffff; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1);">
                    <!-- Header -->
                    <tr>
                        <td style="padding: 40px 40px 20px; text-align: center; background: linear-gradient(135deg, #7c3aed 0%, #6d28d9 100%); border-radius: 8px 8px 0 0;">
                            <h1 style="margin: 0; color: #ffffff; font-size: 24px; font-weight: 600;">You're Invited!</h1>
                        </td>
                    </tr>

                    <!-- Content -->
                    <tr>
                        <td style="padding: 40px;">
                            <p style="margin: 0 0 20px; font-size: 16px; line-height: 24px; color: #111827;">
                                <strong>{{ inviter.name }}</strong> ({{ inviter.email }}) has invited you to join <strong>{{ account_name }}</strong> as a <strong>{{ invite.role }}</strong>.
                            </p>

                            <p style="margin: 0 0 30px; font-size: 14px; line-height: 22px; color: #6b7280;">
                                Click the button below to accept the invitation and get started. This invitation will expire in 7 days.
                            </p>

                            <!-- CTA Button -->
                            <table width="100%" cellpadding="0" cellspacing="0">
                                <tr>
                                    <td align="center" style="padding: 0 0 30px;">
                                        <a href="{{ invite_url }}" style="display: inline-block; padding: 14px 32px; background-color: #7c3aed; color: #ffffff; text-decoration: none; border-radius: 6px; font-size: 16px; font-weight: 600;">
                                            Accept Invitation
                                        </a>
                                    </td>
                                </tr>
                            </table>

                            <p style="margin: 0 0 20px; font-size: 14px; line-height: 22px; color: #6b7280;">
                                Or copy and paste this URL into your browser:
                            </p>
                            <p style="margin: 0 0 30px; padding: 12px; background-color: #f3f4f6; border-radius: 4px; font-size: 12px; color: #4b5563; word-break: break-all; font-family: monospace;">
                                {{ invite_url }}
                            </p>

                            <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 30px 0;">

                            <p style="margin: 0; font-size: 13px; line-height: 20px; color: #9ca3af;">
                                If you don't have an account yet, you'll be able to create one when you click the link. If you didn't expect this invitation, you can safely ignore this email.
                            </p>
                        </td>
                    </tr>

                    <!-- Footer -->
                    <tr>
                        <td style="padding: 20px 40px; text-align: center; background-color: #f9fafb; border-radius: 0 0 8px 8px;">
                            <p style="margin: 0; font-size: 12px; color: #9ca3af;">
                                © {{ year }} FieldSprout. All rights reserved.
                            </p>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>
    """, inviter=inviter, invite=invite, account_name=account_name, invite_url=invite_url, year=2025)

    text_body = f"""
You're Invited to Join {account_name}!

{inviter.name} ({inviter.email}) has invited you to join {account_name} as a {invite.role}.

Click the link below to accept the invitation:
{invite_url}

This invitation will expire in 7 days.

If you don't have an account yet, you'll be able to create one when you click the link.

If you didn't expect this invitation, you can safely ignore this email.

© 2025 FieldSprout. All rights reserved.
    """

    return send_email(
        to=invite.email,
        subject=f"{inviter.name} invited you to join {account_name}",
        html_body=html_body,
        text_body=text_body
    )


def send_welcome_email(user) -> bool:
    """
    Send welcome email to new user.

    Args:
        user: User model instance

    Returns:
        True if sent successfully
    """
    html_body = render_template_string("""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Welcome to FieldSprout</title>
</head>
<body style="margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f9fafb;">
    <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #f9fafb; padding: 40px 20px;">
        <tr>
            <td align="center">
                <table width="600" cellpadding="0" cellspacing="0" style="background-color: #ffffff; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1);">
                    <!-- Header -->
                    <tr>
                        <td style="padding: 40px 40px 20px; text-align: center; background: linear-gradient(135deg, #7c3aed 0%, #6d28d9 100%); border-radius: 8px 8px 0 0;">
                            <h1 style="margin: 0; color: #ffffff; font-size: 28px; font-weight: 600;">Welcome to FieldSprout!</h1>
                        </td>
                    </tr>

                    <!-- Content -->
                    <tr>
                        <td style="padding: 40px;">
                            <p style="margin: 0 0 20px; font-size: 16px; line-height: 24px; color: #111827;">
                                Hi <strong>{{ user.name }}</strong>,
                            </p>

                            <p style="margin: 0 0 20px; font-size: 16px; line-height: 24px; color: #111827;">
                                Thanks for signing up! We're excited to help you grow your local business with AI-powered marketing insights.
                            </p>

                            <div style="margin: 30px 0; padding: 20px; background-color: #f3f4f6; border-left: 4px solid #7c3aed; border-radius: 4px;">
                                <h3 style="margin: 0 0 15px; font-size: 18px; color: #111827;">Get Started in 3 Steps:</h3>
                                <ol style="margin: 0; padding-left: 20px; color: #4b5563;">
                                    <li style="margin-bottom: 10px;">Connect your Google, Facebook, and WordPress accounts</li>
                                    <li style="margin-bottom: 10px;">Review your first automated insights report</li>
                                    <li>Invite your team to collaborate</li>
                                </ol>
                            </div>

                            <!-- CTA Button -->
                            <table width="100%" cellpadding="0" cellspacing="0">
                                <tr>
                                    <td align="center" style="padding: 20px 0;">
                                        <a href="{{ dashboard_url }}" style="display: inline-block; padding: 14px 32px; background-color: #7c3aed; color: #ffffff; text-decoration: none; border-radius: 6px; font-size: 16px; font-weight: 600;">
                                            Go to Dashboard
                                        </a>
                                    </td>
                                </tr>
                            </table>

                            <p style="margin: 30px 0 0; font-size: 14px; line-height: 22px; color: #6b7280;">
                                Need help? Check out our <a href="#" style="color: #7c3aed; text-decoration: none;">documentation</a> or <a href="#" style="color: #7c3aed; text-decoration: none;">contact support</a>.
                            </p>
                        </td>
                    </tr>

                    <!-- Footer -->
                    <tr>
                        <td style="padding: 20px 40px; text-align: center; background-color: #f9fafb; border-radius: 0 0 8px 8px;">
                            <p style="margin: 0; font-size: 12px; color: #9ca3af;">
                                © {{ year }} FieldSprout. All rights reserved.
                            </p>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>
    """, user=user, dashboard_url=f"{current_app.config.get('BASE_URL', 'http://localhost:5000')}/account/dashboard", year=2025)

    text_body = f"""
Welcome to FieldSprout!

Hi {user.name},

Thanks for signing up! We're excited to help you grow your local business with AI-powered marketing insights.

Get Started in 3 Steps:
1. Connect your Google, Facebook, and WordPress accounts
2. Review your first automated insights report
3. Invite your team to collaborate

Go to your dashboard: {current_app.config.get('BASE_URL', 'http://localhost:5000')}/account/dashboard

Need help? Check out our documentation or contact support.

© 2025 FieldSprout. All rights reserved.
    """

    return send_email(
        to=user.email,
        subject="Welcome to FieldSprout - Let's Get Started!",
        html_body=html_body,
        text_body=text_body
    )


def send_subscription_confirmation_email(user, subscription) -> bool:
    """Send email confirming subscription purchase."""
    plan_name = "Growth Plan"  # Customize based on subscription.price_id

    html_body = render_template_string("""
<!DOCTYPE html>
<html>
<body style="font-family: Arial, sans-serif; background-color: #f9fafb; padding: 20px;">
    <div style="max-width: 600px; margin: 0 auto; background-color: #ffffff; border-radius: 8px; padding: 40px;">
        <h1 style="color: #7c3aed; margin-bottom: 20px;">Subscription Confirmed!</h1>

        <p>Hi {{ user.name }},</p>

        <p>Your subscription to <strong>{{ plan_name }}</strong> is now active.</p>

        <p><strong>Next billing date:</strong> {{ subscription.current_period_end.strftime('%B %d, %Y') }}</p>

        <p>You now have access to:</p>
        <ul>
            <li>AI campaign suggestions</li>
            <li>Lead quality insights</li>
            <li>A/B creative tips</li>
            <li>Team collaboration (up to 10 members)</li>
        </ul>

        <p style="margin-top: 30px;">
            <a href="{{ billing_url }}" style="display: inline-block; padding: 12px 24px; background-color: #7c3aed; color: #ffffff; text-decoration: none; border-radius: 6px;">
                Manage Subscription
            </a>
        </p>

        <p style="margin-top: 30px; font-size: 14px; color: #6b7280;">
            Questions? Contact us at support@fieldsprout.com
        </p>
    </div>
</body>
</html>
    """, user=user, plan_name=plan_name, subscription=subscription,
    billing_url=f"{current_app.config.get('BASE_URL', 'http://localhost:5000')}/billing/portal")

    return send_email(
        to=user.email,
        subject=f"Your {plan_name} Subscription is Active",
        html_body=html_body
    )


def send_payment_failed_email(user, subscription) -> bool:
    """Send email when payment fails."""
    html_body = render_template_string("""
<!DOCTYPE html>
<html>
<body style="font-family: Arial, sans-serif; background-color: #f9fafb; padding: 20px;">
    <div style="max-width: 600px; margin: 0 auto; background-color: #ffffff; border-radius: 8px; padding: 40px; border-left: 4px solid #ef4444;">
        <h1 style="color: #ef4444; margin-bottom: 20px;">Payment Failed</h1>

        <p>Hi {{ user.name }},</p>

        <p>We were unable to process your recent payment. Your subscription may be interrupted if this isn't resolved.</p>

        <p><strong>What to do next:</strong></p>
        <ol>
            <li>Check that your payment method is valid and has sufficient funds</li>
            <li>Update your payment method in the billing portal</li>
            <li>Retry the payment</li>
        </ol>

        <p style="margin-top: 30px;">
            <a href="{{ billing_url }}" style="display: inline-block; padding: 12px 24px; background-color: #ef4444; color: #ffffff; text-decoration: none; border-radius: 6px;">
                Update Payment Method
            </a>
        </p>

        <p style="margin-top: 30px; font-size: 14px; color: #6b7280;">
            Need help? Contact us at support@fieldsprout.com
        </p>
    </div>
</body>
</html>
    """, user=user, billing_url=f"{current_app.config.get('BASE_URL', 'http://localhost:5000')}/billing/portal")

    return send_email(
        to=user.email,
        subject="Action Required: Payment Failed",
        html_body=html_body
    )
