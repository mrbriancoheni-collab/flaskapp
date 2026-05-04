# app/marketing/__init__.py
"""
Marketing Command Center — all 10 cross-channel features.

Routes (prefix: /account/marketing):
  /cac               Cross-Channel CAC Dashboard
  /offline           Offline Channel Tracker (Billboard, Mail, Print, Radio)
  /attribution       Attribution Engine (Lead → Job → Revenue)
  /aggregators       Angi / HomeAdvisor / Thumbtack config + leads
  /optimizer         Channel Growth Optimizer
  /pacing            Monthly Budget Pacing (cross-channel)
  /revenue           Revenue & LTV Dashboard
  /reputation-impact Reputation → Lead Impact
  /seasonal          Seasonal Multi-Channel Budget Planner
"""
from __future__ import annotations

import logging
from calendar import monthrange
from datetime import date, datetime, timedelta
from functools import wraps
from typing import Any, Dict, List, Optional

from flask import (
    Blueprint, flash, jsonify, redirect, render_template,
    request, session, url_for,
)
from sqlalchemy import text

from app import db

log = logging.getLogger(__name__)

marketing_bp = Blueprint("marketing_bp", __name__, url_prefix="/account/marketing")

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

CHANNEL_META: Dict[str, Dict] = {
    "google_ads":   {"label": "Google Ads",        "icon": "fa-google",        "color": "blue"},
    "glsa":         {"label": "Google LSA",         "icon": "fa-shield-halved", "color": "green"},
    "facebook":     {"label": "Facebook Ads",       "icon": "fa-facebook",      "color": "indigo"},
    "yelp":         {"label": "Yelp Ads",           "icon": "fa-yelp",          "color": "red"},
    "networx":      {"label": "Networx",            "icon": "fa-bolt",          "color": "orange"},
    "elocal":       {"label": "eLocal",             "icon": "fa-phone",         "color": "cyan"},
    "angi":         {"label": "Angi",               "icon": "fa-hammer",        "color": "sky"},
    "homeadvisor":  {"label": "HomeAdvisor",        "icon": "fa-house",         "color": "teal"},
    "thumbtack":    {"label": "Thumbtack",          "icon": "fa-thumbtack",     "color": "purple"},
    "nextdoor":     {"label": "Nextdoor",           "icon": "fa-location-dot",  "color": "emerald"},
    "billboard":    {"label": "Billboard",          "icon": "fa-rectangle-ad",  "color": "yellow"},
    "direct_mail":  {"label": "Direct Mail",        "icon": "fa-envelope",      "color": "amber"},
    "print":        {"label": "Print / ValPak",     "icon": "fa-newspaper",     "color": "lime"},
    "radio":        {"label": "Radio",              "icon": "fa-radio",         "color": "pink"},
    "door_hanger":  {"label": "Door Hangers",       "icon": "fa-door-closed",   "color": "rose"},
    "vehicle_wrap": {"label": "Vehicle Wrap",       "icon": "fa-truck",         "color": "violet"},
    "other":        {"label": "Other",              "icon": "fa-circle-dot",    "color": "gray"},
}

AGGREGATOR_PLATFORMS = ["angi", "homeadvisor", "thumbtack", "nextdoor", "bark", "porch", "houzz"]

OFFLINE_CHANNELS = [
    "billboard", "direct_mail", "print", "radio", "door_hanger", "vehicle_wrap", "other"
]

ALL_CHANNELS = list(CHANNEL_META.keys())


def _date_range(days: int = 30):
    end = date.today()
    start = end - timedelta(days=days - 1)
    return start, end


def _spend_by_channel(aid: int, start: date, end: date) -> Dict[str, float]:
    """Pull digital spend from ad_spend + offline from offline_channel_spend."""
    result: Dict[str, float] = {}
    # Digital spend
    rows = db.session.execute(text("""
        SELECT source, COALESCE(SUM(amount),0) as total
        FROM ad_spend
        WHERE account_id=:a AND spend_date BETWEEN :s AND :e
        GROUP BY source
    """), {"a": aid, "s": start, "e": end}).fetchall()
    for r in rows:
        result[r[0]] = float(r[1])

    # Offline spend
    rows2 = db.session.execute(text("""
        SELECT channel_type, COALESCE(SUM(amount),0) as total
        FROM offline_channel_spend
        WHERE account_id=:a AND spend_date BETWEEN :s AND :e
        GROUP BY channel_type
    """), {"a": aid, "s": start, "e": end}).fetchall()
    for r in rows2:
        ch = r[0]
        result[ch] = result.get(ch, 0) + float(r[1])

    # Aggregator lead costs (treat as spend)
    rows3 = db.session.execute(text("""
        SELECT platform, COALESCE(SUM(lead_cost),0) as total
        FROM aggregator_leads
        WHERE account_id=:a AND occurred_at BETWEEN :s AND :e
        GROUP BY platform
    """), {"a": aid, "s": str(start) + " 00:00:00", "e": str(end) + " 23:59:59"}).fetchall()
    for r in rows3:
        ch = r[0]
        result[ch] = result.get(ch, 0) + float(r[1])

    return result


def _leads_by_channel(aid: int, start: date, end: date) -> Dict[str, Dict]:
    """Pull lead counts from lead_ingest + aggregator_leads."""
    result: Dict[str, Dict] = {}

    def _add(ch, total, booked, completed):
        if ch not in result:
            result[ch] = {"total": 0, "booked": 0, "completed": 0}
        result[ch]["total"] += total
        result[ch]["booked"] += booked
        result[ch]["completed"] += completed

    rows = db.session.execute(text("""
        SELECT source,
               COUNT(*) as total,
               SUM(CASE WHEN status IN ('booked','completed') THEN 1 ELSE 0 END) as booked,
               SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) as completed
        FROM lead_ingest
        WHERE account_id=:a AND created_at BETWEEN :s AND :e
        GROUP BY source
    """), {"a": aid, "s": str(start) + " 00:00:00", "e": str(end) + " 23:59:59"}).fetchall()
    for r in rows:
        _add(r[0], int(r[1]), int(r[2]), int(r[3]))

    rows2 = db.session.execute(text("""
        SELECT platform,
               COUNT(*) as total,
               SUM(CASE WHEN status IN ('booked','completed') THEN 1 ELSE 0 END) as booked,
               SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) as completed
        FROM aggregator_leads
        WHERE account_id=:a AND occurred_at BETWEEN :s AND :e
        GROUP BY platform
    """), {"a": aid, "s": str(start) + " 00:00:00", "e": str(end) + " 23:59:59"}).fetchall()
    for r in rows2:
        _add(r[0], int(r[1]), int(r[2]), int(r[3]))

    # Calls (from call_events, not duplicated in lead_ingest)
    rows3 = db.session.execute(text("""
        SELECT COUNT(*) as total,
               SUM(CASE WHEN is_qualified_lead=1 THEN 1 ELSE 0 END) as qualified
        FROM call_events
        WHERE account_id=:a AND call_started_at BETWEEN :s AND :e
          AND call_sid NOT IN (
            SELECT COALESCE(external_id,'__none__') FROM lead_ingest
            WHERE account_id=:a AND source='phone'
          )
    """), {"a": aid, "s": str(start) + " 00:00:00", "e": str(end) + " 23:59:59"}).fetchall()
    if rows3:
        r = rows3[0]
        total = int(r[0] or 0)
        qualified = int(r[1] or 0)
        if total:
            _add("phone", total, qualified, 0)

    return result


def _revenue_by_channel(aid: int, start: date, end: date) -> Dict[str, float]:
    """Revenue attributed to each channel via lead_job_links → servicetitan_jobs."""
    rows = db.session.execute(text("""
        SELECT li.source, COALESCE(SUM(ljl.revenue_cents),0) as rev
        FROM lead_job_links ljl
        JOIN lead_ingest li ON ljl.lead_source='lead_ingest' AND ljl.lead_id=li.id
        WHERE ljl.account_id=:a AND li.completed_at BETWEEN :s AND :e
        GROUP BY li.source
    """), {"a": aid, "s": str(start) + " 00:00:00", "e": str(end) + " 23:59:59"}).fetchall()
    result = {}
    for r in rows:
        result[r[0]] = float(r[1]) / 100.0
    return result


def _build_cac_table(aid: int, days: int = 30) -> List[Dict]:
    start, end = _date_range(days)
    spend = _spend_by_channel(aid, start, end)
    leads = _leads_by_channel(aid, start, end)
    revenue = _revenue_by_channel(aid, start, end)

    channels = set(list(spend.keys()) + list(leads.keys()))
    rows = []
    for ch in sorted(channels):
        sp = spend.get(ch, 0.0)
        ld = leads.get(ch, {})
        total_leads = ld.get("total", 0)
        booked = ld.get("booked", 0)
        completed = ld.get("completed", 0)
        rev = revenue.get(ch, 0.0)
        cpl = round(sp / total_leads, 2) if total_leads else None
        cac = round(sp / booked, 2) if booked else None
        roas = round(rev / sp, 2) if sp and rev else None
        meta = CHANNEL_META.get(ch, CHANNEL_META["other"])
        rows.append({
            "channel": ch,
            "label": meta["label"],
            "icon": meta["icon"],
            "color": meta["color"],
            "spend": sp,
            "total_leads": total_leads,
            "booked": booked,
            "completed": completed,
            "cpl": cpl,
            "cac": cac,
            "revenue": rev,
            "roas": roas,
        })

    # Sort by CAC ascending (lower is better); None last
    rows.sort(key=lambda x: (x["cac"] is None, x["cac"] or 9999))
    return rows


# ── 1. CAC Dashboard ───────────────────────────────────────────────────────────

@marketing_bp.get("/")
@login_required
def index():
    return redirect(url_for("marketing_bp.cac_dashboard"))


@marketing_bp.get("/cac")
@login_required
def cac_dashboard():
    aid = _account_id()
    days = int(request.args.get("days", 30))
    rows = _build_cac_table(aid, days)
    total_spend = sum(r["spend"] for r in rows)
    total_leads = sum(r["total_leads"] for r in rows)
    total_booked = sum(r["booked"] for r in rows)
    total_revenue = sum(r["revenue"] for r in rows)
    blended_cac = round(total_spend / total_booked, 2) if total_booked else None
    blended_cpl = round(total_spend / total_leads, 2) if total_leads else None
    return render_template(
        "marketing/cac.html",
        rows=rows,
        days=days,
        total_spend=total_spend,
        total_leads=total_leads,
        total_booked=total_booked,
        total_revenue=total_revenue,
        blended_cac=blended_cac,
        blended_cpl=blended_cpl,
        channel_meta=CHANNEL_META,
    )


# ── 2. Offline Channel Tracker ─────────────────────────────────────────────────

@marketing_bp.get("/offline")
@login_required
def offline_tracker():
    aid = _account_id()
    days = int(request.args.get("days", 90))
    start, end = _date_range(days)

    entries = db.session.execute(text("""
        SELECT id, channel_type, channel_label, spend_date, amount,
               tracking_number, estimated_reach, zone, promo_code, notes
        FROM offline_channel_spend
        WHERE account_id=:a AND spend_date BETWEEN :s AND :e
        ORDER BY spend_date DESC
    """), {"a": aid, "s": start, "e": end}).fetchall()

    totals_by_type = db.session.execute(text("""
        SELECT channel_type, COALESCE(SUM(amount),0) as total
        FROM offline_channel_spend
        WHERE account_id=:a AND spend_date BETWEEN :s AND :e
        GROUP BY channel_type
    """), {"a": aid, "s": start, "e": end}).fetchall()

    return render_template(
        "marketing/offline.html",
        entries=entries,
        totals_by_type={r[0]: float(r[1]) for r in totals_by_type},
        days=days,
        channel_meta=CHANNEL_META,
        offline_channels=OFFLINE_CHANNELS,
    )


@marketing_bp.post("/offline/add")
@login_required
def offline_add():
    aid = _account_id()
    f = request.form
    try:
        db.session.execute(text("""
            INSERT INTO offline_channel_spend
              (account_id, channel_type, channel_label, spend_date, amount,
               tracking_number, estimated_reach, zone, promo_code, notes)
            VALUES (:a, :ct, :cl, :sd, :amt, :tn, :er, :zone, :pc, :notes)
        """), {
            "a": aid,
            "ct": f.get("channel_type", "other"),
            "cl": f.get("channel_label", ""),
            "sd": f.get("spend_date", str(date.today())),
            "amt": float(f.get("amount", 0)),
            "tn": f.get("tracking_number") or None,
            "er": int(f.get("estimated_reach", 0)) or None,
            "zone": f.get("zone") or None,
            "pc": f.get("promo_code") or None,
            "notes": f.get("notes") or None,
        })
        db.session.commit()
        flash("Spend entry added.", "success")
    except Exception as e:
        db.session.rollback()
        log.exception("offline_add failed: %s", e)
        flash("Failed to save entry.", "danger")
    return redirect(url_for("marketing_bp.offline_tracker"))


@marketing_bp.post("/offline/<int:entry_id>/delete")
@login_required
def offline_delete(entry_id: int):
    aid = _account_id()
    db.session.execute(text(
        "DELETE FROM offline_channel_spend WHERE id=:id AND account_id=:a"
    ), {"id": entry_id, "a": aid})
    db.session.commit()
    return redirect(url_for("marketing_bp.offline_tracker"))


# ── 3. Attribution Engine ──────────────────────────────────────────────────────

@marketing_bp.get("/attribution")
@login_required
def attribution():
    aid = _account_id()
    days = int(request.args.get("days", 30))
    start, end = _date_range(days)

    # Funnel by source from lead_ingest
    funnel = db.session.execute(text("""
        SELECT source,
               COUNT(*) as total,
               SUM(CASE WHEN contacted_at IS NOT NULL THEN 1 ELSE 0 END) as contacted,
               SUM(CASE WHEN status IN ('booked','completed') THEN 1 ELSE 0 END) as booked,
               SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) as completed,
               COALESCE(SUM(lead_cost),0) as total_cost
        FROM lead_ingest
        WHERE account_id=:a AND created_at BETWEEN :s AND :e
        GROUP BY source
        ORDER BY total DESC
    """), {"a": aid, "s": str(start) + " 00:00:00", "e": str(end) + " 23:59:59"}).fetchall()

    # Revenue linked to jobs
    rev_by_source = _revenue_by_channel(aid, start, end)

    # ServiceTitan revenue summary (if available)
    try:
        st_summary = db.session.execute(text("""
            SELECT job_type_name,
                   COUNT(*) as jobs,
                   COALESCE(SUM(total),0) as revenue
            FROM servicetitan_jobs
            WHERE account_id=:a AND completed_on BETWEEN :s AND :e
              AND status IN ('Completed','Done')
            GROUP BY job_type_name
            ORDER BY revenue DESC
            LIMIT 10
        """), {"a": aid, "s": start, "e": end}).fetchall()
    except Exception:
        st_summary = []

    return render_template(
        "marketing/attribution.html",
        funnel=funnel,
        rev_by_source=rev_by_source,
        st_summary=st_summary,
        days=days,
        channel_meta=CHANNEL_META,
    )


# ── 4. Aggregators ─────────────────────────────────────────────────────────────

@marketing_bp.get("/aggregators")
@login_required
def aggregators():
    aid = _account_id()

    configs = db.session.execute(text("""
        SELECT platform, platform_label, platform_account_id,
               default_lead_cost, is_active, notes
        FROM aggregator_accounts
        WHERE account_id=:a
    """), {"a": aid}).fetchall()
    config_map = {r[0]: dict(r._mapping) for r in configs}

    days = int(request.args.get("days", 30))
    start, end = _date_range(days)
    lead_stats = db.session.execute(text("""
        SELECT platform,
               COUNT(*) as total,
               SUM(CASE WHEN status IN ('booked','completed') THEN 1 ELSE 0 END) as booked,
               COALESCE(SUM(lead_cost),0) as spend
        FROM aggregator_leads
        WHERE account_id=:a AND occurred_at BETWEEN :s AND :e
        GROUP BY platform
    """), {"a": aid, "s": str(start) + " 00:00:00", "e": str(end) + " 23:59:59"}).fetchall()
    stats_map = {r[0]: dict(r._mapping) for r in lead_stats}

    return render_template(
        "marketing/aggregators.html",
        platforms=AGGREGATOR_PLATFORMS,
        config_map=config_map,
        stats_map=stats_map,
        days=days,
        channel_meta=CHANNEL_META,
    )


@marketing_bp.post("/aggregators/save")
@login_required
def aggregators_save():
    aid = _account_id()
    platform = request.form.get("platform", "")
    if platform not in AGGREGATOR_PLATFORMS:
        flash("Unknown platform.", "danger")
        return redirect(url_for("marketing_bp.aggregators"))
    try:
        db.session.execute(text("""
            INSERT INTO aggregator_accounts
              (account_id, platform, platform_label, platform_account_id, default_lead_cost, is_active, notes)
            VALUES (:a, :p, :pl, :pid, :dlc, :active, :notes)
            ON DUPLICATE KEY UPDATE
              platform_label=VALUES(platform_label),
              platform_account_id=VALUES(platform_account_id),
              default_lead_cost=VALUES(default_lead_cost),
              is_active=VALUES(is_active),
              notes=VALUES(notes),
              updated_at=NOW()
        """), {
            "a": aid,
            "p": platform,
            "pl": request.form.get("platform_label") or None,
            "pid": request.form.get("platform_account_id") or None,
            "dlc": float(request.form.get("default_lead_cost", 0) or 0),
            "active": 1 if request.form.get("is_active") else 0,
            "notes": request.form.get("notes") or None,
        })
        db.session.commit()
        flash(f"{platform.title()} config saved.", "success")
    except Exception as e:
        db.session.rollback()
        log.exception("aggregators_save failed: %s", e)
        flash("Save failed.", "danger")
    return redirect(url_for("marketing_bp.aggregators"))


# ── 5. Channel Growth Optimizer ────────────────────────────────────────────────

@marketing_bp.get("/optimizer")
@login_required
def optimizer():
    aid = _account_id()
    days = int(request.args.get("days", 30))
    rows = _build_cac_table(aid, days)

    # Build recommendations
    recommendations = []
    if rows:
        valid = [r for r in rows if r["cac"] is not None and r["spend"] > 0]
        if valid:
            best = min(valid, key=lambda x: x["cac"])
            worst = max(valid, key=lambda x: x["cac"])
            if best != worst:
                recommendations.append({
                    "type": "invest",
                    "channel": best["label"],
                    "icon": best["icon"],
                    "color": "green",
                    "message": f"Your lowest CAC is {best['label']} at ${best['cac']:.0f}/job. "
                               f"Increasing budget here will generate the cheapest new jobs.",
                    "action": "Increase budget",
                })
                recommendations.append({
                    "type": "cut",
                    "channel": worst["label"],
                    "icon": worst["icon"],
                    "color": "red",
                    "message": f"{worst['label']} has your highest CAC at ${worst['cac']:.0f}/job "
                               f"({round(worst['cac']/best['cac'], 1)}x more expensive than {best['label']}). "
                               f"Consider reallocating this budget.",
                    "action": "Reduce or pause",
                })

        # Channels with spend but zero booked leads
        no_convert = [r for r in rows if r["spend"] > 50 and r["booked"] == 0]
        for nc in no_convert:
            recommendations.append({
                "type": "investigate",
                "channel": nc["label"],
                "icon": nc["icon"],
                "color": "yellow",
                "message": f"{nc['label']} spent ${nc['spend']:.0f} but booked 0 jobs. "
                           f"Review targeting, landing pages, and lead follow-up.",
                "action": "Investigate",
            })

    return render_template(
        "marketing/optimizer.html",
        rows=rows,
        recommendations=recommendations,
        days=days,
        channel_meta=CHANNEL_META,
    )


# ── 6. Budget Pacing ───────────────────────────────────────────────────────────

@marketing_bp.get("/pacing")
@login_required
def pacing():
    aid = _account_id()
    today = date.today()
    month_start = today.replace(day=1)
    _, days_in_month = monthrange(today.year, today.month)
    day_of_month = today.day
    pct_through_month = round(day_of_month / days_in_month * 100, 1)

    # Actual spend this month per channel
    actual_spend = {}
    rows = db.session.execute(text("""
        SELECT source, COALESCE(SUM(amount),0) as total
        FROM ad_spend
        WHERE account_id=:a AND spend_date >= :ms
        GROUP BY source
    """), {"a": aid, "ms": month_start}).fetchall()
    for r in rows:
        actual_spend[r[0]] = float(r[1])

    rows2 = db.session.execute(text("""
        SELECT channel_type, COALESCE(SUM(amount),0) as total
        FROM offline_channel_spend
        WHERE account_id=:a AND spend_date >= :ms
        GROUP BY channel_type
    """), {"a": aid, "ms": month_start}).fetchall()
    for r in rows2:
        ch = r[0]
        actual_spend[ch] = actual_spend.get(ch, 0) + float(r[1])

    # Budgets for this month
    budgets = db.session.execute(text("""
        SELECT channel, budget_cents
        FROM channel_monthly_budgets
        WHERE account_id=:a AND budget_month=:m
    """), {"a": aid, "m": month_start}).fetchall()
    budget_map = {r[0]: r[1] / 100.0 for r in budgets}

    # Build pacing rows
    pacing_rows = []
    all_channels = set(list(actual_spend.keys()) + list(budget_map.keys()))
    for ch in sorted(all_channels):
        spent = actual_spend.get(ch, 0.0)
        budget = budget_map.get(ch, 0.0)
        meta = CHANNEL_META.get(ch, CHANNEL_META["other"])
        expected_spend = budget * (day_of_month / days_in_month) if budget else None
        pace_pct = round(spent / expected_spend * 100, 1) if expected_spend else None
        projected = round(spent / day_of_month * days_in_month, 2) if spent and day_of_month else None
        overspend = max(0, (projected or 0) - budget) if budget else None
        pacing_rows.append({
            "channel": ch,
            "label": meta["label"],
            "icon": meta["icon"],
            "color": meta["color"],
            "spent": spent,
            "budget": budget,
            "expected_spend": expected_spend,
            "pace_pct": pace_pct,
            "projected": projected,
            "overspend": overspend,
            "spend_pct": round(spent / budget * 100, 1) if budget else None,
        })

    total_spent = sum(r["spent"] for r in pacing_rows)
    total_budget = sum(r["budget"] for r in pacing_rows)

    return render_template(
        "marketing/pacing.html",
        pacing_rows=pacing_rows,
        total_spent=total_spent,
        total_budget=total_budget,
        day_of_month=day_of_month,
        days_in_month=days_in_month,
        pct_through_month=pct_through_month,
        month_label=today.strftime("%B %Y"),
        all_channels=ALL_CHANNELS,
        channel_meta=CHANNEL_META,
    )


@marketing_bp.post("/pacing/save")
@login_required
def pacing_save():
    aid = _account_id()
    today = date.today()
    month_start = today.replace(day=1)
    # Accept JSON: { channel: amount_dollars }
    data = request.get_json(silent=True) or {}
    try:
        for ch, amount in data.items():
            cents = int(float(amount) * 100)
            db.session.execute(text("""
                INSERT INTO channel_monthly_budgets (account_id, channel, budget_month, budget_cents)
                VALUES (:a, :c, :m, :cents)
                ON DUPLICATE KEY UPDATE budget_cents=VALUES(budget_cents), updated_at=NOW()
            """), {"a": aid, "c": ch, "m": month_start, "cents": cents})
        db.session.commit()
        return jsonify({"ok": True})
    except Exception as e:
        db.session.rollback()
        log.exception("pacing_save failed: %s", e)
        return jsonify({"error": str(e)}), 400


# ── 7. Revenue & LTV Dashboard ─────────────────────────────────────────────────

@marketing_bp.get("/revenue")
@login_required
def revenue_ltv():
    aid = _account_id()
    days = int(request.args.get("days", 90))
    start, end = _date_range(days)

    # Revenue from ServiceTitan
    try:
        by_type = db.session.execute(text("""
            SELECT job_type_name,
                   COUNT(*) as jobs,
                   COALESCE(SUM(total),0) as revenue,
                   COALESCE(AVG(total),0) as avg_ticket
            FROM servicetitan_jobs
            WHERE account_id=:a AND completed_on BETWEEN :s AND :e
              AND status IN ('Completed','Done')
            GROUP BY job_type_name
            ORDER BY revenue DESC
            LIMIT 15
        """), {"a": aid, "s": start, "e": end}).fetchall()

        totals = db.session.execute(text("""
            SELECT COUNT(*) as jobs,
                   COALESCE(SUM(total),0) as revenue,
                   COALESCE(AVG(total),0) as avg_ticket,
                   COUNT(DISTINCT customer_id) as unique_customers
            FROM servicetitan_jobs
            WHERE account_id=:a AND completed_on BETWEEN :s AND :e
              AND status IN ('Completed','Done')
        """), {"a": aid, "s": start, "e": end}).fetchone()

        # Repeat customers (more than 1 job in period)
        repeat = db.session.execute(text("""
            SELECT COUNT(*) FROM (
                SELECT customer_id FROM servicetitan_jobs
                WHERE account_id=:a AND completed_on BETWEEN :s AND :e
                  AND status IN ('Completed','Done')
                  AND customer_id IS NOT NULL
                GROUP BY customer_id HAVING COUNT(*)>1
            ) sub
        """), {"a": aid, "s": start, "e": end}).scalar() or 0

        # Monthly revenue trend (last 6 months)
        monthly = db.session.execute(text("""
            SELECT DATE_FORMAT(completed_on,'%%Y-%%m') as mon,
                   COALESCE(SUM(total),0) as revenue,
                   COUNT(*) as jobs
            FROM servicetitan_jobs
            WHERE account_id=:a AND completed_on >= DATE_SUB(CURDATE(), INTERVAL 6 MONTH)
              AND status IN ('Completed','Done')
            GROUP BY mon ORDER BY mon
        """), {"a": aid}).fetchall()
        has_st = True
    except Exception:
        by_type = []
        totals = None
        repeat = 0
        monthly = []
        has_st = False

    return render_template(
        "marketing/revenue.html",
        by_type=by_type,
        totals=totals,
        repeat=repeat,
        monthly=monthly,
        has_st=has_st,
        days=days,
    )


# ── 8. Reputation → Lead Impact ────────────────────────────────────────────────

@marketing_bp.get("/reputation-impact")
@login_required
def reputation_impact():
    aid = _account_id()
    days = int(request.args.get("days", 90))
    start, end = _date_range(days)

    # Review counts over time
    try:
        review_trend = db.session.execute(text("""
            SELECT DATE_FORMAT(created_at,'%%Y-%%m-%%d') as day,
                   COUNT(*) as reviews,
                   AVG(rating) as avg_rating
            FROM review_requests
            WHERE account_id=:a AND status='sent'
              AND created_at BETWEEN :s AND :e
            GROUP BY day ORDER BY day
        """), {"a": aid, "s": str(start) + " 00:00:00", "e": str(end) + " 23:59:59"}).fetchall()
    except Exception:
        review_trend = []

    # Lead volume over same period
    try:
        lead_trend = db.session.execute(text("""
            SELECT DATE_FORMAT(created_at,'%%Y-%%m-%%d') as day, COUNT(*) as leads
            FROM lead_ingest
            WHERE account_id=:a AND created_at BETWEEN :s AND :e
            GROUP BY day ORDER BY day
        """), {"a": aid, "s": str(start) + " 00:00:00", "e": str(end) + " 23:59:59"}).fetchall()
    except Exception:
        lead_trend = []

    # GBP insights (impressions from GMB, if available)
    try:
        gbp_trend = db.session.execute(text("""
            SELECT DATE_FORMAT(period_start,'%%Y-%%m') as mon,
                   SUM(searches) as searches, SUM(views) as views,
                   SUM(direction_requests) as directions, SUM(calls) as calls
            FROM gmb_insights
            WHERE account_id=:a AND period_start >= :s
            GROUP BY mon ORDER BY mon
        """), {"a": aid, "s": start}).fetchall()
    except Exception:
        gbp_trend = []

    return render_template(
        "marketing/reputation_impact.html",
        review_trend=review_trend,
        lead_trend=lead_trend,
        gbp_trend=gbp_trend,
        days=days,
    )


# ── 9. Seasonal Budget Planner ─────────────────────────────────────────────────

@marketing_bp.get("/seasonal")
@login_required
def seasonal():
    aid = _account_id()
    year = int(request.args.get("year", date.today().year))

    plans = db.session.execute(text("""
        SELECT channel, jan_cents, feb_cents, mar_cents, apr_cents, may_cents, jun_cents,
               jul_cents, aug_cents, sep_cents, oct_cents, nov_cents, dec_cents
        FROM seasonal_budget_plans
        WHERE account_id=:a AND plan_year=:y
    """), {"a": aid, "y": year}).fetchall()
    plan_map = {r[0]: [r[i+1]/100.0 for i in range(12)] for r in plans}

    # Historical monthly actual spend for comparison
    hist = {}
    try:
        rows = db.session.execute(text("""
            SELECT MONTH(spend_date) as m, COALESCE(SUM(amount),0) as total
            FROM ad_spend
            WHERE account_id=:a AND YEAR(spend_date)=:y
            GROUP BY m
        """), {"a": aid, "y": year}).fetchall()
        for r in rows:
            hist[int(r[0])-1] = float(r[1])
    except Exception:
        pass

    MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]

    return render_template(
        "marketing/seasonal.html",
        plan_map=plan_map,
        hist=hist,
        months=MONTHS,
        year=year,
        all_channels=ALL_CHANNELS,
        channel_meta=CHANNEL_META,
    )


@marketing_bp.post("/seasonal/save")
@login_required
def seasonal_save():
    aid = _account_id()
    data = request.get_json(silent=True) or {}
    year = int(data.get("year", date.today().year))
    plans = data.get("plans", {})  # { channel: [jan$, feb$, ...12 months] }
    MONTH_COLS = ["jan","feb","mar","apr","may","jun","jul","aug","sep","oct","nov","dec"]
    try:
        for ch, amounts in plans.items():
            if len(amounts) != 12:
                continue
            vals = {f"{m}_cents": int(float(v) * 100) for m, v in zip(MONTH_COLS, amounts)}
            db.session.execute(text(f"""
                INSERT INTO seasonal_budget_plans
                  (account_id, plan_year, channel,
                   jan_cents, feb_cents, mar_cents, apr_cents, may_cents, jun_cents,
                   jul_cents, aug_cents, sep_cents, oct_cents, nov_cents, dec_cents)
                VALUES
                  (:a, :y, :c,
                   :jan_cents, :feb_cents, :mar_cents, :apr_cents, :may_cents, :jun_cents,
                   :jul_cents, :aug_cents, :sep_cents, :oct_cents, :nov_cents, :dec_cents)
                ON DUPLICATE KEY UPDATE
                  jan_cents=VALUES(jan_cents), feb_cents=VALUES(feb_cents),
                  mar_cents=VALUES(mar_cents), apr_cents=VALUES(apr_cents),
                  may_cents=VALUES(may_cents), jun_cents=VALUES(jun_cents),
                  jul_cents=VALUES(jul_cents), aug_cents=VALUES(aug_cents),
                  sep_cents=VALUES(sep_cents), oct_cents=VALUES(oct_cents),
                  nov_cents=VALUES(nov_cents), dec_cents=VALUES(dec_cents),
                  updated_at=NOW()
            """), {"a": aid, "y": year, "c": ch, **vals})
        db.session.commit()
        return jsonify({"ok": True})
    except Exception as e:
        db.session.rollback()
        log.exception("seasonal_save failed: %s", e)
        return jsonify({"error": str(e)}), 400


# ── API: lead → job attribution ────────────────────────────────────────────────

@marketing_bp.post("/attribution/link")
@login_required
def attribution_link():
    """Link a lead to a ServiceTitan job for revenue attribution."""
    aid = _account_id()
    d = request.get_json(silent=True) or {}
    try:
        db.session.execute(text("""
            INSERT INTO lead_job_links
              (account_id, lead_source, lead_id, st_job_id, st_job_external_id, revenue_cents, job_type)
            VALUES (:a, :ls, :lid, :jid, :ejid, :rev, :jt)
        """), {
            "a": aid,
            "ls": d.get("lead_source", "lead_ingest"),
            "lid": int(d.get("lead_id", 0)),
            "jid": d.get("st_job_id"),
            "ejid": d.get("st_job_external_id"),
            "rev": int(float(d.get("revenue", 0)) * 100),
            "jt": d.get("job_type"),
        })
        db.session.commit()
        return jsonify({"ok": True})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 400


# ── Public webhook: Aggregator lead intake ─────────────────────────────────────
# External platforms (Angi, HomeAdvisor, Thumbtack, etc.) POST leads here.
# No login required — validated by webhook secret.

@marketing_bp.post("/webhooks/aggregator/<platform>")
def aggregator_webhook(platform: str):
    """
    Accept inbound leads from lead aggregators.
    Validates via ?secret=X against the stored webhook_secret for this account+platform.
    """
    if platform not in AGGREGATOR_PLATFORMS:
        return jsonify({"error": "unknown platform"}), 404

    secret = request.args.get("secret", "")
    if not secret:
        return jsonify({"error": "missing secret"}), 401

    # Find the aggregator account by secret
    try:
        row = db.session.execute(text("""
            SELECT account_id, default_lead_cost
            FROM aggregator_accounts
            WHERE platform=:p AND webhook_secret=:s AND is_active=1
            LIMIT 1
        """), {"p": platform, "s": secret}).fetchone()
    except Exception:
        row = None

    if not row:
        return jsonify({"error": "invalid secret"}), 401

    aid = row[0]
    default_cost = float(row[1] or 0)

    payload = request.get_json(silent=True) or request.form.to_dict()

    # Normalize common field names across platforms
    name = (payload.get("name") or payload.get("customer_name") or
            payload.get("firstName", "") + " " + payload.get("lastName", "")).strip()
    phone = payload.get("phone") or payload.get("phone_number") or payload.get("phoneNumber")
    email = payload.get("email") or payload.get("emailAddress")
    service = payload.get("service") or payload.get("service_type") or payload.get("serviceType")
    city = payload.get("city") or payload.get("serviceCity")
    zip_code = payload.get("zip") or payload.get("postalCode") or payload.get("zipCode")
    lead_cost = float(payload.get("lead_cost") or payload.get("leadCost") or default_cost or 0)
    external_id = str(payload.get("id") or payload.get("lead_id") or payload.get("leadId") or "")

    try:
        db.session.execute(text("""
            INSERT INTO aggregator_leads
              (account_id, platform, external_lead_id, name, phone, email,
               service_type, city, zip, lead_cost, status, occurred_at, raw)
            VALUES (:a, :p, :eid, :name, :phone, :email,
                    :svc, :city, :zip, :cost, 'new', NOW(), :raw)
        """), {
            "a": aid, "p": platform,
            "eid": external_id or None,
            "name": name or None,
            "phone": phone or None,
            "email": email or None,
            "svc": service or None,
            "city": city or None,
            "zip": zip_code or None,
            "cost": lead_cost,
            "raw": str(payload),
        })
        db.session.commit()
        log.info("Aggregator lead from %s for account %d: %s", platform, aid, name)
        return jsonify({"ok": True}), 200
    except Exception as e:
        db.session.rollback()
        log.exception("aggregator_webhook failed for %s: %s", platform, e)
        return jsonify({"error": "ingestion failed"}), 500
