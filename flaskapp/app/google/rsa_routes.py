# app/google/rsa_routes.py
"""
RSA (Responsive Search Ad) asset performance routes.

Blueprint: rsa_bp
Prefix:    /account/google/ads/rsa
"""
from __future__ import annotations

from flask import Blueprint, render_template, jsonify

from app.auth.utils import login_required, current_account_id, growth_required

rsa_bp = Blueprint("rsa_bp", __name__, url_prefix="/account/google/ads/rsa")


@rsa_bp.get("/")
@login_required
def rsa_page():
    """Render the RSA ad copy performance page."""
    return render_template("google/ads/rsa_performance.html")


@rsa_bp.post("/sync")
@login_required
def sync():
    """Trigger a sync of RSA asset performance data from Google Ads. Returns JSON."""
    from app.services.google_ads_rsa_sync import sync_rsa_assets

    aid = current_account_id()
    result = sync_rsa_assets(aid)
    ok = len(result.get("errors", [])) == 0
    return jsonify({
        "ok": ok,
        "ads_synced": result.get("ads_synced", 0),
        "assets_synced": result.get("assets_synced", 0),
        "errors": result.get("errors", []),
        "message": (
            f"Synced {result.get('assets_synced', 0)} assets across {result.get('ads_synced', 0)} ads."
            if ok else
            "Sync completed with errors — see details below."
        ),
    }), 200 if ok else 500


@rsa_bp.get("/report.json")
@login_required
def report_json():
    """Return the RSA performance report as JSON."""
    from app.services.google_ads_rsa_sync import get_rsa_performance_report

    aid = current_account_id()
    report = get_rsa_performance_report(aid)
    return jsonify(report)


@rsa_bp.post("/auto-promote")
@login_required
@growth_required
def auto_promote():
    """Run the auto-promote logic and create recommendations. Returns JSON."""
    from app.services.google_ads_rsa_sync import auto_promote_winners

    aid = current_account_id()
    result = auto_promote_winners(aid)
    ok = len(result.get("errors", [])) == 0
    return jsonify({
        "ok": ok,
        "recommendations_created": result.get("recommendations_created", 0),
        "errors": result.get("errors", []),
        "message": (
            f"Created {result.get('recommendations_created', 0)} new recommendation(s)."
            if ok else
            "Auto-promote completed with errors."
        ),
    }), 200 if ok else 500
