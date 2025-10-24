# app/yelp/__init__.py
from __future__ import annotations

import os
import json
import time
from datetime import datetime
from typing import Optional, Dict, Any, List

import requests
from flask import (
    Blueprint, render_template, request, url_for, flash, current_app, session
)
from flask import redirect as _redirect
from sqlalchemy import text

from app.models_yelp import YelpAccount, YelpLead, YelpProfile
from app import db
from app.auth.utils import login_required, is_paid_account

yelp_bp = Blueprint("yelp_bp", __name__, template_folder="../../templates")

# ---------- helpers ----------

def see_other(endpoint: str, **values):
    return _redirect(url_for(endpoint, **values), code=303)

def _account_id() -> Optional[int]:
    aid = session.get("account_id") or session.get("aid")
    if aid:
        try:
            return int(aid)
        except Exception:
            pass
    uid = session.get("user_id")
    if not uid:
        return None
    row = db.session.execute(
        text("SELECT account_id FROM users WHERE id=:id"),
        {"id": uid},
    ).fetchone()
    return int(row[0]) if row and row[0] is not None else None

def _openai_key() -> Optional[str]:
    return os.getenv("OPENAI_API_KEY") or (getattr(current_app, "config", {}) or {}).get("OPENAI_API_KEY")

def _ensure_token(acct: YelpAccount) -> Optional[str]:
    """
    Yelp Fusion typically uses a static API key (Bearer token).
    If you prefer storing user-entered keys, this returns that.
    """
    if not acct:
        return None
    return acct.access_token or os.getenv("YELP_API_KEY")

# ---------- placeholder Yelp API calls (replace with real endpoints if available) ----------

def _fetch_yelp_leads(access_token: str) -> List[Dict[str, Any]]:
    """
    Yelp doesn't expose a public 'leads inbox' for SMBs via Fusion. We simulate a few.
    """
    now = datetime.utcnow()
    return [
        {
            "id": f"yelp-sim-{int(time.time())}-1",
            "name": "Maria Lopez",
            "phone": "+1 408 555 2201",
            "message": "Need a water heater inspection this week.",
            "city": "San Jose, CA",
            "lead_ts": now.isoformat() + "Z",
            "raw": {"simulated": True},
        },
        {
            "id": f"yelp-sim-{int(time.time())}-2",
            "name": "Chris Young",
            "phone": "+1 415 555 2219",
            "message": "Kitchen sink leak under the cabinet.",
            "city": "San Francisco, CA",
            "lead_ts": now.isoformat() + "Z",
            "raw": {"simulated": True},
        },
    ]

def _fetch_yelp_profiles(access_token: str) -> List[Dict[str, Any]]:
    """
    Simulate 1–N business profiles tied to the Yelp business account.
    """
    return [
        {
            "profile_id": "yelp-sim-profile-1",
            "business_name": "Ace Plumbing Co.",
            "description": "Local, licensed plumbers. Same-day service.",
            "categories": ["Plumbing", "Water Heater Installation/Repair"],
            "service_areas": ["San Francisco", "Daly City", "San Bruno"],
            "phone": "+1 415 555 0100",
            "website": "https://aceplumbing.example.com",
            "hours": {"mon_fri": "8am-6pm", "sat": "9am-3pm", "sun": "closed"},
            "raw": {"simulated": True},
        }
    ]

def _apply_yelp_profile_updates(access_token: str, profile_id: str, updates: Dict[str, Any]) -> bool:
    """
    Placeholder: Log and pretend success. Replace with Yelp Ads/partner API if available.
    """
    current_app.logger.info("Would apply Yelp updates to %s: %s", profile_id, json.dumps(updates)[:400])
    return True

# ---------- AI helpers ----------

def _ai_suggest_profile_optimizations(profile: Dict[str, Any], objective: str = "lead_gen") -> Dict[str, Any]:
    """
    Suggest improved description, categories, and service_areas using ChatGPT.
    Keeps JSON-output only; has a heuristic fallback.
    """
    api_key = _openai_key()
    system = (
        "You are a Yelp profile optimization expert for local businesses. "
        "Return STRICT JSON with keys: description (string), categories (array of strings), "
        "service_areas (array of strings). Make copy high-converting and concise."
    )
    user = {
        "objective": objective,
        "profile": profile,
        "rules": [
            "Description: 1–3 sentences with trust signals (licensed/insured, reviews).",
            "Categories: 2–5 relevant Yelp-style categories.",
            "Service areas: 3–8 realistic cities/areas.",
            "No commentary; JSON only."
        ]
    }

    if api_key:
        try:
            resp = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": (getattr(current_app, "config", {}) or {}).get("OPENAI_MODEL", "gpt-4o-mini"),
                    "temperature": 0.4,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": json.dumps(user)},
                    ],
                    "response_format": {"type": "json_object"},
                },
                timeout=60,
            )
            if resp.status_code < 400:
                data = resp.json()["choices"][0]["message"]["content"]
                return json.loads(data)
            current_app.logger.error("OpenAI error %s: %s", resp.status_code, resp.text[:400])
        except Exception:
            current_app.logger.exception("OpenAI request failed (Yelp optimize)")

    # Fallback
    desc = profile.get("description") or ""
    bn = profile.get("business_name") or "Our company"
    base = f"{bn}: fast, reliable, licensed & insured. Transparent pricing with 5★ reviews."
    if desc and len(desc) < 220:
        base = f"{desc} We’re licensed & insured with 5★ reviews."
    return {
        "description": base[:400],
        "categories": profile.get("categories") or ["Plumbing"],
        "service_areas": profile.get("service_areas") or ["Primary City"],
    }

# ---------- routes ----------

@yelp_bp.route("/", methods=["GET"], endpoint="index")
@login_required
def index():
    """
    Primary Yelp page — API key connect + choose task (Review Leads / Optimize Profiles).
    """
    aid = _account_id()
    acct = YelpAccount.query.filter_by(account_id=aid).order_by(YelpAccount.id.desc()).first()
    return render_template("yelp/index.html", acct=acct)

@yelp_bp.route("/connect", methods=["POST"], endpoint="connect")
@login_required
def connect():
    """
    Store a Yelp API key for this account (mimics OAuth 'connect').
    Accepts: api_key form field (fallback to env YELP_API_KEY if blank).
    """
    aid = _account_id()
    api_key = (request.form.get("api_key") or "").strip() or os.getenv("YELP_API_KEY")
    if not api_key:
        flash("Provide a Yelp API Key (or set YELP_API_KEY in env).", "error")
        return see_other("yelp_bp.index")

    acct = YelpAccount(account_id=aid, access_token=api_key, token_expiry=None)
    try:
        db.session.add(acct)
        db.session.commit()
        flash("Yelp connected.", "success")
    except Exception:
        current_app.logger.exception("Saving YelpAccount failed (migrate models?)")
        flash("Connected (temp), but DB save failed. Check Yelp tables/migrations.", "warning")

    return see_other("yelp_bp.index")

@yelp_bp.route("/leads", methods=["GET"], endpoint="leads")
@login_required
def leads():
    """List simulated Yelp leads and persist a snapshot."""
    aid = _account_id()
    acct = YelpAccount.query.filter_by(account_id=aid).order_by(YelpAccount.id.desc()).first()
    if not acct:
        flash("Connect Yelp first.", "error")
        return see_other("yelp_bp.index")

    token = _ensure_token(acct)
    if not token:
        flash("No Yelp API key present.", "error")
        return see_other("yelp_bp.index")

    api_leads = _fetch_yelp_leads(token)

    # Save snapshot
    for L in api_leads:
        try:
            exists = YelpLead.query.filter_by(account_id=aid, external_id=L["id"]).first()
            if not exists:
                db.session.add(
                    YelpLead(
                        account_id=aid,
                        external_id=L["id"],
                        name=L.get("name"),
                        phone=L.get("phone"),
                        message=L.get("message"),
                        city=L.get("city"),
                        lead_ts=datetime.fromisoformat(L["lead_ts"].replace("Z", "+00:00")) if L.get("lead_ts") else None,
                        raw=L,
                    )
                )
        except Exception:
            current_app.logger.exception("Saving YelpLead failed")
    try:
        db.session.commit()
    except Exception:
        pass

    return render_template("yelp/leads.html", acct=acct, leads=api_leads)

@yelp_bp.route("/optimize", methods=["GET"], endpoint="optimize")
@login_required
def optimize():
    """Show profiles and inline AI suggestions."""
    aid = _account_id()
    acct = YelpAccount.query.filter_by(account_id=aid).order_by(YelpAccount.id.desc()).first()
    if not acct:
        flash("Connect Yelp first.", "error")
        return see_other("yelp_bp.index")

    token = _ensure_token(acct)
    if not token:
        flash("No Yelp API key present.", "error")
        return see_other("yelp_bp.index")

    profiles = _fetch_yelp_profiles(token)

    # Best-effort cache
    for p in profiles:
        try:
            row = YelpProfile.query.filter_by(account_id=aid, profile_id=p["profile_id"]).first()
            if not row:
                row = YelpProfile(
                    account_id=aid,
                    profile_id=p["profile_id"],
                    business_name=p.get("business_name"),
                    description=p.get("description"),
                    categories=p.get("categories"),
                    service_areas=p.get("service_areas"),
                    phone=p.get("phone"),
                    website=p.get("website"),
                    hours=p.get("hours"),
                    raw=p,
                )
                db.session.add(row)
            else:
                row.business_name = p.get("business_name")
                row.description = p.get("description")
                row.categories = p.get("categories")
                row.service_areas = p.get("service_areas")
                row.phone = p.get("phone")
                row.website = p.get("website")
                row.hours = p.get("hours")
                row.raw = p
        except Exception:
            current_app.logger.exception("Saving YelpProfile failed")
    try:
        db.session.commit()
    except Exception:
        pass

    return render_template("yelp/optimize.html", acct=acct, profiles=profiles)

@yelp_bp.route("/optimize/suggest", methods=["POST"], endpoint="optimize_suggest")
@login_required
def optimize_suggest():
    """
    Generate AI suggestions for a given profile.
    Paid-gated: only the AI action is restricted, the page itself is open to all logged-in users.
    """
    if not is_paid_account():
        flash("AI suggestions are available on paid plans. Upgrade to continue.", "warning")
        return see_other("yelp_bp.optimize")

    aid = _account_id()
    profile_id = request.form.get("profile_id")
    objective = (request.form.get("objective") or "Lead Generation").strip().lower()
    objective_map = {"lead generation": "lead_gen", "sales": "sales", "awareness": "awareness", "retention": "retention"}
    objective = objective_map.get(objective, "lead_gen")

    acct = YelpAccount.query.filter_by(account_id=aid).order_by(YelpAccount.id.desc()).first()
    if not acct:
        flash("Connect Yelp first.", "error")
        return see_other("yelp_bp.optimize")

    token = _ensure_token(acct)
    if not token:
        flash("No Yelp API key present.", "error")
        return see_other("yelp_bp.optimize")

    profiles = _fetch_yelp_profiles(token)
    profile = next((p for p in profiles if p.get("profile_id") == profile_id), None)
    if not profile:
        flash("Profile not found.", "error")
        return see_other("yelp_bp.optimize")

    suggestions = _ai_suggest_profile_optimizations(profile, objective=objective)
    flash("AI suggestions ready. Review and apply below.", "success")
    return render_template("yelp/optimize.html", acct=acct, profiles=profiles, suggestions={profile_id: suggestions})

@yelp_bp.route("/optimize/apply", methods=["POST"], endpoint="optimize_apply")
@login_required
def optimize_apply():
    aid = _account_id()
    profile_id = request.form.get("profile_id")
    approved_desc = request.form.get("approved_description") or ""
    approved_categories = [s.strip() for s in (request.form.get("approved_categories") or "").split(",") if s.strip()]
    approved_areas = [s.strip() for s in (request.form.get("approved_service_areas") or "").split(",") if s.strip()]

    acct = YelpAccount.query.filter_by(account_id=aid).order_by(YelpAccount.id.desc()).first()
    if not acct:
        flash("Connect Yelp first.", "error")
        return see_other("yelp_bp.optimize")

    token = _ensure_token(acct)
    if not token:
        flash("No Yelp API key present.", "error")
        return see_other("yelp_bp.optimize")

    updates = {
        "description": approved_desc,
        "categories": approved_categories,
        "service_areas": approved_areas,
    }
    ok = _apply_yelp_profile_updates(token, profile_id, updates)
    if ok:
        flash("Yelp profile updates applied (simulated).", "success")
    else:
        flash("Could not apply updates.", "error")
    return see_other("yelp_bp.optimize")
