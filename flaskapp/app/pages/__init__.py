# app/pages/__init__.py
from flask import Blueprint, render_template, request, flash, redirect, url_for
from app.services.email_service import send_email
import logging

pages_bp = Blueprint("pages", __name__)

logger = logging.getLogger(__name__)

@pages_bp.route("/about")
def about():
    # TODO: Create about.html template
    return render_template("pages/about.html")

@pages_bp.route("/contact", methods=["GET", "POST"])
def contact():
    """Contact form page"""
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        message = request.form.get("message", "").strip()
        company_honeypot = request.form.get("company", "").strip()

        # Honeypot check (bots typically fill this hidden field)
        if company_honeypot:
            logger.warning(f"Contact form spam detected from {email}")
            flash("Message sent!", "success")  # Fake success for bot
            return redirect(url_for("pages.contact"))

        # Basic validation
        if not email or not message:
            flash("Please provide both email and message.", "danger")
            return render_template("contact.html")

        if len(message) > 4000 or len(email) > 254:
            flash("Message or email too long.", "danger")
            return render_template("contact.html")

        # Send notification email to admin
        try:
            send_email(
                to="support@fieldsprout.io",  # Update to your support email
                subject=f"Contact Form: {email}",
                html_content=f"""
                <p><strong>From:</strong> {email}</p>
                <p><strong>Message:</strong></p>
                <p>{message}</p>
                """,
                text_content=f"From: {email}\n\nMessage:\n{message}"
            )
            flash("Thanks! We'll get back to you soon.", "success")
            logger.info(f"Contact form submitted by {email}")
        except Exception as e:
            logger.exception(f"Failed to send contact email from {email}")
            flash("Sorry, there was an error. Please email support@fieldsprout.io directly.", "danger")

        return redirect(url_for("pages.contact"))

    return render_template("contact.html")

@pages_bp.route("/security")
def security():
    # TODO: Create security.html template
    return render_template("pages/security.html")