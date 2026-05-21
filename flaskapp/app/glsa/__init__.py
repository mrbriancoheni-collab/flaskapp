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


def _get_selected_glsa_account(aid: int) -> dict:
    """Get the selected Google Ads account for GLSA"""
    try:
        with db.engine.connect() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT customer_id, customer_name, login_customer_id
                    FROM glsa_selected_accounts
                    WHERE account_id = :aid
                    LIMIT 1
                    """
                ),
                {"aid": aid}
            ).fetchone()

            if row:
                return {
                    "customer_id": row[0],
                    "customer_name": row[1],
                    "login_customer_id": row[2]
                }
    except Exception as e:
        current_app.logger.debug("No selected GLSA account found: %s", e)

    return {"customer_id": None, "customer_name": None, "login_customer_id": None}


def _save_selected_glsa_account(aid: int, customer_id: str, customer_name: str, login_customer_id: str = None):
    """Save the selected Google Ads account for GLSA"""
    try:
        with db.engine.connect() as conn:
            # Create table if not exists
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS glsa_selected_accounts (
                        account_id BIGINT NOT NULL PRIMARY KEY,
                        customer_id VARCHAR(50) NOT NULL,
                        customer_name VARCHAR(255),
                        login_customer_id VARCHAR(50),
                        created_at DATETIME NOT NULL,
                        updated_at DATETIME NOT NULL
                    )
                    """
                )
            )
            conn.commit()

            # Insert or update selection
            conn.execute(
                text(
                    """
                    INSERT INTO glsa_selected_accounts
                    (account_id, customer_id, customer_name, login_customer_id, created_at, updated_at)
                    VALUES (:aid, :cid, :cname, :lcid, NOW(), NOW())
                    ON DUPLICATE KEY UPDATE
                        customer_id = VALUES(customer_id),
                        customer_name = VALUES(customer_name),
                        login_customer_id = VALUES(login_customer_id),
                        updated_at = NOW()
                    """
                ),
                {
                    "aid": aid,
                    "cid": customer_id,
                    "cname": customer_name,
                    "lcid": login_customer_id
                }
            )
            conn.commit()

        current_app.logger.info("Saved GLSA account selection for account %s: %s", aid, customer_id)
    except Exception as e:
        current_app.logger.exception("Failed to save selected GLSA account: %s", e)


def _ads_ctx(aid: int, include_profile: bool = False) -> dict:
    """Resolve Ads context (customer_id + optional login_customer_id). Include a template-safe profile key."""
    # First check if user has manually selected an account
    selected = _get_selected_glsa_account(aid)
    if selected and selected.get("customer_id"):
        ctx = {
            "customer_id": selected["customer_id"],
            "login_customer_id": selected.get("login_customer_id"),
            "customer_name": selected.get("customer_name")
        }
    else:
        # Fall back to automatic context resolution
        try:
            ctx = resolve_ads_context(aid) or {"customer_id": None, "login_customer_id": None}
        except Exception as e:
            current_app.logger.warning("resolve_ads_context error: %s", e)
            ctx = {"customer_id": None, "login_customer_id": None}

    # Load profile from database if requested
    profile_data = {}
    if include_profile:
        try:
            from app.models_glsa import GLSAProfile
            profile = GLSAProfile.query.filter_by(account_id=aid).order_by(GLSAProfile.updated_at.desc()).first()
            if profile:
                # Map database fields to template expected fields
                categories = profile.categories or []
                primary_cat = categories[0] if categories else ""
                other_cats = categories[1:] if len(categories) > 1 else []

                # Parse service_areas - could be list of dicts or strings
                service_areas_raw = profile.service_areas or []
                service_areas = []
                for sa in service_areas_raw:
                    if isinstance(sa, dict):
                        service_areas.append(sa.get("zip") or sa.get("city") or str(sa))
                    else:
                        service_areas.append(str(sa))

                # Parse hours - could be dict or string
                hours_raw = profile.hours
                if isinstance(hours_raw, dict):
                    hours = "; ".join([f"{k} {v}" for k, v in hours_raw.items()])
                else:
                    hours = hours_raw or ""

                profile_data = {
                    "name": profile.business_name,
                    "primary_category": primary_cat,
                    "categories": other_cats,
                    "service_areas": service_areas,
                    "hours": hours,
                    "phone": profile.phone,
                    "website": profile.website,
                    "rating": profile.rating,
                    "reviews_count": profile.review_count,
                    "weekly_budget": None,  # Not stored in profile model yet
                    "last_synced_at": profile.last_synced_at.isoformat() if profile.last_synced_at else None,
                }
        except Exception as e:
            current_app.logger.warning("Error loading GLSA profile: %s", e)

    ctx["profile"] = profile_data
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


@glsa_bp.get("/select-account", endpoint="select_account")
@login_required
def select_account():
    """Page to select Google Ads account for Local Services Ads"""
    aid = current_account_id()
    connected = _has_any_google_token(aid, ("lsa", "ads"))

    if not connected:
        flash("Please connect your Google account first.", "warning")
        return redirect(url_for("glsa_bp.connect"))

    # Get available accounts from Google Ads
    # For now, we'll use the automatically resolved context
    # In a full implementation, this would call Google Ads API to list accessible accounts
    ctx = {}
    try:
        ctx = resolve_ads_context(aid) or {}
    except Exception as e:
        current_app.logger.warning("resolve_ads_context error: %s", e)

    # For demo purposes, create a list with the current account
    # In production, you'd fetch all accessible accounts via Google Ads API
    available_accounts = []
    if ctx.get("customer_id"):
        available_accounts.append({
            "customer_id": ctx["customer_id"],
            "customer_name": f"Google Ads Account {ctx['customer_id'][-4:]}",
            "login_customer_id": ctx.get("login_customer_id")
        })

    # Get currently selected account
    selected = _get_selected_glsa_account(aid)

    # Skip selection page when exactly one account is available
    if len(available_accounts) == 1 and not selected:
        acc = available_accounts[0]
        _save_selected_glsa_account(
            aid,
            acc["customer_id"],
            acc["customer_name"],
            acc.get("login_customer_id"),
        )
        return redirect(url_for("glsa_bp.dashboard"))

    return render_template(
        "glsa/select_account.html",
        connected=connected,
        available_accounts=available_accounts,
        selected=selected,
        ctx=ctx
    )


@glsa_bp.post("/select-account", endpoint="select_account_post")
@login_required
def select_account_post():
    """Save selected Google Ads account for GLSA"""
    aid = current_account_id()

    customer_id = request.form.get("customer_id", "").strip()
    customer_name = request.form.get("customer_name", "").strip()
    login_customer_id = request.form.get("login_customer_id", "").strip() or None

    if not customer_id:
        flash("Please select a Google Ads account.", "error")
        return redirect(url_for("glsa_bp.select_account"))

    _save_selected_glsa_account(aid, customer_id, customer_name, login_customer_id)
    flash("Account selection saved successfully!", "success")

    return redirect(url_for("glsa_bp.dashboard"))


@glsa_bp.get("/optimize", endpoint="optimize")
@login_required
def optimize():
    aid = current_account_id()
    connected = _has_any_google_token(aid, ("lsa", "ads"))
    ctx = _ads_ctx(aid, include_profile=True)

    # Check if sync is needed (no data or stale > 7 days)
    needs_sync = False
    if connected:
        from app.models_glsa import GLSAProfile
        from datetime import datetime, timedelta
        profile = GLSAProfile.query.filter_by(account_id=aid).first()
        if not profile or not profile.last_synced_at:
            needs_sync = True
        elif profile.last_synced_at < datetime.utcnow() - timedelta(days=7):
            needs_sync = True

    return render_template(
        "glsa/optimize.html",
        connected=connected,
        ctx=ctx,
        needs_sync=needs_sync,
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


# ───────────────────────── Data Sync & Historical Pull ─────────────────────────

@glsa_bp.route("/sync", methods=["POST"], endpoint="sync_data")
@login_required
def sync_data():
    """
    Sync LSA data from Google API to local database.
    Pulls leads from the last year (or specified period) and stores them.
    """
    aid = current_account_id()

    try:
        access_token, used_product = ensure_access_token(aid, products=("lsa", "ads"))
    except Exception as e:
        current_app.logger.exception("GLSA token error during sync")
        return jsonify({"ok": False, "error": f"token_unavailable: {e}"}), 401

    ctx = _ads_ctx(aid)
    mgr = (ctx.get("login_customer_id") or "").strip()
    cust = (ctx.get("customer_id") or "").strip()

    if not mgr:
        return jsonify({"ok": False, "error": "missing_manager_customer_id"}), 400

    # Get sync parameters
    try:
        payload = request.get_json(force=True) or {}
    except Exception:
        payload = {}

    months_back = int(payload.get("months", 12))  # Default 12 months (1 year)
    force_full = payload.get("force_full", False)

    # Calculate date range
    today = date.today()
    start_date = today - timedelta(days=months_back * 30)

    result = _sync_leads_from_api(
        aid=aid,
        access_token=access_token,
        manager_id=mgr,
        customer_id=cust,
        start_date=start_date,
        end_date=today,
        force_full=force_full
    )

    return jsonify(result)


def _update_profile_from_leads(aid: int, glsa_account_id: int) -> bool:
    """
    Build/update a GLSAProfile from the synced leads data.
    Extracts categories (job types), service areas (cities), and phone from leads.
    """
    from app.models_glsa import GLSALead, GLSAProfile
    from datetime import datetime
    from sqlalchemy import func

    try:
        # Get unique job types (categories) from leads
        job_types = db.session.query(GLSALead.job_type)\
            .filter(GLSALead.glsa_account_id == glsa_account_id)\
            .filter(GLSALead.job_type.isnot(None))\
            .filter(GLSALead.job_type != "")\
            .distinct().all()
        categories = [jt[0] for jt in job_types if jt[0]]

        # Get unique cities (service areas) from leads
        cities = db.session.query(GLSALead.city)\
            .filter(GLSALead.glsa_account_id == glsa_account_id)\
            .filter(GLSALead.city.isnot(None))\
            .filter(GLSALead.city != "")\
            .distinct().all()
        service_areas = [c[0] for c in cities if c[0]]

        # Get phone from the most recent lead with notes containing ad_phone_number
        recent_lead = GLSALead.query\
            .filter(GLSALead.glsa_account_id == glsa_account_id)\
            .filter(GLSALead.notes.isnot(None))\
            .order_by(GLSALead.lead_ts.desc())\
            .first()

        phone = None
        if recent_lead and recent_lead.notes:
            phone = recent_lead.notes.get("ad_phone_number")

        # Get lead count for review count approximation
        lead_count = GLSALead.query\
            .filter(GLSALead.glsa_account_id == glsa_account_id)\
            .count()

        # Get or create profile
        profile = GLSAProfile.query.filter_by(account_id=aid).first()
        if not profile:
            profile = GLSAProfile(
                account_id=aid,
                glsa_account_id=glsa_account_id
            )
            db.session.add(profile)

        # Update profile with extracted data (don't overwrite user-edited fields)
        if categories and not profile.categories:
            profile.categories = categories
        elif categories:
            # Merge new categories
            existing = set(profile.categories or [])
            profile.categories = list(existing.union(set(categories)))

        if service_areas and not profile.service_areas:
            profile.service_areas = service_areas
        elif service_areas:
            # Merge new service areas
            existing = set(profile.service_areas or [])
            profile.service_areas = list(existing.union(set(service_areas)))

        if phone and not profile.phone:
            profile.phone = phone

        profile.last_synced_at = datetime.utcnow()
        db.session.commit()

        current_app.logger.info(f"GLSA profile updated for account {aid}: {len(categories)} categories, {len(service_areas)} areas")
        return True

    except Exception as e:
        current_app.logger.exception(f"Error updating profile from leads: {e}")
        db.session.rollback()
        return False


def _sync_leads_from_api(
    aid: int,
    access_token: str,
    manager_id: str,
    customer_id: str,
    start_date: date,
    end_date: date,
    force_full: bool = False
) -> dict:
    """
    Fetch leads from Google LSA API and store in database.
    Handles pagination and upserts.
    """
    from app.models_glsa import GLSALead, GLSAAccount
    from datetime import datetime

    # Get or create GLSA account
    glsa_account = GLSAAccount.query.filter_by(account_id=aid).first()
    if not glsa_account:
        glsa_account = GLSAAccount(account_id=aid)
        db.session.add(glsa_account)
        db.session.commit()

    total_fetched = 0
    total_new = 0
    total_updated = 0
    errors = []

    # Build query
    q = f"manager_customer_id:{manager_id}"
    if customer_id:
        q += f";customer_id:{customer_id}"

    page_token = None
    page_count = 0
    max_pages = 100  # Safety limit

    while page_count < max_pages:
        params = {
            "query": q,
            "startDate.year": start_date.year,
            "startDate.month": start_date.month,
            "startDate.day": start_date.day,
            "endDate.year": end_date.year,
            "endDate.month": end_date.month,
            "endDate.day": end_date.day,
            "pageSize": 1000,
        }
        if page_token:
            params["pageToken"] = page_token

        url = f"{API_BASE}/detailedLeadReports:search"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        }

        try:
            r = requests.get(url, headers=headers, params=params, timeout=60)
            r.raise_for_status()
            data = r.json()
        except requests.HTTPError as e:
            errors.append(f"API error on page {page_count}: {e}")
            break
        except Exception as e:
            errors.append(f"Network error on page {page_count}: {e}")
            break

        leads_data = data.get("detailedLeadReports", [])
        if not leads_data:
            break

        # Process and store leads
        for lead_data in leads_data:
            total_fetched += 1
            lead_id = lead_data.get("leadId")

            if not lead_id:
                continue

            # Check if lead exists
            existing = GLSALead.query.filter_by(
                glsa_account_id=glsa_account.id,
                lead_id=lead_id
            ).first()

            # Parse lead timestamp
            lead_ts = None
            create_time = lead_data.get("createTime")
            if create_time:
                try:
                    lead_ts = datetime.fromisoformat(create_time.replace("Z", "+00:00"))
                except Exception:
                    pass

            # Extract contact info
            phone = lead_data.get("consumerPhoneNumber", "")
            name = lead_data.get("consumerName", "")
            job_type = lead_data.get("jobType", "")
            location = lead_data.get("location", {})
            city = location.get("city", "")

            # Build notes with all metadata
            notes = {
                "lead_status": lead_data.get("leadStatus"),
                "charged_price": lead_data.get("chargedPrice"),
                "location": location,
                "timezone": lead_data.get("timezone"),
                "ad_phone_number": lead_data.get("adPhoneNumber"),
                "message_type": lead_data.get("messageType"),
                "lead_type": lead_data.get("leadType"),
                "geo": lead_data.get("geo", {}),
                "raw_data": lead_data,
            }

            if existing:
                # Update existing lead
                existing.name = name
                existing.phone = phone
                existing.job_type = job_type
                existing.city = city
                existing.lead_ts = lead_ts
                existing.notes = notes
                total_updated += 1
            else:
                # Create new lead
                new_lead = GLSALead(
                    account_id=aid,
                    glsa_account_id=glsa_account.id,
                    lead_id=lead_id,
                    name=name,
                    phone=phone,
                    job_type=job_type,
                    city=city,
                    lead_ts=lead_ts,
                    notes=notes,
                )
                db.session.add(new_lead)
                total_new += 1

        # Commit batch
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            errors.append(f"Database error: {e}")
            break

        # Check for next page
        page_token = data.get("nextPageToken")
        if not page_token:
            break

        page_count += 1

    # Update sync timestamp
    glsa_account.updated_at = datetime.utcnow()
    db.session.commit()

    # Build/update profile from leads data
    profile_updated = _update_profile_from_leads(aid, glsa_account.id)

    return {
        "ok": len(errors) == 0,
        "total_fetched": total_fetched,
        "new_leads": total_new,
        "updated_leads": total_updated,
        "pages_processed": page_count + 1,
        "errors": errors,
        "period": f"{start_date.isoformat()} to {end_date.isoformat()}",
        "profile_updated": profile_updated,
    }


@glsa_bp.route("/api/sync-status", methods=["GET"], endpoint="sync_status")
@login_required
def sync_status():
    """Get the current sync status and lead counts."""
    aid = current_account_id()
    from app.models_glsa import GLSALead, GLSAAccount
    from datetime import datetime, timedelta

    glsa_account = GLSAAccount.query.filter_by(account_id=aid).first()
    if not glsa_account:
        return jsonify({
            "ok": True,
            "synced": False,
            "total_leads": 0,
            "last_sync": None,
        })

    total_leads = GLSALead.query.filter_by(glsa_account_id=glsa_account.id).count()
    thirty_days = datetime.utcnow() - timedelta(days=30)
    recent_leads = GLSALead.query.filter(
        GLSALead.glsa_account_id == glsa_account.id,
        GLSALead.lead_ts >= thirty_days
    ).count()

    return jsonify({
        "ok": True,
        "synced": True,
        "total_leads": total_leads,
        "recent_leads_30d": recent_leads,
        "last_sync": glsa_account.updated_at.isoformat() if glsa_account.updated_at else None,
    })


# ───────────────────────── LSA Actions (Push Changes) ─────────────────────────

@glsa_bp.route("/api/dispute", methods=["POST"], endpoint="dispute_lead")
@login_required
def dispute_lead():
    """
    Dispute an LSA lead charge.
    Sends dispute request to Google Local Services API.
    """
    aid = current_account_id()

    try:
        payload = request.get_json(force=True) or {}
    except Exception:
        return jsonify({"ok": False, "error": "invalid_json"}), 400

    lead_id = payload.get("lead_id")
    dispute_reason = payload.get("reason", "WRONG_LOCATION")
    dispute_notes = payload.get("notes", "")

    if not lead_id:
        return jsonify({"ok": False, "error": "missing_lead_id"}), 400

    valid_reasons = [
        "WRONG_LOCATION",
        "WRONG_SERVICE",
        "DUPLICATE",
        "NO_CUSTOMER_CONTACT",
        "SPAM",
        "WRONG_BUSINESS",
        "OTHER"
    ]
    if dispute_reason not in valid_reasons:
        return jsonify({"ok": False, "error": f"invalid_reason. Must be one of: {valid_reasons}"}), 400

    try:
        access_token, _ = ensure_access_token(aid, products=("lsa", "ads"))
    except Exception as e:
        return jsonify({"ok": False, "error": f"token_error: {e}"}), 401

    ctx = _ads_ctx(aid)
    mgr = (ctx.get("login_customer_id") or "").strip()

    if not mgr:
        return jsonify({"ok": False, "error": "missing_manager_customer_id"}), 400

    # Call Google API to dispute lead
    # Note: The actual dispute endpoint may vary based on API version
    url = f"{API_BASE}/leadReports/{lead_id}:dispute"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    body = {
        "disputeReason": dispute_reason,
        "notes": dispute_notes,
    }

    try:
        r = requests.post(url, headers=headers, json=body, timeout=30)
        if r.status_code == 404:
            return jsonify({"ok": False, "error": "lead_not_found", "hint": "Lead may have already been disputed or is too old."}), 404
        r.raise_for_status()
        result = r.json() if r.content else {}
    except requests.HTTPError as e:
        current_app.logger.exception(f"LSA dispute failed for lead {lead_id}")
        return jsonify({"ok": False, "error": f"api_error: {e}"}), 502
    except Exception as e:
        return jsonify({"ok": False, "error": f"network_error: {e}"}), 502

    # Update local database
    from app.models_glsa import GLSALead
    lead = GLSALead.query.filter_by(account_id=aid, lead_id=lead_id).first()
    if lead and lead.notes:
        lead.notes["disputed"] = True
        lead.notes["dispute_reason"] = dispute_reason
        lead.notes["dispute_notes"] = dispute_notes
        db.session.commit()

    return jsonify({
        "ok": True,
        "lead_id": lead_id,
        "dispute_reason": dispute_reason,
        "result": result,
    })


@glsa_bp.route("/api/update-budget", methods=["POST"], endpoint="update_budget")
@login_required
def update_budget():
    """
    Update LSA weekly budget.
    Note: Budget updates may require Google Ads API rather than LSA API directly.
    """
    aid = current_account_id()

    try:
        payload = request.get_json(force=True) or {}
    except Exception:
        return jsonify({"ok": False, "error": "invalid_json"}), 400

    new_budget = payload.get("weekly_budget")
    if not new_budget or new_budget <= 0:
        return jsonify({"ok": False, "error": "invalid_budget"}), 400

    try:
        access_token, _ = ensure_access_token(aid, products=("lsa", "ads"))
    except Exception as e:
        return jsonify({"ok": False, "error": f"token_error: {e}"}), 401

    ctx = _ads_ctx(aid)
    customer_id = (ctx.get("customer_id") or "").strip()

    if not customer_id:
        return jsonify({"ok": False, "error": "missing_customer_id"}), 400

    # LSA budget is typically managed through Google Ads API
    # Using the Google Ads API to update the budget
    try:
        from google.ads.googleads.client import GoogleAdsClient
        import os

        # Build client configuration
        config = {
            "developer_token": os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN"),
            "client_id": os.getenv("GOOGLE_ADS_CLIENT_ID") or current_app.config.get("GOOGLE_ADS_CLIENT_ID"),
            "client_secret": os.getenv("GOOGLE_ADS_CLIENT_SECRET") or current_app.config.get("GOOGLE_ADS_CLIENT_SECRET"),
            "refresh_token": None,  # Will use access_token instead
            "use_proto_plus": True,
            "login_customer_id": ctx.get("login_customer_id", "").replace("-", ""),
        }

        # For LSA, budget updates go through the account-level budget settings
        # This is a simplified implementation - full implementation would use
        # the Google Ads API CampaignBudget service

        # Store the budget preference locally
        from app.models_glsa import GLSAProfile
        profile = GLSAProfile.query.filter_by(account_id=aid).first()
        if not profile:
            from app.models_glsa import GLSAAccount
            glsa_account = GLSAAccount.query.filter_by(account_id=aid).first()
            if not glsa_account:
                glsa_account = GLSAAccount(account_id=aid)
                db.session.add(glsa_account)
                db.session.commit()

            profile = GLSAProfile(
                account_id=aid,
                glsa_account_id=glsa_account.id,
            )
            db.session.add(profile)

        if not profile.suggestions:
            profile.suggestions = {}
        profile.suggestions["weekly_budget"] = float(new_budget)
        db.session.commit()

        return jsonify({
            "ok": True,
            "weekly_budget": new_budget,
            "note": "Budget preference saved. To apply to Google Ads, use the Google Ads interface or API.",
        })

    except ImportError:
        # Google Ads library not available, just store locally
        from app.models_glsa import GLSAProfile, GLSAAccount
        profile = GLSAProfile.query.filter_by(account_id=aid).first()
        if not profile:
            glsa_account = GLSAAccount.query.filter_by(account_id=aid).first()
            if not glsa_account:
                glsa_account = GLSAAccount(account_id=aid)
                db.session.add(glsa_account)
                db.session.commit()
            profile = GLSAProfile(account_id=aid, glsa_account_id=glsa_account.id)
            db.session.add(profile)

        if not profile.suggestions:
            profile.suggestions = {}
        profile.suggestions["weekly_budget"] = float(new_budget)
        db.session.commit()

        return jsonify({
            "ok": True,
            "weekly_budget": new_budget,
            "note": "Budget preference saved locally. Google Ads API integration required for live updates.",
        })
    except Exception as e:
        current_app.logger.exception(f"Budget update error: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


@glsa_bp.route("/api/update-profile", methods=["POST"], endpoint="update_profile")
@login_required
def update_profile():
    """
    Update LSA profile settings (categories, service areas, hours, etc.).
    Stores locally and can be pushed to Google via API.
    """
    aid = current_account_id()

    try:
        payload = request.get_json(force=True) or {}
    except Exception:
        return jsonify({"ok": False, "error": "invalid_json"}), 400

    from app.models_glsa import GLSAProfile, GLSAAccount
    from datetime import datetime

    # Get or create profile
    profile = GLSAProfile.query.filter_by(account_id=aid).first()
    if not profile:
        glsa_account = GLSAAccount.query.filter_by(account_id=aid).first()
        if not glsa_account:
            glsa_account = GLSAAccount(account_id=aid)
            db.session.add(glsa_account)
            db.session.commit()

        profile = GLSAProfile(
            account_id=aid,
            glsa_account_id=glsa_account.id,
        )
        db.session.add(profile)

    # Update profile fields
    if "business_name" in payload:
        profile.business_name = payload["business_name"]
    if "phone" in payload:
        profile.phone = payload["phone"]
    if "email" in payload:
        profile.email = payload["email"]
    if "website" in payload:
        profile.website = payload["website"]
    if "categories" in payload:
        profile.categories = payload["categories"]
    if "service_areas" in payload:
        profile.service_areas = payload["service_areas"]
    if "description" in payload:
        profile.description = payload["description"]
    if "hours" in payload:
        profile.hours = payload["hours"]

    profile.updated_at = datetime.utcnow()

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({"ok": False, "error": f"database_error: {e}"}), 500

    # Optionally push to Google API
    push_to_google = payload.get("push_to_google", False)
    push_result = None

    if push_to_google:
        push_result = _push_profile_to_google(aid, profile)

    return jsonify({
        "ok": True,
        "profile_id": profile.id,
        "updated_fields": list(payload.keys()),
        "push_result": push_result,
    })


def _push_profile_to_google(aid: int, profile) -> dict:
    """
    Push profile changes to Google Local Services.
    Note: This requires the Local Services API write permissions.
    """
    try:
        access_token, _ = ensure_access_token(aid, products=("lsa", "ads"))
    except Exception as e:
        return {"ok": False, "error": f"token_error: {e}"}

    ctx = _ads_ctx(aid)
    mgr = (ctx.get("login_customer_id") or "").strip()

    if not mgr:
        return {"ok": False, "error": "missing_manager_customer_id"}

    # The Local Services API profile update endpoint
    # Note: Actual endpoint structure depends on Google's API version
    # This is a placeholder that would need to be adjusted based on actual API docs

    # For now, return a note that manual update is required
    return {
        "ok": True,
        "note": "Profile saved locally. Use Google Local Services dashboard to push changes.",
        "fields_to_update": {
            "business_name": profile.business_name,
            "categories": profile.categories,
            "service_areas": profile.service_areas,
            "hours": profile.hours,
        }
    }


# ───────────────────────── Live Analysis ─────────────────────────

@glsa_bp.route("/api/analyze", methods=["POST"], endpoint="analyze")
@login_required
def analyze():
    """
    Run live analysis on synced LSA data.
    Generates insights and recommendations based on stored leads.
    """
    aid = current_account_id()

    try:
        payload = request.get_json(force=True) or {}
    except Exception:
        payload = {}

    regenerate = payload.get("regenerate", False)
    analysis = _run_lsa_analysis(aid, regenerate=regenerate)

    return jsonify(analysis)


def _run_lsa_analysis(aid: int, regenerate: bool = False) -> dict:
    """
    Analyze stored LSA data and generate insights.
    """
    from app.models_glsa import GLSALead, GLSAProfile
    from datetime import datetime, timedelta
    from collections import defaultdict

    # Get leads from last 90 days for analysis
    ninety_days = datetime.utcnow() - timedelta(days=90)
    leads = GLSALead.query.filter(
        GLSALead.account_id == aid,
        GLSALead.lead_ts >= ninety_days
    ).all()

    if not leads:
        return {
            "ok": True,
            "has_data": False,
            "message": "No leads found. Please sync your data first.",
            "insights": [],
            "recommendations": [],
        }

    # Calculate metrics
    total_leads = len(leads)
    total_spend = 0
    job_types = defaultdict(int)
    cities = defaultdict(int)
    statuses = defaultdict(int)
    monthly_leads = defaultdict(int)

    for lead in leads:
        # Count job types
        if lead.job_type:
            job_types[lead.job_type] += 1

        # Count cities
        if lead.city:
            cities[lead.city] += 1

        # Count statuses
        if lead.notes and isinstance(lead.notes, dict):
            status = lead.notes.get("lead_status", "UNKNOWN")
            statuses[status] += 1

            # Sum spend
            charged = lead.notes.get("charged_price", {})
            if charged:
                try:
                    total_spend += float(charged.get("units", 0))
                except Exception:
                    pass

        # Monthly breakdown
        if lead.lead_ts:
            month_key = lead.lead_ts.strftime("%Y-%m")
            monthly_leads[month_key] += 1

    # Calculate CPL
    cpl = total_spend / total_leads if total_leads > 0 else 0

    # Get profile for context
    profile = GLSAProfile.query.filter_by(account_id=aid).first()
    rating = profile.rating if profile else None
    review_count = profile.review_count if profile else 0

    # Generate insights
    insights = []

    # Lead volume insight
    avg_monthly = total_leads / 3  # 90 days = ~3 months
    insights.append({
        "type": "metric",
        "title": "Lead Volume",
        "value": f"{total_leads} leads in 90 days",
        "detail": f"Average {avg_monthly:.0f} leads/month",
    })

    # CPL insight
    industry_avg_cpl = 50  # Industry average for comparison
    cpl_status = "good" if cpl < industry_avg_cpl else "warning" if cpl < industry_avg_cpl * 1.3 else "bad"
    insights.append({
        "type": "metric",
        "title": "Cost Per Lead",
        "value": f"${cpl:.2f}",
        "status": cpl_status,
        "detail": f"Industry avg: ${industry_avg_cpl}",
    })

    # Top services insight
    top_services = sorted(job_types.items(), key=lambda x: x[1], reverse=True)[:5]
    insights.append({
        "type": "breakdown",
        "title": "Top Services",
        "items": [{"name": k, "count": v, "pct": round(v / total_leads * 100, 1)} for k, v in top_services],
    })

    # Top locations insight
    top_cities = sorted(cities.items(), key=lambda x: x[1], reverse=True)[:5]
    insights.append({
        "type": "breakdown",
        "title": "Top Locations",
        "items": [{"name": k, "count": v, "pct": round(v / total_leads * 100, 1)} for k, v in top_cities],
    })

    # Generate recommendations
    recommendations = []

    # CPL recommendation
    if cpl > industry_avg_cpl * 1.2:
        recommendations.append({
            "severity": 2,
            "category": "budget",
            "title": "High Cost Per Lead",
            "description": f"Your CPL (${cpl:.2f}) is {((cpl / industry_avg_cpl - 1) * 100):.0f}% above industry average. Consider optimizing your service areas or categories.",
            "action": "Review service areas and remove low-converting locations.",
        })

    # Review recommendation
    if review_count < 50:
        recommendations.append({
            "severity": 2,
            "category": "reviews",
            "title": "Increase Review Count",
            "description": f"You have {review_count} reviews. Businesses with 50+ reviews get 30% more leads.",
            "action": "Implement a review request campaign after completed jobs.",
        })

    # Rating recommendation
    if rating and rating < 4.5:
        recommendations.append({
            "severity": 1,
            "category": "reviews",
            "title": "Improve Rating",
            "description": f"Your {rating:.1f} rating is below the 4.5 target. Higher ratings significantly improve lead share.",
            "action": "Focus on service quality and follow up with dissatisfied customers.",
        })

    # Service diversification
    if len(job_types) < 3:
        recommendations.append({
            "severity": 3,
            "category": "categories",
            "title": "Expand Service Categories",
            "description": "Consider adding more service categories to capture a wider range of leads.",
            "action": "Add 2-3 additional relevant service categories to your profile.",
        })

    # Geographic expansion
    if len(cities) < 5:
        recommendations.append({
            "severity": 3,
            "category": "service_areas",
            "title": "Expand Service Areas",
            "description": "You're receiving leads from limited locations. Expanding coverage could increase volume.",
            "action": "Add neighboring cities/zip codes to your service areas.",
        })

    return {
        "ok": True,
        "has_data": True,
        "period": "Last 90 days",
        "summary": {
            "total_leads": total_leads,
            "total_spend": round(total_spend, 2),
            "cost_per_lead": round(cpl, 2),
            "monthly_average": round(avg_monthly, 1),
        },
        "insights": insights,
        "recommendations": recommendations,
        "monthly_breakdown": dict(sorted(monthly_leads.items())),
    }


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
    Uses stored database data when available, falls back to demo data.
    """
    from app.models_glsa import GLSALead, GLSAProfile, GLSAAccount
    from datetime import datetime, timedelta
    from collections import defaultdict

    # Check if we have synced data
    glsa_account = GLSAAccount.query.filter_by(account_id=aid).first()
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)

    if glsa_account:
        total_leads_db = GLSALead.query.filter(
            GLSALead.glsa_account_id == glsa_account.id,
            GLSALead.lead_ts >= thirty_days_ago
        ).count()
    else:
        total_leads_db = 0

    # If we have real synced data, use it
    if total_leads_db > 0:
        leads = GLSALead.query.filter(
            GLSALead.glsa_account_id == glsa_account.id,
            GLSALead.lead_ts >= thirty_days_ago
        ).all()

        profile = GLSAProfile.query.filter_by(account_id=aid).first()

        # Calculate real metrics from database
        total_leads = len(leads)
        total_spend = 0
        booked = 0
        job_types = defaultdict(lambda: {"count": 0, "spend": 0})
        lead_types_data = defaultdict(lambda: {"count": 0, "spend": 0})

        for lead in leads:
            if lead.notes and isinstance(lead.notes, dict):
                # Get spend
                charged = lead.notes.get("charged_price", {})
                if charged:
                    try:
                        amount = float(charged.get("units", 0))
                        total_spend += amount
                        if lead.job_type:
                            job_types[lead.job_type]["spend"] += amount
                    except Exception:
                        pass

                # Count booked
                status = lead.notes.get("lead_status", "")
                if status in ("BOOKED", "ACTIVE"):
                    booked += 1

                # Lead type breakdown
                lead_type = lead.notes.get("lead_type", "PHONE_CALL")
                lead_types_data[lead_type]["count"] += 1
                if charged:
                    try:
                        lead_types_data[lead_type]["spend"] += float(charged.get("units", 0))
                    except Exception:
                        pass

            if lead.job_type:
                job_types[lead.job_type]["count"] += 1

        # Estimate calls vs messages
        calls = lead_types_data.get("PHONE_CALL", {}).get("count", 0) or int(total_leads * 0.7)
        messages = lead_types_data.get("MESSAGE", {}).get("count", 0) or (total_leads - calls)

        if booked == 0:
            booked = int(total_leads * 0.6)

        booking_rate = (booked / total_leads * 100) if total_leads > 0 else 0
        cpl = total_spend / total_leads if total_leads > 0 else 0
        cpb = total_spend / booked if booked > 0 else 0

        weekly_budget = 500
        if profile and profile.suggestions:
            weekly_budget = profile.suggestions.get("weekly_budget", 500)

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

        # Build lead types breakdown
        lead_types_list = []
        for lt_name, lt_data in sorted(lead_types_data.items(), key=lambda x: x[1]["count"], reverse=True):
            if lt_data["count"] > 0:
                lt_cpl = lt_data["spend"] / lt_data["count"] if lt_data["count"] > 0 else 0
                lead_types_list.append({
                    "type": lt_name.replace("_", " ").title(),
                    "count": lt_data["count"],
                    "pct": round(lt_data["count"] / total_leads * 100),
                    "cpl": round(lt_cpl, 2),
                })

        # Build top services
        top_services = []
        for svc_name, svc_data in sorted(job_types.items(), key=lambda x: x[1]["count"], reverse=True)[:4]:
            svc_booked = int(svc_data["count"] * 0.6)  # Estimate
            svc_revenue = svc_booked * 250  # Estimate avg job value
            top_services.append({
                "name": svc_name,
                "leads": svc_data["count"],
                "booked": svc_booked,
                "revenue": svc_revenue,
            })

        # Build issues/alerts from real data
        issues = []
        if cpl > 50:
            issues.append({
                "type": "warning",
                "title": "High Cost Per Lead",
                "desc": f"Your CPL (${cpl:.2f}) is above the $50 industry benchmark.",
            })
        if profile and profile.review_count and profile.review_count < 100:
            issues.append({
                "type": "info",
                "title": "Review Volume",
                "desc": f"You have {profile.review_count} reviews. Top competitors average 150+ reviews.",
            })
        if booking_rate >= 55:
            issues.append({
                "type": "success",
                "title": "Good Booking Rate",
                "desc": f"Your {booking_rate:.0f}% booking rate is above average.",
            })

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
            "lead_types": lead_types_list,
            "top_services": top_services,
            "issues": issues,
            "last_sync": glsa_account.updated_at.isoformat() if glsa_account and glsa_account.updated_at else None,
        }

    # No synced data - return demo data
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
