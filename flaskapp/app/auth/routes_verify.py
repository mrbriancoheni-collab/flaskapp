# app/auth/routes_verify.py
from __future__ import annotations
from flask import Blueprint, request, redirect, url_for, flash, current_app, render_template
from sqlalchemy import text
from app import db
from app.emailer import send_mail
from app.auth.utils import login_required, current_user_id, _session_email  # uses your existing helpers
from .verify import make_verify_token, read_verify_token, verify_link
from .forms import RegistrationForm, LoginForm


auth_bp = Blueprint("auth_bp", __name__)  # if you already have auth_bp, MERGE these routes into it.

def _load_user(uid: int):
    with db.engine.connect() as c:
        return c.execute(text("SELECT id, email, email_verified FROM users WHERE id=:i"), {"i": uid}).mappings().first()

def _set_email_verified(uid: int):
    with db.engine.begin() as c:
        c.execute(text("UPDATE users SET email_verified=1 WHERE id=:i"), {"i": uid})

@auth_bp.get("/verify/send")
@login_required
def send_verification():
    uid = current_user_id()
    if not uid:
        flash("Please log in.", "warning")
        return redirect(url_for("auth_bp.login"))

    u = _load_user(uid)
    if not u:
        flash("User not found.", "error")
        return redirect(url_for("main_bp.home"))

    email = u["email"]
    token = make_verify_token(uid, email)
    link = verify_link(token)

    subj = "Verify your email"
    txt = f"Please verify your email by clicking this link: {link}"
    html = f"""<p>Please verify your email by clicking this link:</p>
               <p><a href="{link}">{link}</a></p>"""
    try:
        send_mail(email, subj, txt, html)
        flash("Verification email sent.", "success")
    except Exception:
        current_app.logger.exception("Failed to send verification email")
        flash("Could not send verification email. Check SMTP settings.", "error")

    return redirect(url_for("main_bp.home"))

@auth_bp.get("/verify/<token>")
def verify_email(token: str):
    try:
        data = read_verify_token(token)
    except SignatureExpired:
        flash("Verification link expired. Please request a new one.", "warning")
        return redirect(url_for("auth_bp.login"))
    except Exception:
        flash("Invalid verification link.", "error")
        return redirect(url_for("auth_bp.login"))

    uid = int(data.get("uid", 0)) or None
    if not uid:
        flash("Invalid verification link.", "error")
        return redirect(url_for("auth_bp.login"))

    u = _load_user(uid)
    if not u:
        flash("User not found.", "error")
        return redirect(url_for("auth_bp.login"))

    _set_email_verified(uid)
    flash("Email verified. Thank you!", "success")
    return redirect(url_for("main_bp.home"))
