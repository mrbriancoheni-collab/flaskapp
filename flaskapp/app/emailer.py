# app/emailer.py
from __future__ import annotations
import os, smtplib
from email.message import EmailMessage
from typing import Optional
from flask import current_app

def _cfg(key: str, default: Optional[str] = None) -> Optional[str]:
    return (current_app.config.get(key) if current_app else None) or os.getenv(key) or default

def send_mail(to: str, subject: str, text: str, html: Optional[str] = None) -> None:
    host = _cfg("SMTP_HOST", "localhost")
    port = int(_cfg("SMTP_PORT", "587"))
    user = _cfg("SMTP_USER")
    pwd  = _cfg("SMTP_PASSWORD")
    use_tls = (_cfg("SMTP_USE_TLS", "1") == "1")
    from_addr = _cfg("MAIL_FROM", _cfg("MAIL_DEFAULT_SENDER", "no-reply@localhost"))

    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")

    with smtplib.SMTP(host, port, timeout=20) as s:
        if use_tls:
            s.starttls()
        if user and pwd:
            s.login(user, pwd)
        s.send_message(msg)
