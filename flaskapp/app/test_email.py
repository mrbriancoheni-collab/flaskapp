# app/test_email.py
from __future__ import annotations

import os
import smtplib
from email.mime.text import MIMEText
from typing import Iterable, Optional

from flask import Blueprint, current_app, request, render_template_string, flash, redirect, url_for
from flask_login import current_user  # <-- use flask_login, not app.auth.utils
from app.auth.utils import login_required  # keep your decorator

test_mail_bp = Blueprint("test_mail_bp", __name__, url_prefix="/admin")

def _default_sender() -> str:
    # Prefer configured default sender
    sender = current_app.config.get("MAIL_DEFAULT_SENDER") or os.getenv("MAIL_DEFAULT_SENDER")
    if sender:
        return sender
    # Fallback: no-reply@<server_name>
    server_name = current_app.config.get("SERVER_NAME") or os.getenv("SERVER_NAME") or "localhost"
    return f"no-reply@{server_name.split(':', 1)[0]}"

def _send_with_flask_mail(subject: str, recipients: Iterable[str], body: str, html: Optional[str] = None) -> bool:
    mail_ext = current_app.extensions.get("mail")  # present when Flask-Mail initialized
    if not mail_ext:
        return False
    try:
        from flask_mail import Message  # type: ignore
        sender = _default_sender()
        msg = Message(subject=subject, recipients=list(recipients), sender=sender, body=body, html=html)
        mail_ext.send(msg)
        return True
    except Exception:
        current_app.logger.exception("Flask-Mail send failed")
        return False

def _send_with_smtp(subject: str, recipients: Iterable[str], body: str, html: Optional[str] = None) -> None:
    host = current_app.config.get("MAIL_SERVER") or os.getenv("MAIL_SERVER")
    port = int(current_app.config.get("MAIL_PORT") or os.getenv("MAIL_PORT") or 587)
    user = current_app.config.get("MAIL_USERNAME") or os.getenv("MAIL_USERNAME")
    pwd  = current_app.config.get("MAIL_PASSWORD") or os.getenv("MAIL_PASSWORD")
    use_tls = str(current_app.config.get("MAIL_USE_TLS") or os.getenv("MAIL_USE_TLS") or "true").lower() in ("1","true","yes")
    use_ssl = str(current_app.config.get("MAIL_USE_SSL") or os.getenv("MAIL_USE_SSL") or "false").lower() in ("1","true","yes")

    if not host:
        raise RuntimeError("MAIL_SERVER not configured")

    sender = _default_sender()
    to_list = list(recipients)
    # very simple text vs html: prefer html if provided
    if html:
        msg = MIMEText(html, "html", "utf-8")
    else:
        msg = MIMEText(body or "", "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = ", ".join(to_list)

    if use_ssl:
        smtp = smtplib.SMTP_SSL(host, port, timeout=20)
    else:
        smtp = smtplib.SMTP(host, port, timeout=20)

    try:
        smtp.ehlo()
        if use_tls and not use_ssl:
            smtp.starttls()
            smtp.ehlo()
        if user and pwd:
            smtp.login(user, pwd)
        smtp.sendmail(sender, to_list, msg.as_string())
    finally:
        try:
            smtp.quit()
        except Exception:
            pass

def send_test_email(to_addr: str, subject: str, body: str, html: Optional[str] = None) -> None:
    # Try Flask-Mail first; fallback to SMTP with env vars
    if not _send_with_flask_mail(subject, [to_addr], body, html=html):
        _send_with_smtp(subject, [to_addr], body, html=html)

_FORM_HTML = """
{% extends "base_public.html" %}
{% block title %}Send Test Email{% endblock %}
{% block content %}
<div class="max-w-xl mx-auto my-10 space-y-6">
  <h1 class="text-2xl font-semibold">Send Test Email</h1>
  <p class="text-gray-600 text-sm">
    Uses Flask-Mail if configured, otherwise raw SMTP from MAIL_* env/config.
  </p>
  <form method="post" class="space-y-4">
    <div>
      <label class="block text-sm text-gray-700 mb-1">To</label>
      <input name="to" type="email" required class="w-full rounded border px-3 py-2" placeholder="you@example.com"
             value="{{ request.args.get('to','') }}">
    </div>
    <div>
      <label class="block text-sm text-gray-700 mb-1">Subject</label>
      <input name="subject" class="w-full rounded border px-3 py-2" value="FieldSprout test email">
    </div>
    <div>
      <label class="block text-sm text-gray-700 mb-1">Body</label>
      <textarea name="body" rows="5" class="w-full rounded border px-3 py-2">Hello from FieldSprout! This is a test.</textarea>
    </div>
    <div class="flex items-center justify-between">
      <div class="text-sm text-gray-500">
        From: {{ default_sender }}
      </div>
      <button class="rounded bg-indigo-600 text-white px-4 py-2">Send</button>
    </div>
  </form>
</div>
{% endblock %}
"""

@test_mail_bp.route("/test-email", methods=["GET", "POST"], endpoint="test_email")
@login_required
def test_email():
    """
    UI to send a test email.
    GET /admin/test-email?to=you@domain.com
    POST form submits and sends.
    """
    if request.method == "POST":
        to_addr = (request.form.get("to") or "").strip()
        subject = (request.form.get("subject") or "FieldSprout test email").strip()
        body = (request.form.get("body") or "Hello from FieldSprout!").strip()
        if not to_addr:
            flash("Please enter a recipient email.", "error")
            return redirect(url_for("test_mail_bp.test_email"))
        try:
            send_test_email(to_addr, subject, body)
            flash(f"Sent test email to {to_addr}.", "success")
        except Exception as e:
            current_app.logger.exception("Test email failed")
            flash(f"Failed to send test email: {e}", "error")
        return redirect(url_for("test_mail_bp.test_email", to=to_addr))

    return render_template_string(_FORM_HTML, default_sender=_default_sender())
