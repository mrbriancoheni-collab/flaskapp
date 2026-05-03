# app/lead_inbox/__init__.py
"""
Universal Lead Inbox — aggregates leads from every source into one pipeline view.

Sources merged:
  LeadIngest   — Networx, eLocal, webform, phone (direct DB table)
  GLSALead     — Google Local Services Ads
  YelpLead     — Yelp
  FBLead       — Facebook Lead Forms
  CallEvent    — Twilio tracked calls (qualified only, not already in LeadIngest)

Routes:
  GET  /account/leads          — inbox kanban / list view
  GET  /account/leads/<id>     — lead detail JSON (for modal)
  POST /account/leads/<id>/status — update status (delegates to lead_intake_bp)
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from flask import (
    Blueprint, jsonify, redirect, render_template, request, session, url_for,
)
from sqlalchemy import text

from app import db

log = logging.getLogger(__name__)

lead_inbox_bp = Blueprint("lead_inbox_bp", __name__)

# ── Auth helpers ───────────────────────────────────────────────────────────────

def _current_account_id() -> Optional[int]:
    aid = session.get("account_id") or session.get("aid")
    if aid:
        try:
            return int(aid)
        except Exception:
            pass
    uid = session.get("user_id")
    if not uid:
        return None
    try:
        row = db.session.execute(
            text("SELECT account_id FROM users WHERE id=:id"), {"id": uid}
        ).fetchone()
        return int(row[0]) if row else None
    except Exception:
        return None


def _login_required(f):
    from functools import wraps
    @wraps(f)
    def wrapper(*a, **kw):
        if not _current_account_id():
            return redirect(url_for("auth_bp.login", next=request.path))
        return f(*a, **kw)
    return wrapper


# ── Data aggregation ───────────────────────────────────────────────────────────

SOURCE_LABELS = {
    "networx":  {"label": "Networx",  "color": "blue",   "icon": "fa-bolt"},
    "elocal":   {"label": "eLocal",   "color": "orange", "icon": "fa-phone"},
    "glsa":     {"label": "GLSA",     "color": "green",  "icon": "fa-google"},
    "yelp":     {"label": "Yelp",     "color": "red",    "icon": "fa-yelp"},
    "facebook": {"label": "Facebook", "color": "indigo", "icon": "fa-facebook"},
    "phone":    {"label": "Call",     "color": "purple", "icon": "fa-phone-volume"},
    "webform":  {"label": "Web Form", "color": "teal",   "icon": "fa-globe"},
    "other":    {"label": "Other",    "color": "gray",   "icon": "fa-circle"},
}

STATUSES = ["new", "contacted", "booked", "completed", "lost"]


def _fetch_lead_ingest(account_id: int, days: int) -> List[Dict[str, Any]]:
    from app.models_tooling import LeadIngest
    cutoff = datetime.utcnow() - timedelta(days=days)
    rows = LeadIngest.query.filter(
        LeadIngest.account_id == account_id,
        LeadIngest.created_at >= cutoff,
    ).order_by(LeadIngest.created_at.desc()).all()
    out = []
    for r in rows:
        src = SOURCE_LABELS.get(r.source, SOURCE_LABELS["other"])
        out.append({
            "id": f"li_{r.id}",
            "raw_id": r.id,
            "source_key": r.source,
            "source_label": src["label"],
            "source_color": src["color"],
            "source_icon": src["icon"],
            "name": r.name or "Unknown",
            "phone": r.phone,
            "email": r.email,
            "city": r.city,
            "service_type": r.service_type,
            "lead_cost": float(r.lead_cost) if r.lead_cost else None,
            "status": r.status,
            "occurred_at": r.occurred_at or r.created_at,
            "notes": r.job_notes,
            "_type": "lead_ingest",
        })
    return out


def _fetch_glsa_leads(account_id: int, days: int) -> List[Dict[str, Any]]:
    try:
        from app.models_glsa import GLSALead
        cutoff = datetime.utcnow() - timedelta(days=days)
        rows = GLSALead.query.filter(
            GLSALead.account_id == account_id,
            GLSALead.created_at >= cutoff,
        ).order_by(GLSALead.created_at.desc()).all()
        src = SOURCE_LABELS["glsa"]
        return [{
            "id": f"glsa_{r.id}",
            "raw_id": r.id,
            "source_key": "glsa",
            "source_label": src["label"],
            "source_color": src["color"],
            "source_icon": src["icon"],
            "name": r.name or "Unknown",
            "phone": r.phone,
            "email": r.email,
            "city": r.city,
            "service_type": r.job_type,
            "lead_cost": None,
            "status": "new",
            "occurred_at": r.lead_ts or r.created_at,
            "notes": None,
            "_type": "glsa",
        } for r in rows]
    except Exception:
        return []


def _fetch_yelp_leads(account_id: int, days: int) -> List[Dict[str, Any]]:
    try:
        from app.models_yelp import YelpLead
        cutoff = datetime.utcnow() - timedelta(days=days)
        rows = YelpLead.query.filter(
            YelpLead.account_id == account_id,
            YelpLead.created_at >= cutoff,
        ).order_by(YelpLead.created_at.desc()).all()
        src = SOURCE_LABELS["yelp"]
        return [{
            "id": f"yelp_{r.id}",
            "raw_id": r.id,
            "source_key": "yelp",
            "source_label": src["label"],
            "source_color": src["color"],
            "source_icon": src["icon"],
            "name": r.customer_name or "Unknown",
            "phone": r.customer_phone,
            "email": r.customer_email,
            "city": None,
            "service_type": r.service_requested,
            "lead_cost": None,
            "status": "new",
            "occurred_at": r.created_at,
            "notes": r.message,
            "_type": "yelp",
        } for r in rows]
    except Exception:
        return []


def _fetch_fb_leads(account_id: int, days: int) -> List[Dict[str, Any]]:
    try:
        from app.models_fbads import FBLead
        cutoff = datetime.utcnow() - timedelta(days=days)
        rows = FBLead.query.filter(
            FBLead.account_id == account_id,
            FBLead.created_at >= cutoff,
        ).order_by(FBLead.created_at.desc()).all()
        src = SOURCE_LABELS["facebook"]
        out = []
        for r in rows:
            fd = r.field_data or {}
            out.append({
                "id": f"fb_{r.id}",
                "raw_id": r.id,
                "source_key": "facebook",
                "source_label": src["label"],
                "source_color": src["color"],
                "source_icon": src["icon"],
                "name": fd.get("full_name") or fd.get("name") or "Unknown",
                "phone": fd.get("phone_number") or fd.get("phone"),
                "email": fd.get("email"),
                "city": fd.get("city"),
                "service_type": fd.get("service") or fd.get("job_type"),
                "lead_cost": None,
                "status": "new",
                "occurred_at": r.created_at,
                "notes": None,
                "_type": "facebook",
            })
        return out
    except Exception:
        return []


def _fetch_qualified_calls(account_id: int, days: int) -> List[Dict[str, Any]]:
    """Qualified Twilio calls not already captured as a LeadIngest record."""
    try:
        from app.models_calls import CallEvent
        from app.models_tooling import LeadIngest
        cutoff = datetime.utcnow() - timedelta(days=days)

        # phones already in LeadIngest so we don't double-count
        existing_phones = {
            r[0] for r in db.session.execute(
                text("SELECT DISTINCT phone FROM lead_ingest WHERE account_id=:aid AND phone IS NOT NULL"),
                {"aid": account_id},
            ).fetchall()
        }

        rows = CallEvent.query.filter(
            CallEvent.account_id == account_id,
            CallEvent.is_qualified_lead == True,
            CallEvent.created_at >= cutoff,
        ).order_by(CallEvent.created_at.desc()).all()

        src = SOURCE_LABELS["phone"]
        out = []
        for r in rows:
            if r.from_number and r.from_number in existing_phones:
                continue
            out.append({
                "id": f"call_{r.id}",
                "raw_id": r.id,
                "source_key": "phone",
                "source_label": src["label"],
                "source_color": src["color"],
                "source_icon": src["icon"],
                "name": f"{r.caller_city or ''} {r.caller_state or ''}".strip() or "Unknown",
                "phone": r.from_number,
                "email": None,
                "city": r.caller_city,
                "service_type": r.campaign_name,
                "lead_cost": None,
                "status": "new",
                "occurred_at": r.created_at,
                "notes": f"Call duration: {r.call_duration}s · Campaign: {r.campaign_name}",
                "_type": "call",
            })
        return out
    except Exception:
        return []


def _aggregate_leads(account_id: int, days: int = 30) -> List[Dict[str, Any]]:
    all_leads = (
        _fetch_lead_ingest(account_id, days)
        + _fetch_glsa_leads(account_id, days)
        + _fetch_yelp_leads(account_id, days)
        + _fetch_fb_leads(account_id, days)
        + _fetch_qualified_calls(account_id, days)
    )
    all_leads.sort(key=lambda x: x["occurred_at"] or datetime.min, reverse=True)
    return all_leads


# ── Routes ─────────────────────────────────────────────────────────────────────

@lead_inbox_bp.route("/account/leads")
@_login_required
def inbox():
    account_id = _current_account_id()
    days = int(request.args.get("days", 30))
    source_filter = request.args.get("source", "all")

    leads = _aggregate_leads(account_id, days)

    if source_filter != "all":
        leads = [l for l in leads if l["source_key"] == source_filter]

    # Group by status for kanban
    kanban: Dict[str, List] = {s: [] for s in STATUSES}
    for lead in leads:
        bucket = lead["status"] if lead["status"] in kanban else "new"
        kanban[bucket].append(lead)

    # Summary stats
    total = len(leads)
    new_count = len(kanban["new"])
    booked_count = len(kanban["booked"]) + len(kanban["completed"])
    total_cost = sum(l["lead_cost"] or 0 for l in leads)

    # Source breakdown for filter pills
    source_counts: Dict[str, int] = {}
    for l in leads:
        source_counts[l["source_key"]] = source_counts.get(l["source_key"], 0) + 1

    return render_template(
        "lead_inbox/index.html",
        leads=leads,
        kanban=kanban,
        statuses=STATUSES,
        total=total,
        new_count=new_count,
        booked_count=booked_count,
        total_cost=total_cost,
        days=days,
        source_filter=source_filter,
        source_counts=source_counts,
        source_labels=SOURCE_LABELS,
    )


@lead_inbox_bp.route("/account/leads/<lead_id>")
@_login_required
def lead_detail(lead_id: str):
    """Return lead detail as JSON for modal."""
    account_id = _current_account_id()

    if lead_id.startswith("li_"):
        from app.models_tooling import LeadIngest
        raw_id = int(lead_id[3:])
        r = LeadIngest.query.filter_by(id=raw_id, account_id=account_id).first_or_404()
        src = SOURCE_LABELS.get(r.source, SOURCE_LABELS["other"])
        return jsonify({
            "id": lead_id,
            "source_label": src["label"],
            "name": r.name,
            "phone": r.phone,
            "email": r.email,
            "city": r.city,
            "service_type": r.service_type,
            "lead_cost": float(r.lead_cost) if r.lead_cost else None,
            "status": r.status,
            "notes": r.job_notes,
            "occurred_at": r.occurred_at.isoformat() if r.occurred_at else None,
            "raw": r.raw,
        })

    return jsonify({"error": "detail not available for this source type"}), 200
