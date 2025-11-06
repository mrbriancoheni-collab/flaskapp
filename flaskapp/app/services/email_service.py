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
    # Prefer David credentials for bulk/CRM emails, fallback to regular credentials
    smtp_user = (current_app.config.get('MAIL_USERNAME_DAVID') or os.getenv('MAIL_USERNAME_DAVID') or
                current_app.config.get('SMTP_USER') or os.getenv('SMTP_USER') or
                current_app.config.get('MAIL_USERNAME') or os.getenv('MAIL_USERNAME') or '')

    smtp_password = (current_app.config.get('MAIL_PASSWORD_DAVID') or os.getenv('MAIL_PASSWORD_DAVID') or
                    current_app.config.get('SMTP_PASSWORD') or os.getenv('SMTP_PASSWORD') or
                    current_app.config.get('MAIL_PASSWORD') or os.getenv('MAIL_PASSWORD') or '')

    # Use David email as from address if available
    from_email = (current_app.config.get('MAIL_USERNAME_DAVID') or os.getenv('MAIL_USERNAME_DAVID') or
                 current_app.config.get('EMAIL_FROM') or os.getenv('EMAIL_FROM') or
                 'noreply@fieldsprout.com')

    return {
        'provider': current_app.config.get('EMAIL_PROVIDER', os.getenv('EMAIL_PROVIDER', 'smtp')),
        'from_email': from_email,
        'from_name': current_app.config.get('EMAIL_FROM_NAME', os.getenv('EMAIL_FROM_NAME', 'FieldSprout')),

        # SMTP settings - prefer MAIL_* env vars (used by test_email.py)
        'smtp_host': (current_app.config.get('MAIL_SERVER') or os.getenv('MAIL_SERVER') or
                     current_app.config.get('SMTP_HOST') or os.getenv('SMTP_HOST') or 'localhost'),
        'smtp_port': int(current_app.config.get('MAIL_PORT') or os.getenv('MAIL_PORT') or
                        current_app.config.get('SMTP_PORT') or os.getenv('SMTP_PORT') or '587'),
        'smtp_user': smtp_user,
        'smtp_password': smtp_password,
        'smtp_use_tls': (current_app.config.get('MAIL_USE_TLS') or os.getenv('MAIL_USE_TLS') or
                        current_app.config.get('SMTP_USE_TLS') or os.getenv('SMTP_USE_TLS') or 'true').lower() == 'true',
        'smtp_use_ssl': (current_app.config.get('MAIL_USE_SSL') or os.getenv('MAIL_USE_SSL') or
                        current_app.config.get('SMTP_USE_SSL') or os.getenv('SMTP_USE_SSL') or 'false').lower() == 'true',

        # SendGrid settings
        'sendgrid_api_key': current_app.config.get('SENDGRID_API_KEY', os.getenv('SENDGRID_API_KEY', '')),
    }


def send_email(
    to: str,
    subject: str,
    html_body: str,
    text_body: Optional[str] = None,
    reply_to: Optional[str] = None,
    from_email: Optional[str] = None,
    from_name: Optional[str] = None,
    use_bulk_credentials: bool = False
) -> bool:
    """
    Send an email using configured provider.

    Args:
        to: Recipient email address
        subject: Email subject
        html_body: HTML email body
        text_body: Plain text fallback (optional, generated from HTML if not provided)
        reply_to: Reply-to address (optional)
        from_email: Override sender email (optional, for individual emails from admin users)
        from_name: Override sender name (optional)
        use_bulk_credentials: If True, use David credentials for bulk emails (default: False)

    Returns:
        True if email sent successfully, False otherwise
    """
    config = get_email_config()
    provider = config['provider']

    # Override from_email if provided (for individual emails from logged-in user)
    if from_email:
        config['from_email'] = from_email
        if from_name:
            config['from_name'] = from_name
    elif not use_bulk_credentials:
        # For individual emails without explicit sender, log a warning
        current_app.logger.warning(
            f"Sending individual email without explicit from_email. Using default: {config['from_email']}"
        )

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
    smtp_use_tls = config['smtp_use_tls']
    smtp_use_ssl = str(config.get('smtp_use_ssl', 'false')).lower() in ('1', 'true', 'yes')

    if not smtp_host or smtp_host == 'localhost':
        current_app.logger.warning(f"SMTP not configured, email to {to} not sent: {subject}")
        return False

    # Auto-correct common misconfigurations based on port
    if smtp_port == 587 and smtp_use_ssl:
        current_app.logger.warning("Auto-correcting: port 587 requires STARTTLS, not SSL")
        smtp_use_ssl = False
        smtp_use_tls = True
    elif smtp_port == 465 and not smtp_use_ssl:
        current_app.logger.warning("Auto-correcting: port 465 requires SSL")
        smtp_use_ssl = True
        smtp_use_tls = False

    current_app.logger.info(f"Sending email to {to} via {smtp_host}:{smtp_port} (SSL={smtp_use_ssl}, TLS={smtp_use_tls})")

    try:
        if smtp_use_ssl:
            # Port 465: SSL/TLS from start
            with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=20) as server:
                if config['smtp_user'] and config['smtp_password']:
                    server.login(config['smtp_user'], config['smtp_password'])
                server.send_message(msg)
        else:
            # Port 587: Plain connection, then STARTTLS
            with smtplib.SMTP(smtp_host, smtp_port, timeout=20) as server:
                if smtp_use_tls:
                    server.starttls()
                if config['smtp_user'] and config['smtp_password']:
                    server.login(config['smtp_user'], config['smtp_password'])
                server.send_message(msg)

        current_app.logger.info(f"Email sent via SMTP to {to}: {subject}")
        return True
    except Exception as e:
        current_app.logger.error(f"SMTP error sending to {to}: {type(e).__name__}: {e}")
        raise


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

    base_url = current_app.config.get("BASE_URL", "https://fieldsprout.io")
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
    """, user=user, dashboard_url=f"{current_app.config.get('BASE_URL', 'https://fieldsprout.io')}/account/dashboard", year=2025)

    text_body = f"""
Welcome to FieldSprout!

Hi {user.name},

Thanks for signing up! We're excited to help you grow your local business with AI-powered marketing insights.

Get Started in 3 Steps:
1. Connect your Google, Facebook, and WordPress accounts
2. Review your first automated insights report
3. Invite your team to collaborate

Go to your dashboard: {current_app.config.get('BASE_URL', 'https://fieldsprout.io')}/account/dashboard

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
    billing_url=f"{current_app.config.get('BASE_URL', 'https://fieldsprout.io')}/billing/portal")

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
    """, user=user, billing_url=f"{current_app.config.get('BASE_URL', 'https://fieldsprout.io')}/billing/portal")

    return send_email(
        to=user.email,
        subject="Action Required: Payment Failed",
        html_body=html_body
    )


# ===== Tracked Email Sending (for CRM contacts) =====

def send_tracked_email_to_crm_contact(
    crm_contact_id: int,
    subject: str,
    html_body: str,
    text_body: Optional[str] = None,
    campaign_name: Optional[str] = None,
    sent_by_user_id: Optional[int] = None,
    track_clicks: bool = True
):
    """
    Send an email to a CRM contact with tracking enabled.

    This function:
    1. Generates a tracking token
    2. Saves the email to the database (EmailSent)
    3. Injects tracking pixel and wraps links
    4. Sends the email
    5. Returns the EmailSent record

    SENDER LOGIC:
    - Individual emails (no campaign_name): Use the logged-in admin user's email
    - Bulk campaigns (with campaign_name): Use David credentials (MAIL_USERNAME_DAVID)

    Args:
        crm_contact_id: ID of the CRMContact to send to
        subject: Email subject line
        html_body: HTML email body (will be modified to add tracking)
        text_body: Plain text version (optional)
        campaign_name: Optional campaign identifier for grouping (triggers bulk mode)
        sent_by_user_id: ID of user sending the email (optional)
        track_clicks: Whether to track link clicks (default: True)

    Returns:
        EmailSent record if successful, None if failed
    """
    from app.models import CRMContact, EmailSent, User
    from app.extensions import db
    from app.services.email_tracking import (
        generate_tracking_token,
        prepare_tracked_email
    )

    # Get the CRM contact
    contact = CRMContact.query.get(crm_contact_id)
    if not contact:
        current_app.logger.error(f"CRM contact {crm_contact_id} not found")
        return None

    if not contact.email:
        current_app.logger.error(f"CRM contact {crm_contact_id} has no email address")
        return None

    # Determine sender email and name
    from_email = None
    from_name = None
    use_bulk_credentials = False

    if campaign_name:
        # Bulk campaign - use David credentials
        use_bulk_credentials = True
        current_app.logger.info(f"Bulk campaign '{campaign_name}' - using David credentials")
    elif sent_by_user_id:
        # Individual email - use the sender's email
        sender_user = User.query.get(sent_by_user_id)
        if sender_user:
            from_email = sender_user.email
            from_name = sender_user.name
            current_app.logger.info(f"Individual email from {from_name} <{from_email}>")
        else:
            current_app.logger.warning(f"Sender user {sent_by_user_id} not found, using default")
    else:
        current_app.logger.warning("No campaign_name or sent_by_user_id - using default sender")

    # Generate tracking token
    tracking_token = generate_tracking_token()

    # Get base URL for tracking links
    base_url = current_app.config.get("BASE_URL", "https://fieldsprout.io")

    # Prepare HTML with tracking pixel and link tracking
    tracked_html = prepare_tracked_email(
        html_body=html_body,
        tracking_token=tracking_token,
        base_url=base_url,
        track_clicks=track_clicks
    )

    # Create EmailSent record
    email_sent = EmailSent(
        crm_contact_id=crm_contact_id,
        sent_by_user_id=sent_by_user_id,
        subject=subject,
        body_html=tracked_html,
        body_text=text_body,
        tracking_token=tracking_token,
        campaign_name=campaign_name
    )

    try:
        # Save to database first
        db.session.add(email_sent)
        db.session.commit()

        # Send the email with appropriate sender
        success = send_email(
            to=contact.email,
            subject=subject,
            html_body=tracked_html,
            text_body=text_body,
            from_email=from_email,
            from_name=from_name,
            use_bulk_credentials=use_bulk_credentials
        )

        if success:
            email_sent.delivered = True
            current_app.logger.info(
                f"Tracked email sent to CRM contact {crm_contact_id} ({contact.email}): {subject}"
            )
        else:
            email_sent.delivered = False
            email_sent.bounced = True
            current_app.logger.error(
                f"Failed to send tracked email to CRM contact {crm_contact_id} ({contact.email})"
            )

        db.session.commit()
        return email_sent

    except Exception as e:
        current_app.logger.error(f"Error sending tracked email: {e}", exc_info=True)
        db.session.rollback()
        return None


def send_bulk_tracked_emails(
    crm_contact_ids: List[int],
    subject: str,
    html_body: str,
    text_body: Optional[str] = None,
    campaign_name: Optional[str] = None,
    sent_by_user_id: Optional[int] = None
) -> Dict[str, Any]:
    """
    Send tracked emails to multiple CRM contacts.

    Args:
        crm_contact_ids: List of CRMContact IDs
        subject: Email subject (same for all)
        html_body: HTML body (same for all, tracking will be unique per contact)
        text_body: Plain text version (optional)
        campaign_name: Campaign identifier for grouping
        sent_by_user_id: ID of user sending emails

    Returns:
        Dictionary with results:
        {
            'total': int,
            'sent': int,
            'failed': int,
            'email_ids': List[int]  # IDs of EmailSent records created
        }
    """
    results = {
        'total': len(crm_contact_ids),
        'sent': 0,
        'failed': 0,
        'email_ids': []
    }

    for contact_id in crm_contact_ids:
        email_sent = send_tracked_email_to_crm_contact(
            crm_contact_id=contact_id,
            subject=subject,
            html_body=html_body,  # Function will add unique tracking for each email
            text_body=text_body,
            campaign_name=campaign_name,
            sent_by_user_id=sent_by_user_id
        )

        if email_sent and email_sent.delivered:
            results['sent'] += 1
            results['email_ids'].append(email_sent.id)
        else:
            results['failed'] += 1

    current_app.logger.info(
        f"Bulk email campaign '{campaign_name}': "
        f"{results['sent']}/{results['total']} sent successfully"
    )

    return results
