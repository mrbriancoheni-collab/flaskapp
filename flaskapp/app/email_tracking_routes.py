"""
Email Tracking Routes

Handles tracking pixel (opens) and click tracking endpoints.
These endpoints are publicly accessible (no login required) for email tracking.
"""
import logging
from io import BytesIO

from flask import Blueprint, request, redirect, send_file, abort
from urllib.parse import unquote

from app.models import EmailSent
from app.services.email_tracking import log_email_open, log_email_click

logger = logging.getLogger(__name__)

email_tracking_bp = Blueprint(
    "email_tracking_bp",
    __name__,
    url_prefix="/track"
)


# 1x1 transparent GIF image (43 bytes)
TRACKING_PIXEL = (
    b'\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00'
    b'\xff\xff\xff\x00\x00\x00\x21\xf9\x04\x01\x00\x00\x00'
    b'\x00\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02'
    b'\x44\x01\x00\x3b'
)


@email_tracking_bp.route("/pixel/<token>.gif")
def tracking_pixel(token: str):
    """
    Tracking pixel endpoint for email opens.

    When an email is opened, the email client loads this image,
    which logs the open event.

    Args:
        token: Tracking token from the email

    Returns:
        1x1 transparent GIF image
    """
    try:
        # Find the email by tracking token
        email = EmailSent.query.filter_by(tracking_token=token).first()

        if email:
            # Get client info
            ip_address = request.headers.get('X-Forwarded-For', request.remote_addr)
            user_agent = request.headers.get('User-Agent', '')

            # Log the open
            log_email_open(
                email_sent_id=email.id,
                ip_address=ip_address,
                user_agent=user_agent
            )

            logger.debug(f"Email open tracked: token={token}, email_id={email.id}")
        else:
            logger.warning(f"Tracking pixel requested for unknown token: {token}")

    except Exception as e:
        logger.error(f"Error in tracking pixel endpoint: {e}")

    # Always return the pixel, even if tracking fails
    # This prevents broken images in emails
    return send_file(
        BytesIO(TRACKING_PIXEL),
        mimetype='image/gif',
        as_attachment=False,
        download_name='pixel.gif'
    )


@email_tracking_bp.route("/click/<token>")
def click_tracking(token: str):
    """
    Click tracking endpoint for email links.

    When a link in an email is clicked, it goes through this endpoint first
    to log the click, then redirects to the actual destination.

    Args:
        token: Tracking token from the email

    Query Parameters:
        url: The destination URL (URL-encoded)

    Returns:
        Redirect to the destination URL
    """
    destination_url = request.args.get('url', '')

    if not destination_url:
        logger.warning(f"Click tracking called without destination URL: token={token}")
        abort(400, "Missing destination URL")

    # Decode the URL
    try:
        destination_url = unquote(destination_url)
    except Exception as e:
        logger.error(f"Error decoding destination URL: {e}")
        abort(400, "Invalid destination URL")

    try:
        # Find the email by tracking token
        email = EmailSent.query.filter_by(tracking_token=token).first()

        if email:
            # Get client info
            ip_address = request.headers.get('X-Forwarded-For', request.remote_addr)
            user_agent = request.headers.get('User-Agent', '')

            # Log the click
            log_email_click(
                email_sent_id=email.id,
                url=destination_url,
                ip_address=ip_address,
                user_agent=user_agent
            )

            logger.debug(f"Email click tracked: token={token}, email_id={email.id}, url={destination_url[:50]}")
        else:
            logger.warning(f"Click tracking requested for unknown token: {token}")

    except Exception as e:
        logger.error(f"Error in click tracking endpoint: {e}")

    # Always redirect to destination, even if tracking fails
    # This ensures links still work even if there's a tracking error
    return redirect(destination_url, code=302)
