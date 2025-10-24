# app/glsa/__init__.py
from __future__ import annotations

from datetime import date
from typing import Sequence

import requests
from flask import (
    Blueprint,
    render_template,
    redirect,
    url_for,
    flash,
    request,
    current_app,
    jsonify,
)
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app import db
from app.auth.utils import login_required, current_account_id
from app.google.token_utils import ensure_access_token
from app.google.utils_ads import resolve_ads_context

glsa_bp = Blueprint("glsa_bp", __name__, url_prefix="/account/glsa")

API_BASE = "https://localservices.googleapis.com/v1"

SAMPLE_LEADS = [
    {
        "leadId": "LSA-EXAMPLE-1",
        "consumerPhoneNumber": "+1-555-0101",
        "consumerName": "Pat Example",
        "jobType": "Water heater install",
        "createTime": "2025-09-01T16:12:00Z",
        "leadStatus": "ACTIVE",
        "chargedPrice": {"currencyCode": "USD", "units": "49"},
        "location": {"city": "Springfield", "postalCode": "30306"},
        "notes": "Called after hours, left voicemail.",
        "adPhoneNumber": "+1-555-0000",
        "timezone": "America/New_York",
    },
    {
        "leadId": "LSA-EXAMPLE-2",
        "consumerPhoneNumber": "+1-555-0102",
        "consumerName": "Chris Sample",
        "jobType": "Drain clearing (emergency)",
        "createTime": "2025-09-03T09:21:00Z",
        "leadStatus": "BOOKED",
        "chargedPrice": {"currencyCode": "USD", "units": "74"},
        "location": {"city": "Midtown", "postalCode": "30308"},
        "notes": "Converted on first call.",
        "adPhoneNumber": "+1-555-0000",
        "timezone": "America/New_York",
    },
]


def _has_any_google_token(aid: int, prods: Sequence[str]) -> bool:
    """Return True if the account has at least one OAuth token for any of the given products."""
    try:
        with db.engine.connect() as conn:
            row = (
                conn.execute(
                    text(
                        """
                        SELECT 1 AS x
                          FROM google_oauth_tokens
                         WHERE account_id=:aid
                           AND product IN :prods
                         LIMIT 1
                        """
                    ),
                    {"aid": aid, "prods": tuple(prods)},
                )
                .mappings()
                .first()
            )
            return bool(row)
    except SQLAlchemyError as e:
        current_app.logger.warning("GLSA _has_any_google_token failed: %s", e)
        return False


def _ads_ctx(aid: int) -> dict:
    """Resolve Ads context (customer_id + optional login_customer_id). Include a template-safe profile key."""
    try:
        ctx = resolve_ads_context(aid) or {"customer_id": None, "login_customer_id": None}
    except Exception as e:
        current_app.logger.warning("resolve_ads_context error: %s", e)
        ctx = {"customer_id": None, "login_customer_id": None}
    # ensure template-safe keys (optimize.html reads ctx.profile.*)
    ctx.setdefault("profile", {})
    return ctx


# ───────────────────────── Routes ─────────────────────────

@glsa_bp.route("/", methods=["GET"], endpoint="index")
@login_required
def index():
    aid = current_account_id()
    connected = _has_any_google_token(aid, ("lsa", "ads"))
    ctx = _ads_ctx(aid)
    return render_template(
        "glsa/index.html",
        connected=connected,
        ctx=ctx,
        epn=request.endpoint,
        SECTION="glsa",
    )


@glsa_bp.get("/connect", endpoint="connect")
@login_required
def connect():
    # After OAuth, return to GLSA leads (or provided next)
    nxt = request.args.get("next") or url_for("glsa_bp.leads_page")
    return redirect(url_for("google_bp.connect_lsa", next=nxt))


@glsa_bp.get("/optimize", endpoint="optimize")
@login_required
def optimize():
    aid = current_account_id()
    connected = _has_any_google_token(aid, ("lsa", "ads"))
    ctx = _ads_ctx(aid)
    return render_template(
        "glsa/optimize.html",
        connected=connected,
        ctx=ctx,
        epn=request.endpoint,
        SECTION="glsa",
    )


@glsa_bp.route("/optimize/assist", methods=["POST"], endpoint="optimize_assist")
@login_required
def optimize_assist():
    """Accepts profile + answers and returns optimization recommendations for LSA profile/budget/categories."""
    try:
        payload = request.get_json(force=True) or {}
    except Exception:
        return jsonify({"ok": False, "error": "invalid_json"}), 400

    prof = payload.get("profile") or {}
    ans = payload.get("answers") or {}

    recos = []

    # Categories
    primary = (prof.get("primary_category") or "").strip()
    cats = prof.get("categories") or []
    if not primary:
        recos.append("Set a strong primary category that matches your highest-value services.")
    if len(cats) < 2:
        recos.append("Add 2–4 additional relevant categories to widen eligible queries.")
    if ans.get("priorities"):
        recos.append(f"Verify categories cover your stated priorities: “{ans['priorities']}”.")

    # Service areas
    areas = prof.get("service_areas") or []
    if not areas:
        recos.append("Define service areas (zip/cities). Start with your highest-converting neighborhoods.")
    if ans.get("priority_areas"):
        recos.append(f"Emphasize high-value zip/cities: “{ans['priority_areas']}”. Consider excluding low-margin zones.")

    # Hours / responsiveness
    hours = (prof.get("hours") or "").strip()
    if not hours:
        recos.append("Publish business hours; enable after-hours for emergencies if possible.")
    rt = ans.get("response_time") or ""
    if rt and ("5" in rt or "<" in rt):
        recos.append(f"You respond within {rt} — highlight fast response in your profile text.")
    elif rt:
        recos.append(f"Improve response time ({rt}). Leads decay quickly; aim for <15 minutes.")
    ah = ans.get("after_hours") or ""
    if isinstance(ah, str) and ah.lower().startswith("yes"):
        recos.append("Since you take after-hours/weekend calls, reflect this in your hours and ad text.")

    # Reviews
    try:
        rating = float(prof.get("rating") or 0)
    except Exception:
        rating = 0
    try:
        reviews = int(prof.get("reviews_count") or 0)
    except Exception:
        reviews = 0
    if rating and rating < 4.6:
        recos.append("Increase your average rating (target 4.7+). Close the loop on detractors; request more reviews.")
    if reviews < 50:
        recos.append("Ramp up fresh reviews (aim 5–10 this month). Feature key services in replies.")

    # Budget / goals
    try:
        budget = float(prof.get("weekly_budget") or 0)
    except Exception:
        budget = 0
    goal = (ans.get("lead_goal") or "").strip()
    if not budget:
        recos.append("Set a weekly budget aligned to lead goal; scale on profitable days/areas.")
    elif goal:
        recos.append(f"Align budget pacing to your 30-day lead goal ({goal}). Use dayparting on peak times.")

    # Contact / site
    if not (prof.get("website") or "").strip():
        recos.append("Add a website URL; ensure content matches high-intent services and service areas.")
    if not (prof.get("phone") or "").strip():
        recos.append("Verify the call tracking number is correct and recording (if applicable).")

    # MCC hint for lead fetching at scale
    if not (prof.get("manager_id") or ""):
        recos.append("No manager_customer_id found. Set one to fetch GLSA leads at scale (MCC).")

    if not recos:
        recos.append("Looks solid! Next: test specialty categories, structured hours, and budget pacing.")

    return jsonify({"ok": True, "recommendations": recos})


@glsa_bp.route("/leads", methods=["GET"], endpoint="leads_page")
@login_required
def leads_page():
    """Leads page (sample leads if not connected)."""
    aid = current_account_id()
    connected = _has_any_google_token(aid, ("lsa", "ads"))
    ctx = _ads_ctx(aid)
    leads = SAMPLE_LEADS if not connected else None
    acct = {"manager_id": ctx.get("login_customer_id"), "customer_id": ctx.get("customer_id")}
    return render_template(
        "glsa/leads.html",
        connected=connected,
        leads=leads,
        acct=acct,
        epn=request.endpoint,
        SECTION="glsa",
    )


# 🔧 Alias to satisfy templates that link to 'glsa_bp.leads'
@glsa_bp.route("/leads/", methods=["GET"], endpoint="leads")
@login_required
def leads_alias():
    return redirect(url_for("glsa_bp.leads_page"))


@glsa_bp.route("/leads/api", methods=["GET"], endpoint="leads_api")
@login_required
def leads_api():
    """Server-side proxy to GLSA detailedLeadReports:search."""
    aid = current_account_id()
    try:
        access_token, used_product = ensure_access_token(aid, products=("lsa", "ads"))
    except Exception as e:
        current_app.logger.exception("GLSA token error")
        return jsonify({"ok": False, "error": f"token_unavailable: {e}"}), 401

    # manager_customer_id (MCC) is required by GLSA API
    mgr = (request.args.get("manager_customer_id") or "").strip()
    if not mgr:
        ctx = _ads_ctx(aid)
        mgr = (ctx.get("login_customer_id") or "").strip()
    if not mgr:
        return jsonify({"ok": False, "error": "missing_manager_customer_id"}), 400

    cust = (request.args.get("customer_id") or "").strip()

    try:
        page_size = min(int(request.args.get("page_size", 1000)), 10000)
    except Exception:
        page_size = 1000
    page_token = request.args.get("page_token")

    # Default to current month to today
    today = date.today()
    start_str = request.args.get("start")
    end_str = request.args.get("end")
    if start_str:
        try:
            y1, m1, d1 = (int(x) for x in start_str.split("-"))
        except Exception:
            y1, m1, d1 = today.year, today.month, 1
    else:
        y1, m1, d1 = today.year, today.month, 1
    if end_str:
        try:
            y2, m2, d2 = (int(x) for x in end_str.split("-"))
        except Exception:
            y2, m2, d2 = today.year, today.month, today.day
    else:
        y2, m2, d2 = today.year, today.month, today.day

    q = f"manager_customer_id:{mgr}"
    if cust:
        q += f";customer_id:{cust}"

    params = {
        "query": q,
        "startDate.year": y1,
        "startDate.month": m1,
        "startDate.day": d1,
        "endDate.year": y2,
        "endDate.month": m2,
        "endDate.day": d2,
        "pageSize": page_size,
    }
    if page_token:
        params["pageToken"] = page_token

    url = f"{API_BASE}/detailedLeadReports:search"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }

    try:
        r = requests.get(url, headers=headers, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
    except requests.HTTPError as e:
        current_app.logger.exception("GLSA leads request failed")
        hint = None
        if e.response is not None and e.response.status_code == 403:
            hint = (
                "403 Forbidden: verify the Google account has access to GLSA under the MCC, "
                "and that the Ads OAuth scope was granted. Double-check manager_customer_id."
            )
        return jsonify({"ok": False, "error": f"glsa_api_error: {e}", "hint": hint}), 502
    except Exception as e:
        current_app.logger.exception("GLSA leads request failed (network/unknown)")
        return jsonify({"ok": False, "error": f"glsa_api_error: {e}"}), 502

    return jsonify({"ok": True, "source_product": used_product, "params": params, "data": data})


@glsa_bp.route("/optimize/insights.json", methods=["POST"], endpoint="optimize_insights_json")
@login_required
def optimize_insights_json():
    """Generate AI-powered optimization insights for LSA profile."""
    aid = current_account_id()

    try:
        payload = request.get_json(force=True) or {}
    except Exception:
        return jsonify({"ok": False, "error": "invalid_json"}), 400

    profile_data = payload.get("profile") or {}
    regenerate = bool(payload.get("regenerate", False))

    # Import insights service
    from app.services.glsa_insights import generate_glsa_insights

    try:
        insights = generate_glsa_insights(aid, profile_data, regenerate=regenerate)
        return jsonify(insights)
    except Exception as e:
        current_app.logger.exception("Error generating GLSA insights")
        return jsonify({
            "ok": False,
            "error": str(e),
            "summary": "Failed to generate insights.",
            "recommendations": []
        }), 500


@glsa_bp.route("/optimize/apply-recommendation", methods=["POST"], endpoint="optimize_apply_recommendation")
@login_required
def optimize_apply_recommendation():
    """Apply a GLSA recommendation."""
    aid = current_account_id()

    try:
        payload = request.get_json(force=True) or {}
    except Exception:
        return jsonify({"ok": False, "error": "invalid_json"}), 400

    recommendation_id = payload.get("recommendation_id")
    if not recommendation_id:
        return jsonify({"ok": False, "error": "recommendation_id required"}), 400

    # Import insights service
    from app.services.glsa_insights import apply_glsa_recommendation
    from app.auth.utils import current_user_id

    user_id = current_user_id()

    try:
        result = apply_glsa_recommendation(aid, recommendation_id, user_id)
        return jsonify(result)
    except Exception as e:
        current_app.logger.exception("Error applying GLSA recommendation")
        return jsonify({"ok": False, "error": str(e)}), 500


@glsa_bp.route("/optimize/dismiss-recommendation", methods=["POST"], endpoint="optimize_dismiss_recommendation")
@login_required
def optimize_dismiss_recommendation():
    """Dismiss a GLSA recommendation."""
    aid = current_account_id()

    try:
        payload = request.get_json(force=True) or {}
    except Exception:
        return jsonify({"ok": False, "error": "invalid_json"}), 400

    recommendation_id = payload.get("recommendation_id")
    if not recommendation_id:
        return jsonify({"ok": False, "error": "recommendation_id required"}), 400

    reason = payload.get("reason")

    # Import insights service
    from app.services.glsa_insights import dismiss_glsa_recommendation
    from app.auth.utils import current_user_id

    user_id = current_user_id()

    try:
        result = dismiss_glsa_recommendation(aid, recommendation_id, user_id, reason)
        return jsonify(result)
    except Exception as e:
        current_app.logger.exception("Error dismissing GLSA recommendation")
        return jsonify({"ok": False, "error": str(e)}), 500
