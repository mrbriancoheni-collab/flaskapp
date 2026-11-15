"""
Campaign Health Triage blueprint — daily per-campaign action dashboard.

Routes:
  GET  /account/campaign-health          — triage dashboard
  GET  /account/campaign-health/data     — JSON triage data (for AJAX refresh)
"""
import logging

from flask import Blueprint, jsonify, render_template, request
from flask_login import current_user

from app.auth.utils import login_required

log = logging.getLogger(__name__)

campaign_health_bp = Blueprint(
    "campaign_health_bp",
    __name__,
    url_prefix="/account/campaign-health",
)


def _get_account_id() -> int | None:
    try:
        from app.db_utils import get_account_id_for_user
        return get_account_id_for_user(current_user.id)
    except Exception:
        try:
            return current_user.account_id
        except AttributeError:
            return None


@campaign_health_bp.route("/")
@login_required
def index():
    account_id = _get_account_id()
    if not account_id:
        return render_template("campaign_health/index.html", triage=None, error="No Google Ads account connected.")

    try:
        from app.campaign_health.triage import run_triage
        triage = run_triage(account_id)
    except Exception:
        log.exception("run_triage failed for account %s", account_id)
        triage = None

    return render_template("campaign_health/index.html", triage=triage, error=None)


@campaign_health_bp.route("/data")
@login_required
def data():
    """JSON endpoint — used by the dashboard's refresh button."""
    account_id = _get_account_id()
    if not account_id:
        return jsonify({"error": "No Google Ads account connected."}), 400

    days = min(30, max(7, int(request.args.get("days", 7))))
    try:
        from app.campaign_health.triage import run_triage
        return jsonify(run_triage(account_id, days=days))
    except Exception:
        log.exception("run_triage/data failed for account %s", account_id)
        return jsonify({"error": "Triage failed. Check server logs."}), 500
