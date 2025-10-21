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


# ---- Stub for base_app link: prevents BuildError on url_for('reports_bp.cpl_dashboard') ----
@reports_bp.route("/cpl", methods=["GET"], endpoint="cpl_dashboard")
@login_required
def cpl_dashboard():
    # Redirect to index until a dedicated CPL view/template is implemented.
    flash("Cost per Lead dashboard coming soon. Showing account reports overview for now.", "info")
    return redirect(url_for("reports_bp.index"))


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
