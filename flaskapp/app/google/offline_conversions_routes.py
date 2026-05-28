# app/google/offline_conversions_routes.py
"""
Offline Conversion Import routes — CallRail webhook, manual upload, stats.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from flask import (
    Blueprint,
    render_template,
    request,
    jsonify,
    current_app,
)

from app import db
from app.auth.utils import login_required, current_account_id

offline_conv_bp = Blueprint(
    "offline_conv_bp",
    __name__,
    url_prefix="/account/google/ads/offline-conversions",
)


# ─────────────────────────────────────────────────────────────────────────────
# GET /  — Dashboard page
# ─────────────────────────────────────────────────────────────────────────────

@offline_conv_bp.get("/")
@login_required
def imports_page():
    """Render the Phone Call Tracking dashboard."""
    from app.services.google_ads_offline_conversions import get_import_stats
    from app.models_ads import OfflineConversionImport

    aid = current_account_id()
    stats = {}
    recent_imports = []
    try:
        stats = get_import_stats(aid)
    except Exception as exc:
        current_app.logger.exception("get_import_stats failed for account %s", aid)

    try:
        recent_imports = (
            OfflineConversionImport.query
            .filter_by(account_id=aid)
            .order_by(OfflineConversionImport.created_at.desc())
            .limit(50)
            .all()
        )
    except Exception as exc:
        current_app.logger.exception("Could not load recent imports for account %s", aid)

    webhook_url = (
        request.host_url.rstrip("/")
        + f"/account/google/ads/offline-conversions/webhook/callrail/{aid}"
    )

    return render_template(
        "google/ads/offline_conversions.html",
        gads_active="offline_conversions",
        stats=stats,
        recent_imports=recent_imports,
        webhook_url=webhook_url,
        account_id=aid,
    )


# ─────────────────────────────────────────────────────────────────────────────
# POST /webhook/callrail/<account_id>  — CallRail webhook (no auth)
# ─────────────────────────────────────────────────────────────────────────────

@offline_conv_bp.post("/webhook/callrail/<int:account_id>")
def callrail_webhook(account_id: int):
    """
    Receive a call event from CallRail.
    No login_required — this is an inbound webhook from CallRail's servers.
    """
    from app.services.google_ads_offline_conversions import (
        handle_callrail_webhook,
        validate_callrail_signature,
    )

    # Optional signature validation
    secret = os.environ.get("CALLRAIL_WEBHOOK_SECRET", "").strip()
    if secret:
        sig = request.headers.get("X-CallRail-Signature", "")
        if not validate_callrail_signature(request.get_data(), sig, secret):
            current_app.logger.warning(
                "CallRail webhook signature mismatch for account %s", account_id
            )
            return jsonify({"error": "Invalid signature"}), 401

    try:
        payload = request.get_json(force=True, silent=True) or {}
    except Exception:
        payload = {}

    if not payload:
        return jsonify({"error": "Empty or invalid JSON payload"}), 400

    try:
        result = handle_callrail_webhook(payload, account_id)
    except Exception as exc:
        current_app.logger.exception(
            "handle_callrail_webhook raised for account %s", account_id
        )
        return jsonify({"error": str(exc)}), 500

    return jsonify(result), 200


# ─────────────────────────────────────────────────────────────────────────────
# POST /upload  — Trigger upload of pending conversions
# ─────────────────────────────────────────────────────────────────────────────

@offline_conv_bp.post("/upload")
@login_required
def upload():
    """Push all pending offline conversions to Google Ads."""
    from app.services.google_ads_offline_conversions import upload_pending_conversions

    aid = current_account_id()
    try:
        result = upload_pending_conversions(aid)
        result["ok"] = result["failed"] == 0
        return jsonify(result), 200
    except Exception as exc:
        current_app.logger.exception("upload_pending_conversions failed for account %s", aid)
        return jsonify({"ok": False, "error": str(exc)}), 500


# ─────────────────────────────────────────────────────────────────────────────
# GET /stats.json  — Stats endpoint for JS polling
# ─────────────────────────────────────────────────────────────────────────────

@offline_conv_bp.get("/stats.json")
@login_required
def stats_json():
    """Return import stats as JSON for the dashboard."""
    from app.services.google_ads_offline_conversions import get_import_stats

    aid = current_account_id()
    try:
        stats = get_import_stats(aid)
        return jsonify(stats), 200
    except Exception as exc:
        current_app.logger.exception("get_import_stats failed for account %s", aid)
        return jsonify({"error": str(exc)}), 500


# ─────────────────────────────────────────────────────────────────────────────
# POST /manual  — Manual import from JSON body
# ─────────────────────────────────────────────────────────────────────────────

@offline_conv_bp.post("/manual")
@login_required
def manual_import():
    """
    Accept a JSON array of conversion records:
      [{gclid, conversion_time, value, conversion_name}, ...]
    Creates OfflineConversionImport rows with source="manual".
    Returns {"created": N, "skipped": N, "errors": [...]}.
    """
    from app.models_ads import OfflineConversionImport

    aid = current_account_id()

    try:
        body = request.get_json(force=True, silent=True) or []
    except Exception:
        body = []

    if not isinstance(body, list):
        body = [body]

    created = 0
    skipped = 0
    errors = []

    for idx, item in enumerate(body):
        if not isinstance(item, dict):
            errors.append(f"Item {idx}: not an object")
            skipped += 1
            continue

        gclid = (item.get("gclid") or "").strip()
        if not gclid:
            errors.append(f"Item {idx}: missing gclid")
            skipped += 1
            continue

        # Parse conversion_time
        raw_time = item.get("conversion_time")
        conversion_time = None
        if raw_time:
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
                try:
                    conversion_time = datetime.strptime(str(raw_time).strip(), fmt).replace(
                        tzinfo=timezone.utc
                    )
                    break
                except ValueError:
                    continue
        if conversion_time is None:
            conversion_time = datetime.now(timezone.utc)

        try:
            value = float(item.get("value") or 0.0)
        except (TypeError, ValueError):
            value = 0.0

        conversion_name = (item.get("conversion_name") or "Phone Call Lead").strip()

        record = OfflineConversionImport(
            account_id=aid,
            source="manual",
            external_id=None,
            gclid=gclid,
            conversion_name=conversion_name,
            conversion_time=conversion_time,
            conversion_value=value,
            currency_code="USD",
            status="pending",
        )
        db.session.add(record)
        created += 1

    if created > 0:
        try:
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            current_app.logger.exception("manual_import DB commit failed for account %s", aid)
            return jsonify({"ok": False, "error": str(exc)}), 500

    return jsonify({
        "ok": True,
        "created": created,
        "skipped": skipped,
        "errors": errors,
    }), 200
