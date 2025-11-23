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
    """Redirect to main dashboard."""
    return redirect(url_for("glsa_bp.dashboard"))


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


# ───────────────────────── Dashboard Data ─────────────────────────

@glsa_bp.route("/dashboard", methods=["GET"], endpoint="dashboard")
@login_required
def dashboard():
    """Main LSA dashboard with performance metrics."""
    aid = current_account_id()
    connected = _has_any_google_token(aid, ("lsa", "ads"))
    ctx = _ads_ctx(aid)

    # Fetch metrics (real or demo)
    metrics = _get_lsa_metrics(aid, connected)
    opportunities = _get_lsa_opportunities(aid)

    return render_template(
        "glsa/dashboard.html",
        connected=connected,
        ctx=ctx,
        metrics=metrics,
        opportunities=opportunities,
        epn=request.endpoint,
        SECTION="glsa",
    )


@glsa_bp.route("/api/metrics", methods=["GET"], endpoint="api_metrics")
@login_required
def api_metrics():
    """API endpoint for LSA performance metrics."""
    aid = current_account_id()
    connected = _has_any_google_token(aid, ("lsa", "ads"))
    metrics = _get_lsa_metrics(aid, connected)
    return jsonify({"ok": True, "metrics": metrics})


def _get_lsa_metrics(aid: int, connected: bool) -> dict:
    """
    Fetch LSA performance metrics for the dashboard.
    Returns real data if connected, demo data otherwise.
    """
    if not connected:
        # Demo data for unconnected accounts
        return {
            "is_demo": True,
            "period": "Last 30 days",
            "leads": {
                "total": 47,
                "calls": 32,
                "messages": 15,
                "booked": 28,
                "booking_rate": 59.6,
            },
            "spend": {
                "total": 1840.00,
                "cost_per_lead": 39.15,
                "cost_per_booked": 65.71,
                "weekly_budget": 500.00,
                "budget_utilization": 92,
            },
            "performance": {
                "grade": "B",
                "grade_color": "green",
                "score": 72,
                "response_time_avg": "8 min",
                "response_time_score": 85,
                "review_rating": 4.6,
                "review_count": 112,
                "review_score": 78,
            },
            "trends": {
                "leads_change": 12,
                "cpl_change": -8,
                "booking_rate_change": 5,
            },
            "lead_types": [
                {"type": "Emergency", "count": 18, "pct": 38, "cpl": 52.00},
                {"type": "Scheduled", "count": 21, "pct": 45, "cpl": 31.00},
                {"type": "Quote Request", "count": 8, "pct": 17, "cpl": 35.00},
            ],
            "top_services": [
                {"name": "Water Heater Install", "leads": 14, "booked": 9, "revenue": 4200},
                {"name": "Drain Clearing", "leads": 12, "booked": 8, "revenue": 1600},
                {"name": "Leak Repair", "leads": 11, "booked": 7, "revenue": 2100},
                {"name": "Pipe Repair", "leads": 10, "booked": 4, "revenue": 1800},
            ],
            "issues": [
                {"type": "warning", "title": "Response Time Opportunity", "desc": "6 leads had >15min response time. Faster responses convert 40% better."},
                {"type": "info", "title": "Review Volume", "desc": "You have 112 reviews. Top competitors average 180+ reviews."},
                {"type": "success", "title": "Budget Efficiency", "desc": "Your CPL is 18% below industry average. Good budget management."},
            ],
        }

    # Connected - fetch real data from API or database
    try:
        # Try to get leads from database first
        from app.models_glsa import GLSALead, GLSAProfile
        from datetime import datetime, timedelta

        thirty_days_ago = datetime.utcnow() - timedelta(days=30)

        leads = GLSALead.query.filter(
            GLSALead.account_id == aid,
            GLSALead.lead_ts >= thirty_days_ago
        ).all()

        profile = GLSAProfile.query.filter(
            GLSAProfile.account_id == aid
        ).order_by(GLSAProfile.updated_at.desc()).first()

        total_leads = len(leads)
        # Estimate calls vs messages (typically 70/30 split for LSA)
        calls = int(total_leads * 0.7)
        messages = total_leads - calls

        # Calculate booked (estimate from status if available)
        booked = sum(1 for l in leads if l.notes and isinstance(l.notes, dict) and l.notes.get('status') == 'booked')
        if booked == 0:
            booked = int(total_leads * 0.6)  # Default estimate

        booking_rate = (booked / total_leads * 100) if total_leads > 0 else 0

        # Get spend data from notes/charges
        total_spend = sum(
            float(l.notes.get('charged_price', {}).get('units', 0))
            for l in leads
            if l.notes and isinstance(l.notes, dict) and l.notes.get('charged_price')
        )
        if total_spend == 0:
            total_spend = total_leads * 45  # Default estimate

        cpl = total_spend / total_leads if total_leads > 0 else 0
        cpb = total_spend / booked if booked > 0 else 0

        weekly_budget = profile.suggestions.get('weekly_budget', 500) if profile and profile.suggestions else 500

        # Calculate grade
        score = 50
        if booking_rate >= 60:
            score += 20
        elif booking_rate >= 40:
            score += 10
        if cpl <= 40:
            score += 15
        elif cpl <= 60:
            score += 8
        if profile and profile.rating and profile.rating >= 4.5:
            score += 15
        elif profile and profile.rating and profile.rating >= 4.0:
            score += 8

        grade = "A" if score >= 85 else "B" if score >= 70 else "C" if score >= 55 else "D"
        grade_color = "green" if grade in ("A", "B") else "yellow" if grade == "C" else "red"

        return {
            "is_demo": False,
            "period": "Last 30 days",
            "leads": {
                "total": total_leads,
                "calls": calls,
                "messages": messages,
                "booked": booked,
                "booking_rate": round(booking_rate, 1),
            },
            "spend": {
                "total": round(total_spend, 2),
                "cost_per_lead": round(cpl, 2),
                "cost_per_booked": round(cpb, 2),
                "weekly_budget": weekly_budget,
                "budget_utilization": min(100, int((total_spend / 4) / weekly_budget * 100)) if weekly_budget else 0,
            },
            "performance": {
                "grade": grade,
                "grade_color": grade_color,
                "score": score,
                "response_time_avg": "N/A",
                "response_time_score": 70,
                "review_rating": profile.rating if profile else 0,
                "review_count": profile.review_count if profile else 0,
                "review_score": int((profile.rating / 5 * 100)) if profile and profile.rating else 0,
            },
            "trends": {
                "leads_change": 0,
                "cpl_change": 0,
                "booking_rate_change": 0,
            },
            "lead_types": [],
            "top_services": [],
            "issues": [],
        }
    except Exception as e:
        current_app.logger.exception(f"Error fetching LSA metrics: {e}")
        return _get_lsa_metrics(aid, False)  # Fall back to demo data


def _get_lsa_opportunities(aid: int) -> list:
    """Fetch optimization opportunities for the account."""
    try:
        from app.models_ads import OptimizerRecommendation

        recommendations = OptimizerRecommendation.query.filter(
            OptimizerRecommendation.account_id == aid,
            OptimizerRecommendation.source_type == 'glsa',
            OptimizerRecommendation.status == 'open'
        ).order_by(
            OptimizerRecommendation.severity.asc()
        ).limit(5).all()

        return [
            {
                "id": r.id,
                "title": r.title,
                "description": r.description,
                "category": r.category,
                "severity": r.severity,
                "impact": r.expected_impact,
            }
            for r in recommendations
        ]
    except Exception:
        return []
