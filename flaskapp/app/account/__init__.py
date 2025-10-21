# app/account/__init__.py
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional, Tuple

import requests
from flask import (
    Blueprint,
    current_app,
    redirect,
    render_template,
    url_for,
    jsonify,
    flash,
)
from sqlalchemy import text

from app import db
from app.auth.utils import login_required, current_account_id, is_paid_account

account_bp = Blueprint("account_bp", __name__, url_prefix="/account")

# --------------------------- helpers ---------------------------

def _safe_dt(v) -> Optional[datetime]:
    try:
        if isinstance(v, datetime):
            return v
        if v is None:
            return None
        return datetime.fromisoformat(str(v).replace(" ", "T"))
    except Exception:
        return None

def _endpoint_exists(ep: str) -> bool:
    try:
        return ep in current_app.view_functions
    except Exception:
        return False

def _connect_url(provider: str) -> str:
    """
    Map dashboard 'Connect' buttons to the right endpoints.
    Accept both 'glsa' and 'lsa', and provide per-product Google connects.
    """
    mapping = {
        # Google product-specific connects
        "ga":   "google_bp.connect_ga",
        "ads":  "google_bp.connect_ads",
        "gsc":  "google_bp.connect_gsc",
        "gmb":  "google_bp.connect_gmb",
        "glsa": "google_bp.connect_lsa",
        "lsa":  "google_bp.connect_lsa",
        # Other providers
        "facebook": "fbads_bp.index",
        "wp":       "wp_bp.index",
        "yelp":     "yelp_bp.index",
        # Fallback to Google hub
        "google":   "google_bp.index",
    }
    ep = mapping.get(provider)
    try:
        if ep and _endpoint_exists(ep):
            return url_for(ep)
        return "#"
    except Exception:
        return "#"

def _has_google_oauth(aid: int, product: str) -> Tuple[bool, Optional[datetime]]:
    """
    True if there is an OAuth row in google_oauth_tokens for this product.
    Mirrors the pattern used elsewhere in the app.
    """
    try:
        with db.engine.connect() as conn:
            row = (
                conn.execute(
                    text(
                        """
                        SELECT token_expiry
                          FROM google_oauth_tokens
                         WHERE account_id=:aid
                           AND product=:prod
                         ORDER BY updated_at DESC
                         LIMIT 1
                        """
                    ),
                    {"aid": aid, "prod": product},
                )
                .mappings()
                .first()
            )
            if row:
                return True, _safe_dt(row.get("token_expiry"))
    except Exception:
        pass
    return False, None

def _is_facebook_connected(aid: int) -> Tuple[bool, Optional[datetime]]:
    try:
        with db.engine.connect() as conn:
            row = (
                conn.execute(
                    text(
                        "SELECT refreshed_at FROM fb_tokens "
                        "WHERE account_id=:aid ORDER BY refreshed_at DESC LIMIT 1"
                    ),
                    {"aid": aid},
                )
                .mappings()
                .first()
            )
            if row:
                return True, _safe_dt(row.get("refreshed_at"))
    except Exception:
        pass
    return False, None

# ---------- WordPress from DB (wp_sites) or env fallback ----------
def _wp_row(aid: int) -> Optional[Dict[str, Any]]:
    try:
        with db.engine.connect() as conn:
            row = (
                conn.execute(
                    text(
                        """
                        SELECT base_url, username, app_password
                          FROM wp_sites
                         WHERE account_id=:aid
                         ORDER BY updated_at DESC
                         LIMIT 1
                        """
                    ),
                    {"aid": aid},
                )
                .mappings()
                .first()
            )
            return dict(row) if row else None
    except Exception as e:
        current_app.logger.exception("wp_sites lookup failed: %s", e)
        return None

def _wp_creds(aid: int) -> Optional[Tuple[str, str, str]]:
    row = _wp_row(aid)
    if row and row.get("base_url") and row.get("username") and row.get("app_password"):
        return row["base_url"].rstrip("/"), row["username"], row["app_password"]
    base = (current_app.config.get("WP_BASE") or "").rstrip("/")
    user = current_app.config.get("WP_USER") or ""
    app_pw = current_app.config.get("WP_APP_PW") or ""
    if base and user and app_pw:
        return base, user, app_pw
    return None

def _is_wp_connected(aid: int) -> bool:
    return _wp_creds(aid) is not None

def _wp_get(aid: int, path: str, params: Optional[Dict[str, Any]] = None, timeout: int = 6):
    base, user, app_pw = _wp_creds(aid)  # type: ignore[misc]
    url = f"{base}/wp-json{path}"
    resp = requests.get(url, params=params or {}, auth=(user, app_pw), timeout=timeout)
    resp.raise_for_status()
    return resp

def _fetch_wp_summary(aid: int) -> Dict[str, Any]:
    out: Dict[str, Any] = {"connected": False, "error": None, "site": {}, "posts": [], "pages": [], "counts": {}}
    if not _is_wp_connected(aid):
        return out
    try:
        try:
            r_site = _wp_get(aid, "/")
            site = r_site.json() or {}
        except Exception:
            site = {}
        out["site"] = {
            "name": site.get("name"),
            "description": site.get("description"),
            "home": site.get("home"),
        }
        r_posts = _wp_get(aid, "/wp/v2/posts", {"per_page": 5, "orderby": "date", "order": "desc"})
        posts = r_posts.json() or []
        cnt_posts = int(r_posts.headers.get("X-WP-Total", "0"))
        out["posts"] = [
            {
                "id": p.get("id"),
                "title": (p.get("title") or {}).get("rendered"),
                "date": p.get("date"),
                "link": p.get("link"),
                "status": p.get("status"),
            }
            for p in posts
        ]
        r_pages = _wp_get(aid, "/wp/v2/pages", {"per_page": 5, "orderby": "modified", "order": "desc"})
        pages = r_pages.json() or []
        cnt_pages = int(r_pages.headers.get("X-WP-Total", "0"))
        out["pages"] = [
            {
                "id": pg.get("id"),
                "title": (pg.get("title") or {}).get("rendered"),
                "modified": pg.get("modified"),
                "link": pg.get("link"),
                "status": pg.get("status"),
            }
            for pg in pages
        ]
        out["counts"] = {"posts": cnt_posts, "pages": cnt_pages}
        out["connected"] = True
    except Exception as e:
        out["error"] = str(e)
    return out

def _sample(label: str) -> Dict[str, Any]:
    return {"sample": True, "label": label}

# --------------------------- cards builder ---------------------------

def _connection_cards(aid: int) -> Dict[str, Dict[str, Any]]:
    """
    Build a dict keyed exactly how the dashboard template expects:
    'ga', 'ads', 'gsc', 'gmb', 'glsa', 'facebook', 'wp', 'yelp'
    """
    cards: Dict[str, Dict[str, Any]] = {}

    # Google Analytics
    ga_conn, ga_exp = _has_google_oauth(aid, "ga")
    cards["ga"] = {
        "name": "Google Analytics",
        "slug": "ga",
        "connected": ga_conn,
        "last_sync": ga_exp,
        "connect_url": _connect_url("ga"),
        "data": {} if ga_conn else _sample("Connect Google Analytics to surface traffic & conversions."),
    }

    # Google Ads
    ads_conn, ads_exp = _has_google_oauth(aid, "ads")
    cards["ads"] = {
        "name": "Google Ads",
        "slug": "ads",
        "connected": ads_conn,
        "last_sync": ads_exp,
        "connect_url": _connect_url("ads"),
        "data": {} if ads_conn else _sample("Connect Google Ads to create and manage campaigns."),
    }

    # Search Console
    gsc_conn, gsc_exp = _has_google_oauth(aid, "gsc")
    cards["gsc"] = {
        "name": "Search Console",
        "slug": "gsc",
        "connected": gsc_conn,
        "last_sync": gsc_exp,
        "connect_url": _connect_url("gsc"),
        "data": {} if gsc_conn else _sample("Connect Search Console to monitor indexed pages & queries."),
    }

    # Google Business Profile
    gmb_conn, gmb_exp = _has_google_oauth(aid, "gmb")
    cards["gmb"] = {
        "name": "Google Business",
        "slug": "gmb",
        "connected": gmb_conn,
        "last_sync": gmb_exp,
        "connect_url": _connect_url("gmb"),
        "data": {} if gmb_conn else _sample("Connect GBP to manage reviews and listings."),
    }

    # Local Services Ads (GLSA / LSA)
    # Prefer oauth token in google_oauth_tokens with product 'lsa';
    # fall back to glsa_accounts for legacy/manual entries.
    lsa_conn, lsa_exp = _has_google_oauth(aid, "lsa")
    if not lsa_conn:
        try:
            with db.engine.connect() as conn:
                row = (
                    conn.execute(
                        text(
                            """
                            SELECT access_token, token_expiry
                              FROM glsa_accounts
                             WHERE account_id = :aid
                             ORDER BY updated_at DESC
                             LIMIT 1
                            """
                        ),
                        {"aid": aid},
                    )
                    .mappings()
                    .first()
                )
            lsa_conn = bool(row and row.get("access_token"))
            lsa_exp = _safe_dt(row.get("token_expiry")) if row else None
        except Exception as e:
            current_app.logger.error("GLSA lookup failed: %s", e)
            lsa_conn = False
            lsa_exp = None

    cards["glsa"] = {
        "name": "Local Services Ads",
        "slug": "glsa",
        "connected": lsa_conn,
        "last_sync": lsa_exp,
        "connect_url": _connect_url("glsa"),
        "data": {} if lsa_conn else _sample("Connect Local Services Ads to review leads and optimize your profile."),
    }

    # Facebook
    fb_conn, fb_exp = _is_facebook_connected(aid)
    cards["facebook"] = {
        "name": "Facebook Ads",
        "slug": "facebook",
        "connected": fb_conn,
        "last_sync": fb_exp,
        "connect_url": _connect_url("facebook"),
        "data": {} if fb_conn else _sample("Connect Facebook Ads to sync lead gen and campaigns."),
    }

    # WordPress
    wp_summary = _fetch_wp_summary(aid) if _is_wp_connected(aid) else None
    cards["wp"] = {
        "name": "WordPress",
        "slug": "wp",
        "connected": bool(wp_summary and wp_summary.get("connected")),
        "last_sync": None,
        "connect_url": _connect_url("wp"),
        "data": wp_summary if (wp_summary and wp_summary.get("connected")) else _sample("Latest posts & pages"),
        "error": (wp_summary or {}).get("error") if wp_summary else None,
    }

    # Yelp (coming soon)
    cards["yelp"] = {
        "name": "Yelp",
        "slug": "yelp",
        "connected": False,
        "last_sync": None,
        "connect_url": "#",
        "data": _sample("Coming soon"),
        "coming_soon": True,
    }

    return cards

# --------------------------- routes ---------------------------

@account_bp.route("/", methods=["GET"], endpoint="account_index")
@login_required
def account_index():
    return redirect(url_for("account_bp.dashboard"))

@account_bp.route("/dashboard", methods=["GET"], endpoint="dashboard")
@login_required
def dashboard():
    aid = current_account_id()
    if not aid:
        flash("We couldn't determine your account. Please log in again.", "error")
        return redirect(url_for("auth_bp.logout"))

    is_paid = is_paid_account()
    cards = _connection_cards(aid)

    # Stable order to match template expectations
    card_order = ["ga", "ads", "gsc", "gmb", "glsa", "facebook", "wp", "yelp"]

    connected_count = sum(1 for k in card_order if cards.get(k, {}).get("connected"))
    total_count = len(card_order)
    pct = int(round((connected_count / max(1, total_count)) * 100))

    return render_template(
        "account/dashboard.html",
        cards=cards,
        card_order=card_order,
        is_paid=is_paid,
        connected_count=connected_count,
        total_count=total_count,
        connected_percent=pct,
    )

@account_bp.route("/connect/<provider>", methods=["GET"], endpoint="connect")
@login_required
def connect(provider: str):
    url = _connect_url(provider.lower())
    if url == "#":
        flash("Provider not available.", "error")
        return redirect(url_for("account_bp.dashboard"))
    return redirect(url)

@account_bp.route("/stripe/webhook", methods=["POST"], endpoint="stripe_webhook")
def stripe_webhook():
    return jsonify({"ok": True}), 200
