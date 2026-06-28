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

# SQLAlchemy imports
from sqlalchemy import text

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
            with db.engine.connect() as conn:
                conn.execute(
                    text(
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
                conn.execute(
                    text(
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
                conn.commit()
            return
        except Exception:
            current_app.logger.exception("FB token DB store failed; falling back to session.")
    # Fallback to session (per-account session if you run multi-tenant in one login)
    session["fb_access_token"] = token
    session["fb_expires_at"] = expires_at.isoformat()


def _try_refresh_token(token_row) -> None:
    """
    Attempt a proactive token refresh using Facebook's fb_exchange_token grant.
    Updates expires_at in DB if successful. On any failure, leaves token unchanged.
    token_row must expose .access_token and .account_id (positional indices 0 and the aid).
    """
    try:
        app_id = current_app.config.get("FB_APP_ID") or os.getenv("FB_APP_ID")
        app_secret = current_app.config.get("FB_APP_SECRET") or os.getenv("FB_APP_SECRET")
        if not app_id or not app_secret:
            return
        resp = requests.get(
            f"{GRAPH}/oauth/access_token",
            params=dict(
                grant_type="fb_exchange_token",
                client_id=app_id,
                client_secret=app_secret,
                fb_exchange_token=token_row[0],
            ),
            timeout=30,
        )
        if not resp.ok:
            return
        data = resp.json()
        new_token = data.get("access_token")
        expires_in = data.get("expires_in")
        if not new_token:
            return
        new_expires = datetime.utcnow() + timedelta(seconds=int(expires_in or 60 * 60 * 24 * 60))
        if db:
            with db.engine.connect() as conn:
                conn.execute(
                    text(
                        "UPDATE facebook_tokens SET access_token=:t, expires_at=:exp, updated_at=NOW() "
                        "WHERE account_id=:aid"
                    ),
                    dict(t=new_token, exp=new_expires, aid=token_row[2]),
                )
                conn.commit()
        current_app.logger.info("FB token proactively refreshed for account %s", token_row[2])
    except Exception:
        current_app.logger.exception("FB proactive token refresh failed; existing token unchanged.")


def _get_fb_token(aid: int) -> Optional[str]:
    if db:
        try:
            with db.engine.connect() as conn:
                result = conn.execute(
                    text("SELECT access_token, expires_at, account_id FROM facebook_tokens WHERE account_id=:aid LIMIT 1"),
                    {"aid": aid},
                )
                row = result.fetchone()
                if row:
                    # Check hard expiry
                    if row[1] and row[1] < datetime.utcnow():
                        # Token expired — do NOT delete, just signal reconnect
                        return None
                    # Proactive refresh if expiring within 7 days
                    if row[1] and row[1] < datetime.utcnow() + timedelta(days=7):
                        _try_refresh_token(row)
                    return row[0]
        except Exception:
            current_app.logger.exception("FB token DB read failed; trying session fallback.")
    # Session fallback
    exp_str = session.get("fb_expires_at")
    if exp_str:
        try:
            exp_dt = datetime.fromisoformat(exp_str)
            if exp_dt < datetime.utcnow():
                return None
        except Exception:
            pass
    return session.get("fb_access_token")


def _clear_fb_token(aid: int) -> None:
    if db:
        try:
            with db.engine.connect() as conn:
                conn.execute(
                    text("DELETE FROM facebook_tokens WHERE account_id=:aid"),
                    {"aid": aid},
                )
                conn.commit()
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

def _get_profile_from_db(user_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """Load FBProfile for the current account."""
    if not db:
        return None
    try:
        from app.models_fbads import FBProfile
        aid = user_id or current_account_id()
        prof = FBProfile.query.filter_by(account_id=aid).first()
        if not prof:
            return None
        raw = prof.raw or {}
        return {"page_id": prof.page_id, "page_name": prof.page_name,
                "about": prof.about, "description": prof.description,
                "website": prof.website, "phone": prof.phone, **raw}
    except Exception:
        return None


def _save_profile_to_db(data: Dict[str, Any], user_id: Optional[int] = None) -> None:
    """Upsert FBProfile; extra fields not in the schema are stored in raw JSON."""
    if not db:
        return
    try:
        from app.models_fbads import FBProfile
        aid = user_id or current_account_id()
        page_id = data.get("page_id") or "default"
        prof = FBProfile.query.filter_by(account_id=aid, page_id=page_id).first()
        if prof is None:
            prof = FBProfile(account_id=aid, page_id=page_id)
            db.session.add(prof)
        prof.page_name = data.get("page_name")
        prof.website = data.get("website")
        prof.phone = data.get("phone")
        known = {"page_id", "page_name", "website", "phone", "about", "description"}
        prof.raw = {k: v for k, v in data.items() if k not in known}
        db.session.commit()
    except Exception:
        db.session.rollback()


def _get_leads_from_db(user_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """Return FBLead rows for the current account as list of dicts."""
    if not db:
        return []
    try:
        from app.models_fbads import FBLead
        aid = user_id or current_account_id()
        leads = (FBLead.query.filter_by(account_id=aid)
                 .order_by(FBLead.created_at.desc()).limit(200).all())
        result = []
        for lead in leads:
            raw = lead.raw or {}
            result.append({
                "id": lead.id,
                "created_at": lead.created_at.strftime("%Y-%m-%d %H:%M") if lead.created_at else "",
                "full_name": lead.name, "email": lead.email, "phone": lead.phone,
                "campaign": raw.get("campaign_name", ""), "adset": raw.get("adset_name", ""),
                "ad": raw.get("ad_name", ""), "status": raw.get("status", "New"),
                "notes": raw.get("notes", ""),
            })
        return result
    except Exception:
        return []


def _update_lead_status_in_db(lead_id: int, status: str, user_id: Optional[int] = None) -> None:
    """Update status field stored in FBLead.raw."""
    if not db:
        return
    try:
        from app.models_fbads import FBLead
        aid = user_id or current_account_id()
        lead = FBLead.query.filter_by(id=lead_id, account_id=aid).first()
        if lead:
            raw = dict(lead.raw or {})
            raw["status"] = status
            lead.raw = raw
            db.session.commit()
    except Exception:
        db.session.rollback()


def _update_lead_notes_in_db(lead_id: int, notes: str, user_id: Optional[int] = None) -> None:
    """Update notes field stored in FBLead.raw."""
    if not db:
        return
    try:
        from app.models_fbads import FBLead
        aid = user_id or current_account_id()
        lead = FBLead.query.filter_by(id=lead_id, account_id=aid).first()
        if lead:
            raw = dict(lead.raw or {})
            raw["notes"] = notes
            lead.raw = raw
            db.session.commit()
    except Exception:
        db.session.rollback()


def _get_lead_by_id_from_db(lead_id: int, user_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """Return a single FBLead as a dict."""
    if not db:
        return None
    try:
        from app.models_fbads import FBLead
        aid = user_id or current_account_id()
        lead = FBLead.query.filter_by(id=lead_id, account_id=aid).first()
        if not lead:
            return None
        raw = lead.raw or {}
        return {
            "id": lead.id,
            "created_at": lead.created_at.strftime("%Y-%m-%d %H:%M") if lead.created_at else "",
            "full_name": lead.name, "email": lead.email, "phone": lead.phone,
            "campaign": raw.get("campaign_name", ""), "adset": raw.get("adset_name", ""),
            "ad": raw.get("ad_name", ""), "status": raw.get("status", "New"),
            "notes": raw.get("notes", ""),
        }
    except Exception:
        return None

# -----------------------------------------------------------------------------
# Routes — UI pages you already had
# -----------------------------------------------------------------------------
@fbads_bp.get("/")
@login_required
def index():
    connected = _is_connected()
    return render_template("fbads/index.html", connected=connected, config=current_app.config)

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
# Account/Page Selection Helpers
# -----------------------------------------------------------------------------
def _get_selected_account(aid: int) -> Optional[Dict[str, Any]]:
    """Get the selected Facebook ad account for this user"""
    if db:
        try:
            with db.engine.connect() as conn:
                result = conn.execute(
                    text(
                        "SELECT ad_account_id, ad_account_name, page_id, page_name "
                        "FROM facebook_selected_accounts WHERE account_id=:aid LIMIT 1"
                    ),
                    {"aid": aid},
                )
                row = result.fetchone()
                if row:
                    return {
                        "ad_account_id": row[0],
                        "ad_account_name": row[1],
                        "page_id": row[2],
                        "page_name": row[3]
                    }
        except Exception:
            current_app.logger.debug("No selected Facebook account found")
    return None

def _save_selected_account(aid: int, ad_account_id: str, ad_account_name: str, page_id: str, page_name: str):
    """Save the selected Facebook ad account/page for this user"""
    if db:
        try:
            with db.engine.connect() as conn:
                # Create table if not exists
                conn.execute(
                    text(
                        """
                        CREATE TABLE IF NOT EXISTS facebook_selected_accounts (
                            account_id BIGINT NOT NULL PRIMARY KEY,
                            ad_account_id VARCHAR(255) NOT NULL,
                            ad_account_name VARCHAR(255),
                            page_id VARCHAR(255),
                            page_name VARCHAR(255),
                            created_at DATETIME NOT NULL,
                            updated_at DATETIME NOT NULL
                        )
                        """
                    )
                )
                conn.execute(
                    text(
                        """
                        INSERT INTO facebook_selected_accounts
                        (account_id, ad_account_id, ad_account_name, page_id, page_name, created_at, updated_at)
                        VALUES (:aid, :ad_id, :ad_name, :pg_id, :pg_name, NOW(), NOW())
                        ON DUPLICATE KEY UPDATE
                            ad_account_id = VALUES(ad_account_id),
                            ad_account_name = VALUES(ad_account_name),
                            page_id = VALUES(page_id),
                            page_name = VALUES(page_name),
                            updated_at = NOW()
                        """
                    ),
                    dict(aid=aid, ad_id=ad_account_id, ad_name=ad_account_name, pg_id=page_id, pg_name=page_name),
                )
                conn.commit()
        except Exception as e:
            current_app.logger.exception("Failed to save selected Facebook account: %s", e)

# -----------------------------------------------------------------------------
# Account/Page Selection Routes
# -----------------------------------------------------------------------------
@fbads_bp.get("/select-account", endpoint="select_account")
@login_required
def select_account():
    """Page to select Facebook ad account and page"""
    aid = current_account_id()
    tok = _get_fb_token(aid)

    if not tok:
        flash("Your Facebook connection expired — please reconnect to continue.", "warning")
        return redirect(url_for("fbads_bp.connect"))

    # Fetch available ad accounts
    ad_accounts = []
    try:
        aa = requests.get(
            f"{GRAPH}/me/adaccounts",
            params=dict(access_token=tok, fields="id,name,account_status,currency,timezone_name"),
            timeout=30,
        ).json()
        ad_accounts = aa.get("data", [])
    except Exception as e:
        current_app.logger.exception("Failed to fetch ad accounts")
        flash(f"Failed to fetch ad accounts: {str(e)}", "error")

    # Fetch available pages
    pages = []
    try:
        pg = requests.get(
            f"{GRAPH}/me/accounts",
            params=dict(access_token=tok, fields="id,name,category,access_token"),
            timeout=30,
        ).json()
        pages = pg.get("data", [])
    except Exception as e:
        current_app.logger.exception("Failed to fetch pages")
        flash(f"Failed to fetch pages: {str(e)}", "error")

    # Get currently selected account
    selected = _get_selected_account(aid)

    return render_template(
        "fbads/select_account.html",
        ad_accounts=ad_accounts,
        pages=pages,
        selected=selected,
        config=current_app.config
    )

@fbads_bp.post("/select-account", endpoint="select_account_post")
@login_required
def select_account_post():
    """Save selected Facebook ad account and page"""
    aid = current_account_id()

    ad_account_id = request.form.get("ad_account_id", "").strip()
    ad_account_name = request.form.get("ad_account_name", "").strip()
    page_id = request.form.get("page_id", "").strip()
    page_name = request.form.get("page_name", "").strip()

    if not ad_account_id:
        flash("Please select an ad account.", "error")
        return redirect(url_for("fbads_bp.select_account"))

    _save_selected_account(aid, ad_account_id, ad_account_name, page_id, page_name)
    flash("Account selection saved successfully!", "success")

    return redirect(url_for("fbads_bp.index"))

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

    # Facebook Marketing API permissions required for campaign management
    # ads_management: Create, edit, and manage campaigns, ad sets, and ads
    # read_insights: Access performance data and analytics
    # business_management: Access ad accounts under business manager
    # pages_show_list: List Facebook pages for ad account association
    scope = ",".join([
        "ads_management",
        "read_insights",
        "business_management",
        "pages_show_list",
        "leads_retrieval"
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

@fbads_bp.post("/save-token", endpoint="save_token")
@login_required
def save_token():
    """Save Facebook access token from client-side login"""
    try:
        data = request.get_json()
        access_token = data.get('access_token')
        user_id = data.get('user_id')
        expires_in = data.get('expires_in')

        if not access_token:
            return jsonify({"success": False, "error": "No access token provided"}), 400

        aid = current_account_id()

        # Exchange short-lived token for long-lived token
        app_id = current_app.config.get("FB_APP_ID") or os.getenv("FB_APP_ID")
        app_secret = current_app.config.get("FB_APP_SECRET") or os.getenv("FB_APP_SECRET")

        if app_id and app_secret:
            try:
                # Exchange for long-lived token (60 days)
                exchange_url = f"{GRAPH}/oauth/access_token"
                params = {
                    "grant_type": "fb_exchange_token",
                    "client_id": app_id,
                    "client_secret": app_secret,
                    "fb_exchange_token": access_token
                }
                resp = requests.get(exchange_url, params=params, timeout=30)
                if resp.status_code == 200:
                    token_data = resp.json()
                    long_lived_token = token_data.get('access_token')
                    if long_lived_token:
                        access_token = long_lived_token
                        current_app.logger.info("Exchanged for long-lived Facebook token")
            except Exception as e:
                current_app.logger.warning(f"Failed to exchange for long-lived token: {e}")
                # Continue with short-lived token

        # Save the token
        _save_fb_token(aid, access_token)

        return jsonify({"success": True, "message": "Facebook connected successfully"})

    except Exception as e:
        current_app.logger.exception("Error saving Facebook token")
        return jsonify({"success": False, "error": str(e)}), 500

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

# -----------------------------------------------------------------------------
# Facebook Ads Optimizer Page (similar to Google Ads optimizer)
# -----------------------------------------------------------------------------
@fbads_bp.route("/optimize", endpoint="optimize")
@login_required
def fb_ads_optimize():
    """
    Facebook Ads optimizer page with AI-powered recommendations.
    Analyzes campaigns, ad sets, and ads for optimization opportunities.
    """
    connected = _is_connected()

    # Sample data for demo purposes
    recommendations = _generate_sample_recommendations()
    performance_summary = _generate_sample_performance()

    return render_template(
        "fbads/optimizer.html",
        connected=connected,
        recommendations=recommendations,
        performance=performance_summary,
        config=current_app.config
    )

def _generate_sample_recommendations():
    """Generate sample optimization recommendations for Facebook Ads"""
    return [
        {
            "id": 1,
            "category": "Budget Optimization",
            "severity": "high",
            "title": "Redistribute budget from underperforming ad sets",
            "description": "3 ad sets with CTR < 0.5% are consuming 35% of your budget. Reallocate to better performers.",
            "impact": "Potential 40% reduction in CPC (~$850/month savings)",
            "ad_sets": ["General Audience 18-65", "Broad Interest Targeting", "Lookalike 1%"],
            "current_metrics": {
                "avg_ctr": "0.42%",
                "avg_cpc": "$4.25",
                "monthly_spend": "$2,450"
            },
            "suggested_action": {
                "type": "budget_reallocation",
                "details": "Reduce budget by 60% on these ad sets, increase top 3 performers by 30%"
            }
        },
        {
            "id": 2,
            "category": "Creative Fatigue",
            "severity": "high",
            "title": "Refresh ad creatives showing engagement decline",
            "description": "5 ads have been running for 45+ days with 60% drop in CTR. Time to refresh creative.",
            "impact": "Expected 50-80% CTR improvement",
            "ads": ["Summer Special - Image A", "Get Quote - Video", "Testimonial Carousel"],
            "current_metrics": {
                "frequency": "8.2",
                "ctr_decline": "-62%",
                "days_running": "47"
            },
            "suggested_action": {
                "type": "creative_refresh",
                "details": "Create 3 new variations with different hooks, images, and CTAs"
            }
        },
        {
            "id": 3,
            "category": "Audience Targeting",
            "severity": "medium",
            "title": "Expand high-performing lookalike audiences",
            "description": "Your 1% lookalike audience has 2.1% CTR and $18 CPL. Scale with 2-3% lookalikes.",
            "impact": "3x reach potential while maintaining <20% CPL increase",
            "audiences": ["Lookalike 1% - Customer List"],
            "current_metrics": {
                "ctr": "2.1%",
                "cpl": "$18.00",
                "roas": "4.2x"
            },
            "suggested_action": {
                "type": "audience_expansion",
                "details": "Create 2% and 3% lookalike audiences, start with $30/day test budget each"
            }
        },
        {
            "id": 4,
            "category": "Placement Optimization",
            "severity": "medium",
            "title": "Disable underperforming placements",
            "description": "Audience Network and Messenger placements have 0.08% CTR vs 1.4% on Feed.",
            "impact": "15-25% cost savings by focusing on high-performing placements",
            "placements": ["Audience Network", "Messenger Inbox", "Right Column"],
            "current_metrics": {
                "audience_network_ctr": "0.08%",
                "feed_ctr": "1.42%",
                "wasted_spend": "$340/mo"
            },
            "suggested_action": {
                "type": "placement_optimization",
                "details": "Disable Audience Network and Right Column, focus on Feed and Stories"
            }
        },
        {
            "id": 5,
            "category": "Conversion Tracking",
            "severity": "high",
            "title": "Fix incomplete conversion tracking",
            "description": "Only 2 of 8 campaigns have proper conversion events. Missing critical ROAS data.",
            "impact": "Enable data-driven optimization and accurate ROAS measurement",
            "campaigns": ["Lead Gen - Spring 2025", "Service Area Expansion"],
            "current_metrics": {
                "campaigns_with_tracking": "2/8",
                "untracked_spend": "$1,850/mo"
            },
            "suggested_action": {
                "type": "tracking_setup",
                "details": "Install Facebook Pixel events for Lead, Contact, and Purchase on all campaigns"
            }
        },
        {
            "id": 6,
            "category": "Ad Copy",
            "severity": "low",
            "title": "Test urgency-driven copy variations",
            "description": "Current ads lack urgency. Test limited-time offers and seasonal promotions.",
            "impact": "10-30% conversion rate improvement based on industry benchmarks",
            "ads": ["General Service Ad", "Quality Promise"],
            "current_metrics": {
                "conversion_rate": "1.2%",
                "industry_avg": "2.1%"
            },
            "suggested_action": {
                "type": "copy_testing",
                "details": "A/B test: '20% Off This Week Only' vs current evergreen copy"
            }
        },
        {
            "id": 7,
            "category": "Landing Page",
            "severity": "medium",
            "title": "Improve landing page load speed",
            "description": "Landing page takes 4.2s to load. 40% of clicks don't reach the page.",
            "impact": "Recover 30-40% of lost traffic, reduce CPL by $8-12",
            "current_metrics": {
                "load_time": "4.2s",
                "bounce_rate": "68%",
                "target_load_time": "<2s"
            },
            "suggested_action": {
                "type": "landing_page",
                "details": "Compress images, enable caching, use CDN, minimize JavaScript"
            }
        },
        {
            "id": 8,
            "category": "Bidding Strategy",
            "severity": "low",
            "title": "Test Lowest Cost with bid cap",
            "description": "Current Lowest Cost strategy occasionally spikes above target CPL.",
            "impact": "More consistent CPL with 10-15% volume increase",
            "campaigns": ["Lead Gen - Primary"],
            "current_metrics": {
                "avg_cpl": "$22",
                "cpl_spikes": "up to $45",
                "target_cpl": "$20"
            },
            "suggested_action": {
                "type": "bid_strategy",
                "details": "Switch to Cost Cap bidding with $24 cap to control costs while scaling"
            }
        }
    ]

def _generate_sample_performance():
    """Generate sample performance metrics for the optimizer dashboard"""
    return {
        "account_health_score": 72,
        "monthly_spend": 8450.00,
        "total_impressions": 1245000,
        "total_clicks": 8920,
        "avg_ctr": 0.72,
        "avg_cpc": 2.85,
        "avg_cpm": 20.50,
        "total_conversions": 156,
        "cost_per_conversion": 54.17,
        "roas": 3.8,
        "campaigns": {
            "total": 8,
            "active": 6,
            "paused": 2,
            "issues": 3
        },
        "ad_sets": {
            "total": 24,
            "active": 18,
            "learning": 3,
            "low_performance": 5
        },
        "ads": {
            "total": 67,
            "active": 52,
            "creative_fatigue": 12,
            "high_performers": 8
        },
        "quick_stats": [
            {"label": "Wasted Spend", "value": "$1,250/mo", "trend": "down", "severity": "warning"},
            {"label": "Creative Fatigue", "value": "12 ads", "trend": "up", "severity": "danger"},
            {"label": "Optimization Potential", "value": "$3,200/mo", "trend": "neutral", "severity": "info"},
            {"label": "CTR vs Industry", "value": "-22%", "trend": "down", "severity": "warning"}
        ],
        "top_opportunities": [
            {"category": "Budget", "potential_savings": 850},
            {"category": "Creative", "potential_lift": "60% CTR"},
            {"category": "Audience", "potential_reach": "3x"}
        ]
    }

# -----------------------------------------------------------------------------
# Campaigns, Ad Sets, and Ads Management
# -----------------------------------------------------------------------------
@fbads_bp.route("/campaigns", endpoint="campaigns")
@login_required
def campaigns():
    """View and manage Facebook Ad campaigns"""
    aid = current_account_id()
    tok = _get_fb_token(aid)
    if tok is None:
        flash("Your Facebook connection expired — please reconnect to continue.", "warning")
        return redirect(url_for("fbads_bp.connect"))
    connected = bool(tok)
    selected = _get_selected_account(aid)

    campaigns_data = []
    if connected and selected:
        try:
            # Fetch campaigns from Facebook API
            resp = requests.get(
                f"{GRAPH}/{selected['ad_account_id']}/campaigns",
                params=dict(
                    access_token=tok,
                    fields="id,name,status,objective,daily_budget,lifetime_budget,created_time,updated_time",
                    limit=100
                ),
                timeout=30,
            ).json()
            campaigns_data = resp.get("data", [])
        except Exception as e:
            current_app.logger.exception("Failed to fetch campaigns")
            flash(f"Failed to load campaigns: {str(e)}", "error")

    # Sample data if not connected
    if not campaigns_data:
        campaigns_data = [
            {
                "id": "camp_001",
                "name": "Lead Gen - Sacramento",
                "status": "ACTIVE",
                "objective": "LEAD_GENERATION",
                "daily_budget": "5000",
                "lifetime_budget": None,
                "spend": "$1,234.56",
                "impressions": "45,230",
                "clicks": "892",
                "ctr": "1.97%",
                "cpc": "$1.38"
            },
            {
                "id": "camp_002",
                "name": "Brand Awareness - Bay Area",
                "status": "ACTIVE",
                "objective": "BRAND_AWARENESS",
                "daily_budget": "3000",
                "lifetime_budget": None,
                "spend": "$876.23",
                "impressions": "78,940",
                "clicks": "523",
                "ctr": "0.66%",
                "cpc": "$1.68"
            },
            {
                "id": "camp_003",
                "name": "Retargeting - Website Visitors",
                "status": "PAUSED",
                "objective": "CONVERSIONS",
                "daily_budget": "2500",
                "lifetime_budget": None,
                "spend": "$0.00",
                "impressions": "0",
                "clicks": "0",
                "ctr": "0.00%",
                "cpc": "$0.00"
            }
        ]

    return render_template(
        "fbads/campaigns.html",
        connected=connected,
        selected=selected,
        campaigns=campaigns_data,
        config=current_app.config
    )

# -----------------------------------------------------------------------------
# Campaign Creation (for Meta App Review)
# -----------------------------------------------------------------------------
@fbads_bp.route("/create-test-campaign", methods=["GET"], endpoint="create_test_campaign")
@login_required
def create_test_campaign():
    """
    Simple campaign creation form for Meta app review.
    Demonstrates end-to-end flow: create campaign → show in Ads Manager → pull metrics.
    """
    aid = current_account_id()
    tok = _get_fb_token(aid)
    if tok is None:
        flash("Your Facebook connection expired — please reconnect to continue.", "warning")
        return redirect(url_for("fbads_bp.connect"))
    connected = bool(tok)
    selected = _get_selected_account(aid)

    if not connected:
        flash("Your Facebook connection expired — please reconnect to continue.", "warning")
        return redirect(url_for("fbads_bp.connect"))

    if not selected:
        flash("Please select an ad account first.", "warning")
        return redirect(url_for("fbads_bp.select_account"))

    # Common campaign objectives for home services
    objectives = [
        ("OUTCOME_LEADS", "Lead Generation"),
        ("OUTCOME_TRAFFIC", "Traffic"),
        ("OUTCOME_ENGAGEMENT", "Engagement"),
        ("OUTCOME_AWARENESS", "Brand Awareness"),
        ("OUTCOME_SALES", "Conversions/Sales"),
    ]

    return render_template(
        "fbads/create_test_campaign.html",
        connected=connected,
        selected=selected,
        objectives=objectives,
        config=current_app.config
    )

@fbads_bp.post("/create-test-campaign", endpoint="create_test_campaign_post")
@login_required
def create_test_campaign_post():
    """
    Handle campaign creation via Marketing API.
    Creates a test campaign in the user's ad account.
    """
    aid = current_account_id()
    tok = _get_fb_token(aid)
    selected = _get_selected_account(aid)

    if not tok or not selected:
        flash("Not connected to Facebook or no account selected.", "error")
        return redirect(url_for("fbads_bp.create_test_campaign"))

    # Get form data
    campaign_name = request.form.get("campaign_name", "").strip()
    objective = request.form.get("objective", "OUTCOME_LEADS")
    daily_budget = request.form.get("daily_budget", "5")
    status = request.form.get("status", "PAUSED")  # Start paused for safety

    # Validation
    if not campaign_name:
        flash("Campaign name is required.", "error")
        return redirect(url_for("fbads_bp.create_test_campaign"))

    try:
        daily_budget_cents = int(float(daily_budget) * 100)  # Convert to cents
    except (ValueError, TypeError):
        flash("Invalid budget amount.", "error")
        return redirect(url_for("fbads_bp.create_test_campaign"))

    # Create campaign via Marketing API
    try:
        endpoint = f"{GRAPH}/{selected['ad_account_id']}/campaigns"
        payload = {
            "name": campaign_name,
            "objective": objective,
            "status": status,
            "special_ad_categories": [],  # Required field
            "access_token": tok
        }

        # Note: daily_budget is set at ad set level, not campaign level for newer objectives
        # For now we'll create campaign without budget (budget goes on ad set)

        current_app.logger.info(f"Creating campaign: {campaign_name} with objective {objective}")

        resp = requests.post(endpoint, data=payload, timeout=30)
        resp.raise_for_status()

        result = resp.json()
        campaign_id = result.get("id")

        current_app.logger.info(f"Campaign created successfully: {campaign_id}")

        flash(
            f"✅ Campaign '{campaign_name}' created successfully! "
            f"Campaign ID: {campaign_id}. "
            f"You can view it in Facebook Ads Manager.",
            "success"
        )

        # Store campaign ID in session for potential follow-up actions
        session["last_created_campaign_id"] = campaign_id
        session["last_created_campaign_name"] = campaign_name

        return redirect(url_for("fbads_bp.campaigns"))

    except requests.exceptions.HTTPError as e:
        error_msg = e.response.text if e.response else str(e)
        current_app.logger.error(f"Campaign creation failed: {error_msg}")

        flash(
            f"Failed to create campaign. Facebook API error: {error_msg}",
            "error"
        )
        return redirect(url_for("fbads_bp.create_test_campaign"))

    except Exception as e:
        current_app.logger.exception("Unexpected error creating campaign")
        flash(f"Unexpected error: {str(e)}", "error")
        return redirect(url_for("fbads_bp.create_test_campaign"))

@fbads_bp.route("/adsets", endpoint="adsets")
@login_required
def adsets():
    """View and manage Facebook Ad sets"""
    aid = current_account_id()
    tok = _get_fb_token(aid)
    if tok is None:
        flash("Your Facebook connection expired — please reconnect to continue.", "warning")
        return redirect(url_for("fbads_bp.connect"))
    connected = bool(tok)
    selected = _get_selected_account(aid)

    campaign_id = request.args.get("campaign_id")
    adsets_data = []

    if connected and selected and campaign_id:
        try:
            # Fetch ad sets from Facebook API
            resp = requests.get(
                f"{GRAPH}/{campaign_id}/adsets",
                params=dict(
                    access_token=tok,
                    fields="id,name,status,daily_budget,lifetime_budget,targeting,optimization_goal,billing_event,bid_amount,created_time",
                    limit=100
                ),
                timeout=30,
            ).json()
            adsets_data = resp.get("data", [])
        except Exception as e:
            current_app.logger.exception("Failed to fetch ad sets")
            flash(f"Failed to load ad sets: {str(e)}", "error")

    # Sample data
    if not adsets_data:
        adsets_data = [
            {
                "id": "adset_001",
                "name": "Age 25-45 | Homeowners",
                "status": "ACTIVE",
                "daily_budget": "2000",
                "optimization_goal": "LEAD_GENERATION",
                "spend": "$612.34",
                "impressions": "23,450",
                "clicks": "489",
                "ctr": "2.08%",
                "cpc": "$1.25",
                "cpl": "$18.50"
            },
            {
                "id": "adset_002",
                "name": "Lookalike 1% - Past Customers",
                "status": "ACTIVE",
                "daily_budget": "1500",
                "optimization_goal": "LEAD_GENERATION",
                "spend": "$445.89",
                "impressions": "18,230",
                "clicks": "312",
                "ctr": "1.71%",
                "cpc": "$1.43",
                "cpl": "$22.30"
            },
            {
                "id": "adset_003",
                "name": "Interest: Home Improvement",
                "status": "LEARNING",
                "daily_budget": "1000",
                "optimization_goal": "LEAD_GENERATION",
                "spend": "$89.12",
                "impressions": "3,550",
                "clicks": "91",
                "ctr": "2.56%",
                "cpc": "$0.98",
                "cpl": "$14.85"
            }
        ]

    return render_template(
        "fbads/adsets.html",
        connected=connected,
        selected=selected,
        campaign_id=campaign_id,
        adsets=adsets_data,
        config=current_app.config
    )

@fbads_bp.post("/ads/update", endpoint="update_ad")
@login_required
def update_ad():
    """Update a Facebook ad via Marketing API with optional image upload"""
    aid = current_account_id()
    tok = _get_fb_token(aid)
    selected = _get_selected_account(aid)

    if not tok or not selected:
        flash("Not connected to Facebook", "error")
        return redirect(url_for("fbads_bp.ads", adset_id=request.form.get("adset_id")))

    ad_id = request.form.get("ad_id")
    name = request.form.get("name")
    status = request.form.get("status")
    headline = request.form.get("headline")
    body = request.form.get("body")
    call_to_action = request.form.get("call_to_action")
    adset_id = request.form.get("adset_id")

    if not ad_id or not name:
        flash("Ad ID and name are required", "error")
        return redirect(url_for("fbads_bp.ads", adset_id=adset_id))

    try:
        # Handle image upload if provided
        image_hash = None
        if 'image' in request.files:
            image_file = request.files['image']
            if image_file and image_file.filename:
                current_app.logger.info(f"Uploading image: {image_file.filename}")

                # Upload image to Facebook AdImage API
                ad_account_id = selected['ad_account_id']
                image_upload_url = f"{GRAPH}/{ad_account_id}/adimages"

                files = {
                    'filename': (image_file.filename, image_file.stream, image_file.content_type)
                }
                data = {
                    'access_token': tok
                }

                img_resp = requests.post(
                    image_upload_url,
                    files=files,
                    data=data,
                    timeout=60
                )
                img_resp.raise_for_status()
                img_result = img_resp.json()

                # Get the image hash
                if 'images' in img_result and image_file.filename in img_result['images']:
                    image_hash = img_result['images'][image_file.filename]['hash']
                    current_app.logger.info(f"Image uploaded successfully: hash={image_hash}")
                    flash(f"✅ Image uploaded successfully!", "success")
                else:
                    current_app.logger.error(f"Image upload failed: {img_result}")
                    flash("Image upload failed. Updating text only.", "warning")

        # Update ad basic properties
        update_data = {
            "name": name,
            "status": status,
            "access_token": tok
        }

        resp = requests.post(
            f"{GRAPH}/{ad_id}",
            data=update_data,
            timeout=30
        )
        resp.raise_for_status()

        # If we have a new image, create/update the creative
        if image_hash and headline and body:
            try:
                # Create new creative with the image
                creative_data = {
                    "name": f"Creative for {name}",
                    "object_story_spec": {
                        "page_id": selected.get('page_id', ''),
                        "link_data": {
                            "image_hash": image_hash,
                            "link": "https://fieldsprout.io",  # Replace with actual link
                            "message": body,
                            "name": headline,
                            "call_to_action": {
                                "type": call_to_action or "LEARN_MORE"
                            } if call_to_action else {}
                        }
                    },
                    "access_token": tok
                }

                creative_resp = requests.post(
                    f"{GRAPH}/{selected['ad_account_id']}/adcreatives",
                    json=creative_data,
                    timeout=30
                )
                creative_resp.raise_for_status()
                creative_result = creative_resp.json()
                creative_id = creative_result.get('id')

                if creative_id:
                    # Update ad with new creative
                    requests.post(
                        f"{GRAPH}/{ad_id}",
                        data={
                            "creative": {"creative_id": creative_id},
                            "access_token": tok
                        },
                        timeout=30
                    )
                    current_app.logger.info(f"Ad creative updated: {creative_id}")

            except Exception as creative_error:
                current_app.logger.error(f"Failed to update creative: {creative_error}")
                flash("Ad updated but creative update failed. Text changes only.", "warning")

        flash(f"✅ Ad '{name}' updated successfully!", "success")
        current_app.logger.info(f"Updated Facebook ad {ad_id}: {name}")

    except requests.exceptions.HTTPError as e:
        error_msg = e.response.text if e.response else str(e)
        current_app.logger.error(f"Failed to update ad {ad_id}: {error_msg}")
        flash(f"Failed to update ad: {error_msg}", "error")
    except Exception as e:
        current_app.logger.exception(f"Error updating ad {ad_id}")
        flash(f"Error updating ad: {str(e)}", "error")

    return redirect(url_for("fbads_bp.ads", adset_id=adset_id))

@fbads_bp.route("/ads", endpoint="ads")
@login_required
def ads():
    """View and manage Facebook Ads"""
    aid = current_account_id()
    tok = _get_fb_token(aid)
    if tok is None:
        flash("Your Facebook connection expired — please reconnect to continue.", "warning")
        return redirect(url_for("fbads_bp.connect"))
    connected = bool(tok)
    selected = _get_selected_account(aid)

    adset_id = request.args.get("adset_id")
    ads_data = []

    if connected and selected and adset_id:
        try:
            # Fetch ads from Facebook API
            resp = requests.get(
                f"{GRAPH}/{adset_id}/ads",
                params=dict(
                    access_token=tok,
                    fields="id,name,status,creative,preview_shareable_link,created_time",
                    limit=100
                ),
                timeout=30,
            ).json()
            ads_data = resp.get("data", [])
        except Exception as e:
            current_app.logger.exception("Failed to fetch ads")
            flash(f"Failed to load ads: {str(e)}", "error")

    # Sample data
    if not ads_data:
        ads_data = [
            {
                "id": "ad_001",
                "name": "Summer Special - Image A",
                "status": "ACTIVE",
                "creative_type": "single_image",
                "headline": "Save 20% on All Services This Month",
                "body": "Professional service you can trust. Licensed, insured, and highly rated.",
                "spend": "$234.56",
                "impressions": "12,340",
                "clicks": "256",
                "ctr": "2.07%",
                "cpc": "$0.92",
                "frequency": "1.8"
            },
            {
                "id": "ad_002",
                "name": "Testimonial Video",
                "status": "ACTIVE",
                "creative_type": "video",
                "headline": "See Why Customers Choose Us",
                "body": "Over 500 5-star reviews. Same-day service available.",
                "spend": "$178.23",
                "impressions": "8,920",
                "clicks": "189",
                "ctr": "2.12%",
                "cpc": "$0.94",
                "frequency": "1.5"
            },
            {
                "id": "ad_003",
                "name": "Free Quote CTA",
                "status": "ACTIVE",
                "creative_type": "single_image",
                "headline": "Get Your Free Quote Today",
                "body": "Fast, reliable service. Book online in 60 seconds.",
                "spend": "$89.45",
                "impressions": "4,230",
                "clicks": "98",
                "ctr": "2.32%",
                "cpc": "$0.91",
                "frequency": "1.3"
            }
        ]

    return render_template(
        "fbads/ads.html",
        connected=connected,
        selected=selected,
        adset_id=adset_id,
        ads=ads_data,
        config=current_app.config
    )

# -----------------------------------------------------------------------------
# Optimizer API - Apply Fixes
# -----------------------------------------------------------------------------
@fbads_bp.post("/api/apply-fix", endpoint="apply_fix")
@login_required
def apply_fix():
    """Apply an optimization fix to a campaign, ad set, or ad"""
    aid = current_account_id()
    tok = _get_fb_token(aid)

    if not tok:
        return jsonify({"success": False, "error": "Not connected to Facebook"}), 401

    try:
        data = request.get_json()
        recommendation_id = data.get('recommendation_id')
        action_type = data.get('action_type')
        entity_type = data.get('entity_type')  # 'campaign', 'adset', 'ad'
        entity_id = data.get('entity_id')
        params = data.get('params', {})

        if not all([recommendation_id, action_type, entity_type]):
            return jsonify({"success": False, "error": "Missing required parameters"}), 400

        # Apply the fix based on action type
        result = _apply_facebook_fix(tok, action_type, entity_type, entity_id, params)

        if result.get('success'):
            return jsonify({
                "success": True,
                "message": f"Successfully applied fix: {result.get('message', 'Optimization applied')}",
                "details": result.get('details', {})
            })
        else:
            return jsonify({
                "success": False,
                "error": result.get('error', 'Failed to apply fix')
            }), 400

    except Exception as e:
        current_app.logger.exception("Error applying Facebook Ads fix")
        return jsonify({"success": False, "error": str(e)}), 500

def _apply_facebook_fix(access_token: str, action_type: str, entity_type: str, entity_id: str, params: dict) -> dict:
    """
    Apply a specific optimization fix via Facebook Graph API

    Action types:
    - adjust_budget: Modify campaign/adset budget
    - pause_entity: Pause campaign/adset/ad
    - enable_entity: Enable campaign/adset/ad
    - adjust_bid: Modify bid strategy or bid amount
    - update_schedule: Modify ad schedule
    - duplicate_winner: Duplicate high-performing ad
    """
    # Facebook-specific error code messages
    FB_ERROR_MESSAGES = {
        190: "Your Facebook connection has expired. Please reconnect.",
        200: "Permission denied by Facebook.",  # FB error code 200 means permission denied
        4: "Facebook rate limit reached — please try again in a few minutes.",
        10: "Permission denied. Make sure your Facebook App has ads_management permission.",
        100: "Invalid parameter sent to Facebook API.",
        368: "Your ad account has been flagged. Please check Facebook Ads Manager.",
    }

    def _parse_fb_response(resp, current_access_token: str, current_entity_id: str):
        """Parse a Facebook API response and return a structured result dict, or None if success."""
        try:
            data = resp.json()
        except Exception:
            data = {}

        fb_error = data.get('error', {})
        fb_code = fb_error.get('code')
        fb_msg = fb_error.get('message', resp.text)

        if not resp.ok or fb_code:
            user_msg = FB_ERROR_MESSAGES.get(fb_code, fb_msg or "Facebook API error")
            # For expired token (code 190), clear the stored token to force reconnect
            if fb_code == 190:
                try:
                    aid = current_account_id()
                    _clear_fb_token(aid)
                except Exception:
                    pass
            return {"success": False, "error": user_msg, "fb_code": fb_code}
        return None  # No error

    try:
        if action_type == 'adjust_budget':
            # Update budget for campaign or ad set
            budget_value = params.get('budget')
            if not budget_value:
                return {"success": False, "error": "Budget value required"}

            endpoint = f"{GRAPH}/{entity_id}"
            payload = {
                "access_token": access_token
            }

            if entity_type == 'campaign':
                payload['daily_budget'] = int(float(budget_value) * 100)  # Convert to cents
            elif entity_type == 'adset':
                payload['daily_budget'] = int(float(budget_value) * 100)

            resp = requests.post(endpoint, data=payload, timeout=30)
            err = _parse_fb_response(resp, access_token, entity_id)
            if err:
                return err
            return {
                "success": True,
                "message": f"Budget updated to ${budget_value}",
                "details": {"new_budget": budget_value}
            }

        elif action_type == 'pause_entity':
            # Pause campaign, ad set, or ad
            endpoint = f"{GRAPH}/{entity_id}"
            payload = {
                "access_token": access_token,
                "status": "PAUSED"
            }

            resp = requests.post(endpoint, data=payload, timeout=30)
            err = _parse_fb_response(resp, access_token, entity_id)
            if err:
                return err
            return {
                "success": True,
                "message": f"{entity_type.title()} paused successfully",
                "details": {"status": "PAUSED"}
            }

        elif action_type == 'enable_entity':
            # Enable campaign, ad set, or ad
            endpoint = f"{GRAPH}/{entity_id}"
            payload = {
                "access_token": access_token,
                "status": "ACTIVE"
            }

            resp = requests.post(endpoint, data=payload, timeout=30)
            err = _parse_fb_response(resp, access_token, entity_id)
            if err:
                return err
            return {
                "success": True,
                "message": f"{entity_type.title()} enabled successfully",
                "details": {"status": "ACTIVE"}
            }

        elif action_type == 'adjust_bid':
            # Update bid strategy or bid amount for ad set
            if entity_type != 'adset':
                return {"success": False, "error": "Bid adjustments only available for ad sets"}

            bid_strategy = params.get('bid_strategy')
            bid_amount = params.get('bid_amount')

            endpoint = f"{GRAPH}/{entity_id}"
            payload = {
                "access_token": access_token
            }

            if bid_strategy:
                payload['bid_strategy'] = bid_strategy
            if bid_amount:
                payload['bid_amount'] = int(float(bid_amount) * 100)  # Convert to cents

            resp = requests.post(endpoint, data=payload, timeout=30)
            err = _parse_fb_response(resp, access_token, entity_id)
            if err:
                return err
            return {
                "success": True,
                "message": "Bid strategy updated",
                "details": {"bid_strategy": bid_strategy, "bid_amount": bid_amount}
            }

        elif action_type == 'update_schedule':
            # Update ad schedule for ad set
            if entity_type != 'adset':
                return {"success": False, "error": "Schedule updates only available for ad sets"}

            schedule = params.get('schedule')
            if not schedule:
                return {"success": False, "error": "Schedule data required"}

            endpoint = f"{GRAPH}/{entity_id}"
            payload = {
                "access_token": access_token,
                "adset_schedule": schedule
            }

            resp = requests.post(endpoint, data=payload, timeout=30)
            err = _parse_fb_response(resp, access_token, entity_id)
            if err:
                return err
            return {
                "success": True,
                "message": "Ad schedule updated",
                "details": {"schedule": schedule}
            }

        elif action_type == 'duplicate_winner':
            # Duplicate a high-performing ad
            if entity_type != 'ad':
                return {"success": False, "error": "Duplication only available for ads"}

            # First fetch the ad details
            fetch_resp = requests.get(
                f"{GRAPH}/{entity_id}",
                params={
                    "access_token": access_token,
                    "fields": "name,adset_id,creative"
                },
                timeout=30
            )

            if fetch_resp.status_code != 200:
                return {"success": False, "error": "Failed to fetch ad details"}

            ad_data = fetch_resp.json()
            adset_id = ad_data.get('adset_id')

            # Create duplicate ad
            endpoint = f"{GRAPH}/{adset_id}/ads"
            payload = {
                "access_token": access_token,
                "name": f"{ad_data.get('name', 'Ad')} (Copy)",
                "creative": ad_data.get('creative'),
                "status": "PAUSED"  # Start paused for review
            }

            resp = requests.post(endpoint, data=payload, timeout=30)
            err = _parse_fb_response(resp, access_token, entity_id)
            if err:
                return err
            new_ad = resp.json()
            return {
                "success": True,
                "message": "Ad duplicated successfully (started paused)",
                "details": {"new_ad_id": new_ad.get('id')}
            }

        else:
            return {"success": False, "error": f"Unknown action type: {action_type}"}

    except Exception as e:
        current_app.logger.exception("Error in _apply_facebook_fix")
        return {"success": False, "error": str(e)}


