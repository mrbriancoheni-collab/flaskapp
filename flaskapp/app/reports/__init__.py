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


# =========================
# ===== PULSE OVERVIEW  ===
# =========================

def _normalize_source(src: str) -> str:
    s = (src or "").lower().strip().replace(" ", "-").replace("_", "-")
    if s in ("google-ads", "googleads", "adwords", "google-adwords"):
        return "google-ads"
    if s in ("glsa", "local-services", "local-services-ads", "lsa"):
        return "glsa"
    if s in ("organic", "seo", "website", "direct", "web"):
        return "organic"
    if s in ("networx", "network-x"):
        return "networx"
    if s in ("elocal", "e-local"):
        return "elocal"
    if s in ("yelp",):
        return "yelp"
    if s in ("facebook", "fb", "facebook-ads", "meta"):
        return "facebook"
    return s or "other"


_SOURCE_META = {
    "google-ads": {"label": "Google Ads",         "icon": "fa-brands fa-google",       "color": "blue",   "color_hex": "#4285F4"},
    "glsa":       {"label": "Local Services Ads",  "icon": "fa-solid fa-shield-halved", "color": "green",  "color_hex": "#34A853"},
    "organic":    {"label": "Website / Organic",   "icon": "fa-solid fa-globe",         "color": "teal",   "color_hex": "#0D9488"},
    "networx":    {"label": "Networx",             "icon": "fa-solid fa-bolt",          "color": "orange", "color_hex": "#F97316"},
    "elocal":     {"label": "eLocal",              "icon": "fa-solid fa-phone",         "color": "purple", "color_hex": "#8B5CF6"},
    "yelp":       {"label": "Yelp",                "icon": "fa-brands fa-yelp",         "color": "red",    "color_hex": "#EF4444"},
    "facebook":   {"label": "Facebook Ads",        "icon": "fa-brands fa-facebook-f",   "color": "indigo", "color_hex": "#4F46E5"},
    "other":      {"label": "Other Sources",       "icon": "fa-solid fa-circle",        "color": "gray",   "color_hex": "#6B7280"},
}


def _compute_health_grade(revenue, prev_revenue, total_spend, total_leads, total_jobs, booking_rate):
    score = 50  # start neutral

    # Revenue trend (+/- up to 25 pts)
    if prev_revenue and prev_revenue > 0:
        trend = (revenue - prev_revenue) / prev_revenue
        if trend >= 0.15:
            score += 25
        elif trend >= 0.05:
            score += 15
        elif trend >= 0:
            score += 5
        elif trend >= -0.10:
            score -= 10
        else:
            score -= 25
    elif revenue > 0:
        score += 10

    # CPL efficiency (+/- up to 15 pts)
    if total_spend > 0 and total_leads > 0:
        cpl = total_spend / total_leads
        if cpl < 40:
            score += 15
        elif cpl < 80:
            score += 8
        elif cpl < 150:
            score += 0
        elif cpl < 300:
            score -= 10
        else:
            score -= 15

    # Booking rate (+/- up to 10 pts)
    if booking_rate is not None:
        if booking_rate >= 0.5:
            score += 10
        elif booking_rate >= 0.3:
            score += 5
        elif booking_rate < 0.15:
            score -= 10

    if score >= 85:
        return "A"
    if score >= 72:
        return "B"
    if score >= 58:
        return "C"
    if score >= 42:
        return "D"
    return "F"


def _grade_copy(grade, revenue, prev_revenue, total_leads, total_spend):
    trend_pct = None
    if prev_revenue and prev_revenue > 0:
        trend_pct = round((revenue - prev_revenue) / prev_revenue * 100)

    if grade == "A":
        msg = "Things are firing on all cylinders."
        if trend_pct and trend_pct > 0:
            msg = f"Revenue is up {trend_pct}% from last month and your marketing is working efficiently."
        detail = "Keep doing what you're doing — and make sure you're capturing every lead."
    elif grade == "B":
        msg = "Solid month overall — a few tweaks could make it great."
        if trend_pct and trend_pct > 0:
            msg = f"You're up {trend_pct}% from last month with room to optimize spend."
        detail = "Check the action items below to squeeze more out of what's working."
    elif grade == "C":
        msg = "Decent, but there's real money being left on the table."
        detail = "Your lead sources are inconsistent — focus on the highest-ROI channel and double down."
    elif grade == "D":
        msg = "Marketing spend isn't converting to revenue the way it should."
        detail = "Review your booking process — getting leads but not closing is usually a response-time or follow-up issue."
    else:
        msg = "Immediate attention needed — spend is outpacing results."
        detail = "Pause low-performing channels and focus on your one best source until things stabilize."

    return msg, detail


def _generate_actions(aid, channels, total_leads, booking_rate, total_spend):
    actions = []

    # 1. Review requests
    try:
        with db.engine.connect() as conn:
            from datetime import datetime, timedelta
            week_ago = datetime.utcnow() - timedelta(days=7)
            sent_row = conn.execute(text(
                "SELECT COUNT(DISTINCT job_id) FROM review_requests "
                "WHERE account_id=:aid AND sent_at >= :cutoff"
            ), {"aid": aid, "cutoff": week_ago}).scalar() or 0
            completed_row = conn.execute(text(
                "SELECT COUNT(*) FROM servicetitan_jobs "
                "WHERE account_id=:aid AND completed_date >= :cutoff "
                "AND job_status IN ('Completed','completed')"
            ), {"aid": aid, "cutoff": week_ago}).scalar() or 0
            unasked = max(0, int(completed_row) - int(sent_row))
            if unasked >= 3:
                actions.append({
                    "priority": 1,
                    "icon": "fa-solid fa-star",
                    "color": "amber",
                    "headline": f"Ask {unasked} recent customers for a review",
                    "body": f"You completed {completed_row} jobs this week but only sent {sent_row} review requests. A 5-star review is worth more than most ad clicks.",
                    "cta": "Send Review Requests",
                    "url": "/account/reputation/review-requests",
                })
    except Exception:
        pass

    # 2. Reactivation candidates
    try:
        with db.engine.connect() as conn:
            from datetime import datetime, timedelta
            yr_ago = datetime.utcnow() - timedelta(days=365)
            reactivation_count = conn.execute(text(
                "SELECT COUNT(DISTINCT customer_id) FROM servicetitan_jobs "
                "WHERE account_id=:aid AND completed_date < :cutoff "
                "AND customer_id NOT IN ("
                "  SELECT DISTINCT customer_id FROM servicetitan_jobs "
                "  WHERE account_id=:aid AND completed_date >= :cutoff"
                ")"
            ), {"aid": aid, "cutoff": yr_ago}).scalar() or 0
            if reactivation_count >= 5:
                actions.append({
                    "priority": 2,
                    "icon": "fa-solid fa-rotate-left",
                    "color": "indigo",
                    "headline": f"Re-engage {int(reactivation_count)} customers who haven't called in a year",
                    "body": "Past customers are 5x more likely to book than a cold lead — and they cost nothing to reach. A simple 'we miss you' email typically books 1-3 jobs.",
                    "cta": "Launch Reactivation Campaign",
                    "url": "/account/journey/reactivation",
                })
    except Exception:
        pass

    # 3. Budget / channel opportunity
    best_channel = None
    best_roas = 0
    for src, data in channels.items():
        if data.get("spend", 0) > 0 and data.get("revenue", 0) > 0:
            roas = data["revenue"] / data["spend"]
            if roas > best_roas:
                best_roas = roas
                best_channel = src

    if best_channel and best_roas >= 4:
        meta = _SOURCE_META.get(best_channel, {"label": best_channel})
        actions.append({
            "priority": 3,
            "icon": "fa-solid fa-arrow-trend-up",
            "color": "green",
            "headline": f"{meta['label']} is returning {best_roas:.1f}x — consider increasing the budget",
            "body": f"For every $1 you spend on {meta['label']}, you're getting ${best_roas:.1f} back. That's well above the 3x threshold where it makes sense to spend more.",
            "cta": "Review Budget",
            "url": "/account/auto-budget",
        })
    elif booking_rate is not None and booking_rate < 0.25 and total_leads > 10:
        pct = round(booking_rate * 100)
        actions.append({
            "priority": 3,
            "icon": "fa-solid fa-triangle-exclamation",
            "color": "orange",
            "headline": f"Only {pct}% of leads are booking — follow-up speed is likely the issue",
            "body": "Industry data shows that responding to a lead within 5 minutes makes you 21x more likely to win the job. Check your response process.",
            "cta": "Review Lead Flow",
            "url": "/account/reports/cpl",
        })

    # 4. Pricing intelligence (always a quick win)
    if len(actions) < 3:
        actions.append({
            "priority": 4,
            "icon": "fa-solid fa-tags",
            "color": "purple",
            "headline": "Check if your prices are leaving money on the table",
            "body": "AI analysis of your job data can spot services where you're underpriced or where pricing is inconsistent across technicians.",
            "cta": "Run Pricing Analysis",
            "url": "/account/marketing/pricing-intelligence",
        })

    return actions[:3]


@reports_bp.route("/overview", methods=["GET"], endpoint="overview")
@login_required
def overview():
    from datetime import datetime, timedelta

    aid = current_account_id()
    now = datetime.utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    prev_start = (month_start - timedelta(days=1)).replace(day=1)
    six_months_ago = month_start - timedelta(days=182)

    is_sample = False
    channels: Dict[str, Any] = {}

    def _ch(src):
        k = _normalize_source(src)
        if k not in channels:
            channels[k] = {"spend": 0.0, "leads": 0, "booked": 0, "revenue": 0.0, "jobs": 0}
        return channels[k]

    # ── Revenue + job count from CRM ─────────────────────────────────────────
    total_jobs_this_month = 0
    try:
        with db.engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT lead_source, COUNT(*) as cnt, SUM(total_amount) as rev "
                "FROM servicetitan_jobs "
                "WHERE account_id=:aid AND completed_date>=:ms "
                "AND job_status IN ('Completed','completed') "
                "GROUP BY lead_source"
            ), {"aid": aid, "ms": month_start}).fetchall()
            for src, cnt, rev in rows:
                c = _ch(src or "other")
                c["revenue"] += float(rev or 0)
                c["jobs"] += int(cnt)
                total_jobs_this_month += int(cnt)
    except Exception as exc:
        current_app.logger.warning("pulse: crm revenue query failed: %s", exc)

    # ── Prev month revenue ────────────────────────────────────────────────────
    prev_revenue = 0.0
    try:
        with db.engine.connect() as conn:
            row = conn.execute(text(
                "SELECT SUM(total_amount) FROM servicetitan_jobs "
                "WHERE account_id=:aid AND completed_date>=:ps AND completed_date<:ms "
                "AND job_status IN ('Completed','completed')"
            ), {"aid": aid, "ps": prev_start, "ms": month_start}).scalar()
            prev_revenue = float(row or 0)
    except Exception:
        pass

    # ── Leads from lead_ingest ────────────────────────────────────────────────
    try:
        with db.engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT source, COUNT(*) as cnt, "
                "SUM(CASE WHEN status IN ('booked','completed') THEN 1 ELSE 0 END) as booked, "
                "SUM(COALESCE(lead_cost,0)) as cost "
                "FROM lead_ingest "
                "WHERE account_id=:aid AND occurred_at>=:ms "
                "GROUP BY source"
            ), {"aid": aid, "ms": month_start}).fetchall()
            for src, cnt, booked, cost in rows:
                c = _ch(src or "other")
                c["leads"] += int(cnt)
                c["booked"] += int(booked)
                c["spend"] += float(cost or 0)
    except Exception as exc:
        current_app.logger.warning("pulse: lead_ingest query failed: %s", exc)

    # ── Ad spend ──────────────────────────────────────────────────────────────
    try:
        with db.engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT source, SUM(amount) FROM ad_spend "
                "WHERE account_id=:aid AND spend_date>=:ms GROUP BY source"
            ), {"aid": aid, "ms": month_start.date()}).fetchall()
            for src, amt in rows:
                _ch(src or "other")["spend"] += float(amt or 0)
    except Exception as exc:
        current_app.logger.warning("pulse: ad_spend query failed: %s", exc)

    # ── Google Ads from gads_stats_daily ─────────────────────────────────────
    try:
        with db.engine.connect() as conn:
            row = conn.execute(text(
                "SELECT SUM(cost_micros)/1e6, SUM(clicks), SUM(conversions) "
                "FROM gads_stats_daily "
                "WHERE account_id=:aid AND date>=:ms"
            ), {"aid": aid, "ms": month_start.date()}).fetchone()
            if row and row[0]:
                c = _ch("google-ads")
                c["spend"] = max(c["spend"], float(row[0]))
                if not c["leads"] and row[2]:
                    c["leads"] = int(row[2])
    except Exception:
        pass

    # ── Fall back to demo data ────────────────────────────────────────────────
    if not channels or all(
        c["revenue"] == 0 and c["spend"] == 0 and c["leads"] == 0
        for c in channels.values()
    ):
        is_sample = True
        channels = {
            "google-ads": {"spend": 1380, "leads": 42, "booked": 18, "revenue": 9800, "jobs": 18},
            "glsa":       {"spend": 820,  "leads": 24, "booked": 11, "revenue": 7200, "jobs": 11},
            "networx":    {"spend": 460,  "leads": 14, "booked": 5,  "revenue": 3400, "jobs": 5},
            "organic":    {"spend": 0,    "leads": 18, "booked": 7,  "revenue": 4800, "jobs": 7},
            "elocal":     {"spend": 310,  "leads": 9,  "booked": 3,  "revenue": 2100, "jobs": 3},
        }
        prev_revenue = 22800.0
        total_jobs_this_month = 44

    # ── 6-month revenue trend ─────────────────────────────────────────────────
    monthly_trend = []
    try:
        with db.engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT DATE_TRUNC('month', completed_date) as mo, SUM(total_amount) "
                "FROM servicetitan_jobs "
                "WHERE account_id=:aid AND completed_date>=:sma "
                "AND job_status IN ('Completed','completed') "
                "GROUP BY mo ORDER BY mo"
            ), {"aid": aid, "sma": six_months_ago}).fetchall()
            monthly_trend = [{"month": r[0].strftime("%b"), "revenue": float(r[1] or 0)} for r in rows]
    except Exception:
        pass

    if not monthly_trend and is_sample:
        monthly_trend = [
            {"month": "Dec", "revenue": 18200},
            {"month": "Jan", "revenue": 15400},
            {"month": "Feb", "revenue": 17800},
            {"month": "Mar", "revenue": 21300},
            {"month": "Apr", "revenue": 22800},
            {"month": "May", "revenue": 27300},
        ]

    # ── Totals ────────────────────────────────────────────────────────────────
    total_revenue = sum(c["revenue"] for c in channels.values())
    total_spend   = sum(c["spend"]   for c in channels.values())
    total_leads   = sum(c["leads"]   for c in channels.values())
    total_booked  = sum(c["booked"]  for c in channels.values())
    booking_rate  = total_booked / total_leads if total_leads else None

    # ── Health grade ─────────────────────────────────────────────────────────
    grade = _compute_health_grade(total_revenue, prev_revenue, total_spend, total_leads, total_jobs_this_month, booking_rate)
    grade_msg, grade_detail = _grade_copy(grade, total_revenue, prev_revenue, total_leads, total_spend)

    # ── Channel display list ──────────────────────────────────────────────────
    channel_list = []
    for src, data in sorted(channels.items(), key=lambda x: -x[1]["revenue"]):
        if data["revenue"] == 0 and data["spend"] == 0 and data["leads"] == 0:
            continue
        meta = _SOURCE_META.get(src, {"label": src.replace("-", " ").title(),
                                      "icon": "fa-solid fa-circle",
                                      "color": "gray", "color_hex": "#6B7280"})
        rev  = data["revenue"]
        sp   = data["spend"]
        lds  = data["leads"]
        bkd  = data["booked"]
        channel_list.append({
            "key":       src,
            "label":     meta["label"],
            "icon":      meta["icon"],
            "color":     meta["color"],
            "color_hex": meta["color_hex"],
            "revenue":   rev,
            "spend":     sp,
            "leads":     lds,
            "booked":    bkd,
            "jobs":      data.get("jobs", bkd),
            "cpl":       sp / lds if lds and sp else None,
            "roas":      rev / sp  if sp else None,
            "cpr":       sp / bkd  if bkd and sp else None,
            "rev_share": round(rev / total_revenue * 100) if total_revenue else 0,
        })

    # ── Action items ─────────────────────────────────────────────────────────
    actions = _generate_actions(aid, channels, total_leads, booking_rate, total_spend)

    # ── MoM delta ────────────────────────────────────────────────────────────
    mom_delta = None
    if prev_revenue and prev_revenue > 0:
        mom_delta = round((total_revenue - prev_revenue) / prev_revenue * 100)

    return render_template(
        "reports/overview.html",
        grade=grade,
        grade_msg=grade_msg,
        grade_detail=grade_detail,
        total_revenue=total_revenue,
        prev_revenue=prev_revenue,
        mom_delta=mom_delta,
        total_spend=total_spend,
        total_leads=total_leads,
        total_jobs=total_jobs_this_month,
        booking_rate=booking_rate,
        channel_list=channel_list,
        actions=actions,
        monthly_trend=monthly_trend,
        is_sample=is_sample,
        month_label=now.strftime("%B %Y"),
        epn=request.endpoint,
        SECTION="reports",
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
