# app/account/__init__.py
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional, Tuple

import requests
from flask import (
    Blueprint,
    current_app,
    g,
    redirect,
    render_template,
    url_for,
    jsonify,
    flash,
    request,
)
from sqlalchemy import text

from app import db
from app.auth.utils import login_required, current_account_id, is_paid_account

# Import performance utilities for caching
try:
    from app.performance_utils import cache_result, request_cache
except ImportError:
    # Fallback no-op decorators if performance_utils not available
    def cache_result(ttl=300, key_prefix=""):
        def decorator(func):
            return func
        return decorator
    def request_cache(func):
        return func

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

@request_cache
def _get_all_google_oauth(aid: int) -> Dict[str, Tuple[bool, Optional[datetime]]]:
    """
    Batch fetch all Google OAuth tokens for an account in ONE query.
    Returns dict keyed by product name.
    Cached per-request to avoid duplicate queries.
    MySQL-compatible version using GROUP BY.
    """
    result = {}
    try:
        with db.engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT product, MAX(token_expiry) as token_expiry
                      FROM google_oauth_tokens
                     WHERE account_id=:aid
                     GROUP BY product
                    """
                ),
                {"aid": aid},
            ).mappings().all()

            for row in rows:
                product = row.get("product")
                if product:
                    result[product] = (True, _safe_dt(row.get("token_expiry")))
    except Exception as e:
        current_app.logger.error(f"Error fetching Google OAuth tokens: {e}")

    return result

@request_cache
def _has_google_oauth(aid: int, product: str) -> Tuple[bool, Optional[datetime]]:
    """
    True if there is an OAuth row in google_oauth_tokens for this product.
    Now uses batch query for better performance.
    Cached per-request to avoid duplicate queries.
    """
    all_tokens = _get_all_google_oauth(aid)
    return all_tokens.get(product, (False, None))

@request_cache
def _is_facebook_connected(aid: int) -> Tuple[bool, Optional[datetime]]:
    """Cached per-request to avoid duplicate queries."""
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

@cache_result(ttl=300, key_prefix="wp_summary")
def _fetch_wp_summary(aid: int) -> Dict[str, Any]:
    """
    Fetch WordPress summary with 5-minute cache.
    This prevents slow HTTP requests on every dashboard load.
    """
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

def _check_ai_requirements(aid: int, ads_connected: bool) -> list:
    """
    Return a list of warning dicts describing missing ML/AI agent requirements.
    Only runs when Google Ads is connected — no point warning otherwise.
    """
    import os
    if not ads_connected:
        return []

    has_biz, has_examples = _fetch_ai_context(aid)
    has_openai = bool(os.getenv('OPENAI_API_KEY'))

    warnings = []
    if not has_biz and not has_examples:
        warnings.append({
            'key': 'no_business_context',
            'title': 'AI agents have no business context',
            'detail': (
                'The AI agents need a business description or negative keyword examples '
                'to intelligently filter irrelevant search terms. Without this, the LLM '
                'relevance check is skipped entirely.'
            ),
            'fix_url': url_for('agents_bp.dashboard'),
            'fix_label': 'Configure AI Settings →',
            'severity': 'warning',
        })
    elif not has_examples:
        warnings.append({
            'key': 'no_nk_examples',
            'title': 'Negative keyword examples not set',
            'detail': (
                'Adding examples of what is and isn\'t relevant to your business '
                'helps the AI make better negative keyword decisions.'
            ),
            'fix_url': url_for('agents_bp.dashboard'),
            'fix_label': 'Add Examples →',
            'severity': 'info',
        })

    if not has_openai:
        warnings.append({
            'key': 'no_openai_key',
            'title': 'OpenAI API key not configured',
            'detail': (
                'The AI agents use OpenAI to evaluate search terms. '
                'Intelligent LLM filtering is disabled without this key.'
            ),
            'fix_url': None,
            'fix_label': None,
            'severity': 'error',
        })

    return warnings


def _fetch_ai_context(aid: int):
    """
    Check both storage locations for AI context (accounts table columns
    AND account_settings key-value rows). Returns (has_biz, has_examples).
    """
    has_biz = False
    has_examples = False
    try:
        # Primary: accounts table columns (written by save_ai_settings)
        row = db.session.execute(text(
            "SELECT business_description, negative_keyword_examples "
            "FROM accounts WHERE id = :id"
        ), {"id": aid}).first()
        if row:
            has_biz = bool(row[0] and str(row[0]).strip())
            has_examples = bool(row[1] and str(row[1]).strip())
    except Exception:
        pass  # columns may not exist yet

    # Fallback: account_settings key-value table (older code path)
    if not has_biz or not has_examples:
        try:
            rows = db.session.execute(text(
                "SELECT setting_key, setting_value FROM account_settings "
                "WHERE account_id = :aid "
                "  AND setting_key IN ('business_description', 'negative_keyword_examples')"
            ), {"aid": aid}).all()
            for key, val in rows:
                if val and str(val).strip():
                    if key == 'business_description':
                        has_biz = True
                    elif key == 'negative_keyword_examples':
                        has_examples = True
        except Exception:
            pass

    return has_biz, has_examples



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

# --------------------------- pulse snapshot ---------------------------

def _quick_pulse(aid: int) -> dict:
    """Three fast aggregation queries for the dashboard snapshot banner."""
    from datetime import datetime
    now = datetime.utcnow()
    ms = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    out = {"revenue": 0.0, "jobs": 0, "leads": 0, "spend": 0.0, "is_sample": False}
    try:
        with db.engine.connect() as conn:
            r = conn.execute(text(
                "SELECT COUNT(*), COALESCE(SUM(total_amount),0) FROM servicetitan_jobs "
                "WHERE account_id=:aid AND completed_date>=:ms "
                "AND job_status IN ('Completed','completed')"
            ), {"aid": aid, "ms": ms}).fetchone()
            if r and r[0]:
                out["jobs"] = int(r[0])
                out["revenue"] = float(r[1])
    except Exception:
        pass
    try:
        with db.engine.connect() as conn:
            out["leads"] = int(conn.execute(text(
                "SELECT COUNT(*) FROM lead_ingest WHERE account_id=:aid AND occurred_at>=:ms"
            ), {"aid": aid, "ms": ms}).scalar() or 0)
    except Exception:
        pass
    try:
        with db.engine.connect() as conn:
            out["spend"] = float(conn.execute(text(
                "SELECT COALESCE(SUM(amount),0) FROM ad_spend "
                "WHERE account_id=:aid AND spend_date>=:ms"
            ), {"aid": aid, "ms": ms.date()}).scalar() or 0)
    except Exception:
        pass
    if out["revenue"] == 0 and out["jobs"] == 0 and out["leads"] == 0:
        out.update({"revenue": 27300.0, "jobs": 44, "leads": 84, "spend": 2610.0, "is_sample": True})
    return out


_INTEGRATION_META = [
    ("ads",      "Google Ads",         "fa-brands fa-google",          "blue",   "Campaigns, spend & AI optimization",    "google_bp.ads_performance", "google_bp.connect_ads"),
    ("ga",       "Analytics",          "fa-solid fa-chart-line",        "orange", "Website traffic, sessions & goals",     "google_bp.ga_ui",           "google_bp.connect_ga"),
    ("gsc",      "Search Console",     "fa-solid fa-magnifying-glass",  "green",  "Keywords, rankings & indexing",         "google_bp.gsc_ui",          "google_bp.connect_search_console"),
    ("gmb",      "Business Profile",   "fa-solid fa-location-dot",      "red",    "Reviews, listing & local visibility",   "gmb_bp.index",              "google_bp.connect_gmb"),
    ("glsa",     "Local Services Ads", "fa-solid fa-shield-halved",     "indigo", "Local leads, cost per lead & disputes", "glsa_bp.dashboard",         "google_bp.connect_lsa"),
    ("facebook", "Facebook Ads",       "fa-brands fa-facebook-f",       "blue",   "Lead gen & campaign performance",       None,                        None),
    ("wp",       "WordPress",          "fa-brands fa-wordpress",        "sky",    "Content publishing & SEO automation",   "wp_bp.insights",            "wp_bp.settings"),
    ("yelp",     "Yelp",               "fa-brands fa-yelp",             "red",    "Reviews & business listing",            None,                        None),
]


def _build_integrations(cards: dict) -> list:
    """Build a pre-resolved integrations list for the dashboard template."""
    from flask import current_app
    rows = []
    for key, label, icon, color, detail, manage_ep, connect_ep in _INTEGRATION_META:
        card = cards.get(key, {})
        is_on = bool(card.get("connected"))
        is_soon = bool(card.get("coming_soon"))

        manage_url = "#"
        connect_url = card.get("connect_url") or "#"

        if is_on and manage_ep:
            try:
                manage_url = url_for(manage_ep)
            except Exception:
                manage_url = "#"
        elif not is_on and connect_ep:
            try:
                connect_url = url_for(connect_ep)
            except Exception:
                pass

        last_sync_str = ""
        ls = card.get("last_sync")
        if ls:
            try:
                last_sync_str = ls.strftime("%b %-d")
            except Exception:
                pass

        rows.append({
            "key":          key,
            "label":        label,
            "icon":         icon,
            "color":        color,
            "detail":       detail,
            "is_on":        is_on,
            "is_soon":      is_soon,
            "manage_url":   manage_url,
            "connect_url":  connect_url,
            "last_sync":    last_sync_str,
        })
    return rows


# --------------------------- ads kpi snapshot ---------------------------

def _fetch_ads_kpis(aid: int) -> dict:
    """Server-side Google Ads KPI snapshot for the dashboard (MTD vs prior month)."""
    from datetime import date, timedelta
    out = {"has_data": False, "spend": 0.0, "clicks": 0, "conversions": 0.0,
           "impressions": 0, "ctr": 0.0, "cpc": 0.0,
           "trend_spend": None, "trend_clicks": None, "trend_conv": None,
           "best_campaign": None}
    try:
        today = date.today()
        ms = today.replace(day=1)
        prev_end = ms - timedelta(days=1)
        prev_start = prev_end.replace(day=1)

        kpi_sql = """
            SELECT COALESCE(SUM(gs.cost_micros),0) AS cm,
                   COALESCE(SUM(gs.clicks),0)       AS cl,
                   COALESCE(SUM(gs.conversions),0)  AS cv,
                   COALESCE(SUM(gs.impressions),0)  AS im
              FROM gads_stats_daily gs
              JOIN ads_campaigns ac ON ac.id=gs.entity_id AND ac.account_id=:aid
             WHERE gs.entity_type='campaign' AND gs.date>=:s AND gs.date<=:e
        """
        with db.engine.connect() as conn:
            r = conn.execute(text(kpi_sql), {"aid": aid, "s": ms.isoformat(), "e": today.isoformat()}).mappings().first()
            p = conn.execute(text(kpi_sql), {"aid": aid, "s": prev_start.isoformat(), "e": prev_end.isoformat()}).mappings().first()

            if not r:
                return out
            spend   = float(r["cm"] or 0) / 1_000_000
            clicks  = int(r["cl"] or 0)
            conv    = float(r["cv"] or 0)
            impr    = int(r["im"] or 0)

            if spend == 0 and clicks == 0 and conv == 0:
                return out

            def _pct(cur, prev):
                prev = float(prev or 0)
                if not prev:
                    return None
                return round((float(cur) - prev) / prev * 100, 1)

            ps = float(p["cm"] or 0) / 1_000_000 if p else 0
            pc = int(p["cl"] or 0) if p else 0
            pv = float(p["cv"] or 0) if p else 0

            best = conn.execute(text("""
                SELECT ac.name, SUM(gs.conversions) AS cv
                  FROM gads_stats_daily gs
                  JOIN ads_campaigns ac ON ac.id=gs.entity_id
                 WHERE ac.account_id=:aid AND gs.entity_type='campaign' AND gs.date>=:s
                 GROUP BY ac.id, ac.name ORDER BY cv DESC LIMIT 1
            """), {"aid": aid, "s": ms.isoformat()}).mappings().first()

            out.update({
                "has_data":      True,
                "spend":         round(spend, 2),
                "clicks":        clicks,
                "conversions":   round(conv, 1),
                "impressions":   impr,
                "ctr":           round(clicks / impr * 100, 2) if impr else 0,
                "cpc":           round(spend / clicks, 2) if clicks else 0,
                "trend_spend":   _pct(spend, ps),
                "trend_clicks":  _pct(clicks, pc),
                "trend_conv":    _pct(conv, pv),
                "best_campaign": dict(best) if best else None,
            })
    except Exception as exc:
        current_app.logger.warning("_fetch_ads_kpis: %s", exc)
    return out


# --------------------------- routes ---------------------------

@account_bp.route("/", methods=["GET"], endpoint="account_index")
@login_required
def account_index():
    return redirect(url_for("account_bp.dashboard"))

@account_bp.route("/dashboard", methods=["GET"], endpoint="dashboard")
@login_required
def dashboard():
    """Dashboard with aggressive 5-minute session caching for instant loads."""
    from datetime import datetime, timedelta
    from flask import session

    aid = current_account_id()
    if not aid:
        flash("We couldn't determine your account. Please log in again.", "error")
        return redirect(url_for("auth_bp.logout"))

    # Check for cached dashboard data (5-minute TTL)
    force_refresh = request.args.get('refresh') == '1'
    cache_key = f"dashboard_data_{aid}"

    if not force_refresh and cache_key in session:
        cached = session.get(cache_key)
        if cached and cached.get("__cached_at"):
            try:
                cache_time = datetime.fromisoformat(cached["__cached_at"])
                if datetime.utcnow() - cache_time < timedelta(minutes=5):
                    current_app.logger.debug(f"Using cached dashboard for account {aid}")
                    # ai_warnings always computed fresh — reflects current config state
                    cached_cards = cached.get("cards") or {}
                    ads_connected = cached_cards.get("ads", {}).get("connected", False)
                    ai_warnings = _check_ai_requirements(aid, ads_connected)
                    ads_on = ads_connected
                    return render_template(
                        "account/dashboard.html",
                        cards=cached_cards,
                        integrations=_build_integrations(cached_cards),
                        card_order=cached.get("card_order", []),
                        is_paid=cached.get("is_paid", False),
                        connected_count=cached.get("connected_count", 0),
                        total_count=cached.get("total_count", 8),
                        connected_percent=cached.get("connected_percent", 0),
                        ai_warnings=ai_warnings,
                        pulse=_quick_pulse(aid),
                        kpis=_fetch_ads_kpis(aid) if ads_on else {},
                        user=g.user,
                    )
            except (ValueError, TypeError, KeyError):
                pass

    # Fetch fresh data
    is_paid = is_paid_account()
    cards = _connection_cards(aid)

    # Stable order to match template expectations
    card_order = ["ga", "ads", "gsc", "gmb", "glsa", "facebook", "wp", "yelp"]

    connected_count = sum(1 for k in card_order if cards.get(k, {}).get("connected"))
    total_count = len(card_order)
    pct = int(round((connected_count / max(1, total_count)) * 100))

    # Cache the result
    session[cache_key] = {
        "cards": cards,
        "card_order": card_order,
        "is_paid": is_paid,
        "connected_count": connected_count,
        "total_count": total_count,
        "connected_percent": pct,
        "__cached_at": datetime.utcnow().isoformat(),
    }

    ads_connected = cards.get("ads", {}).get("connected", False)
    ai_warnings = _check_ai_requirements(aid, ads_connected)

    return render_template(
        "account/dashboard.html",
        cards=cards,
        integrations=_build_integrations(cards),
        card_order=card_order,
        is_paid=is_paid,
        connected_count=connected_count,
        total_count=total_count,
        connected_percent=pct,
        ai_warnings=ai_warnings,
        pulse=_quick_pulse(aid),
        kpis=_fetch_ads_kpis(aid) if ads_connected else {},
        user=g.user,
    )

@account_bp.route("/dashboard/kpis.json", methods=["GET"], endpoint="dashboard_kpis")
@login_required
def dashboard_kpis():
    """Return this-month Google Ads KPIs with prior-month trends."""
    from datetime import date, timedelta
    aid = current_account_id()
    if not aid:
        return jsonify({"error": "no account"}), 403

    today = date.today()
    month_start = today.replace(day=1)
    # Previous full calendar month
    prev_month_end = month_start - timedelta(days=1)
    prev_month_start = prev_month_end.replace(day=1)

    def _pct_change(current, prior):
        if not prior:
            return None
        return round((current - prior) / prior * 100, 1)

    kpi_sql = """
        SELECT
            COALESCE(SUM(gs.cost_micros), 0)    AS cost_micros,
            COALESCE(SUM(gs.clicks), 0)          AS clicks,
            COALESCE(SUM(gs.conversions), 0)     AS conversions,
            COALESCE(SUM(gs.impressions), 0)     AS impressions
        FROM gads_stats_daily gs
        JOIN ads_campaigns ac ON ac.id = gs.entity_id AND ac.account_id = :aid
        WHERE gs.entity_type = 'campaign'
          AND gs.date >= :start AND gs.date <= :end
    """
    try:
        row = db.session.execute(text(kpi_sql), {
            "aid": aid, "start": month_start.isoformat(), "end": today.isoformat()
        }).mappings().first()
        prev = db.session.execute(text(kpi_sql), {
            "aid": aid, "start": prev_month_start.isoformat(), "end": prev_month_end.isoformat()
        }).mappings().first()

        spend = float(row["cost_micros"] or 0) / 1_000_000 if row else 0.0
        clicks = int(row["clicks"] or 0) if row else 0
        conversions = float(row["conversions"] or 0) if row else 0.0
        impressions = int(row["impressions"] or 0) if row else 0
        ctr = round(clicks / impressions * 100, 2) if impressions else 0

        prev_spend = float(prev["cost_micros"] or 0) / 1_000_000 if prev else 0.0
        prev_clicks = int(prev["clicks"] or 0) if prev else 0
        prev_conversions = float(prev["conversions"] or 0) if prev else 0.0
        prev_impressions = int(prev["impressions"] or 0) if prev else 0
        prev_ctr = round(prev_clicks / prev_impressions * 100, 2) if prev_impressions else 0

        # Best-performing campaign this month
        best = db.session.execute(text("""
            SELECT ac.name, SUM(gs.cost_micros) / 1000000.0 AS spend,
                   SUM(gs.conversions) AS conversions
            FROM gads_stats_daily gs
            JOIN ads_campaigns ac ON ac.id = gs.entity_id
            WHERE ac.account_id = :aid
              AND gs.entity_type = 'campaign'
              AND gs.date >= :month_start
            GROUP BY ac.id, ac.name
            ORDER BY SUM(gs.conversions) DESC, SUM(gs.cost_micros) DESC
            LIMIT 1
        """), {"aid": aid, "month_start": month_start.isoformat()}).mappings().first()

        return jsonify({
            "spend_dollars": round(spend, 2),
            "clicks": clicks,
            "conversions": round(conversions, 1),
            "impressions": impressions,
            "ctr": ctr,
            "cpc": round(spend / clicks, 2) if clicks else 0,
            "best_campaign": dict(best) if best else None,
            "month_start": month_start.isoformat(),
            "trends": {
                "spend": _pct_change(spend, prev_spend),
                "clicks": _pct_change(clicks, prev_clicks),
                "conversions": _pct_change(conversions, prev_conversions),
                "ctr": _pct_change(ctr, prev_ctr),
            },
        })
    except Exception as exc:
        current_app.logger.exception("dashboard_kpis error: %s", exc)
        return jsonify({"error": str(exc)}), 500


@account_bp.route("/dashboard/quick-wins.json", methods=["GET"], endpoint="dashboard_quick_wins")
@login_required
def dashboard_quick_wins():
    """Return top 3 quick-win recommendations from local DB data (no live API calls)."""
    aid = current_account_id()
    if not aid:
        return jsonify({"error": "no account"}), 403

    from datetime import date
    month_start = date.today().replace(day=1).isoformat()
    wins = []

    try:
        # 1. Wasted spend: campaigns with spend but zero conversions this month
        wasted = db.session.execute(text("""
            SELECT ac.name, ac.id AS campaign_id,
                   SUM(gs.cost_micros) / 1000000.0 AS spend,
                   SUM(gs.conversions) AS conversions
            FROM gads_stats_daily gs
            JOIN ads_campaigns ac ON ac.id = gs.entity_id
            WHERE ac.account_id = :aid
              AND gs.entity_type = 'campaign'
              AND gs.date >= :month_start
              AND ac.status = 'enabled'
            GROUP BY ac.id, ac.name
            HAVING SUM(gs.conversions) = 0 AND SUM(gs.cost_micros) > 50000000
            ORDER BY SUM(gs.cost_micros) DESC
            LIMIT 3
        """), {"aid": aid, "month_start": month_start}).mappings().all()

        if wasted:
            total_waste = sum(float(r["spend"] or 0) for r in wasted)
            worst = wasted[0]
            wins.append({
                "win_type": "pause_low_performers",
                "title": f"Pause '{worst['name']}' — 0 conversions this month",
                "description": f"Spending ${total_waste:.0f} this month across {len(wasted)} campaign(s) with zero conversions.",
                "impact_monthly_value": round(total_waste, 0),
                "impact_leads": 0,
                "difficulty": "easy",
                "time_estimate": "1 min",
                "action_url": "/account/google/",
                "action_text": "Review Campaigns",
                "priority_score": total_waste * 2,
            })

        # 2. Budget-limited campaigns (high CTR but low impression share proxy: high spend relative to budget)
        budget_opps = db.session.execute(text("""
            SELECT ac.name, ac.id AS campaign_id,
                   ac.daily_budget_cents / 100.0 AS daily_budget,
                   SUM(gs.cost_micros) / 1000000.0 / COUNT(DISTINCT gs.date) AS avg_daily_spend,
                   SUM(gs.conversions) AS conversions
            FROM gads_stats_daily gs
            JOIN ads_campaigns ac ON ac.id = gs.entity_id
            WHERE ac.account_id = :aid
              AND gs.entity_type = 'campaign'
              AND gs.date >= :month_start
              AND ac.status = 'enabled'
              AND ac.daily_budget_cents > 0
            GROUP BY ac.id, ac.name, ac.daily_budget_cents
            HAVING SUM(gs.conversions) >= 2
               AND SUM(gs.cost_micros) / 1000000.0 / COUNT(DISTINCT gs.date) >= ac.daily_budget_cents * 0.9 / 100.0
            ORDER BY SUM(gs.conversions) DESC
            LIMIT 1
        """), {"aid": aid, "month_start": month_start}).mappings().first()

        if budget_opps:
            est_leads = max(1, int(float(budget_opps["conversions"] or 0) * 0.15))
            wins.append({
                "win_type": "budget_reallocation",
                "title": f"Increase Budget for '{budget_opps['name']}'",
                "description": f"This campaign is hitting its daily budget cap. A 20% increase could add ~{est_leads} more leads/month.",
                "impact_monthly_value": 0,
                "impact_leads": est_leads,
                "difficulty": "medium",
                "time_estimate": "5 mins",
                "action_url": "/account/google/budget-planning",
                "action_text": "Adjust Budget",
                "priority_score": est_leads * 750,
            })

        # 3. Quality/CTR: campaigns with high impressions but very low CTR (< 1%)
        low_ctr = db.session.execute(text("""
            SELECT ac.name, ac.id AS campaign_id,
                   SUM(gs.impressions) AS impressions,
                   SUM(gs.clicks) AS clicks,
                   SUM(gs.cost_micros) / 1000000.0 AS spend
            FROM gads_stats_daily gs
            JOIN ads_campaigns ac ON ac.id = gs.entity_id
            WHERE ac.account_id = :aid
              AND gs.entity_type = 'campaign'
              AND gs.date >= :month_start
              AND ac.status = 'enabled'
            GROUP BY ac.id, ac.name
            HAVING SUM(gs.impressions) > 500
               AND (SUM(gs.clicks) * 100.0 / SUM(gs.impressions)) < 1.0
               AND SUM(gs.cost_micros) > 0
            ORDER BY SUM(gs.impressions) DESC
            LIMIT 1
        """), {"aid": aid, "month_start": month_start}).mappings().first()

        if low_ctr:
            ctr = round(float(low_ctr["clicks"] or 0) / float(low_ctr["impressions"]) * 100, 2) if low_ctr["impressions"] else 0
            est_savings = round(float(low_ctr["spend"] or 0) * 0.15, 0)
            wins.append({
                "win_type": "quality_score_improvement",
                "title": f"Improve Ad Copy for '{low_ctr['name']}'",
                "description": f"CTR is {ctr}% on {int(low_ctr['impressions'] or 0):,} impressions. Better headlines could cut wasted impressions and save ~${est_savings:.0f}/mo.",
                "impact_monthly_value": est_savings,
                "impact_leads": 0,
                "difficulty": "medium",
                "time_estimate": "15 mins",
                "action_url": "/account/google/",
                "action_text": "View Campaigns",
                "priority_score": est_savings * 1.5,
            })

        # Sort by priority score and return top 3
        wins.sort(key=lambda w: w["priority_score"], reverse=True)
        return jsonify({"wins": wins[:3], "count": len(wins[:3])})

    except Exception as exc:
        current_app.logger.exception("dashboard_quick_wins error: %s", exc)
        return jsonify({"wins": [], "count": 0, "error": str(exc)})


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
    """
    Stripe webhook handler for subscription and payment events.
    Verifies webhook signature and processes events.
    """
    import stripe
    from app.services.stripe_service import process_webhook_event

    payload = request.data
    sig_header = request.headers.get("Stripe-Signature")
    webhook_secret = current_app.config.get("STRIPE_WEBHOOK_SECRET")

    if not webhook_secret:
        current_app.logger.error("STRIPE_WEBHOOK_SECRET not configured")
        return jsonify({"error": "Webhook secret not configured"}), 500

    try:
        # Verify webhook signature
        event = stripe.Webhook.construct_event(
            payload, sig_header, webhook_secret
        )
    except ValueError as e:
        # Invalid payload
        current_app.logger.error(f"Invalid webhook payload: {e}")
        return jsonify({"error": "Invalid payload"}), 400
    except stripe.error.SignatureVerificationError as e:
        # Invalid signature
        current_app.logger.error(f"Invalid webhook signature: {e}")
        return jsonify({"error": "Invalid signature"}), 400

    # Process the event
    try:
        handled = process_webhook_event(event)
        if handled:
            return jsonify({"status": "success", "event": event["type"]}), 200
        else:
            # Event type not handled (not an error)
            return jsonify({"status": "ignored", "event": event["type"]}), 200
    except Exception as e:
        current_app.logger.error(f"Error processing webhook: {e}", exc_info=True)
        return jsonify({"error": "Processing failed"}), 500


@account_bp.route("/billing/checkout/<plan>", methods=["POST"], endpoint="billing_checkout_plan")
@login_required
def billing_checkout_plan(plan: str):
    """
    Create a Stripe checkout session for a subscription plan.
    """
    import stripe
    from flask import g
    from app.services.stripe_service import create_subscription

    # Verify user is loaded
    if not hasattr(g, 'user') or not g.user:
        current_app.logger.error("g.user not available in billing_checkout_plan")
        flash("Authentication error. Please log in again.", "error")
        return redirect(url_for("auth_bp.login"))

    if plan not in ['monthly', 'yearly']:
        flash("Invalid plan selected.", "error")
        return redirect(url_for("main_bp.pricing"))

    # Get the price ID from config
    if plan == 'monthly':
        price_id = current_app.config.get("STRIPE_MONTHLY_PRICE_ID")
        direct_link = current_app.config.get("STRIPE_MONTHLY_LINK")
    else:
        price_id = current_app.config.get("STRIPE_YEARLY_PRICE_ID")
        direct_link = current_app.config.get("STRIPE_YEARLY_LINK")

    # If no price ID, fall back to direct Stripe payment link
    if not price_id:
        if direct_link:
            current_app.logger.info(f"Using direct Stripe link for {plan} plan")
            return redirect(direct_link)
        flash(f"Stripe {plan} plan is not configured. Please contact support.", "error")
        current_app.logger.error(f"Stripe {plan} price ID not configured")
        return redirect(url_for("main_bp.pricing"))

    try:
        # Create checkout session using optimized stripe service
        current_app.logger.info(f"Creating checkout session for user {g.user.id}, plan {plan}")

        _, checkout_url = create_subscription(
            user_id=str(g.user.id),
            price_id=price_id,
            email=g.user.email,
            name=getattr(g.user, 'name', None)
        )

        current_app.logger.info(f"Checkout session created successfully, redirecting to: {checkout_url}")

        # Redirect to Stripe checkout
        return redirect(checkout_url)

    except ValueError as e:
        current_app.logger.error(f"Stripe configuration error: {e}", exc_info=True)
        # Fall back to direct link if available
        if direct_link:
            current_app.logger.info(f"Falling back to direct Stripe link for {plan}")
            return redirect(direct_link)
        flash("Payment configuration error. Please contact support.", "error")
        return redirect(url_for("main_bp.pricing"))
    except stripe.error.StripeError as e:
        current_app.logger.error(f"Stripe error during checkout: {e}", exc_info=True)
        # Fall back to direct link if available
        if direct_link:
            current_app.logger.info(f"Falling back to direct Stripe link for {plan}")
            return redirect(direct_link)
        flash("Payment processing error. Please try again.", "error")
        return redirect(url_for("main_bp.pricing"))
    except Exception as e:
        current_app.logger.error(f"Error creating checkout session: {e}", exc_info=True)
        # Fall back to direct link if available
        if direct_link:
            current_app.logger.info(f"Falling back to direct Stripe link for {plan}")
            return redirect(direct_link)
        flash("An unexpected error occurred. Please try again.", "error")
        return redirect(url_for("main_bp.pricing"))


@account_bp.route("/billing/portal", methods=["GET", "POST"], endpoint="billing_portal")
@login_required
def billing_portal():
    """
    Redirect to Stripe Customer Portal for managing subscriptions.
    """
    import stripe
    from flask import g

    # Verify user is loaded
    if not hasattr(g, 'user') or not g.user:
        current_app.logger.error("g.user not available in billing_portal")
        flash("Authentication error. Please log in again.", "error")
        return redirect(url_for("auth_bp.login"))

    # Initialize Stripe
    stripe.api_key = current_app.config.get("STRIPE_SECRET_KEY")

    if not stripe.api_key:
        flash("Payment system not configured. Please contact support.", "error")
        current_app.logger.error("STRIPE_SECRET_KEY not configured")
        return redirect(url_for("account_bp.dashboard"))

    try:
        # Get or create Stripe customer
        from app.services.stripe_service import get_or_create_stripe_customer

        customer = get_or_create_stripe_customer(
            user_id=str(g.user.id),
            email=g.user.email,
            name=getattr(g.user, 'name', None)
        )

        # Create portal session
        return_url = url_for("account_bp.dashboard", _external=True)
        portal_session = stripe.billing_portal.Session.create(
            customer=customer.stripe_customer_id,
            return_url=return_url
        )

        return redirect(portal_session.url)

    except Exception as e:
        flash("Unable to access billing portal. Please try again.", "error")
        current_app.logger.error(f"Error creating portal session: {e}", exc_info=True)
        return redirect(url_for("account_bp.dashboard"))
