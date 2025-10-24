# app/auth/__init__.py
from __future__ import annotations

import re
from urllib.parse import urlparse

from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from werkzeug.security import generate_password_hash, check_password_hash
from markupsafe import Markup, escape
from sqlalchemy import text
from flask import (
    Blueprint, render_template, request, redirect, url_for,
    flash, session, current_app
)

from app import db

# Optional rate limiter (harmless if not installed)
try:
    from app import limiter  # initialized in app.__init__ when flask-limiter is present
except Exception:  # pragma: no cover
    limiter = None

# Preferred import name; fall back to older function name if needed
try:
    from app.auth.passwords import validate_strength  # expected signature: (pw, email) -> (ok: bool, msg: str)
except ImportError:  # fallback to legacy name with same return shape
    from app.auth.passwords import validate_password_strength as validate_strength

# Your email sender helper (must be implemented)
from app.auth.email_utils import send_email  # def send_email(to, subject, html) -> bool


auth_bp = Blueprint("auth_bp", __name__, url_prefix="")

# ---------------------------------------------------------------------
# Tiny form shim (keeps existing templates working without WTForms)
# ---------------------------------------------------------------------
class _Field:
    def __init__(self, name: str, type_: str, value: str = ""):
        self.name = name
        self.type = type_
        self.data = value
        self.errors = []

    def __call__(self, **attrs):
        attr_str = " ".join(
            f'{escape(k).replace("_","-")}="{escape(v)}"' for k, v in attrs.items()
        )
        return Markup(
            f'<input name="{escape(self.name)}" type="{escape(self.type)}" '
            f'value="{escape(self.data)}" {attr_str}>'
        )

class LoginForm:
    def __init__(self, email: str = "", password: str = ""):
        self.email = _Field("email", "email", email)
        self.password = _Field("password", "password", password)

    def hidden_tag(self):  # for template compatibility
        return Markup("")


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------
def _limit(spec: str):
    """Decorator shim so routes work even if limiter is None."""
    def _wrap(fn):
        if limiter:
            return limiter.limit(spec)(fn)
        return fn
    return _wrap


# Simple and strict-ish email check (server-side)
_email_rx = re.compile(
    r"^[A-Z0-9._%+\-']+@[A-Z0-9.\-]+\.[A-Z]{2,}$",
    re.IGNORECASE
)

def _is_valid_email(email: str) -> bool:
    e = (email or "").strip().lower()
    if not e or len(e) > 254:
        return False
    if not _email_rx.match(e):
        return False
    # Optional: block disposable domains if configured
    deny = current_app.config.get("DISPOSABLE_EMAIL_DOMAINS", ())
    if deny:
        try:
            domain = e.split("@", 1)[1]
            if domain.lower() in {d.lower() for d in deny}:
                return False
        except Exception:
            return False
    return True


def _normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def _is_safe_next(next_url: str) -> bool:
    """
    Allow only relative, same-site redirects for ?next=...
    """
    if not next_url:
        return False
    p = urlparse(next_url)
    return not p.scheme and not p.netloc and next_url.startswith("/")


def _post_auth_target(default_endpoint: str = "account_bp.dashboard") -> str:
    """
    Decide where to send the user after login/register.
    Use ?next= when it's a safe, same-site path and not a login/register/logout loop.
    Otherwise go to the account dashboard.
    """
    next_url = request.values.get("next", "")
    if _is_safe_next(next_url):
        bad_starts = ("/login", "/register", "/logout", "/signup")
        if not next_url.startswith(bad_starts):
            return next_url
    return url_for(default_endpoint)


def _set_login_session(user_id, email):
    """
    Store a few keys that your app treats as 'logged in'.
    (Matches AUTH_SESSION_KEYS defaults in app/__init__.py)
    """
    session["user_id"] = str(user_id)
    session["uid"] = str(user_id)
    session["email"] = email
    session.permanent = True


def _find_user_by_email(email: str):
    """
    Returns mapping row with keys:
      id, account_id, email, password_hash, email_verified
    """
    with db.engine.connect() as conn:
        return (
            conn.execute(
                text(
                    "SELECT id, account_id, email, password_hash, email_verified "
                    "FROM users WHERE email=:e LIMIT 1"
                ),
                {"e": _normalize_email(email)},
            )
            .mappings()
            .first()
        )


def _create_account_and_user(name: str, email: str, password: str):
    """
    Creates an account + owner user. Returns new user_id or None if email exists.
    Assumes tables:
      accounts(id, name, created_at, ...)
      users(id, account_id, name, email, password_hash, role, email_verified, created_at, ...)
    """
    email_n = _normalize_email(email)
    pwd_hash = generate_password_hash(password)
    with db.engine.begin() as conn:
        exist = conn.execute(
            text("SELECT id FROM users WHERE email=:e LIMIT 1"),
            {"e": email_n},
        ).fetchone()
        if exist:
            return None

        acc_res = conn.execute(
            text("INSERT INTO accounts (name, created_at) VALUES (:n, NOW())"),
            {"n": name or email_n},
        )
        account_id = acc_res.lastrowid

        user_res = conn.execute(
            text(
                """
                INSERT INTO users
                  (account_id, name, email, password_hash, role, email_verified, created_at)
                VALUES
                  (:aid, :n, :e, :ph, 'owner', 0, NOW())
                """
            ),
            {"aid": account_id, "n": name or email_n, "e": email_n, "ph": pwd_hash},
        )
        return user_res.lastrowid


def _create_user_from_invite(name: str, email: str, password: str, invite):
    """
    Create a user and join existing account via team invite.
    Returns new user_id or None if email already exists.

    Args:
        name: User's full name
        email: User's email
        password: User's password
        invite: TeamInvite model instance

    Returns:
        New user_id or None if email exists
    """
    email_n = _normalize_email(email)
    pwd_hash = generate_password_hash(password)

    with db.engine.begin() as conn:
        # Check if email already exists
        exist = conn.execute(
            text("SELECT id FROM users WHERE email=:e LIMIT 1"),
            {"e": email_n},
        ).fetchone()
        if exist:
            return None

        # Create user in invited account with specified role
        user_res = conn.execute(
            text(
                """
                INSERT INTO users
                  (account_id, name, email, password_hash, role, email_verified, created_at)
                VALUES
                  (:aid, :n, :e, :ph, :role, 0, NOW())
                """
            ),
            {
                "aid": invite.account_id,
                "n": name or email_n,
                "e": email_n,
                "ph": pwd_hash,
                "role": invite.role
            },
        )
        user_id = user_res.lastrowid

        # Mark invite as accepted
        conn.execute(
            text(
                """
                UPDATE team_invites
                SET status = 'accepted', accepted_at = NOW()
                WHERE id = :invite_id
                """
            ),
            {"invite_id": invite.id}
        )

        return user_id


# ---- itsdangerous (email verification & password reset tokens) -------------
def _s():
    secret = current_app.config.get("SECRET_KEY")
    salt = current_app.config.get("SECURITY_PASSWORD_SALT", "change-me")
    return URLSafeTimedSerializer(secret_key=secret, salt=salt)


def _verification_token(user_id: int, email: str) -> str:
    return _s().dumps({"kind": "verify", "uid": str(user_id), "email": _normalize_email(email)})


def _reset_token(user_id: int, email: str) -> str:
    return _s().dumps({"kind": "reset", "uid": str(user_id), "email": _normalize_email(email)})


def _loads_token(token: str, max_age: int):
    return _s().loads(token, max_age=max_age)


def _send_verification_email(email: str, token: str) -> bool:
    verify_url = url_for("auth_bp.verify_email", token=token, _external=True)
    html = f"""
    <p>Confirm your email for <b>{escape(current_app.config.get('APP_NAME','App'))}</b>.</p>
    <p><a href="{escape(verify_url)}">Verify my email</a></p>
    <p>If the button doesn’t work, copy this URL:<br>{escape(verify_url)}</p>
    """
    return send_email(email, "Verify your email", html)


def _send_reset_email(email: str, token: str) -> bool:
    reset_url = url_for("auth_bp.reset_password", token=token, _external=True)
    html = f"""
    <p>You requested a password reset.</p>
    <p><a href="{escape(reset_url)}">Reset my password</a></p>
    <p>If you did not request this, you can ignore this email.</p>
    """
    return send_email(email, "Reset your password", html)


# ---------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------
@auth_bp.route("/login", methods=["GET", "POST"], endpoint="login")
@_limit("10/minute")
def login():
    next_url = request.values.get("next", "")
    # Allow prefill via querystring (?email=foo) on GET for convenience
    form = LoginForm(
        email=request.values.get("email", "") if request.method == "POST" else request.args.get("email", ""),
        password=""
    )

    if request.method == "POST":
        email = _normalize_email(request.form.get("email", ""))
        password = request.form.get("password", "")

        ok = True
        if not email:
            form.email.errors.append("Email is required")
            ok = False
        elif not _is_valid_email(email):  # <-- server-side email sanity check
            form.email.errors.append("Enter a valid email address")
            ok = False

        if not password:
            form.password.errors.append("Password is required")
            ok = False

        if ok:
            row = _find_user_by_email(email)
            if not row or not check_password_hash(row["password_hash"], password):
                form.password.errors.append("Invalid email or password")
            else:
                _set_login_session(row["id"], email)

                if not row["email_verified"]:
                    flash("Please verify your email. We can resend the link from the login page.", "warning")

                # Always prefer a safe ?next=, otherwise go to account dashboard
                return redirect(_post_auth_target())

    return render_template("login.html", form=form, next=next_url)


@auth_bp.route("/register", methods=["GET", "POST"], endpoint="register")
@_limit("5/minute")
def register():
    if request.method == "POST":
        next_url = request.form.get("next", "")
        name = (request.form.get("name") or "").strip()
        email = _normalize_email(request.form.get("email", ""))
        password = request.form.get("password", "")
        invite_token = request.form.get("invite_token", "").strip()

        errs = []
        if not name:
            errs.append("Name is required.")
        if not email:
            errs.append("Email is required.")
        elif not _is_valid_email(email):  # <-- server-side email sanity check
            errs.append("Enter a valid email address.")

        # Strong password validation (server-side)
        ok_pw, msg_pw = validate_strength(password, email)
        if not ok_pw and msg_pw:
            errs.append(msg_pw)

        # Check if invite exists and is valid
        invite = None
        if invite_token:
            from app.models_team import TeamInvite
            invite = TeamInvite.query.filter_by(token=invite_token).first()
            if invite and not invite.is_valid():
                errs.append("This invitation has expired or is no longer valid.")
                invite = None
            elif invite and invite.email.lower() != email.lower():
                errs.append("This invitation was sent to a different email address.")
                invite = None

        if errs:
            for e in errs:
                flash(e, "error")
            return render_template("register.html", next=next_url, invite_token=invite_token)

        # Create user (with or without invite)
        if invite:
            # Join existing account via invite
            user_id = _create_user_from_invite(name, email, password, invite)
            if not user_id:
                flash("An account with that email already exists. Please log in.", "error")
                return redirect(url_for("auth_bp.login", next=next_url))
            flash(f"Welcome! You've joined as {invite.role}.", "success")
        else:
            # Create new account + owner user
            user_id = _create_account_and_user(name, email, password)
            if not user_id:
                flash("An account with that email already exists. Please log in.", "error")
                return redirect(url_for("auth_bp.login", next=next_url))

        _set_login_session(user_id, email)

        # Best-effort: send verification email
        try:
            tok = _verification_token(user_id, email)
            if _send_verification_email(email, tok):
                flash("Verification email sent. Please check your inbox.", "success")
            else:
                flash("We could not send a verification email (mail not configured).", "warning")
        except Exception:
            current_app.logger.exception("Failed to send verification email")

        # After registration, land on dashboard (or safe ?next=)
        return redirect(_post_auth_target())

    # GET
    invite_token = request.args.get("invite_token", "")
    invite_email = None
    if invite_token:
        from app.models_team import TeamInvite
        invite = TeamInvite.query.filter_by(token=invite_token).first()
        if invite and invite.is_valid():
            invite_email = invite.email

    return render_template("register.html", next=request.args.get("next", ""), invite_token=invite_token, invite_email=invite_email)


# --- /signup alias -> same as /register ---
@auth_bp.route("/signup", methods=["GET", "POST"], endpoint="signup")
def signup_alias():
    # Call the same logic so templates/links using /signup keep working
    return register()


# --- Email verification ---
@auth_bp.route("/verify", methods=["GET"], endpoint="verify_email")
def verify_email():
    token = request.args.get("token", "")
    try:
        data = _loads_token(token, max_age=60 * 60 * 24 * 3)  # 3 days
        if data.get("kind") != "verify":
            flash("Invalid verification link.", "error")
            return render_template("auth/verify_result.html", ok=False)

        uid = data.get("uid")
        email = _normalize_email(data.get("email", ""))

        with db.engine.begin() as conn:
            row = (
                conn.execute(
                    text("SELECT id, email, email_verified FROM users WHERE id=:id LIMIT 1"),
                    {"id": uid},
                )
                .mappings()
                .first()
            )
            if not row or _normalize_email(row["email"]) != email:
                flash("Verification link does not match any account.", "error")
                return render_template("auth/verify_result.html", ok=False)

            if not row["email_verified"]:
                conn.execute(
                    text("UPDATE users SET email_verified=1, email_verified_at=NOW() WHERE id=:id"),
                    {"id": uid},
                )

        flash("Your email has been verified. Thank you!", "success")
        return render_template("auth/verify_result.html", ok=True)

    except SignatureExpired:
        flash("Verification link expired. Please request a new one.", "error")
    except BadSignature:
        flash("Invalid verification link.", "error")

    return render_template("auth/verify_result.html", ok=False)


@auth_bp.route("/resend-verification", methods=["POST"], endpoint="resend_verification")
@_limit("3/minute")
def resend_verification():
    email = _normalize_email(request.form.get("email", "") or session.get("email", ""))
    if not email or not _is_valid_email(email):  # <-- server-side email sanity check
        flash("Enter a valid email to resend verification.", "error")
        return redirect(url_for("auth_bp.login"))

    row = _find_user_by_email(email)
    if not row:
        # Do not reveal account existence
        flash("If an account exists, a new verification link will be sent.", "info")
        return redirect(url_for("auth_bp.login"))

    try:
        tok = _verification_token(row["id"], email)
        sent = _send_verification_email(email, tok)
        flash(
            "Verification email sent." if sent else "Could not send verification email.",
            "info" if sent else "warning",
        )
    except Exception:
        current_app.logger.exception("Resend verification failed")
    # Regardless, return to login with the email pre-filled
    return redirect(url_for("auth_bp.login", email=email))


# --- Password reset ---
@auth_bp.route("/forgot", methods=["GET", "POST"], endpoint="forgot_password")
@_limit("5/minute")
def forgot_password():
    if request.method == "POST":
        email = _normalize_email(request.form.get("email", ""))
        if email and _is_valid_email(email):  # server-side email check
            row = _find_user_by_email(email)
            if row:
                try:
                    tok = _reset_token(row["id"], email)
                    _send_reset_email(email, tok)
                except Exception:
                    current_app.logger.exception("Failed sending reset email")
        # Never reveal whether email exists
        return render_template("auth/forgot_sent.html")

    return render_template("auth/forgot_password.html")


@auth_bp.route("/reset/<token>", methods=["GET", "POST"], endpoint="reset_password")
def reset_password(token: str):
    # Validate token
    try:
        data = _loads_token(token, max_age=60 * 60 * 2)  # 2 hours
        if data.get("kind") != "reset":
            flash("Invalid reset link.", "error")
            return render_template("auth/reset_password.html", token=None)
    except SignatureExpired:
        flash("Reset link expired. Please request a new one.", "error")
        return redirect(url_for("auth_bp.forgot_password"))
    except BadSignature:
        flash("Invalid reset link.", "error")
        return redirect(url_for("auth_bp.forgot_password"))

    uid = data.get("uid")
    email = _normalize_email(data.get("email", ""))

    if request.method == "POST":
        pw1 = request.form.get("password", "")
        pw2 = request.form.get("password2", "")

        errs = []
        # Strong password validation on reset, too
        ok_pw, msg_pw = validate_strength(pw1, email)
        if not ok_pw and msg_pw:
            errs.append(msg_pw)
        if pw1 != pw2:
            errs.append("Passwords do not match.")
        if errs:
            for e in errs:
                flash(e, "error")
            return render_template("auth/reset_password.html", token=token)

        with db.engine.begin() as conn:
            row = (
                conn.execute(
                    text("SELECT id, email FROM users WHERE id=:id LIMIT 1"),
                    {"id": uid},
                )
                .mappings()
                .first()
            )
            if not row or _normalize_email(row["email"]) != email:
                flash("Reset link does not match any account.", "error")
                return render_template("auth/reset_password.html", token=None)

            conn.execute(
                text("UPDATE users SET password_hash=:ph, updated_at=NOW() WHERE id=:id"),
                {"ph": generate_password_hash(pw1), "id": uid},
            )

        flash("Your password has been updated. Please log in.", "success")
        return redirect(url_for("auth_bp.login", email=email))

    return render_template("auth/reset_password.html", token=token)


@auth_bp.route("/logout", methods=["POST", "GET"], endpoint="logout")
def logout():
    session.clear()
    return redirect(url_for("main_bp.home"))
