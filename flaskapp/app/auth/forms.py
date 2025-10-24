# app/auth/forms.py
from __future__ import annotations

from flask_wtf import FlaskForm
from flask import current_app
from wtforms import StringField, PasswordField, SubmitField, BooleanField
from wtforms.validators import DataRequired, Length, EqualTo, ValidationError
from sqlalchemy import func

from app.models import User
from app.auth.passwords import validate_strength, is_valid_email


class RegistrationForm(FlaskForm):
    username = StringField(
        "Username",
        validators=[DataRequired(), Length(min=2, max=20)],
    )
    email = StringField(
        "Email",
        validators=[DataRequired()],  # we use is_valid_email() for better errors/disposable checks
    )
    password = PasswordField(
        "Password",
        validators=[DataRequired()],  # strength enforced via validate_password() below
    )
    confirm_password = PasswordField(
        "Confirm Password",
        validators=[DataRequired(), EqualTo("password", message="Passwords must match.")],
    )
    submit = SubmitField("Sign Up")

    def validate_username(self, field):
        val = (field.data or "").strip()
        if not val:
            raise ValidationError("Username is required.")
        # Case-insensitive uniqueness
        exists = (
            User.query.filter(func.lower(User.username) == val.lower()).first()
        )
        if exists:
            raise ValidationError("Username already taken.")

    def validate_email(self, field):
        val = (field.data or "").strip().lower()

        ok, msg = is_valid_email(val)
        if not ok:
            raise ValidationError(msg or "Enter a valid email address.")

        # Case-insensitive uniqueness
        exists = User.query.filter(func.lower(User.email) == val).first()
        if exists:
            raise ValidationError("Email already in use.")

    def validate_password(self, field):
        pw = field.data or ""
        # Use the central helper so policy/env config is respected
        ok, msg = validate_strength(pw, (self.email.data or "").strip().lower())
        if not ok:
            raise ValidationError(msg or "Password does not meet requirements.")


class LoginForm(FlaskForm):
    # Keep the field name 'username' for compatibility with existing templates/routes,
    # but treat it as an email and validate with is_valid_email()
    username = StringField("Email", validators=[DataRequired()])
    password = PasswordField("Password", validators=[DataRequired()])
    remember = BooleanField("Remember Me")
    submit = SubmitField("Login")

    def validate_username(self, field):
        val = (field.data or "").strip().lower()
        ok, msg = is_valid_email(val)
        if not ok:
            raise ValidationError(msg or "Enter a valid email address.")
