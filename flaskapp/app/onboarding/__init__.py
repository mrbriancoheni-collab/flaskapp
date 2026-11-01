"""
Onboarding blueprint — URL-first account setup flow.

Routes:
  GET  /onboard          — URL input page
  POST /onboard/analyze  — AJAX: scrape + analyze website, return JSON
  POST /onboard/confirm  — Save detected/edited info, redirect to dashboard
"""
from __future__ import annotations

import logging
from urllib.parse import urlparse

from flask import (
    Blueprint,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from sqlalchemy import text

from app import db
from app.auth.utils import login_required

logger = logging.getLogger(__name__)

onboarding_bp = Blueprint("onboarding_bp", __name__, url_prefix="/onboard")


def _current_account_id() -> int | None:
    """Return the account_id for the current user without crashing."""
    try:
        from app.account import current_account_id
        return current_account_id()
    except Exception:
        user = getattr(g, "user", None)
        if user and hasattr(user, "account_id"):
            return user.account_id
        return None


def _is_onboarding_complete(account_id: int) -> bool:
    """Check onboarding_complete flag; returns False if column not yet migrated."""
    try:
        with db.engine.connect() as conn:
            row = conn.execute(
                text("SELECT onboarding_complete FROM accounts WHERE id = :aid"),
                {"aid": account_id},
            ).fetchone()
        if row is None:
            return False
        return bool(row[0])
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@onboarding_bp.route("", methods=["GET"], endpoint="onboarding_start")
@login_required
def onboarding_start():
    aid = _current_account_id()
    if aid and _is_onboarding_complete(aid):
        return redirect(url_for("account_bp.dashboard"))
    return render_template("onboard/start.html")


@onboarding_bp.route("/analyze", methods=["POST"], endpoint="onboarding_analyze")
@login_required
def onboarding_analyze():
    """AJAX endpoint — analyze a website URL and return structured data."""
    body = request.get_json(silent=True) or {}
    raw_url = (body.get("url") or "").strip()

    if not raw_url:
        return jsonify(success=False, error="Please provide a URL."), 400

    # Ensure scheme
    if not raw_url.startswith(("http://", "https://")):
        raw_url = "https://" + raw_url

    # Basic URL sanity check
    parsed = urlparse(raw_url)
    if not parsed.hostname:
        return jsonify(success=False, error="That doesn't look like a valid URL."), 400

    try:
        from app.services.website_analyzer import analyze_website
        data, error = analyze_website(raw_url)
    except Exception as exc:
        logger.exception("onboarding_analyze unexpected error: %s", exc)
        # Graceful fallback — let the form still work
        return jsonify(success=True, data=None, fallback=True)

    if error:
        # Return fallback so the user can still fill in manually
        logger.warning("Website analysis error for %s: %s", raw_url, error)
        return jsonify(success=True, data=None, fallback=True, error=error)

    return jsonify(success=True, data=data)


@onboarding_bp.route("/confirm", methods=["POST"], endpoint="onboarding_confirm")
@login_required
def onboarding_confirm():
    """Save confirmed/edited business info and mark onboarding complete."""
    aid = _current_account_id()
    if not aid:
        return redirect(url_for("account_bp.dashboard"))

    website_url = request.form.get("website_url", "").strip()[:500]
    business_name = request.form.get("business_name", "").strip()[:150]
    trade = request.form.get("trade", "other").strip()[:100]
    services_raw = request.form.get("services", "").strip()
    service_area = request.form.get("service_area", "").strip()[:200]

    # Normalise services to a JSON-ish comma list stored as TEXT
    services_list = [s.strip() for s in services_raw.split(",") if s.strip()]
    services_str = ", ".join(services_list[:8])

    description = (
        f"{business_name} is a {trade.replace('_', ' ')} contractor"
        f"{' in ' + service_area if service_area else ''}."
    )

    try:
        with db.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE accounts
                    SET website_url        = :url,
                        name               = :name,
                        detected_trade     = :trade,
                        detected_location  = :location,
                        business_description = :desc,
                        business_services  = :services,
                        onboarding_complete = TRUE
                    WHERE id = :aid
                    """
                ),
                {
                    "url": website_url or None,
                    "name": business_name or "My Business",
                    "trade": trade,
                    "location": service_area or None,
                    "desc": description,
                    "services": services_str or None,
                    "aid": aid,
                },
            )
    except Exception as exc:
        logger.exception("onboarding_confirm DB update failed: %s", exc)

    return redirect(url_for("account_bp.dashboard"))
