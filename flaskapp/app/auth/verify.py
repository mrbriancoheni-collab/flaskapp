# app/auth/verify.py
from __future__ import annotations
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from flask import current_app, url_for

def _serializer() -> URLSafeTimedSerializer:
    secret = current_app.config["SECRET_KEY"]
    salt = current_app.config.get("EMAIL_VERIFY_SALT", "email-verify")
    return URLSafeTimedSerializer(secret_key=secret, salt=salt)

def make_verify_token(user_id: int, email: str) -> str:
    return _serializer().dumps({"uid": user_id, "email": email})

def read_verify_token(token: str, max_age: int = 60*60*24*3) -> dict:
    # default: 3 days validity
    return _serializer().loads(token, max_age=max_age)

def verify_link(token: str) -> str:
    return url_for("auth_bp.verify_email", token=token, _external=True)
