from __future__ import annotations
import smtplib
from email.message import EmailMessage
from flask import current_app

def _mail_cfg():
    c = current_app.config
    return dict(
        server=c.get("MAIL_SERVER"),
        port=int(c.get("MAIL_PORT", 587)),
        username=c.get("MAIL_USERNAME"),
        password=c.get("MAIL_PASSWORD"),
        use_tls=str(c.get("MAIL_USE_TLS", "1")).lower() in ("1", "true", "yes", "on"),
        use_ssl=str(c.get("MAIL_USE_SSL", "0")).lower() in ("1", "true", "yes", "on"),
        default_sender=c.get("MAIL_DEFAULT_SENDER") or c.get("MAIL_USERNAME"),
        default_sender_name=c.get("MAIL_DEFAULT_SENDER_NAME", c.get("APP_NAME", "App")),
    )

def send_email(to: str, subject: str, html_body: str, text_body: str | None = None) -> bool:
    cfg = _mail_cfg()
    if not (cfg["server"] and cfg["default_sender"]):
        current_app.logger.warning("Email not sent: MAIL_SERVER/MAIL_DEFAULT_SENDER not configured")
        return False

    msg = EmailMessage()
    sender = cfg["default_sender"]
    sender_name = cfg["default_sender_name"]
    msg["From"] = f"{sender_name} <{sender}>"
    msg["To"] = to
    msg["Subject"] = subject

    text_body = text_body or "Please view this message in an HTML-capable mail client."
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")

    try:
        # Prefer SSL if explicitly enabled (e.g., port 465)
        if cfg["use_ssl"]:
            with smtplib.SMTP_SSL(cfg["server"], cfg["port"]) as s:
                if cfg["username"] and cfg["password"]:
                    s.login(cfg["username"], cfg["password"])
                s.send_message(msg)
        else:
            with smtplib.SMTP(cfg["server"], cfg["port"]) as s:
                if cfg["use_tls"]:
                    s.starttls()
                if cfg["username"] and cfg["password"]:
                    s.login(cfg["username"], cfg["password"])
                s.send_message(msg)
        return True
    except Exception:
        current_app.logger.exception("Failed to send email via SMTP")
        return False
