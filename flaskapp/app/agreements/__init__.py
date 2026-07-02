# app/agreements/__init__.py
"""
Service Agreements — track recurring maintenance plans and their contribution
to revenue.  Works with or without ServiceTitan.

Routes (prefix: /account/agreements):
  GET  /                    — dashboard (active plans, renewals, MRR)
  GET  /new                 — add agreement form
  POST /new                 — save new agreement
  GET  /<id>/edit           — edit agreement
  POST /<id>/edit           — save edits
  POST /<id>/delete         — soft-delete (cancel)
  GET  /export.csv          — CSV export of all active agreements
  POST /notify/<id>         — send renewal reminder SMS/email
"""
from __future__ import annotations

import csv
import io
import logging
import os
from datetime import date, datetime, timedelta
from functools import wraps
from typing import Any, Dict, List, Optional

from flask import (
    Blueprint, flash, make_response, redirect, render_template,
    request, session, url_for,
)
from sqlalchemy import text

from app import db

log = logging.getLogger(__name__)

agreements_bp = Blueprint("agreements_bp", __name__, url_prefix="/account/agreements")

PLAN_TYPES = ["annual", "monthly", "biannual", "quarterly"]
SERVICE_TYPES = [
    ("hvac",        "HVAC"),
    ("plumbing",    "Plumbing"),
    ("electrical",  "Electrical"),
    ("pest",        "Pest Control"),
    ("landscaping", "Landscaping"),
    ("roofing",     "Roofing"),
    ("other",       "Other"),
]
STATUSES = ["active", "pending_renewal", "expired", "cancelled"]


# ── Auth ───────────────────────────────────────────────────────────────────────

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
    try:
        row = db.session.execute(
            text("SELECT account_id FROM users WHERE id=:id"), {"id": uid}
        ).fetchone()
        return int(row[0]) if row else None
    except Exception:
        return None


def login_required(f):
    @wraps(f)
    def wrapper(*a, **kw):
        if not _account_id():
            return redirect(url_for("auth_bp.login", next=request.path))
        return f(*a, **kw)
    return wrapper


# ── Helpers ────────────────────────────────────────────────────────────────────

def _fetch_agreements(aid: int, status: Optional[str] = None) -> List[Dict]:
    where = "account_id = :a"
    params: Dict[str, Any] = {"a": aid}
    if status:
        where += " AND status = :s"
        params["s"] = status
    rows = db.session.execute(text(f"""
        SELECT id, customer_name, customer_phone, customer_email, customer_address,
               plan_name, plan_type, service_type, monthly_value, annual_value,
               start_date, renewal_date, status, st_customer_id, notes, created_at
        FROM service_agreements
        WHERE {where}
        ORDER BY renewal_date ASC
    """), params).fetchall()
    return [dict(r._mapping) for r in rows]


def _agreement_stats(aid: int) -> Dict[str, Any]:
    row = db.session.execute(text("""
        SELECT
          COUNT(*) as total,
          SUM(CASE WHEN status='active' THEN 1 ELSE 0 END) as active_count,
          SUM(CASE WHEN status='active' THEN monthly_value ELSE 0 END) as mrr,
          SUM(CASE WHEN status='active' THEN annual_value ELSE 0 END) as arr,
          SUM(CASE WHEN status='pending_renewal' THEN 1 ELSE 0 END) as pending_renewal,
          SUM(CASE WHEN renewal_date BETWEEN CURDATE() AND DATE_ADD(CURDATE(), INTERVAL 30 DAY)
                   AND status='active' THEN 1 ELSE 0 END) as renewing_soon
        FROM service_agreements
        WHERE account_id = :a
    """), {"a": aid}).fetchone()
    if row:
        return dict(row._mapping)
    return {"total": 0, "active_count": 0, "mrr": 0, "arr": 0,
            "pending_renewal": 0, "renewing_soon": 0}


def _send_renewal_sms(agreement: Dict, account_id: int) -> bool:
    """Send a renewal reminder SMS via Twilio."""
    phone = agreement.get("customer_phone", "")
    if not phone:
        return False
    try:
        import requests as req
        sid = os.getenv("TWILIO_ACCOUNT_SID")
        tok = os.getenv("TWILIO_AUTH_TOKEN")
        from_num = os.getenv("TWILIO_FROM_NUMBER")
        if not (sid and tok and from_num):
            log.info("Simulated renewal SMS to %s for %s", phone, agreement["plan_name"])
            return True
        renewal_date = agreement["renewal_date"]
        if hasattr(renewal_date, "strftime"):
            renewal_date = renewal_date.strftime("%B %d, %Y")
        body = (
            f"Hi {agreement['customer_name'].split()[0]}, your {agreement['plan_name']} "
            f"renews on {renewal_date}. Reply STOP to opt out or call us to discuss."
        )
        url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
        req.post(url, data={"From": from_num, "To": phone, "Body": body},
                 auth=(sid, tok), timeout=10)
        return True
    except Exception:
        log.exception("Renewal SMS failed for agreement %s", agreement.get("id"))
        return False


# ── Routes ─────────────────────────────────────────────────────────────────────

@agreements_bp.get("/")
@login_required
def index():
    aid = _account_id()
    status_filter = request.args.get("status", "")
    all_agreements = _fetch_agreements(aid, status_filter or None)
    stats = _agreement_stats(aid)

    # Segment for template
    renewing_soon = [
        a for a in all_agreements
        if a["status"] == "active"
        and a["renewal_date"]
        and (a["renewal_date"] - date.today()).days <= 30
    ]
    return render_template(
        "agreements/index.html",
        agreements=all_agreements,
        stats=stats,
        renewing_soon=renewing_soon,
        status_filter=status_filter,
        statuses=STATUSES,
        service_types=SERVICE_TYPES,
        today=date.today(),
    )


@agreements_bp.get("/new")
@login_required
def new_form():
    return render_template(
        "agreements/form.html",
        agreement=None,
        plan_types=PLAN_TYPES,
        service_types=SERVICE_TYPES,
        today=date.today(),
    )


@agreements_bp.post("/new")
@login_required
def create():
    aid = _account_id()
    f = request.form
    try:
        monthly_value = float(f.get("monthly_value") or 0)
        annual_value = float(f.get("annual_value") or 0)
        if not annual_value and monthly_value:
            annual_value = monthly_value * 12
        if not monthly_value and annual_value:
            monthly_value = round(annual_value / 12, 2)

        db.session.execute(text("""
            INSERT INTO service_agreements
              (account_id, customer_name, customer_phone, customer_email,
               customer_address, plan_name, plan_type, service_type,
               monthly_value, annual_value, start_date, renewal_date, status,
               st_customer_id, notes)
            VALUES
              (:a, :cn, :cp, :ce, :ca, :pn, :pt, :st,
               :mv, :av, :sd, :rd, :stat, :stcid, :notes)
        """), {
            "a": aid,
            "cn": f.get("customer_name", "").strip(),
            "cp": f.get("customer_phone", "").strip() or None,
            "ce": f.get("customer_email", "").strip() or None,
            "ca": f.get("customer_address", "").strip() or None,
            "pn": f.get("plan_name", "").strip(),
            "pt": f.get("plan_type", "annual"),
            "st": f.get("service_type") or None,
            "mv": monthly_value,
            "av": annual_value,
            "sd": f.get("start_date") or date.today().isoformat(),
            "rd": f.get("renewal_date"),
            "stat": f.get("status", "active"),
            "stcid": f.get("st_customer_id", "").strip() or None,
            "notes": f.get("notes", "").strip() or None,
        })
        db.session.commit()
        flash("Agreement saved.", "success")
    except Exception:
        log.exception("Failed to create agreement")
        db.session.rollback()
        flash("Failed to save agreement.", "danger")
    return redirect(url_for("agreements_bp.index"))


@agreements_bp.get("/<int:agreement_id>/edit")
@login_required
def edit_form(agreement_id: int):
    aid = _account_id()
    row = db.session.execute(text("""
        SELECT id, customer_name, customer_phone, customer_email, customer_address,
               plan_name, plan_type, service_type, monthly_value, annual_value,
               start_date, renewal_date, status, st_customer_id, notes
        FROM service_agreements
        WHERE id=:id AND account_id=:a
    """), {"id": agreement_id, "a": aid}).fetchone()
    if not row:
        flash("Agreement not found.", "warning")
        return redirect(url_for("agreements_bp.index"))
    return render_template(
        "agreements/form.html",
        agreement=dict(row._mapping),
        plan_types=PLAN_TYPES,
        service_types=SERVICE_TYPES,
        today=date.today(),
    )


@agreements_bp.post("/<int:agreement_id>/edit")
@login_required
def update(agreement_id: int):
    aid = _account_id()
    f = request.form
    try:
        monthly_value = float(f.get("monthly_value") or 0)
        annual_value = float(f.get("annual_value") or 0)
        if not annual_value and monthly_value:
            annual_value = monthly_value * 12
        if not monthly_value and annual_value:
            monthly_value = round(annual_value / 12, 2)

        db.session.execute(text("""
            UPDATE service_agreements
            SET customer_name=:cn, customer_phone=:cp, customer_email=:ce,
                customer_address=:ca, plan_name=:pn, plan_type=:pt,
                service_type=:st, monthly_value=:mv, annual_value=:av,
                start_date=:sd, renewal_date=:rd, status=:stat,
                st_customer_id=:stcid, notes=:notes
            WHERE id=:id AND account_id=:a
        """), {
            "cn": f.get("customer_name", "").strip(),
            "cp": f.get("customer_phone", "").strip() or None,
            "ce": f.get("customer_email", "").strip() or None,
            "ca": f.get("customer_address", "").strip() or None,
            "pn": f.get("plan_name", "").strip(),
            "pt": f.get("plan_type", "annual"),
            "st": f.get("service_type") or None,
            "mv": monthly_value,
            "av": annual_value,
            "sd": f.get("start_date"),
            "rd": f.get("renewal_date"),
            "stat": f.get("status", "active"),
            "stcid": f.get("st_customer_id", "").strip() or None,
            "notes": f.get("notes", "").strip() or None,
            "id": agreement_id,
            "a": aid,
        })
        db.session.commit()
        flash("Agreement updated.", "success")
    except Exception:
        log.exception("Failed to update agreement")
        db.session.rollback()
        flash("Failed to update agreement.", "danger")
    return redirect(url_for("agreements_bp.index"))


@agreements_bp.post("/<int:agreement_id>/delete")
@login_required
def delete(agreement_id: int):
    aid = _account_id()
    try:
        db.session.execute(text("""
            UPDATE service_agreements SET status='cancelled'
            WHERE id=:id AND account_id=:a
        """), {"id": agreement_id, "a": aid})
        db.session.commit()
        flash("Agreement cancelled.", "info")
    except Exception:
        db.session.rollback()
        flash("Failed to cancel agreement.", "danger")
    return redirect(url_for("agreements_bp.index"))


@agreements_bp.get("/export.csv")
@login_required
def export_csv():
    aid = _account_id()
    rows = _fetch_agreements(aid)
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=[
        "id", "customer_name", "customer_phone", "customer_email",
        "plan_name", "plan_type", "service_type",
        "monthly_value", "annual_value", "start_date", "renewal_date", "status", "notes"
    ])
    writer.writeheader()
    for row in rows:
        writer.writerow({k: row.get(k, "") for k in writer.fieldnames})
    resp = make_response(output.getvalue())
    resp.headers["Content-Type"] = "text/csv"
    resp.headers["Content-Disposition"] = (
        f"attachment; filename=agreements_{date.today().isoformat()}.csv"
    )
    return resp


@agreements_bp.post("/notify/<int:agreement_id>")
@login_required
def send_renewal_notice(agreement_id: int):
    aid = _account_id()
    row = db.session.execute(text("""
        SELECT id, customer_name, customer_phone, plan_name, renewal_date
        FROM service_agreements
        WHERE id=:id AND account_id=:a
    """), {"id": agreement_id, "a": aid}).fetchone()
    if not row:
        flash("Agreement not found.", "warning")
        return redirect(url_for("agreements_bp.index"))
    success = _send_renewal_sms(dict(row._mapping), aid)
    if success:
        flash(f"Renewal reminder sent to {row.customer_name}.", "success")
    else:
        flash("Could not send reminder — no phone number on file.", "warning")
    return redirect(url_for("agreements_bp.index"))
