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
    # Use David email as sender for bulk emails
    david_email = current_app.config.get("MAIL_USERNAME_DAVID") or os.getenv("MAIL_USERNAME_DAVID")
    if david_email:
        return david_email

    # Fallback to regular configured sender
    sender = current_app.config.get("MAIL_DEFAULT_SENDER") or os.getenv("MAIL_DEFAULT_SENDER")
    if sender:
        return sender

    # Last resort: no-reply@<server_name>
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
    # Use David credentials for bulk emails
    host = current_app.config.get("MAIL_SERVER") or os.getenv("MAIL_SERVER")
    port = int(current_app.config.get("MAIL_PORT") or os.getenv("MAIL_PORT") or 587)

    # Prefer David credentials, fallback to regular credentials
    user = (current_app.config.get("MAIL_USERNAME_DAVID") or os.getenv("MAIL_USERNAME_DAVID") or
            current_app.config.get("MAIL_USERNAME") or os.getenv("MAIL_USERNAME"))
    pwd  = (current_app.config.get("MAIL_PASSWORD_DAVID") or os.getenv("MAIL_PASSWORD_DAVID") or
            current_app.config.get("MAIL_PASSWORD") or os.getenv("MAIL_PASSWORD"))

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
{% extends "base_admin.html" %}
{% block title %}Send Test Email – {{ super() }}{% endblock %}
{% block content %}
<div class="max-w-2xl mx-auto">
  <div class="mb-6">
    <h1 class="text-2xl font-bold">Send Test Email</h1>
    <p class="text-gray-600 text-sm mt-2">
      Test email functionality using MAIL_USERNAME_DAVID credentials.
    </p>
  </div>

  <!-- Configuration Info -->
  <div class="bg-blue-50 border border-blue-200 rounded-lg p-4 mb-6">
    <h3 class="font-semibold text-blue-900 mb-2">
      <i class="fa-solid fa-info-circle mr-2"></i>Email Configuration
    </h3>
    <div class="text-sm text-blue-900 space-y-1">
      <div><strong>From:</strong> {{ default_sender }}</div>
      <div><strong>Server:</strong> {{ mail_server or 'Not configured' }}</div>
      <div><strong>Port:</strong> {{ mail_port or 'Not configured' }}</div>
      <div><strong>Auth:</strong> {{ 'Yes' if mail_username else 'No' }}</div>
    </div>
  </div>

  <div class="bg-white border rounded-lg p-6">
    <form method="post" class="space-y-4">
      <input type="hidden" name="csrf_token" value="{{ csrf_token() if csrf_token else '' }}">

      <div>
        <label class="block text-sm font-medium text-gray-700 mb-1">To</label>
        <input name="to" type="email" required
               class="w-full rounded border border-gray-300 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-indigo-500"
               placeholder="recipient@example.com"
               value="{{ request.args.get('to','') }}">
      </div>

      <div>
        <label class="block text-sm font-medium text-gray-700 mb-1">Subject</label>
        <input name="subject"
               class="w-full rounded border border-gray-300 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-indigo-500"
               value="FieldSprout Test Email">
      </div>

      <div>
        <label class="block text-sm font-medium text-gray-700 mb-1">Body</label>
        <textarea name="body" rows="6"
                  class="w-full rounded border border-gray-300 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-indigo-500">Hello from FieldSprout!

This is a test email sent from the admin panel.

If you received this email, the email system is working correctly.</textarea>
      </div>

      <div class="flex items-center justify-between pt-4">
        <a href="{{ url_for('admin_bp.dashboard') }}" class="text-gray-600 hover:text-gray-900">
          <i class="fa-solid fa-arrow-left mr-2"></i>Back to Admin
        </a>
        <button type="submit" class="px-6 py-2 bg-indigo-600 text-white rounded hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-indigo-500">
          <i class="fa-solid fa-paper-plane mr-2"></i>Send Test Email
        </button>
      </div>
    </form>
  </div>

  <!-- Recent Test Results -->
  {% if last_test_result %}
  <div class="mt-6 bg-white border rounded-lg p-4">
    <h3 class="font-semibold mb-2">Last Test Result</h3>
    <div class="text-sm">
      {% if last_test_result.success %}
        <div class="text-green-600">
          <i class="fa-solid fa-check-circle mr-2"></i>
          Email sent successfully to {{ last_test_result.to }}
        </div>
      {% else %}
        <div class="text-red-600">
          <i class="fa-solid fa-exclamation-circle mr-2"></i>
          Failed to send: {{ last_test_result.error }}
        </div>
      {% endif %}
    </div>
  </div>
  {% endif %}
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

        current_app.logger.info(f"Attempting to send test email to {to_addr}")

        try:
            # Get mail config for debugging
            mail_server = current_app.config.get("MAIL_SERVER") or os.getenv("MAIL_SERVER")
            mail_user = (current_app.config.get("MAIL_USERNAME_DAVID") or os.getenv("MAIL_USERNAME_DAVID") or
                        current_app.config.get("MAIL_USERNAME") or os.getenv("MAIL_USERNAME"))

            current_app.logger.info(f"Mail server: {mail_server}, user: {mail_user}")

            if not mail_server:
                flash("MAIL_SERVER not configured. Please set environment variables.", "error")
                return redirect(url_for("test_mail_bp.test_email", to=to_addr))

            if not mail_user:
                flash("MAIL_USERNAME_DAVID or MAIL_USERNAME not configured. Please set environment variables.", "error")
                return redirect(url_for("test_mail_bp.test_email", to=to_addr))

            send_test_email(to_addr, subject, body)

            current_app.logger.info(f"Test email sent successfully to {to_addr}")
            flash(f"✓ Test email sent successfully to {to_addr}! Check your inbox.", "success")

        except Exception as e:
            current_app.logger.exception("Test email failed")
            error_msg = str(e)
            flash(f"✗ Failed to send test email: {error_msg}", "error")

        return redirect(url_for("test_mail_bp.test_email", to=to_addr))

    # GET request - show form
    mail_server = current_app.config.get("MAIL_SERVER") or os.getenv("MAIL_SERVER")
    mail_port = current_app.config.get("MAIL_PORT") or os.getenv("MAIL_PORT") or 587
    mail_username = (current_app.config.get("MAIL_USERNAME_DAVID") or os.getenv("MAIL_USERNAME_DAVID") or
                    current_app.config.get("MAIL_USERNAME") or os.getenv("MAIL_USERNAME"))

    return render_template_string(
        _FORM_HTML,
        default_sender=_default_sender(),
        mail_server=mail_server,
        mail_port=mail_port,
        mail_username=mail_username
    )
