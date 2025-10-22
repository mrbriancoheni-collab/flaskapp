# app/google/__init__.py
from __future__ import annotations
from flask import Blueprint, current_app, request, redirect, url_for, session, render_template, flash
import json
import os
from datetime import datetime, timedelta, date
from urllib.parse import urlencode, urlparse, parse_qs
from flask_login import current_user, login_required

import requests
from flask import (
    Blueprint,
    current_app,
    redirect,
    render_template,
    request,
    session,
    url_for,
    flash,
    jsonify,
)
from sqlalchemy import text

from app import db
from app.auth.utils import login_required, current_account_id
from app.google.utils_ads import (
    pick_and_save_customer_id_after_oauth,
    save_customer_id,
)

google_bp = Blueprint("google_bp", __name__, url_prefix="/account/google")

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"

CANONICAL = {"ga", "ads", "gsc", "gmb", "lsa"}

PRODUCT_ALIASES = {
    "ga": "ga", "analytics": "ga", "googleanalytics": "ga",
    "google-analytics": "ga", "google_analytics": "ga",
    "ga_oauth": "ga", "analytics_oauth": "ga",
    "ads": "ads", "adwords": "ads", "googleads": "ads",
    "google-ads": "ads", "google_ads": "ads", "ads_oauth": "ads",
    "gsc": "gsc", "searchconsole": "gsc", "search-console": "gsc",
    "search_console": "gsc", "gsc_oauth": "gsc",
    "gmb": "gmb", "googlebusiness": "gmb", "google-business": "gmb",
    "google_business": "gmb", "mybusiness": "gmb", "google_my_business": "gmb",
    "lsa": "lsa", "glsa": "lsa", "localservices": "lsa",
    "local-services": "lsa", "local_services": "lsa",
    "localservicesads": "lsa", "local-services-ads": "lsa",
    "local_services_ads": "lsa", "localservices_advertising": "lsa",
}

SCOPES = {
    "ga":  ["https://www.googleapis.com/auth/analytics.readonly"],
    "ads": ["https://www.googleapis.com/auth/adwords"],
    "gsc": ["https://www.googleapis.com/auth/webmasters.readonly"],
    "gmb": ["https://www.googleapis.com/auth/business.manage"],
    "lsa": ["https://www.googleapis.com/auth/adwords"],
}

PRODUCT_CLIENT_ENV = {
    "ads": ("GOOGLE_ADS_CLIENT_ID", "GOOGLE_ADS_CLIENT_SECRET"),
    "ga": ("GOOGLE_ANALYTICS_CLIENT_ID", "GOOGLE_ANALYTICS_SECRET"),
    "gsc": ("GOOGLE_SEARCH_CONSOLE_CLIENT_ID", "GOOGLE_SEARCH_CONSOLE_SECRET"),
    "lsa": ("GOOGLE_LSA_CLIENT_ID", "GOOGLE_LSA_SECRET"),
}

# ------------------------- OpenAI (for insights) -------------------------
try:
    from openai import OpenAI
    _OPENAI_OK = True
except Exception:
    _OPENAI_OK = False

# ------------------------- GA clients (Data + Admin) -------------------------
try:
    from google.analytics.data_v1beta import BetaAnalyticsDataClient  # noqa
    from google.analytics.data_v1beta.types import (  # noqa
        DateRange, Metric, Dimension, RunReportRequest,
        FilterExpression, Filter, FilterExpressionList
    )
    _GA_OK = True
except Exception:
    _GA_OK = False

try:
    from google.analytics.admin_v1beta import AnalyticsAdminServiceClient
    _GA_ADMIN_OK = True
except Exception:
    _GA_ADMIN_OK = False

# ------------------------- Jinja helpers -------------------------
@google_bp.app_context_processor
def google_ctx_injector():
    def has_endpoint(endpoint_name: str) -> bool:
        try:
            return endpoint_name in current_app.view_functions
        except Exception:
            return False

    def bp_exists(bp_name: str) -> bool:
        try:
            return bp_name in current_app.blueprints
        except Exception:
            return False

    return {
        "app": current_app,           # <— add this
        "current_app": current_app,
        "has_endpoint": has_endpoint,
        "bp_exists": bp_exists,
    }

# ------------------------- Helpers -------------------------

def _external_base() -> str | None:
    return (
        os.getenv("GOOGLE_EXTERNAL_BASE_URL")
        or current_app.config.get("GOOGLE_EXTERNAL_BASE_URL")
        or os.getenv("EXTERNAL_BASE_URL")
        or current_app.config.get("EXTERNAL_BASE_URL")
    )

def _redirect_uri() -> str:
    explicit = os.getenv("GOOGLE_REDIRECT_URI") or current_app.config.get("GOOGLE_REDIRECT_URI")
    if explicit:
        return explicit
    base = _external_base()
    if base:
        return f"{base}/account/google/callback"
    return url_for("google_bp.oauth_callback", _external=True, _scheme="https")

def _client_info(product: str) -> tuple[str | None, str | None]:
    id_key, secret_key = PRODUCT_CLIENT_ENV.get(product, (None, None))
    if id_key and secret_key:
        prod_id = os.getenv(id_key) or current_app.config.get(id_key)
        prod_secret = os.getenv(secret_key) or current_app.config.get(secret_key)
        if prod_id and prod_secret:
            return prod_id, prod_secret
    return (
        os.getenv("GOOGLE_CLIENT_ID") or current_app.config.get("GOOGLE_CLIENT_ID"),
        os.getenv("GOOGLE_CLIENT_SECRET") or current_app.config.get("GOOGLE_CLIENT_SECRET"),
    )

def _normalize_product(name: str) -> str | None:
    if not name:
        return None
    raw = str(name).strip().lower()
    normalized = raw.replace("/", "-").replace("_", "-")
    normalized = "-".join(s for s in normalized.replace(" ", "-").split("-") if s)
    key = PRODUCT_ALIASES.get(normalized)
    if key in CANONICAL:
        return key
    if "local" in normalized and "service" in normalized:
        return "lsa"
    if "adword" in normalized or ("google" in normalized and "ad" in normalized):
        return "ads"
    if "analytic" in normalized:
        return "ga"
    if "search" in normalized or "console" in normalized or normalized == "gsc":
        return "gsc"
    if "business" in normalized or normalized == "gmb":
        return "gmb"
    current_app.logger.warning("Google OAuth normalize failed; raw='%s' normalized='%s'", raw, normalized)
    return None

def _store_tokens(account_id: int, product: str, token_json: dict):
    at_raw = token_json.get("access_token")
    rt_raw = token_json.get("refresh_token")
    access_token = at_raw.strip() if isinstance(at_raw, str) else at_raw
    refresh_token = rt_raw.strip() if isinstance(rt_raw, str) else rt_raw

    expires_in = token_json.get("expires_in")
    explicit_expiry = token_json.get("expiry") or token_json.get("token_expiry") or token_json.get("expiry_date")
    if explicit_expiry:
        ts = str(explicit_expiry).rstrip("Z")
        try:
            token_expiry = datetime.fromisoformat(ts)
        except Exception:
            token_expiry = None
    elif expires_in:
        token_expiry = datetime.utcnow() + timedelta(seconds=int(expires_in))
    else:
        token_expiry = None

    cleaned = dict(token_json)
    if access_token is not None:
        cleaned["access_token"] = access_token
    if refresh_token is not None:
        cleaned["refresh_token"] = refresh_token

    with db.engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO google_oauth_tokens
                    (account_id, product, credentials_json,
                     access_token, refresh_token, token_expiry,
                     created_at, updated_at)
                VALUES
                    (:aid, :prod, :creds,
                     :at, :rt, :exp,
                     NOW(), NOW())
                ON DUPLICATE KEY UPDATE
                    credentials_json = VALUES(credentials_json),
                    access_token     = VALUES(access_token),
                    refresh_token    = COALESCE(VALUES(refresh_token), refresh_token),
                    token_expiry     = VALUES(token_expiry),
                    updated_at       = NOW()
                """
            ),
            {
                "aid": account_id,
                "prod": product,
                "creds": json.dumps(cleaned),
                "at": access_token,
                "rt": refresh_token,
                "exp": token_expiry,
            },
        )

# ------------------------- GA property selection helpers -------------------------

def _get_ga_selected_property(aid: int) -> tuple[str | None, str | None]:
    try:
        with db.engine.connect() as conn:
            row = (
                conn.execute(
                    text("""
                        SELECT ga_property_id, ga_property_name
                        FROM google_oauth_tokens
                        WHERE account_id=:aid AND product='ga'
                        ORDER BY id DESC LIMIT 1
                    """),
                    {"aid": aid},
                )
            ).mappings().first()
        if not row:
            return None, None
        return row.get("ga_property_id"), row.get("ga_property_name")
    except Exception:
        current_app.logger.exception("Reading GA selected property failed")
        return None, None

def _set_ga_selected_property(aid: int, prop_id: str, prop_name: str | None):
    try:
        with db.engine.begin() as conn:
            conn.execute(
                text("""
                    UPDATE google_oauth_tokens t
                    JOIN (
                        SELECT id
                        FROM google_oauth_tokens
                        WHERE account_id = :aid AND product = 'ga'
                        ORDER BY id DESC
                        LIMIT 1
                    ) last_row ON last_row.id = t.id
                    SET t.ga_property_id   = :pid,
                        t.ga_property_name = :pname,
                        t.updated_at       = NOW()
                """),
                {"aid": aid, "pid": prop_id, "pname": prop_name},
            )
    except Exception:
        current_app.logger.exception("Saving GA selected property failed")

def _get_ga_user_tokens(aid: int) -> dict | None:
    try:
        with db.engine.connect() as conn:
            row = (
                conn.execute(
                    text("SELECT credentials_json FROM google_oauth_tokens WHERE account_id=:aid AND product='ga' ORDER BY id DESC LIMIT 1"),
                    {"aid": aid},
                )
            ).mappings().first()
        if not row:
            return None
        return json.loads(row["credentials_json"])
    except Exception:
        current_app.logger.exception("Failed reading GA user tokens")
        return None

def _refresh_ga_user_access_token(tokens: dict) -> dict | None:
    client_id, client_secret = _client_info("ga")
    refresh_token = (tokens or {}).get("refresh_token")
    if not (client_id and client_secret and refresh_token):
        return None
    try:
        resp = requests.post(
            GOOGLE_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
            },
            timeout=10,
        )
        resp.raise_for_status()
        refreshed = resp.json()
        merged = dict(tokens)
        merged["access_token"] = refreshed.get("access_token")
        if refreshed.get("expires_in"):
            merged["expires_in"] = refreshed["expires_in"]
        return merged
    except Exception:
        current_app.logger.exception("Failed refreshing GA user token")
        return None

def _admin_list_properties_via_user_token(aid: int) -> list[dict]:
    tokens = _get_ga_user_tokens(aid)
    if not tokens:
        return []
    access_token = tokens.get("access_token")
    if not access_token and tokens.get("refresh_token"):
        tokens = _refresh_ga_user_access_token(tokens)
        access_token = (tokens or {}).get("access_token")
    if not access_token:
        return []
    try:
        r = requests.get(
            "https://analyticsadmin.googleapis.com/v1beta/accountSummaries",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
        if r.status_code == 401 and tokens.get("refresh_token"):
            tokens2 = _refresh_ga_user_access_token(tokens)
            if tokens2 and tokens2.get("access_token"):
                r = requests.get(
                    "https://analyticsadmin.googleapis.com/v1beta/accountSummaries",
                    headers={"Authorization": f"Bearer {tokens2['access_token']}"},
                    timeout=10,
                )
        if not r.ok:
            current_app.logger.warning("Admin list accountSummaries failed: %s %s", r.status_code, r.text[:200])
            return []
        out = []
        for acc in r.json().get("accountSummaries", []) or []:
            for ps in acc.get("propertySummaries", []) or []:
                out.append({"property": ps.get("property"), "displayName": ps.get("displayName")})
        return out
    except Exception:
        current_app.logger.exception("Admin list properties via user token errored")
        return []

def _plain_prop_id(raw: str | None) -> str | None:
    if not raw:
        return None
    return str(raw).split("/")[-1]

def _norm_prop_id(raw: str | None) -> str | None:
    pid = _plain_prop_id(raw)
    return f"properties/{pid}" if pid else None

def _ga_data_creds():
    """
    Build service-account credentials for Admin API lookups (property name).
    Safe even if analytics-data libs aren't installed.
    """
    try:
        from google.oauth2 import service_account as sa  # local import avoids NameError
    except Exception:
        return None

    scopes = ["https://www.googleapis.com/auth/analytics.readonly"]
    creds_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    try:
        if creds_json:
            return sa.Credentials.from_service_account_info(json.loads(creds_json), scopes=scopes)
        if creds_path:
            return sa.Credentials.from_service_account_file(creds_path, scopes=scopes)
    except Exception as e:
        current_app.logger.warning("GA credentials build failed: %s", e)
    return None

_PROP_NAME_CACHE: dict[str, str] = {}

def _ga_property_name(property_id_raw: str) -> str | None:
    if not _GA_ADMIN_OK:
        return None
    pid = _plain_prop_id(property_id_raw)
    if not pid:
        return None
    if pid in _PROP_NAME_CACHE:
        return _PROP_NAME_CACHE[pid]
    try:
        creds = _ga_data_creds()
        if not creds:
            return None
        admin = AnalyticsAdminServiceClient(credentials=creds)
        prop = admin.get_property(name=f"properties/{pid}")
        name = getattr(prop, "display_name", None) or getattr(prop, "displayName", None)
        if name:
            _PROP_NAME_CACHE[pid] = name
        return name
    except Exception as e:
        current_app.logger.warning("GA Admin name lookup failed for %s: %s", pid, e)
        return None

def _admin_property_name_via_user_token(aid: int, property_id_raw: str) -> str | None:
    pid = _plain_prop_id(property_id_raw)
    if not pid:
        return None
    tokens = _get_ga_user_tokens(aid)
    if not tokens:
        return None
    access_token = tokens.get("access_token")
    if not access_token and tokens.get("refresh_token"):
        tokens = _refresh_ga_user_access_token(tokens)
        access_token = (tokens or {}).get("access_token")
    if not access_token:
        return None
    try:
        r = requests.get(
            f"https://analyticsadmin.googleapis.com/v1beta/properties/{pid}",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
        if r.status_code == 401 and tokens.get("refresh_token"):
            tokens2 = _refresh_ga_user_access_token(tokens)
            if tokens2 and tokens2.get("access_token"):
                r = requests.get(
                    f"https://analyticsadmin.googleapis.com/v1beta/properties/{pid}",
                    headers={"Authorization": f"Bearer {tokens2['access_token']}"},
                    timeout=10,
                )
        if r.ok:
            data = r.json()
            return data.get("displayName") or data.get("display_name")
        current_app.logger.warning("Admin API via user token failed: %s %s", r.status_code, r.text[:200])
    except Exception:
        current_app.logger.exception("Admin API call via user token errored")
    return None

def _ga_property_name_any(property_id_raw: str, aid: int | None = None) -> str | None:
    name = _ga_property_name(property_id_raw)
    if name:
        return name
    if aid is not None:
        name = _admin_property_name_via_user_token(aid, property_id_raw)
        if name:
            return name
    return None

def _ensure_default_ga_property_selected(aid: int):
    existing_id, _ = _get_ga_selected_property(aid)
    if existing_id:
        return
    env_pid = os.getenv("GA_PROPERTY_ID")
    if env_pid:
        pid = _norm_prop_id(env_pid)
        name = _ga_property_name_any(env_pid, aid) or os.getenv("GA_PROPERTY_LABEL")
        if pid:
            _set_ga_selected_property(aid, pid, name)
            return
    props = _admin_list_properties_via_user_token(aid)
    if props:
        pid = props[0].get("property")
        name = props[0].get("displayName")
        if pid:
            _set_ga_selected_property(aid, pid, name)

# ---------- GSC helpers ----------
def _get_gsc_user_tokens(aid: int) -> dict | None:
    try:
        with db.engine.connect() as conn:
            row = (
                conn.execute(
                    text("SELECT credentials_json FROM google_oauth_tokens WHERE account_id=:aid AND product='gsc' ORDER BY id DESC LIMIT 1"),
                    {"aid": aid},
                )
            ).mappings().first()
        if not row:
            return None
        return json.loads(row["credentials_json"])
    except Exception:
        current_app.logger.exception("Failed reading GSC user tokens")
        return None

def _refresh_gsc_user_access_token(tokens: dict) -> dict | None:
    client_id, client_secret = _client_info("gsc")
    refresh_token = (tokens or {}).get("refresh_token")
    if not (client_id and client_secret and refresh_token):
        return None
    try:
        resp = requests.post(
            GOOGLE_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
            },
            timeout=10,
        )
        resp.raise_for_status()
        refreshed = resp.json()
        merged = dict(tokens)
        merged["access_token"] = refreshed.get("access_token")
        if refreshed.get("expires_in"):
            merged["expires_in"] = refreshed["expires_in"]
        return merged
    except Exception:
        current_app.logger.exception("Failed refreshing GSC user token")
        return None

def _gsc_user_access_token(aid: int) -> str | None:
    tokens = _get_gsc_user_tokens(aid)
    if not tokens:
        return None
    at = tokens.get("access_token")
    if not at and tokens.get("refresh_token"):
        tokens = _refresh_gsc_user_access_token(tokens)
        at = (tokens or {}).get("access_token")
    return at

def _get_gsc_selected_site(aid: int) -> str | None:
    try:
        with db.engine.connect() as conn:
            row = (
                conn.execute(
                    text("""
                        SELECT gsc_site
                        FROM google_oauth_tokens
                        WHERE account_id=:aid AND product='gsc'
                        ORDER BY id DESC LIMIT 1
                    """),
                    {"aid": aid},
                )
            ).mappings().first()
        return (row or {}).get("gsc_site")
    except Exception:
        current_app.logger.exception("Reading GSC selected site failed")
        return None

def _set_gsc_selected_site(aid: int, site_url: str | None):
    if not site_url:
        return
    try:
        with db.engine.begin() as conn:
            conn.execute(
                text("""
                    UPDATE google_oauth_tokens t
                    JOIN (
                        SELECT id
                        FROM google_oauth_tokens
                        WHERE account_id = :aid AND product = 'gsc'
                        ORDER BY id DESC
                        LIMIT 1
                    ) last_row ON last_row.id = t.id
                    SET t.gsc_site  = :site,
                        t.updated_at = NOW()
                """),
                {"aid": aid, "site": site_url},
            )
    except Exception:
        current_app.logger.exception("Saving GSC selected site failed")

def _gsc_list_sites(aid: int) -> list[dict]:
    at = _gsc_user_access_token(aid)
    if not at:
        return []
    url = "https://www.googleapis.com/webmasters/v3/sites"
    hdrs = {"Authorization": f"Bearer {at}"}
    try:
        r = requests.get(url, headers=hdrs, timeout=15)
        if r.status_code == 401:
            tokens = _refresh_gsc_user_access_token(_get_gsc_user_tokens(aid) or {})
            new_at = (tokens or {}).get("access_token")
            if new_at:
                hdrs["Authorization"] = f"Bearer {new_at}"
                r = requests.get(url, headers=hdrs, timeout=15)
        if not r.ok:
            current_app.logger.warning("GSC sites list failed: %s %s", r.status_code, r.text[:200])
            return []
        items = r.json().get("siteEntry", []) or []
        # Prefer verified sites the user has access to
        items = [s for s in items if (s.get("permissionLevel") or "").lower() != "siteunverifieduser"]
        return [{"siteUrl": s.get("siteUrl"), "permissionLevel": s.get("permissionLevel")} for s in items if s.get("siteUrl")]
    except Exception:
        current_app.logger.exception("GSC list sites errored")
        return []

def _ensure_default_gsc_site_selected(aid: int):
    if _get_gsc_selected_site(aid):
        return
    sites = _gsc_list_sites(aid)
    if sites:
        _set_gsc_selected_site(aid, sites[0]["siteUrl"])

def _fetch_ads_live(aid: int):
    cid = _get_saved_customer_id(aid, conn)
    if not cid:
        # Fall back instead of raising
        current_app.logger.info("No CID; returning empty snapshot with CTA")
        return {"ok": True, "data": [], "needs_setup": True}

def _fetch_gsc_report(site_url: str, start_date: str, end_date: str) -> dict | None:
    """Return clicks, impressions, ctr, position, top pages, top queries from GSC."""
    if not site_url:
        return None

    aid = current_account_id()
    at = _gsc_user_access_token(aid)
    if not at:
        current_app.logger.warning("GSC: no user access token")
        return None

    base = f"https://searchconsole.googleapis.com/webmasters/v3/sites/{site_url}/searchAnalytics/query"
    hdrs = {"Authorization": f"Bearer {at}", "Content-Type": "application/json"}

    def _post(payload: dict) -> requests.Response:
        r = requests.post(base, headers=hdrs, json=payload, timeout=20)
        if r.status_code == 401:
            tokens = _refresh_gsc_user_access_token(_get_gsc_user_tokens(aid) or {})
            new_at = (tokens or {}).get("access_token")
            if new_at:
                hdrs["Authorization"] = f"Bearer {new_at}"
                r = requests.post(base, headers=hdrs, json=payload, timeout=20)
        return r

    # KPIs (no dimensions): aggregated totals
    kpi_payload = {
        "startDate": start_date,
        "endDate": end_date,
        "dimensions": [],
        "rowLimit": 1
    }
    r_kpi = _post(kpi_payload)
    if not r_kpi.ok:
        current_app.logger.warning("GSC KPI failed: %s %s", r_kpi.status_code, r_kpi.text[:200])
        return None
    kpi_rows = (r_kpi.json().get("rows") or [])
    clicks = impressions = 0
    ctr = position = 0.0
    if kpi_rows:
        row = kpi_rows[0]
        clicks = int(row.get("clicks", 0))
        impressions = int(row.get("impressions", 0))
        ctr = float(row.get("ctr", 0.0))
        position = float(row.get("position", 0.0))

    # Top pages
    top_pages: list[dict] = []
    rp = _post({
        "startDate": start_date,
        "endDate": end_date,
        "dimensions": ["page"],
        "rowLimit": 10,
        "orderBy": [{"fieldName": "clicks", "order": "descending"}],
    })
    if rp.ok:
        for row in rp.json().get("rows", []):
            page = (row.get("keys") or [""])[0]
            top_pages.append({
                "page": page,
                "clicks": int(row.get("clicks", 0)),
                "impressions": int(row.get("impressions", 0)),
                "ctr": round(float(row.get("ctr", 0.0)) * 100, 2),
                "position": round(float(row.get("position", 0.0)), 1),
            })

    # Top queries
    top_queries: list[dict] = []
    rq = _post({
        "startDate": start_date,
        "endDate": end_date,
        "dimensions": ["query"],
        "rowLimit": 10,
        "orderBy": [{"fieldName": "clicks", "order": "descending"}],
    })
    if rq.ok:
        for row in rq.json().get("rows", []):
            q = (row.get("keys") or [""])[0]
            top_queries.append({
                "query": q,
                "clicks": int(row.get("clicks", 0)),
                "impressions": int(row.get("impressions", 0)),
                "ctr": round(float(row.get("ctr", 0.0)) * 100, 2),
                "position": round(float(row.get("position", 0.0)), 1),
            })

    return {
        "site_url": site_url,
        "clicks": clicks,
        "impressions": impressions,
        "ctr_pct": round(ctr * 100, 2),
        "avg_position": round(position, 1),
        "top_pages": top_pages,
        "top_queries": top_queries,
    }

# --- OpenAI Insights --------------------------------------------------------
from openai import OpenAI
import json
import math
from flask import current_app

def _build_insights_prompt(gsc: dict) -> str:
    """Make a compact, deterministic prompt for AI insights."""
    # keep only what's needed & keep it small
    summary = {
        "property": gsc.get("property") or gsc.get("site_url") or "",
        "period": gsc.get("period") or "Last 28 days",
        "clicks": int(gsc.get("clicks", 0) or 0),
        "impressions": int(gsc.get("impressions", 0) or 0),
        "ctr_pct": float(gsc.get("ctr_pct", 0) or 0.0),
        "avg_position": float(gsc.get("avg_position", 0) or 0.0),
        "top_queries": [
            {
                "query": q.get("query",""),
                "clicks": int(q.get("clicks",0) or 0),
                "impressions": int(q.get("impressions",0) or 0),
                "ctr_pct": float(q.get("ctr_pct", (q.get('ctr') or 0)*100)),
                "position": float(q.get("position",0.0) or 0.0),
            } for q in (gsc.get("top_queries") or [])[:15]
        ],
        "top_pages": [
            {
                "url": p.get("url") or p.get("page") or "",
                "clicks": int(p.get("clicks",0) or 0),
                "impressions": int(p.get("impressions",0) or 0),
                "ctr_pct": float(p.get("ctr_pct", (p.get('ctr') or 0)*100)),
                "position": float(p.get("position",0.0) or 0.0),
            } for p in (gsc.get("top_pages") or [])[:15]
        ],
    }

    return (
        "You are an SEO & CRO analyst. Given Search Console metrics, produce specific, "
        "impact-ordered recommendations to improve content, conversion, and revenue.\n\n"
        "Constraints:\n"
        "• Be concise (bullet points, 6–10 items total). \n"
        "• Group into three sections: Content, Conversion, Revenue. \n"
        "• Reference concrete queries/pages and include quick win thresholds (e.g., CTR < 1%, position 8–20). \n"
        "• Suggest titles/meta/faq ideas, internal links, and on-page experiments when relevant. \n"
        "• If data looks like a demo or zeros, say so and suggest next steps.\n\n"
        f"DATA (JSON):\n{json.dumps(summary, ensure_ascii=False)}"
    )

def get_gsc_insights(gsc: dict) -> str:
    """
    Calls OpenAI with the compact prompt. Returns markdown text (or empty string on failure).
    Respects OPENAI_API_KEY and OPENAI_MODEL from app config.
    """
    try:
        api_key = current_app.config.get("OPENAI_API_KEY")
        model = current_app.config.get("OPENAI_MODEL", "gpt-4o-mini")
        if not api_key:
            current_app.logger.info("AI insights skipped: OPENAI_API_KEY missing")
            return ""

        client = OpenAI(api_key=api_key)

        prompt = _build_insights_prompt(gsc)
        # Responses API (official modern surface)
        resp = client.responses.create(
            model=model,
            input=prompt,
            temperature=0.3,
            max_output_tokens=800,
        )

        # Extract plain text
        text = ""
        if resp and resp.output and len(resp.output) and getattr(resp.output[0], "content", None):
            # SDK returns a structured output list; gather all text parts
            parts = []
            for item in resp.output:
                if getattr(item, "content", None):
                    for block in item.content:
                        if block.type == "output_text" or block.type == "text":
                            parts.append(block.text)
            text = "\n".join(parts).strip()

        return text or ""

    except Exception as e:
        current_app.logger.exception("OpenAI insights failed: %s", e)
        return ""


# ------------------------- Misc helpers -------------------------

def _is_connected(account_id: int, product: str) -> bool:
    with db.engine.connect() as conn:
        row = (
            conn.execute(
                text(
                    "SELECT id FROM google_oauth_tokens "
                    "WHERE account_id=:aid AND product=:prod LIMIT 1"
                ),
                {"aid": account_id, "prod": product},
            )
        ).mappings().first()
        return bool(row)

def _ai_enabled() -> bool:
    return bool(
        os.getenv("OPENAI_API_KEY")
        or os.getenv("CHATGPT_API_KEY")
        or current_app.config.get("OPENAI_API_KEY")
        or current_app.config.get("CHATGPT_API_KEY")
    )

def _openai_api_key() -> str | None:
    return (
        os.getenv("OPENAI_API_KEY")
        or current_app.config.get("OPENAI_API_KEY")
        or os.getenv("CHATGPT_API_KEY")
        or current_app.config.get("CHATGPT_API_KEY")
    )

def _ads_custom_prompt_key(aid: int) -> str:
    return f"ads_custom_prompt_{aid}"

def _get_ads_custom_prompt(aid: int) -> str:
    return session.get(_ads_custom_prompt_key(aid)) or (
        "You are FieldSprout AI. Analyze the Google Ads performance data provided as JSON. "
        "Write a crisp executive SUMMARY (3–5 sentences), then INSIGHTS as bullet points "
        "(focus on spend, CPA, ROAS, query intent, device/daypart), and an OPTIMIZATION CHECKLIST "
        "(prioritized, action verbs, no more than 8 items). Be concrete and data-driven."
    )

def _set_ads_custom_prompt(aid: int, prompt: str) -> None:
    session[_ads_custom_prompt_key(aid)] = (prompt or "").strip()

# ------------------------- GA reporting helpers -------------------------

def _resolve_timeframe(tf: str) -> tuple[str, str, str]:
    today = date.today()
    if tf == "7d":
        start = today - timedelta(days=7); label = "Last 7 days"
    elif tf == "14d":
        start = today - timedelta(days=14); label = "Last 14 days"
    elif tf == "28d":
        start = today - timedelta(days=28); label = "Last 28 days"
    elif tf == "30d":
        start = today - timedelta(days=30); label = "Last 30 days"
    elif tf == "90d":
        start = today - timedelta(days=90); label = "Last 90 days"
    elif tf == "this_month":
        start = today.replace(day=1); label = "This month"
    elif tf == "last_month":
        first_this = today.replace(day=1)
        last_month_end = first_this - timedelta(days=1)
        start = last_month_end.replace(day=1); end = last_month_end
        return (start.isoformat(), end.isoformat(), "Last month")
    else:
        start = today - timedelta(days=28); label = "Last 28 days"
    return (start.isoformat(), today.isoformat(), label)

def _fmt_seconds_to_m_ss(value: str | float | int | None) -> str:
    try:
        sec = float(value or 0)
    except Exception:
        return str(value or "")
    m, s = divmod(int(round(sec)), 60)
    return f"{m}m:{s:02d}s"

def _ga_user_access_token(aid: int) -> str | None:
    tokens = _get_ga_user_tokens(aid)
    if not tokens:
        return None
    at = tokens.get("access_token")
    if not at and tokens.get("refresh_token"):
        tokens = _refresh_ga_user_access_token(tokens)
        at = (tokens or {}).get("access_token")
    return at

def _fetch_ga_report(property_name: str, start_date: str, end_date: str) -> dict | None:
    if not property_name:
        return None

    try:
        aid = current_account_id()
        at = _ga_user_access_token(aid)
        if not at:
            current_app.logger.warning("GA Data API: no user access token")
            return None

        headers = {"Authorization": f"Bearer {at}", "Content-Type": "application/json"}
        base = f"https://analyticsdata.googleapis.com/v1beta/{property_name}:runReport"

        # Optional: exclude self-referrals and any other noisy sources you list in env/config
        sources_to_exclude: set[str] = set()
        for h in _own_hostnames():
            sources_to_exclude.add(f"{h} / referral")
        # Also allow hard-coded extra excludes via env/config, comma-separated:
        extra_src = (os.getenv("GA_EXCLUDE_SOURCES") or current_app.config.get("GA_EXCLUDE_SOURCES") or "")
        for item in extra_src.split(","):
            v = item.strip()
            if v:
                sources_to_exclude.add(v)
        dim_filter = _build_exclusion_filter(sorted(sources_to_exclude))

        def _post(payload: dict) -> requests.Response:
            # Attach our dimensionFilter on every call unless caller provided one explicitly
            if dim_filter and "dimensionFilter" not in payload:
                payload = dict(payload)
                payload["dimensionFilter"] = dim_filter
            r = requests.post(base, headers=headers, json=payload, timeout=15)
            if r.status_code == 401:
                # Try a one-time refresh and retry
                tokens = _refresh_ga_user_access_token(_get_ga_user_tokens(aid) or {})
                new_at = (tokens or {}).get("access_token")
                if new_at:
                    headers["Authorization"] = f"Bearer {new_at}"
                    r = requests.post(base, headers=headers, json=payload, timeout=15)
            return r

        # --- KPIs (compute avg engagement = userEngagementDuration / engagedSessions) ---
        kpi_payload = {
            "dateRanges": [{"startDate": start_date, "endDate": end_date}],
            "metrics": [
                {"name": "sessions"},
                {"name": "totalUsers"},
                {"name": "newUsers"},
                {"name": "engagedSessions"},
                {"name": "userEngagementDuration"},  # seconds aggregate
                {"name": "conversions"},
                {"name": "totalRevenue"},
            ],
        }
        r_kpi = _post(kpi_payload)
        if not r_kpi.ok:
            current_app.logger.warning("GA KPI request failed: %s %s", r_kpi.status_code, r_kpi.text[:200])
            return None
        kpi = r_kpi.json()

        def _m(name: str) -> str:
            hdrs = kpi.get("metricHeaders", []) or []
            rows = kpi.get("rows", []) or []
            if not rows:
                return "0"
            try:
                idx = next(i for i, h in enumerate(hdrs) if h.get("name") == name)
            except StopIteration:
                return "0"
            mv = rows[0].get("metricValues", []) or []
            return (mv[idx].get("value") if idx < len(mv) else "0") or "0"

        sessions               = int(float(_m("sessions")))
        users                  = int(float(_m("totalUsers")))
        new_users              = int(float(_m("newUsers")))
        engaged_sessions       = int(float(_m("engagedSessions")))
        engagement_duration_s  = float(_m("userEngagementDuration") or 0.0)
        avg_engagement_secs    = engagement_duration_s / max(float(engaged_sessions or 0), 1.0)
        conversions            = int(float(_m("conversions")))
        revenue                = round(float(_m("totalRevenue") or 0.0), 2)

        # --- Top pages: use pagePathPlusQueryString, compute avg engagement per page ---
        top_pages: list[dict] = []
        rp = _post({
            "dateRanges": [{"startDate": start_date, "endDate": end_date}],
            "dimensions": [{"name": "pagePathPlusQueryString"}],
            "metrics": [
                {"name": "views"},
                {"name": "userEngagementDuration"},
            ],
            "limit": 10,
            "orderBys": [{"metric": {"metricName": "views"}, "desc": True}],
        })
        if rp.ok:
            pj = rp.json()
            for row in pj.get("rows", []) or []:
                dim_vals = row.get("dimensionValues") or []
                url = (dim_vals[0].get("value") if dim_vals else "") or "/"
                mv = row.get("metricValues") or []
                views = int(float((mv[0].get("value") if len(mv) > 0 else "0") or 0))
                dur   = float((mv[1].get("value") if len(mv) > 1 else "0") or 0.0)
                avg_s = (dur / max(views, 1)) if views else 0.0
                top_pages.append({"url": url, "views": views, "engagement": _fmt_seconds_to_m_ss(avg_s)})

        # --- Top sources/medium ---
        top_sources: list[dict] = []
        rs = _post({
            "dateRanges": [{"startDate": start_date, "endDate": end_date}],
            "dimensions": [{"name": "sessionSourceMedium"}],
            "metrics": [{"name": "sessions"}],
            "limit": 10,
            "orderBys": [{"metric": {"metricName": "sessions"}, "desc": True}],
        })
        if rs.ok:
            sj = rs.json()
            for row in sj.get("rows", []) or []:
                sm = (row.get("dimensionValues") or [{}])[0].get("value", "")
                mv = row.get("metricValues") or []
                ses = int(float((mv[0].get("value") if len(mv) > 0 else "0") or 0))
                top_sources.append({"source": sm, "sessions": ses})

        # --- Conversions by event (hide the generic events) ---
        generic_events = {"page_view", "user_engagement", "first_visit", "session_start", "scroll"}
        conversions_by_event: list[dict] = []
        rc = _post({
            "dateRanges": [{"startDate": start_date, "endDate": end_date}],
            "dimensions": [{"name": "eventName"}],
            "metrics": [{"name": "eventCount"}],
            "limit": 25,
            "orderBys": [{"metric": {"metricName": "eventCount"}, "desc": True}],
        })
        if rc.ok:
            cj = rc.json()
            for row in cj.get("rows", []) or []:
                ev = (row.get("dimensionValues") or [{}])[0].get("value", "")
                if ev in generic_events:
                    continue
                mv = row.get("metricValues") or []
                cnt = int(float((mv[0].get("value") if len(mv) > 0 else "0") or 0))
                conversions_by_event.append({"event": ev, "count": cnt})

        return {
            "property_name": _ga_property_name_any(property_name, aid)
                              or current_app.config.get("GA_PROPERTY_LABEL")
                              or "GA4 Property",
            "sessions": sessions,
            "users": users,
            "new_users": new_users,
            "engaged_sessions": engaged_sessions,
            "avg_engagement_time": _fmt_seconds_to_m_ss(avg_engagement_secs),
            "conversions": conversions,
            "revenue": revenue,
            "top_pages": top_pages,
            "top_sources": top_sources,
            "conversions_by_event": conversions_by_event,
        }

    except Exception:
        current_app.logger.exception("GA Data API user-token fetch failed")
        return None



@google_bp.get("/analytics/debug/ping")
@login_required
def ga_debug_ping():
    aid = current_account_id()
    at = _ga_user_access_token(aid)
    pid, _ = _get_ga_selected_property(aid)
    out = {"has_access_token": bool(at), "selected_property": pid}

    if not at:
        return jsonify({**out, "ok": False, "reason": "no_access_token"}), 400

    # Check scopes attached to this token
    try:
        ti = requests.get(
            "https://www.googleapis.com/oauth2/v3/tokeninfo",
            params={"access_token": at},
            timeout=10
        )
        out["tokeninfo_status"] = ti.status_code
        if ti.ok:
            out["token_scopes"] = (ti.json().get("scope") or "").split()
        else:
            out["tokeninfo_error"] = ti.text[:200]
    except Exception as e:
        out["tokeninfo_error"] = f"{e}"

    # Try a trivial GA Admin call via user token (lists account summaries)
    try:
        r = requests.get(
            "https://analyticsadmin.googleapis.com/v1beta/accountSummaries",
            headers={"Authorization": f"Bearer {at}"},
            timeout=15
        )
        out["admin_status"] = r.status_code
        if r.ok:
            out["admin_accounts_count"] = len(r.json().get("accountSummaries", []) or [])
        else:
            out["admin_error"] = r.text[:200]
    except Exception as e:
        out["admin_error"] = f"{e}"

    return jsonify({"ok": True, **out}), 200


# ------------------------- Demo / state helpers (Ads) -------------------------

_SAMPLE_ADS = {
    "account_name": "Demo Plumbing Co.",
    "campaigns": [
        {"id": "C-1001", "name": "Emergency Plumbing - Search", "type": "SEARCH", "status": "Enabled", "daily_budget": 75, "bidding": "tCPA", "target": 65},
        {"id": "C-1002", "name": "Water Heater Install - Search", "type": "SEARCH", "status": "Paused", "daily_budget": 40, "bidding": "Maximize Conversions", "target": None}
    ],
    "ad_groups": [
        {"id": "AG-2001", "campaign_id": "C-1001", "name": "Near Me", "status": "Enabled"},
        {"id": "AG-2002", "campaign_id": "C-1001", "name": "24 Hour", "status": "Enabled"},
        {"id": "AG-2003", "campaign_id": "C-1002", "name": "Tankless", "status": "Paused"}
    ],
    "keywords": [
        {"id": "KW-3001", "ad_group_id": "AG-2001", "match": "Exact", "text": "[emergency plumber near me]", "status": "Enabled", "cpc": 9.50, "conv": 7, "cpa": 58},
        {"id": "KW-3002", "ad_group_id": "AG-2001", "match": "Phrase", "text": "\"emergency leak repair\"", "status": "Enabled", "cpc": 5.10, "conv": 2, "cpa": 92},
        {"id": "KW-3003", "ad_group_id": "AG-2002", "match": "Broad", "text": "plumber 24 hours", "status": "Enabled", "cpc": 3.40, "conv": 0, "cpa": None}
    ],
    "negatives": [
        {"id": "NEG-4001", "scope": "Campaign", "parent_id": "C-1001", "text": "free"},
        {"id": "NEG-4002", "scope": "Campaign", "parent_id": "C-1001", "text": "DIY"},
        {"id": "NEG-4003", "scope": "Account", "parent_id": None, "text": "jobs"}
    ],
    "ads": [
        {"id": "AD-5001", "ad_group_id": "AG-2001", "h1": "Emergency Plumber Near You", "h2": "30–60 Min Arrival", "h3": "Licensed • Insured", "d1": "Fast, professional service. Upfront pricing & guarantees.", "path": "emergency"},
        {"id": "AD-5002", "ad_group_id": "AG-2002", "h1": "24/7 Plumbing Help", "h2": "Call Now • Same-Day", "h3": "Local Techs", "d1": "Clogs, leaks, burst pipes—fixed today.", "path": "24-hr"}
    ],
    "extensions": [
        {"id": "EXT-6001", "type": "Sitelink", "text": "Financing Options", "url": "https://example.com/finance"},
        {"id": "EXT-6002", "type": "Callout", "text": "No Trip Fees", "url": ""}
    ],
    "landing_pages": [
        {"id": "LP-7001", "url": "https://example.com/emergency", "load": "2.1s", "mobile_friendly": True, "notes": "Strong above-the-fold CTA, add trust badges lower."},
        {"id": "LP-7002", "url": "https://example.com/water-heaters", "load": "3.9s", "mobile_friendly": False, "notes": "Hero text small on mobile; consider sticky CTA."}
    ]
}

def _sample_ads() -> dict:
    return _SAMPLE_ADS

def _save_ads_state(aid: int, data: dict):
    session[f"ads_state_{aid}"] = data

def _own_hostnames() -> set[str]:
    """Get hostnames we should treat as 'self', from EXTERNAL_BASE_URL and GA_EXCLUDE_HOSTS."""
    hosts: set[str] = set()
    base = _external_base()
    if base:
        try:
            h = urlparse(base).hostname
            if h:
                hosts.add(h.lower())
        except Exception:
            pass
    extra = (os.getenv("GA_EXCLUDE_HOSTS") or current_app.config.get("GA_EXCLUDE_HOSTS") or "")
    for item in extra.split(","):
        item = item.strip().lower()
        if item:
            hosts.add(item)
    return hosts

def _build_exclusion_filter(sources_to_exclude: list[str]) -> dict | None:
    """
    Build a dimensionFilter to exclude a list of exact sessionSourceMedium values.
    Example excluded values: 'app.storylab.ai / referral'
    """
    if not sources_to_exclude:
        return None
    return {
        "andGroup": {
            "expressions": [
                {
                    "notExpression": {
                        "filter": {
                            "fieldName": "sessionSourceMedium",
                            "stringFilter": {"value": src, "matchType": "EXACT"},
                        }
                    }
                }
                for src in sources_to_exclude
            ]
        }
    }


def _get_saved_customer_id(aid: int) -> str | None:
    try:
        from app.google.utils_ads import get_customer_id  # optional
        cid = get_customer_id(aid)
        if cid:
            return str(cid).replace("-", "")
    except Exception:
        pass
    try:
        with db.engine.connect() as conn:
            row = conn.execute(
                text("""
                    SELECT google_ads_customer_id
                      FROM google_oauth_tokens
                     WHERE account_id=:aid AND product='ads'
                     ORDER BY id DESC LIMIT 1
                """),
                {"aid": aid},
            ).first()
        if row and row[0]:
            return str(row[0]).replace("-", "")
    except Exception:
        current_app.logger.exception("Could not read google_ads_customer_id from tokens table")
    try:
        with db.engine.connect() as conn:
            row = (
                conn.execute(
                    text("SELECT customer_id FROM google_ads_accounts WHERE account_id=:aid ORDER BY id DESC LIMIT 1"),
                    {"aid": aid},
                )
            ).mappings().first()
            cid = (row or {}).get("customer_id")
            return str(cid).replace("-", "") if cid else None
    except Exception:
        current_app.logger.exception("Could not read saved Google Ads customer id (legacy table)")
        return None
def _fetch_ads_snapshot_from_google(aid: int) -> dict:
    customer_id = _get_saved_customer_id(aid)
    if not customer_id:
        raise RuntimeError("No Google Ads customer selected")

    with db.engine.connect() as conn:
        row = (
            conn.execute(
                text("SELECT credentials_json FROM google_oauth_tokens WHERE account_id=:aid AND product='ads' ORDER BY id DESC LIMIT 1"),
                {"aid": aid},
            )
        ).mappings().first()
    if not row:
        raise RuntimeError("No OAuth token record found for Google Ads")

    creds = json.loads(row["credentials_json"])
    refresh_token = creds.get("refresh_token")
    client_id, client_secret = _client_info("ads")

    from google.ads.googleads.client import GoogleAdsClient
    cfg = {
        "developer_token": current_app.config.get("GOOGLE_ADS_DEVELOPER_TOKEN") or os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN"),
        "login_customer_id": (current_app.config.get("GOOGLE_ADS_LOGIN_CUSTOMER_ID") or os.getenv("GOOGLE_ADS_LOGIN_CUSTOMER_ID") or "").replace("-", ""),
        "use_proto_plus": True,
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
    }
    if not cfg["developer_token"]:
        raise RuntimeError("Missing GOOGLE_ADS_DEVELOPER_TOKEN")

    client = GoogleAdsClient.load_from_dict(cfg)

    def _gaql(q: str):
        svc = client.get_service("GoogleAdsService")
        return svc.search(customer_id=customer_id, query=q)

    campaigns = []
    for r in _gaql("""
        SELECT campaign.id, campaign.name, campaign.status,
               campaign.advertising_channel_type, campaign.bidding_strategy_type
        FROM campaign
        WHERE campaign.status != 'REMOVED'
        ORDER BY campaign.id
        LIMIT 50
    """):
        c = r.campaign
        campaigns.append({
            "id": str(c.id),
            "name": c.name,
            "type": str(c.advertising_channel_type).split(".")[-1],
            "status": str(c.status).split(".")[-1],
            "daily_budget": None,
            "bidding": str(c.bidding_strategy_type).split(".")[-1],
            "target": None,
        })

    ad_groups = []
    for r in _gaql("""
        SELECT ad_group.id, ad_group.name, ad_group.status, ad_group.campaign
        FROM ad_group
        WHERE ad_group.status != 'REMOVED'
        ORDER BY ad_group.id
        LIMIT 100
    """):
        ag = r.ad_group
        ad_groups.append({
            "id": str(ag.id),
            "campaign_id": str(ag.campaign.split("/")[-1]),
            "name": ag.name,
            "status": str(ag.status).split(".")[-1],
        })

    keywords = []
    for r in _gaql("""
        SELECT ad_group_criterion.criterion_id, ad_group_criterion.status,
               ad_group_criterion.keyword.text, ad_group_criterion.keyword.match_type,
               ad_group_criterion.ad_group
        FROM ad_group_criterion
        WHERE ad_group_criterion.type = KEYWORD
          AND ad_group_criterion.status != 'REMOVED'
        ORDER BY ad_group_criterion.criterion_id
        LIMIT 100
    """):
        kw = r.ad_group_criterion
        keywords.append({
            "id": str(kw.criterion_id),
            "ad_group_id": str(kw.ad_group.split("/")[-1]),
            "match": str(kw.keyword.match_type).split(".")[-1].title(),
            "text": kw.keyword.text,
            "status": str(kw.status).split(".")[-1],
            "cpc": None,
            "conv": None,
            "cpa": None,
        })

    return {
        "account_name": customer_id,
        "campaigns": campaigns,
        "ad_groups": ad_groups,
        "keywords": keywords,
        "negatives": [],
        "ads": [],
        "extensions": [],
        "landing_pages": [],
        "__source": "live",
    }

def _fetch_ads_live(aid: int) -> dict | None:
    try:
        return _fetch_ads_snapshot_from_google(aid)
    except Exception:
        current_app.logger.exception("Ads live pull: unexpected failure")
        return None

def _get_ads_state(aid: int) -> dict:
    sess_key = f"ads_state_{aid}"
    connected = _is_connected(aid, "ads")
    state = session.get(sess_key)
    if connected:
        if state and state.get("__source") == "live":
            return state
        live = _fetch_ads_live(aid)
        if live:
            session[sess_key] = live
            return live
        return state or {"account_name": "Google Ads Account", "campaigns": [], "ad_groups": [],
                         "keywords": [], "negatives": [], "ads": [], "extensions": [], "landing_pages": []}
    if not state:
        state = json.loads(json.dumps(_sample_ads()))
        session[sess_key] = state
    return state

# ------------------------- Ads AI summary (placeholder JSON) -------------------------

@google_bp.get('/ads/ai-summary.json', endpoint='ads_ai_summary_json')
@login_required
def ads_ai_summary_json():
    return jsonify({
        "summary": "Account looks healthy. Two paused campaigns; consider consolidating budgets.",
        "insights": [
            "Exact match keywords drive 78% of conversions.",
            "Two ad groups have no responsive search ad."
        ],
        "checklist": [
            "Raise daily budget on best CPA campaign.",
            "Add 2 sitelinks + callout extensions."
        ]
    })

# ------------------------- Routes: Index -------------------------

@google_bp.route("/", methods=["GET"], endpoint="index")
@login_required
def index():
    aid = current_account_id()
    connected = {
        "ga":  _is_connected(aid, "ga"),
        "ads": _is_connected(aid, "ads"),
        "gsc": _is_connected(aid, "gsc"),
        "gmb": _is_connected(aid, "gmb"),
        "lsa": _is_connected(aid, "lsa"),
    }
    return render_template("google/index.html", connected=connected, epn=request.endpoint)

# ------------------------- GA Insights (ChatGPT) -------------------------

@google_bp.route("/analytics/insights", methods=["GET"], endpoint="ga_insights")
@login_required
def ga_insights():
    if not _OPENAI_OK or not os.environ.get("OPENAI_API_KEY"):
        return jsonify({
            "summary": "AI is not configured (missing OPENAI_API_KEY).",
            "insights": [],
            "improvements": []
        }), 503

    timeframe = request.args.get("timeframe", "28d")
    start_date, end_date, label = _resolve_timeframe(timeframe)

    ga_struct = None
    aid = current_account_id()

    env_pid_raw = os.getenv("GA_PROPERTY_ID")
    prop_id, prop_name = _get_ga_selected_property(aid)
    effective_prop = prop_id or (_norm_prop_id(env_pid_raw) if env_pid_raw else None)

    try:
        if effective_prop:
            ga_struct = _fetch_ga_report(effective_prop, start_date, end_date)
            if ga_struct:
                ga_struct["period"] = label
                disp = _ga_property_name_any(effective_prop, aid) or prop_name or os.getenv("GA_PROPERTY_LABEL")
                if disp:
                    ga_struct["property_name"] = disp
    except Exception as e:
        current_app.logger.exception("GA fetch for insights failed: %s", e)

    if not ga_struct:
        ga_struct = {
            "property_name": "Demo Property (GA4)",
            "period": label,
            "sessions": 4280,
            "users": 3675,
            "new_users": 3012,
            "engaged_sessions": 2890,
            "avg_engagement_time": "0m:58s",
            "conversions": 196,
            "revenue": 18420.00,
            "top_pages": [
                {"url": "/", "views": 1200, "engagement": "54s"},
                {"url": "/services", "views": 780, "engagement": "48s"},
                {"url": "/pricing", "views": 620, "engagement": "62s"},
            ],
            "top_sources": [
                {"source": "google / organic", "sessions": 1920},
                {"source": "direct / (none)", "sessions": 1430},
                {"source": "google / cpc", "sessions": 540},
            ],
            "conversions_by_event": [
                {"event": "generate_lead", "count": 96},
                {"event": "purchase", "count": 38},
                {"event": "contact_submit", "count": 62},
            ],
        }

    compact = {
        "period": ga_struct.get("period"),
        "kpis": {
            "sessions": ga_struct.get("sessions"),
            "users": ga_struct.get("users"),
            "new_users": ga_struct.get("new_users"),
            "engaged_sessions": ga_struct.get("engaged_sessions"),
            "avg_engagement_time": ga_struct.get("avg_engagement_time"),
            "conversions": ga_struct.get("conversions"),
            "revenue": ga_struct.get("revenue"),
        },
        "top_pages": ga_struct.get("top_pages", [])[:8],
        "top_sources": ga_struct.get("top_sources", [])[:8],
        "conversions_by_event": ga_struct.get("conversions_by_event", [])[:8],
    }

    sys_msg = (
        "You are a senior growth analyst. Write crisp, actionable insights from Google Analytics. "
        "Prefer specificity and next steps. Avoid fluff. Keep it under 120 words per section."
    )
    user_msg = (
        "Given this GA snapshot as JSON, 1) write a 2–3 sentence summary, "
        "2) list 3–5 key insights, and 3) list 3–5 recommended improvements that a marketer can execute this week. "
        "Return strict JSON with keys: summary (string), insights (array of strings), improvements (array of strings).\n\n"
        f"GA_SNAPSHOT:\n{json.dumps(compact)}"
    )

    try:
        client = OpenAI()
        resp = client.chat.completions.create(
            model=os.environ.get("GA_INSIGHTS_MODEL", "gpt-4o-mini"),
            temperature=0.3,
            messages=[
                {"role": "system", "content": sys_msg},
                {"role": "user", "content": user_msg},
            ],
            response_format={"type": "json_object"},
            timeout=30,
        )
        content = resp.choices[0].message.content
        parsed = json.loads(content)
        out = {
            "summary": parsed.get("summary") or "",
            "insights": parsed.get("insights") or [],
            "improvements": parsed.get("improvements") or [],
        }
        return jsonify(out)
    except Exception as e:
        current_app.logger.exception("OpenAI insights failed: %s", e)
        return jsonify({
            "summary": "Traffic and engagement are stable with opportunities to lift conversions via CRO and paid optimization.",
            "insights": [
                "Organic search is the top driver of sessions; paid contributes fewer but higher-intent visits.",
                "Engagement time suggests skimming behavior on key pages.",
                "Lead-oriented events cluster on /pricing and /services."
            ],
            "improvements": [
                "Add prominent ‘Get Quote’ CTA above the fold on top pages.",
                "Shift budget to best-performing source/medium pairs and pause low CTR ad groups.",
                "Publish two high-intent SEO pages targeting pricing + local service modifiers."
            ]
        }), 200

# ---------- GSC routes ----------

@google_bp.get("/gsc/sites.json", endpoint="gsc_sites_json")
@login_required
def gsc_sites_json():
    aid = current_account_id()
    sites = _gsc_list_sites(aid)
    sel = _get_gsc_selected_site(aid)
    return jsonify({"ok": True, "sites": sites, "selected": sel})

@google_bp.route("/gsc/select", methods=["POST", "GET"], endpoint="gsc_select_site")
@login_required
def gsc_select_site():
    aid = current_account_id()
    site = (request.values.get("site_url") or "").strip()
    if not site:
        return jsonify({"ok": False, "error": "Missing site_url"}), 400
    _set_gsc_selected_site(aid, site)
    return jsonify({"ok": True, "site_url": site})

@google_bp.route("/gsc/data", methods=["GET"], endpoint="gsc_data")
@login_required
def gsc_data():
    timeframe = request.args.get("timeframe", "28d")
    start_date, end_date, label = _resolve_timeframe(timeframe)

    aid = current_account_id()
    site_url = _get_gsc_selected_site(aid) or os.getenv("GSC_SITE")

    data = None
    try:
        if site_url:
            data = _fetch_gsc_report(site_url, start_date, end_date)
    except Exception:
        current_app.logger.exception("GSC fetch failed")
        data = None

    if not data:
        # fallback demo payload shaped the way the template/JS expects
        data = {
            "summary": {
                "clicks": 0,
                "impressions": 0,
                "ctr_pct": 0.0,
                "avg_position": 0.0,
            },
            "top_pages": [],
            "top_queries": [],
            "site_url": site_url,
            "period": label,
            "is_demo": True,
        }
    else:
        # normalize/augment real payload
        # if your _fetch_gsc_report already returns this shape, you can skip the mapping
        if "summary" not in data:
            data = {
                "summary": {
                    "clicks": data.get("clicks", 0),
                    "impressions": data.get("impressions", 0),
                    "ctr_pct": data.get("ctr_pct", 0.0),
                    "avg_position": data.get("avg_position", 0.0),
                },
                "top_pages": data.get("top_pages", []),
                "top_queries": data.get("top_queries", []),
            }
        data["site_url"] = site_url
        data["period"] = label
        data["is_demo"] = False

    return jsonify(data), 200

@google_bp.route("/gsc/optimize", methods=["POST"], endpoint="gsc_optimize")
@login_required
def gsc_optimize():
    """
    Stub: queue or compute Search Console optimizations.
    Supports form POST or JSON; returns JSON for XHR or redirects with flash.
    """
    # Optional scope/mode inputs
    if request.is_json:
        scope = (request.json or {}).get("scope", "all")
    else:
        scope = (request.form.get("scope") or "all").strip().lower()

    # TODO: call your job/logic here (e.g., enqueue a task)
    # e.g. optimize_gsc_for_account(current_account_id(), scope=scope)

    msg = f"GSC optimization queued (scope: {scope})."
    # XHR -> JSON
    if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"ok": True, "message": msg})

    # Form POST -> redirect + flash
    flash(msg, "success")
    return redirect(url_for("google_bp.gsc_ui"))

@google_bp.route("/analytics/optimize", methods=["POST"], endpoint="ga_optimize")
@login_required
def ga_optimize():
    """
    Stub: generate AI optimization suggestions for GA data.
    Accepts form POST or JSON. Returns JSON for XHR, else redirect with flash.
    """
    if request.is_json:
        timeframe = (request.json or {}).get("timeframe", "28d")
        scope = (request.json or {}).get("scope", "all")
    else:
        timeframe = request.form.get("timeframe", "28d")
        scope = (request.form.get("scope") or "all").strip().lower()

    # Minimal: reuse ga_data() structure to ensure we have numbers, then pretend we queued work.
    # You might call OpenAI here to produce suggestions (similar to ga_insights()).
    msg = f"GA optimization queued for {timeframe} (scope: {scope})."

    if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"ok": True, "message": msg})

    flash(msg, "success")
    return redirect(url_for("google_bp.ga_ui"))

# ------------------------- Debug: tokens (DB view) -------------------------

@google_bp.get("/debug/tokens")
@login_required
def debug_tokens():
    aid = current_account_id()
    with db.engine.connect() as conn:
        rows = conn.execute(
            text("""
                SELECT * FROM google_oauth_tokens
                 WHERE account_id = :aid
                 ORDER BY updated_at DESC
                 LIMIT 200
            """),
            {"aid": aid},
        ).mappings().all()
    redacted = []
    for r in rows:
        d = dict(r)
        for k in ("access_token","refresh_token","credentials_json"):
            if k in d and d[k]:
                d[k] = "[redacted]"
        redacted.append(d)
    return jsonify({"ok": True, "rows": redacted})

# ------------------------- Debug: Ads (live customers + config) -------------------------

@google_bp.get("/ads/debug/customers")
@login_required
def ads_debug_customers():
    aid = current_account_id()
    with db.engine.connect() as conn:
        row = conn.execute(text("""
            SELECT access_token, refresh_token, credentials_json, id
            FROM google_oauth_tokens
            WHERE account_id=:aid AND product='ads'
            ORDER BY updated_at DESC
            LIMIT 1
        """), {"aid": aid}).mappings().first()

    if not row:
        return jsonify({"ok": False, "error": "No Ads token row"}), 400

    access_token = (row.get("access_token") or "").strip() or None
    refresh_token = (row.get("refresh_token") or "").strip() or None
    if not (access_token or refresh_token) and row.get("credentials_json"):
        try:
            cj = json.loads(row["credentials_json"]) or {}
            access_token = access_token or (cj.get("access_token") or "").strip() or None
            refresh_token = refresh_token or (cj.get("refresh_token") or "").strip() or None
        except Exception:
            pass

    if not (access_token or refresh_token):
        return jsonify({"ok": False, "error": "No access token or refresh token stored. Reconnect Google Ads."}), 400

    dev_token = (
        current_app.config.get("GOOGLE_ADS_DEVELOPER_TOKEN")
        or os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN")
    )
    if not dev_token:
        return jsonify({"ok": False, "error": "GOOGLE_ADS_DEVELOPER_TOKEN not configured"}), 500

    login = (current_app.config.get("GOOGLE_ADS_LOGIN_CUSTOMER_ID") or os.getenv("GOOGLE_ADS_LOGIN_CUSTOMER_ID") or "")
    login = login.replace("-", "").strip()
    VERSIONS = ("v19", "v18")

    def _call_list(access_tok: str):
        base_headers = {
            "developer-token": dev_token,
            "Accept": "application/json",
            "Authorization": f"Bearer {access_tok}",
        }
        if login:
            base_headers["login-customer-id"] = login

        last = None
        for ver in VERSIONS:
            url = f"https://googleads.googleapis.com/{ver}/customers:listAccessibleCustomers"
            r = requests.get(url, headers=base_headers, timeout=20)
            last = r
            if r.status_code == 200:
                names = (r.json().get("resourceNames") or [])
                return {"ok": True, "api_version": ver, "login_customer_id": login or None,
                        "customers": [n.split("/")[1] for n in names if "/" in n]}, 200
            if r.status_code in (401, 403):
                return {"ok": False, "status": r.status_code, "error": r.text}, r.status_code
            if r.status_code == 404:
                continue
            return {"ok": False, "status": r.status_code, "error": r.text}, r.status_code

        return {"ok": False, "status": 404, "error": "Endpoint not found on tried versions: " + ", ".join(VERSIONS)}, 404

    if access_token:
        data, code = _call_list(access_token)
        if code == 200:
            return jsonify(data), 200
        if code != 200 and not refresh_token:
            return jsonify(data), code

    if refresh_token:
        client_id, client_secret = _client_info("ads")
        if not (client_id and client_secret):
            return jsonify({"ok": False, "error": "Ads OAuth client not configured"}), 500

        try:
            resp = requests.post(
                GOOGLE_TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "refresh_token": refresh_token,
                },
                timeout=15,
            )
            if resp.status_code != 200:
                return jsonify({"ok": False, "status": resp.status_code, "error": resp.text}), resp.status_code

            tok = resp.json()
            access_token = tok.get("access_token")

            try:
                exp = None
                if tok.get("expires_in"):
                    exp = datetime.utcnow() + timedelta(seconds=int(tok["expires_in"]))
                with db.engine.begin() as conn:
                    conn.execute(
                        text("""
                            UPDATE google_oauth_tokens t
                            JOIN (
                                SELECT id
                                FROM google_oauth_tokens
                                WHERE account_id=:aid AND product='ads'
                                ORDER BY updated_at DESC
                                LIMIT 1
                            ) last_row ON last_row.id = t.id
                            SET t.access_token=:at,
                                t.token_expiry=:exp,
                                t.updated_at=NOW()
                        """),
                        {"aid": aid, "at": access_token, "exp": exp}
                    )
            except Exception:
                current_app.logger.exception("Failed to persist refreshed Ads access token")

            if access_token:
                data, code = _call_list(access_token)
                return jsonify(data), code

            return jsonify({"ok": False, "error": "Token refresh returned no access_token"}), 500

        except Exception as e:
            current_app.logger.exception("Ads token refresh failed")
            return jsonify({"ok": False, "error": f"Refresh failed: {e}"}), 500

    return jsonify({"ok": False, "error": "Unauthorized and no refresh_token available. Reconnect Google Ads."}), 401


@google_bp.get("/ads/debug/config")
@login_required
def ads_debug_config():
    dev_cfg = current_app.config.get("GOOGLE_ADS_DEVELOPER_TOKEN")
    dev_env = os.environ.get("GOOGLE_ADS_DEVELOPER_TOKEN")
    mgr_cfg = current_app.config.get("GOOGLE_ADS_LOGIN_CUSTOMER_ID")
    mgr_env = os.environ.get("GOOGLE_ADS_LOGIN_CUSTOMER_ID")
    return jsonify({
        "ok": True,
        "config": {"has_dev": bool(dev_cfg), "dev_len": len(dev_cfg or ""), "login_cid": (mgr_cfg or None)},
        "env":    {"has_dev": bool(dev_env), "dev_len": len(dev_env or ""), "login_cid": (mgr_env or None)}
    })

# ------------------------- Google Ads UI -------------------------

@google_bp.route("/ads", methods=["GET"], endpoint="ads_ui")
@login_required
def ads_ui():
    # Redirect to new hierarchical campaigns view
    return redirect(url_for("google_bp.ads_campaigns"))

# ---- New Hierarchical Ads Views ----

@google_bp.route("/ads/campaigns", methods=["GET"], endpoint="ads_campaigns")
@login_required
def ads_campaigns():
    """Level 1: Campaigns list view"""
    aid = current_account_id()
    connected = _is_connected(aid, "ads")
    ai = _ai_enabled()
    ads_data = _get_ads_state(aid)
    return render_template(
        "google/ads_campaigns.html",
        connected=connected,
        ai_connected=ai,
        ads_data=ads_data,
        epn=request.endpoint,
    )

@google_bp.route("/ads/campaign/<campaign_id>", methods=["GET"], endpoint="ads_campaign_detail")
@login_required
def ads_campaign_detail(campaign_id: str):
    """Level 2: Campaign detail with ad groups"""
    aid = current_account_id()
    ads_data = _get_ads_state(aid)

    # Find the campaign
    campaign = next((c for c in ads_data.get("campaigns", []) if c["id"] == campaign_id), None)
    if not campaign:
        flash("Campaign not found.", "error")
        return redirect(url_for("google_bp.ads_campaigns"))

    # Get ad groups for this campaign
    ad_groups = [g for g in ads_data.get("ad_groups", []) if g.get("campaign_id") == campaign_id]

    # Get all ad group IDs for counting keywords
    ad_group_ids = [g["id"] for g in ad_groups]
    keywords = [k for k in ads_data.get("keywords", []) if k.get("ad_group_id") in ad_group_ids]
    ads = [a for a in ads_data.get("ads", []) if a.get("ad_group_id") in ad_group_ids]

    return render_template(
        "google/ads_campaign_detail.html",
        campaign=campaign,
        ad_groups=ad_groups,
        keywords=keywords,
        ads=ads,
        total_keywords=len(keywords),
        epn=request.endpoint,
    )

@google_bp.route("/ads/campaign/<campaign_id>/adgroup/<adgroup_id>", methods=["GET"], endpoint="ads_adgroup_detail")
@login_required
def ads_adgroup_detail(campaign_id: str, adgroup_id: str):
    """Level 3: Ad group detail with tabs (keywords, ads, negatives)"""
    aid = current_account_id()
    ads_data = _get_ads_state(aid)

    # Find the campaign and ad group
    campaign = next((c for c in ads_data.get("campaigns", []) if c["id"] == campaign_id), None)
    ad_group = next((g for g in ads_data.get("ad_groups", []) if g["id"] == adgroup_id), None)

    if not campaign or not ad_group:
        flash("Campaign or ad group not found.", "error")
        return redirect(url_for("google_bp.ads_campaigns"))

    # Get keywords, ads, and negatives for this ad group
    keywords = [k for k in ads_data.get("keywords", []) if k.get("ad_group_id") == adgroup_id]
    ads = [a for a in ads_data.get("ads", []) if a.get("ad_group_id") == adgroup_id]

    # Negatives can be at campaign or ad group level
    negatives = [n for n in ads_data.get("negatives", [])
                 if (n.get("scope") == "Ad Group" and n.get("parent_id") == adgroup_id) or
                    (n.get("scope") == "Campaign" and n.get("parent_id") == campaign_id)]

    return render_template(
        "google/ads_adgroup_detail.html",
        campaign=campaign,
        ad_group=ad_group,
        keywords=keywords,
        ads=ads,
        negatives=negatives,
        epn=request.endpoint,
    )

# ------------------------- GA JSON data (AJAX) -------------------------

@google_bp.route("/analytics/data", methods=["GET"], endpoint="ga_data")
@login_required
def ga_data():
    timeframe = request.args.get("timeframe", "28d")
    start_date, end_date, label = _resolve_timeframe(timeframe)

    aid = current_account_id()
    env_pid_raw = os.getenv("GA_PROPERTY_ID")
    prop_id, prop_name = _get_ga_selected_property(aid)
    effective_prop = prop_id or (_norm_prop_id(env_pid_raw) if env_pid_raw else None)
    connected_name = prop_name or (_ga_property_name_any(env_pid_raw, aid) if env_pid_raw else None) or os.getenv("GA_PROPERTY_LABEL")

    ga = None
    try:
        if effective_prop:
            ga = _fetch_ga_report(effective_prop, start_date, end_date)
            if ga:
                ga["period"] = label
                disp = _ga_property_name_any(effective_prop, aid) or connected_name
                if disp:
                    ga["property_name"] = disp
    except Exception:
        current_app.logger.exception("GA fetch failed")
        ga = None

    if not ga:
        ga = {
            "property_name": "Demo Property (GA4)",  # never mix real name with demo
            "period": label,
            "sessions": 4280,
            "users": 3675,
            "new_users": 3012,
            "engaged_sessions": 2890,
            "avg_engagement_time": "0m:58s",
            "conversions": 196,
            "revenue": 18420.00,
            "top_pages": [
                {"url": "/", "views": 1200, "engagement": "54s"},
                {"url": "/services", "views": 780, "engagement": "48s"},
                {"url": "/pricing", "views": 620, "engagement": "62s"},
            ],
            "top_sources": [
                {"source": "google / organic", "sessions": 1920},
                {"source": "direct / (none)", "sessions": 1430},
                {"source": "google / cpc", "sessions": 540},
            ],
            "conversions_by_event": [
                {"event": "generate_lead", "count": 96},
                {"event": "purchase", "count": 38},
                {"event": "contact_submit", "count": 62},
            ],
            "is_demo": True,
        }
    else:
        ga["is_demo"] = False

    return jsonify(ga), 200
    
@google_bp.get("/analytics/diag.json", endpoint="ga_diag")
@login_required
def ga_diag():
    aid = current_account_id()
    env_pid_raw = os.getenv("GA_PROPERTY_ID")
    prop_id, prop_name = _get_ga_selected_property(aid)
    effective_prop = prop_id or (_norm_prop_id(env_pid_raw) if env_pid_raw else None)

    tok = _get_ga_user_tokens(aid) or {}
    at = tok.get("access_token")
    rt = tok.get("refresh_token")
    issues = []

    if not tok:
        issues.append("No token row for GA in google_oauth_tokens.")
    else:
        if not at:
            issues.append("No access_token present.")
        if not rt:
            issues.append("No refresh_token present (cannot refresh on 401).")

    if not effective_prop:
        issues.append("No GA property selected (and GA_PROPERTY_ID not set).")

    # quick probe (does not use the Data API)
    name = None
    if effective_prop and (at or rt):
        try:
            # try to fetch the property name via Admin API using user token
            name = _admin_property_name_via_user_token(aid, effective_prop)
            if not name:
                issues.append("Admin API name lookup failed with current token (permission or token issue).")
        except Exception as e:
            issues.append(f"Admin API probe raised: {e}")

    return jsonify({
        "ok": len(issues) == 0,
        "account_id": aid,
        "selected_property_id": effective_prop,
        "selected_property_name": prop_name,
        "env_property": env_pid_raw,
        "has_access_token": bool(at),
        "has_refresh_token": bool(rt),
        "admin_name_probe": name,
        "issues": issues
    })


# ------------------------- Ads actions -------------------------

@google_bp.route("/ads/pull-live", methods=["POST"], endpoint="ads_pull_live")
@login_required
def ads_pull_live():
    aid = current_account_id()
    try:
        snapshot = _fetch_ads_snapshot_from_google(aid)
        _save_ads_state(aid, snapshot)
        flash("Pulled latest data from Google Ads.", "success")
    except Exception as e:
        current_app.logger.exception("Pull live Ads failed")
        flash(f"Could not pull live Google Ads data: {e}", "error")
    return redirect(url_for("google_bp.ads_ui"))

@google_bp.post('/ads/refresh.json', endpoint='ads_refresh_json')
@login_required
def ads_refresh_json():
    aid = current_account_id()
    try:
        snapshot = _fetch_ads_snapshot_from_google(aid)
        _save_ads_state(aid, snapshot)
        return jsonify({"ok": True, "message": "Pulled latest data from Google Ads."})
    except Exception as e:
        current_app.logger.exception("ads_refresh_json failed")
        return jsonify({"ok": False, "error": str(e)}), 500

@google_bp.route("/ads/prompt", methods=["POST"], endpoint="ads_prompt_save")
@login_required
def ads_prompt_save():
    aid = current_account_id()
    prompt = (request.form.get("prompt") or "").strip()
    _set_ads_custom_prompt(aid, prompt)
    flash("AI prompt saved for Google Ads.", "success")
    return redirect(url_for("google_bp.ads_ui"))

def _generate_ads_suggestions(aid: int, scope: str = "all", regenerate: bool = False) -> dict:
    """
    Generate AI-powered optimization suggestions for Google Ads account.

    Args:
        aid: Account ID
        scope: Analysis scope (all, campaigns, keywords, etc.)
        regenerate: Force regeneration even if recent insights exist

    Returns:
        Dictionary with summary and categorized recommendations
    """
    from app.services.google_ads_insights import generate_ai_insights, categorize_recommendations

    try:
        # Generate insights using AI service
        insights = generate_ai_insights(aid, scope=scope, regenerate=regenerate)

        # Categorize for easier consumption
        categorized = categorize_recommendations(insights.get("recommendations", []))

        # Store in session for backwards compatibility
        session[f"ads_suggestions_{aid}"] = insights

        return insights

    except Exception as e:
        current_app.logger.error(f"Failed to generate AI suggestions: {e}", exc_info=True)

        # Fallback to basic suggestions
        fallback = {
            "summary": "AI insights are temporarily unavailable. Please try again later.",
            "recommendations": [],
            "error": str(e)
        }
        session[f"ads_suggestions_{aid}"] = fallback
        return fallback

@google_bp.route("/ads/optimize.json", methods=["POST", "GET"], endpoint="ads_optimize_json")
@login_required
def ads_optimize_json():
    aid = current_account_id()
    if request.is_json:
        scope = (request.json or {}).get("scope", "all")
        regenerate = bool((request.json or {}).get("regenerate", False))
    else:
        scope = request.args.get("scope", "all")
        regenerate = (request.args.get("regenerate") == "true")
    sugs = _generate_ads_suggestions(aid, scope=str(scope).lower(), regenerate=bool(regenerate))
    return jsonify({"ok": True, "scope": scope, "suggestions": sugs})

@google_bp.route("/ads/optimize", methods=["POST", "GET"], endpoint="ads_optimize")
@login_required
def ads_optimize():
    aid = current_account_id()
    if request.method == "GET":
        return redirect(url_for("google_bp.ads_ui"))
    scope = (request.form.get("scope") or "all").strip().lower()
    regen_flag = request.form.get("regenerate") or request.form.get("refresh") or ""
    regenerate = str(regen_flag).lower() in ("1", "true", "yes", "on")
    _generate_ads_suggestions(aid, scope=scope, regenerate=regenerate)
    flash("Optimization suggestions generated.", "success")
    return redirect(url_for("google_bp.ads_ui"))

@google_bp.route("/ads/update", methods=["POST", "GET"], endpoint="ads_update")
@login_required
def ads_update():
    aid = current_account_id()
    if request.method == "GET":
        return redirect(url_for("google_bp.ads_ui"))

    state = _get_ads_state(aid)
    form = request.form

    def _collect(prefix):
        items = {}
        for k, v in form.items():
            if not k.startswith(prefix + "["):
                continue
            try:
                left = k.split("[", 1)[1]
                idx = int(left.split("]", 1)[0])
            except Exception:
                continue
            field = k.split("][")[-1].rstrip("]")
            items.setdefault(idx, {})[field] = v
        return [items[i] for i in sorted(items.keys())]

    if any(s in form for s in ("campaigns[0][name]", "campaigns[0][id]")):
        new_list = _collect("campaigns")
        for c in new_list:
            if "daily_budget" in c and c["daily_budget"] not in (None, ""):
                try: c["daily_budget"] = float(c["daily_budget"])
                except Exception: pass
            if "target" in c and c["target"] not in (None, ""):
                try: c["target"] = float(c["target"])
                except Exception: pass
        state["campaigns"] = new_list

    if any(s in form for s in ("ad_groups[0][name]", "ad_groups[0][id]")):
        state["ad_groups"] = _collect("ad_groups")

    if any(s in form for s in ("keywords[0][text]", "keywords[0][id]")):
        kws = _collect("keywords")
        for k in kws:
            for fld in ("cpc", "cpa"):
                if fld in k and k[fld] not in (None, ""):
                    try: k[fld] = float(k[fld])
                    except Exception: pass
            if "conv" in k and k["conv"] not in (None, ""):
                try: k["conv"] = int(k["conv"])
                except Exception: pass
        state["keywords"] = kws

    if any(s in form for s in ("negatives[0][text]", "negatives[0][id]")):
        state["negatives"] = _collect("negatives")

    if any(s in form for s in ("ads[0][h1]", "ads[0][id]")):
        state["ads"] = _collect("ads")

    if any(s in form for s in ("extensions[0][text]", "extensions[0][id]")):
        state["extensions"] = _collect("extensions")

    if any(s in form for s in ("landing_pages[0][url]", "landing_pages[0][id]")):
        lps = _collect("landing_pages")
        for lp in lps:
            if "mobile_friendly" in lp:
                mv = lp["mobile_friendly"]
                lp["mobile_friendly"] = (str(mv).lower() in ("true", "1", "yes", "on"))
        state["landing_pages"] = lps

    _save_ads_state(aid, state)
    flash("Google Ads changes saved.", "success")
    return redirect(url_for("google_bp.ads_ui"))

@google_bp.route("/ads/apply-recommendation", methods=["POST"], endpoint="ads_apply_recommendation")
@login_required
def ads_apply_recommendation():
    """Apply a single AI recommendation."""
    from app.services.google_ads_insights import apply_recommendation
    from flask_login import current_user

    data = request.get_json() if request.is_json else request.form
    recommendation_id = data.get("recommendation_id")

    if not recommendation_id:
        return jsonify({"ok": False, "error": "Missing recommendation_id"}), 400

    try:
        recommendation_id = int(recommendation_id)
    except:
        return jsonify({"ok": False, "error": "Invalid recommendation_id"}), 400

    success, message = apply_recommendation(recommendation_id, current_user.id)

    if success:
        return jsonify({"ok": True, "message": message})
    else:
        return jsonify({"ok": False, "error": message}), 400


@google_bp.route("/ads/dismiss-recommendation", methods=["POST"], endpoint="ads_dismiss_recommendation")
@login_required
def ads_dismiss_recommendation():
    """Dismiss a recommendation."""
    from app.services.google_ads_insights import dismiss_recommendation

    data = request.get_json() if request.is_json else request.form
    recommendation_id = data.get("recommendation_id")
    reason = data.get("reason", "")

    if not recommendation_id:
        return jsonify({"ok": False, "error": "Missing recommendation_id"}), 400

    try:
        recommendation_id = int(recommendation_id)
    except:
        return jsonify({"ok": False, "error": "Invalid recommendation_id"}), 400

    success, message = dismiss_recommendation(recommendation_id, reason)

    if success:
        return jsonify({"ok": True, "message": message})
    else:
        return jsonify({"ok": False, "error": message}), 400


@google_bp.route("/ads/apply-suggestions", methods=["POST", "GET"], endpoint="ads_apply_suggestions")
@login_required
def ads_apply_suggestions():
    """Legacy route for applying multiple suggestions."""
    if request.method == "GET":
        flash("No suggestions selected.", "info")
        return redirect(url_for("google_bp.ads_ui"))
    flash("Suggestions applied (demo).", "success")
    return redirect(url_for("google_bp.ads_ui"))

@google_bp.route("/ads/start", methods=["GET"], endpoint="ads_start")
@login_required
def ads_start():
    session["google_oauth_product"] = "ads"
    nxt = request.args.get("next")
    url = url_for("google_bp.start", product="ads")
    if nxt:
        url = f"{url}?{urlencode({'next': nxt})}"
    return redirect(url)

# ------------------------- GA UI -------------------------

@google_bp.get("/analytics/properties.json", endpoint="ga_properties_json")
@login_required
def ga_properties_json():
    aid = current_account_id()
    props = _admin_list_properties_via_user_token(aid)
    out = [{"id": p.get("property"), "name": p.get("displayName")} for p in (props or []) if p.get("property")]
    env_pid = os.getenv("GA_PROPERTY_ID")
    if not out and env_pid:
        out = [{
            "id": f"properties/{env_pid.split('/')[-1]}",
            "name": os.getenv("GA_PROPERTY_LABEL") or env_pid
        }]
    return jsonify({"ok": True, "properties": out})

@google_bp.route("/analytics/select", methods=["POST", "GET"], endpoint="ga_select_property")
@login_required
def ga_select_property():
    aid = current_account_id()
    if request.method == "POST":
        pid_raw = (request.form.get("property_id") or "").strip()
        pname = (request.form.get("property_name") or "").strip() or None
    else:
        pid_raw = (request.args.get("property_id") or "").strip()
        pname = (request.args.get("property_name") or "").strip() or None

    if not pid_raw:
        return jsonify({"ok": False, "error": "Missing property_id"}), 400

    pid_norm = _norm_prop_id(pid_raw)
    if not pid_norm:
        return jsonify({"ok": False, "error": "Invalid property_id"}), 400

    name = pname or _ga_property_name_any(pid_norm, aid)
    _set_ga_selected_property(aid, pid_norm, name)
    return jsonify({"ok": True, "property_id": pid_norm, "property_name": name})

@google_bp.route("/analytics", methods=["GET"], endpoint="ga_ui")
@login_required
def ga_ui():
    aid = current_account_id()
    connected = _is_connected(aid, "ga")
    ai_ok = _ai_enabled()

    if connected:
        pid, _ = _get_ga_selected_property(aid)
        if not pid:
            try:
                _ensure_default_ga_property_selected(aid)
            except Exception:
                current_app.logger.exception("Auto-select GA property on UI load failed")

    prop_id, prop_name = (None, None)
    if connected:
        pid, pname = _get_ga_selected_property(aid)
        prop_id = pid
        prop_name = pname or (os.getenv("GA_PROPERTY_LABEL") or None)
    connected_name = prop_name

    ga_sample = {
        "property_name": "Demo Property (GA4)",
        "period": "Last 28 days",
        "sessions": 4280,
        "users": 3675,
        "new_users": 3012,
        "engaged_sessions": 2890,
        "avg_engagement_time": "0m:58s",
        "conversions": 196,
        "revenue": 18420.00,
        "top_pages": [
            {"path": "/emergency-plumbing", "sessions": 980, "conv_rate": 5.8},
            {"path": "/water-heater-install", "sessions": 760, "conv_rate": 4.2},
            {"path": "/drain-cleaning", "sessions": 420, "conv_rate": 3.9},
            {"path": "/pricing", "sessions": 315, "conv_rate": 6.1},
        ],
        "top_channels": [
            {"channel": "Organic Search", "sessions": 2050, "conv": 86},
            {"channel": "Paid Search", "sessions": 920, "conv": 74},
            {"channel": "Direct", "sessions": 610, "conv": 19},
            {"channel": "Referral", "sessions": 330, "conv": 10},
        ],
    }

    ga_initial = None if connected else ga_sample

    ga_ai = {
        "source": "FieldSprout AI" if ai_ok else "sample",
        "summary": "Click Generate Insights to analyze the selected timeframe."
        if ai_ok else "Traffic is stable (+6% WoW).",
        "insights": [] if ai_ok else [
            "Organic Search contributes the largest share of sessions.",
            "Paid Search shows strong conversion density on emergency-intent pages.",
        ],
        "improvements": [] if ai_ok else [
            "Shift 10–15% budget to emergency/near-me terms during peak hours.",
            "Add internal links from blog to service pages to capture organic momentum.",
        ],
    }

    if request.args.get("json") == "1":
        with current_app.test_request_context(
            query_string={"timeframe": request.args.get("timeframe", "28d")}
        ):
            return ga_data()

    selected_property = prop_id
    return render_template(
        "google/ga.html",
        connected_ga=connected,
        connected_ga_name=connected_name,
        ai_enabled=ai_ok,
        ga=ga_initial,
        ga_ai=ga_ai,
        epn=request.endpoint,
        ga_property_label=os.getenv("GA_PROPERTY_LABEL"),
        ga_selected_id=prop_id,
        app=current_app,
    )

# ------------------------- GSC / GMB stubs -------------------------


def _has_gsc_connection(user) -> bool:
    try:
        # If you have a credentials model, prefer that:
        # from app.models import GscCredential
        # return bool(GscCredential.query.filter_by(user_id=user.id, valid=True).first())
        return bool(
            getattr(user, "gsc_connected", False)
            and getattr(user, "gsc_property_id", None)
        )
    except Exception:
        return False

# --------- CONNECT ----------

# ---------- OAuth helpers (GSC) ----------

def _gsc_scopes():
    # Read from config if present; fallback to read-only scope
    scopes = current_app.config.get("GOOGLE_OAUTH_SCOPES")
    if scopes:
        return list(scopes)
    return ["https://www.googleapis.com/auth/webmasters.readonly"]

def _gsc_client_config():
    """
    Return the Google client config dict expected by google_auth_oauthlib.flow.Flow.
    You can load from an env var JSON or a file path; adapt as needed.
    """
    # 1) JSON content in env (preferred in many deployments)
    env_json = os.getenv("GOOGLE_OAUTH_CLIENT_JSON")
    if env_json:
        try:
            return json.loads(env_json)
        except Exception:
            pass

    # 2) File path in env
    cfg_path = os.getenv("GOOGLE_OAUTH_CLIENT_FILE")
    if cfg_path and os.path.exists(cfg_path):
        with open(cfg_path, "r", encoding="utf-8") as f:
            return json.load(f)

    # 3) LAST RESORT: read from Flask config (if you store it there)
    cfg = current_app.config.get("GOOGLE_OAUTH_CLIENT_CONFIG")
    if cfg:
        return cfg

    raise RuntimeError("Google OAuth client config not found. Set GOOGLE_OAUTH_CLIENT_JSON or GOOGLE_OAUTH_CLIENT_FILE.")

def build_gsc_auth_url(*, redirect_uri: str) -> str:
    """
    Build the Google OAuth consent URL for Search Console, store state in session.
    """
    # Lazy import so the module imports even if libs aren’t installed yet
    from google_auth_oauthlib.flow import Flow

    client_config = _gsc_client_config()
    scopes = _gsc_scopes()

    flow = Flow.from_client_config(client_config=client_config, scopes=scopes, redirect_uri=redirect_uri)
    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent"  # ensures we can get/refresh a refresh_token on first grant
    )
    session["oauth_state_gsc"] = state
    return auth_url

def _exchange_code_for_creds(redirect_uri: str):
    from google_auth_oauthlib.flow import Flow

    client_config = _gsc_client_config()
    scopes = _gsc_scopes()

    state = session.get("oauth_state_gsc")
    flow = Flow.from_client_config(client_config=client_config, scopes=scopes, state=state, redirect_uri=redirect_uri)
    flow.fetch_token(authorization_response=request.url)
    return flow.credentials

# Optional: build a Search Console service client (if you need to call the API here)
def _build_gsc_service(creds):
    from googleapiclient.discovery import build
    # API is “searchconsole” (new name). If your libs are older, “webmasters” also works.
    return build("searchconsole", "v1", credentials=creds, cache_discovery=False)

# ---------- Routes ----------

@google_bp.route("/gsc/connect")
def connect_gsc():
    """
    Starts the OAuth flow and redirects to Google consent.
    """
    redirect_uri = url_for("google_bp.gsc_callback", _external=True)
    auth_url = build_gsc_auth_url(redirect_uri=redirect_uri)  # <- this was missing
    return redirect(auth_url)

@google_bp.route("/gsc/callback")
def gsc_callback():
    """
    Handles Google's redirect back to us. Exchanges code for tokens, stores flags,
    and sends the user to the GSC UI page.
    """
    try:
        redirect_uri = url_for("google_bp.gsc_callback", _external=True)
        creds = _exchange_code_for_creds(redirect_uri)   # must exist

        # Optional: pick a property/site to save for display
        site_url = ""
        try:
            svc = _build_gsc_service(creds)              # must exist
            sites = (svc.sites().list().execute() or {})
            for s in (sites.get("siteEntry") or []):
                if s.get("permissionLevel") in (
                    "siteOwner", "siteFullUser", "siteRestrictedUser"
                ):
                    site_url = s.get("siteUrl") or ""
                    break
        except Exception:
            # If listing sites fails, we still consider the account "connected"
            current_app.logger.info("GSC list sites failed; proceeding as connected", exc_info=True)

        # --- Always mirror state into the session so the UI updates instantly ---
        session["gsc_connected"] = True
        if site_url:
            session["gsc_site_url"] = site_url
            session["gsc_property_id"] = site_url  # if you store property_id == site_url

        # --- Persist on the user, if authenticated (nice-to-have, not required for UI) ---
        if getattr(current_user, "is_authenticated", False):
            try:
                setattr(current_user, "gsc_connected", True)
                if site_url:
                    setattr(current_user, "gsc_site_url", site_url)
                    setattr(current_user, "gsc_property_id", site_url)
                db.session.commit()
            except Exception:
                db.session.rollback()
                current_app.logger.exception("Failed to persist GSC flags on user")
        else:
            flash("Connected to Google. Please sign in again to finalize linking.", "warning")

        flash("Google Search Console connected.", "success")
        return redirect(url_for("google_bp.gsc_ui"))

    except Exception as e:
        current_app.logger.exception("GSC OAuth callback failed: %s", e)
        flash("Could not complete Search Console connection. Please try again.", "error")
        return redirect(url_for("google_bp.gsc_ui"))


@google_bp.route("/gsc")
def gsc_ui():
    # Connection flag: session OR user model
    connected = bool(session.get("gsc_connected"))
    try:
        connected = connected or bool(getattr(current_user, "gsc_connected", False))
    except Exception:
        pass

    # Property/Site values (session first, then user model)
    site_url = session.get("gsc_site_url") or getattr(current_user, "gsc_site_url", None)
    property_id = session.get("gsc_property_id") or getattr(current_user, "gsc_property_id", None)

    gsc = {}

    if connected:
        # TODO: replace with your real fetchers
        # summary_raw = fetch_gsc_summary(property_id, start, end)
        # top_queries_raw = fetch_gsc_queries(property_id, start, end)
        # top_pages_raw = fetch_gsc_pages(property_id, start, end)

        # For now: minimal structure so template renders the “real” block
        gsc = {
            "property": site_url or property_id or "Search Console property",
            "site_url": site_url,
            "period": "Last 28 days",
            "clicks": 0,
            "impressions": 0,
            "ctr_pct": 0.0,
            "avg_position": 0.0,
            "top_queries": [],
            "top_pages": [],
        }

    # Only call AI when we actually have real numbers
        has_real = (gsc.get("clicks", 0) or 0) > 0 or (gsc.get("impressions", 0) or 0) > 0
        insights = get_gsc_insights(gsc) if has_real else ""
    else:
        insights = ""  # keep empty on demo

    return render_template(
        "google/gsc.html",
        gsc=gsc,
        connected_gsc=connected,
        insights=insights,   # <— NEW
        epn=request.endpoint
    )

@google_bp.route("/analytics/old", methods=["GET"], endpoint="ga_ui_old")
@login_required
def ga_ui_old():
    return redirect(url_for("google_bp.ga_ui"))

@google_bp.route("/ga", methods=["GET"], endpoint="ga_alias")
@login_required
def ga_alias():
    return redirect(url_for("google_bp.ga_ui"))

# ------------------------- Ads CRUD stubs -------------------------

def _ads_not_implemented():
    flash("Google Ads actions are not implemented yet.", "info")
    return redirect(url_for("google_bp.ads_ui"))

@google_bp.route("/ads/pick-account", methods=["GET", "POST"], endpoint="ads_pick_account")
@login_required
def ads_pick_account():
    ids = session.get("ads_accessible_ids") or []
    if request.method == "POST":
        picked = (request.form.get("customer_id") or "").strip()
        if not picked:
            flash("Please pick an account.", "error")
        else:
            save_customer_id(current_account_id(), picked)
            session.pop("ads_accessible_ids", None)
            flash("Google Ads account saved.", "success")
            return redirect(url_for("google_bp.ads_ui"))
    return render_template("google/ads_account_pick.html", ids=ids)

@google_bp.route("/ads/campaign/create", methods=["POST"], endpoint="ads_campaign_create")
@login_required
def ads_campaign_create():
    """Create a new campaign"""
    aid = current_account_id()
    ads_data = _get_ads_state(aid)

    # Generate new campaign ID
    existing_ids = [int(c["id"].split("-")[1]) for c in ads_data.get("campaigns", []) if "-" in c["id"]]
    new_id = f"C-{max(existing_ids) + 1 if existing_ids else 1001}"

    new_campaign = {
        "id": new_id,
        "name": request.form.get("name", "New Campaign"),
        "type": request.form.get("type", "SEARCH"),
        "status": request.form.get("status", "Paused"),
        "daily_budget": float(request.form.get("daily_budget", 50)),
        "bidding": request.form.get("bidding", "Manual CPC"),
        "target": float(request.form.get("target")) if request.form.get("target") else None
    }

    ads_data.setdefault("campaigns", []).append(new_campaign)
    _save_ads_state(aid, ads_data)
    flash(f"Campaign '{new_campaign['name']}' created successfully.", "success")
    return redirect(url_for("google_bp.ads_campaigns"))

@google_bp.route("/ads/campaign/update", methods=["POST"], endpoint="ads_campaign_update")
@login_required
def ads_campaign_update():
    """Update an existing campaign"""
    aid = current_account_id()
    ads_data = _get_ads_state(aid)
    campaign_id = request.form.get("id")

    campaign = next((c for c in ads_data.get("campaigns", []) if c["id"] == campaign_id), None)
    if not campaign:
        flash("Campaign not found.", "error")
        return redirect(url_for("google_bp.ads_campaigns"))

    campaign["name"] = request.form.get("name", campaign["name"])
    campaign["type"] = request.form.get("type", campaign["type"])
    campaign["status"] = request.form.get("status", campaign["status"])
    campaign["daily_budget"] = float(request.form.get("daily_budget", campaign.get("daily_budget", 50)))
    campaign["bidding"] = request.form.get("bidding", campaign["bidding"])
    campaign["target"] = float(request.form.get("target")) if request.form.get("target") else None

    _save_ads_state(aid, ads_data)
    flash(f"Campaign '{campaign['name']}' updated successfully.", "success")
    return redirect(url_for("google_bp.ads_campaign_detail", campaign_id=campaign_id))

@google_bp.route("/ads/campaign/delete", methods=["POST"], endpoint="ads_campaign_delete")
@login_required
def ads_campaign_delete():
    """Delete a campaign and all its ad groups, keywords, and ads"""
    aid = current_account_id()
    ads_data = _get_ads_state(aid)
    campaign_id = request.form.get("id")

    # Find and remove campaign
    campaigns = ads_data.get("campaigns", [])
    campaign = next((c for c in campaigns if c["id"] == campaign_id), None)

    if not campaign:
        flash("Campaign not found.", "error")
        return redirect(url_for("google_bp.ads_campaigns"))

    # Remove campaign
    ads_data["campaigns"] = [c for c in campaigns if c["id"] != campaign_id]

    # Remove all ad groups in this campaign
    ad_group_ids = [g["id"] for g in ads_data.get("ad_groups", []) if g.get("campaign_id") == campaign_id]
    ads_data["ad_groups"] = [g for g in ads_data.get("ad_groups", []) if g.get("campaign_id") != campaign_id]

    # Remove all keywords in those ad groups
    ads_data["keywords"] = [k for k in ads_data.get("keywords", []) if k.get("ad_group_id") not in ad_group_ids]

    # Remove all ads in those ad groups
    ads_data["ads"] = [a for a in ads_data.get("ads", []) if a.get("ad_group_id") not in ad_group_ids]

    # Remove campaign-level negatives
    ads_data["negatives"] = [n for n in ads_data.get("negatives", [])
                              if not (n.get("scope") == "Campaign" and n.get("parent_id") == campaign_id)]

    _save_ads_state(aid, ads_data)
    flash(f"Campaign '{campaign['name']}' and all its ad groups deleted.", "success")
    return redirect(url_for("google_bp.ads_campaigns"))

@google_bp.route("/ads/adgroup/create", methods=["POST"], endpoint="ads_adgroup_create")
@login_required
def ads_adgroup_create():
    """Create a new ad group"""
    aid = current_account_id()
    ads_data = _get_ads_state(aid)
    campaign_id = request.form.get("campaign_id")

    # Generate new ad group ID
    existing_ids = [int(g["id"].split("-")[1]) for g in ads_data.get("ad_groups", []) if "-" in g["id"]]
    new_id = f"AG-{max(existing_ids) + 1 if existing_ids else 2001}"

    new_ad_group = {
        "id": new_id,
        "campaign_id": campaign_id,
        "name": request.form.get("name", "New Ad Group"),
        "status": request.form.get("status", "Enabled")
    }

    ads_data.setdefault("ad_groups", []).append(new_ad_group)
    _save_ads_state(aid, ads_data)
    flash(f"Ad group '{new_ad_group['name']}' created successfully.", "success")
    return redirect(url_for("google_bp.ads_campaign_detail", campaign_id=campaign_id))

@google_bp.route("/ads/adgroup/update", methods=["POST"], endpoint="ads_adgroup_update")
@login_required
def ads_adgroup_update():
    """Update an existing ad group"""
    aid = current_account_id()
    ads_data = _get_ads_state(aid)
    adgroup_id = request.form.get("id")
    campaign_id = request.form.get("campaign_id")

    ad_group = next((g for g in ads_data.get("ad_groups", []) if g["id"] == adgroup_id), None)
    if not ad_group:
        flash("Ad group not found.", "error")
        return redirect(url_for("google_bp.ads_campaign_detail", campaign_id=campaign_id))

    ad_group["name"] = request.form.get("name", ad_group["name"])
    ad_group["status"] = request.form.get("status", ad_group["status"])

    _save_ads_state(aid, ads_data)
    flash(f"Ad group '{ad_group['name']}' updated successfully.", "success")
    return redirect(url_for("google_bp.ads_campaign_detail", campaign_id=campaign_id))

@google_bp.route("/ads/adgroup/delete", methods=["POST"], endpoint="ads_adgroup_delete")
@login_required
def ads_adgroup_delete():
    """Delete an ad group and all its keywords and ads"""
    aid = current_account_id()
    ads_data = _get_ads_state(aid)
    adgroup_id = request.form.get("id")
    campaign_id = request.form.get("campaign_id")

    # Find and remove ad group
    ad_groups = ads_data.get("ad_groups", [])
    ad_group = next((g for g in ad_groups if g["id"] == adgroup_id), None)

    if not ad_group:
        flash("Ad group not found.", "error")
        return redirect(url_for("google_bp.ads_campaign_detail", campaign_id=campaign_id))

    # Remove ad group
    ads_data["ad_groups"] = [g for g in ad_groups if g["id"] != adgroup_id]

    # Remove all keywords in this ad group
    ads_data["keywords"] = [k for k in ads_data.get("keywords", []) if k.get("ad_group_id") != adgroup_id]

    # Remove all ads in this ad group
    ads_data["ads"] = [a for a in ads_data.get("ads", []) if a.get("ad_group_id") != adgroup_id]

    # Remove ad group-level negatives
    ads_data["negatives"] = [n for n in ads_data.get("negatives", [])
                              if not (n.get("scope") == "Ad Group" and n.get("parent_id") == adgroup_id)]

    _save_ads_state(aid, ads_data)
    flash(f"Ad group '{ad_group['name']}' and all its keywords/ads deleted.", "success")
    return redirect(url_for("google_bp.ads_campaign_detail", campaign_id=campaign_id))

@google_bp.route("/ads/ad/new/<int:gid>", methods=["POST"], endpoint="ads_ad_new")
@login_required
def ads_ad_new(gid: int):
    return _ads_not_implemented()

@google_bp.route("/ads/ad/<int:aid_>/edit", methods=["POST"], endpoint="ads_ad_edit")
@login_required
def ads_ad_edit(aid_: int):
    return _ads_not_implemented()

@google_bp.route("/ads/ad/<int:aid_>/delete", methods=["POST"], endpoint="ads_ad_delete")
@login_required
def ads_ad_delete(aid_: int):
    return _ads_not_implemented()

@google_bp.route("/ads/keyword/new/<int:gid>", methods=["POST"], endpoint="ads_keyword_new")
@login_required
def ads_keyword_new(gid: int):
    return _ads_not_implemented()

@google_bp.route("/ads/keyword/<int:kid>/edit", methods=["POST"], endpoint="ads_keyword_edit")
@login_required
def ads_keyword_edit(kid: int):
    return _ads_not_implemented()

@google_bp.route("/ads/keyword/<int:kid>/delete", methods=["POST"], endpoint="ads_keyword_delete")
@login_required
def ads_keyword_delete(kid: int):
    return _ads_not_implemented()

# ------------------------- Connect shortlinks -------------------------

@google_bp.route("/connect/ga", methods=["GET"], endpoint="connect_ga")
@login_required
def connect_ga():
    session["google_oauth_product"] = "ga"
    return redirect(url_for("google_bp.start", product="ga"))

@google_bp.route("/connect/ads", methods=["GET"], endpoint="connect_ads")
@login_required
def connect_ads():
    session["google_oauth_product"] = "ads"
    nxt = request.args.get("next")
    url = url_for("google_bp.start", product="ads")
    if nxt:
        url = f"{url}?{urlencode({'next': nxt})}"
    return redirect(url)

@google_bp.route("/connect/gmb", methods=["GET"], endpoint="connect_gmb")
@login_required
def connect_gmb():
    session["google_oauth_product"] = "gmb"
    return redirect(url_for("google_bp.start", product="gmb"))

@google_bp.route("/connect/lsa", methods=["GET"], endpoint="connect_lsa")
@login_required
def connect_lsa():
    session["google_oauth_product"] = "lsa"
    nxt = request.args.get("next") or url_for("glsa_bp.leads_page")
    url = url_for("google_bp.start", product="lsa")
    if nxt:
        url = f"{url}?{urlencode({'next': nxt})}"
    return redirect(url)

@google_bp.route("/connect/ads/oauth", methods=["GET"], endpoint="connect_ads_oauth")
@login_required
def connect_ads_oauth():
    session["google_oauth_product"] = "ads"
    return redirect(url_for("google_bp.start", product="ads"))

@google_bp.route("/connect/ga/oauth", methods=["GET"], endpoint="connect_ga_oauth")
@login_required
def connect_ga_oauth():
    session["google_oauth_product"] = "ga"
    return redirect(url_for("google_bp.start", product="ga"))

@google_bp.route("/connect/gsc/oauth", methods=["GET"], endpoint="connect_gsc_oauth")
@login_required
def connect_gsc_oauth():
    session["google_oauth_product"] = "gsc"
    return redirect(url_for("google_bp.start", product="gsc"))

@google_bp.route("/connect/analytics", methods=["GET"], endpoint="connect_analytics")
@login_required
def connect_analytics():
    session["google_oauth_product"] = "ga"
    return redirect(url_for("google_bp.start", product="ga"))

@google_bp.route("/connect/analytics/oauth", methods=["GET"], endpoint="connect_analytics_oauth")
@login_required
def connect_analytics_oauth():
    session["google_oauth_product"] = "ga"
    return redirect(url_for("google_bp.start", product="ga"))

@google_bp.route("/connect/search-console", methods=["GET"], endpoint="connect_search_console")
@login_required
def connect_search_console():
    session["google_oauth_product"] = "gsc"
    return redirect(url_for("google_bp.start", product="gsc"))

@google_bp.route("/connect/search-console/oauth", methods=["GET"], endpoint="connect_search_console_oauth")
@login_required
def connect_search_console_oauth():
    session["google_oauth_product"] = "gsc"
    return redirect(url_for("google_bp.start", product="gsc"))

@google_bp.route("/connect/<product>", methods=["GET"], endpoint="connect")
@login_required
def connect(product: str):
    canon = _normalize_product(product or "")
    if not canon:
        flash("Unknown Google product.", "error")
        return redirect(url_for("google_bp.index"))
    session["google_oauth_product"] = canon
    return redirect(url_for("google_bp.start", product=canon))

# ------------------------- OAuth flow -------------------------

def _infer_product_if_missing() -> str | None:
    state = request.args.get("state")
    p = _normalize_product(state) if state else None
    if p:
        return p
    ref = request.referrer
    if ref:
        try:
            qs = parse_qs(urlparse(ref).query)
            for key in ("product", "state", "p"):
                if key in qs and qs[key]:
                    p2 = _normalize_product(qs[key][0])
                    if p2:
                        return p2
        except Exception:
            pass
    return None

@google_bp.route("/start", methods=["GET"], endpoint="start")
@login_required
def start():
    raw = (
        request.args.get("product")
        or request.args.get("state")
        or session.get("google_oauth_product")
        or ""
    )
    product = _normalize_product(raw) or _infer_product_if_missing()
    if product not in SCOPES:
        current_app.logger.warning(
            "Unknown Google product at /start; raw='%s' args=%s session.product=%s",
            raw, dict(request.args), session.get("google_oauth_product")
        )
        flash("Unknown Google product.", "error")
        return redirect(url_for("google_bp.index"))

    nxt = request.args.get("next")
    if nxt:
        session["google_oauth_next"] = nxt

    client_id, client_secret = _client_info(product)
    if not client_id or not client_secret:
        flash(f"Google OAuth is not configured for {product.upper()} (missing client ID/secret).", "error")
        return redirect(url_for("google_bp.index"))

    session["google_oauth_product"] = product

    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": _redirect_uri(),
        "scope": " ".join(SCOPES[product]),
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": product,
    }
    return redirect(f"{GOOGLE_AUTH_URL}?{urlencode(params)}")

@google_bp.route("/callback", methods=["GET"], endpoint="oauth_callback")
@login_required
def oauth_callback():
    err = request.args.get("error")
    if err:
        flash(f"Google authorization failed: {err}", "error")
        return redirect(url_for("google_bp.index"))

    code = request.args.get("code")
    product = _normalize_product(request.args.get("state") or session.get("google_oauth_product") or "")
    if not code or product not in SCOPES:
        flash("Invalid Google callback.", "error")
        return redirect(url_for("google_bp.index"))

    client_id, client_secret = _client_info(product)
    if not client_id or not client_secret:
        flash(f"Google OAuth not configured for {product.upper()}.", "error")
        return redirect(url_for("google_bp.index"))

    data = {
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": _redirect_uri(),
        "grant_type": "authorization_code",
    }

    try:
        resp = requests.post(GOOGLE_TOKEN_URL, data=data, timeout=10)
        resp.raise_for_status()
        token_json = resp.json()
    except Exception as e:
        current_app.logger.exception("Google token exchange failed")
        flash(f"Could not complete Google sign-in: {e}", "error")
        return redirect(url_for("google_bp.index"))

    aid = current_account_id()
    _store_tokens(aid, product, token_json)

    if product == "ga":
        try:
            _ensure_default_ga_property_selected(aid)
        except Exception:
            current_app.logger.exception("Could not auto-select GA property after OAuth")

    if product in ("ads", "lsa"):
        try:
            at = token_json.get("access_token")
            access_token = at.strip() if isinstance(at, str) else at
            ids = pick_and_save_customer_id_after_oauth(aid, access_token) if access_token else []
            if len(ids) == 0:
                flash("No Google Ads accounts found for this Google login. Ensure you have admin access.", "warning")
            elif len(ids) > 1:
                session["ads_accessible_ids"] = ids
                flash("Pick the Google Ads account you want to manage.", "info")
                return redirect(url_for("google_bp.ads_pick_account"))
        except Exception:
            current_app.logger.exception("Listing accessible Ads customers failed")

    flash(f"Connected Google {product.upper()} successfully.", "success")

    nxt = session.pop("google_oauth_next", None)
    if nxt:
        return redirect(nxt)

    if product == "gmb":
        return redirect(url_for("gmb_bp.index"))
    if product == "lsa":
        return redirect(url_for("glsa_bp.leads_page"))
    if product == "ads":
        return redirect(url_for("google_bp.ads_ui"))
    if product == "ga":
        return redirect(url_for("google_bp.ga_ui"))
    if product == "gsc":
        return redirect(url_for("google_bp.gsc_ui"))
    return redirect(url_for("google_bp.index"))

# ========================== GA Insights Routes ==========================

@google_bp.route("/ga/insights.json", methods=["POST"], endpoint="ga_insights_json")
@login_required
def ga_insights_json():
    """Generate AI insights for Google Analytics property."""
    from app.services.ga_insights import generate_ga_insights

    aid = current_account_id()
    data = request.get_json() if request.is_json else {}
    property_id = data.get("property_id", "")
    regenerate = bool(data.get("regenerate", False))

    if not property_id:
        return jsonify({"ok": False, "error": "Missing property_id"}), 400

    try:
        insights = generate_ga_insights(aid, property_id, regenerate=regenerate)
        return jsonify({"ok": True, **insights})
    except Exception as e:
        current_app.logger.error(f"Error generating GA insights: {e}", exc_info=True)
        return jsonify({"ok": False, "error": str(e)}), 500


@google_bp.route("/ga/apply-recommendation", methods=["POST"], endpoint="ga_apply_recommendation")
@login_required
def ga_apply_recommendation():
    """Apply a GA recommendation."""
    from app.services.ga_insights import apply_ga_recommendation

    data = request.get_json() if request.is_json else request.form
    recommendation_id = data.get("recommendation_id")

    if not recommendation_id:
        return jsonify({"ok": False, "error": "Missing recommendation_id"}), 400

    try:
        recommendation_id = int(recommendation_id)
    except:
        return jsonify({"ok": False, "error": "Invalid recommendation_id"}), 400

    success, message = apply_ga_recommendation(recommendation_id, current_user.id)

    if success:
        return jsonify({"ok": True, "message": message})
    else:
        return jsonify({"ok": False, "error": message}), 400


@google_bp.route("/ga/dismiss-recommendation", methods=["POST"], endpoint="ga_dismiss_recommendation")
@login_required
def ga_dismiss_recommendation():
    """Dismiss a GA recommendation."""
    from app.services.ga_insights import dismiss_ga_recommendation

    data = request.get_json() if request.is_json else request.form
    recommendation_id = data.get("recommendation_id")
    reason = data.get("reason", "")

    if not recommendation_id:
        return jsonify({"ok": False, "error": "Missing recommendation_id"}), 400

    try:
        recommendation_id = int(recommendation_id)
    except:
        return jsonify({"ok": False, "error": "Invalid recommendation_id"}), 400

    success, message = dismiss_ga_recommendation(recommendation_id, current_user.id, reason)

    if success:
        return jsonify({"ok": True, "message": message})
    else:
        return jsonify({"ok": False, "error": message}), 400


# ========================== GSC Insights Routes ==========================

@google_bp.route("/gsc/insights.json", methods=["POST"], endpoint="gsc_insights_json")
@login_required
def gsc_insights_json():
    """Generate AI SEO insights for Google Search Console property."""
    from app.services.gsc_insights import generate_gsc_insights

    aid = current_account_id()
    data = request.get_json() if request.is_json else {}
    site_url = data.get("site_url", "")
    regenerate = bool(data.get("regenerate", False))

    if not site_url:
        return jsonify({"ok": False, "error": "Missing site_url"}), 400

    try:
        insights = generate_gsc_insights(aid, site_url, regenerate=regenerate)
        return jsonify({"ok": True, **insights})
    except Exception as e:
        current_app.logger.error(f"Error generating GSC insights: {e}", exc_info=True)
        return jsonify({"ok": False, "error": str(e)}), 500


@google_bp.route("/gsc/apply-recommendation", methods=["POST"], endpoint="gsc_apply_recommendation")
@login_required
def gsc_apply_recommendation():
    """Apply a GSC recommendation."""
    from app.services.gsc_insights import apply_gsc_recommendation

    data = request.get_json() if request.is_json else request.form
    recommendation_id = data.get("recommendation_id")

    if not recommendation_id:
        return jsonify({"ok": False, "error": "Missing recommendation_id"}), 400

    try:
        recommendation_id = int(recommendation_id)
    except:
        return jsonify({"ok": False, "error": "Invalid recommendation_id"}), 400

    success, message = apply_gsc_recommendation(recommendation_id, current_user.id)

    if success:
        return jsonify({"ok": True, "message": message})
    else:
        return jsonify({"ok": False, "error": message}), 400


@google_bp.route("/gsc/dismiss-recommendation", methods=["POST"], endpoint="gsc_dismiss_recommendation")
@login_required
def gsc_dismiss_recommendation():
    """Dismiss a GSC recommendation."""
    from app.services.gsc_insights import dismiss_gsc_recommendation

    data = request.get_json() if request.is_json else request.form
    recommendation_id = data.get("recommendation_id")
    reason = data.get("reason", "")

    if not recommendation_id:
        return jsonify({"ok": False, "error": "Missing recommendation_id"}), 400

    try:
        recommendation_id = int(recommendation_id)
    except:
        return jsonify({"ok": False, "error": "Invalid recommendation_id"}), 400

    success, message = dismiss_gsc_recommendation(recommendation_id, current_user.id, reason)

    if success:
        return jsonify({"ok": True, "message": message})
    else:
        return jsonify({"ok": False, "error": message}), 400


# ========================== Disconnect Route ==========================

@google_bp.route("/disconnect/<product>", methods=["POST", "GET"], endpoint="disconnect")
@login_required
def disconnect(product: str):
    canon = _normalize_product(product or "")
    if not canon:
        flash("Unknown Google product.", "error")
        return redirect(url_for("google_bp.index"))

    aid = current_account_id()
    with db.engine.begin() as conn:
        conn.execute(
            text("DELETE FROM google_oauth_tokens WHERE account_id=:aid AND product=:prod"),
            {"aid": aid, "prod": canon},
        )

    if canon == "ads":
        session.pop(f"ads_state_{aid}", None)
        session.pop(f"ads_suggestions_{aid}", None)

    flash(f"Disconnected Google {canon.upper()}.", "info")
    return redirect(url_for("google_bp.index"))
