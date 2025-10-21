# app/auth/forms.py
from __future__ import annotations

import re
from flask import current_app
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField, BooleanField
from wtforms.validators import DataRequired, Length, Email, EqualTo, ValidationError
from app.models import User

# -------------------------
# Helpers / Validators
# -------------------------

_SYMBOLS_RE = re.compile(r"[^\w]")  # any non-alphanumeric/underscore
_UPPER_RE = re.compile(r"[A-Z]")
_LOWER_RE = re.compile(r"[a-z]")
_DIGIT_RE = re.compile(r"\d")

# very small starter list; extend in config with DISPOSABLE_EMAIL_DOMAINS
_DEFAULT_DISPOSABLES = {
    "mailinator.com", "10minutemail.com", "guerrillamail.com",
    "getnada.com", "yopmail.com",
}

def _password_policy():
    """Read policy from config with safe defaults."""
    cfg = current_app.config if current_app else {}
    return {
        "min_length": int(cfg.get("PASSWORD_MIN_LENGTH", 12)),
        "require_upper": bool(cfg.get("PASSWORD_REQUIRE_UPPER", True)),
        "require_lower": bool(cfg.get("PASSWORD_REQUIRE_LOWER", True)),
        "require_digit": bool(cfg.get("PASSWORD_REQUIRE_DIGIT", True)),
        "require_symbol": bool(cfg.get("PASSWORD_REQUIRE_SYMBOL", True)),
    }

def validate_password_strength(pw: str) -> str | None:
    """Return error message if weak, else None."""
    policy = _password_policy()
    if len(pw or "") < policy["min_length"]:
        return f"Password must be at least {policy['min_length']} characters long."
    if policy["require_upper"] and not _UPPER_RE.search(pw):
        return "Password must include at least one uppercase letter."
    if policy["require_lower"] and not _LOWER_RE.search(pw):
        return "Password must include at least one lowercase letter."
    if policy["require_digit"] and not _DIGIT_RE.search(pw):
        return "Password must include at least one number."
    if policy["require_symbol"] and not _SYMBOLS_RE.search(pw):
        return "Password must include at least one symbol (e.g., !@#$%)."
    return None

def _disposable_domains() -> set[str]:
    cfg = current_app.config if current_app else {}
    extra = set(d.strip().lower() for d in cfg.get("DISPOSABLE_EMAIL_DOMAINS", []))
    return _DEFAULT_DISPOSABLES | extra

def _ensure_not_disposable(email: str) -> None:
    try:
        domain = (email or "").rsplit("@", 1)[1].lower()
    except Exception:
        return
    if domain in _disposable_domains():
        raise ValidationError("Please use a real email address (disposable domains are not allowed).")

# -------------------------
# Forms
# -------------------------

class RegistrationForm(FlaskForm):
    username = StringField("Username", validators=[DataRequired(), Length(2, 20)])
    email = StringField("Email", validators=[DataRequired(), Email(message="Enter a valid email address.")])
    password = PasswordField(
        "Password",
        validators=[DataRequired(), Length(6, 128)],  # base guard; we enforce stronger via custom check below
    )
    confirm_password = PasswordField(
        "Confirm Password",
        validators=[DataRequired(), EqualTo("password", message="Passwords must match.")],
    )
    submit = SubmitField("Sign Up")

    def validate_username(self, username):
        if User.query.filter_by(username=username.data.strip()).first():
            raise ValidationError("Username already taken.")

    def validate_email(self, email):
        val = email.data.strip().lower()
        _ensure_not_disposable(val)
        if User.query.filter_by(email=val).first():
            raise ValidationError("Email already in use.")

    def validate_password(self, password):
        msg = validate_password_strength(password.data or "")
        if msg:
            raise ValidationError(msg)

class LoginForm(FlaskForm):
    # Keep field name 'username' to avoid breaking existing templates/routes, but validate as an email.
    username = StringField("Email", validators=[DataRequired(), Email(message="Enter a valid email address.")])
    password = PasswordField("Password", validators=[DataRequired()])
    remember = BooleanField("Remember Me")
    submit = SubmitField("Login")

    def validate_username(self, username):
        # Optional: block disposables at login too (helps reduce spam sign-ins)
        _ensure_not_disposable(username.data.strip().lower())
