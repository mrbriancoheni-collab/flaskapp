# app/google/gclid_capture_routes.py
"""
GCLID Capture routes — website visitor tracking, snippet delivery, manual upload.

Blueprint: gclid_capture_bp
Prefix:    /track
"""
from __future__ import annotations

import csv
import io
import json
import logging
import re
import time
from datetime import datetime, timedelta
from typing import List, Optional

from flask import (
    Blueprint,
    Response,
    current_app,
    jsonify,
    render_template,
    request,
)

from app import db
from app.auth.utils import login_required, current_account_id

logger = logging.getLogger(__name__)

gclid_capture_bp = Blueprint("gclid_capture_bp", __name__, url_prefix="/track")

# ---------------------------------------------------------------------------
# EmailGclidMap — imported defensively (parallel agent may not have landed yet)
# ---------------------------------------------------------------------------
try:
    from app.models_skimmer import EmailGclidMap
    HAS_EMAIL_MAP = True
except ImportError:
    HAS_EMAIL_MAP = False

# ---------------------------------------------------------------------------
# Simple in-memory rate limiter  (not perfect across workers, but avoids Redis)
# ---------------------------------------------------------------------------
_rate_counters: dict = {}   # {account_id: (window_start_ts, count)}
_RATE_LIMIT = 100           # requests per window
_RATE_WINDOW = 60           # seconds


def _check_rate_limit(account_id: int) -> bool:
    """Return True if the request is allowed, False if rate-limited."""
    now = time.time()
    window_start, count = _rate_counters.get(account_id, (now, 0))
    if now - window_start > _RATE_WINDOW:
        # start a fresh window
        _rate_counters[account_id] = (now, 1)
        return True
    if count >= _RATE_LIMIT:
        return False
    _rate_counters[account_id] = (window_start, count + 1)
    return True


# ---------------------------------------------------------------------------
# Phone normalisation helper
# ---------------------------------------------------------------------------
def _normalize_phone(raw: str) -> Optional[str]:
    """Strip non-digits; return E.164 (+1XXXXXXXXXX) or None."""
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 10:
        return "+1" + digits
    if len(digits) == 11 and digits.startswith("1"):
        return "+" + digits
    return None


# ---------------------------------------------------------------------------
# Upsert helpers
# ---------------------------------------------------------------------------

def _upsert_phone(account_id: int, phone_e164: str, gclid: str, utm_source: Optional[str],
                  utm_medium: Optional[str], utm_campaign: Optional[str],
                  keyword: Optional[str]) -> None:
    from app.models_skimmer import PhoneGclidMap
    expires = datetime.utcnow() + timedelta(days=90)
    existing = PhoneGclidMap.query.filter_by(
        account_id=account_id, phone_e164=phone_e164
    ).first()
    if existing:
        existing.gclid = gclid
        existing.utm_source = utm_source
        existing.utm_medium = utm_medium
        existing.utm_campaign = utm_campaign
        existing.keyword = keyword
        existing.expires_at = expires
    else:
        row = PhoneGclidMap(
            account_id=account_id,
            phone_e164=phone_e164,
            gclid=gclid,
            utm_source=utm_source,
            utm_medium=utm_medium,
            utm_campaign=utm_campaign,
            keyword=keyword,
            expires_at=expires,
        )
        db.session.add(row)


def _upsert_email(account_id: int, email: str, gclid: str, utm_source: Optional[str],
                  utm_medium: Optional[str], utm_campaign: Optional[str],
                  keyword: Optional[str]) -> bool:
    """Return True if EmailGclidMap is available and the upsert succeeded."""
    if not HAS_EMAIL_MAP:
        return False
    expires = datetime.utcnow() + timedelta(days=90)
    existing = EmailGclidMap.query.filter_by(
        account_id=account_id, email=email
    ).first()
    if existing:
        existing.gclid = gclid
        existing.utm_source = utm_source
        existing.utm_medium = utm_medium
        existing.utm_campaign = utm_campaign
        existing.keyword = keyword
        existing.expires_at = expires
    else:
        row = EmailGclidMap(
            account_id=account_id,
            email=email,
            gclid=gclid,
            utm_source=utm_source,
            utm_medium=utm_medium,
            utm_campaign=utm_campaign,
            keyword=keyword,
            expires_at=expires,
        )
        db.session.add(row)
    return True


# ---------------------------------------------------------------------------
# POST /track/gclid  — public, no login
# ---------------------------------------------------------------------------

@gclid_capture_bp.post("/gclid")
def capture_gclid():
    """Accept GCLID + contact info from website visitors (called by JS snippet)."""
    from app.models import Account

    data = request.get_json(silent=True) or {}

    # --- validate account_id ---
    raw_account_id = data.get("account_id")
    if not raw_account_id:
        return jsonify({"error": "account_id required"}), 400
    try:
        account_id = int(raw_account_id)
    except (TypeError, ValueError):
        return jsonify({"error": "account_id must be an integer"}), 400

    # --- rate limit ---
    if not _check_rate_limit(account_id):
        return jsonify({"error": "Rate limit exceeded. Max 100 requests per minute."}), 429

    # --- validate gclid ---
    gclid = (data.get("gclid") or "").strip()
    if not gclid:
        return jsonify({"error": "gclid required"}), 400

    # --- validate account exists ---
    try:
        account = Account.query.get(account_id)
        if not account:
            return jsonify({"error": "Invalid account_id"}), 400
    except Exception as exc:
        logger.warning("Account lookup failed: %s", exc)
        return jsonify({"error": "Invalid account_id"}), 400

    # --- extract optional fields ---
    raw_phone = (data.get("phone") or "").strip()
    raw_email = (data.get("email") or "").strip().lower()
    utm_source = (data.get("utm_source") or "").strip() or None
    utm_medium = (data.get("utm_medium") or "").strip() or None
    utm_campaign = (data.get("utm_campaign") or "").strip() or None
    keyword = (data.get("keyword") or "").strip() or None

    phone_e164 = _normalize_phone(raw_phone) if raw_phone else None
    email = raw_email if raw_email else None

    stored: List[str] = []

    try:
        if phone_e164:
            _upsert_phone(account_id, phone_e164, gclid, utm_source, utm_medium, utm_campaign, keyword)
            stored.append("phone")
        if email:
            ok = _upsert_email(account_id, email, gclid, utm_source, utm_medium, utm_campaign, keyword)
            if ok:
                stored.append("email")
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        logger.exception("gclid capture DB error for account %s", account_id)
        return jsonify({"error": str(exc)}), 500

    return jsonify({"ok": True, "stored": stored})


# ---------------------------------------------------------------------------
# GET /track/snippet.js  — login required, returns JavaScript
# ---------------------------------------------------------------------------

@gclid_capture_bp.get("/snippet.js")
@login_required
def snippet_js():
    """Return a JavaScript snippet tailored to the logged-in user's account."""
    account_id = current_account_id()
    capture_url = request.host_url.rstrip("/") + "/track/gclid"

    js = f"""
(function() {{
  var ACCOUNT_ID = {account_id};
  var CAPTURE_URL = "{capture_url}";
  var STORAGE_KEY = "fs_gclid";
  var TTL_MS = 90 * 24 * 60 * 60 * 1000; // 90 days

  function getParam(name) {{
    var url = new URL(window.location.href);
    return url.searchParams.get(name) || null;
  }}

  function saveToStorage(key, value) {{
    try {{ localStorage.setItem(key, JSON.stringify({{ v: value, ts: Date.now() }})); }} catch(e) {{}}
  }}

  function loadFromStorage(key) {{
    try {{
      var raw = localStorage.getItem(key);
      if (!raw) return null;
      var obj = JSON.parse(raw);
      if (Date.now() - obj.ts > TTL_MS) {{ localStorage.removeItem(key); return null; }}
      return obj.v;
    }} catch(e) {{ return null; }}
  }}

  function saveParam(name, storageKey) {{
    var val = getParam(name);
    if (val) saveToStorage(storageKey, val);
  }}

  // On page load: capture GCLID and UTM params from URL
  (function captureFromUrl() {{
    var gclidFromUrl = getParam("gclid");
    var stored = loadFromStorage(STORAGE_KEY);
    if (gclidFromUrl) {{
      // Always prefer freshest — update if URL has one
      if (!stored || gclidFromUrl !== stored) {{
        saveToStorage(STORAGE_KEY, gclidFromUrl);
      }}
    }}
    saveParam("utm_source", "fs_utm_source");
    saveParam("utm_medium", "fs_utm_medium");
    saveParam("utm_campaign", "fs_utm_campaign");
    saveParam("keyword", "fs_keyword");
  }})();

  function findField(form, names) {{
    for (var i = 0; i < names.length; i++) {{
      var el = form.querySelector('[name="' + names[i] + '"], [id="' + names[i] + '"], [placeholder*="' + names[i] + '"]');
      if (el) return el.value || null;
    }}
    return null;
  }}

  function addHidden(form, name, value) {{
    if (!value) return;
    var existing = form.querySelector('input[name="' + name + '"]');
    if (existing) {{ existing.value = value; return; }}
    var inp = document.createElement("input");
    inp.type = "hidden";
    inp.name = name;
    inp.value = value;
    form.appendChild(inp);
  }}

  function sendCapture(gclid, phone, email) {{
    var payload = {{
      account_id: ACCOUNT_ID,
      gclid: gclid,
      phone: phone || null,
      email: email || null,
      utm_source: loadFromStorage("fs_utm_source"),
      utm_medium: loadFromStorage("fs_utm_medium"),
      utm_campaign: loadFromStorage("fs_utm_campaign"),
      keyword: loadFromStorage("fs_keyword"),
      landing_page: window.location.href
    }};
    try {{
      navigator.sendBeacon
        ? navigator.sendBeacon(CAPTURE_URL, new Blob([JSON.stringify(payload)], {{type:"application/json"}}))
        : fetch(CAPTURE_URL, {{method:"POST", headers:{{"Content-Type":"application/json"}}, body:JSON.stringify(payload), keepalive:true}});
    }} catch(e) {{}}
  }}

  // Attach to all forms on the page
  document.addEventListener("submit", function(evt) {{
    var form = evt.target;
    if (!form || form.tagName !== "FORM") return;
    var gclid = loadFromStorage(STORAGE_KEY);
    var phone = findField(form, ["phone","tel","mobile","Phone","PhoneNumber","phone_number"]);
    var email = findField(form, ["email","Email","email_address","EmailAddress"]);
    if (gclid) {{
      addHidden(form, "fs_gclid", gclid);
      addHidden(form, "fs_phone", phone);
      addHidden(form, "fs_email", email);
      sendCapture(gclid, phone, email);
    }}
  }}, true);

}})();
""".strip()

    return Response(js, mimetype="application/javascript")


# ---------------------------------------------------------------------------
# GET /track/snippet  — login required, HTML embed guide
# ---------------------------------------------------------------------------

@gclid_capture_bp.get("/snippet")
@login_required
def snippet_page():
    """Show embed instructions and a test button."""
    account_id = current_account_id()
    snippet_js_url = request.host_url.rstrip("/") + "/track/snippet.js"
    script_tag = f'<script src="{snippet_js_url}" defer></script>'
    capture_url = request.host_url.rstrip("/") + "/track/gclid"
    return render_template(
        "integrations/gclid_snippet.html",
        account_id=account_id,
        script_tag=script_tag,
        snippet_js_url=snippet_js_url,
        capture_url=capture_url,
    )


# ---------------------------------------------------------------------------
# POST /track/manual-upload  — login required, CSV or JSON bulk import
# ---------------------------------------------------------------------------

@gclid_capture_bp.post("/manual-upload")
@login_required
def manual_upload():
    """Bulk import phone/email → GCLID mappings from CSV file or JSON body."""
    account_id = current_account_id()

    MAX_ROWS = 5000
    imported = 0
    skipped = 0
    errors: List[str] = []

    # ---- determine input format ----
    rows: List[dict] = []

    if request.content_type and "application/json" in request.content_type:
        data = request.get_json(silent=True)
        if not isinstance(data, list):
            return jsonify({"error": "JSON body must be an array of objects"}), 400
        rows = data[:MAX_ROWS]
        if len(data) > MAX_ROWS:
            errors.append(f"Truncated to first {MAX_ROWS} rows (received {len(data)}).")
    else:
        # CSV upload
        file = request.files.get("file")
        if not file:
            return jsonify({"error": "No file uploaded. Send a CSV file in the 'file' field."}), 400
        try:
            stream = io.StringIO(file.read().decode("utf-8-sig"))
            reader = csv.DictReader(stream)
            for i, row in enumerate(reader):
                if i >= MAX_ROWS:
                    errors.append(f"Truncated to first {MAX_ROWS} rows.")
                    break
                rows.append(row)
        except Exception as exc:
            return jsonify({"error": f"Failed to parse CSV: {exc}"}), 400

    # ---- process rows ----
    for idx, row in enumerate(rows):
        try:
            raw_phone = str(row.get("phone") or "").strip()
            raw_email = str(row.get("email") or "").strip().lower()
            gclid = str(row.get("gclid") or "").strip()
            utm_campaign = str(row.get("utm_campaign") or "").strip() or None
            keyword_val = str(row.get("keyword") or "").strip() or None

            if not gclid:
                skipped += 1
                errors.append(f"Row {idx + 1}: missing gclid — skipped.")
                continue

            phone_e164 = _normalize_phone(raw_phone) if raw_phone else None
            email = raw_email if raw_email else None

            if not phone_e164 and not email:
                skipped += 1
                errors.append(f"Row {idx + 1}: no valid phone or email — skipped.")
                continue

            if phone_e164:
                _upsert_phone(account_id, phone_e164, gclid, None, None, utm_campaign, keyword_val)
            if email:
                _upsert_email(account_id, email, gclid, None, None, utm_campaign, keyword_val)

            imported += 1

        except Exception as exc:
            skipped += 1
            errors.append(f"Row {idx + 1}: {exc}")

    try:
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        logger.exception("manual_upload commit failed for account %s", account_id)
        return jsonify({"error": f"Database error: {exc}"}), 500

    return jsonify({
        "imported": imported,
        "skipped": skipped,
        "errors": errors[:50],  # cap error list to avoid huge responses
    })
