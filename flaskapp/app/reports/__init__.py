# app/reports/__init__.py
from __future__ import annotations

from typing import Any, Dict, Optional

from flask import Blueprint, render_template, current_app, flash, redirect, url_for, request
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app import db

# --------- Auth helpers (use real ones if available) ---------
try:
    from app.auth.utils import login_required, current_account_id  # type: ignore
except Exception:  # pragma: no cover
    from functools import wraps
    from flask import session

    def login_required(fn):
        @wraps(fn)
        def wrapper(*a, **k):
            if not (session.get("user_id") or session.get("uid")):
                return redirect(url_for("auth_bp.login", next=request.path))
            return fn(*a, **k)
        return wrapper

    def current_account_id() -> Optional[int]:
        uid = (session.get("user_id") or session.get("uid"))
        if not uid:
            return None
        try:
            with db.engine.connect() as conn:
                row = conn.execute(
                    text("SELECT account_id FROM users WHERE id=:id"),
                    {"id": uid},
                ).first()
                return int(row[0]) if row else None
        except Exception:
            return None


reports_bp = Blueprint("reports_bp", __name__, url_prefix="/account/reports")


# =========================
# ===== DB UTILITIES  =====
# =========================

def _google_connected(aid: int, product: str) -> Optional[Dict[str, Any]]:
    """
    Return minimal row if a token exists for the product, else None.
    IMPORTANT: Do not select columns that may not exist (e.g., 'email').
    """
    try:
        with db.engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT id, product FROM google_oauth_tokens "
                    "WHERE account_id=:aid AND product=:p LIMIT 1"
                ),
                {"aid": aid, "p": product},
            ).mappings().first()
            return dict(row) if row else None
    except SQLAlchemyError as e:
        current_app.logger.warning("reports._google_connected failed: %s", e)
        return None


def _is_connected(aid: int, product: str) -> bool:
    return _google_connected(aid, product) is not None


def _fb_account(aid: int) -> Optional[Dict[str, Any]]:
    try:
        with db.engine.connect() as conn:
            row = conn.execute(
                text("SELECT fb_account_id, name FROM fb_accounts WHERE account_id=:aid LIMIT 1"),
                {"aid": aid},
            ).mappings().first()
            return dict(row) if row else None
    except SQLAlchemyError as e:
        current_app.logger.warning("reports._fb_account failed: %s", e)
        return None


def _wp_site(aid: int) -> Optional[Dict[str, Any]]:
    try:
        with db.engine.connect() as conn:
            row = conn.execute(
                text("SELECT base, site_name FROM wp_sites WHERE account_id=:aid ORDER BY id DESC LIMIT 1"),
                {"aid": aid},
            ).mappings().first()
            return dict(row) if row else None
    except SQLAlchemyError as e:
        current_app.logger.warning("reports._wp_site failed: %s", e)
        return None


def _connected_map(aid: Optional[int]) -> Dict[str, bool]:
    """
    Returns a dict of booleans for each channel, safely false if no account id.
    """
    if not aid:
        return {"ga": False, "gsc": False, "ads": False, "gmb": False, "lsa": False}
    return {
        "ga": _is_connected(aid, "ga"),
        "gsc": _is_connected(aid, "gsc"),
        "ads": _is_connected(aid, "ads"),
        "gmb": _is_connected(aid, "gmb"),
        "lsa": _is_connected(aid, "lsa"),
    }


# =========================
# ===== SAMPLE DATA    ====
# =========================

SAMPLE_GA = {
    "property_name": "Demo Property (GA4)",
    "period": "Last 28 days",
    "sessions": 4280,
    "users": 3675,
    "new_users": 3012,
    "engaged_sessions": 2890,
    "avg_engagement_time": "0m:58s",
    "conversions": 196,
    "revenue": 18420.00,
    "notes": "Traffic stable week-over-week; engagement improved after hero CTA update.",
    "wow_sessions_delta": 6.2,
    "wow_conv_delta": 9.8,
}

SAMPLE_GSC = {
    "site": "https://example.com/",
    "period": "Last 28 days",
    "clicks": 3120,
    "impressions": 142500,
    "ctr": 2.19,
    "position": 14.6,
    "top_queries": [
        {"q": "emergency plumber", "clicks": 460, "position": 6.4},
        {"q": "water heater install", "clicks": 380, "position": 8.2},
        {"q": "plumber near me", "clicks": 295, "position": 10.1},
    ],
    "notes": "Clicks rose after adding FAQ schema to service pages.",
    "wow_clicks_delta": 5.4,
    "wow_ctr_delta": 0.2,
}

SAMPLE_CARDS = [
    {
        "product": "ads",
        "title": "Google Ads",
        "connected": False,
        "data": {
            "account_name": "Demo Plumbing Co.",
            "period": "Last 30 days",
            "spend": 4210.77,
            "clicks": 1980,
            "impr": 88400,
            "conv": 146,
            "cpa": 28.82,
            "roas": 5.1,
            "highlights": [
                "Emergency campaign drove 62% of conversions with 18% lower CPA.",
                "Added negatives: free, diy — cut wasted spend by ~8%.",
            ],
        },
    },
    {
        "product": "gmb",
        "title": "Business Profile",
        "connected": False,
        "data": {
            "location": "Clean Finish Cleaning Service",
            "period": "Last 30 days",
            "profile_views": 6240,
            "calls": 132,
            "directions": 88,
            "website_visits": 410,
            "reviews": {"new": 23, "avg_rating": 4.8},
            "notes": "Photos updated 2 weeks ago; +11% profile views WoW.",
        },
    },
    {
        "product": "lsa",
        "title": "Local Services Ads",
        "connected": False,
        "data": {
            "business": "Demo Plumbing Co.",
            "period": "Last 30 days",
            "leads": 74,
            "booked": 29,
            "avg_cost_per_lead": 42.10,
            "disputes": {"filed": 2, "won": 1},
            "notes": "Peak lead volume on Mondays; consider bid adjustments Fri–Sun.",
        },
    },
]


# =========================
# ===== ROUTES         ====
# =========================

@reports_bp.route("/", methods=["GET"], endpoint="index")
@login_required
def index():
    """
    Account Reports landing: high-level GA + GSC + insights from connected accounts.
    Falls back to sample data if not connected.
    """
    aid = current_account_id()
    connected = _connected_map(aid)

    ga = SAMPLE_GA
    gsc = SAMPLE_GSC

    cards = []
    for c in SAMPLE_CARDS:
        c2 = dict(c)
        c2["connected"] = bool(connected.get(c["product"], False))
        cards.append(c2)

    return render_template(
        "reports/index.html",
        connected=connected,
        ga=ga,
        gsc=gsc,
        cards=cards,
        epn=request.endpoint,
    )


@reports_bp.route("/cpl", methods=["GET"], endpoint="cpl_dashboard")
@login_required
def cpl_dashboard():
    """Cross-source ROI: spend, leads, CPL, booking rate, revenue by channel."""
    from datetime import datetime, timedelta
    from decimal import Decimal

    aid = current_account_id()
    days = int(request.args.get("days", 30))
    cutoff = datetime.utcnow() - timedelta(days=days)

    # ── Source metadata ──────────────────────────────────────────────────────
    SOURCE_META = {
        "networx":    {"label": "Networx",       "icon": "fa-bolt",       "color": "blue"},
        "elocal":     {"label": "eLocal",         "icon": "fa-phone",      "color": "orange"},
        "glsa":       {"label": "GLSA",           "icon": "fa-google",     "color": "green"},
        "google-ads": {"label": "Google Ads",     "icon": "fa-google",     "color": "blue"},
        "facebook":   {"label": "Facebook Ads",   "icon": "fa-facebook",   "color": "indigo"},
        "yelp":       {"label": "Yelp",           "icon": "fa-yelp",       "color": "red"},
        "phone":      {"label": "Direct Calls",   "icon": "fa-phone",      "color": "purple"},
        "webform":    {"label": "Web Form",       "icon": "fa-globe",      "color": "teal"},
    }

    is_sample = False
    rows_map: dict = {}  # source -> {spend, leads, booked, revenue}

    def _bucket(src):
        rows_map.setdefault(src, {"spend": 0.0, "leads": 0, "booked": 0, "revenue": 0.0})
        return rows_map[src]

    # ── Lead counts from LeadIngest ──────────────────────────────────────────
    try:
        with db.engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT source, COUNT(*) as cnt, "
                "SUM(CASE WHEN status IN ('booked','completed') THEN 1 ELSE 0 END) as booked, "
                "SUM(COALESCE(lead_cost, 0)) as total_cost "
                "FROM lead_ingest WHERE account_id=:aid AND created_at>=:cutoff GROUP BY source"
            ), {"aid": aid, "cutoff": cutoff}).fetchall()
            for r in rows:
                b = _bucket(r[0])
                b["leads"] += int(r[1])
                b["booked"] += int(r[2])
                b["spend"] += float(r[3] or 0)
    except Exception as exc:
        current_app.logger.warning("cpl_dashboard lead_ingest query failed: %s", exc)

    # ── Spend from AdSpend table (covers Google Ads, GLSA, etc.) ────────────
    try:
        with db.engine.connect() as conn:
            spend_rows = conn.execute(text(
                "SELECT source, SUM(amount) FROM ad_spend "
                "WHERE account_id=:aid AND spend_date>=:cutoff GROUP BY source"
            ), {"aid": aid, "cutoff": cutoff.date()}).fetchall()
            for src, amt in spend_rows:
                _bucket(src)["spend"] += float(amt or 0)
    except Exception as exc:
        current_app.logger.warning("cpl_dashboard ad_spend query failed: %s", exc)

    # ── Revenue from CRM jobs ─────────────────────────────────────────────────
    try:
        with db.engine.connect() as conn:
            rev_rows = conn.execute(text(
                "SELECT lead_source, SUM(revenue_cents)/100.0 "
                "FROM crm_jobs WHERE account_id=:aid AND job_date>=:cutoff "
                "AND job_status='completed' GROUP BY lead_source"
            ), {"aid": aid, "cutoff": cutoff.date()}).fetchall()
            for src, rev in rev_rows:
                if src:
                    _bucket(src.lower().replace(" ", "-"))["revenue"] += float(rev or 0)
    except Exception as exc:
        current_app.logger.warning("cpl_dashboard crm_jobs query failed: %s", exc)

    # ── Fall back to sample data if nothing real ─────────────────────────────
    if not rows_map:
        is_sample = True
        rows_map = {
            "google-ads": {"spend": 1200, "leads": 38, "booked": 12, "revenue": 8400},
            "glsa":       {"spend": 780,  "leads": 22, "booked": 9,  "revenue": 6300},
            "networx":    {"spend": 450,  "leads": 10, "booked": 4,  "revenue": 2800},
            "elocal":     {"spend": 280,  "leads": 8,  "booked": 3,  "revenue": 2100},
            "yelp":       {"spend": 0,    "leads": 5,  "booked": 1,  "revenue": 700},
        }

    # ── Build display rows ───────────────────────────────────────────────────
    display_rows = []
    for src, data in sorted(rows_map.items(), key=lambda x: -x[1]["leads"]):
        meta = SOURCE_META.get(src, {"label": src.replace("-", " ").title(), "icon": "fa-circle", "color": "gray"})
        leads = data["leads"]
        booked = data["booked"]
        spend = data["spend"]
        revenue = data["revenue"]
        cpl = spend / leads if leads and spend else None
        book_rate = booked / leads if leads else None
        roas = revenue / spend if spend else None
        display_rows.append({
            "source": src,
            "label": meta["label"],
            "icon": meta["icon"],
            "color": meta["color"],
            "leads": leads,
            "booked": booked,
            "spend": spend,
            "revenue": revenue,
            "cpl": cpl,
            "book_rate": book_rate,
            "roas": roas,
        })

    # ── Totals row ────────────────────────────────────────────────────────────
    total_leads = sum(r["leads"] for r in display_rows)
    total_booked = sum(r["booked"] for r in display_rows)
    total_spend = sum(r["spend"] for r in display_rows)
    total_revenue = sum(r["revenue"] for r in display_rows)
    totals = {
        "leads": total_leads,
        "booked": total_booked,
        "spend": total_spend,
        "revenue": total_revenue,
        "cpl": total_spend / total_leads if total_leads else None,
        "book_rate": total_booked / total_leads if total_leads else None,
        "roas": total_revenue / total_spend if total_spend else None,
    }

    present_sources = set(rows_map.keys())
    missing_sources = []
    if "networx" not in present_sources:
        missing_sources.append("networx")
    if "elocal" not in present_sources:
        missing_sources.append("elocal")
    try:
        with db.engine.connect() as conn:
            crm_row = conn.execute(text(
                "SELECT id FROM crm_connections WHERE account_id=:aid LIMIT 1"
            ), {"aid": aid}).first()
        if not crm_row:
            missing_sources.append("crm")
    except Exception:
        missing_sources.append("crm")

    return render_template(
        "reports/cpl.html",
        rows=display_rows,
        totals=totals,
        days=days,
        is_sample=is_sample,
        missing_sources=missing_sources,
    )


# ---- Per-channel report pages (kept from original) ----

@reports_bp.route("/google-ads")
@login_required
def google_ads():
    aid = current_account_id()
    tok = _google_connected(aid, "ads") if aid else None
    return render_template("reports/google_ads.html", connected=bool(tok), token=tok)


@reports_bp.route("/google-analytics")
@login_required
def google_analytics():
    aid = current_account_id()
    tok = _google_connected(aid, "ga") if aid else None
    return render_template("reports/google_analytics.html", connected=bool(tok), token=tok)


@reports_bp.route("/google-business")
@login_required
def google_business():
    aid = current_account_id()
    tok = _google_connected(aid, "gmb") if aid else None
    return render_template("reports/google_business.html", connected=bool(tok), token=tok)


@reports_bp.route("/google-search-console")
@login_required
def google_search_console():
    aid = current_account_id()
    tok = _google_connected(aid, "gsc") if aid else None
    return render_template("reports/google_search_console.html", connected=bool(tok), token=tok)


@reports_bp.route("/facebook-ads")
@login_required
def facebook_ads():
    aid = current_account_id()
    acct = _fb_account(aid) if aid else None
    leads_30d = 0
    if aid:
        try:
            row = db.session.execute(
                text(
                    "SELECT COUNT(*) FROM fb_leads "
                    "WHERE account_id=:aid AND created_time >= (NOW() - INTERVAL 30 DAY)"
                ),
                {"aid": aid},
            ).first()
            leads_30d = int(row[0] or 0)
        except Exception as e:
            current_app.logger.warning("reports.facebook_ads leads query failed: %s", e)
            leads_30d = 0
    return render_template(
        "reports/facebook_ads.html",
        connected=bool(acct),
        account=acct,
        leads_30d=leads_30d,
    )


@reports_bp.route("/wordpress")
@login_required
def wordpress():
    aid = current_account_id()
    site = _wp_site(aid) if aid else None
    return render_template("reports/wordpress.html", connected=bool(site), site=site)
