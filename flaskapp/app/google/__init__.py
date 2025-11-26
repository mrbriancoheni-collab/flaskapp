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
from app.auth.utils import login_required, ajax_login_required, current_account_id
from app.google.utils_ads import (
    pick_and_save_customer_id_after_oauth,
    save_customer_id,
)

google_bp = Blueprint("google_bp", __name__, url_prefix="/account/google")

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"


def _safe_db_query(query_func, retry_with_table_creation=True):
    """
    Execute a database query with automatic error handling and table creation.

    If a table doesn't exist or column is missing, automatically create/alter the schema.

    Args:
        query_func: Function that executes the query and returns results
        retry_with_table_creation: If True, retry once after ensuring tables exist

    Returns:
        Query results or None if error
    """
    try:
        return query_func()
    except Exception as e:
        error_msg = str(e).lower()

        # Check for common database errors indicating missing tables/columns
        needs_schema_fix = any([
            "doesn't exist" in error_msg,
            "no such table" in error_msg,
            "unknown column" in error_msg,
            "table not found" in error_msg,
        ])

        if needs_schema_fix and retry_with_table_creation:
            current_app.logger.warning(f"Database schema error detected: {e}. Attempting to create/fix tables...")
            try:
                # Ensure all Google tables exist
                from app.models_google import ensure_google_tables
                ensure_google_tables()
                current_app.logger.info("Successfully created/fixed database tables")

                # Retry the query
                return query_func()
            except Exception as retry_error:
                current_app.logger.error(f"Failed to fix database schema: {retry_error}", exc_info=True)
                return None
        else:
            current_app.logger.error(f"Database query error: {e}", exc_info=True)
            return None

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
    # Try reading from accounts table first (where save_customer_id stores it)
    try:
        with db.engine.connect() as conn:
            row = conn.execute(
                text("SELECT google_ads_customer_id FROM accounts WHERE id=:aid LIMIT 1"),
                {"aid": aid},
            ).first()
        if row and row[0]:
            return str(row[0]).replace("-", "")
    except Exception:
        current_app.logger.debug("Could not read google_ads_customer_id from accounts table")

    # Try utils_ads helper if available
    try:
        from app.google.utils_ads import get_customer_id  # optional
        cid = get_customer_id(aid)
        if cid:
            return str(cid).replace("-", "")
    except Exception:
        pass

    # Try google_oauth_tokens table
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
        current_app.logger.debug("Could not read google_ads_customer_id from tokens table")

    # Try google_ads_accounts table (legacy)
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
        current_app.logger.debug("Could not read saved Google Ads customer id (legacy table)")

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

    # Only include login_customer_id if it's actually set (MCC accounts only)
    login_cid = (current_app.config.get("GOOGLE_ADS_LOGIN_CUSTOMER_ID") or os.getenv("GOOGLE_ADS_LOGIN_CUSTOMER_ID") or "").replace("-", "")

    cfg = {
        "developer_token": current_app.config.get("GOOGLE_ADS_DEVELOPER_TOKEN") or os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN"),
        "use_proto_plus": True,
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
    }

    # Only add login_customer_id if it's a valid 10-digit number (MCC mode)
    if login_cid and len(login_cid) == 10 and login_cid.isdigit():
        cfg["login_customer_id"] = login_cid
        current_app.logger.info(f"Using MCC login_customer_id: {login_cid}")
    else:
        current_app.logger.info(f"Direct account mode (no MCC)")

    if not cfg["developer_token"]:
        raise RuntimeError("Missing GOOGLE_ADS_DEVELOPER_TOKEN")

    client = GoogleAdsClient.load_from_dict(cfg)

    def _gaql(q: str):
        svc = client.get_service("GoogleAdsService")
        return svc.search(customer_id=customer_id, query=q)

    campaigns = []
    for r in _gaql("""
        SELECT campaign.id, campaign.name, campaign.status,
               campaign.advertising_channel_type, campaign.bidding_strategy_type,
               campaign_budget.amount_micros,
               metrics.cost_micros, metrics.conversions, metrics.clicks, metrics.impressions
        FROM campaign
        WHERE campaign.status != 'REMOVED'
          AND segments.date DURING LAST_30_DAYS
        ORDER BY metrics.cost_micros DESC
        LIMIT 50
    """):
        c = r.campaign
        metrics = r.metrics
        budget_micros = r.campaign_budget.amount_micros if hasattr(r, 'campaign_budget') and r.campaign_budget else None
        daily_budget = (budget_micros / 1_000_000) if budget_micros else None
        cost = (metrics.cost_micros or 0) / 1_000_000
        conversions = metrics.conversions or 0

        campaigns.append({
            "id": str(c.id),
            "name": c.name,
            "type": str(c.advertising_channel_type).split(".")[-1],
            "status": str(c.status).split(".")[-1],
            "daily_budget": daily_budget,
            "bidding": str(c.bidding_strategy_type).split(".")[-1],
            "target": None,
            "cost_30d": cost,
            "conversions": conversions,
            "clicks": metrics.clicks or 0,
            "impressions": metrics.impressions or 0,
            "cpa": (cost / conversions) if conversions > 0 else None,
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
               ad_group_criterion.ad_group,
               metrics.cost_micros, metrics.conversions, metrics.clicks
        FROM keyword_view
        WHERE ad_group_criterion.status != 'REMOVED'
          AND segments.date DURING LAST_30_DAYS
        ORDER BY metrics.cost_micros DESC
        LIMIT 100
    """):
        kw = r.ad_group_criterion
        metrics = r.metrics
        cost = (metrics.cost_micros or 0) / 1_000_000
        conversions = metrics.conversions or 0
        keywords.append({
            "id": str(kw.criterion_id),
            "ad_group_id": str(kw.ad_group.split("/")[-1]),
            "match": str(kw.keyword.match_type).split(".")[-1].title(),
            "text": kw.keyword.text,
            "status": str(kw.status).split(".")[-1],
            "cpc": (cost / max(1, metrics.clicks or 1)) if cost > 0 else None,
            "conv": conversions,
            "cpa": (cost / conversions) if conversions > 0 else None,
        })

    # Fetch negative keywords (campaign-level)
    negatives = []
    try:
        for r in _gaql("""
            SELECT campaign_criterion.criterion_id, campaign_criterion.keyword.text,
                   campaign_criterion.keyword.match_type, campaign_criterion.campaign
            FROM campaign_criterion
            WHERE campaign_criterion.type = KEYWORD
              AND campaign_criterion.negative = TRUE
            LIMIT 200
        """):
            neg = r.campaign_criterion
            negatives.append({
                "id": str(neg.criterion_id),
                "campaign_id": str(neg.campaign.split("/")[-1]),
                "text": neg.keyword.text,
                "match": str(neg.keyword.match_type).split(".")[-1].title(),
            })
    except Exception as e:
        current_app.logger.warning(f"Failed to fetch negative keywords: {e}")

    # Fetch ads (RSA - Responsive Search Ads)
    ads = []
    try:
        for r in _gaql("""
            SELECT ad_group_ad.ad.id, ad_group_ad.status, ad_group_ad.ad_group,
                   ad_group_ad.ad.responsive_search_ad.headlines,
                   ad_group_ad.ad.responsive_search_ad.descriptions,
                   ad_group_ad.ad.final_urls
            FROM ad_group_ad
            WHERE ad_group_ad.ad.type = RESPONSIVE_SEARCH_AD
              AND ad_group_ad.status != 'REMOVED'
            LIMIT 50
        """):
            ad = r.ad_group_ad
            headlines = [h.text for h in ad.ad.responsive_search_ad.headlines] if ad.ad.responsive_search_ad.headlines else []
            descriptions = [d.text for d in ad.ad.responsive_search_ad.descriptions] if ad.ad.responsive_search_ad.descriptions else []
            ads.append({
                "id": str(ad.ad.id),
                "ad_group_id": str(ad.ad_group.split("/")[-1]),
                "status": str(ad.status).split(".")[-1],
                "headlines": headlines[:3],  # First 3 headlines
                "descriptions": descriptions[:2],  # First 2 descriptions
                "final_url": ad.ad.final_urls[0] if ad.ad.final_urls else None,
            })
    except Exception as e:
        current_app.logger.warning(f"Failed to fetch ads: {e}")

    # Fetch extensions
    extensions = []
    try:
        # Fetch campaign-level assets (v21 API uses campaign_asset)
        # Note: LOCATION is not a valid field_type, it's set differently via location extensions
        for r in _gaql("""
            SELECT campaign_asset.field_type,
                   campaign.id
            FROM campaign_asset
            WHERE campaign_asset.field_type IN (
                'CALL', 'SITELINK', 'CALLOUT', 'STRUCTURED_SNIPPET', 'PROMOTION'
            )
        """):
            field_type = str(r.campaign_asset.field_type).split(".")[-1].lower()
            campaign_id = str(r.campaign.id)

            # Dedupe by type
            if not any(e["type"] == field_type for e in extensions):
                extensions.append({
                    "type": field_type,
                    "campaign_id": campaign_id,
                })

        # Check for location extensions separately (they use a different resource)
        try:
            for r in _gaql("""
                SELECT campaign.id
                FROM campaign_feed
                WHERE campaign_feed.placeholder_types CONTAINS 'LOCATION'
            """):
                campaign_id = str(r.campaign.id)
                if not any(e["type"] == "location" for e in extensions):
                    extensions.append({
                        "type": "location",
                        "campaign_id": campaign_id,
                    })
        except Exception as loc_err:
            # Location extensions may not be available or query may fail
            current_app.logger.debug(f"Could not fetch location extensions: {loc_err}")

    except Exception as e:
        current_app.logger.warning(f"Failed to fetch campaign assets: {e}")

    # Fetch landing pages from ads
    landing_pages = []
    seen_urls = set()
    for ad in ads:
        url = ad.get("final_url")
        if url and url not in seen_urls:
            landing_pages.append({"url": url})
            seen_urls.add(url)

    return {
        "account_name": customer_id,
        "campaigns": campaigns,
        "ad_groups": ad_groups,
        "keywords": keywords,
        "negatives": negatives,
        "ads": ads,
        "extensions": extensions,
        "landing_pages": landing_pages,
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
    """
    Google Ads main page - Uses the Opportunities Dashboard layout with real user data.
    Same layout as the demo page but shows actual connected account data.
    """
    aid = current_account_id()
    connected = _is_connected(aid, "ads")

    # Get ads data
    ads_data = _get_ads_state(aid)

    # Generate comprehensive analysis using the opportunities analyzer
    analysis = _analyze_ads_opportunities(aid, ads_data)

    # Split opportunities into auto-applicable and manual tasks
    # Auto-applicable: Can be applied with one click or AI agent
    # Manual tasks: Require extensive manual setup
    all_opportunities = analysis.get("opportunities", [])

    def is_auto_applicable(opp):
        opt_type = opp.get("optimization_type", "")

        # Core auto-applicable types (can be applied with one click)
        if opt_type in ['negative_keyword', 'mobile_bid']:
            return True

        # Extension types - only callout and structured snippet are auto-applicable
        if opt_type == 'extension':
            ext_type = opp.get("optimization_data", {}).get("type", "").lower()
            return "callout" in ext_type or "snippet" in ext_type or "structured" in ext_type

        # Agent-generated optimizations - check if they're auto-executable
        if opp.get('agent_generated'):
            requires_approval = opp.get('optimization_data', {}).get('requires_approval', True)
            return not requires_approval  # Auto-applicable if doesn't require approval

        # Agent decision types that are auto-executable
        agent_auto_types = [
            'pause_keyword',           # Pause underperformers
            'adjust_keyword_bid',      # Bid adjustments
            'add_negative_keyword',    # Block waste
            'adjust_bids',             # Campaign-level bid adjustments
            'adjust_daily_budget',     # Budget pacing
        ]
        if opt_type in agent_auto_types:
            return True

        # Note: mobile_ads requires custom ad copy, so it's NOT auto-applicable
        return False

    # Get already-applied optimizations to filter them out
    from app.models_google import AppliedOptimization, CompletedManualTask, ensure_google_tables
    applied_optimization_titles = set()

    def _fetch_applied_opts():
        """Fetch applied optimizations from database."""
        from datetime import datetime, timedelta
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)
        applied_opts = AppliedOptimization.query.filter(
            AppliedOptimization.account_id == aid,
            AppliedOptimization.status == 'applied',
            AppliedOptimization.created_at >= thirty_days_ago
        ).all()
        return {opt.optimization_title for opt in applied_opts}

    # Use safe query wrapper with automatic table creation
    result = _safe_db_query(_fetch_applied_opts)
    if result is not None:
        applied_optimization_titles = result
        current_app.logger.info(f"Found {len(applied_optimization_titles)} applied optimizations in last 30 days")
    else:
        current_app.logger.warning("Could not fetch applied optimizations, proceeding without filter")

    # Filter out already-applied optimizations from auto-applicable list
    auto_applicable_opps = [opp for opp in all_opportunities if is_auto_applicable(opp)]
    analysis["opportunities"] = [
        opp for opp in auto_applicable_opps
        if opp.get("title") not in applied_optimization_titles
    ]

    all_manual_tasks = [opp for opp in all_opportunities if not is_auto_applicable(opp)]

    # Filter out completed manual tasks
    completed_task_ids = set()

    def _fetch_completed_tasks():
        """Fetch completed manual tasks from database."""
        return {task.task_id for task in CompletedManualTask.query.filter_by(account_id=aid).all()}

    # Use safe query wrapper with automatic table creation
    result = _safe_db_query(_fetch_completed_tasks)
    if result is not None:
        completed_task_ids = result
    else:
        current_app.logger.warning("Could not fetch completed manual tasks, proceeding without filter")

    analysis["manual_tasks"] = [
        task for task in all_manual_tasks
        if task.get("id") not in completed_task_ids
    ]

    current_app.logger.info(
        f"ads_ui: Split {len(all_opportunities)} total into {len(auto_applicable_opps)} auto-applicable "
        f"({len(applied_optimization_titles)} already applied, {len(analysis['opportunities'])} remaining) "
        f"and {len(all_manual_tasks)} manual tasks ({len(completed_task_ids)} completed, {len(analysis['manual_tasks'])} remaining). "
        f"Auto types: {[o.get('title') for o in analysis['opportunities']]}"
    )

    # TEMPLATE DEBUG: Log what's being passed to template
    current_app.logger.info(
        f"TEMPLATE DEBUG - Passing to template: "
        f"opportunities={len(analysis.get('opportunities', []))}, "
        f"manual_tasks={len(analysis.get('manual_tasks', []))}, "
        f"manual_task_titles={[t.get('title') for t in analysis.get('manual_tasks', [])]}"
    )

    return render_template(
        "google/ads_opportunities.html",
        connected=connected,
        ads_data=ads_data,
        analysis=analysis,
        epn=request.endpoint,
        is_demo=False,
    )

# ------------------------- GA JSON data (AJAX) -------------------------

@google_bp.route("/analytics/data", methods=["GET"], endpoint="ga_data")
@login_required
def ga_data():
    # Detect if this is being accessed directly in a browser (not AJAX)
    # If so, redirect to the main analytics page
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    accepts_json = 'application/json' in request.headers.get('Accept', '')

    if not is_ajax and not accepts_json:
        # User is accessing this directly - redirect to main analytics page
        timeframe = request.args.get("timeframe", "28d")
        return redirect(url_for("google_bp.ga_ui", timeframe=timeframe))

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

@google_bp.route("/ads/list-customers", methods=["GET"], endpoint="ads_list_customers")
@ajax_login_required
def ads_list_customers():
    """AJAX endpoint to fetch accessible Google Ads customer IDs."""
    aid = current_account_id()
    try:
        # Get refresh token from database (the official Google Ads library needs refresh_token)
        with db.engine.connect() as conn:
            row = conn.execute(
                text("""
                    SELECT refresh_token
                    FROM google_oauth_tokens
                    WHERE account_id=:aid AND LOWER(product) IN ('ads', 'lsa')
                    ORDER BY updated_at DESC LIMIT 1
                """),
                {"aid": aid}
            ).mappings().first()

        if not row or not row['refresh_token']:
            return jsonify({"ok": False, "error": "Not connected - no refresh token"}), 400

        from app.google.utils_ads import list_accessible_customers
        customer_ids = list_accessible_customers(row['refresh_token'])

        # Get current default customer ID
        with db.engine.connect() as conn:
            account_row = conn.execute(
                text("SELECT google_ads_customer_id FROM accounts WHERE id=:aid LIMIT 1"),
                {"aid": aid}
            ).mappings().first()

        current_id = account_row['google_ads_customer_id'] if account_row else None

        return jsonify({
            "ok": True,
            "customers": customer_ids,
            "current": current_id
        })
    except ValueError as e:
        # ValueError contains user-friendly messages (NOT_ADS_USER, UNAUTHENTICATED, etc.)
        current_app.logger.warning(f"Google Ads access issue: {e}")
        return jsonify({"ok": False, "error": str(e), "error_type": "access_issue"}), 400
    except Exception as e:
        current_app.logger.exception("Failed to list Google Ads customers")
        return jsonify({"ok": False, "error": str(e)}), 500


@google_bp.route("/ads/select-customer", methods=["POST", "GET"], endpoint="ads_select_customer")
@ajax_login_required
def ads_select_customer():
    """AJAX endpoint to save selected Google Ads customer ID and fetch initial data."""
    aid = current_account_id()
    customer_id = (request.values.get("customer_id") or "").strip()

    if not customer_id:
        return jsonify({"ok": False, "error": "Missing customer_id"}), 400

    try:
        from app.google.utils_ads import save_customer_id
        save_customer_id(aid, customer_id)

        # Automatically fetch and analyze ads data after saving customer ID
        try:
            current_app.logger.info(f"Auto-fetching Google Ads data for account {aid} after customer selection")
            snapshot = _fetch_ads_snapshot_from_google(aid)
            _save_ads_state(aid, snapshot)
            current_app.logger.info(f"Successfully fetched and saved Google Ads data for account {aid}")
        except Exception as fetch_err:
            # Log but don't fail the save - data can be fetched later
            current_app.logger.warning(f"Could not auto-fetch ads data after save: {fetch_err}")

        return jsonify({"ok": True, "customer_id": customer_id})
    except Exception as e:
        current_app.logger.exception("Failed to save Google Ads customer ID")
        return jsonify({"ok": False, "error": str(e)}), 500


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
    _ = _get_ads_state(aid)
    sugs: dict[str, list[dict]] = {}
    if scope in ("all", "campaigns"):
        sugs["campaigns"] = [
            {"id": "S-C-1", "change": "Raise budget +10% for 'Emergency Plumbing - Search' (hitting target tCPA)."},
            {"id": "S-C-2", "change": "Switch paused 'Water Heater Install' to Max Conv with target CPA of $70."},
        ]
    if scope in ("all", "adgroups"):
        sugs["adgroups"] = [{"id": "S-G-1", "change": "Split 'Near Me' into Mobile/Desktop for device bid mods."}]
    if scope in ("all", "keywords"):
        sugs["keywords"] = [
            {"id": "S-K-1", "change": "Promote [emergency plumber near me] to exact and raise CPC to $10.50."},
            {"id": "S-K-2", "change": "Pause low-perf 'plumber 24 hours' broad; add phrase variant."},
        ]
    if scope in ("all", "negatives"):
        sugs["negatives"] = [{"id": "S-N-1", "change": "Add account-level negatives: 'free', 'DIY'."}]
    if scope in ("all", "ads"):
        sugs["ads"] = [
            {"id": "S-A-1", "change": "New headline: 'Local Plumber in 30–60 Minutes'"},
            {"id": "S-A-2", "change": "Add benefit callout: 'No Trip Fees • Upfront Pricing'"},
        ]
    if scope in ("all", "extensions"):
        sugs["extensions"] = [{"id": "S-E-1", "change": "Add sitelinks to Finance, Coupons, Same-Day Service."}]
    if scope in ("all", "landing"):
        sugs["landing"] = [{"id": "S-L-1", "change": "Add sticky mobile CTA on /water-heaters, compress hero image to <200 KB."}]
    session[f"ads_suggestions_{aid}"] = sugs
    return sugs

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


@google_bp.route("/ads/opportunities/demo", methods=["GET"], endpoint="ads_opportunities_demo")
def ads_opportunities_demo():
    """
    Demo version of Opportunities Dashboard for showing to potential customers.
    Does not require login or connected account - uses mock data.
    """
    from flask import current_app, render_template

    try:
        current_app.logger.info("Demo route accessed - starting")

        # Generate mock ads data for demo
        mock_ads_data = {
            "account_name": "ABC Plumbing & HVAC (Demo)",
            "campaigns": [
                {"name": "Emergency Services", "status": "enabled", "daily_budget": 150, "conversions": 45},
                {"name": "Main Campaign", "status": "enabled", "daily_budget": 200, "conversions": 62},
                {"name": "Water Heater Services", "status": "enabled", "daily_budget": 100, "conversions": 28},
                {"name": "Seasonal Campaign", "status": "paused", "daily_budget": 75, "conversions": 12},
            ],
            "ad_groups": [
                {"name": "Emergency Plumbing", "status": "enabled"},
                {"name": "HVAC Repair", "status": "enabled"},
                {"name": "Water Heater", "status": "enabled"},
                {"name": "AC Installation", "status": "enabled"},
                {"name": "Heating Services", "status": "enabled"},
            ],
            "keywords": [
                {"keyword": "emergency plumber", "cpa": 45, "conv": 15},
                {"keyword": "24/7 plumbing", "cpa": 38, "conv": 12},
                {"keyword": "hvac repair", "cpa": 52, "conv": 18},
                {"keyword": "water heater repair", "cpa": 41, "conv": 10},
                {"keyword": "ac installation", "cpa": 65, "conv": 8},
            ],
            "negatives": [
                {"keyword": "diy"},
                {"keyword": "training"},
            ],
            "ads": [
                {"headline": "24/7 Emergency Plumber", "status": "enabled"},
                {"headline": "Licensed HVAC Repair", "status": "enabled"},
                {"headline": "Water Heater Installation", "status": "enabled"},
            ],
            "extensions": [
                {"type": "call", "phone": "555-123-4567"},
            ],
        }

        current_app.logger.info("Mock data created - generating analysis")
        # Generate comprehensive analysis using the same function as the real version
        analysis = _analyze_ads_opportunities(0, mock_ads_data)  # aid=0 for demo
        current_app.logger.info(f"Analysis completed - opportunities count: {len(analysis.get('opportunities', []))}")

        # Split opportunities into auto-applicable and manual tasks
        # Auto-applicable: Can be applied with one click (negative_keyword, mobile_bid, callout/snippet extensions)
        # Manual tasks: Require manual setup (setup, quality_score, mobile_ads, account_structure, location/call/sitelink extensions)
        all_opportunities = analysis.get("opportunities", [])

        def is_auto_applicable(opp):
            opt_type = opp.get("optimization_type", "")
            if opt_type in ['negative_keyword', 'mobile_bid']:
                return True
            if opt_type == 'extension':
                # Only callout and structured snippet extensions are auto-applicable
                ext_type = opp.get("optimization_data", {}).get("type", "").lower()
                return "callout" in ext_type or "snippet" in ext_type or "structured" in ext_type
            return False

        analysis["opportunities"] = [opp for opp in all_opportunities if is_auto_applicable(opp)]
        analysis["manual_tasks"] = [opp for opp in all_opportunities if not is_auto_applicable(opp)]

        # Note: Demo mode doesn't filter completed tasks since it's not tied to a real account

        current_app.logger.info(
            f"ads_opportunities_demo: Split {len(all_opportunities)} total into {len(analysis['opportunities'])} auto-applicable "
            f"and {len(analysis['manual_tasks'])} manual tasks. Auto types: {[o.get('title') for o in analysis['opportunities']]}"
        )

        # TEMPLATE DEBUG: Log what's being passed to template
        current_app.logger.info(
            f"TEMPLATE DEBUG - Passing to template: "
            f"opportunities={len(analysis.get('opportunities', []))}, "
            f"manual_tasks={len(analysis.get('manual_tasks', []))}, "
            f"manual_task_titles={[t.get('title') for t in analysis.get('manual_tasks', [])]}"
        )

        current_app.logger.info("Rendering template")
        return render_template(
            "google/ads_opportunities.html",
            connected=True,  # Show as connected for demo purposes
            ads_data=mock_ads_data,
            analysis=analysis,
            epn="ads_opportunities_demo",
            is_demo=True,  # Flag to indicate this is a demo
        )
    except Exception as e:
        current_app.logger.exception(f"Error in demo route: {str(e)}")
        # Return detailed error for debugging
        import traceback
        return f"""
        <html><body>
        <h1>Demo Error Debug Info</h1>
        <p><strong>Error:</strong> {str(e)}</p>
        <p><strong>Type:</strong> {type(e).__name__}</p>
        <pre>{traceback.format_exc()}</pre>
        </body></html>
        """, 500


@google_bp.route("/ads/opportunities", methods=["GET"], endpoint="ads_opportunities")
@login_required
def ads_opportunities():
    """
    Opportunities Dashboard - Beautiful, actionable insights view.
    Matches the visual quality of the ads-grader report.

    Note: Email notifications are sent by the daily cron job (see cron_tasks.py),
    not when users view this page.
    """
    aid = current_account_id()
    connected = _is_connected(aid, "ads")

    # Get ads data
    ads_data = _get_ads_state(aid)

    # Generate comprehensive analysis
    analysis = _analyze_ads_opportunities(aid, ads_data)

    # Split opportunities into auto-applicable and manual tasks
    # Auto-applicable: Can be applied with one click (negative_keyword, mobile_bid, callout/snippet extensions)
    # Manual tasks: Require manual setup (setup, quality_score, mobile_ads, account_structure, location/call/sitelink extensions)
    all_opportunities = analysis.get("opportunities", [])

    def is_auto_applicable(opp):
        opt_type = opp.get("optimization_type", "")
        if opt_type in ['negative_keyword', 'mobile_bid']:
            return True
        if opt_type == 'extension':
            # Only callout and structured snippet extensions are auto-applicable
            ext_type = opp.get("type", "").lower()
            return "callout" in ext_type or "snippet" in ext_type or "structured" in ext_type
        return False

    analysis["opportunities"] = [opp for opp in all_opportunities if is_auto_applicable(opp)]
    analysis["manual_tasks"] = [opp for opp in all_opportunities if not is_auto_applicable(opp)]

    current_app.logger.info(
        f"ads_opportunities: Split {len(all_opportunities)} total into {len(analysis['opportunities'])} auto-applicable "
        f"and {len(analysis['manual_tasks'])} manual tasks. Auto types: {[o.get('title') for o in analysis['opportunities']]}"
    )

    # TEMPLATE DEBUG: Log what's being passed to template
    current_app.logger.info(
        f"TEMPLATE DEBUG - Passing to template: "
        f"opportunities={len(analysis.get('opportunities', []))}, "
        f"manual_tasks={len(analysis.get('manual_tasks', []))}, "
        f"manual_task_titles={[t.get('title') for t in analysis.get('manual_tasks', [])]}"
    )

    return render_template(
        "google/ads_opportunities.html",
        connected=connected,
        ads_data=ads_data,
        analysis=analysis,
        epn=request.endpoint,
        is_demo=False,
    )


@google_bp.route("/ads/structure", methods=["GET"], endpoint="ads_structure")
@login_required
def ads_structure():
    """
    Account Structure page - Shows the full hierarchy of the Google Ads account.
    Displays campaigns, ad groups, keywords, ads, and extensions in a navigable tree view.
    """
    aid = current_account_id()
    connected = _is_connected(aid, "ads")

    # Get ads data
    ads_data = _get_ads_state(aid)

    return render_template(
        "google/ads_structure.html",
        connected=connected,
        ads_data=ads_data,
        epn=request.endpoint,
    )


def _apply_optimization(aid: int, customer_id: str, opt_type: str, opt_data: dict, opt_title: str) -> dict:
    """
    Apply a single optimization to Google Ads via API.

    Returns dict with: {"success": bool, "resource_name": str, "api_response": dict, "message": str, "error": str}
    """
    try:
        # Get Google Ads refresh token from database
        try:
            with db.engine.connect() as conn:
                row = (
                    conn.execute(
                        text("SELECT credentials_json FROM google_oauth_tokens WHERE account_id=:aid AND product='ads' ORDER BY id DESC LIMIT 1"),
                        {"aid": aid},
                    )
                ).mappings().first()

            if not row:
                return {"success": False, "error": "No OAuth token found for Google Ads"}

            creds = json.loads(row["credentials_json"])
            refresh_token = creds.get("refresh_token")

            if not refresh_token:
                return {"success": False, "error": "No refresh token available"}

        except Exception as e:
            return {"success": False, "error": f"API authentication failed: {str(e)}"}

        # Apply based on optimization type
        if opt_type == "negative_keyword":
            return _apply_negative_keyword(aid, customer_id, opt_data, refresh_token)

        elif opt_type == "mobile_bid":
            return _apply_mobile_bid_adjustment(aid, customer_id, opt_data, refresh_token)

        elif opt_type == "extension":
            return _apply_extension(aid, customer_id, opt_data, refresh_token)

        elif opt_type == "setup":
            # Setup tasks are manual best practices
            return {
                "success": False,
                "error": "This is a manual setup task. Please complete it in Google Ads UI following the action steps provided."
            }

        elif opt_type == "quality_score":
            # Quality score improvements are ongoing optimizations
            return {
                "success": False,
                "error": "Quality Score improvements require ongoing ad copy testing, landing page optimization, and relevance improvements. This is a manual optimization process."
            }

        elif opt_type == "mobile_ads":
            # Mobile ad creation requires custom ad copy
            return {
                "success": False,
                "error": "Creating mobile-optimized ads requires custom ad copy. Please write mobile-focused headlines and descriptions in Google Ads UI."
            }

        elif opt_type == "account_structure":
            # Account restructuring is complex manual work
            return {
                "success": False,
                "error": "Account restructuring requires manual planning and execution. Consult with a Google Ads specialist or follow Google's best practices for campaign organization."
            }

        else:
            # Unsupported optimization type - log but don't fail
            current_app.logger.warning(f"Unsupported optimization type: {opt_type}")
            return {
                "success": False,
                "error": f"Optimization type '{opt_type}' requires manual implementation. Please complete it in Google Ads UI."
            }

    except Exception as e:
        current_app.logger.exception(f"Error applying optimization {opt_title}")
        return {"success": False, "error": str(e)}


def _apply_negative_keyword(aid: int, customer_id: str, opt_data: dict, access_token: str) -> dict:
    """Add negative keyword to campaign."""
    try:
        from google.ads.googleads.client import GoogleAdsClient
        from google.ads.googleads.errors import GoogleAdsException

        term = opt_data.get("term", "")
        if not term:
            return {"success": False, "error": "No keyword term provided"}

        # Get campaign ID from optimization data
        campaign_id = opt_data.get("campaign_id")
        if not campaign_id:
            return {"success": False, "error": "No campaign ID provided"}

        # Create Google Ads client using same client_info lookup as data fetching
        client_id, client_secret = _client_info("ads")
        credentials = {
            "developer_token": current_app.config.get("GOOGLE_ADS_DEVELOPER_TOKEN"),
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": access_token,
            "token_uri": "https://oauth2.googleapis.com/token",
            "use_proto_plus": True
        }

        client = GoogleAdsClient.load_from_dict(credentials)
        campaign_criterion_service = client.get_service("CampaignCriterionService")

        # Build campaign criterion operation
        campaign_criterion_operation = client.get_type("CampaignCriterionOperation")
        campaign_criterion = campaign_criterion_operation.create

        # Set campaign resource name
        campaign_criterion.campaign = f"customers/{customer_id}/campaigns/{campaign_id}"
        campaign_criterion.negative = True
        campaign_criterion.keyword.text = term
        campaign_criterion.keyword.match_type = client.enums.KeywordMatchTypeEnum.BROAD

        # Execute
        response = campaign_criterion_service.mutate_campaign_criteria(
            customer_id=customer_id,
            operations=[campaign_criterion_operation]
        )

        resource_name = response.results[0].resource_name if response.results else None

        return {
            "success": True,
            "resource_name": resource_name,
            "api_response": {"results": [{"resource_name": resource_name}]},
            "message": f"Added negative keyword: {term}"
        }

    except GoogleAdsException as ex:
        error_msg = f"Google Ads API error: {ex.error.code().name}"
        for error in ex.failure.errors:
            error_msg += f" - {error.message}"
        return {"success": False, "error": error_msg}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _apply_mobile_bid_adjustment(aid: int, customer_id: str, opt_data: dict, access_token: str) -> dict:
    """Apply mobile bid adjustment to campaign."""
    try:
        from google.ads.googleads.client import GoogleAdsClient
        from google.ads.googleads.errors import GoogleAdsException

        bid_adjustment = opt_data.get("bid_adjustment", 20)  # Default 20%
        campaign_id = opt_data.get("campaign_id")

        if not campaign_id:
            return {"success": False, "error": "No campaign ID provided"}

        # Create Google Ads client using same client_info lookup as data fetching
        client_id, client_secret = _client_info("ads")
        credentials = {
            "developer_token": current_app.config.get("GOOGLE_ADS_DEVELOPER_TOKEN"),
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": access_token,
            "token_uri": "https://oauth2.googleapis.com/token",
            "use_proto_plus": True
        }

        client = GoogleAdsClient.load_from_dict(credentials)
        campaign_criterion_service = client.get_service("CampaignCriterionService")

        # Build mobile device criterion operation
        campaign_criterion_operation = client.get_type("CampaignCriterionOperation")
        campaign_criterion = campaign_criterion_operation.update

        # Set campaign resource name
        campaign_criterion.campaign = f"customers/{customer_id}/campaigns/{campaign_id}"
        campaign_criterion.criterion_id = 30001  # Mobile devices
        campaign_criterion.bid_modifier = 1.0 + (bid_adjustment / 100.0)  # Convert percentage to multiplier

        # Set update mask (v21 API)
        client.copy_from(
            campaign_criterion_operation.update_mask,
            client.get_type("FieldMask")(paths=["bid_modifier"])
        )

        # Execute
        response = campaign_criterion_service.mutate_campaign_criteria(
            customer_id=customer_id,
            operations=[campaign_criterion_operation]
        )

        resource_name = response.results[0].resource_name if response.results else None

        return {
            "success": True,
            "resource_name": resource_name,
            "api_response": {"results": [{"resource_name": resource_name}]},
            "message": f"Set mobile bid adjustment to +{bid_adjustment}%"
        }

    except GoogleAdsException as ex:
        error_msg = f"Google Ads API error: {ex.error.code().name}"
        for error in ex.failure.errors:
            error_msg += f" - {error.message}"
        return {"success": False, "error": error_msg}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _apply_extension(aid: int, customer_id: str, opt_data: dict, refresh_token: str) -> dict:
    """Apply ad extension (callout, sitelink, etc.) at account level."""
    try:
        from google.ads.googleads.client import GoogleAdsClient
        from google.ads.googleads.errors import GoogleAdsException

        current_app.logger.info(f"_apply_extension: opt_data={opt_data}")
        ext_type = opt_data.get("type", "").lower()
        current_app.logger.info(f"_apply_extension: ext_type={ext_type}")
        if not ext_type:
            current_app.logger.error(f"_apply_extension: No extension type in opt_data. Keys: {list(opt_data.keys())}")
            return {"success": False, "error": "No extension type specified"}

        # Create Google Ads client using same client_info lookup as data fetching
        client_id, client_secret = _client_info("ads")
        credentials = {
            "developer_token": current_app.config.get("GOOGLE_ADS_DEVELOPER_TOKEN"),
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "token_uri": "https://oauth2.googleapis.com/token",
            "use_proto_plus": True
        }

        # Log credential status for debugging
        cred_status = {k: ("present" if v else "MISSING") for k, v in credentials.items() if k != "use_proto_plus"}
        current_app.logger.info(f"_apply_extension: Credential status: {cred_status}")

        # Log client_id prefix for OAuth debugging (mask most of it for security)
        client_id = credentials.get("client_id", "")
        if client_id:
            client_id_preview = f"{client_id[:20]}...{client_id[-10:]}" if len(client_id) > 30 else "***"
            current_app.logger.info(f"_apply_extension: Using OAuth client_id: {client_id_preview}")

        try:
            client = GoogleAdsClient.load_from_dict(credentials)
        except Exception as oauth_error:
            current_app.logger.error(f"_apply_extension: OAuth client initialization failed: {oauth_error}")
            # Check if it's an unauthorized_client error
            error_str = str(oauth_error)
            if "unauthorized_client" in error_str.lower():
                return {
                    "success": False,
                    "error": f"OAuth Error: The refresh_token was issued by a different OAuth client, or your OAuth client (client_id ending in {client_id[-10:] if client_id else '???'}) doesn't have Google Ads API enabled. Please verify: 1) Your OAuth client has Google Ads API scope enabled, 2) Regenerate refresh_token using the correct OAuth client"
                }
            raise

        # Handle different extension types
        if "callout" in ext_type:
            return _create_callout_extension(client, customer_id, opt_data)
        elif "sitelink" in ext_type:
            return _create_sitelink_extension(client, customer_id, opt_data)
        elif "call" in ext_type:
            return _create_call_extension(client, customer_id, opt_data)
        elif "structured" in ext_type or "snippet" in ext_type:
            return _create_structured_snippet_extension(client, customer_id, opt_data)
        elif "location" in ext_type:
            # Location extensions require Google My Business integration
            return {
                "success": False,
                "error": "Location extensions require Google My Business link. Please connect GMB first or add manually in Google Ads UI."
            }
        else:
            return {
                "success": False,
                "error": f"Extension type '{ext_type}' not yet supported. Supported: Callout, Sitelink, Call, Structured Snippet"
            }

    except GoogleAdsException as ex:
        error_msg = f"Google Ads API error: {ex.error.code().name}"
        for error in ex.failure.errors:
            error_msg += f" - {error.message}"
        return {"success": False, "error": error_msg}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _create_callout_extension(client, customer_id: str, opt_data: dict) -> dict:
    """Create callout assets (API v21) for service business."""
    try:
        # Default callouts for service businesses
        callouts = [
            "Licensed & Insured",
            "20+ Years Experience",
            "Same Day Service",
            "Free Estimates"
        ]

        asset_service = client.get_service("AssetService")
        customer_asset_service = client.get_service("CustomerAssetService")

        created_assets = []

        # Step 1: Create callout assets
        for callout_text in callouts:
            asset_operation = client.get_type("AssetOperation")
            asset = asset_operation.create
            asset.name = f"Callout: {callout_text}"
            asset.callout_asset.callout_text = callout_text

            # Create the asset
            asset_response = asset_service.mutate_assets(
                customer_id=customer_id,
                operations=[asset_operation]
            )

            if asset_response.results:
                asset_resource_name = asset_response.results[0].resource_name
                created_assets.append(asset_resource_name)

                # Step 2: Link asset to customer
                customer_asset_operation = client.get_type("CustomerAssetOperation")
                customer_asset = customer_asset_operation.create
                customer_asset.asset = asset_resource_name
                customer_asset.field_type = client.enums.AssetFieldTypeEnum.CALLOUT

                customer_asset_service.mutate_customer_assets(
                    customer_id=customer_id,
                    operations=[customer_asset_operation]
                )

        return {
            "success": True,
            "resource_name": created_assets[0] if created_assets else None,
            "api_response": {"results": created_assets},
            "message": f"Created {len(created_assets)} callout assets: {', '.join(callouts)}"
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


def _create_sitelink_extension(client, customer_id: str, opt_data: dict) -> dict:
    """Sitelinks require actual landing page URLs from the business."""
    return {
        "success": False,
        "error": "Sitelink extensions require specific landing page URLs from your website. Please add manually in Google Ads UI with your actual page URLs (e.g., /services, /contact, /emergency)."
    }


def _create_call_extension(client, customer_id: str, opt_data: dict) -> dict:
    """Create call extension."""
    return {
        "success": False,
        "error": "Call extensions require business phone number. Please add manually in Google Ads UI with your phone number."
    }


def _create_structured_snippet_extension(client, customer_id: str, opt_data: dict) -> dict:
    """Create structured snippet asset (API v21) for service business."""
    try:
        # Default snippets for service businesses
        snippet_values = [
            "Repairs",
            "Installation",
            "Maintenance",
            "Emergency Service",
            "Inspection"
        ]

        asset_service = client.get_service("AssetService")
        customer_asset_service = client.get_service("CustomerAssetService")

        # Step 1: Create structured snippet asset
        asset_operation = client.get_type("AssetOperation")
        asset = asset_operation.create
        asset.name = "Structured Snippet: Services"

        # Set the structured snippet data
        snippet = asset.structured_snippet_asset
        snippet.header = "Services"
        snippet.values.extend(snippet_values)

        # Create the asset
        asset_response = asset_service.mutate_assets(
            customer_id=customer_id,
            operations=[asset_operation]
        )

        asset_resource_name = asset_response.results[0].resource_name if asset_response.results else None

        if asset_resource_name:
            # Step 2: Link asset to customer
            customer_asset_operation = client.get_type("CustomerAssetOperation")
            customer_asset = customer_asset_operation.create
            customer_asset.asset = asset_resource_name
            customer_asset.field_type = client.enums.AssetFieldTypeEnum.STRUCTURED_SNIPPET

            customer_asset_service.mutate_customer_assets(
                customer_id=customer_id,
                operations=[customer_asset_operation]
            )

        return {
            "success": True,
            "resource_name": asset_resource_name,
            "api_response": {"results": [asset_resource_name]},
            "message": f"Created structured snippet asset: Services - {', '.join(snippet_values)}"
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


@google_bp.route("/ads/approve-optimizations", methods=["POST"], endpoint="approve_optimizations")
@login_required
def approve_optimizations():
    """
    Handle approval and submission of selected optimizations to Google Ads.
    Receives a list of optimization IDs and applies them to the user's account.
    """
    try:
        from flask import jsonify

        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "No data provided"}), 400

        optimizations = data.get("optimizations", [])

        # Get actual numeric customer ID from database (not the display name from frontend)
        aid = current_account_id()
        current_app.logger.info(f"approve_optimizations: aid={aid}, looking up customer_id...")
        customer_id = _get_saved_customer_id(aid)
        current_app.logger.info(f"approve_optimizations: customer_id={customer_id}")

        if not customer_id:
            current_app.logger.error(f"approve_optimizations: No customer ID found for aid={aid}")
            return jsonify({"success": False, "error": "No Google Ads customer ID found. Please reconnect your Google Ads account."}), 400

        if not optimizations:
            current_app.logger.warning(f"approve_optimizations: No optimizations provided in request")
            return jsonify({"success": False, "error": "No optimizations selected"}), 400

        # Log the approval action
        from app.models_audit import AuditLog
        from app.models_google import AppliedOptimization
        from app import db

        opt_titles = [opt.get("title", f"Optimization {opt.get('id')}") for opt in optimizations]
        opt_types = [opt.get("optimization_type", "unknown") for opt in optimizations]

        current_app.logger.info(
            f"approve_optimizations: Received {len(optimizations)} items. "
            f"Types: {dict((t, opt_types.count(t)) for t in set(opt_types))}"
        )

        # Log first optimization for debugging
        if optimizations:
            first_opt = optimizations[0]
            current_app.logger.info(
                f"approve_optimizations: First optimization: "
                f"title={first_opt.get('title')}, "
                f"type={first_opt.get('optimization_type')}, "
                f"has_data={bool(first_opt.get('optimization_data'))}, "
                f"data_keys={list(first_opt.get('optimization_data', {}).keys())}"
            )

        AuditLog.log(
            account_id=aid,
            user_id=current_user.id,
            action="google_ads_approve_optimizations",
            context_data={
                "note": f"Approved {len(optimizations)} optimizations: {', '.join(opt_titles)}",
                "optimization_count": len(optimizations),
                "optimization_titles": opt_titles,
                "optimization_types": opt_types
            }
        )

        # Apply each optimization via Google Ads API
        results = []
        applied_count = 0
        failed_count = 0

        for opt in optimizations:
            opt_type = opt.get("optimization_type", "")
            opt_title = opt.get("title", "")
            opt_data = opt.get("optimization_data", {})

            # Create tracking record
            applied_opt = AppliedOptimization(
                account_id=aid,
                user_id=current_user.id,
                customer_id=customer_id,
                optimization_type=opt_type,
                optimization_title=opt_title,
                optimization_data=opt_data,
                status='pending'
            )
            db.session.add(applied_opt)
            db.session.flush()  # Get ID

            try:
                # Apply the optimization based on type
                result = _apply_optimization(aid, customer_id, opt_type, opt_data, opt_title)

                if result.get("success"):
                    applied_opt.status = 'applied'
                    applied_opt.resource_name = result.get("resource_name")
                    applied_opt.api_response = result.get("api_response")
                    applied_opt.applied_at = datetime.utcnow()
                    applied_count += 1
                    results.append({
                        "optimization": opt_title,
                        "type": opt_type,
                        "status": "applied",
                        "resource_name": result.get("resource_name"),
                        "message": result.get("message", "Successfully applied")
                    })
                else:
                    applied_opt.status = 'failed'
                    applied_opt.error_message = result.get("error", "Unknown error")
                    failed_count += 1
                    results.append({
                        "optimization": opt_title,
                        "type": opt_type,
                        "status": "failed",
                        "error": result.get("error")
                    })

            except Exception as e:
                applied_opt.status = 'failed'
                applied_opt.error_message = str(e)
                failed_count += 1
                results.append({
                    "optimization": opt_title,
                    "type": opt_type,
                    "status": "failed",
                    "error": str(e)
                })
                current_app.logger.exception(f"Error applying optimization: {opt_title}")

        db.session.commit()

        # Clear cached ads data so next page load fetches fresh data with updated extensions/scores
        sess_key = f"ads_state_{aid}"
        if sess_key in session:
            del session[sess_key]
            current_app.logger.info(f"Cleared ads cache for account {aid} to refresh data after applying optimizations")

        current_app.logger.info(
            f"Account {aid} applied {applied_count}/{len(optimizations)} optimizations. {failed_count} failed."
        )

        return jsonify({
            "success": failed_count == 0,
            "message": f"Applied {applied_count}/{len(optimizations)} optimization(s). {failed_count} failed.",
            "applied_count": applied_count,
            "failed_count": failed_count,
            "results": results
        })

    except Exception as e:
        current_app.logger.exception("Error approving optimizations")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@google_bp.route("/ads/applied-optimizations", methods=["GET"], endpoint="applied_optimizations")
@login_required
def get_applied_optimizations():
    """
    Get history of applied optimizations for confirmation.
    Allows user to verify what changes were pushed to Google Ads.
    """
    try:
        from flask import jsonify
        from app.models_google import AppliedOptimization

        aid = current_account_id()
        customer_id = request.args.get("customer_id")
        status_filter = request.args.get("status")  # applied, failed, pending

        # Build query
        query = AppliedOptimization.query.filter_by(account_id=aid)

        if customer_id:
            query = query.filter_by(customer_id=customer_id)

        if status_filter:
            query = query.filter_by(status=status_filter)

        # Get recent optimizations (last 30 days)
        from datetime import datetime, timedelta
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)
        query = query.filter(AppliedOptimization.created_at >= thirty_days_ago)

        # Order by most recent first
        optimizations = query.order_by(AppliedOptimization.created_at.desc()).limit(100).all()

        # Format response
        results = []
        for opt in optimizations:
            results.append({
                "id": opt.id,
                "customer_id": opt.customer_id,
                "campaign_id": opt.campaign_id,
                "type": opt.optimization_type,
                "title": opt.optimization_title,
                "status": opt.status,
                "resource_name": opt.resource_name,
                "error": opt.error_message,
                "applied_at": opt.applied_at.isoformat() if opt.applied_at else None,
                "created_at": opt.created_at.isoformat(),
            })

        # Summary stats
        stats = {
            "total": len(results),
            "applied": sum(1 for r in results if r["status"] == "applied"),
            "failed": sum(1 for r in results if r["status"] == "failed"),
            "pending": sum(1 for r in results if r["status"] == "pending"),
        }

        return jsonify({
            "success": True,
            "optimizations": results,
            "stats": stats
        })

    except Exception as e:
        current_app.logger.exception("Error fetching applied optimizations")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@google_bp.route("/ads/mark-manual-task-complete", methods=["POST"], endpoint="mark_manual_task_complete")
@login_required
def mark_manual_task_complete():
    """
    Mark a manual task as complete so it doesn't appear in the list anymore.
    Stores completion status in database.
    """
    try:
        from flask import jsonify
        from app.models_google import CompletedManualTask
        from app import db

        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "No data provided"}), 400

        task_id = data.get("task_id")
        task_title = data.get("task_title")

        if not task_id or not task_title:
            return jsonify({"success": False, "error": "Task ID and title required"}), 400

        aid = current_account_id()
        customer_id = _get_saved_customer_id(aid)

        # Create completion record
        completed_task = CompletedManualTask(
            account_id=aid,
            user_id=current_user.id,
            customer_id=customer_id,
            task_id=task_id,
            task_title=task_title
        )
        db.session.add(completed_task)
        db.session.commit()

        current_app.logger.info(
            f"Manual task marked complete: account_id={aid}, task_id={task_id}, title={task_title}"
        )

        return jsonify({
            "success": True,
            "message": f"Task '{task_title}' marked as complete"
        })

    except Exception as e:
        current_app.logger.exception("Error marking manual task complete")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


def _run_ai_agents_for_opportunities(aid: int, ads_data: dict, customer_id: str = None, refresh_token: str = None) -> list:
    """
    Run all 8 AI agents (Strategic, Operational, Tactical) and convert their decisions
    into optimization opportunities for the ads UI.

    Returns: List of opportunity dictionaries compatible with the UI format.
    """
    opportunities = []

    try:
        # Import agents
        from app.agents import (
            StrategicDirectorAgent,
            CampaignManagerAgent,
            BudgetGuardianAgent,
            QualityScoreAgent,
            KeywordOptimizerAgent,
            NegativeKeywordAgent,
            AdCopyAgent,
            LandingPageAnalystAgent,
            EventBus,
            DecisionLog
        )

        # Initialize infrastructure
        event_bus = EventBus()
        decision_log = DecisionLog()

        # Prepare context for agents (convert ads_data to agent-compatible format)
        campaigns = ads_data.get("campaigns", [])
        keywords = ads_data.get("keywords", [])
        search_terms = ads_data.get("search_terms", [])
        ad_groups = ads_data.get("ad_groups", [])

        # Calculate performance metrics for agent context
        total_cost = sum(c.get("cost_30d", 0) or 0 for c in campaigns)
        total_clicks = sum(c.get("clicks", 0) or 0 for c in campaigns)
        total_conversions = sum(c.get("conversions", 0) or 0 for c in campaigns)

        context = {
            'account_id': aid,
            'customer_id': customer_id or '',
            'performance_90d': {
                'spend': total_cost * 3,  # Estimate 90-day from 30-day
                'conversions': total_conversions * 3,
                'cost_per_conversion': (total_cost / total_conversions) if total_conversions > 0 else 0,
            },
            'campaigns': [
                {
                    'id': str(c.get('id', '')),
                    'name': c.get('name', ''),
                    'roas': (c.get('conversions', 0) * 500) / c.get('cost_30d', 1) if c.get('cost_30d', 0) > 0 else 0,
                    'impression_share': c.get('impression_share', None),
                    'monthly_spend': c.get('cost_30d', 0),
                    'spend_90d': c.get('cost_30d', 0) * 3,
                    'conversions': c.get('conversions', 0),
                    'cpa': (c.get('cost_30d', 0) / c.get('conversions', 1)) if c.get('conversions', 0) > 0 else 0,
                    'cpl_7d': (c.get('cost_30d', 0) / 7) / max(c.get('conversions', 0), 1),
                    'conversion_rate_7d': (c.get('conversions', 0) / max(c.get('clicks', 1), 1)) * 100,
                }
                for c in campaigns
            ],
            'keywords': [
                {
                    'id': str(k.get('id', '')),
                    'text': k.get('text', ''),
                    'cpa_30d': k.get('cpa', 0),
                    'conversions_30d': k.get('conv', 0),
                    'spend_30d': k.get('cost', 0),
                }
                for k in keywords
            ],
            'search_terms': [
                {
                    'query': st.get('query', ''),
                    'cost': st.get('cost', 0),
                    'conversions': st.get('conversions', 0),
                    'cost_per_conversion': st.get('cpa', 0),
                }
                for st in search_terms
            ],
            'ad_groups': [
                {
                    'id': str(ag.get('id', '')),
                    'name': ag.get('name', ''),
                    'ads': ag.get('ads', []),
                    'avg_ctr': ag.get('ctr', 3.0),
                }
                for ag in ad_groups
            ],
            'total_budget': total_cost,
            'target_cpa': 100,  # Default target
            'business_goals': {
                'target_roas': 3.0,
                'target_cpl': 80,
                'customer_value': 500,
            }
        }

        # Initialize all 8 agents
        agents = [
            StrategicDirectorAgent(event_bus=event_bus, decision_log=decision_log),
            CampaignManagerAgent(event_bus=event_bus, decision_log=decision_log),
            BudgetGuardianAgent(event_bus=event_bus, decision_log=decision_log),
            QualityScoreAgent(event_bus=event_bus, decision_log=decision_log),
            KeywordOptimizerAgent(event_bus=event_bus, decision_log=decision_log),
            NegativeKeywordAgent(event_bus=event_bus, decision_log=decision_log),
            AdCopyAgent(event_bus=event_bus, decision_log=decision_log),
            LandingPageAnalystAgent(event_bus=event_bus, decision_log=decision_log),
        ]

        # Run each agent and collect opportunities
        for agent in agents:
            try:
                # Each agent runs analyze() -> decide() cycle
                agent_opportunities = agent.analyze(context)
                agent_decisions = agent.decide(agent_opportunities)

                # Convert agent decisions to UI-compatible opportunities
                for decision in agent_decisions:
                    # Map agent decision to opportunity format
                    opportunity = {
                        'title': decision.title,
                        'description': decision.description,
                        'priority': _map_risk_to_priority(decision.risk_level),
                        'impact_score': int((1 - decision.confidence) * 100) if decision.confidence else 50,
                        'category': agent.agent_type,
                        'icon': _get_agent_icon(agent.agent_type),
                        'color': _get_agent_color(agent.agent_type),
                        'action': decision.description,
                        'estimated_time': '15 min' if decision.requires_approval == False else '30 min',
                        'quick_win': decision.requires_approval == False and decision.risk_level == 'low',
                        'confidence_score': int(decision.confidence * 100),
                        'risk_level': decision.risk_level,
                        'benefit_explanation': decision.reasoning,
                        'optimization_type': decision.decision_type,
                        'optimization_data': {
                            'agent_id': decision.agent_id,
                            'decision_id': decision.decision_id,
                            'campaign_id': decision.campaign_id,
                            'ad_group_id': decision.ad_group_id,
                            'action_data': decision.action_data,
                            'requires_approval': decision.requires_approval,
                        },
                        'agent_generated': True,
                    }

                    # Add financial metrics if available
                    if decision.expected_monthly_savings:
                        opportunity['monthly_savings'] = decision.expected_monthly_savings
                        opportunity['annual_savings'] = decision.expected_monthly_savings * 12

                    if decision.expected_monthly_leads:
                        opportunity['monthly_leads'] = decision.expected_monthly_leads
                        opportunity['annual_leads'] = decision.expected_monthly_leads * 12

                    opportunities.append(opportunity)

                current_app.logger.info(f"Agent {agent.agent_id} generated {len(agent_decisions)} opportunities")

            except Exception as e:
                current_app.logger.error(f"Error running agent {agent.agent_id}: {e}", exc_info=True)
                continue

        current_app.logger.info(f"AI Agents generated {len(opportunities)} total opportunities for account {aid}")

    except ImportError as e:
        current_app.logger.warning(f"AI Agents not available: {e}")
    except Exception as e:
        current_app.logger.error(f"Error running AI agents: {e}", exc_info=True)

    return opportunities


def _map_risk_to_priority(risk_level: str) -> str:
    """Map agent risk level to UI priority."""
    mapping = {
        'low': 'high',      # Low risk = high priority (can execute safely)
        'medium': 'medium',
        'high': 'low',      # High risk = low priority (needs careful review)
        'critical': 'high', # Critical issues = high priority
    }
    return mapping.get(risk_level, 'medium')


def _get_agent_icon(agent_type: str) -> str:
    """Get FontAwesome icon for agent type."""
    icons = {
        'strategic': 'fa-chess-king',
        'operational': 'fa-gauge-high',
        'campaign_manager': 'fa-chart-line',
        'budget_guardian': 'fa-shield-halved',
        'quality_score_doctor': 'fa-star',
        'keyword_optimizer': 'fa-key',
        'negative_keyword_agent': 'fa-ban',
        'ad_copy_scientist': 'fa-pen-to-square',
        'landing_page_analyst': 'fa-desktop',
    }
    return icons.get(agent_type, 'fa-robot')


def _get_agent_color(agent_type: str) -> str:
    """Get color for agent type."""
    colors = {
        'strategic': 'purple',
        'operational': 'blue',
        'campaign_manager': 'blue',
        'budget_guardian': 'red',
        'quality_score_doctor': 'yellow',
        'keyword_optimizer': 'green',
        'negative_keyword_agent': 'red',
        'ad_copy_scientist': 'purple',
        'landing_page_analyst': 'orange',
    }
    return colors.get(agent_type, 'gray')


def _analyze_ads_opportunities(aid: int, ads_data: dict) -> dict:
    """
    Comprehensive analysis of Google Ads account to identify opportunities.
    Uses 8 AI agents (Strategic, Operational, Tactical) plus rule-based analysis.
    Returns scores, top opportunities, and categorized recommendations.
    """
    campaigns = ads_data.get("campaigns", [])
    ad_groups = ads_data.get("ad_groups", [])
    keywords = ads_data.get("keywords", [])
    negatives = ads_data.get("negatives", [])
    ads = ads_data.get("ads", [])
    extensions = ads_data.get("extensions", [])

    # Calculate performance metrics from REAL campaign data
    enabled_campaigns = [c for c in campaigns if c.get("status", "").lower() in ("enabled", "active")]

    # Debug logging for campaign data
    current_app.logger.info(
        f"_analyze_ads_opportunities: aid={aid}, "
        f"total_campaigns={len(campaigns)}, "
        f"enabled_campaigns={len(enabled_campaigns)}, "
        f"campaigns_with_ids={len([c for c in campaigns if c.get('id')])}, "
        f"sample_campaign_keys={list(campaigns[0].keys()) if campaigns else []}"
    )

    # Use real metrics from campaigns if available (fetched from Google Ads API)
    total_cost = sum(c.get("cost_30d", 0) or 0 for c in campaigns)
    total_clicks = sum(c.get("clicks", 0) or 0 for c in campaigns)
    total_impressions = sum(c.get("impressions", 0) or 0 for c in campaigns)
    total_conversions = sum(c.get("conversions", 0) or 0 for c in campaigns)

    # Fall back to keyword-level data if campaign data is missing
    if total_conversions == 0:
        total_conversions = sum(k.get("conv", 0) or 0 for k in keywords)

    # Calculate daily/monthly spend from real data or budgets
    if total_cost > 0:
        monthly_spend = total_cost  # Already 30-day data
        daily_spend = total_cost / 30
    else:
        daily_spend = sum(c.get("daily_budget", 0) or 0 for c in enabled_campaigns)
        monthly_spend = daily_spend * 30

    # Use REAL metrics when available, fall back to industry benchmarks for new accounts
    has_historical_data = total_clicks > 0 and total_impressions > 0

    if has_historical_data:
        # Calculate from actual data
        avg_cpc = total_cost / total_clicks if total_clicks > 0 else 4.0
        avg_ctr = total_clicks / total_impressions if total_impressions > 0 else 0.04
        estimated_clicks = total_clicks
        estimated_impressions = total_impressions
    else:
        # NEW ACCOUNT or no data - use industry best practice benchmarks
        # Home services industry averages (based on Google Ads benchmarks 2024)
        avg_cpc = 4.50  # Home services avg CPC
        avg_ctr = 0.035  # 3.5% CTR industry average
        estimated_clicks = int(monthly_spend / avg_cpc) if monthly_spend > 0 else 0
        estimated_impressions = int(estimated_clicks / avg_ctr) if estimated_clicks > 0 else 0

    cost_per_conversion = (monthly_spend / total_conversions) if total_conversions > 0 else 0
    conversion_rate = (total_conversions / total_clicks) if total_clicks > 0 else 0.03  # 3% industry avg

    performance = {
        "monthly_spend": monthly_spend,
        "daily_spend": daily_spend,
        "impressions": estimated_impressions,
        "clicks": estimated_clicks,
        "ctr": avg_ctr,
        "conversions": total_conversions,
        "cost_per_conversion": cost_per_conversion,
        "conversion_rate": conversion_rate,
        "has_historical_data": has_historical_data,
    }

    # Calculate health scores (0-100)
    scores = {
        "overall": 0,
        "wasted_spend": 0,
        "quality_score": 0,
        "ctr": 0,
        "account_structure": 0,
        "mobile": 0,
        "extensions": 0,
    }

    # ========== WASTED SPEND SCORE ==========
    # Based on negative keyword coverage AND search term analysis
    if len(keywords) > 0:
        neg_ratio = len(negatives) / max(len(keywords), 1)
        # Perfect = 2.5 negatives per keyword (ratio of 2.5)
        base_score = min(100, int((neg_ratio / 2.5) * 100))

        # Bonus points if they have good negative keyword lists
        if neg_ratio >= 2.0:
            base_score = min(100, base_score + 10)

        scores["wasted_spend"] = base_score
    else:
        # No keywords = new account, give benefit of doubt but flag for setup
        scores["wasted_spend"] = 40  # Needs attention

    # ========== QUALITY SCORE ==========
    # Use real CPA data if available, otherwise estimate based on industry benchmarks
    if has_historical_data and total_conversions > 0:
        # Calculate from actual keyword performance
        keywords_with_conversions = [k for k in keywords if (k.get("conv", 0) or 0) > 0]
        if keywords_with_conversions:
            avg_keyword_cpa = sum(k.get("cpa", 0) or 0 for k in keywords_with_conversions) / len(keywords_with_conversions)
            # Industry benchmark: $50-80 CPA for home services is average
            # Lower CPA = higher QS, Higher CPA = lower QS
            if avg_keyword_cpa <= 40:
                scores["quality_score"] = 85  # Excellent
            elif avg_keyword_cpa <= 60:
                scores["quality_score"] = 70  # Good
            elif avg_keyword_cpa <= 80:
                scores["quality_score"] = 55  # Average
            elif avg_keyword_cpa <= 100:
                scores["quality_score"] = 40  # Below average
            else:
                scores["quality_score"] = 30  # Poor
        else:
            scores["quality_score"] = 50  # No conversion data
    else:
        # NEW ACCOUNT - score based on account structure (proxy for QS potential)
        if len(keywords) > 0 and len(ads) > 0:
            scores["quality_score"] = 60  # Has basics set up
        elif len(keywords) > 0:
            scores["quality_score"] = 45  # Keywords but needs ads
        else:
            scores["quality_score"] = 35  # Needs full setup

    # ========== CTR SCORE ==========
    # Use REAL CTR data when available
    if has_historical_data and avg_ctr > 0:
        # Industry benchmark CTR by vertical (home services: 3.5-5% is good)
        if avg_ctr >= 0.06:
            scores["ctr"] = 90  # Excellent (6%+)
        elif avg_ctr >= 0.05:
            scores["ctr"] = 80  # Very good (5-6%)
        elif avg_ctr >= 0.04:
            scores["ctr"] = 70  # Good (4-5%)
        elif avg_ctr >= 0.03:
            scores["ctr"] = 55  # Average (3-4%)
        elif avg_ctr >= 0.02:
            scores["ctr"] = 40  # Below average (2-3%)
        else:
            scores["ctr"] = 25  # Poor (<2%)
    else:
        # NEW ACCOUNT - score based on ad copy quality indicators
        if len(ads) >= 3:
            scores["ctr"] = 60  # Multiple ads for testing
        elif len(ads) >= 1:
            scores["ctr"] = 45  # Has ads
        else:
            scores["ctr"] = 30  # Needs ads

    # ========== ACCOUNT STRUCTURE SCORE ==========
    enabled_campaigns_count = sum(1 for c in campaigns if c.get("status", "").lower() == "enabled")
    ads_per_group = len(ads) / max(1, len(ad_groups))
    keywords_per_group = len(keywords) / max(1, len(ad_groups))

    structure_score = 40  # Base score
    # Campaign organization
    if 2 <= enabled_campaigns_count <= 10:
        structure_score += 15  # Good campaign structure
    elif enabled_campaigns_count == 1:
        structure_score += 5   # Single campaign is ok for small accounts

    # Ads per ad group (best practice: 3-5 RSAs)
    if 3 <= ads_per_group <= 5:
        structure_score += 20  # Optimal
    elif 2 <= ads_per_group < 3:
        structure_score += 10  # Acceptable
    elif ads_per_group >= 1:
        structure_score += 5   # Needs more ads

    # Keywords per ad group (best practice: 5-20)
    if 5 <= keywords_per_group <= 20:
        structure_score += 20  # Optimal tight themes
    elif 3 <= keywords_per_group < 5:
        structure_score += 10  # Acceptable
    elif keywords_per_group > 20:
        structure_score += 0   # Too broad - needs restructuring
    elif keywords_per_group >= 1:
        structure_score += 5   # Sparse but exists

    scores["account_structure"] = min(100, structure_score)

    # ========== MOBILE SCORE ==========
    # Check for mobile bid adjustments and mobile-specific setup
    # Since we can't directly fetch device data yet, score based on best practice indicators
    has_mobile_indicators = False

    # Check if any campaign has mobile-specific settings (from campaign data)
    for campaign in campaigns:
        # Look for mobile bid adjustments in campaign data
        if campaign.get("mobile_bid_adjustment"):
            has_mobile_indicators = True
            break

    if has_mobile_indicators:
        scores["mobile"] = 75  # Has mobile optimization
    else:
        # Check ad count as proxy (more ads = likely has mobile variations)
        if ads_per_group >= 3:
            scores["mobile"] = 55  # Multiple ads may include mobile-optimized
        elif len(extensions) >= 2 and any(e.get("type") == "call" for e in extensions):
            scores["mobile"] = 50  # Has call extension (mobile-friendly)
        else:
            scores["mobile"] = 35  # Needs mobile optimization

    current_app.logger.info(
        f"Mobile scoring: has_mobile_indicators={has_mobile_indicators}, "
        f"ads_per_group={ads_per_group}, "
        f"extensions_count={len(extensions)}, "
        f"mobile_score={scores['mobile']}"
    )

    # ========== EXTENSIONS SCORE ==========
    # Score based on number and types of extensions (critical for service businesses)
    extension_types = set(e.get("type", "").lower() for e in extensions)
    critical_extensions = {"call", "sitelink", "callout", "location"}
    has_critical = len(extension_types & critical_extensions)

    if len(extensions) >= 5 and has_critical >= 3:
        scores["extensions"] = 95  # Excellent
    elif len(extensions) >= 4 and has_critical >= 2:
        scores["extensions"] = 80  # Very good
    elif len(extensions) >= 3:
        scores["extensions"] = 65  # Good
    elif len(extensions) >= 2:
        scores["extensions"] = 50  # Acceptable
    elif len(extensions) >= 1:
        scores["extensions"] = 35  # Needs more
    else:
        scores["extensions"] = 15  # Critical - no extensions

    # Calculate overall score (weighted average)
    scores["overall"] = int(
        scores["wasted_spend"] * 0.25 +
        scores["quality_score"] * 0.25 +
        scores["ctr"] * 0.15 +
        scores["account_structure"] * 0.15 +
        scores["mobile"] * 0.10 +
        scores["extensions"] * 0.10
    )

    # Generate grade
    if scores["overall"] >= 90:
        grade = "A+"
    elif scores["overall"] >= 85:
        grade = "A"
    elif scores["overall"] >= 80:
        grade = "A-"
    elif scores["overall"] >= 75:
        grade = "B+"
    elif scores["overall"] >= 70:
        grade = "B"
    elif scores["overall"] >= 65:
        grade = "B-"
    elif scores["overall"] >= 60:
        grade = "C+"
    elif scores["overall"] >= 55:
        grade = "C"
    elif scores["overall"] >= 50:
        grade = "C-"
    elif scores["overall"] >= 45:
        grade = "D+"
    elif scores["overall"] >= 40:
        grade = "D"
    else:
        grade = "F"

    # Generate top opportunities with ROI projections - GRANULAR LINE ITEMS
    # Use REAL account data for calculations
    opportunities = []

    # Calculate base metrics for scaling
    total_monthly_spend = monthly_spend or 1000  # Fallback for calculations
    avg_cpc = total_monthly_spend / max(estimated_clicks, 1) if estimated_clicks > 0 else 4.0
    conversion_rate = (total_conversions / max(estimated_clicks, 1)) if estimated_clicks > 0 else 0.03

    # Negative Keywords - Generate from search term patterns or estimate based on spend
    # Industry benchmark: 5-8% of spend is typically wasted on irrelevant terms
    if scores["wasted_spend"] < 70:
        estimated_waste_pct = max(0.05, (100 - scores["wasted_spend"]) / 100 * 0.15)  # 5-15% waste based on score
        total_estimated_waste = total_monthly_spend * estimated_waste_pct

        # Common negative keyword suggestions scaled to account spend
        negative_suggestions = [
            {"term": "jobs", "waste_pct": 0.25, "relevance": "career seekers, not customers"},
            {"term": "careers", "waste_pct": 0.15, "relevance": "job seekers looking for employment"},
            {"term": "DIY", "waste_pct": 0.13, "relevance": "do-it-yourself searchers won't hire"},
            {"term": "how to", "waste_pct": 0.12, "relevance": "informational searches, not purchase intent"},
            {"term": "free", "waste_pct": 0.10, "relevance": "bargain hunters unlikely to convert"},
            {"term": "cheap", "waste_pct": 0.08, "relevance": "price-focused, low-value customers"},
            {"term": "training", "waste_pct": 0.05, "relevance": "students/learners, not buyers"},
            {"term": "salary", "waste_pct": 0.03, "relevance": "job seekers researching pay"},
        ]

        neg_opps_created = 0
        neg_opps_skipped_no_campaign = 0
        neg_opps_skipped_too_small = 0

        for neg in negative_suggestions:
            estimated_waste = total_estimated_waste * neg["waste_pct"]
            if estimated_waste < 10:  # Skip if savings too small
                neg_opps_skipped_too_small += 1
                continue

            estimated_clicks_wasted = int(estimated_waste / avg_cpc)
            campaign_names = [c.get("name", "Campaign") for c in campaigns[:2]] if campaigns else ["All Campaigns"]
            # Get first enabled campaign ID for applying the optimization
            first_campaign_id = next((c.get("id") for c in campaigns if c.get("status", "").lower() in ("enabled", "active")),
                                    campaigns[0].get("id") if campaigns else None)

            # Skip if no campaign available to apply to
            if not first_campaign_id:
                neg_opps_skipped_no_campaign += 1
                continue

            neg_opps_created += 1

            opportunities.append({
                "title": f"Add negative keyword: \"{neg['term']}\"",
                "description": f"Block '{neg['term']}' searches - {neg['relevance']} (est. {estimated_clicks_wasted} wasted clicks/mo)",
                "priority": "high" if estimated_waste > total_monthly_spend * 0.02 else "medium",
                "impact_score": min(100, int((neg["waste_pct"] / 0.25) * 100)),
                "monthly_savings": round(estimated_waste, 0),
                "annual_savings": round(estimated_waste * 12, 0),
                "icon": "fa-ban",
                "color": "red",
                "category": "negative_keyword",
                "action": f"Add '{neg['term']}' as negative keyword to {', '.join(campaign_names[:2])}",
                "estimated_time": "5 min",
                "quick_win": True,
                "confidence_score": 92,
                "risk_level": "low",
                "before_state": f"'{neg['term']}' triggering ads, wasting ~${estimated_waste:.0f}/mo on {estimated_clicks_wasted} irrelevant clicks",
                "after_state": f"'{neg['term']}' blocked, saving ${estimated_waste:.0f}/mo to reinvest in converting traffic",
                "success_metrics": [f"Block {estimated_clicks_wasted} irrelevant clicks", f"Save ${estimated_waste:.0f}/month", "Improve conversion rate"],
                "optimization_type": "negative_keyword",
                "optimization_data": {
                    "term": neg["term"],
                    "estimated_waste": estimated_waste,
                    "clicks": estimated_clicks_wasted,
                    "cpc": avg_cpc,
                    "campaign_id": first_campaign_id
                },
            })

        current_app.logger.info(
            f"Negative keywords: total_estimated_waste=${total_estimated_waste:.2f}, "
            f"created={neg_opps_created}, "
            f"skipped_too_small={neg_opps_skipped_too_small}, "
            f"skipped_no_campaign={neg_opps_skipped_no_campaign}"
        )

    # Ad Extensions - Create individual line item for each extension type
    # Calculate potential leads based on REAL traffic volume
    # CTR lift translates to more clicks → more conversions at current conversion rate
    if scores["extensions"] < 70:
        extension_opportunities = []
        base_monthly_clicks = estimated_clicks or 500

        # Call extensions - HIGHEST impact for service business (mobile-heavy)
        if len([e for e in extensions if e.get("type") == "call"]) == 0:
            ctr_lift = 0.20  # 20% average CTR lift
            additional_clicks = int(base_monthly_clicks * ctr_lift)
            additional_leads = max(1, int(additional_clicks * conversion_rate))
            extension_opportunities.append({
                "type": "Call Extensions",
                "ctr_lift": "15-25%",
                "leads_per_month": additional_leads,
                "additional_clicks": additional_clicks,
                "time": "10 min",
                "description": f"Add click-to-call button to mobile ads - drives {additional_clicks} more clicks/mo at your {conversion_rate*100:.1f}% conversion rate",
                "example": "Call Now: (555) 123-4567",
                "order": 1,
                "benefit": "Direct phone calls convert 3x better than form fills. Mobile users expect tap-to-call."
            })

        # Sitelinks - Second highest, compounds with call extensions
        if len([e for e in extensions if e.get("type") == "sitelink"]) == 0:
            ctr_lift = 0.12  # 12% average CTR lift
            additional_clicks = int(base_monthly_clicks * ctr_lift)
            additional_leads = max(1, int(additional_clicks * conversion_rate))
            extension_opportunities.append({
                "type": "Sitelinks",
                "ctr_lift": "10-15%",
                "leads_per_month": additional_leads,
                "additional_clicks": additional_clicks,
                "time": "20 min",
                "description": f"Add 4-6 quick links below your ads - drives {additional_clicks} more targeted clicks/mo",
                "example": "24/7 Emergency | Same Day Service | Free Estimate | Pricing",
                "order": 2,
                "benefit": "Sitelinks take up more ad space, pushing competitors down. Users find relevant pages faster."
            })

        # Callouts - Moderate impact, diminishing returns starting
        if len([e for e in extensions if e.get("type") == "callout"]) == 0:
            ctr_lift = 0.08  # 8% average CTR lift
            additional_clicks = int(base_monthly_clicks * ctr_lift)
            additional_leads = max(1, int(additional_clicks * conversion_rate))
            extension_opportunities.append({
                "type": "Callouts",
                "ctr_lift": "6-10%",
                "leads_per_month": additional_leads,
                "additional_clicks": additional_clicks,
                "time": "15 min",
                "description": f"Highlight USPs like 'Licensed & Insured' - adds {additional_clicks} more clicks/mo",
                "example": "Licensed & Insured • 20+ Years Experience • 5-Star Rated • Same Day",
                "order": 3,
                "benefit": "Builds trust and differentiates from competitors. No extra cost for these clicks."
            })

        # Location - Good for local business
        if len([e for e in extensions if e.get("type") == "location"]) == 0:
            ctr_lift = 0.05  # 5% average CTR lift
            additional_clicks = int(base_monthly_clicks * ctr_lift)
            additional_leads = max(1, int(additional_clicks * conversion_rate))
            extension_opportunities.append({
                "type": "Location Extensions",
                "ctr_lift": "4-7%",
                "leads_per_month": additional_leads,
                "additional_clicks": additional_clicks,
                "time": "10 min",
                "description": f"Show your address and 'Get Directions' link - {additional_clicks} more local clicks/mo",
                "example": "123 Main St, City • Open Now • Get Directions",
                "order": 4,
                "benefit": "Local searchers trust businesses with visible addresses. Drives foot traffic and calls."
            })

        # Structured Snippets - Minimal incremental value
        if len([e for e in extensions if e.get("type") == "structured_snippet"]) == 0:
            ctr_lift = 0.03  # 3% average CTR lift
            additional_clicks = int(base_monthly_clicks * ctr_lift)
            additional_leads = max(1, int(additional_clicks * conversion_rate))
            extension_opportunities.append({
                "type": "Structured Snippets",
                "ctr_lift": "2-4%",
                "leads_per_month": additional_leads,
                "additional_clicks": additional_clicks,
                "time": "15 min",
                "description": f"List your services or specialties - {additional_clicks} more clicks/mo",
                "example": "Services: Repairs, Installation, Maintenance, Emergency, Inspection",
                "order": 5,
                "benefit": "Pre-qualifies traffic by showing exactly what you offer before they click."
            })

        for ext in extension_opportunities:
            # Calculate financial value of additional leads
            lead_value = cost_per_conversion if cost_per_conversion > 0 else (total_monthly_spend / max(total_conversions, 1))
            monthly_value = ext["leads_per_month"] * lead_value if lead_value > 0 else ext["leads_per_month"] * 100

            opportunities.append({
                "title": f"Add {ext['type']}",
                "description": ext["description"],
                "priority": "high" if ext["leads_per_month"] >= max(1, int(total_conversions * 0.15)) else "medium",
                "impact_score": min(100, int((ext.get("order", 5) / 5) * 100)),
                "monthly_leads": ext["leads_per_month"],
                "annual_leads": ext["leads_per_month"] * 12,
                "monthly_value": round(monthly_value, 0),
                "icon": "fa-puzzle-piece",
                "color": "blue",
                "category": "extension",
                "action": f"Enable {ext['type']} for all campaigns",
                "estimated_time": ext["time"],
                "quick_win": True,
                "confidence_score": 95 if ext.get("order", 5) <= 2 else 85,
                "risk_level": "low",
                "before_state": f"No {ext['type']} enabled - missing {ext['additional_clicks']} clicks/mo",
                "after_state": f"{ext['type']} active, CTR up {ext['ctr_lift']}, +{ext['leads_per_month']} leads/mo",
                "success_metrics": [f"CTR increase of {ext['ctr_lift']}", f"+{ext['leads_per_month']} leads/mo", f"~${monthly_value:.0f}/mo value"],
                "benefit_explanation": ext.get("benefit", ""),
                "optimization_type": "extension",
                "optimization_data": ext,
            })

    # Quality Score - Use REAL keyword data from account
    # Each QS point improvement reduces CPC by ~6-8%
    if scores["quality_score"] < 75 and keywords:
        # Analyze actual keywords with cost data
        keywords_with_cost = [k for k in keywords if k.get("cpa") and k.get("cpa") > 0]

        if keywords_with_cost:
            # Sort by cost (highest spend keywords have most impact)
            keywords_with_cost.sort(key=lambda x: (x.get("cpa", 0) or 0) * (x.get("conv", 0) or 0), reverse=True)

            for kw in keywords_with_cost[:5]:  # Top 5 highest-spend keywords
                kw_cpc = kw.get("cpc") or avg_cpc
                kw_cpa = kw.get("cpa") or cost_per_conversion
                kw_conversions = kw.get("conv", 0) or 0
                kw_text = kw.get("text", "keyword")

                # Estimate current QS based on CPA (higher CPA often correlates with lower QS)
                if kw_cpa > cost_per_conversion * 1.5:
                    estimated_qs = 4
                elif kw_cpa > cost_per_conversion * 1.2:
                    estimated_qs = 5
                elif kw_cpa > cost_per_conversion:
                    estimated_qs = 6
                else:
                    estimated_qs = 7

                # Calculate potential savings from QS improvement
                target_qs = 8
                qs_improvement = target_qs - estimated_qs
                cpc_reduction_pct = qs_improvement * 6  # ~6% per QS point

                monthly_keyword_spend = kw_cpa * kw_conversions if kw_conversions > 0 else kw_cpc * 50
                monthly_savings = monthly_keyword_spend * (cpc_reduction_pct / 100)

                if monthly_savings < 20:  # Skip if savings too small
                    continue

                opportunities.append({
                    "title": f"Improve Quality Score for \"{kw_text}\"",
                    "description": f"This keyword has higher-than-average CPA (${kw_cpa:.2f}) - improving ad relevance and landing page can reduce costs significantly",
                    "priority": "high" if estimated_qs <= 5 else "medium",
                    "impact_score": min(100, int((monthly_savings / (total_monthly_spend * 0.1)) * 100)),
                    "monthly_savings": round(monthly_savings, 0),
                    "annual_savings": round(monthly_savings * 12, 0),
                    "icon": "fa-star",
                    "color": "yellow",
                    "category": "quality_score",
                    "action": f"Improve ad copy relevance and landing page for '{kw_text}'",
                    "estimated_time": "45 min",
                    "quick_win": False,
                    "confidence_score": 78,
                    "risk_level": "medium",
                    "before_state": f"Est. QS: {estimated_qs}/10, CPA: ${kw_cpa:.2f}, {kw_conversions} conversions/mo",
                    "after_state": f"QS: 8/10, CPA reduced by ~{cpc_reduction_pct:.0f}%, save ${monthly_savings:.0f}/mo",
                    "success_metrics": [f"QS increased to 8/10", f"CPA reduced by {cpc_reduction_pct:.0f}%", f"Save ${monthly_savings:.0f}/month"],
                    "benefit_explanation": "Quality Score directly impacts your ad position and cost-per-click. Higher QS = lower CPCs and better positions.",
                    "optimization_type": "quality_score",
                    "optimization_data": {"keyword": kw_text, "estimated_qs": estimated_qs, "cpa": kw_cpa, "potential_savings": monthly_savings},
                })

    # Mobile Optimization - Calculate based on actual traffic
    # Mobile typically represents 60%+ of local service searches
    if scores["mobile"] < 70:
        # Estimate mobile portion of traffic (industry avg is 60%)
        estimated_mobile_clicks = int(estimated_clicks * 0.60)
        mobile_conversion_boost = 0.25  # 25% more mobile traffic with bid adjustment
        additional_mobile_clicks = int(estimated_mobile_clicks * mobile_conversion_boost)
        additional_mobile_leads = max(1, int(additional_mobile_clicks * conversion_rate))
        lead_value = cost_per_conversion if cost_per_conversion > 0 else 100

        # Get first enabled campaign ID for applying the optimization
        first_campaign_id = next((c.get("id") for c in campaigns if c.get("status", "").lower() in ("enabled", "active")),
                                campaigns[0].get("id") if campaigns else None)

        current_app.logger.info(
            f"Mobile optimization: scores[mobile]={scores['mobile']}, "
            f"first_campaign_id={first_campaign_id}, "
            f"will_create_mobile_bid_opp={bool(first_campaign_id)}"
        )

        # Skip mobile bid optimization if no campaign available
        if first_campaign_id:
            # Mobile bid adjustment - Do this FIRST
            opportunities.append({
                "title": "Add +20% mobile bid adjustment",
                "description": f"Your account gets ~{estimated_mobile_clicks:,} mobile clicks/mo. A +20% bid adjustment could capture {additional_mobile_clicks} more clicks → {additional_mobile_leads} more leads",
                "priority": "high" if additional_mobile_leads >= 3 else "medium",
                "impact_score": 70,
                "monthly_leads": additional_mobile_leads,
                "annual_leads": additional_mobile_leads * 12,
                "monthly_value": round(additional_mobile_leads * lead_value, 0),
                "icon": "fa-mobile-screen",
                "color": "green",
                "category": "mobile",
                "action": "Set mobile bid modifier to +20% for all campaigns",
                "estimated_time": "10 min",
                "quick_win": True,
                "confidence_score": 85,
                "risk_level": "low",
                "before_state": f"Mobile bids at 0%, ~{estimated_mobile_clicks:,} mobile clicks/mo",
                "after_state": f"Mobile bids +20%, +{additional_mobile_clicks} clicks/mo → +{additional_mobile_leads} leads",
                "success_metrics": [f"+{additional_mobile_clicks} mobile clicks/mo", f"+{additional_mobile_leads} leads/mo", f"~${additional_mobile_leads * lead_value:.0f}/mo value"],
                "benefit_explanation": "60% of local service searches happen on mobile. Higher bids = better ad position = more calls. Mobile users have higher purchase intent.",
                "optimization_type": "mobile_bid",
                "optimization_data": {
                    "bid_adjustment": 20,
                    "estimated_mobile_clicks": estimated_mobile_clicks,
                    "campaign_id": first_campaign_id
                },
            })

        # Mobile-preferred ads - Compounds with bid adjustment
        mobile_ctr_boost = 0.12  # 12% CTR improvement
        mobile_ad_clicks = int(estimated_mobile_clicks * mobile_ctr_boost)
        mobile_ad_leads = max(1, int(mobile_ad_clicks * conversion_rate))

        opportunities.append({
            "title": "Create mobile-optimized RSA ads",
            "description": f"Mobile-specific headlines and CTAs can boost CTR by 12% → {mobile_ad_clicks} more clicks → {mobile_ad_leads} more leads",
            "priority": "medium",
            "impact_score": 50,
            "monthly_leads": mobile_ad_leads,
            "annual_leads": mobile_ad_leads * 12,
            "monthly_value": round(mobile_ad_leads * lead_value, 0),
            "icon": "fa-mobile-screen",
            "color": "green",
            "category": "mobile",
            "action": "Create 3-5 RSA variations with mobile-focused headlines and tap-to-call CTAs",
            "estimated_time": "30 min",
            "quick_win": False,
            "confidence_score": 75,
            "risk_level": "low",
            "before_state": "Same generic ads shown on all devices",
            "after_state": f"Mobile-optimized ads with urgent CTAs, +{mobile_ad_leads} leads/mo",
            "success_metrics": [f"Mobile CTR up {mobile_ctr_boost*100:.0f}%", f"+{mobile_ad_leads} leads/mo", f"~${mobile_ad_leads * lead_value:.0f}/mo value"],
            "benefit_explanation": "Mobile users skim ads quickly. Shorter headlines, urgency words ('Call Now', 'Same Day'), and tap-to-call convert better than desktop-style ads.",
            "optimization_type": "mobile_ads",
            "optimization_data": {"ad_count": 5, "ctr_boost": mobile_ctr_boost, "compounds_with": "mobile_bid"},
        })

    # Account Structure - Calculate benefits based on actual account metrics
    if scores["account_structure"] < 70:
        num_campaigns = len(campaigns)
        num_ad_groups = len(ad_groups)
        num_keywords = len(keywords)
        keywords_per_group = num_keywords // max(num_ad_groups, 1)
        ads_per_group = len(ads) // max(num_ad_groups, 1)

        # Calculate structure issues and financial impact
        structure_issues = []
        estimated_efficiency_gain = 0

        # Check keywords per ad group (ideal: 5-15)
        if keywords_per_group > 20:
            structure_issues.append(f"Too many keywords per ad group ({keywords_per_group} avg) - reduces ad relevance")
            estimated_efficiency_gain += 0.08  # 8% efficiency gain from better organization
        elif keywords_per_group < 3:
            structure_issues.append(f"Too few keywords per ad group ({keywords_per_group} avg) - inefficient structure")
            estimated_efficiency_gain += 0.05

        # Check ads per ad group (ideal: 3-5 RSAs)
        if ads_per_group < 2:
            structure_issues.append(f"Only {ads_per_group} ad(s) per ad group - need 3+ RSAs for proper testing")
            estimated_efficiency_gain += 0.10  # 10% improvement from proper ad testing

        # Check campaign count vs spend
        spend_per_campaign = total_monthly_spend / max(num_campaigns, 1)
        if spend_per_campaign < 300 and num_campaigns > 3:
            structure_issues.append(f"Budget spread too thin (${spend_per_campaign:.0f}/campaign) - consolidate for better optimization")
            estimated_efficiency_gain += 0.12

        # Calculate financial impact
        potential_monthly_savings = total_monthly_spend * estimated_efficiency_gain
        time_saved_hours = max(2, num_campaigns + num_ad_groups // 5)  # More campaigns = more time saved

        description_parts = []
        if structure_issues:
            description_parts.append("Issues found: " + "; ".join(structure_issues[:2]))
        description_parts.append(f"Restructuring could improve efficiency by {estimated_efficiency_gain*100:.0f}%")

        opportunities.append({
            "title": "Reorganize account structure",
            "description": " ".join(description_parts),
            "priority": "medium" if potential_monthly_savings > 200 else "low",
            "impact_score": min(80, int(estimated_efficiency_gain * 500)),
            "monthly_savings": round(potential_monthly_savings, 0),
            "annual_savings": round(potential_monthly_savings * 12, 0),
            "monthly_time_saved": time_saved_hours,
            "icon": "fa-folder-tree",
            "color": "purple",
            "category": "account_structure",
            "action": "Reorganize campaigns by service type with 5-15 tightly themed keywords per ad group",
            "estimated_time": f"{max(2, num_campaigns)} hours",
            "quick_win": False,
            "confidence_score": 72,
            "risk_level": "medium",
            "before_state": f"{num_campaigns} campaigns, {num_ad_groups} ad groups, {keywords_per_group} keywords/group, {ads_per_group} ads/group",
            "after_state": f"Organized by service type, 5-15 keywords per ad group, 3+ RSAs per group",
            "success_metrics": [
                f"~${potential_monthly_savings:.0f}/mo efficiency gain",
                f"Save {time_saved_hours}+ hours/mo on management",
                "Higher Quality Scores from better ad relevance"
            ],
            "benefit_explanation": """**Why Account Structure Matters:**
• **Ad Relevance**: Tightly themed ad groups (5-15 related keywords) allow you to write highly specific ads → higher CTR → lower CPCs
• **Quality Score**: Google rewards relevant ad-to-keyword matches with higher QS → better ad positions at lower cost
• **Easier Optimization**: Finding underperformers is easier when campaigns are organized by service/intent
• **Budget Control**: Separate campaigns for high-intent vs research keywords lets you allocate budget strategically
• **Testing Efficiency**: 3+ RSAs per ad group enables proper A/B testing to find winning messages""",
            "structure_issues": structure_issues,
            "optimization_type": "account_structure",
            "optimization_data": {
                "current_campaigns": num_campaigns,
                "current_ad_groups": num_ad_groups,
                "keywords_per_group": keywords_per_group,
                "ads_per_group": ads_per_group,
                "estimated_efficiency_gain": estimated_efficiency_gain,
            },
        })

    # ========== COMPREHENSIVE ACCOUNT SETUP CHECKING ==========
    # Always check what's actually been set up, regardless of historical data
    # This helps new accounts AND existing accounts that may be missing critical components

    setup_checks = {
        'has_conversion_tracking': total_conversions > 0,
        'has_campaigns': len(campaigns) > 0,
        'has_ad_groups': len(ad_groups) > 0,
        'has_keywords': len(keywords) > 0,
        'has_ads': len(ads) > 0,
        'has_negatives': len(negatives) > 0,
        'has_extensions': len(extensions) > 0,
        'has_callout_ext': any(e.get('type') == 'callout' for e in extensions),
        'has_sitelink_ext': any(e.get('type') == 'sitelink' for e in extensions),
        'has_call_ext': any(e.get('type') == 'call' for e in extensions),
        'has_location_ext': any(e.get('type') == 'location' for e in extensions),
    }

    current_app.logger.info(f"Account setup checks: {setup_checks}")

    # 1. CRITICAL: Conversion tracking
    if not setup_checks['has_conversion_tracking']:
        opportunities.append({
            "title": "⚠️ Set up conversion tracking (CRITICAL)",
            "description": "Essential foundation: Without conversion tracking, you can't optimize for what matters. Set up phone calls, form submissions, and purchases as conversions.",
            "priority": "high",
            "impact_score": 100,
            "category": "setup",
            "icon": "fa-chart-line",
            "color": "red",
            "action": "Install Google Ads conversion tag and set up conversion actions for calls, forms, and purchases",
            "estimated_time": "30 min",
            "quick_win": True,
            "confidence_score": 100,
            "risk_level": "low",
            "benefit_explanation": "**Why This is Critical:** Without conversion tracking, Google's AI can't optimize your bids for actual customers. You're essentially flying blind, paying for clicks that may never convert.",
            "optimization_type": "setup",
            "optimization_data": {'setup_check': 'conversion_tracking'},
            "best_practice": True,
        })

    # 2. Basic account structure (only if missing)
    if not setup_checks['has_campaigns'] or not setup_checks['has_ad_groups']:
        opportunities.append({
            "title": "⚠️ Set up campaign structure",
            "description": f"Your account needs basic structure: {'campaigns' if not setup_checks['has_campaigns'] else ''} {('and ' if not setup_checks['has_campaigns'] and not setup_checks['has_ad_groups'] else '')} {'ad groups' if not setup_checks['has_ad_groups'] else ''}",
            "priority": "high",
            "impact_score": 100,
            "category": "setup",
            "icon": "fa-folder-tree",
            "color": "red",
            "action": "Create at least 1 campaign with 2-3 tightly themed ad groups",
            "estimated_time": "1 hour",
            "quick_win": False,
            "confidence_score": 100,
            "risk_level": "low",
            "benefit_explanation": "Campaigns and ad groups are the foundation of your account structure. You need at least one campaign with organized ad groups before adding keywords and ads.",
            "optimization_type": "setup",
            "optimization_data": {'setup_check': 'basic_structure'},
            "best_practice": True,
        })

    # 3. Keywords (only if missing)
    if setup_checks['has_campaigns'] and setup_checks['has_ad_groups'] and not setup_checks['has_keywords']:
        opportunities.append({
            "title": "Add keywords to your ad groups",
            "description": "Your ad groups need keywords to trigger your ads. Start with 15-30 tightly themed keywords per ad group.",
            "priority": "high",
            "impact_score": 95,
            "category": "setup",
            "icon": "fa-key",
            "color": "blue",
            "action": "Add 15-30 closely related keywords per ad group (e.g., 'emergency plumber', 'emergency plumbing', '24 hour plumber')",
            "estimated_time": "2 hours",
            "quick_win": False,
            "confidence_score": 95,
            "risk_level": "low",
            "benefit_explanation": "Keywords determine when your ads show. Tightly themed ad groups (15-30 related keywords) allow you to write highly specific ads that match search intent → higher CTR → lower CPCs.",
            "optimization_type": "setup",
            "optimization_data": {'setup_check': 'keywords'},
            "best_practice": True,
        })

    # 4. Ads (only if missing)
    if setup_checks['has_campaigns'] and setup_checks['has_ad_groups'] and setup_checks['has_keywords'] and not setup_checks['has_ads']:
        opportunities.append({
            "title": "Create ads for your ad groups",
            "description": "Your ad groups have keywords but no ads. Create 3-5 Responsive Search Ads per ad group for proper testing.",
            "priority": "high",
            "impact_score": 90,
            "category": "setup",
            "icon": "fa-ad",
            "color": "purple",
            "action": "Write 3-5 RSAs per ad group with 15 headlines and 4 descriptions each",
            "estimated_time": "3 hours",
            "quick_win": False,
            "confidence_score": 90,
            "risk_level": "low",
            "benefit_explanation": "Ads are what users see and click. Multiple RSAs enable Google to test different combinations and find what works best. Without ads, your keywords can't trigger any impressions.",
            "optimization_type": "setup",
            "optimization_data": {'setup_check': 'ads'},
            "best_practice": True,
        })

    # 5. Negative keywords (if few or none - ALWAYS check this)
    if setup_checks['has_keywords'] and len(negatives) < 10:
        missing_count = max(0, 10 - len(negatives))
        opportunities.append({
            "title": f"Add {missing_count} starter negative keywords",
            "description": f"You have {len(negatives)} negative keywords. Add at least 10 to block obvious non-converting terms: jobs, careers, DIY, how to, free, salary.",
            "priority": "high",
            "impact_score": 85,
            "category": "negative_keyword",
            "icon": "fa-ban",
            "color": "red",
            "action": "Add these negatives: jobs, careers, DIY, how to, free, cheap, salary, training, reviews, complaints",
            "estimated_time": "15 min",
            "quick_win": True,
            "confidence_score": 95,
            "risk_level": "low",
            "benefit_explanation": "These terms attract job seekers, DIYers, and researchers - not paying customers. Block them before they drain your budget.",
            "optimization_type": "setup",
            "optimization_data": {'setup_check': 'negative_keywords', 'current_count': len(negatives)},
            "best_practice": True,
        })

    # 6. Extensions (always check what's missing)
    missing_extensions = []
    if not setup_checks['has_call_ext']:
        missing_extensions.append('Call extension (critical for service businesses)')
    if not setup_checks['has_sitelink_ext']:
        missing_extensions.append('Sitelinks (4-6 links to key pages)')
    if not setup_checks['has_callout_ext']:
        missing_extensions.append('Callouts (4 benefit statements)')
    if not setup_checks['has_location_ext']:
        missing_extensions.append('Location extension')

    if missing_extensions:
        opportunities.append({
            "title": f"Add {len(missing_extensions)} missing ad extensions",
            "description": f"Missing: {', '.join(missing_extensions[:2])}{'...' if len(missing_extensions) > 2 else ''}. Extensions increase ad size and CTR by 15-30%.",
            "priority": "high",
            "impact_score": 80,
            "category": "extension",
            "icon": "fa-puzzle-piece",
            "color": "green",
            "action": f"Set up: {', '.join(missing_extensions)}",
            "estimated_time": "45 min",
            "quick_win": True,
            "confidence_score": 95,
            "risk_level": "low",
            "benefit_explanation": "Extensions make your ad larger, pushing competitors down. Call extensions are especially critical for service businesses - mobile users expect tap-to-call.",
            "optimization_type": "setup",
            "optimization_data": {'setup_check': 'extensions', 'missing': missing_extensions},
            "best_practice": True,
        })

    # Note: Setup recommendations are now handled by comprehensive setup checking above
    # which runs ALWAYS, not just for new accounts

    # ========== AI AGENTS INTEGRATION ==========
    # Run 8 AI agents (Strategic, Operational, Tactical) to generate additional opportunities
    try:
        # Get customer_id and credentials from database for agent context
        customer_id = None
        refresh_token = None
        try:
            # Get customer_id from accounts table
            cid_query = text("SELECT google_ads_customer_id FROM accounts WHERE id=:aid LIMIT 1")
            with db.engine.connect() as conn:
                result = conn.execute(cid_query, {"aid": aid})
                row = result.first()
                if row:
                    customer_id = row[0]

            # Get refresh_token from google_oauth_tokens
            creds_query = text("""
                SELECT credentials_json
                FROM google_oauth_tokens
                WHERE account_id = :account_id AND product = 'ads'
                ORDER BY id DESC LIMIT 1
            """)
            with db.engine.connect() as conn:
                result = conn.execute(creds_query, {"account_id": aid})
                row = result.first()
                if row:
                    creds_json = json.loads(row[0]) if isinstance(row[0], str) else row[0]
                    refresh_token = creds_json.get('refresh_token')

            current_app.logger.info(f"AI Agents context: customer_id={customer_id}, has_refresh_token={bool(refresh_token)}")
        except Exception as e:
            current_app.logger.warning(f"Could not fetch customer_id/token for AI agents: {e}")

        # Run all 8 AI agents and collect their opportunities
        agent_opportunities = _run_ai_agents_for_opportunities(aid, ads_data, customer_id, refresh_token)
        if agent_opportunities:
            opportunities.extend(agent_opportunities)
            current_app.logger.info(f"Added {len(agent_opportunities)} AI agent opportunities to the list")
    except Exception as e:
        current_app.logger.error(f"Error integrating AI agents: {e}", exc_info=True)

    # Sort opportunities by priority and impact
    priority_order = {"high": 0, "medium": 1, "low": 2}
    opportunities.sort(key=lambda x: (priority_order.get(x["priority"], 3), -x.get("impact_score", 0)))

    # Generate detailed recommendations by category
    recommendations = _generate_detailed_recommendations(aid, ads_data, scores)

    # Add campaign-level breakdown using REAL data
    campaign_breakdown = []
    for i, campaign in enumerate(campaigns[:5]):  # Top 5 campaigns
        campaign_cost = campaign.get("cost_30d", 0) or (campaign.get("daily_budget", 0) * 25)
        campaign_conversions = campaign.get("conversions", 0)
        campaign_clicks = campaign.get("clicks", 0)

        # Calculate health score based on real metrics
        if campaign_conversions > 0 and campaign_cost > 0:
            cpa = campaign_cost / campaign_conversions
            # Compare to account average
            avg_cpa = cost_per_conversion if cost_per_conversion > 0 else 80
            if cpa <= avg_cpa * 0.8:
                health = 85  # 20% better than average
            elif cpa <= avg_cpa:
                health = 70  # At or below average
            elif cpa <= avg_cpa * 1.2:
                health = 55  # 20% worse than average
            else:
                health = 40  # Needs attention
        elif campaign_clicks > 0:
            health = 50  # Has traffic but no conversions yet
        else:
            health = 35  # No data

        campaign_breakdown.append({
            "name": campaign.get("name", f"Campaign {i+1}"),
            "status": campaign.get("status", "enabled"),
            "budget": campaign.get("daily_budget", 0),
            "spend": campaign_cost,
            "conversions": campaign_conversions,
            "clicks": campaign_clicks,
            "cpa": (campaign_cost / campaign_conversions) if campaign_conversions > 0 else None,
            "health_score": health,
        })

    # Add competitive insights using REAL account data
    your_cpc = avg_cpc if has_historical_data else 4.50
    industry_avg_cpc = 4.50  # Home services industry average

    competitive_insights = {
        "avg_cpc_vs_industry": {
            "yours": round(your_cpc, 2),
            "industry": industry_avg_cpc,
            "diff_pct": round(((your_cpc - industry_avg_cpc) / industry_avg_cpc) * 100, 0) if industry_avg_cpc > 0 else 0
        },
        "your_ctr": round(avg_ctr * 100, 2) if has_historical_data else None,
        "industry_avg_ctr": 3.5,  # Industry benchmark
        "has_historical_data": has_historical_data,
        "top_competitor_tactics": [
            "Using 'Same Day Service' or '24/7' in 85% of ads (urgency converts)",
            "Average 4-5 ad extensions per ad (especially call extensions)",
            "Mobile bid adjustments +20-30% (mobile-first strategy)",
            "Quality Score 8+ on top keywords (lower CPCs through relevance)",
            "Negative keyword lists with 50+ terms (blocks wasted spend)",
        ],
        "industry_benchmarks": {
            "avg_ctr": "3.5-5%",
            "avg_cpa": "$50-80",
            "avg_conversion_rate": "3-5%",
            "recommended_extensions": "4-5 types minimum",
            "keywords_per_ad_group": "5-20 tightly themed",
        }
    }

    # Add quick wins (optimizations < 30 min)
    quick_wins = [opp for opp in opportunities if opp.get("quick_win", False)]

    return {
        "scores": scores,
        "grade": grade,
        "opportunities": opportunities,  # Return all individual line items
        "recommendations": recommendations,
        "account_name": ads_data.get("account_name", "Google Ads Account"),
        "campaign_breakdown": campaign_breakdown,
        "competitive_insights": competitive_insights,
        "quick_wins": quick_wins,
        "total_opportunities": len(opportunities),
        "performance": performance,
    }


def _generate_detailed_recommendations(aid: int, ads_data: dict, scores: dict) -> list:
    """Generate detailed, actionable recommendations grouped by category."""
    recommendations = []

    # Negative Keywords recommendations
    if scores["wasted_spend"] < 70:
        recommendations.append({
            "category": "wasted_spend",
            "title": "Negative Keywords Strategy",
            "priority": "high",
            "items": [
                "Add top 4 negatives first: 'jobs', 'careers', 'DIY', 'how to' (saves $2,017/mo)",
                "Review search terms report weekly and add 5-10 more negatives",
                "Create negative keyword lists by theme (e.g., job-seeking, free/cheap seekers)",
                "Use broad match negatives for obvious irrelevant terms",
                "Focus on high-waste terms first - diminishing returns after top 5-6",
            ],
            "impact": "Can reduce wasted spend by $1,800-2,700/month (decreasing returns after top terms)",
        })

    # Quality Score recommendations
    if scores["quality_score"] < 75:
        recommendations.append({
            "category": "quality_score",
            "title": "Quality Score Optimization",
            "priority": "high",
            "items": [
                "Focus on lowest QS keywords first (QS 3-4) - biggest CPC reduction potential",
                "Match ad headlines to keyword themes (include exact keyword in headline)",
                "Improve landing page load speed (target <2 seconds, especially mobile)",
                "Ensure landing page content matches ad promise and keyword intent",
                "Use dynamic keyword insertion sparingly in appropriate ad groups",
            ],
            "impact": "Can reduce CPC by 15-40% on low QS keywords (saves $800-2,200/month, highest impact on QS 3-4)",
        })

    # Ad Extensions recommendations
    if scores["extensions"] < 70:
        recommendations.append({
            "category": "extensions",
            "title": "Ad Extensions Setup",
            "priority": "high",
            "items": [
                "Add call extensions FIRST - highest impact for service business (18 leads/mo)",
                "Add sitelinks to key pages - compounds well with call extensions (12 more leads/mo)",
                "Create callout extensions highlighting benefits (8 more leads/mo)",
                "Add location extensions if you have a physical location (6 more leads/mo)",
                "Add structured snippets last - minimal incremental value (3 leads/mo)",
            ],
            "impact": "Can increase CTR by 20-35% and add 30-47 leads/month (diminishing returns after first 3 extensions)",
        })

    # CTR/Ad Copy recommendations
    if scores["ctr"] < 70:
        recommendations.append({
            "category": "ctr",
            "title": "Ad Copy Improvements",
            "priority": "medium",
            "items": [
                "Test emotional triggers in headlines (urgency: 'Fast Response', 'Same Day')",
                "Add time-sensitive offers in descriptions ('24/7 Emergency', 'Available Now')",
                "Include pricing transparency to build trust ('Upfront Pricing', 'No Hidden Fees')",
                "Test different calls-to-action ('Call Now' vs 'Get Quote' vs 'Schedule Today')",
                "Use ad customizers for location and time-based copy variations",
            ],
            "impact": "Can improve CTR by 20-40% (10-25 more clicks/month, compounds with extensions)",
        })

    # Mobile recommendations
    if scores["mobile"] < 70:
        recommendations.append({
            "category": "mobile",
            "title": "Mobile Optimization",
            "priority": "medium",
            "items": [
                "Increase mobile bid adjustment to +20% FIRST (captures 8 more mobile leads/mo)",
                "Create mobile-preferred ads with tap-to-call - compounds with bid adjustment",
                "Ensure landing pages are mobile-responsive with large tap-friendly CTAs",
                "Add call extensions if not done yet - critical for mobile conversions",
                "Test mobile-specific ad copy emphasizing speed and convenience",
            ],
            "impact": "Can increase mobile conversions by 35-50% (12 total leads/month when both optimizations done)",
        })

    # Account Structure recommendations
    if scores["account_structure"] < 70:
        recommendations.append({
            "category": "account_structure",
            "title": "Account Organization",
            "priority": "low",
            "items": [
                "Create separate campaigns by service type for better budget control",
                "Use single-keyword ad groups (SKAGs) for top performing keywords",
                "Split search and display into separate campaigns",
                "Create branded vs non-branded campaign separation",
                "Use clear naming conventions (Location-Service-MatchType)",
            ],
            "impact": "Easier management, better control, 5+ hours saved/month",
        })

    return recommendations

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

@google_bp.route("/ads/apply-suggestions", methods=["POST", "GET"], endpoint="ads_apply_suggestions")
@login_required
def ads_apply_suggestions():
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

@google_bp.route("/ads/campaign/new", methods=["POST"], endpoint="ads_campaign_new")
@login_required
def ads_campaign_new():
    return _ads_not_implemented()

@google_bp.route("/ads/campaign/<int:cid>/edit", methods=["POST"], endpoint="ads_campaign_edit")
@login_required
def ads_campaign_edit(cid: int):
    return _ads_not_implemented()

@google_bp.route("/ads/campaign/<int:cid>/delete", methods=["POST"], endpoint="ads_campaign_delete")
@login_required
def ads_campaign_delete(cid: int):
    return _ads_not_implemented()

@google_bp.route("/ads/adgroup/new/<int:cid>", methods=["POST"], endpoint="ads_adgroup_new")
@login_required
def ads_adgroup_new(cid: int):
    return _ads_not_implemented()

@google_bp.route("/ads/adgroup/<int:gid>/edit", methods=["POST"], endpoint="ads_adgroup_edit")
@login_required
def ads_adgroup_edit(gid: int):
    return _ads_not_implemented()

@google_bp.route("/ads/adgroup/<int:gid>/delete", methods=["POST"], endpoint="ads_adgroup_delete")
@login_required
def ads_adgroup_delete(gid: int):
    return _ads_not_implemented()

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
            # Use refresh_token for the official Google Ads library (it handles access tokens internally)
            rt = token_json.get("refresh_token")
            refresh_token = rt.strip() if isinstance(rt, str) else rt
            ids = pick_and_save_customer_id_after_oauth(aid, refresh_token) if refresh_token else []
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
