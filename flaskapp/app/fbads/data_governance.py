# app/fbads/data_governance.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import base64, hmac, hashlib, json, time
from typing import Dict, Any, Tuple, Optional
from flask import (
    Blueprint, request, jsonify, render_template, current_app, url_for, session
)

# Optional DB import
try:
    from app import db  # type: ignore
except Exception:  # pragma: no cover
    db = None  # type: ignore

data_bp = Blueprint("data_bp", __name__)  # register with url_prefix="/account"

# ---------- shared helpers ----------
def _b64url_decode(s: str) -> bytes:
    s += '=' * (-len(s) % 4)
    return base64.urlsafe_b64decode(s.encode("utf-8"))

def _parse_signed_request(signed_request: str, app_secret: str) -> Tuple[bool, Dict[str, Any]]:
    """
    Validates Facebook signed_request per docs:
    https://developers.facebook.com/docs/facebook-login/security/#signed-requests
    """
    try:
        sig_b64, payload_b64 = signed_request.split(".", 1)
        sig = _b64url_decode(sig_b64)
        payload = json.loads(_b64url_decode(payload_b64) or b"{}")
        expected = hmac.new(
            app_secret.encode("utf-8"),
            msg=payload_b64.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).digest()
        return hmac.compare_digest(sig, expected), payload
    except Exception:
        return False, {}

def _app_secret() -> Optional[str]:
    return current_app.config.get("FB_APP_SECRET")

# Simple demo stores (swap to DB if you prefer)
_DELETION_REQS: Dict[str, Dict[str, Any]] = {}
_DEAUTH_LOG: Dict[str, Dict[str, Any]] = {}

def _delete_user_data(user_id: str) -> None:
    """
    Central place to purge PII for a Facebook user.
    Replace body with your own deletes (tokens, leads, etc).
    """
    # Example: if you persisted a token per account/user, delete there.
    # Here we just note the user in session for demo.
    k = f"deleted_{user_id}"
    session[k] = int(time.time())

# ---------- Public Info Page ----------
@data_bp.get("/legal/data-deletion")
def data_deletion_landing():
    """
    Public-facing instructions page you’ll link in Facebook:
    Products → Facebook Login → Settings → Data Deletion Requests → 'Data Deletion Instructions URL'
    """
    return render_template("legal/data_deletion.html")

# ---------- Data Deletion Callback (required) ----------
@data_bp.post("/facebook/data_deletion")
def facebook_data_deletion():
    """
    What you configure as the 'Data Deletion Request URL'.
    Receives POST with signed_request; validate, delete, return a status URL.
    """
    signed_request = request.form.get("signed_request", "")
    secret = _app_secret()
    if not signed_request or not secret:
        return jsonify({"error": "missing signed_request or app_secret"}), 400

    ok, payload = _parse_signed_request(signed_request, secret)
    if not ok:
        return jsonify({"error": "invalid signature"}), 400

    user_id = str(payload.get("user_id") or "")
    if not user_id:
        return jsonify({"error": "missing user_id"}), 400

    # Delete now (or enqueue an async job and mark status accordingly)
    _delete_user_data(user_id)

    confirmation_code = f"fbdel_{user_id}_{int(time.time())}"
    _DELETION_REQS[confirmation_code] = {
        "user_id": user_id,
        "status": "completed",
        "updated_at": int(time.time()),
    }

    status_url = url_for("data_bp.facebook_data_deletion_status", code=confirmation_code, _external=True)
    return jsonify({"url": status_url, "confirmation_code": confirmation_code}), 200

@data_bp.get("/facebook/data_deletion_status/<code>")
def facebook_data_deletion_status(code: str):
    """
    Minimal status endpoint shown to the user by Facebook after they request deletion.
    """
    rec = _DELETION_REQS.get(code)
    if not rec:
        return render_template("legal/deletion_status.html", found=False), 404
    return render_template("legal/deletion_status.html", found=True, rec=rec), 200

# ---------- Deauthorize Callback (recommended) ----------
@data_bp.route("/facebook/deauthorize", methods=["GET", "POST"])
def facebook_deauthorize():
    """
    What you configure as the 'Deauthorize Callback URL' under Facebook App → Products → Facebook Login → Settings.
    Facebook POSTs a signed_request here when a user removes your app.
    We also provide GET so you can sanity-check in browser (will just render a small info page).
    """
    if request.method == "GET":
        # Human-friendly page so you can load/confirm the URL works.
        return render_template("legal/deauthorize_info.html")

    # POST from Facebook
    signed_request = request.form.get("signed_request", "")
    secret = _app_secret()
    if not signed_request or not secret:
        return jsonify({"error": "missing signed_request or app_secret"}), 400

    ok, payload = _parse_signed_request(signed_request, secret)
    if not ok:
        return jsonify({"error": "invalid signature"}), 400

    user_id = str(payload.get("user_id") or "")
    issued_at = int(payload.get("issued_at") or time.time())
    if user_id:
        # Remove all user data on deauth as well (or mark for deletion)
        _delete_user_data(user_id)

    key = f"deauth_{user_id}_{issued_at}"
    _DEAUTH_LOG[key] = {"user_id": user_id, "issued_at": issued_at, "processed_at": int(time.time())}

    # Respond 200 to acknowledge. You may return plain text or JSON.
    return jsonify({"ok": True}), 200
