# app/fbads/__init__.py
# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import json
import csv
import requests
from io import StringIO
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    make_response,
    jsonify,
    flash,
    session,
    current_app,
)

# Optional DB imports (graceful if not present)
try:
    from app import db  # type: ignore
except Exception:  # pragma: no cover
    db = None  # type: ignore

# Use your project's auth decorator if present
try:
    from app.auth.utils import login_required, current_account_id  # type: ignore
except Exception:  # pragma: no cover
    def login_required(fn):  # fallback no-op decorator
        return fn
    def current_account_id() -> int:
        return 0

fbads_bp = Blueprint("fbads_bp", __name__)  # app registers url_prefix="/account/fbads"

GRAPH = "https://graph.facebook.com/v20.0"

# -----------------------------------------------------------------------------
# Config helpers
# -----------------------------------------------------------------------------
def _fb_cfg():
    """
    Returns (APP_ID, APP_SECRET, REDIRECT_URI)
    REDIRECT_URI must exactly match the Facebook App's configured redirect.
    """
    app_id = current_app.config.get("FB_APP_ID") or os.getenv("FB_APP_ID")
    app_secret = current_app.config.get("FB_APP_SECRET") or os.getenv("FB_APP_SECRET")
    redirect_uri = (
        current_app.config.get("FB_REDIRECT_URI")
        or os.getenv("FB_REDIRECT_URI")
        or url_for("fbads_bp.callback", _external=True)
    )
    return app_id, app_secret, redirect_uri


def _openai_client():
    key = current_app.config.get("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not key:
        return None, None
    model = current_app.config.get("OPENAI_MODEL") or os.getenv("OPENAI_MODEL") or "gpt-4o-mini"
    try:
        from openai import OpenAI  # type: ignore
        return OpenAI(api_key=key), model
    except Exception:
        return None, None

# -----------------------------------------------------------------------------
# Token storage helpers (DB if available, else session fallback)
# -----------------------------------------------------------------------------
def _store_fb_token(aid: int, token: str, expires_in: Optional[int]) -> None:
    expires_at = datetime.utcnow() + timedelta(seconds=int(expires_in or 60 * 60 * 24 * 60))
    if db:
        try:
            db.engine.execute(
                db.text(
                    """
                    CREATE TABLE IF NOT EXISTS facebook_tokens (
                        account_id BIGINT NOT NULL PRIMARY KEY,
                        access_token TEXT NOT NULL,
                        expires_at DATETIME NULL,
                        created_at DATETIME NOT NULL,
                        updated_at DATETIME NOT NULL
                    )
                    """
                )
            )
            db.engine.execute(
                db.text(
                    """
                    INSERT INTO facebook_tokens (account_id, access_token, expires_at, created_at, updated_at)
                    VALUES (:aid, :t, :exp, NOW(), NOW())
                    ON DUPLICATE KEY UPDATE
                        access_token = VALUES(access_token),
                        expires_at   = VALUES(expires_at),
                        updated_at   = NOW()
                    """
                ),
                dict(aid=aid, t=token, exp=expires_at),
            )
            return
        except Exception:
            current_app.logger.exception("FB token DB store failed; falling back to session.")
    # Fallback to session (per-account session if you run multi-tenant in one login)
    session["fb_access_token"] = token
    session["fb_expires_at"] = expires_at.isoformat()


def _get_fb_token(aid: int) -> Optional[str]:
    if db:
        try:
            row = db.engine.execute(
                db.text("SELECT access_token, expires_at FROM facebook_tokens WHERE account_id=:aid LIMIT 1"),
                {"aid": aid},
            ).fetchone()
            if row:
                return row[0]
        except Exception:
            current_app.logger.exception("FB token DB read failed; trying session fallback.")
    return session.get("fb_access_token")


def _clear_fb_token(aid: int) -> None:
    if db:
        try:
            db.engine.execute(
                db.text("DELETE FROM facebook_tokens WHERE account_id=:aid"),
                {"aid": aid},
            )
        except Exception:
            current_app.logger.exception("FB token DB delete failed.")
    session.pop("fb_access_token", None)
    session.pop("fb_expires_at", None)

# -----------------------------------------------------------------------------
# Connection helper & sample data
# -----------------------------------------------------------------------------
def _is_connected() -> bool:
    """
    Real: checks token presence. Dev override: ?connected=1
    """
    if request.args.get("connected") == "1":
        return True
    try:
        aid = current_account_id()
    except Exception:
        aid = 0
    return bool(_get_fb_token(aid))

def _sample_profile() -> Dict[str, Any]:
    return {
        "connected": False,
        "page_name": "Clean Finish Pest Control",
        "page_id": "1234567890",
        "ad_account_id": "act_987654321",
        "pixel_id": "112233445566",
        "timezone": "America/Los_Angeles",
        "currency": "USD",
        "business_name": "Clean Finish, LLC",
        "website": "https://www.cleanfinish.co",
        "phone": "(916) 555-0199",
        "address": "1234 Main St, Sacramento, CA 95814",
        "daily_spend_cap": 250.00,
        "lead_destination": "email",
        "webhook_url": "",
        "notifications_email": "leads@cleanfinish.co",
        "auto_approve_leads": True,
        "notes": "",
    }

def _sample_leads() -> List[Dict[str, Any]]:
    return [
        {
            "id": 501,
            "created_at": "2025-09-10 14:22",
            "full_name": "Jane Alvarez",
            "email": "jane@example.com",
            "phone": "(916) 555-1020",
            "campaign": "Pest – Sacramento",
            "adset": "General Pest",
            "ad": "Eco-Friendly Pest Control",
            "status": "New",
            "notes": "",
        },
        {
            "id": 502,
            "created_at": "2025-09-11 09:05",
            "full_name": "Marcus Lee",
            "email": "marcus@example.com",
            "phone": "(916) 555-2040",
            "campaign": "Pest – Sacramento",
            "adset": "Ant Control",
            "ad": "$99 Pest Inspection",
            "status": "Contacted",
            "notes": "Left voicemail",
        },
        {
            "id": 503,
            "created_at": "2025-09-12 16:41",
            "full_name": "Priya Patel",
            "email": "priya@example.com",
            "phone": "(916) 555-7788",
            "campaign": "Termite – Citrus Heights",
            "adset": "Termite Inspection",
            "ad": "Termite Inspection",
            "status": "Qualified",
            "notes": "Booked for Tue 2pm",
        },
    ]

# TODO: replace with your DB CRUD once wired
def _get_profile_from_db(user_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
    return None

def _save_profile_to_db(data: Dict[str, Any], user_id: Optional[int] = None) -> None:
    # Persist `data` to your fbads profile table; also add audit logging if desired
    pass

def _get_leads_from_db(user_id: Optional[int] = None) -> List[Dict[str, Any]]:
    return []

def _update_lead_status_in_db(lead_id: int, status: str, user_id: Optional[int] = None) -> None:
    pass

def _update_lead_notes_in_db(lead_id: int, notes: str, user_id: Optional[int] = None) -> None:
    pass

def _get_lead_by_id_from_db(lead_id: int, user_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
    return None

# -----------------------------------------------------------------------------
# Routes — UI pages you already had
# -----------------------------------------------------------------------------
@fbads_bp.get("/")
@login_required
def index():
    connected = _is_connected()
    return render_template("fbads/index.html", connected=connected)

@fbads_bp.get("/leads")
@login_required
def leads():
    connected = _is_connected()
    if connected:
        leads_data = _get_leads_from_db() or _sample_leads()
    else:
        leads_data = _sample_leads()
    return render_template("fbads/leads.html", connected=connected, fb_leads=leads_data)

@fbads_bp.get("/profile/edit")
@login_required
def profile_edit():
    connected = _is_connected()
    profile = _get_profile_from_db() if connected else None
    if profile:
        profile["connected"] = True
    return render_template("fbads/profile_edit.html", profile=profile)

@fbads_bp.post("/profile/edit", endpoint="profile_edit_post")
@login_required
def profile_edit_post():
    form = request.form
    data = {
        "page_name": form.get("page_name", "").strip(),
        "page_id": form.get("page_id", "").strip(),
        "ad_account_id": form.get("ad_account_id", "").strip(),
        "pixel_id": form.get("pixel_id", "").strip(),
        "timezone": form.get("timezone", "").strip(),
        "currency": form.get("currency", "").strip(),
        "business_name": form.get("business_name", "").strip(),
        "website": form.get("website", "").strip(),
        "phone": form.get("phone", "").strip(),
        "address": form.get("address", "").strip(),
        "daily_spend_cap": float(form.get("daily_spend_cap") or 0.0),
        "lead_destination": form.get("lead_destination", "email"),
        "webhook_url": form.get("webhook_url", "").strip(),
        "notifications_email": form.get("notifications_email", "").strip(),
        "auto_approve_leads": ("auto_approve_leads" in form),
        "notes": form.get("notes", "").strip(),
    }
    _save_profile_to_db(data)
    return redirect(url_for("fbads_bp.profile_edit"))

# -----------------------------------------------------------------------------
# Connect / Disconnect (now real OAuth; keeps same endpoints)
# -----------------------------------------------------------------------------
@fbads_bp.get("/connect", endpoint="connect")
@login_required
def fb_connect():
    app_id, _secret, redirect_uri = _fb_cfg()
    if not app_id:
        flash("Facebook App ID not configured.", "error")
        return redirect(url_for("fbads_bp.index"))

    scope = ",".join([
        "ads_read", "ads_management", "pages_show_list", "pages_read_engagement", "business_management"
    ])
    from urllib.parse import urlencode
    params = dict(
        client_id=app_id,
        redirect_uri=redirect_uri,
        response_type="code",
        scope=scope,
        state="ok",
    )
    return redirect(f"https://www.facebook.com/v20.0/dialog/oauth?{urlencode(params)}")

@fbads_bp.get("/callback", endpoint="callback")
@login_required
def callback():
    code = request.args.get("code")
    if not code:
        flash("Facebook login failed.", "error")
        return redirect(url_for("fbads_bp.index"))

    app_id, app_secret, redirect_uri = _fb_cfg()
    if not app_secret:
        flash("Facebook App Secret not configured.", "error")
        return redirect(url_for("fbads_bp.index"))

    # 1) Exchange code for short-lived token
    r = requests.get(
        f"{GRAPH}/oauth/access_token",
        params=dict(client_id=app_id, client_secret=app_secret, redirect_uri=redirect_uri, code=code),
        timeout=30,
    )
    try:
        r.raise_for_status()
    except Exception:
        current_app.logger.exception("FB short-lived token exchange failed: %s", r.text)
        flash("Facebook token exchange failed.", "error")
        return redirect(url_for("fbads_bp.index"))
    short_tok = r.json().get("access_token")

    # 2) Exchange for long-lived token
    rr = requests.get(
        f"{GRAPH}/oauth/access_token",
        params=dict(
            grant_type="fb_exchange_token",
            client_id=app_id,
            client_secret=app_secret,
            fb_exchange_token=short_tok
        ),
        timeout=30,
    )
    try:
        rr.raise_for_status()
    except Exception:
        current_app.logger.exception("FB long-lived token exchange failed: %s", rr.text)
        flash("Facebook long-lived token exchange failed.", "error")
        return redirect(url_for("fbads_bp.index"))

    data = rr.json()
    aid = current_account_id()
    _store_fb_token(aid, data.get("access_token"), data.get("expires_in"))
    flash("Facebook connected.", "success")
    return redirect(url_for("fbads_bp.index"))

@fbads_bp.post("/disconnect", endpoint="disconnect")
@login_required
def fb_disconnect():
    aid = current_account_id()
    _clear_fb_token(aid)
    flash("Facebook disconnected.", "success")
    return redirect(url_for("fbads_bp.profile_edit"))

# -----------------------------------------------------------------------------
# Lead actions used by templates
# -----------------------------------------------------------------------------
@fbads_bp.post("/lead/status", endpoint="update_lead_status")
@login_required
def update_lead_status():
    lead_id = request.form.get("lead_id")
    status = request.form.get("status", "New")
    try:
        if lead_id:
            _update_lead_status_in_db(int(lead_id), status)
    except Exception:
        pass
    return redirect(url_for("fbads_bp.leads"))

@fbads_bp.post("/lead/notes", endpoint="update_lead_notes")
@login_required
def update_lead_notes():
    lead_id = request.form.get("lead_id")
    notes = request.form.get("notes", "")
    try:
        if lead_id:
            _update_lead_notes_in_db(int(lead_id), notes)
    except Exception:
        pass
    return redirect(url_for("fbads_bp.leads"))

@fbads_bp.get("/leads/export", endpoint="export_leads_csv")
@login_required
def export_leads_csv():
    connected = _is_connected()
    if connected:
        rows = _get_leads_from_db() or _sample_leads()
    else:
        rows = _sample_leads()

    header = ["id", "created_at", "full_name", "email", "phone", "campaign", "adset", "ad", "status", "notes"]
    sio = StringIO()
    writer = csv.writer(sio)
    writer.writerow(header)
    for r in rows:
        writer.writerow([
            r.get("id", ""),
            r.get("created_at", ""),
            r.get("full_name", ""),
            r.get("email", ""),
            r.get("phone", ""),
            r.get("campaign", ""),
            r.get("adset", ""),
            r.get("ad", ""),
            r.get("status", ""),
            r.get("notes", ""),
        ])

    resp = make_response(sio.getvalue())
    resp.headers["Content-Type"] = "text/csv; charset=utf-8"
    resp.headers["Content-Disposition"] = "attachment; filename=fb_leads.csv"
    return resp

@fbads_bp.get("/lead/<int:lead_id>", endpoint="lead_detail")
@login_required
def lead_detail(lead_id: int):
    lead = _get_lead_by_id_from_db(lead_id) or {
        "id": lead_id,
        "full_name": "Sample Lead",
        "email": "sample@example.com",
        "phone": "(000) 000-0000",
        "status": "New",
        "notes": "",
    }
    return render_template("fbads/lead_detail.html", lead=lead)

# -----------------------------------------------------------------------------
# Health & AI endpoints
# -----------------------------------------------------------------------------
@fbads_bp.get("/__debug")
@login_required
def __debug():
    aid = current_account_id()
    tok = _get_fb_token(aid)
    if not tok:
        return jsonify(ok=False, connected=False, error="No token. Click Connect."), 200
    rv: Dict[str, Any] = dict(ok=True, connected=True)

    try:
        aa = requests.get(
            f"{GRAPH}/me/adaccounts",
            params=dict(access_token=tok, fields="id,account_status,currency,timezone_name,name"),
            timeout=30,
        ).json()
        rv["adaccounts"] = aa
    except Exception as e:
        rv["adaccounts_error"] = str(e)

    try:
        pages = requests.get(
            f"{GRAPH}/me/accounts",
            params=dict(access_token=tok, fields="id,name,category,link,about,description,website"),
            timeout=30,
        ).json()
        rv["pages"] = pages
    except Exception as e:
        rv["pages_error"] = str(e)

    return jsonify(rv), 200

@fbads_bp.post("/optimize-profile.json", endpoint="optimize_profile_json")
@login_required
def optimize_profile_json():
    aid = current_account_id()
    tok = _get_fb_token(aid)
    if not tok:
        return jsonify(ok=False, error="Not connected to Facebook."), 401

    try:
        pages = requests.get(
            f"{GRAPH}/me/accounts",
            params=dict(access_token=tok, fields="id,name,category,about,description,website,link"),
            timeout=30,
        ).json()
        page = (pages.get("data") or [{}])[0] if isinstance(pages, dict) else {}
        profile = {
            "name": page.get("name") or "",
            "category": page.get("category") or "",
            "about": page.get("about") or "",
            "description": page.get("description") or "",
            "website": page.get("website") or "",
            "link": page.get("link") or "",
        }
    except Exception:
        current_app.logger.exception("FB Page fetch failed")
    # Even if fetch fails, try AI on minimal data
    client, model = _openai_client()
    if not client:
        return jsonify(ok=True, ai=False, suggestions={
            "about": "Add a one-liner with core service + city.",
            "description": "Use ~400–600 chars: services, proof (ratings/years), service area, clear CTA.",
            "cta": "Use a 'Book now' or 'Get quote' button to your best lead form.",
            "keywords": ["local service","near me","licensed","insured","free estimate","same-day","top rated","reliable"]
        })

    sys = ("You optimize Facebook Page profiles for clarity, trust, and conversion. "
           "Return JSON with keys about, description, cta, keywords (8-12 short phrases).")
    user = f"PAGE:\n{json.dumps(profile, ensure_ascii=False, indent=2)}\n\nReturn valid JSON."

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role":"system","content":sys},{"role":"user","content":user}],
            response_format={"type":"json_object"},
            temperature=0.3, max_tokens=600
        )
        data = json.loads((resp.choices[0].message.content or "").strip() or "{}")
        return jsonify(ok=True, ai=True, suggestions=data)
    except Exception:
        current_app.logger.exception("OpenAI profile optimize failed")
        return jsonify(ok=True, ai=False, suggestions={
            "about": "Add a one-liner with core service + city.",
            "description": "Use ~400–600 chars: services, proof (ratings/years), service area, clear CTA.",
            "cta": "Use a 'Book now' or 'Get quote' button to your best lead form.",
            "keywords": ["local service","near me","licensed","insured","free estimate","same-day","top rated","reliable"]
        })

@fbads_bp.post("/optimize-ads.json", endpoint="optimize_ads_json")
@login_required
def optimize_ads_json():
    aid = current_account_id()
    tok = _get_fb_token(aid)
    if not tok:
        return jsonify(ok=False, error="Not connected to Facebook."), 401

    # pick first ad account
    try:
        aa = requests.get(
            f"{GRAPH}/me/adaccounts",
            params=dict(access_token=tok, fields="id,name"),
            timeout=30,
        ).json()
        acts = (aa.get("data") or []) if isinstance(aa, dict) else []
        if not acts:
            return jsonify(ok=False, error="No ad accounts visible for this user."), 400
        act_id = acts[0]["id"]
    except Exception:
        current_app.logger.exception("Fetching adaccounts failed")
        return jsonify(ok=False, error="Could not fetch ad accounts."), 500

    # insights last 30d at adset level
    try:
        ins = requests.get(
            f"{GRAPH}/{act_id}/insights",
            params=dict(
                access_token=tok,
                date_preset="last_30d",
                level="adset",
                time_increment=1,
                fields="campaign_name,adset_name,objective,impressions,reach,clicks,inline_link_clicks,spend,ctr,cpc,cpm,actions",
                limit=200,
            ),
            timeout=60,
        ).json()
        rows = ins.get("data") or []
    except Exception:
        current_app.logger.exception("Fetching insights failed")
        rows = []

    # aggregate by adset
    by_adset: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        key = f"{r.get('campaign_name','')}/{r.get('adset_name','')}"
        o = by_adset.setdefault(key, dict(
            campaign=r.get("campaign_name"),
            adset=r.get("adset_name"),
            objective=r.get("objective"),
            impressions=0, clicks=0, link_clicks=0, spend=0.0, actions=[]
        ))
        o["impressions"] += int(r.get("impressions") or 0)
        o["clicks"] += int(r.get("clicks") or 0)
        o["link_clicks"] += int(r.get("inline_link_clicks") or 0)
        try:
            o["spend"] += float(r.get("spend") or 0.0)
        except Exception:
            pass
        acts = r.get("actions") or []
        o["actions"].extend(acts)

    summary = []
    for _, v in by_adset.items():
        summary.append({
            "campaign": v["campaign"],
            "adset": v["adset"],
            "objective": v["objective"],
            "impressions": v["impressions"],
            "clicks": v["clicks"],
            "link_clicks": v["link_clicks"],
            "spend": round(v["spend"], 2),
        })

    client, model = _openai_client()
    if not client:
        recs = [{"action":"review_budget_allocation","reason":"Shift spend from CTR <0.5% adsets to >1.5% to lower CPC."}]
        return jsonify(ok=True, ai=False, recommendations=recs, quick_wins=[
            "Pause lowest CTR adsets",
            "Duplicate best audience with new creative",
            "Test Advantage+ placements"
        ], sample=summary[:10])

    sys = ("You are a paid-social strategist. Given adset-level performance summaries for the last 30 days, "
           "return JSON with keys: recommendations (list of items with 'action' and 'reason'), and quick_wins (3 strings). "
           "Be concrete about budgets, audiences, creatives, placements.")
    user = f"ADSETS:\n{json.dumps(summary[:60], ensure_ascii=False, indent=2)}\nReturn valid JSON."

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role":"system","content":sys},{"role":"user","content":user}],
            response_format={"type":"json_object"},
            temperature=0.2, max_tokens=700
        )
        data = json.loads((resp.choices[0].message.content or "").strip() or "{}")
        return jsonify(ok=True, ai=True, **data)
    except Exception:
        current_app.logger.exception("OpenAI ads optimize failed")
        recs = [{"action":"review_budget_allocation","reason":"Shift spend from CTR <0.5% adsets to >1.5% to lower CPC."}]
        return jsonify(ok=True, ai=False, recommendations=recs, quick_wins=[
            "Pause lowest CTR adsets",
            "Duplicate best audience with new creative",
            "Test Advantage+ placements"
        ], sample=summary[:10])
