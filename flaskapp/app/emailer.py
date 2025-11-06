# app/emailer.py
from __future__ import annotations
import os, smtplib
from email.message import EmailMessage
from typing import Optional
from flask import current_app

def _cfg(key: str, default: Optional[str] = None) -> Optional[str]:
    return (current_app.config.get(key) if current_app else None) or os.getenv(key) or default

def send_mail(to: str, subject: str, text: str, html: Optional[str] = None) -> None:
    # Support both SMTP_* and MAIL_* environment variables for compatibility
    host = _cfg("MAIL_SERVER") or _cfg("SMTP_HOST", "localhost")
    port = int(_cfg("MAIL_PORT") or _cfg("SMTP_PORT", "587"))

    # Try MAIL_USERNAME_DAVID first, then MAIL_USERNAME, then SMTP_USER
    user = (_cfg("MAIL_USERNAME_DAVID") or _cfg("MAIL_USERNAME") or _cfg("SMTP_USER"))
    pwd  = (_cfg("MAIL_PASSWORD_DAVID") or _cfg("MAIL_PASSWORD") or _cfg("SMTP_PASSWORD"))

    use_tls = str(_cfg("MAIL_USE_TLS") or _cfg("SMTP_USE_TLS", "1")).lower() in ("1", "true", "yes")
    use_ssl = str(_cfg("MAIL_USE_SSL") or "false").lower() in ("1", "true", "yes")
    from_addr = _cfg("MAIL_FROM") or _cfg("MAIL_DEFAULT_SENDER", "no-reply@localhost")

    # Auto-correct common misconfigurations based on port
    if port == 587 and use_ssl:
        if current_app:
            current_app.logger.warning("Auto-correcting: port 587 requires STARTTLS, not SSL")
        use_ssl = False
        use_tls = True
    elif port == 465 and not use_ssl:
        if current_app:
            current_app.logger.warning("Auto-correcting: port 465 requires SSL")
        use_ssl = True
        use_tls = False

    # Log configuration for debugging (without sensitive data)
    if current_app:
        current_app.logger.info(f"Sending email to {to} via {host}:{port} (SSL={use_ssl}, TLS={use_tls})")

    if not host or host == "localhost":
        raise RuntimeError("MAIL_SERVER not configured - set MAIL_SERVER environment variable")

    if not user or not pwd:
        raise RuntimeError("MAIL credentials not configured - set MAIL_USERNAME_DAVID and MAIL_PASSWORD_DAVID environment variables")

    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")

    try:
        if use_ssl:
            # Port 465: SSL/TLS from start
            with smtplib.SMTP_SSL(host, port, timeout=20) as s:
                if user and pwd:
                    s.login(user, pwd)
                s.send_message(msg)
        else:
            # Port 587: Plain connection, then STARTTLS
            with smtplib.SMTP(host, port, timeout=20) as s:
                if use_tls:
                    s.starttls()
                if user and pwd:
                    s.login(user, pwd)
                s.send_message(msg)

        if current_app:
            current_app.logger.info(f"Email sent successfully to {to}")
    except Exception as e:
        if current_app:
            current_app.logger.error(f"Failed to send email to {to}: {type(e).__name__}: {e}")
        raise
