"""
Email Tracking Service

Provides tracking pixel and click tracking functionality for email campaigns.
Tracks opens and clicks for emails sent to CRM contacts.
"""
import secrets
import logging
from datetime import datetime
from typing import Optional, Dict, Any
from urllib.parse import urljoin, quote
import re

from flask import url_for

logger = logging.getLogger(__name__)


def generate_tracking_token() -> str:
    """
    Generate a unique tracking token for an email.

    Returns:
        32-character hex token
    """
    return secrets.token_hex(32)


def get_tracking_pixel_url(tracking_token: str, base_url: str = None) -> str:
    """
    Get the URL for the tracking pixel image.

    Args:
        tracking_token: Unique token for this email
        base_url: Base URL of the application (optional, will use url_for if not provided)

    Returns:
        Full URL to the tracking pixel endpoint
    """
    if base_url:
        # Manual URL construction when base_url is provided
        return f"{base_url}/track/pixel/{tracking_token}.gif"
    else:
        # Use Flask's url_for (requires application context)
        try:
            return url_for('email_tracking_bp.tracking_pixel', token=tracking_token, _external=True)
        except RuntimeError:
            # If no app context, return relative URL
            return f"/track/pixel/{tracking_token}.gif"


def get_click_tracking_url(tracking_token: str, destination_url: str, base_url: str = None) -> str:
    """
    Get a click-tracking URL that wraps the destination URL.

    Args:
        tracking_token: Unique token for this email
        destination_url: The actual URL the user should be redirected to
        base_url: Base URL of the application (optional)

    Returns:
        Full URL to the click tracking endpoint with encoded destination
    """
    encoded_url = quote(destination_url, safe='')

    if base_url:
        return f"{base_url}/track/click/{tracking_token}?url={encoded_url}"
    else:
        try:
            return url_for('email_tracking_bp.click_tracking',
                          token=tracking_token,
                          url=destination_url,
                          _external=True)
        except RuntimeError:
            return f"/track/click/{tracking_token}?url={encoded_url}"


def inject_tracking_pixel(html_body: str, tracking_token: str, base_url: str = None) -> str:
    """
    Inject a tracking pixel into HTML email body.

    Args:
        html_body: HTML content of the email
        tracking_token: Unique token for this email
        base_url: Base URL of the application

    Returns:
        Modified HTML with tracking pixel injected before closing </body> tag
    """
    if not html_body:
        return html_body

    pixel_url = get_tracking_pixel_url(tracking_token, base_url)
    tracking_pixel = f'<img src="{pixel_url}" width="1" height="1" style="display:none;" alt="" />'

    # Try to inject before </body> tag
    if '</body>' in html_body.lower():
        # Case-insensitive replacement
        import re
        html_body = re.sub(r'</body>', f'{tracking_pixel}</body>', html_body, flags=re.IGNORECASE)
    else:
        # Append to end if no </body> tag
        html_body += tracking_pixel

    return html_body


def wrap_links_with_tracking(html_body: str, tracking_token: str, base_url: str = None) -> str:
    """
    Wrap all links in HTML email with click tracking URLs.

    Args:
        html_body: HTML content of the email
        tracking_token: Unique token for this email
        base_url: Base URL of the application

    Returns:
        Modified HTML with all links wrapped in tracking URLs
    """
    if not html_body:
        return html_body

    # Find all href attributes in <a> tags
    def replace_href(match):
        full_tag = match.group(0)
        href_value = match.group(1) or match.group(2)  # Handle both quote styles

        # Skip mailto:, tel:, and anchor links
        if href_value.startswith(('mailto:', 'tel:', '#', '{{')):
            return full_tag

        # Skip if already a tracking URL
        if '/track/click/' in href_value:
            return full_tag

        # Wrap with tracking URL
        tracking_url = get_click_tracking_url(tracking_token, href_value, base_url)

        # Replace the href value while preserving the rest of the tag
        if match.group(1):  # Double quotes
            return full_tag.replace(f'href="{href_value}"', f'href="{tracking_url}"')
        else:  # Single quotes
            return full_tag.replace(f"href='{href_value}'", f"href='{tracking_url}'")

    # Regex to match href attributes (both single and double quotes)
    pattern = r'<a[^>]*\shref=(?:"([^"]*)"|\'([^\']*)\')'
    html_body = re.sub(pattern, replace_href, html_body, flags=re.IGNORECASE)

    return html_body


def prepare_tracked_email(
    html_body: str,
    tracking_token: str,
    base_url: str,
    track_clicks: bool = True
) -> str:
    """
    Prepare an email for tracking by injecting pixel and wrapping links.

    Args:
        html_body: HTML content of the email
        tracking_token: Unique token for this email
        base_url: Base URL of the application
        track_clicks: Whether to wrap links with click tracking (default: True)

    Returns:
        Modified HTML with tracking pixel and wrapped links
    """
    if not html_body:
        return html_body

    # First wrap links (if enabled)
    if track_clicks:
        html_body = wrap_links_with_tracking(html_body, tracking_token, base_url)

    # Then inject tracking pixel
    html_body = inject_tracking_pixel(html_body, tracking_token, base_url)

    return html_body


def log_email_open(
    email_sent_id: int,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None
) -> bool:
    """
    Log an email open event.

    Args:
        email_sent_id: ID of the EmailSent record
        ip_address: IP address of the opener
        user_agent: User agent of the email client/browser

    Returns:
        True if logged successfully, False otherwise
    """
    try:
        from app.models import EmailOpen
        from app.extensions import db

        email_open = EmailOpen(
            email_sent_id=email_sent_id,
            opened_at=datetime.utcnow(),
            ip_address=ip_address[:45] if ip_address else None,  # Truncate to column size
            user_agent=user_agent[:512] if user_agent else None  # Truncate to column size
        )

        db.session.add(email_open)
        db.session.commit()

        logger.info(f"Logged email open: email_sent_id={email_sent_id}")
        return True

    except Exception as e:
        logger.error(f"Error logging email open: {e}")
        try:
            from app.extensions import db
            db.session.rollback()
        except:
            pass
        return False


def log_email_click(
    email_sent_id: int,
    url: str,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None
) -> bool:
    """
    Log an email click event.

    Args:
        email_sent_id: ID of the EmailSent record
        url: The destination URL that was clicked
        ip_address: IP address of the clicker
        user_agent: User agent of the browser

    Returns:
        True if logged successfully, False otherwise
    """
    try:
        from app.models import EmailClick
        from app.extensions import db

        email_click = EmailClick(
            email_sent_id=email_sent_id,
            clicked_at=datetime.utcnow(),
            url=url[:2048] if url else "",  # Truncate to column size
            ip_address=ip_address[:45] if ip_address else None,
            user_agent=user_agent[:512] if user_agent else None
        )

        db.session.add(email_click)
        db.session.commit()

        logger.info(f"Logged email click: email_sent_id={email_sent_id}, url={url[:50]}")
        return True

    except Exception as e:
        logger.error(f"Error logging email click: {e}")
        try:
            from app.extensions import db
            db.session.rollback()
        except:
            pass
        return False
