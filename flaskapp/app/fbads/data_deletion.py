# app/fbads/data_deletion.py (or inside your existing blueprint/module)
import base64
import hmac
import hashlib
import json
import time
from typing import Tuple, Dict, Any
from flask import Blueprint, request, jsonify, current_app, url_for

data_deletion_bp = Blueprint("data_deletion_bp", __name__)

def _b64url_decode(s: str) -> bytes:
    s += '=' * (-len(s) % 4)
    return base64.urlsafe_b64decode(s.encode('utf-8'))

def _parse_signed_request(signed_request: str, app_secret: str) -> Tuple[bool, Dict[str, Any]]:
    try:
        sig_b64, payload_b64 = signed_request.split('.', 1)
        sig = _b64url_decode(sig_b64)
        payload = json.loads(_b64url_decode(payload_b64) or b"{}")
        expected = hmac.new(
            app_secret.encode('utf-8'),
            msg=payload_b64.encode('utf-8'),
            digestmod=hashlib.sha256
        ).digest()
        ok = hmac.compare_digest(sig, expected)
        return ok, payload
    except Exception:
        return False, {}

# In-memory demo store; replace with DB if you want persistence.
_DATA_DELETION_REQUESTS: Dict[str, Dict[str, Any]] = {}

@data_deletion_bp.post("/facebook/data_deletion")
def facebook_data_deletion():
    """This is the URL you paste into Facebook → Products → Facebook Login → Settings → Data Deletion Requests."""
    signed_request = request.form.get("signed_request", "")
    app_secret = current_app.config.get("FB_APP_SECRET")
    if not signed_request or not app_secret:
        return jsonify({"error": "missing signed_request or app_secret"}), 400

    ok, payload = _parse_signed_request(signed_request, app_secret)
    if not ok:
        return jsonify({"error": "invalid signature"}), 400

    # The payload typically includes 'user_id'
    user_id = str(payload.get("user_id") or "")
    if not user_id:
        return jsonify({"error": "missing user_id"}), 400

    # TODO: delete or anonymize any data associated with this user_id in your DB/storage.
    # For demo, we just mark a request ID + status entry.
    confirmation_code = f"fbdel_{user_id}_{int(time.time())}"
    _DATA_DELETION_REQUESTS[confirmation_code] = {
        "user_id": user_id,
        "status": "scheduled",   # or "completed" after async job
        "updated_at": int(time.time()),
    }

    # Return the URL that Facebook will show to the user.
    status_url = url_for("data_deletion_bp.facebook_data_deletion_status",
                         code=confirmation_code, _external=True)

    # Per Facebook docs, return a JSON object with `url` and optionally `confirmation_code`.
    return jsonify({
        "url": status_url,
        "confirmation_code": confirmation_code
    }), 200

@data_deletion_bp.get("/facebook/data_deletion_status/<code>")
def facebook_data_deletion_status(code: str):
    """Public page/endpoint for users to check the status of their deletion request."""
    rec = _DATA_DELETION_REQUESTS.get(code)
    if not rec:
        return jsonify({"ok": False, "status": "not_found"}), 404

    # You can render a template instead. Keeping JSON for simplicity.
    return jsonify({
        "ok": True,
        "status": rec["status"],
        "user_id": rec["user_id"],
        "updated_at": rec["updated_at"]
    }), 200
