# app/auth/__init__.py
from __future__ import annotations

import re
from urllib.parse import urlparse, urljoin

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

# Email service (uses Mailgun API by default)
from app.services.email_service import send_email


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
    Otherwise go to the admin dashboard for admins, or account dashboard for regular users.
    """
    next_url = request.values.get("next", "")
    if _is_safe_next(next_url):
        bad_starts = ("/login", "/register", "/logout", "/signup")
        if not next_url.startswith(bad_starts):
            return next_url

    # Check if user is an admin and redirect to admin dashboard
    from flask import g
    if hasattr(g, 'user') and g.user and hasattr(g.user, 'is_admin') and g.user.is_admin:
        return url_for("admin_bp.dashboard")

    return url_for(default_endpoint)


def _set_login_session(user_id, email):
    """
    Store a few keys that your app treats as 'logged in'.
    (Matches AUTH_SESSION_KEYS defaults in app/__init__.py)
    Also integrates with Flask-Login for compatibility.
    """
    session["user_id"] = str(user_id)
    session["uid"] = str(user_id)
    session["email"] = email
    session.permanent = True

    # Also log in via Flask-Login for compatibility with current_user
    try:
        from flask_login import login_user
        from app.models import User
        user = User.query.get(int(user_id))
        if user:
            login_user(user, remember=True)
    except Exception as e:
        # Log but don't fail if Flask-Login integration has issues
        current_app.logger.warning(f"Flask-Login integration failed: {e}")


def _send_welcome_email(name: str, email: str) -> None:
    """Send a welcome email to a newly registered user. Failures are logged, not raised."""
    try:
        from flask import render_template as _rt
        base_url = current_app.config.get('BASE_URL', 'https://fieldsprout.io').rstrip('/')
        html = _rt(
            'emails/welcome.html',
            name=name.split()[0] if name else 'there',
            dashboard_url=f"{base_url}/account/dashboard",
            unsubscribe_url=f"{base_url}/account/unsubscribe",
        )
        send_email(
            to=email,
            subject="Welcome to FieldSprout — here's how to get started",
            html_body=html,
        )
    except Exception:
        current_app.logger.warning("Welcome email failed to send", exc_info=True)


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

    Note: Email verification is disabled - all accounts are created with email_verified=1
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

        # Insert account
        conn.execute(
            text("INSERT INTO accounts (name, created_at) VALUES (:n, NOW())"),
            {"n": name or email_n},
        )

        # Get the last inserted account ID using LAST_INSERT_ID()
        account_id_result = conn.execute(text("SELECT LAST_INSERT_ID()")).scalar()
        account_id = int(account_id_result) if account_id_result else None

        if not account_id:
            raise Exception("Failed to retrieve account ID after insert")

        # Insert user
        conn.execute(
            text(
                """
                INSERT INTO users
                  (account_id, name, email, password_hash, role, email_verified, email_verified_at, created_at)
                VALUES
                  (:aid, :n, :e, :ph, 'owner', 1, NOW(), NOW())
                """
            ),
            {"aid": account_id, "n": name or email_n, "e": email_n, "ph": pwd_hash},
        )

        # Get the last inserted user ID using LAST_INSERT_ID()
        user_id_result = conn.execute(text("SELECT LAST_INSERT_ID()")).scalar()
        user_id = int(user_id_result) if user_id_result else None

        if not user_id:
            raise Exception("Failed to retrieve user ID after insert")

        return user_id


def _create_user_and_account(name: str, email: str, password: Optional[str] = None, email_verified: bool = False):
    """
    Creates an account + owner user (supports OAuth users with no password).
    Returns (account_id, user_id) or (None, None) if email exists.
    """
    email_n = _normalize_email(email)

    # For OAuth users without password, generate a random secure password they'll never use
    if password:
        pwd_hash = generate_password_hash(password)
    else:
        import secrets
        pwd_hash = generate_password_hash(secrets.token_urlsafe(32))

    with db.engine.begin() as conn:
        exist = conn.execute(
            text("SELECT id FROM users WHERE email=:e LIMIT 1"),
            {"e": email_n},
        ).fetchone()
        if exist:
            return None, None

        # Insert account
        conn.execute(
            text("INSERT INTO accounts (name, created_at) VALUES (:n, NOW())"),
            {"n": name or email_n},
        )

        # Get the last inserted account ID using LAST_INSERT_ID()
        account_id_result = conn.execute(text("SELECT LAST_INSERT_ID()")).scalar()
        account_id = int(account_id_result) if account_id_result else None

        if not account_id:
            raise Exception("Failed to retrieve account ID after insert")

        # Set email_verified_at when email is verified (e.g., OAuth providers)
        if email_verified:
            conn.execute(
                text(
                    """
                    INSERT INTO users
                      (account_id, name, email, password_hash, role, email_verified, email_verified_at, created_at)
                    VALUES
                      (:aid, :n, :e, :ph, 'owner', 1, NOW(), NOW())
                    """
                ),
                {"aid": account_id, "n": name or email_n, "e": email_n, "ph": pwd_hash},
            )
        else:
            conn.execute(
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

        # Get the last inserted user ID using LAST_INSERT_ID()
        user_id_result = conn.execute(text("SELECT LAST_INSERT_ID()")).scalar()
        user_id = int(user_id_result) if user_id_result else None

        if not user_id:
            raise Exception("Failed to retrieve user ID after insert")

        return account_id, user_id


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
    <p>If the button doesn't work, copy this URL:<br>{escape(verify_url)}</p>
    """
    return send_email(email, "Verify your email", html_body=html)


def _send_reset_email(email: str, token: str) -> bool:
    reset_url = url_for("auth_bp.reset_password", token=token, _external=True)
    html = f"""
    <p>You requested a password reset.</p>
    <p><a href="{escape(reset_url)}">Reset my password</a></p>
    <p>If you did not request this, you can ignore this email.</p>
    """
    return send_email(email, "Reset your password", html_body=html)


# ---------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------
def _account_deactivated(user_id) -> bool:
    """
    True only if the user's account was soft-deleted by an admin (status='deleted').
    Fails OPEN (returns False on any error) so a DB hiccup can never lock out
    the whole user base. 'deleted' is set exclusively by the admin deactivate
    action, so this never affects active/trial/canceled accounts.
    """
    try:
        from app import db
        from sqlalchemy import text
        with db.engine.connect() as conn:
            r = conn.execute(
                text("SELECT a.status FROM accounts a "
                     "JOIN users u ON u.account_id = a.id WHERE u.id = :uid"),
                {"uid": user_id},
            ).first()
        return bool(r and str(r[0] or "").lower() == "deleted")
    except Exception:
        return False


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
            elif _account_deactivated(row["id"]):
                form.email.errors.append(
                    "This account has been deactivated. Please contact support if you believe this is an error."
                )
            else:
                _set_login_session(row["id"], email)

                # Email verification is disabled - all accounts have access
                # (Legacy code removed: no more email verification warnings)

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

        errs = []
        if not name:
            errs.append("Name is required.")
        if not email:
            errs.append("Email is required.")
        elif not _is_valid_email(email):  # <-- server-side email sanity check
            errs.append("Enter a valid email address.")

        ok_pw, msg_pw = validate_strength(password, email, min_length=8)
        if not ok_pw and msg_pw:
            errs.append(msg_pw)

        if errs:
            for e in errs:
                flash(e, "error")
            return render_template("register.html", next=next_url)

        user_id = _create_account_and_user(name, email, password)
        if not user_id:
            flash("An account with that email already exists. Please log in.", "error")
            return redirect(url_for("auth_bp.login", next=next_url))

        _set_login_session(user_id, email)
        _send_welcome_email(name, email)
        flash("Welcome to FieldSprout! Your account has been created.", "success")
        return redirect(_post_auth_target())

    # GET
    return render_template("register.html", next=request.args.get("next", ""))


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
        # Strong password validation on reset, too - minimum 8 characters
        ok_pw, msg_pw = validate_strength(pw1, email, min_length=8)
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
    # Clear session-based auth
    session.clear()

    # Also logout via Flask-Login
    try:
        from flask_login import logout_user
        logout_user()
    except Exception:
        pass  # Gracefully handle if Flask-Login not available

    flash("You have been logged out successfully.", "info")
    return redirect(url_for("main_bp.home"))


# ---------------------------------------------------------------------
# Google OAuth Routes (Sign in with Google)
# ---------------------------------------------------------------------
@auth_bp.route("/auth/google", methods=["GET"], endpoint="google_login")
def google_login():
    """
    Initiate Google OAuth flow for user authentication.
    """
    try:
        from app.auth.google_oauth import GoogleAuthHelper

        # Store next URL in session for post-login redirect
        next_url = request.args.get("next", "")
        if next_url:
            session['google_auth_next'] = next_url

        # Get authorization URL
        auth_url = GoogleAuthHelper.get_authorization_url()

        return redirect(auth_url)

    except Exception as e:
        current_app.logger.exception(f"Error initiating Google OAuth: {e}")
        flash("Unable to connect to Google. Please try again or use email/password login.", "error")
        return redirect(url_for("auth_bp.login"))


@auth_bp.route("/auth/google/callback", methods=["GET"], endpoint="google_callback")
def google_callback():
    """
    Handle Google OAuth callback and create/login user.
    """
    try:
        from app.auth.google_oauth import GoogleAuthHelper
        from app.models_oauth import UserOAuthProvider

        # Get authorization code and state
        code = request.args.get("code")
        state = request.args.get("state")
        error = request.args.get("error")

        if error:
            current_app.logger.warning(f"Google OAuth error: {error}")
            flash("Google sign-in was cancelled or failed.", "warning")
            return redirect(url_for("auth_bp.login"))

        if not code:
            flash("Invalid Google sign-in response.", "error")
            return redirect(url_for("auth_bp.login"))

        # Exchange code for user info
        userinfo = GoogleAuthHelper.handle_callback(code, state)

        if not userinfo or not userinfo.get('google_id') or not userinfo.get('email'):
            flash("Unable to verify Google account. Please try again.", "error")
            return redirect(url_for("auth_bp.login"))

        google_id = userinfo['google_id']
        email = _normalize_email(userinfo['email'])
        name = userinfo.get('name', 'User')
        picture = userinfo.get('picture')

        # Check if this Google account is already linked
        oauth_record = UserOAuthProvider.get_by_provider('google', google_id)

        if oauth_record:
            # Existing Google account - log them in
            user_row = _find_user_by_id(oauth_record.user_id)

            if user_row:
                _set_login_session(user_row["id"], user_row["email"])

                # Update OAuth record
                oauth_record.email = email
                oauth_record.name = name
                oauth_record.picture = picture
                oauth_record.last_login_at = datetime.utcnow()
                db.session.commit()

                flash(f"Welcome back, {user_row['name']}!", "success")

                # Redirect to next URL or dashboard
                next_url = session.pop('google_auth_next', '')
                if next_url and _is_safe_redirect(next_url):
                    return redirect(next_url)
                return redirect(_post_auth_target())
            else:
                # OAuth record exists but user doesn't - cleanup and treat as new
                db.session.delete(oauth_record)
                db.session.commit()

        # Check if email already exists (user might want to link accounts)
        existing_user = _find_user_by_email(email)

        if existing_user:
            # Email exists - link Google account to existing user
            user_id = existing_user["id"]

            # Create OAuth provider record
            oauth_provider = UserOAuthProvider(
                user_id=user_id,
                provider='google',
                provider_user_id=google_id,
                email=email,
                name=name,
                picture=picture,
                last_login_at=datetime.utcnow()
            )
            db.session.add(oauth_provider)
            db.session.commit()

            _set_login_session(user_id, email)

            flash(f"Your Google account has been linked! Welcome back, {existing_user['name']}!", "success")

            next_url = session.pop('google_auth_next', '')
            if next_url and _is_safe_redirect(next_url):
                return redirect(next_url)
            return redirect(_post_auth_target())

        # New user - create account
        # Note: Google-authenticated users have verified emails
        account_id, user_id = _create_user_and_account(
            name=name,
            email=email,
            password=None,  # No password for OAuth users
            email_verified=True  # Google verified the email
        )

        # Create OAuth provider record
        oauth_provider = UserOAuthProvider(
            user_id=user_id,
            provider='google',
            provider_user_id=google_id,
            email=email,
            name=name,
            picture=picture,
            last_login_at=datetime.utcnow()
        )
        db.session.add(oauth_provider)
        db.session.commit()

        _set_login_session(user_id, email)

        _send_welcome_email(name, email)
        flash(f"Welcome to FieldSprout, {name}! Your account has been created.", "success")

        next_url = session.pop('google_auth_next', '')
        if next_url and _is_safe_redirect(next_url):
            return redirect(next_url)
        return redirect(_post_auth_target())

    except Exception as e:
        current_app.logger.exception(f"Error in Google OAuth callback: {e}")
        flash("An error occurred during Google sign-in. Please try again.", "error")
        return redirect(url_for("auth_bp.login"))


# ---------------------------------------------------------------------
# Facebook OAuth Routes (Sign in with Facebook)
# DISABLED: Pending Facebook app approval for business_management permission
# ---------------------------------------------------------------------
# @auth_bp.route("/auth/facebook", methods=["GET"], endpoint="facebook_login")
# def facebook_login():
#     """
#     Initiate Facebook OAuth flow for user authentication.
#     """
#     try:
#         from app.auth.facebook_oauth import FacebookAuthHelper
#
#         # Check if Facebook OAuth is configured
#         if not FacebookAuthHelper.is_configured():
#             flash("Facebook sign-in is not currently available. Please use email/password login.", "warning")
#             return redirect(url_for("auth_bp.login"))
#
#         # Store next URL in session for post-login redirect
#         next_url = request.args.get("next", "")
#         if next_url:
#             session['facebook_auth_next'] = next_url
#
#         # Get authorization URL
#         auth_url = FacebookAuthHelper.get_authorization_url()
#
#         return redirect(auth_url)
#
#     except Exception as e:
#         current_app.logger.exception(f"Error initiating Facebook OAuth: {e}")
#         flash("Unable to connect to Facebook. Please try again or use email/password login.", "error")
#         return redirect(url_for("auth_bp.login"))
#
#
# @auth_bp.route("/auth/facebook/callback", methods=["GET"], endpoint="facebook_callback")
# def facebook_callback():
#     """
#     Handle Facebook OAuth callback and create/login user.
#     """
#     try:
#         from app.auth.facebook_oauth import FacebookAuthHelper
#         from app.models_oauth import UserOAuthProvider
#         from datetime import datetime
#
#         # Get authorization code and state
#         code = request.args.get("code")
#         state = request.args.get("state")
#         error = request.args.get("error")
#         error_reason = request.args.get("error_reason")
#
#         if error:
#             current_app.logger.warning(f"Facebook OAuth error: {error} ({error_reason})")
#             if error_reason == "user_denied":
#                 flash("Facebook sign-in was cancelled.", "info")
#             else:
#                 flash("Facebook sign-in failed. Please try again.", "warning")
#             return redirect(url_for("auth_bp.login"))
#
#         if not code:
#             flash("Invalid Facebook sign-in response.", "error")
#             return redirect(url_for("auth_bp.login"))
#
#         # Exchange code for user info
#         userinfo = FacebookAuthHelper.handle_callback(code, state)
#
#         if not userinfo or not userinfo.get('facebook_id'):
#             flash("Unable to verify Facebook account. Please try again.", "error")
#             return redirect(url_for("auth_bp.login"))
#
#         facebook_id = userinfo['facebook_id']
#         email = userinfo.get('email')  # May be None if user denied permission
#         name = userinfo.get('name', 'Facebook User')
#         picture = userinfo.get('picture')
#
#         # If no email, we cannot create an account
#         if not email:
#             flash("We need your email address to create an account. Please grant email permission or use email/password sign-up.", "warning")
#             return redirect(url_for("auth_bp.register"))
#
#         email = _normalize_email(email)
#
#         # Check if this Facebook account is already linked
#         oauth_record = UserOAuthProvider.get_by_provider('facebook', facebook_id)
#
#         if oauth_record:
#             # Existing Facebook account - log them in
#             user_row = _find_user_by_id(oauth_record.user_id)
#
#             if user_row:
#                 _set_login_session(user_row["id"], user_row["email"])
#
#                 # Update OAuth record
#                 oauth_record.email = email
#                 oauth_record.name = name
#                 oauth_record.picture = picture
#                 oauth_record.last_login_at = datetime.utcnow()
#                 db.session.commit()
#
#                 flash(f"Welcome back, {user_row['name']}!", "success")
#
#                 # Redirect to next URL or dashboard
#                 next_url = session.pop('facebook_auth_next', '')
#                 if next_url and _is_safe_redirect(next_url):
#                     return redirect(next_url)
#                 return redirect(_post_auth_target())
#             else:
#                 # OAuth record exists but user doesn't - cleanup and treat as new
#                 db.session.delete(oauth_record)
#                 db.session.commit()
#
#         # Check if email already exists (user might want to link accounts)
#         existing_user = _find_user_by_email(email)
#
#         if existing_user:
#             # Email exists - link Facebook account to existing user
#             user_id = existing_user["id"]
#
#             # Create OAuth provider record
#             oauth_provider = UserOAuthProvider(
#                 user_id=user_id,
#                 provider='facebook',
#                 provider_user_id=facebook_id,
#                 email=email,
#                 name=name,
#                 picture=picture,
#                 last_login_at=datetime.utcnow()
#             )
#             db.session.add(oauth_provider)
#             db.session.commit()
#
#             _set_login_session(user_id, email)
#
#             flash(f"Your Facebook account has been linked! Welcome back, {existing_user['name']}!", "success")
#
#             next_url = session.pop('facebook_auth_next', '')
#             if next_url and _is_safe_redirect(next_url):
#                 return redirect(next_url)
#             return redirect(_post_auth_target())
#
#         # New user - create account
#         # Note: Facebook-authenticated users have verified emails (Facebook verifies them)
#         account_id, user_id = _create_user_and_account(
#             name=name,
#             email=email,
#             password=None,  # No password for OAuth users
#             email_verified=True  # Facebook verified the email
#         )
#
#         # Create OAuth provider record
#         oauth_provider = UserOAuthProvider(
#             user_id=user_id,
#             provider='facebook',
#             provider_user_id=facebook_id,
#             email=email,
#             name=name,
#             picture=picture,
#             last_login_at=datetime.utcnow()
#         )
#         db.session.add(oauth_provider)
#         db.session.commit()
#
#         _set_login_session(user_id, email)
#
#         flash(f"Welcome to {current_app.config.get('APP_NAME', 'FieldSprout')}, {name}! Your account has been created.", "success")
#
#         next_url = session.pop('facebook_auth_next', '')
#         if next_url and _is_safe_redirect(next_url):
#             return redirect(next_url)
#         return redirect(_post_auth_target())
#
#     except Exception as e:
#         current_app.logger.exception(f"Error in Facebook OAuth callback: {e}")
#         flash("An error occurred during Facebook sign-in. Please try again.", "error")
#         return redirect(url_for("auth_bp.login"))


# Helper function to find user by ID
def _find_user_by_id(user_id: int):
    """Find user by ID."""
    with db.engine.begin() as conn:
        return (
            conn.execute(
                text("SELECT id, name, email, email_verified FROM users WHERE id=:id LIMIT 1"),
                {"id": user_id},
            )
            .mappings()
            .first()
        )


def _is_safe_redirect(target: str) -> bool:
    """Check if redirect target is safe (same domain)."""
    try:
        ref_url = urlparse(request.host_url)
        test_url = urlparse(urljoin(request.host_url, target))
        return test_url.scheme in ("http", "https") and ref_url.netloc == test_url.netloc
    except Exception:
        return False
