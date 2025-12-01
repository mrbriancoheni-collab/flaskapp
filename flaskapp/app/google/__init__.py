# app/google/__init__.py
from __future__ import annotations
from flask import Blueprint, current_app, request, redirect, url_for, session, render_template, flash
import json
import os
import uuid
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

        # Location extensions detection is skipped for now
        # The campaign_feed.placeholder_types field is not available/queryable in Google Ads API v21
        # Location extensions are managed differently and require additional API calls
        # Users will see "Add Location Extensions" in manual tasks if location tracking is important

    except Exception as e:
        current_app.logger.warning(f"Failed to fetch campaign assets: {e}")

    # ========== PERFORMANCE MAX SUPPORT ==========
    # Performance Max campaigns don't have traditional ad groups, keywords, or RSAs
    # They use asset groups with various asset types instead
    asset_groups = []
    pmax_assets = []
    pmax_campaigns = [c for c in campaigns if c.get('type') == 'PERFORMANCE_MAX']

    if pmax_campaigns:
        current_app.logger.info(f"Found {len(pmax_campaigns)} Performance Max campaigns, fetching asset groups...")
        try:
            # Fetch asset groups for Performance Max campaigns
            for r in _gaql("""
                SELECT asset_group.id, asset_group.name, asset_group.status,
                       asset_group.campaign, asset_group.final_urls,
                       asset_group.final_mobile_urls
                FROM asset_group
                WHERE asset_group.status != 'REMOVED'
                LIMIT 100
            """):
                ag = r.asset_group
                asset_groups.append({
                    "id": str(ag.id),
                    "name": ag.name,
                    "status": str(ag.status).split(".")[-1],
                    "campaign_id": str(ag.campaign.split("/")[-1]),
                    "final_urls": list(ag.final_urls) if ag.final_urls else [],
                    "final_mobile_urls": list(ag.final_mobile_urls) if ag.final_mobile_urls else [],
                })
            current_app.logger.info(f"Fetched {len(asset_groups)} asset groups for Performance Max")
        except Exception as e:
            current_app.logger.warning(f"Failed to fetch Performance Max asset groups: {e}")

        try:
            # Fetch assets for Performance Max campaigns
            for r in _gaql("""
                SELECT asset_group_asset.field_type, asset_group_asset.asset_group,
                       asset.type, asset.name, asset.text_asset.text,
                       asset.image_asset.full_size.url, asset.youtube_video_asset.youtube_video_id
                FROM asset_group_asset
                WHERE asset_group_asset.status != 'REMOVED'
                LIMIT 500
            """):
                aga = r.asset_group_asset
                asset = r.asset
                asset_type = str(asset.type).split(".")[-1]
                field_type = str(aga.field_type).split(".")[-1]

                asset_data = {
                    "asset_group_id": str(aga.asset_group.split("/")[-1]),
                    "field_type": field_type,  # HEADLINE, DESCRIPTION, etc.
                    "asset_type": asset_type,   # TEXT, IMAGE, YOUTUBE_VIDEO
                    "name": asset.name if asset.name else None,
                }

                # Extract asset content based on type
                if asset_type == 'TEXT' and asset.text_asset and asset.text_asset.text:
                    asset_data["text"] = asset.text_asset.text
                elif asset_type == 'IMAGE' and asset.image_asset:
                    asset_data["image_url"] = asset.image_asset.full_size.url if asset.image_asset.full_size else None
                elif asset_type == 'YOUTUBE_VIDEO' and asset.youtube_video_asset:
                    asset_data["youtube_video_id"] = asset.youtube_video_asset.youtube_video_id

                pmax_assets.append(asset_data)

            current_app.logger.info(f"Fetched {len(pmax_assets)} assets for Performance Max asset groups")
        except Exception as e:
            current_app.logger.warning(f"Failed to fetch Performance Max assets: {e}")

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
        "asset_groups": asset_groups,  # Performance Max asset groups
        "pmax_assets": pmax_assets,    # Performance Max assets (headlines, descriptions, images, videos)
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
        decision_type = opp.get('decision_type', '')

        # Core auto-applicable types (can be applied with one click)
        if opt_type in ['negative_keyword', 'mobile_bid', 'mobile_ads', 'starter_negative_keywords']:
            return True

        # AI-generated ad content (auto-complete with AI)
        if opt_type in ['pmax_headlines', 'pmax_descriptions', 'rsa_headline_variations', 'create_rsa_ads']:
            return True

        # AI-assisted campaign creation (auto-complete with AI)
        if decision_type == 'create_search_campaign':
            return True

        # Extension types - ALL extensions are now auto-applicable (including location)
        if opt_type == 'extension':
            ext_type = opp.get("optimization_data", {}).get("type", "").lower()
            return ("callout" in ext_type or "snippet" in ext_type or "structured" in ext_type
                    or "sitelink" in ext_type or "call" in ext_type or "price" in ext_type
                    or "location" in ext_type)

        # Agent-generated optimizations - check if they're auto-executable
        if opp.get('agent_generated'):
            # Search campaign creation is now auto-applicable
            if decision_type == 'create_search_campaign':
                return True
            requires_approval = opp.get('optimization_data', {}).get('requires_approval', True)
            return not requires_approval  # Auto-applicable if doesn't require approval

        # Agent decision types that are auto-executable
        agent_auto_types = [
            'pause_keyword',           # Pause underperformers
            'adjust_keyword_bid',      # Bid adjustments
            'add_negative_keyword',    # Block waste
            'adjust_bids',             # Campaign-level bid adjustments
            'adjust_daily_budget',     # Budget pacing
            'create_search_campaign',  # AI-assisted Search campaign creation
            'add_pmax_assets',         # AI-generated PMax headlines and descriptions
            'improve_asset_variety',   # AI-generated additional headline variations
            'add_asset_groups',        # AI-generated asset groups with themes
            'create_asset_groups',     # AI-generated asset groups for new campaigns
        ]
        if opt_type in agent_auto_types or decision_type in agent_auto_types:
            return True

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
        # Auto-applicable: Can be applied with one click (negative_keyword, mobile_bid, mobile_ads, PMax AI content, extensions)
        # Manual tasks: Require manual setup (setup, quality_score, account_structure, location extensions)
        all_opportunities = analysis.get("opportunities", [])

        def is_auto_applicable(opp):
            opt_type = opp.get("optimization_type", "")
            decision_type = opp.get('decision_type', '')

            # Core auto-applicable types
            if opt_type in ['negative_keyword', 'mobile_bid', 'mobile_ads', 'starter_negative_keywords']:
                return True

            # AI-generated ad content
            if opt_type in ['pmax_headlines', 'pmax_descriptions', 'rsa_headline_variations']:
                return True

            # AI-assisted campaign creation
            if decision_type == 'create_search_campaign':
                return True

            # Extensions
            if opt_type == 'extension':
                # Callout, structured snippet, sitelink, call, and price extensions are auto-applicable
                ext_type = opp.get("optimization_data", {}).get("type", "").lower()
                return ("callout" in ext_type or "snippet" in ext_type or "structured" in ext_type
                        or "sitelink" in ext_type or "call" in ext_type or "price" in ext_type)
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
    # Auto-applicable: Can be applied with one click (negative_keyword, mobile_bid, mobile_ads, PMax AI content, extensions)
    # Manual tasks: Require manual setup (setup, quality_score, account_structure, location extensions)
    all_opportunities = analysis.get("opportunities", [])

    def is_auto_applicable(opp):
        opt_type = opp.get("optimization_type", "")
        decision_type = opp.get('decision_type', '')

        # Core auto-applicable types
        if opt_type in ['negative_keyword', 'mobile_bid', 'mobile_ads', 'starter_negative_keywords']:
            return True

        # AI-generated ad content
        if opt_type in ['pmax_headlines', 'pmax_descriptions', 'rsa_headline_variations']:
            return True

        # AI-assisted campaign creation
        if decision_type == 'create_search_campaign':
            return True

        # Extensions
        if opt_type == 'extension':
            # Callout, structured snippet, sitelink, call, and price extensions are auto-applicable
            ext_type = opp.get("type", "").lower()
            return ("callout" in ext_type or "snippet" in ext_type or "structured" in ext_type
                    or "sitelink" in ext_type or "call" in ext_type or "price" in ext_type)
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


@google_bp.route("/ads/campaigns/paused", methods=["GET"], endpoint="get_paused_campaigns")
@login_required
def get_paused_campaigns():
    """Get all paused campaigns with details."""
    aid = current_account_id()
    ads_data = _get_ads_state(aid)

    # Filter for paused campaigns
    paused = [c for c in ads_data.get('campaigns', []) if c.get('status', '').lower() == 'paused']

    return jsonify({
        'success': True,
        'campaigns': paused
    })


@google_bp.route("/ads/campaigns/<campaign_id>/details", methods=["GET"], endpoint="get_campaign_details")
@login_required
def get_campaign_details(campaign_id):
    """Get detailed information about a specific campaign including ad groups, keywords, and ads."""
    aid = current_account_id()
    customer_id = _get_ads_customer_id(aid)

    if not customer_id:
        return jsonify({'success': False, 'error': 'No Google Ads customer ID found'}), 400

    try:
        from google.ads.googleads.client import GoogleAdsClient

        # Get refresh token
        tok = _get_ads_user_tokens(aid) or {}
        refresh_token = tok.get("refresh_token")
        if not refresh_token:
            return jsonify({'success': False, 'error': 'No refresh token available'}), 400

        # Create Google Ads client
        client_id, client_secret = _client_info("ads")
        credentials = {
            "developer_token": current_app.config.get("GOOGLE_ADS_DEVELOPER_TOKEN"),
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "token_uri": "https://oauth2.googleapis.com/token",
            "use_proto_plus": True
        }

        client = GoogleAdsClient.load_from_dict(credentials)
        google_ads_service = client.get_service("GoogleAdsService")

        # Get campaign details
        campaign_query = f"""
            SELECT
                campaign.id,
                campaign.name,
                campaign.status,
                campaign.advertising_channel_type,
                campaign.bidding_strategy_type,
                campaign_budget.amount_micros,
                metrics.cost_micros,
                metrics.conversions,
                metrics.clicks,
                metrics.impressions
            FROM campaign
            WHERE campaign.id = {campaign_id}
            AND segments.date DURING LAST_30_DAYS
        """

        campaign_response = google_ads_service.search(customer_id=customer_id, query=campaign_query)
        campaign_data = None

        for row in campaign_response:
            c = row.campaign
            metrics = row.metrics
            budget_micros = row.campaign_budget.amount_micros if hasattr(row, 'campaign_budget') and row.campaign_budget else None

            campaign_data = {
                'id': str(c.id),
                'name': c.name,
                'type': str(c.advertising_channel_type).split(".")[-1],
                'status': str(c.status).split(".")[-1].title(),
                'daily_budget': (budget_micros / 1_000_000) if budget_micros else None,
                'bidding': str(c.bidding_strategy_type).split(".")[-1].replace("_", " ").title(),
                'cost_30d': (metrics.cost_micros or 0) / 1_000_000,
                'conversions': metrics.conversions or 0,
                'clicks': metrics.clicks or 0,
                'impressions': metrics.impressions or 0,
            }
            break

        if not campaign_data:
            return jsonify({'success': False, 'error': 'Campaign not found'}), 404

        # Get ad groups for this campaign
        ag_query = f"""
            SELECT
                ad_group.id,
                ad_group.name,
                ad_group.status,
                metrics.clicks,
                metrics.impressions,
                metrics.conversions
            FROM ad_group
            WHERE campaign.id = {campaign_id}
            AND ad_group.status != 'REMOVED'
            AND segments.date DURING LAST_30_DAYS
            LIMIT 50
        """

        ad_groups = []
        ag_response = google_ads_service.search(customer_id=customer_id, query=ag_query)
        for row in ag_response:
            ag = row.ad_group
            metrics = row.metrics
            ad_groups.append({
                'id': str(ag.id),
                'name': ag.name,
                'status': str(ag.status).split(".")[-1].title(),
                'clicks': metrics.clicks or 0,
                'impressions': metrics.impressions or 0,
                'conversions': metrics.conversions or 0,
            })

        # Get keywords for this campaign
        kw_query = f"""
            SELECT
                ad_group_criterion.keyword.text,
                ad_group_criterion.keyword.match_type,
                ad_group.name,
                metrics.clicks,
                metrics.impressions,
                metrics.conversions,
                metrics.cost_micros
            FROM keyword_view
            WHERE campaign.id = {campaign_id}
            AND ad_group_criterion.status != 'REMOVED'
            AND segments.date DURING LAST_30_DAYS
            LIMIT 100
        """

        keywords = []
        kw_response = google_ads_service.search(customer_id=customer_id, query=kw_query)
        for row in kw_response:
            kw = row.ad_group_criterion.keyword
            metrics = row.metrics
            keywords.append({
                'text': kw.text,
                'match_type': str(kw.match_type).split(".")[-1].title(),
                'ad_group': row.ad_group.name,
                'clicks': metrics.clicks or 0,
                'impressions': metrics.impressions or 0,
                'conversions': metrics.conversions or 0,
                'cost': (metrics.cost_micros or 0) / 1_000_000,
            })

        campaign_data['ad_groups'] = ad_groups
        campaign_data['keywords'] = keywords

        return jsonify({
            'success': True,
            'campaign': campaign_data
        })

    except Exception as e:
        current_app.logger.exception(f"Error getting campaign details: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@google_bp.route("/ads/campaigns/<campaign_id>/activate", methods=["POST"], endpoint="activate_campaign")
@login_required
def activate_campaign(campaign_id):
    """Activate a paused campaign."""
    aid = current_account_id()
    customer_id = _get_ads_customer_id(aid)

    if not customer_id:
        return jsonify({'success': False, 'error': 'No Google Ads customer ID found'}), 400

    try:
        from google.ads.googleads.client import GoogleAdsClient
        from google.ads.googleads.errors import GoogleAdsException

        # Get refresh token
        tok = _get_ads_user_tokens(aid) or {}
        refresh_token = tok.get("refresh_token")
        if not refresh_token:
            return jsonify({'success': False, 'error': 'No refresh token available'}), 400

        # Create Google Ads client
        client_id, client_secret = _client_info("ads")
        credentials = {
            "developer_token": current_app.config.get("GOOGLE_ADS_DEVELOPER_TOKEN"),
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "token_uri": "https://oauth2.googleapis.com/token",
            "use_proto_plus": True
        }

        client = GoogleAdsClient.load_from_dict(credentials)
        campaign_service = client.get_service("CampaignService")

        # Create campaign operation to update status
        campaign_operation = client.get_type("CampaignOperation")
        campaign = campaign_operation.update
        campaign.resource_name = f"customers/{customer_id}/campaigns/{campaign_id}"
        campaign.status = client.enums.CampaignStatusEnum.ENABLED

        # Update field mask
        client.copy_from(
            campaign_operation.update_mask,
            client.get_type("FieldMask", version='v21')(paths=["status"])
        )

        # Execute the operation
        response = campaign_service.mutate_campaigns(
            customer_id=customer_id,
            operations=[campaign_operation]
        )

        # Clear ads cache to refresh data
        sess_key = f"_ads_state_{aid}"
        session.pop(sess_key, None)

        return jsonify({
            'success': True,
            'message': f'Campaign activated successfully',
            'resource_name': response.results[0].resource_name if response.results else None
        })

    except GoogleAdsException as ex:
        error_msg = f"Google Ads API error: {ex.error.code().name}"
        for error in ex.failure.errors:
            error_msg += f" - {error.message}"
        current_app.logger.error(f"Error activating campaign: {error_msg}")
        return jsonify({'success': False, 'error': error_msg}), 500
    except Exception as e:
        current_app.logger.exception(f"Error activating campaign: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


def _generate_preview(opt_type: str, opt_data: dict, opt_title: str) -> dict:
    """Generate human-readable preview of what an optimization will create."""
    preview = {
        "title": opt_title,
        "type": opt_type,
        "summary": "",
        "details": []
    }

    if opt_type == "negative_keyword":
        term = opt_data.get("term", "")
        preview["summary"] = f"Block searches containing '{term}'"
        preview["details"] = [
            f"Negative keyword: {term}",
            "Match type: Broad",
            "Will prevent ads from showing for queries containing this term"
        ]

    elif opt_type == "starter_negative_keywords":
        keywords = opt_data.get("starter_keywords", [])
        preview["summary"] = f"Block {len(keywords)} common non-buyer search terms"
        preview["details"] = [f"• {kw}" for kw in keywords]
        preview["details"].append(f"\nTotal: {len(keywords)} negative keywords")

    elif opt_type == "mobile_bid":
        adjustment = opt_data.get("bid_adjustment", 20)
        preview["summary"] = f"Increase mobile bids by {adjustment}%"
        preview["details"] = [
            f"Mobile bid modifier: +{adjustment}%",
            "Applies to all Search campaigns",
            f"Mobile ads will bid {adjustment}% higher to capture more mobile traffic"
        ]

    elif opt_type == "rsa_headline_variations":
        needed = opt_data.get("needed_headlines", 3)
        preview["summary"] = f"Add {needed} AI-generated headline variations to your RSA ads"
        preview["details"] = [
            f"New headlines: {needed} variations",
            "AI-generated based on your existing ad copy",
            "Improves Google's ability to test and optimize ad combinations"
        ]

    elif opt_type == "pmax_headlines":
        needed = opt_data.get("needed_headlines", 3)
        preview["summary"] = f"Add {needed} AI-generated headlines to Performance Max"
        preview["details"] = [
            f"New headlines: {needed} variations",
            "AI-generated for your Performance Max asset groups",
            "Increases ad variety and testing opportunities"
        ]

    elif opt_type == "pmax_descriptions":
        needed = opt_data.get("needed_descriptions", 2)
        preview["summary"] = f"Add {needed} AI-generated descriptions to Performance Max"
        preview["details"] = [
            f"New descriptions: {needed} variations",
            "AI-generated benefit-focused descriptions",
            "Meets Google's Performance Max best practices"
        ]

    elif opt_type == "extension":
        ext_type = opt_data.get("type", "").lower()
        if "call" in ext_type:
            preview["summary"] = "Add click-to-call button to your mobile ads"
            preview["details"] = [
                "Extension type: Call",
                "Auto-detects your business phone or uses placeholder",
                "Mobile users can tap to call directly from ads"
            ]
        elif "sitelink" in ext_type:
            preview["summary"] = "Add 4-6 quick links below your ads"
            preview["details"] = [
                "Extension type: Sitelink",
                "Links: Services, Contact, Emergency, About, Pricing, Reviews",
                "Takes up more ad space, pushes competitors down"
            ]
        elif "callout" in ext_type:
            preview["summary"] = "Add trust-building callouts to your ads"
            preview["details"] = [
                "Extension type: Callout",
                "Callouts: Licensed & Insured, 20+ Years Experience, Same Day Service, Free Estimates",
                "Highlights your unique selling points"
            ]
        elif "price" in ext_type:
            preview["summary"] = "Show pricing directly in your ads"
            preview["details"] = [
                "Extension type: Price",
                "Basic Service: $99 | Emergency: $199 | Inspection: $79 | Installation: $499",
                "Pre-qualifies leads who see pricing upfront"
            ]
        elif "structured" in ext_type or "snippet" in ext_type:
            preview["summary"] = "Showcase your service categories"
            preview["details"] = [
                "Extension type: Structured Snippet",
                "Categories: Repairs, Installation, Maintenance, Emergency Service, Inspection",
                "Shows breadth of services offered"
            ]
        else:
            preview["summary"] = f"Add {ext_type} extension"
            preview["details"] = [f"Extension type: {ext_type}"]

    elif opt_type == "mobile_ads":
        preview["summary"] = "Create mobile-optimized RSA ads with urgent CTAs"
        preview["details"] = [
            "AI-generated mobile-focused ad copy",
            "10-15 short, punchy headlines (e.g., 'Call Now - Fast Service')",
            "3-4 mobile-optimized descriptions with tap-to-call CTAs"
        ]

    elif opt_data.get("decision_type") == "create_search_campaign":
        preview["summary"] = "Create AI-generated Search campaign with keywords and ads"
        preview["details"] = [
            "Campaign: 1 new Search campaign (starts PAUSED)",
            "Structure: 2-3 tightly themed ad groups",
            "Keywords: 5-10 relevant keywords per ad group (Phrase & Exact match)",
            "Ads: 1 RSA per ad group with 10 headlines and 3 descriptions",
            "Budget: $50/day default (you can adjust before enabling)"
        ]

    else:
        preview["summary"] = f"Apply {opt_title}"
        preview["details"] = ["Preview not available for this optimization type"]

    return preview


def _apply_optimization(aid: int, customer_id: str, opt_type: str, opt_data: dict, opt_title: str, preview: bool = False) -> dict:
    """
    Apply a single optimization to Google Ads via API, or preview what would be created.

    Args:
        preview: If True, returns preview data without applying changes

    Returns dict with: {"success": bool, "resource_name": str, "api_response": dict, "message": str, "error": str, "preview_data": dict}
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

        # PREVIEW MODE: Generate preview data without making API calls
        if preview:
            preview_data = _generate_preview(opt_type, opt_data, opt_title)
            return {
                "success": True,
                "message": f"Preview: {opt_title}",
                "preview_data": preview_data
            }

        # Check for agent-generated decisions with decision_type
        decision_type = opt_data.get('decision_type', '')
        if decision_type == 'create_search_campaign':
            return _apply_create_search_campaign(aid, customer_id, opt_data, refresh_token)
        elif decision_type in ['add_asset_groups', 'create_asset_groups']:
            return _apply_add_asset_groups(aid, customer_id, opt_data, refresh_token)

        # Apply based on optimization type
        if opt_type == "negative_keyword":
            return _apply_negative_keyword(aid, customer_id, opt_data, refresh_token)

        elif opt_type == "starter_negative_keywords":
            return _apply_starter_negative_keywords(aid, customer_id, opt_data, refresh_token)

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
            # Generate AI-powered mobile RSA ads
            return _apply_mobile_rsa_ads(aid, customer_id, opt_data, refresh_token)

        elif opt_type == "rsa_headline_variations":
            # Generate AI-powered RSA headline variations for existing ads
            return _apply_rsa_headline_variations(aid, customer_id, opt_data, refresh_token)

        elif opt_type == "pmax_headlines":
            # Generate AI-powered Performance Max headlines
            return _apply_pmax_headlines(aid, customer_id, opt_data, refresh_token)

        elif opt_type == "pmax_descriptions":
            # Generate AI-powered Performance Max descriptions
            return _apply_pmax_descriptions(aid, customer_id, opt_data, refresh_token)

        elif opt_type == "create_rsa_ads":
            # Generate AI-powered RSA ads for ad groups (complete ads with headlines and descriptions)
            return _apply_create_rsa_ads(aid, customer_id, opt_data, refresh_token)

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


def _apply_starter_negative_keywords(aid: int, customer_id: str, opt_data: dict, access_token: str) -> dict:
    """Add starter pack of negative keywords to all Search campaigns."""
    try:
        from google.ads.googleads.client import GoogleAdsClient
        from google.ads.googleads.errors import GoogleAdsException

        # Get starter keywords from optimization data
        starter_keywords = opt_data.get("starter_keywords", [])
        if not starter_keywords:
            return {"success": False, "error": "No starter keywords provided"}

        # Create Google Ads client
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
        google_ads_service = client.get_service("GoogleAdsService")
        campaign_criterion_service = client.get_service("CampaignCriterionService")

        # Get all enabled Search campaigns
        query = """
            SELECT campaign.id, campaign.name
            FROM campaign
            WHERE campaign.status = 'ENABLED'
            AND campaign.advertising_channel_type != 'PERFORMANCE_MAX'
        """

        response = google_ads_service.search(customer_id=customer_id, query=query)

        campaign_ids = []
        for row in response:
            campaign_ids.append(row.campaign.id)

        if not campaign_ids:
            return {
                "success": False,
                "error": "No enabled Search campaigns found. Negative keywords can only be added to Search campaigns."
            }

        # Add each negative keyword to all campaigns
        added_count = 0
        operations = []

        for campaign_id in campaign_ids:
            for keyword in starter_keywords:
                campaign_criterion_operation = client.get_type("CampaignCriterionOperation")
                campaign_criterion = campaign_criterion_operation.create

                campaign_criterion.campaign = f"customers/{customer_id}/campaigns/{campaign_id}"
                campaign_criterion.negative = True
                campaign_criterion.keyword.text = keyword
                campaign_criterion.keyword.match_type = client.enums.KeywordMatchTypeEnum.BROAD

                operations.append(campaign_criterion_operation)

        # Execute all operations in batch
        if operations:
            response = campaign_criterion_service.mutate_campaign_criteria(
                customer_id=customer_id,
                operations=operations
            )
            added_count = len(response.results)

        return {
            "success": True,
            "api_response": {"results": response.results if operations else []},
            "message": f"Added {len(starter_keywords)} negative keywords to {len(campaign_ids)} campaign(s) ({added_count} total additions)",
            "keywords_added": starter_keywords,
            "campaigns_updated": len(campaign_ids)
        }

    except GoogleAdsException as ex:
        error_msg = f"Google Ads API error: {ex.error.code().name}"
        for error in ex.failure.errors:
            error_msg += f" - {error.message}"
        return {"success": False, "error": error_msg}
    except Exception as e:
        current_app.logger.error(f"Error adding starter negative keywords: {e}")
        return {"success": False, "error": str(e)}


def _apply_mobile_bid_adjustment(aid: int, customer_id: str, opt_data: dict, access_token: str) -> dict:
    """Apply mobile bid adjustment to campaign."""
    try:
        from google.ads.googleads.client import GoogleAdsClient
        from google.ads.googleads.errors import GoogleAdsException
        from google.protobuf import field_mask_pb2

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

        # Build the resource name for the mobile device criterion
        mobile_resource_name = f"customers/{customer_id}/campaignCriteria/{campaign_id}~30001"

        # Try to update the existing mobile device criterion
        campaign_criterion_operation = client.get_type("CampaignCriterionOperation")
        campaign_criterion = campaign_criterion_operation.update

        campaign_criterion.resource_name = mobile_resource_name
        campaign_criterion.bid_modifier = 1.0 + (bid_adjustment / 100.0)  # Convert percentage to multiplier

        # Set update mask using protobuf FieldMask
        campaign_criterion_operation.update_mask.CopyFrom(
            field_mask_pb2.FieldMask(paths=["bid_modifier"])
        )

        # Execute
        try:
            response = campaign_criterion_service.mutate_campaign_criteria(
                customer_id=customer_id,
                operations=[campaign_criterion_operation]
            )
            resource_name = response.results[0].resource_name if response.results else None
        except GoogleAdsException as update_ex:
            # If criterion doesn't exist, create it instead
            current_app.logger.info(f"Mobile criterion doesn't exist, creating it. Error: {update_ex}")

            campaign_criterion_operation = client.get_type("CampaignCriterionOperation")
            campaign_criterion = campaign_criterion_operation.create

            campaign_criterion.campaign = f"customers/{customer_id}/campaigns/{campaign_id}"
            campaign_criterion.criterion_id = 30001  # Mobile devices
            campaign_criterion.bid_modifier = 1.0 + (bid_adjustment / 100.0)

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


def _generate_mobile_ad_copy(business_name: str, keywords: list, website_url: str = "") -> dict:
    """Generate mobile-optimized RSA ad copy using AI."""
    try:
        from app.ai_clients import chatgpt_response
        import json

        # Get top keywords for context (limit to 10)
        keyword_text = ", ".join([k.get("text", "") for k in keywords[:10] if k.get("text")])

        prompt = f"""Generate mobile-optimized Google RSA ad copy for a business.

Business: {business_name}
Keywords: {keyword_text}
Website: {website_url}

Requirements:
- Headlines: 10-15 short, punchy headlines (max 30 chars each)
- Descriptions: 3-4 concise descriptions (max 90 chars each)
- Focus on mobile users: urgency, tap-to-call CTAs, "Call Now", "Same Day", etc.
- Include numbers, benefits, and action words
- Make headlines scan-friendly for mobile

Return ONLY valid JSON in this format:
{{
  "headlines": ["Call Now - Fast Service", "Same Day Repair Available", ...],
  "descriptions": ["Get a free estimate today. Licensed professionals ready to help.", ...]
}}"""

        response = chatgpt_response(prompt)

        # Try to parse JSON from response
        try:
            # Extract JSON if it's wrapped in markdown code blocks
            if "```json" in response:
                response = response.split("```json")[1].split("```")[0].strip()
            elif "```" in response:
                response = response.split("```")[1].split("```")[0].strip()

            ad_copy = json.loads(response)

            # Validate required fields
            if "headlines" not in ad_copy or "descriptions" not in ad_copy:
                raise ValueError("Missing required fields")

            # Trim headlines to 30 chars and descriptions to 90 chars
            ad_copy["headlines"] = [h[:30] for h in ad_copy["headlines"][:15]]
            ad_copy["descriptions"] = [d[:90] for d in ad_copy["descriptions"][:4]]

            return {"success": True, "ad_copy": ad_copy}

        except json.JSONDecodeError as e:
            current_app.logger.error(f"Failed to parse AI response as JSON: {e}")
            return {"success": False, "error": f"AI returned invalid JSON: {str(e)}"}

    except Exception as e:
        current_app.logger.error(f"Error generating mobile ad copy: {e}")
        return {"success": False, "error": str(e)}


def _apply_mobile_rsa_ads(aid: int, customer_id: str, opt_data: dict, refresh_token: str) -> dict:
    """Generate and create mobile-optimized RSA ads using AI."""
    try:
        from google.ads.googleads.client import GoogleAdsClient
        from google.ads.googleads.errors import GoogleAdsException

        # Create Google Ads client
        client_id, client_secret = _client_info("ads")
        credentials = {
            "developer_token": current_app.config.get("GOOGLE_ADS_DEVELOPER_TOKEN"),
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "token_uri": "https://oauth2.googleapis.com/token",
            "use_proto_plus": True
        }

        client = GoogleAdsClient.load_from_dict(credentials)
        google_ads_service = client.get_service("GoogleAdsService")

        # Get business name and website from Search campaigns only (not Performance Max)
        # Performance Max campaigns use asset groups, not ad groups with RSAs
        query = """
            SELECT
                campaign.id,
                campaign.name,
                campaign.status,
                campaign.advertising_channel_type,
                ad_group.id,
                ad_group.name
            FROM ad_group
            WHERE campaign.status = 'ENABLED'
            AND ad_group.status = 'ENABLED'
            AND campaign.advertising_channel_type != 'PERFORMANCE_MAX'
            LIMIT 1
        """

        response = google_ads_service.search(customer_id=customer_id, query=query)

        campaign_id = None
        ad_group_id = None
        business_name = "Your Business"

        for row in response:
            campaign_id = row.campaign.id
            ad_group_id = row.ad_group.id
            business_name = row.campaign.name.split(" - ")[0].split(" | ")[0]  # Extract business name
            break

        if not campaign_id or not ad_group_id:
            return {
                "success": False,
                "error": "Mobile RSA ads require a Search campaign. Your account only has Performance Max campaigns, which use asset groups instead of RSAs. Create a Search campaign first to use this optimization."
            }

        # Get keywords for context
        keywords_query = f"""
            SELECT ad_group_criterion.keyword.text
            FROM ad_group_criterion
            WHERE ad_group.id = {ad_group_id}
            AND ad_group_criterion.type = 'KEYWORD'
            LIMIT 10
        """

        keywords = []
        try:
            kw_response = google_ads_service.search(customer_id=customer_id, query=keywords_query)
            for row in kw_response:
                if hasattr(row.ad_group_criterion, 'keyword'):
                    keywords.append({"text": row.ad_group_criterion.keyword.text})
        except:
            pass

        # Get website URL from campaign or use empty
        website_url = opt_data.get("website_url", "")

        # Generate AI ad copy
        current_app.logger.info(f"Generating mobile ad copy for {business_name}")
        ai_result = _generate_mobile_ad_copy(business_name, keywords, website_url)

        if not ai_result.get("success"):
            return ai_result

        ad_copy = ai_result["ad_copy"]
        headlines = ad_copy["headlines"]
        descriptions = ad_copy["descriptions"]

        # Get final URL from existing ads or use website
        final_url = website_url or "https://example.com"

        try:
            url_query = f"""
                SELECT ad_group_ad.ad.final_urls
                FROM ad_group_ad
                WHERE ad_group.id = {ad_group_id}
                LIMIT 1
            """
            url_response = google_ads_service.search(customer_id=customer_id, query=url_query)
            for row in url_response:
                if row.ad_group_ad.ad.final_urls:
                    final_url = row.ad_group_ad.ad.final_urls[0]
                    break
        except:
            pass

        # Create RSA
        ad_group_ad_service = client.get_service("AdGroupAdService")
        ad_group_ad_operation = client.get_type("AdGroupAdOperation")

        ad_group_ad = ad_group_ad_operation.create
        ad_group_ad.ad_group = client.get_service("AdGroupService").ad_group_path(
            customer_id, ad_group_id
        )
        ad_group_ad.status = client.enums.AdGroupAdStatusEnum.ENABLED

        # Set RSA ad
        rsa = ad_group_ad.ad.responsive_search_ad
        ad_group_ad.ad.final_urls.append(final_url)

        # Add headlines
        for headline in headlines:
            headline_asset = client.get_type("AdTextAsset")
            headline_asset.text = headline
            rsa.headlines.append(headline_asset)

        # Add descriptions
        for description in descriptions:
            description_asset = client.get_type("AdTextAsset")
            description_asset.text = description
            rsa.descriptions.append(description_asset)

        # Create the ad
        ad_response = ad_group_ad_service.mutate_ad_group_ads(
            customer_id=customer_id,
            operations=[ad_group_ad_operation]
        )

        resource_name = ad_response.results[0].resource_name if ad_response.results else None

        return {
            "success": True,
            "resource_name": resource_name,
            "api_response": {"results": [resource_name]},
            "message": f"Created mobile-optimized RSA with {len(headlines)} headlines and {len(descriptions)} descriptions (AI-generated)",
            "ad_preview": {
                "headlines": headlines[:3],
                "descriptions": descriptions[:1]
            }
        }

    except GoogleAdsException as ex:
        error_msg = f"Google Ads API error: {ex.error.code().name}"
        for error in ex.failure.errors:
            error_msg += f" - {error.message}"
        return {"success": False, "error": error_msg}
    except Exception as e:
        current_app.logger.error(f"Error creating mobile RSA ads: {e}")
        return {"success": False, "error": str(e)}


def _generate_rsa_headline_variations(business_name: str, existing_headlines: list, needed: int) -> dict:
    """Generate additional RSA headline variations using AI."""
    try:
        from app.ai_clients import chatgpt_response
        import json

        existing_text = "\n".join([f"- {h}" for h in existing_headlines if h]) if existing_headlines else "None yet"

        prompt = f"""Generate {needed} RSA headline variations for a Google Search campaign.

Business: {business_name}

Existing Headlines (for context - don't duplicate):
{existing_text}

Requirements:
- Headlines: {needed} NEW headlines (max 30 chars each)
- Make them complementary to existing headlines
- Mix of benefit-focused, action-oriented, and trust-building
- Include numbers, urgency, and local appeal where appropriate
- Examples: "24/7 Emergency Service", "Licensed Professionals", "Same Day Appointments"

Return ONLY valid JSON:
{{"headlines": ["Fast Service - Call Now", "Licensed Professionals", ...]}}"""

        response = chatgpt_response(prompt)

        # Parse JSON from response
        try:
            # Extract JSON if it's wrapped in markdown code blocks
            if "```json" in response:
                response = response.split("```json")[1].split("```")[0].strip()
            elif "```" in response:
                response = response.split("```")[1].split("```")[0].strip()

            result = json.loads(response)

            # Validate and trim
            if "headlines" not in result:
                raise ValueError("Missing headlines field")

            headlines = [h[:30] for h in result["headlines"][:needed]]

            return {"success": True, "headlines": headlines}

        except json.JSONDecodeError as e:
            current_app.logger.error(f"Failed to parse AI response as JSON: {e}")
            return {"success": False, "error": f"AI returned invalid JSON: {str(e)}"}

    except Exception as e:
        current_app.logger.error(f"Error generating RSA headline variations: {e}")
        return {"success": False, "error": str(e)}


def _apply_rsa_headline_variations(aid: int, customer_id: str, opt_data: dict, refresh_token: str) -> dict:
    """Generate and add AI-generated headline variations to existing RSA ads."""
    try:
        from google.ads.googleads.client import GoogleAdsClient
        from google.ads.googleads.errors import GoogleAdsException
        from google.protobuf import field_mask_pb2

        # Create Google Ads client
        client_id, client_secret = _client_info("ads")
        credentials = {
            "developer_token": current_app.config.get("GOOGLE_ADS_DEVELOPER_TOKEN"),
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "token_uri": "https://oauth2.googleapis.com/token",
            "use_proto_plus": True
        }

        client = GoogleAdsClient.load_from_dict(credentials)
        google_ads_service = client.get_service("GoogleAdsService")
        ad_service = client.get_service("AdService")
        ad_group_ad_service = client.get_service("AdGroupAdService")

        # Get existing RSA ads from Search campaigns
        query = """
            SELECT
                ad_group.id,
                ad_group.name,
                ad_group_ad.ad.id,
                ad_group_ad.ad.name,
                ad_group_ad.ad.responsive_search_ad.headlines,
                ad_group_ad.ad.responsive_search_ad.descriptions,
                ad_group_ad.ad.final_urls,
                campaign.name,
                campaign.id
            FROM ad_group_ad
            WHERE ad_group_ad.ad.type = RESPONSIVE_SEARCH_AD
            AND ad_group_ad.status = 'ENABLED'
            AND ad_group.status = 'ENABLED'
            AND campaign.status = 'ENABLED'
            AND campaign.advertising_channel_type = 'SEARCH'
            LIMIT 5
        """

        results = google_ads_service.search(customer_id=customer_id, query=query)

        # Get business name from first campaign
        business_name = "Your Business"
        existing_headlines = opt_data.get('existing_headlines', [])
        needed = opt_data.get('needed_headlines', 3)

        for row in results:
            business_name = row.campaign.name
            break

        # Generate new headlines using AI
        ai_result = _generate_rsa_headline_variations(business_name, existing_headlines, needed)

        if not ai_result.get("success"):
            return ai_result

        new_headlines = ai_result.get("headlines", [])

        if not new_headlines:
            return {"success": False, "error": "AI generated no headlines"}

        # Update each RSA ad with new headlines
        updated_ads = 0
        operations = []

        for row in results:
            ad = row.ad_group_ad.ad
            current_headlines = [h.text for h in ad.responsive_search_ad.headlines]
            current_descriptions = [d.text for d in ad.responsive_search_ad.descriptions]

            # Skip if already has 15 headlines
            if len(current_headlines) >= 15:
                continue

            # Calculate how many new headlines to add
            slots_available = 15 - len(current_headlines)
            headlines_to_add = new_headlines[:min(slots_available, len(new_headlines))]

            # Create updated ad
            ad_group_ad_operation = client.get_type("AdGroupAdOperation")
            updated_ad = ad_group_ad_operation.update

            # Build resource name
            updated_ad.resource_name = client.get_service("AdGroupAdService").ad_group_ad_path(
                customer_id, row.ad_group.id, row.ad_group_ad.ad.id
            )

            # Copy existing ad settings
            updated_ad.ad.id = ad.id
            updated_ad.ad.final_urls.extend([str(url) for url in ad.final_urls])

            # Set RSA
            rsa = updated_ad.ad.responsive_search_ad

            # Add existing headlines
            for headline in current_headlines:
                headline_asset = client.get_type("AdTextAsset")
                headline_asset.text = headline
                rsa.headlines.append(headline_asset)

            # Add new AI-generated headlines
            for headline in headlines_to_add:
                headline_asset = client.get_type("AdTextAsset")
                headline_asset.text = headline
                rsa.headlines.append(headline_asset)

            # Add existing descriptions
            for description in current_descriptions:
                description_asset = client.get_type("AdTextAsset")
                description_asset.text = description
                rsa.descriptions.append(description_asset)

            # Set update mask - only update the ad fields we're changing
            ad_group_ad_operation.update_mask.CopyFrom(
                field_mask_pb2.FieldMask(paths=["ad.responsive_search_ad.headlines", "ad.responsive_search_ad.descriptions"])
            )

            operations.append(ad_group_ad_operation)
            updated_ads += 1

        if not operations:
            return {
                "success": False,
                "error": "All RSA ads already have 15 headlines (maximum). No updates needed."
            }

        # Execute updates
        response = ad_group_ad_service.mutate_ad_group_ads(
            customer_id=customer_id,
            operations=operations
        )

        return {
            "success": True,
            "message": f"Added {len(new_headlines)} headline variations to {updated_ads} RSA ad{'' if updated_ads == 1 else 's'}",
            "resource_name": response.results[0].resource_name if response.results else None,
            "api_response": {
                "updated_ads": updated_ads,
                "new_headlines": new_headlines
            }
        }

    except GoogleAdsException as ex:
        error_msg = f"Google Ads API error: {ex.error.code().name}"
        for error in ex.failure.errors:
            error_msg += f" - {error.message}"
        return {"success": False, "error": error_msg}
    except Exception as e:
        current_app.logger.error(f"Error adding RSA headline variations: {e}")
        return {"success": False, "error": str(e)}


def _generate_pmax_headlines(business_name: str, existing_headlines: list, needed: int) -> dict:
    """Generate Performance Max headlines using AI."""
    try:
        from app.ai_clients import chatgpt_response
        import json

        existing_text = "\n".join([f"- {h}" for h in existing_headlines if h]) if existing_headlines else "None yet"

        prompt = f"""Generate {needed} Performance Max headline variations for a business.

Business: {business_name}

Existing Headlines:
{existing_text}

Requirements:
- Headlines: {needed} NEW headlines (max 30 chars each, don't duplicate existing)
- Make them punchy, benefit-focused, and action-oriented
- Include variety: some with urgency, some with benefits, some with credibility
- Avoid duplicating existing headlines

Return ONLY valid JSON in this format:
{{
  "headlines": ["Fast Service - Call Now", "Licensed Professionals", ...]
}}"""

        response = chatgpt_response(prompt)

        try:
            if "```json" in response:
                response = response.split("```json")[1].split("```")[0].strip()
            elif "```" in response:
                response = response.split("```")[1].split("```")[0].strip()

            result = json.loads(response)
            if "headlines" not in result:
                raise ValueError("Missing headlines field")

            headlines = [h[:30] for h in result["headlines"][:needed]]
            return {"success": True, "headlines": headlines}

        except json.JSONDecodeError as e:
            return {"success": False, "error": f"AI returned invalid JSON: {str(e)}"}

    except Exception as e:
        return {"success": False, "error": str(e)}


def _generate_pmax_descriptions(business_name: str, existing_descriptions: list, needed: int) -> dict:
    """Generate Performance Max descriptions using AI."""
    try:
        from app.ai_clients import chatgpt_response
        import json

        existing_text = "\n".join([f"- {d}" for d in existing_descriptions if d]) if existing_descriptions else "None yet"

        prompt = f"""Generate {needed} Performance Max description variations for a business.

Business: {business_name}

Existing Descriptions:
{existing_text}

Requirements:
- Descriptions: {needed} NEW descriptions (max 90 chars each, don't duplicate existing)
- Focus on benefits, credibility, and calls-to-action
- Include variety: some emphasize speed, some quality, some experience
- Make them compelling and conversion-focused

Return ONLY valid JSON in this format:
{{
  "descriptions": ["Get expert service with same-day availability. Licensed professionals ready to help.", ...]
}}"""

        response = chatgpt_response(prompt)

        try:
            if "```json" in response:
                response = response.split("```json")[1].split("```")[0].strip()
            elif "```" in response:
                response = response.split("```")[1].split("```")[0].strip()

            result = json.loads(response)
            if "descriptions" not in result:
                raise ValueError("Missing descriptions field")

            descriptions = [d[:90] for d in result["descriptions"][:needed]]
            return {"success": True, "descriptions": descriptions}

        except json.JSONDecodeError as e:
            return {"success": False, "error": f"AI returned invalid JSON: {str(e)}"}

    except Exception as e:
        return {"success": False, "error": str(e)}


def _apply_pmax_headlines(aid: int, customer_id: str, opt_data: dict, refresh_token: str) -> dict:
    """Generate and add AI-generated headlines to Performance Max asset groups."""
    try:
        from google.ads.googleads.client import GoogleAdsClient
        from google.ads.googleads.errors import GoogleAdsException

        client_id, client_secret = _client_info("ads")
        credentials = {
            "developer_token": current_app.config.get("GOOGLE_ADS_DEVELOPER_TOKEN"),
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "token_uri": "https://oauth2.googleapis.com/token",
            "use_proto_plus": True
        }

        client = GoogleAdsClient.load_from_dict(credentials)
        google_ads_service = client.get_service("GoogleAdsService")

        # Get Performance Max campaign and asset group
        query = """
            SELECT
                campaign.id,
                campaign.name,
                asset_group.id,
                asset_group.name
            FROM asset_group
            WHERE campaign.advertising_channel_type = 'PERFORMANCE_MAX'
            AND campaign.status = 'ENABLED'
            LIMIT 1
        """

        response = google_ads_service.search(customer_id=customer_id, query=query)

        campaign_id = None
        asset_group_id = None
        business_name = "Your Business"

        for row in response:
            campaign_id = row.campaign.id
            asset_group_id = row.asset_group.id
            business_name = row.campaign.name.split(" - ")[0].split(" | ")[0]
            break

        if not asset_group_id:
            return {
                "success": False,
                "error": "No Performance Max asset groups found. Please create a Performance Max campaign first."
            }

        # Get existing headlines and generate new ones
        existing_headlines = opt_data.get('existing_headlines', [])
        needed = opt_data.get('needed_headlines', 1)

        current_app.logger.info(f"Generating {needed} PMax headlines for {business_name}")
        ai_result = _generate_pmax_headlines(business_name, existing_headlines, needed)

        if not ai_result.get("success"):
            return ai_result

        headlines = ai_result["headlines"]

        # Create headline assets and link to asset group
        asset_service = client.get_service("AssetService")
        asset_group_asset_service = client.get_service("AssetGroupAssetService")

        created_assets = []

        for headline_text in headlines:
            # Create text asset
            asset_operation = client.get_type("AssetOperation")
            asset = asset_operation.create
            asset.text_asset.text = headline_text
            asset.name = f"PMax Headline: {headline_text[:20]}"

            asset_response = asset_service.mutate_assets(
                customer_id=customer_id,
                operations=[asset_operation]
            )

            if asset_response.results:
                asset_resource_name = asset_response.results[0].resource_name
                created_assets.append(asset_resource_name)

                # Link asset to asset group
                asset_group_asset_operation = client.get_type("AssetGroupAssetOperation")
                asset_group_asset = asset_group_asset_operation.create
                asset_group_asset.asset = asset_resource_name
                asset_group_asset.asset_group = client.get_service("AssetGroupService").asset_group_path(
                    customer_id, asset_group_id
                )
                asset_group_asset.field_type = client.enums.AssetFieldTypeEnum.HEADLINE

                asset_group_asset_service.mutate_asset_group_assets(
                    customer_id=customer_id,
                    operations=[asset_group_asset_operation]
                )

        return {
            "success": True,
            "resource_name": created_assets[0] if created_assets else None,
            "api_response": {"results": created_assets},
            "message": f"Added {len(created_assets)} AI-generated headline{'' if len(created_assets) == 1 else 's'} to Performance Max",
            "headlines": headlines
        }

    except GoogleAdsException as ex:
        error_msg = f"Google Ads API error: {ex.error.code().name}"
        for error in ex.failure.errors:
            error_msg += f" - {error.message}"
        return {"success": False, "error": error_msg}
    except Exception as e:
        current_app.logger.error(f"Error adding PMax headlines: {e}")
        return {"success": False, "error": str(e)}


def _apply_pmax_descriptions(aid: int, customer_id: str, opt_data: dict, refresh_token: str) -> dict:
    """Generate and add AI-generated descriptions to Performance Max asset groups."""
    try:
        from google.ads.googleads.client import GoogleAdsClient
        from google.ads.googleads.errors import GoogleAdsException

        client_id, client_secret = _client_info("ads")
        credentials = {
            "developer_token": current_app.config.get("GOOGLE_ADS_DEVELOPER_TOKEN"),
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "token_uri": "https://oauth2.googleapis.com/token",
            "use_proto_plus": True
        }

        client = GoogleAdsClient.load_from_dict(credentials)
        google_ads_service = client.get_service("GoogleAdsService")

        # Get Performance Max campaign and asset group
        query = """
            SELECT
                campaign.id,
                campaign.name,
                asset_group.id,
                asset_group.name
            FROM asset_group
            WHERE campaign.advertising_channel_type = 'PERFORMANCE_MAX'
            AND campaign.status = 'ENABLED'
            LIMIT 1
        """

        response = google_ads_service.search(customer_id=customer_id, query=query)

        campaign_id = None
        asset_group_id = None
        business_name = "Your Business"

        for row in response:
            campaign_id = row.campaign.id
            asset_group_id = row.asset_group.id
            business_name = row.campaign.name.split(" - ")[0].split(" | ")[0]
            break

        if not asset_group_id:
            return {
                "success": False,
                "error": "No Performance Max asset groups found. Please create a Performance Max campaign first."
            }

        # Get existing descriptions and generate new ones
        existing_descriptions = opt_data.get('existing_descriptions', [])
        needed = opt_data.get('needed_descriptions', 1)

        current_app.logger.info(f"Generating {needed} PMax descriptions for {business_name}")
        ai_result = _generate_pmax_descriptions(business_name, existing_descriptions, needed)

        if not ai_result.get("success"):
            return ai_result

        descriptions = ai_result["descriptions"]

        # Create description assets and link to asset group
        asset_service = client.get_service("AssetService")
        asset_group_asset_service = client.get_service("AssetGroupAssetService")

        created_assets = []

        for description_text in descriptions:
            # Create text asset
            asset_operation = client.get_type("AssetOperation")
            asset = asset_operation.create
            asset.text_asset.text = description_text
            asset.name = f"PMax Description: {description_text[:20]}"

            asset_response = asset_service.mutate_assets(
                customer_id=customer_id,
                operations=[asset_operation]
            )

            if asset_response.results:
                asset_resource_name = asset_response.results[0].resource_name
                created_assets.append(asset_resource_name)

                # Link asset to asset group
                asset_group_asset_operation = client.get_type("AssetGroupAssetOperation")
                asset_group_asset = asset_group_asset_operation.create
                asset_group_asset.asset = asset_resource_name
                asset_group_asset.asset_group = client.get_service("AssetGroupService").asset_group_path(
                    customer_id, asset_group_id
                )
                asset_group_asset.field_type = client.enums.AssetFieldTypeEnum.DESCRIPTION

                asset_group_asset_service.mutate_asset_group_assets(
                    customer_id=customer_id,
                    operations=[asset_group_asset_operation]
                )

        return {
            "success": True,
            "resource_name": created_assets[0] if created_assets else None,
            "api_response": {"results": created_assets},
            "message": f"Added {len(created_assets)} AI-generated description{'' if len(created_assets) == 1 else 's'} to Performance Max",
            "descriptions": descriptions
        }

    except GoogleAdsException as ex:
        error_msg = f"Google Ads API error: {ex.error.code().name}"
        for error in ex.failure.errors:
            error_msg += f" - {error.message}"
        return {"success": False, "error": error_msg}
    except Exception as e:
        current_app.logger.error(f"Error adding PMax descriptions: {e}")
        return {"success": False, "error": str(e)}


def _apply_add_asset_groups(aid: int, customer_id: str, opt_data: dict, refresh_token: str) -> dict:
    """Create AI-generated asset groups for Performance Max campaigns."""
    try:
        from google.ads.googleads.client import GoogleAdsClient
        from google.ads.googleads.errors import GoogleAdsException
        from app.ai_clients import chatgpt_response
        import json

        # Create Google Ads client
        client_id, client_secret = _client_info("ads")
        credentials = {
            "developer_token": current_app.config.get("GOOGLE_ADS_DEVELOPER_TOKEN"),
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "token_uri": "https://oauth2.googleapis.com/token",
            "use_proto_plus": True
        }

        client = GoogleAdsClient.load_from_dict(credentials)

        # Get business name and existing PMax campaign
        google_ads_service = client.get_service("GoogleAdsService")
        query = """
            SELECT
                campaign.id,
                campaign.name
            FROM campaign
            WHERE campaign.advertising_channel_type = 'PERFORMANCE_MAX'
                AND campaign.status = 'ENABLED'
            LIMIT 1
        """
        response = google_ads_service.search(customer_id=customer_id, query=query)

        pmax_campaign_id = None
        business_name = "Your Business"
        for row in response:
            pmax_campaign_id = row.campaign.id
            business_name = row.campaign.name.split(" - ")[0].split(" | ")[0]
            break

        if not pmax_campaign_id:
            return {"success": False, "error": "No active Performance Max campaign found"}

        # How many asset groups to create
        current_count = opt_data.get('action_data', {}).get('current_count', 1)
        recommended_count = opt_data.get('action_data', {}).get('recommended_count', 3)
        num_to_create = min(recommended_count - current_count, 3)  # Max 3 at once

        current_app.logger.info(f"Generating {num_to_create} asset groups for {business_name}")

        # Generate asset group themes using AI
        prompt = f"""Generate {num_to_create} asset group themes for a Google Performance Max campaign.

Business: {business_name}

Each asset group should target a different product/service category or customer segment.

For each asset group, provide:
- A specific theme/category name
- 3 headlines (30 chars each)
- 2 descriptions (90 chars each)
- A suggested final URL path

Return ONLY valid JSON:
{{
  "asset_groups": [
    {{
      "name": "Service Name",
      "headlines": ["Headline 1", "Headline 2", "Headline 3"],
      "descriptions": ["Description 1", "Description 2"],
      "url_path": "/service-page"
    }}
  ]
}}"""

        ai_response = chatgpt_response(prompt)

        # Parse AI response
        if "```json" in ai_response:
            ai_response = ai_response.split("```json")[1].split("```")[0].strip()
        elif "```" in ai_response:
            ai_response = ai_response.split("```")[1].split("```")[0].strip()

        asset_group_data = json.loads(ai_response)

        # Get existing PMax assets (images) to reuse
        query = """
            SELECT
                asset.resource_name,
                asset.type,
                asset.image_asset.full_size.url
            FROM asset
            WHERE asset.type = 'IMAGE'
            LIMIT 5
        """
        image_assets = []
        try:
            response = google_ads_service.search(customer_id=customer_id, query=query)
            for row in response:
                image_assets.append(row.asset.resource_name)
        except:
            pass  # Images optional for now

        # Get website URL from campaign settings
        base_url = "https://example.com"
        query = f"""
            SELECT
                asset_group.final_urls
            FROM asset_group
            WHERE asset_group.campaign = 'customers/{customer_id}/campaigns/{pmax_campaign_id}'
            LIMIT 1
        """
        try:
            response = google_ads_service.search(customer_id=customer_id, query=query)
            for row in response:
                if row.asset_group.final_urls:
                    base_url = row.asset_group.final_urls[0]
                    break
        except:
            pass

        # Create asset groups
        asset_group_service = client.get_service("AssetGroupService")
        asset_service = client.get_service("AssetService")
        asset_group_asset_service = client.get_service("AssetGroupAssetService")

        created_groups = []
        campaign_resource_name = f"customers/{customer_id}/campaigns/{pmax_campaign_id}"

        for ag_data in asset_group_data.get("asset_groups", [])[:num_to_create]:
            # Create asset group
            asset_group_operation = client.get_type("AssetGroupOperation")
            asset_group = asset_group_operation.create

            asset_group.name = ag_data.get("name", "Asset Group")
            asset_group.campaign = campaign_resource_name
            asset_group.status = client.enums.AssetGroupStatusEnum.ENABLED

            # Set final URL
            url_path = ag_data.get("url_path", "")
            final_url = base_url.rstrip("/") + url_path if url_path else base_url
            asset_group.final_urls.append(final_url)

            ag_response = asset_group_service.mutate_asset_groups(
                customer_id=customer_id,
                operations=[asset_group_operation]
            )

            asset_group_resource_name = ag_response.results[0].resource_name
            created_groups.append(ag_data.get("name"))

            # Add headlines to asset group
            headline_operations = []
            for headline_text in ag_data.get("headlines", [])[:5]:
                # Create text asset
                asset_operation = client.get_type("AssetOperation")
                text_asset = asset_operation.create
                text_asset.text_asset.text = headline_text[:30]  # Max 30 chars
                text_asset.type_ = client.enums.AssetTypeEnum.TEXT

                asset_response = asset_service.mutate_assets(
                    customer_id=customer_id,
                    operations=[asset_operation]
                )

                # Link asset to asset group
                asset_group_asset_operation = client.get_type("AssetGroupAssetOperation")
                asset_group_asset = asset_group_asset_operation.create
                asset_group_asset.asset = asset_response.results[0].resource_name
                asset_group_asset.asset_group = asset_group_resource_name
                asset_group_asset.field_type = client.enums.AssetFieldTypeEnum.HEADLINE

                asset_group_asset_service.mutate_asset_group_assets(
                    customer_id=customer_id,
                    operations=[asset_group_asset_operation]
                )

            # Add descriptions to asset group
            for desc_text in ag_data.get("descriptions", [])[:4]:
                # Create text asset
                asset_operation = client.get_type("AssetOperation")
                text_asset = asset_operation.create
                text_asset.text_asset.text = desc_text[:90]  # Max 90 chars
                text_asset.type_ = client.enums.AssetTypeEnum.TEXT

                asset_response = asset_service.mutate_assets(
                    customer_id=customer_id,
                    operations=[asset_operation]
                )

                # Link asset to asset group
                asset_group_asset_operation = client.get_type("AssetGroupAssetOperation")
                asset_group_asset = asset_group_asset_operation.create
                asset_group_asset.asset = asset_response.results[0].resource_name
                asset_group_asset.asset_group = asset_group_resource_name
                asset_group_asset.field_type = client.enums.AssetFieldTypeEnum.DESCRIPTION

                asset_group_asset_service.mutate_asset_group_assets(
                    customer_id=customer_id,
                    operations=[asset_group_asset_operation]
                )

            # Add images if available
            if image_assets:
                for image_asset in image_assets[:3]:  # Add up to 3 images
                    asset_group_asset_operation = client.get_type("AssetGroupAssetOperation")
                    asset_group_asset = asset_group_asset_operation.create
                    asset_group_asset.asset = image_asset
                    asset_group_asset.asset_group = asset_group_resource_name
                    asset_group_asset.field_type = client.enums.AssetFieldTypeEnum.MARKETING_IMAGE

                    try:
                        asset_group_asset_service.mutate_asset_group_assets(
                            customer_id=customer_id,
                            operations=[asset_group_asset_operation]
                        )
                    except:
                        pass  # Image linking optional

        return {
            "success": True,
            "message": f"Created {len(created_groups)} asset group{'' if len(created_groups) == 1 else 's'}: {', '.join(created_groups)}",
            "asset_groups": created_groups
        }

    except GoogleAdsException as ex:
        error_msg = f"Google Ads API error: {ex.error.code().name}"
        for error in ex.failure.errors:
            error_msg += f" - {error.message}"
        return {"success": False, "error": error_msg}
    except Exception as e:
        current_app.logger.error(f"Error creating asset groups: {e}")
        return {"success": False, "error": str(e)}


def _apply_create_search_campaign(aid: int, customer_id: str, opt_data: dict, refresh_token: str) -> dict:
    """Create AI-generated Search campaign with keywords and RSA ads."""
    try:
        from google.ads.googleads.client import GoogleAdsClient
        from google.ads.googleads.errors import GoogleAdsException
        from app.ai_clients import chatgpt_response
        import json

        # Create Google Ads client
        client_id, client_secret = _client_info("ads")
        credentials = {
            "developer_token": current_app.config.get("GOOGLE_ADS_DEVELOPER_TOKEN"),
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "token_uri": "https://oauth2.googleapis.com/token",
            "use_proto_plus": True
        }

        client = GoogleAdsClient.load_from_dict(credentials)

        # Get business name from existing PMax campaign
        google_ads_service = client.get_service("GoogleAdsService")
        query = """
            SELECT campaign.name
            FROM campaign
            WHERE campaign.status = 'ENABLED'
            LIMIT 1
        """
        response = google_ads_service.search(customer_id=customer_id, query=query)
        business_name = "Your Business"
        for row in response:
            business_name = row.campaign.name.split(" - ")[0].split(" | ")[0]
            break

        # Generate campaign structure using AI
        current_app.logger.info(f"Generating Search campaign structure for {business_name}")

        prompt = f"""Generate a Google Search campaign structure for a business.

Business: {business_name}

Create JSON with:
- Campaign name
- 2-3 ad groups with targeted themes
- 5-10 relevant keywords per ad group (Phrase and Exact match)
- 1 RSA ad per ad group (10 headlines, 3 descriptions)

Return ONLY valid JSON:
{{
  "campaign_name": "Search - {business_name}",
  "daily_budget": 50,
  "ad_groups": [
    {{
      "name": "Brand",
      "keywords": [{{"text": "{business_name}", "match": "Exact"}}, ...],
      "rsa": {{
        "final_url": "https://example.com",
        "headlines": ["Headline 1", ...],
        "descriptions": ["Description 1", ...]
      }}
    }}
  ]
}}"""

        ai_response = chatgpt_response(prompt)

        # Parse AI response
        if "```json" in ai_response:
            ai_response = ai_response.split("```json")[1].split("```")[0].strip()
        elif "```" in ai_response:
            ai_response = ai_response.split("```")[1].split("```")[0].strip()

        campaign_data = json.loads(ai_response)

        # Create campaign
        campaign_service = client.get_service("CampaignService")
        campaign_operation = client.get_type("CampaignOperation")
        campaign = campaign_operation.create

        campaign.name = campaign_data.get("campaign_name", f"Search - {business_name}")
        campaign.advertising_channel_type = client.enums.AdvertisingChannelTypeEnum.SEARCH
        campaign.status = client.enums.CampaignStatusEnum.PAUSED  # Start paused for safety

        # Set EU political advertising declaration (required field in v21)
        # Must use enum value, not boolean
        campaign.contains_eu_political_advertising = (
            client.enums.EuPoliticalAdvertisingStatusEnum.DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING
        )

        # Set start and end dates (recommended practice)
        start_date = (datetime.utcnow() + timedelta(days=1)).strftime("%Y%m%d")
        end_date = (datetime.utcnow() + timedelta(days=365)).strftime("%Y%m%d")
        campaign.start_date = start_date
        campaign.end_date = end_date

        # Set up network settings (required field for Search campaigns)
        campaign.network_settings.target_google_search = True
        campaign.network_settings.target_search_network = True
        campaign.network_settings.target_content_network = False
        campaign.network_settings.target_partner_search_network = False

        # Set bidding strategy to Manual CPC
        # Initialize the manual_cpc object first (required for proper configuration)
        campaign.manual_cpc = client.get_type("ManualCpc")
        # Note: enhanced_cpc_enabled cannot be set during campaign creation in API v21
        # Note: campaign_budget will be set after creating the budget below

        # Create budget first
        budget_service = client.get_service("CampaignBudgetService")
        budget_operation = client.get_type("CampaignBudgetOperation")
        budget = budget_operation.create
        # Add timestamp and short UUID to ensure unique budget names
        timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        unique_id = str(uuid.uuid4())[:8]
        budget.name = f"Budget for {campaign.name} {timestamp}-{unique_id}"
        budget.amount_micros = int(campaign_data.get("daily_budget", 50) * 1_000_000)
        budget.delivery_method = client.enums.BudgetDeliveryMethodEnum.STANDARD

        budget_response = budget_service.mutate_campaign_budgets(
            customer_id=customer_id,
            operations=[budget_operation]
        )
        campaign.campaign_budget = budget_response.results[0].resource_name

        campaign_response = campaign_service.mutate_campaigns(
            customer_id=customer_id,
            operations=[campaign_operation]
        )

        campaign_resource_name = campaign_response.results[0].resource_name
        campaign_id = campaign_resource_name.split("/")[-1]

        # Create ad groups, keywords, and RSAs
        ad_group_service = client.get_service("AdGroupService")
        ad_group_criterion_service = client.get_service("AdGroupCriterionService")
        ad_group_ad_service = client.get_service("AdGroupAdService")

        created_ad_groups = 0
        created_keywords = 0
        created_ads = 0

        for ag_data in campaign_data.get("ad_groups", [])[:3]:  # Limit to 3 ad groups
            # Create ad group
            ad_group_operation = client.get_type("AdGroupOperation")
            ad_group = ad_group_operation.create
            ad_group.name = ag_data.get("name", "Ad Group")
            ad_group.campaign = campaign_resource_name
            ad_group.status = client.enums.AdGroupStatusEnum.ENABLED
            ad_group.cpc_bid_micros = 2_000_000  # $2 default bid

            ag_response = ad_group_ad_service = client.get_service("AdGroupService")
            ag_response = ag_response.mutate_ad_groups(
                customer_id=customer_id,
                operations=[ad_group_operation]
            )
            ad_group_resource_name = ag_response.results[0].resource_name
            created_ad_groups += 1

            # Add keywords
            keyword_operations = []
            for kw_data in ag_data.get("keywords", [])[:10]:  # Limit to 10 keywords
                kw_operation = client.get_type("AdGroupCriterionOperation")
                keyword = kw_operation.create
                keyword.ad_group = ad_group_resource_name
                keyword.status = client.enums.AdGroupCriterionStatusEnum.ENABLED
                keyword.keyword.text = kw_data.get("text", "")
                keyword.keyword.match_type = (
                    client.enums.KeywordMatchTypeEnum.EXACT
                    if kw_data.get("match") == "Exact"
                    else client.enums.KeywordMatchTypeEnum.PHRASE
                )
                keyword_operations.append(kw_operation)

            if keyword_operations:
                ad_group_criterion_service.mutate_ad_group_criteria(
                    customer_id=customer_id,
                    operations=keyword_operations
                )
                created_keywords += len(keyword_operations)

            # Create RSA
            rsa_data = ag_data.get("rsa", {})
            if rsa_data:
                ad_operation = client.get_type("AdGroupAdOperation")
                ad_group_ad = ad_operation.create
                ad_group_ad.ad_group = ad_group_resource_name
                ad_group_ad.status = client.enums.AdGroupAdStatusEnum.ENABLED

                rsa = ad_group_ad.ad.responsive_search_ad
                ad_group_ad.ad.final_urls.append(rsa_data.get("final_url", "https://example.com"))

                for headline in rsa_data.get("headlines", [])[:15]:
                    h = client.get_type("AdTextAsset")
                    h.text = headline[:30]
                    rsa.headlines.append(h)

                for description in rsa_data.get("descriptions", [])[:4]:
                    d = client.get_type("AdTextAsset")
                    d.text = description[:90]
                    rsa.descriptions.append(d)

                ad_group_ad_service = client.get_service("AdGroupAdService")
                ad_group_ad_service.mutate_ad_group_ads(
                    customer_id=customer_id,
                    operations=[ad_operation]
                )
                created_ads += 1

        return {
            "success": True,
            "resource_name": campaign_resource_name,
            "message": f"Created Search campaign '{campaign.name}' with {created_ad_groups} ad groups, {created_keywords} keywords, {created_ads} RSA ads (campaign starts PAUSED - review and enable when ready)",
            "campaign_id": campaign_id,
            "campaign_name": campaign.name,
            "ad_groups": created_ad_groups,
            "keywords": created_keywords,
            "ads": created_ads
        }

    except GoogleAdsException as ex:
        error_msg = f"Google Ads API error: {ex.error.code().name}"
        for error in ex.failure.errors:
            error_msg += f" - {error.message}"
            # Log field path elements to identify which field is causing the issue
            if error.location:
                for field_path_element in error.location.field_path_elements:
                    error_msg += f" (field: {field_path_element.field_name})"
        current_app.logger.error(f"GoogleAdsException details: {error_msg}")
        return {"success": False, "error": error_msg}
    except Exception as e:
        current_app.logger.error(f"Error creating Search campaign: {e}")
        current_app.logger.exception("Full exception traceback:")
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
        elif "price" in ext_type:
            return _create_price_extension(client, customer_id, opt_data)
        elif "location" in ext_type:
            # Location extensions - auto-complete with GMB prerequisite check
            return _create_location_extension(client, customer_id, opt_data, aid)
        else:
            return {
                "success": False,
                "error": f"Extension type '{ext_type}' not yet supported. Supported: Callout, Sitelink, Call, Structured Snippet, Price"
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
    """Create sitelink assets (API v21) with auto-generated standard links."""
    try:
        # Get website URL from account or use empty string
        website_url = opt_data.get("website_url", "")
        if not website_url:
            # Try to get from campaigns
            campaign_service = client.get_service("GoogleAdsService")
            query = """
                SELECT campaign.final_url_suffix, campaign.name
                FROM campaign
                WHERE campaign.status = 'ENABLED'
                LIMIT 1
            """
            try:
                response = campaign_service.search(customer_id=customer_id, query=query)
                for row in response:
                    if hasattr(row.campaign, 'final_url_suffix') and row.campaign.final_url_suffix:
                        website_url = row.campaign.final_url_suffix.split('/')[0]
                        break
            except:
                pass

        # Default to example.com if no URL found (user will need to update)
        if not website_url:
            website_url = "https://example.com"

        # Ensure URL has protocol
        if not website_url.startswith('http'):
            website_url = f"https://{website_url}"

        # Remove trailing slash
        website_url = website_url.rstrip('/')

        # Standard sitelinks for service businesses
        sitelinks = [
            {"text": "Contact Us", "url": f"{website_url}/contact", "description1": "Get in touch today", "description2": "Fast response time"},
            {"text": "Our Services", "url": f"{website_url}/services", "description1": "Full service offerings", "description2": "Expert solutions"},
            {"text": "About Us", "url": f"{website_url}/about", "description1": "Learn our story", "description2": "Trusted experts"},
            {"text": "Get a Quote", "url": f"{website_url}/quote", "description1": "Free estimates", "description2": "No obligation"},
        ]

        asset_service = client.get_service("AssetService")
        customer_asset_service = client.get_service("CustomerAssetService")

        created_assets = []

        # Step 1: Create sitelink assets
        for link in sitelinks:
            asset_operation = client.get_type("AssetOperation")
            asset = asset_operation.create
            asset.name = f"Sitelink: {link['text']}"

            # Set the sitelink data
            sitelink = asset.sitelink_asset
            sitelink.link_text = link['text']
            sitelink.description1 = link['description1']
            sitelink.description2 = link['description2']
            sitelink.final_url = link['url']

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
                customer_asset.field_type = client.enums.AssetFieldTypeEnum.SITELINK

                customer_asset_service.mutate_customer_assets(
                    customer_id=customer_id,
                    operations=[customer_asset_operation]
                )

        link_texts = [link['text'] for link in sitelinks]
        return {
            "success": True,
            "resource_name": created_assets[0] if created_assets else None,
            "api_response": {"results": created_assets},
            "message": f"Created {len(created_assets)} sitelink assets: {', '.join(link_texts)}"
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


def _create_call_extension(client, customer_id: str, opt_data: dict) -> dict:
    """Create call extension asset (API v21) with auto-detected or placeholder phone."""
    try:
        # Try to get phone number from opt_data, account, or use placeholder
        phone_number = opt_data.get("phone_number", "")

        if not phone_number:
            # Try to detect from existing call extensions or campaigns
            try:
                google_ads_service = client.get_service("GoogleAdsService")
                query = """
                    SELECT asset.call_asset.phone_number
                    FROM asset
                    WHERE asset.type = 'CALL'
                    LIMIT 1
                """
                response = google_ads_service.search(customer_id=customer_id, query=query)
                for row in response:
                    if hasattr(row.asset, 'call_asset') and row.asset.call_asset.phone_number:
                        phone_number = row.asset.call_asset.phone_number
                        break
            except:
                pass

        # Use placeholder if still not found (user can update later in Google Ads UI)
        if not phone_number:
            phone_number = "+1-800-555-0100"  # Standard placeholder
            message_suffix = " (Using placeholder number - please update in Google Ads UI with your actual phone)"
        else:
            message_suffix = ""

        # Format phone number (remove spaces, dashes, parens)
        phone_clean = phone_number.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
        if not phone_clean.startswith("+"):
            # Assume US number if no country code
            phone_clean = f"+1{phone_clean}"

        # Get country code (default to US)
        country_code = opt_data.get("country_code", "US")

        asset_service = client.get_service("AssetService")
        customer_asset_service = client.get_service("CustomerAssetService")

        # Step 1: Create call asset
        asset_operation = client.get_type("AssetOperation")
        asset = asset_operation.create
        asset.name = "Call Extension: Business Phone"

        # Set the call data
        call_asset = asset.call_asset
        call_asset.phone_number = phone_clean
        call_asset.country_code = country_code
        call_asset.call_conversion_reporting_state = client.enums.CallConversionReportingStateEnum.USE_ACCOUNT_LEVEL_CALL_CONVERSION_ACTION

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
            customer_asset.field_type = client.enums.AssetFieldTypeEnum.CALL

            customer_asset_service.mutate_customer_assets(
                customer_id=customer_id,
                operations=[customer_asset_operation]
            )

        return {
            "success": True,
            "resource_name": asset_resource_name,
            "api_response": {"results": [asset_resource_name]},
            "message": f"Created call extension with phone: {phone_number}{message_suffix}"
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


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


def _create_price_extension(client, customer_id: str, opt_data: dict) -> dict:
    """Create price asset (API v21) with standard service pricing tiers."""
    try:
        # Get website URL from campaigns for price item URLs
        website_url = "https://example.com"
        campaign_service = client.get_service("GoogleAdsService")
        query = """
            SELECT campaign.final_url_suffix, campaign.name
            FROM campaign
            WHERE campaign.status = 'ENABLED'
            LIMIT 1
        """
        try:
            response = campaign_service.search(customer_id=customer_id, query=query)
            for row in response:
                # Try to extract base domain from campaign data if available
                pass
        except:
            pass

        # Standard service pricing tiers
        price_offerings = [
            {"header": "Basic Service", "description": "Standard maintenance & repairs", "price": 99, "unit": "USD"},
            {"header": "Emergency Service", "description": "24/7 urgent repairs", "price": 199, "unit": "USD"},
            {"header": "Inspection", "description": "Complete system check", "price": 79, "unit": "USD"},
            {"header": "Installation", "description": "New system setup", "price": 499, "unit": "USD"},
        ]

        asset_service = client.get_service("AssetService")
        customer_asset_service = client.get_service("CustomerAssetService")

        # Step 1: Create price asset
        asset_operation = client.get_type("AssetOperation")
        asset = asset_operation.create
        asset.name = "Price Extension: Services"

        # Set the price asset data
        price_asset = asset.price_asset
        price_asset.type_ = client.enums.PriceExtensionTypeEnum.SERVICES
        price_asset.price_qualifier = client.enums.PriceExtensionPriceQualifierEnum.FROM
        price_asset.language_code = "en"

        # Add price offerings
        for offering in price_offerings:
            price_offering = client.get_type("PriceOffering")
            price_offering.header = offering["header"]
            price_offering.description = offering["description"]
            price_offering.price.amount_micros = int(offering["price"] * 1_000_000)
            price_offering.price.currency_code = offering["unit"]
            price_offering.unit = client.enums.PriceExtensionPriceUnitEnum.PER_HOUR
            price_offering.final_url = website_url

            price_asset.price_offerings.append(price_offering)

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
            customer_asset.field_type = client.enums.AssetFieldTypeEnum.PRICE

            customer_asset_service.mutate_customer_assets(
                customer_id=customer_id,
                operations=[customer_asset_operation]
            )

        price_summary = ", ".join([f"{p['header']}: ${p['price']}" for p in price_offerings])
        return {
            "success": True,
            "resource_name": asset_resource_name,
            "api_response": {"results": [asset_resource_name]},
            "message": f"Created price extension with {len(price_offerings)} service tiers: {price_summary}"
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


def _create_location_extension(client, customer_id: str, opt_data: dict, aid: int) -> dict:
    """
    Create location extension using Google My Business data.
    Auto-complete with GMB prerequisite check.
    """
    try:
        # Step 1: Check if GMB is connected for this account
        gmb_connected = _check_gmb_connection(aid)

        if not gmb_connected:
            return {
                "success": False,
                "error": "Location extensions require Google Business Profile connection. To enable auto-complete: 1) Connect your Google Business Profile in Settings, 2) Come back and click 'Apply' again to auto-configure your location extension.",
                "requires_prerequisite": "gmb_connection",
                "prerequisite_url": "/account/google/auth/gmb"
            }

        # Step 2: Get GMB location data
        gmb_locations = _get_gmb_locations(aid)

        if not gmb_locations:
            return {
                "success": False,
                "error": "No Google Business Profile locations found. Please ensure you have at least one business location set up in your Google Business Profile.",
                "requires_prerequisite": "gmb_locations"
            }

        # Step 3: Link GMB location feed to Google Ads (this creates location extension automatically)
        # Google Ads API will automatically create location extensions from linked GMB locations
        location_feed_service = client.get_service("FeedService")

        # Create location feed linked to GMB
        feed_operation = client.get_type("FeedOperation")
        feed = feed_operation.create
        feed.name = "Location Extensions"
        feed.origin = client.enums.FeedOriginEnum.GOOGLE

        # The affiliate location feed uses GMB data
        feed.affiliate_location_feed_data.chain_ids.append(gmb_locations[0].get('chain_id', ''))

        # Create the feed
        feed_response = location_feed_service.mutate_feeds(
            customer_id=customer_id,
            operations=[feed_operation]
        )

        resource_name = feed_response.results[0].resource_name if feed_response.results else None

        return {
            "success": True,
            "resource_name": resource_name,
            "api_response": {"results": [resource_name]},
            "message": f"Location extension linked to {len(gmb_locations)} Google Business Profile location(s)"
        }

    except Exception as e:
        current_app.logger.exception("Error creating location extension")
        return {"success": False, "error": str(e)}


def _apply_create_rsa_ads(aid: int, customer_id: str, opt_data: dict, refresh_token: str) -> dict:
    """
    Create AI-generated RSA ads for ad groups with headlines and descriptions.
    This handles the complete "Create ads for ad groups" auto-complete optimization.
    """
    try:
        from google.ads.googleads.client import GoogleAdsClient
        from google.ads.googleads.errors import GoogleAdsException

        # Get ad groups and keywords from opt_data
        ad_groups = opt_data.get('ad_groups', [])
        keywords_by_ad_group = opt_data.get('keywords_by_ad_group', {})

        if not ad_groups:
            return {"success": False, "error": "No ad groups provided"}

        # Create Google Ads client
        client_id, client_secret = _client_info("ads")
        credentials = {
            "developer_token": current_app.config.get("GOOGLE_ADS_DEVELOPER_TOKEN"),
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "token_uri": "https://oauth2.googleapis.com/token",
            "use_proto_plus": True
        }

        client = GoogleAdsClient.load_from_dict(credentials)
        ad_group_ad_service = client.get_service("AdGroupAdService")

        # Get business info from account
        business_name = _get_business_name_from_account(aid, customer_id, client)

        created_ads = 0
        operations = []

        for ad_group in ad_groups[:5]:  # Limit to first 5 ad groups to avoid rate limits
            ad_group_id = ad_group.get('id')
            ad_group_name = ad_group.get('name', 'Ad Group')

            if not ad_group_id:
                continue

            # Get keywords for this ad group
            keywords = keywords_by_ad_group.get(ad_group_id, [])

            if not keywords:
                continue

            # Generate AI-powered headlines and descriptions
            ai_result = _generate_complete_rsa_ad(business_name, ad_group_name, keywords)

            if not ai_result.get("success"):
                current_app.logger.warning(f"AI generation failed for ad group {ad_group_id}: {ai_result.get('error')}")
                continue

            headlines = ai_result.get("headlines", [])
            descriptions = ai_result.get("descriptions", [])

            if len(headlines) < 3 or len(descriptions) < 2:
                current_app.logger.warning(f"Insufficient ad content generated for ad group {ad_group_id}")
                continue

            # Create RSA ad
            ad_group_ad_operation = client.get_type("AdGroupAdOperation")
            ad_group_ad = ad_group_ad_operation.create
            ad_group_ad.ad_group = client.get_service("AdGroupAdService").ad_group_path(customer_id, ad_group_id)
            ad_group_ad.status = client.enums.AdGroupAdStatusEnum.PAUSED  # Start PAUSED for review

            # Set ad final URL (try to get from campaign or use example)
            final_url = _get_campaign_final_url(customer_id, client, ad_group.get('campaign_id'))
            ad_group_ad.ad.final_urls.append(final_url)

            # Create RSA with AI-generated content
            rsa = ad_group_ad.ad.responsive_search_ad

            # Add headlines (up to 15)
            for headline in headlines[:15]:
                headline_asset = client.get_type("AdTextAsset")
                headline_asset.text = headline
                rsa.headlines.append(headline_asset)

            # Add descriptions (up to 4)
            for description in descriptions[:4]:
                description_asset = client.get_type("AdTextAsset")
                description_asset.text = description
                rsa.descriptions.append(description_asset)

            operations.append(ad_group_ad_operation)
            created_ads += 1

        if not operations:
            return {"success": False, "error": "Failed to generate ad content for any ad groups"}

        # Execute ad creation
        response = ad_group_ad_service.mutate_ad_group_ads(
            customer_id=customer_id,
            operations=operations
        )

        return {
            "success": True,
            "message": f"Created {created_ads} RSA ad{'' if created_ads == 1 else 's'} with AI-generated headlines and descriptions (starting PAUSED for review)",
            "resource_name": response.results[0].resource_name if response.results else None,
            "api_response": {
                "created_ads": created_ads,
                "ad_group_count": len(ad_groups)
            }
        }

    except GoogleAdsException as ex:
        error_msg = f"Google Ads API error: {ex.error.code().name}"
        for error in ex.failure.errors:
            error_msg += f" - {error.message}"
        return {"success": False, "error": error_msg}
    except Exception as e:
        current_app.logger.exception(f"Error creating RSA ads")
        return {"success": False, "error": str(e)}


def _generate_complete_rsa_ad(business_name: str, ad_group_name: str, keywords: list) -> dict:
    """Generate complete RSA ad with 15 headlines and 4 descriptions using AI."""
    try:
        from app.ai_clients import chatgpt_response
        import json

        keywords_text = ", ".join(keywords[:10])  # Use first 10 keywords

        prompt = f"""Generate a complete Responsive Search Ad for Google Ads.

Business: {business_name}
Ad Group: {ad_group_name}
Keywords: {keywords_text}

Requirements:
- Headlines: 15 unique headlines (max 30 chars each)
- Descriptions: 4 unique descriptions (max 90 chars each)
- Make them relevant to the keywords
- Include variety: urgency, benefits, credibility, action-oriented
- Focus on what makes this business stand out

Return ONLY valid JSON in this format:
{{
  "headlines": ["Fast Service - Call Now", "Licensed Professionals", ...],
  "descriptions": ["Get professional service from licensed experts. Same-day appointments available.", ...]
}}"""

        response = chatgpt_response(prompt)

        try:
            if "```json" in response:
                response = response.split("```json")[1].split("```")[0].strip()
            elif "```" in response:
                response = response.split("```")[1].split("```")[0].strip()

            result = json.loads(response)

            if "headlines" not in result or "descriptions" not in result:
                raise ValueError("Missing headlines or descriptions field")

            # Truncate to character limits
            headlines = [h[:30] for h in result["headlines"][:15]]
            descriptions = [d[:90] for d in result["descriptions"][:4]]

            return {
                "success": True,
                "headlines": headlines,
                "descriptions": descriptions
            }

        except json.JSONDecodeError as e:
            return {"success": False, "error": f"AI returned invalid JSON: {str(e)}"}

    except Exception as e:
        current_app.logger.exception("Error generating RSA ad content")
        return {"success": False, "error": str(e)}


def _get_business_name_from_account(aid: int, customer_id: str, client) -> str:
    """Get business name from campaigns or account name."""
    try:
        google_ads_service = client.get_service("GoogleAdsService")
        query = """
            SELECT campaign.name
            FROM campaign
            WHERE campaign.status = 'ENABLED'
            LIMIT 1
        """
        results = google_ads_service.search(customer_id=customer_id, query=query)
        for row in results:
            return row.campaign.name

        # Fallback to customer name
        query2 = "SELECT customer.descriptive_name FROM customer"
        results2 = google_ads_service.search(customer_id=customer_id, query=query2)
        for row in results2:
            if row.customer.descriptive_name:
                return row.customer.descriptive_name

    except Exception:
        pass

    return "Your Business"


def _get_campaign_final_url(customer_id: str, client, campaign_id: int = None) -> str:
    """Get final URL from campaign or return example URL."""
    try:
        google_ads_service = client.get_service("GoogleAdsService")
        query = """
            SELECT campaign.final_url_suffix
            FROM campaign
            WHERE campaign.status = 'ENABLED'
            LIMIT 1
        """
        results = google_ads_service.search(customer_id=customer_id, query=query)
        for row in results:
            if row.campaign.final_url_suffix:
                return row.campaign.final_url_suffix

    except Exception:
        pass

    return "https://www.example.com"


def _check_gmb_connection(aid: int) -> bool:
    """Check if Google My Business / Google Business Profile is connected for this account."""
    try:
        with db.engine.connect() as conn:
            row = conn.execute(
                text("SELECT id FROM google_oauth_tokens WHERE account_id=:aid AND product='gmb' ORDER BY id DESC LIMIT 1"),
                {"aid": aid},
            ).mappings().first()
        return row is not None
    except Exception:
        current_app.logger.exception("Error checking GMB connection")
        return False


def _get_gmb_locations(aid: int) -> list:
    """
    Get Google My Business locations for this account.
    Returns list of location data from GMB API.
    """
    try:
        # Get GMB OAuth tokens
        with db.engine.connect() as conn:
            row = conn.execute(
                text("SELECT credentials_json FROM google_oauth_tokens WHERE account_id=:aid AND product='gmb' ORDER BY id DESC LIMIT 1"),
                {"aid": aid},
            ).mappings().first()

        if not row:
            return []

        creds = json.loads(row["credentials_json"])
        access_token = creds.get("access_token")

        if not access_token:
            return []

        # Call GMB API to get locations
        # Using Google My Business API v4.9
        response = requests.get(
            "https://mybusinessbusinessinformation.googleapis.com/v1/accounts/-/locations",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10
        )

        if response.ok:
            data = response.json()
            locations = data.get("locations", [])
            return locations
        else:
            current_app.logger.warning(f"GMB API error: {response.status_code} {response.text[:200]}")
            return []

    except Exception:
        current_app.logger.exception("Error getting GMB locations")
        return []


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
        preview_mode = data.get("preview", False)  # Preview mode: return what would be created without applying

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

        # Apply each optimization via Google Ads API (or preview what would be created)
        results = []
        applied_count = 0
        failed_count = 0

        for opt in optimizations:
            opt_type = opt.get("optimization_type", "")
            opt_title = opt.get("title", "")
            opt_data = opt.get("optimization_data", {})

            # Skip database tracking in preview mode
            if not preview_mode:
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
                # Apply the optimization (or generate preview)
                result = _apply_optimization(aid, customer_id, opt_type, opt_data, opt_title, preview=preview_mode)

                if result.get("success"):
                    if not preview_mode:
                        applied_opt.status = 'applied'
                        applied_opt.resource_name = result.get("resource_name")
                        applied_opt.api_response = result.get("api_response")
                        applied_opt.applied_at = datetime.utcnow()
                    applied_count += 1
                    results.append({
                        "optimization": opt_title,
                        "type": opt_type,
                        "status": "preview" if preview_mode else "applied",
                        "resource_name": result.get("resource_name"),
                        "message": result.get("message", "Successfully applied"),
                        "preview_data": result.get("preview_data") if preview_mode else None
                    })
                else:
                    if not preview_mode:
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
                if not preview_mode:
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

        if not preview_mode:
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
    Run all 11 AI agents and convert their decisions into optimization opportunities for the ads UI.

    Agents:
    - 1 Strategic: Long-term planning and goal-setting
    - 3 Operational: Daily management and coordination
    - 4 Tactical (Search): Keyword, ad copy, negative keyword, landing page optimization
    - 3 Performance Max: Asset performance, audience signals, campaign structure

    Returns: List of opportunity dictionaries compatible with the UI format.
    """
    opportunities = []

    try:
        # Import agents (8 Search + 3 Performance Max = 11 total)
        from app.agents import (
            # Strategic Layer (1)
            StrategicDirectorAgent,
            # Operational Layer (3)
            CampaignManagerAgent,
            BudgetGuardianAgent,
            QualityScoreAgent,
            # Tactical Layer (4)
            KeywordOptimizerAgent,
            NegativeKeywordAgent,
            AdCopyAgent,
            LandingPageAnalystAgent,
            # Performance Max Layer (3)
            AssetPerformanceAgent,
            AudienceSignalAgent,
            PMaxCampaignStructureAgent,
            # Infrastructure
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
        asset_groups = ads_data.get("asset_groups", [])  # Performance Max
        pmax_assets = ads_data.get("pmax_assets", [])    # Performance Max assets

        # Calculate performance metrics for agent context
        total_cost = sum(c.get("cost_30d", 0) or 0 for c in campaigns)
        total_clicks = sum(c.get("clicks", 0) or 0 for c in campaigns)
        total_conversions = sum(c.get("conversions", 0) or 0 for c in campaigns)

        # Separate Performance Max from Search campaigns
        pmax_campaigns = [c for c in campaigns if c.get('type') == 'PERFORMANCE_MAX']
        search_campaigns = [c for c in campaigns if c.get('type') != 'PERFORMANCE_MAX']

        context = {
            'account_id': aid,
            'customer_id': customer_id or '',
            'has_pmax_campaigns': len(pmax_campaigns) > 0,
            'has_search_campaigns': len(search_campaigns) > 0,
            'performance_90d': {
                'spend': total_cost * 3,  # Estimate 90-day from 30-day
                'conversions': total_conversions * 3,
                'cost_per_conversion': (total_cost / total_conversions) if total_conversions > 0 else 0,
            },
            'campaigns': [
                {
                    'id': str(c.get('id', '')),
                    'name': c.get('name', ''),
                    'type': c.get('type', ''),  # PERFORMANCE_MAX, SEARCH, etc.
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
            # Performance Max specific data
            'asset_groups': [
                {
                    'id': str(asg.get('id', '')),
                    'name': asg.get('name', ''),
                    'campaign_id': str(asg.get('campaign_id', '')),
                    'status': asg.get('status', ''),
                }
                for asg in asset_groups
            ],
            'pmax_assets': pmax_assets,  # Full asset list for agents to analyze
            'pmax_summary': {
                'asset_groups_count': len(asset_groups),
                'total_assets': len(pmax_assets),
                'headlines_count': len([a for a in pmax_assets if a.get('field_type') == 'HEADLINE']),
                'descriptions_count': len([a for a in pmax_assets if a.get('field_type') == 'DESCRIPTION']),
                'images_count': len([a for a in pmax_assets if a.get('asset_type') == 'IMAGE']),
            },
            'total_budget': total_cost,
            'target_cpa': 100,  # Default target
            'business_goals': {
                'target_roas': 3.0,
                'target_cpl': 80,
                'customer_value': 500,
            }
        }

        # Initialize all 11 agents (8 Search + 3 Performance Max)
        agents = [
            # Strategic Layer
            StrategicDirectorAgent(event_bus=event_bus, decision_log=decision_log),
            # Operational Layer
            CampaignManagerAgent(event_bus=event_bus, decision_log=decision_log),
            BudgetGuardianAgent(event_bus=event_bus, decision_log=decision_log),
            QualityScoreAgent(event_bus=event_bus, decision_log=decision_log),
            # Tactical Layer (Search campaigns)
            KeywordOptimizerAgent(event_bus=event_bus, decision_log=decision_log),
            NegativeKeywordAgent(event_bus=event_bus, decision_log=decision_log),
            AdCopyAgent(event_bus=event_bus, decision_log=decision_log),
            LandingPageAnalystAgent(event_bus=event_bus, decision_log=decision_log),
            # Performance Max Layer
            AssetPerformanceAgent(event_bus=event_bus, decision_log=decision_log),
            AudienceSignalAgent(event_bus=event_bus, decision_log=decision_log),
            PMaxCampaignStructureAgent(event_bus=event_bus, decision_log=decision_log),
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
                            'decision_type': decision.decision_type,
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

        current_app.logger.info(f"11 AI Agents (8 Search + 3 PMax) generated {len(opportunities)} total opportunities for account {aid}")

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
        # Strategic & Operational
        'strategic': 'fa-chess-king',
        'operational': 'fa-gauge-high',
        'campaign_manager': 'fa-chart-line',
        'budget_guardian': 'fa-shield-halved',
        'quality_score_doctor': 'fa-star',
        # Tactical (Search)
        'keyword_optimizer': 'fa-key',
        'negative_keyword_agent': 'fa-ban',
        'ad_copy_scientist': 'fa-pen-to-square',
        'landing_page_analyst': 'fa-desktop',
        # Performance Max
        'AssetPerformanceAgent': 'fa-images',
        'AudienceSignalAgent': 'fa-users',
        'PMaxCampaignStructureAgent': 'fa-layer-group',
    }
    return icons.get(agent_type, 'fa-robot')


def _get_agent_color(agent_type: str) -> str:
    """Get color for agent type."""
    colors = {
        # Strategic & Operational
        'strategic': 'purple',
        'operational': 'blue',
        'campaign_manager': 'blue',
        'budget_guardian': 'red',
        'quality_score_doctor': 'yellow',
        # Tactical (Search)
        'keyword_optimizer': 'green',
        'negative_keyword_agent': 'red',
        'ad_copy_scientist': 'purple',
        'landing_page_analyst': 'orange',
        # Performance Max
        'AssetPerformanceAgent': 'purple',
        'AudienceSignalAgent': 'blue',
        'PMaxCampaignStructureAgent': 'green',
    }
    return colors.get(agent_type, 'gray')


def _create_optimization_bundles(opportunities: list) -> list:
    """
    Create smart bundles of complementary optimizations that work better together.

    Returns list of bundles with metadata about synergies.
    """
    bundles = []
    opp_titles = {opp.get("title"): opp for opp in opportunities}

    # Bundle 1: Mobile Power Combo (3x better together)
    mobile_bid = next((o for o in opportunities if o.get("optimization_type") == "mobile_bid"), None)
    mobile_ads = next((o for o in opportunities if o.get("optimization_type") == "mobile_ads"), None)
    call_ext = next((o for o in opportunities if o.get("optimization_type") == "extension" and "call" in o.get("optimization_data", {}).get("type", "").lower()), None)

    if mobile_bid or mobile_ads or call_ext:
        mobile_bundle_opps = [o for o in [mobile_bid, mobile_ads, call_ext] if o]
        if len(mobile_bundle_opps) >= 2:
            bundles.append({
                "id": "mobile_power_combo",
                "title": "🔥 Mobile Power Combo",
                "description": "These mobile optimizations work 3x better together - bid higher + show mobile ads + enable tap-to-call",
                "optimizations": mobile_bundle_opps,
                "total_time": sum(int(o.get("estimated_time", "0").split()[0]) for o in mobile_bundle_opps if o.get("estimated_time", "0")[0].isdigit()),
                "synergy_score": 95,
                "impact_multiplier": "3x",
                "recommendation": "Apply all together for maximum mobile traffic capture"
            })

    # Bundle 2: Extension Suite (complete your ad real estate)
    extension_types = ["call", "sitelink", "callout", "price", "structured_snippet"]
    extension_opps = [
        o for o in opportunities
        if o.get("optimization_type") == "extension"
        and any(ext in o.get("optimization_data", {}).get("type", "").lower() for ext in extension_types)
    ]

    if len(extension_opps) >= 3:
        bundles.append({
            "id": "extension_suite",
            "title": "⚡ Quick Wins: Extension Suite",
            "description": f"Apply {len(extension_opps)} extensions in {len(extension_opps)} minutes - each adds 5-20% CTR boost",
            "optimizations": extension_opps,
            "total_time": len(extension_opps),  # 1 min each
            "synergy_score": 85,
            "impact_multiplier": "Compound CTR gains",
            "recommendation": "Extensions stack - more extensions = larger ads = higher CTR"
        })

    # Bundle 3: AI Content Generator (let AI write your ads)
    ai_content_opps = [
        o for o in opportunities
        if o.get("optimization_type") in ["pmax_headlines", "pmax_descriptions", "rsa_headline_variations", "mobile_ads"]
    ]

    if len(ai_content_opps) >= 2:
        bundles.append({
            "id": "ai_content_generator",
            "title": "🤖 AI Content Generator",
            "description": f"Let AI write {len(ai_content_opps)} types of ad content in minutes - saves hours of copywriting",
            "optimizations": ai_content_opps,
            "total_time": len(ai_content_opps),  # ~1 min each
            "synergy_score": 80,
            "impact_multiplier": "Time savings",
            "recommendation": "AI-generated content is ready to test immediately"
        })

    # Bundle 4: Negative Keywords Foundation (block waste first)
    negative_opps = [
        o for o in opportunities
        if o.get("optimization_type") in ["negative_keyword", "starter_negative_keywords"]
    ]

    if negative_opps:
        bundles.append({
            "id": "negative_keywords_foundation",
            "title": "📊 Complete Your Setup: Negative Keywords",
            "description": "Block non-buyer searches before spending more on campaigns",
            "optimizations": negative_opps,
            "total_time": sum(int(o.get("estimated_time", "0").split()[0]) for o in negative_opps if o.get("estimated_time", "0")[0].isdigit()),
            "synergy_score": 90,
            "impact_multiplier": "Waste reduction",
            "recommendation": "Apply these first to stop wasting budget, then invest in new campaigns"
        })

    # Bundle 5: Search Campaign Starter Pack (for PMax-only accounts)
    search_campaign = next((o for o in opportunities if o.get("optimization_data", {}).get("decision_type") == "create_search_campaign"), None)
    rsa_headlines = next((o for o in opportunities if o.get("optimization_type") == "rsa_headline_variations"), None)

    if search_campaign:
        search_bundle_opps = [search_campaign]
        if rsa_headlines:
            search_bundle_opps.append(rsa_headlines)

        bundles.append({
            "id": "search_campaign_starter",
            "title": "🎯 Search Campaign Starter Pack",
            "description": "Create your first Search campaign with AI-generated keywords, ad groups, and RSA ads",
            "optimizations": search_bundle_opps,
            "total_time": 2,
            "synergy_score": 95,
            "impact_multiplier": "Keyword-level control",
            "recommendation": "CRITICAL: Add Search campaigns alongside Performance Max for better control and insights"
        })

    # Sort bundles by synergy score (highest impact first)
    bundles.sort(key=lambda b: b["synergy_score"], reverse=True)

    return bundles


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

        # Get first enabled SEARCH campaign ID for applying the optimization
        # Performance Max campaigns don't support device bid adjustments
        first_campaign_id = next(
            (c.get("id") for c in campaigns
             if c.get("status", "").lower() in ("enabled", "active")
             and c.get("type") != "PERFORMANCE_MAX"),
            None
        )

        current_app.logger.info(
            f"Mobile optimization: scores[mobile]={scores['mobile']}, "
            f"first_campaign_id={first_campaign_id}, "
            f"will_create_mobile_bid_opp={bool(first_campaign_id)}"
        )

        # Only create mobile bid adjustment for Search campaigns (not Performance Max)
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

        # Mobile-preferred ads - Only for Search campaigns (not Performance Max)
        # Performance Max campaigns use asset groups, not traditional RSAs
        # Check if there are any Search campaigns (first_campaign_id will be None if only PMax)
        if first_campaign_id:
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

    # Performance Max campaigns use asset groups instead of ad groups
    asset_groups = ads_data.get("asset_groups", [])
    pmax_assets = ads_data.get("pmax_assets", [])
    pmax_campaigns = [c for c in campaigns if c.get('type') == 'PERFORMANCE_MAX']
    search_campaigns = [c for c in campaigns if c.get('type') != 'PERFORMANCE_MAX']

    setup_checks = {
        'has_conversion_tracking': total_conversions > 0,
        'has_campaigns': len(campaigns) > 0,
        'has_pmax_campaigns': len(pmax_campaigns) > 0,
        'has_search_campaigns': len(search_campaigns) > 0,
        'has_ad_groups': len(ad_groups) > 0,  # Search campaigns only
        'has_asset_groups': len(asset_groups) > 0,  # Performance Max only
        'has_keywords': len(keywords) > 0,  # Search campaigns only
        'has_ads': len(ads) > 0,  # Search RSAs
        'has_pmax_assets': len(pmax_assets) > 0,  # Performance Max assets
        'has_negatives': len(negatives) > 0,
        'has_extensions': len(extensions) > 0,
        'has_callout_ext': any(e.get('type') == 'callout' for e in extensions),
        'has_sitelink_ext': any(e.get('type') == 'sitelink' for e in extensions),
        'has_call_ext': any(e.get('type') == 'call' for e in extensions),
        'has_structured_snippet_ext': any(e.get('type') == 'structured_snippet' for e in extensions),
        'has_price_ext': any(e.get('type') == 'price' for e in extensions),
        'has_location_ext': any(e.get('type') == 'location' for e in extensions),
    }

    current_app.logger.info(f"Account setup checks: {setup_checks} | PMax campaigns: {len(pmax_campaigns)}, Search campaigns: {len(search_campaigns)}")

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

    # 2. Basic account structure (only if missing Search campaigns)
    # Performance Max campaigns use asset groups, not ad groups
    if setup_checks['has_search_campaigns'] and not setup_checks['has_ad_groups']:
        opportunities.append({
            "title": "⚠️ Add ad groups to Search campaigns",
            "description": "Your Search campaigns need ad groups. Create 2-3 tightly themed ad groups per campaign.",
            "priority": "high",
            "impact_score": 100,
            "category": "setup",
            "icon": "fa-folder-tree",
            "color": "red",
            "action": "Create 2-3 tightly themed ad groups for each Search campaign",
            "estimated_time": "1 hour",
            "quick_win": False,
            "confidence_score": 100,
            "risk_level": "low",
            "benefit_explanation": "Search campaigns need ad groups to organize keywords and ads. Ad groups are the foundation of Search campaign structure.",
            "optimization_type": "setup",
            "optimization_data": {'setup_check': 'basic_structure'},
            "best_practice": True,
        })

    # Performance Max-specific setup recommendations
    if setup_checks['has_pmax_campaigns']:
        # Check if asset groups exist for Performance Max
        if not setup_checks['has_asset_groups']:
            opportunities.append({
                "title": "⚠️ Add asset groups to Performance Max campaigns",
                "description": "Your Performance Max campaigns need asset groups. Each asset group should target a specific product/service category.",
                "priority": "high",
                "impact_score": 95,
                "category": "setup",
                "icon": "fa-layer-group",
                "color": "purple",
                "action": "Create asset groups for each product/service you offer",
                "estimated_time": "1 hour",
                "quick_win": False,
                "confidence_score": 95,
                "risk_level": "low",
                "benefit_explanation": "Performance Max uses asset groups instead of ad groups. Each asset group contains headlines, descriptions, images, and videos that Google's AI combines to create ads.",
                "optimization_type": "setup",
                "optimization_data": {'setup_check': 'pmax_asset_groups'},
                "best_practice": True,
            })

        # Check if assets exist for Performance Max
        if setup_checks['has_asset_groups'] and not setup_checks['has_pmax_assets']:
            opportunities.append({
                "title": "Add assets to Performance Max asset groups",
                "description": "Your asset groups need assets: 5+ headlines, 5+ descriptions, 15+ images, and optional videos.",
                "priority": "high",
                "impact_score": 90,
                "category": "setup",
                "icon": "fa-images",
                "color": "green",
                "action": "Upload 5+ headlines, 5+ descriptions, 15+ images (landscape/square), and videos to each asset group",
                "estimated_time": "2 hours",
                "quick_win": False,
                "confidence_score": 95,
                "risk_level": "low",
                "benefit_explanation": "Performance Max needs diverse assets for Google's AI to test and optimize. More assets = more combinations = better performance.",
                "optimization_type": "setup",
                "optimization_data": {'setup_check': 'pmax_assets'},
                "best_practice": True,
            })

        # Check asset variety for existing Performance Max
        # Break down into separate auto-complete optimizations
        if setup_checks['has_pmax_assets']:
            headlines = [a for a in pmax_assets if a.get('field_type') == 'HEADLINE']
            descriptions = [a for a in pmax_assets if a.get('field_type') == 'DESCRIPTION']
            images = [a for a in pmax_assets if a.get('asset_type') == 'IMAGE']

            # Separate opportunity for headlines (AI-generated, auto-complete)
            if len(headlines) < 5:
                needed = max(0, 5 - len(headlines))
                opportunities.append({
                    "title": f"Add {needed} more headline{'' if needed == 1 else 's'} to Performance Max",
                    "description": f"You have {len(headlines)} headlines, need 5+. AI will generate {needed} mobile-optimized headline{'' if needed == 1 else 's'} for better ad variety.",
                    "priority": "high",
                    "impact_score": 75,
                    "category": "pmax",
                    "icon": "fa-heading",
                    "color": "purple",
                    "action": f"AI-generate {needed} compelling headline variations",
                    "estimated_time": "1 min (AI-generated)",
                    "quick_win": True,
                    "confidence_score": 90,
                    "risk_level": "low",
                    "benefit_explanation": "More headline variety gives Google's AI more combinations to test. 5+ headlines is best practice for Performance Max.",
                    "optimization_type": "pmax_headlines",
                    "optimization_data": {
                        'current_headlines': len(headlines),
                        'needed_headlines': needed,
                        'existing_headlines': [h.get('text', '') for h in headlines[:5]]
                    },
                    "best_practice": True,
                })

            # Separate opportunity for descriptions (AI-generated, auto-complete)
            if len(descriptions) < 4:
                needed = max(0, 4 - len(descriptions))
                opportunities.append({
                    "title": f"Add {needed} more description{'' if needed == 1 else 's'} to Performance Max",
                    "description": f"You have {len(descriptions)} descriptions, need 4+. AI will generate {needed} persuasive description{'' if needed == 1 else 's'} highlighting benefits.",
                    "priority": "high",
                    "impact_score": 75,
                    "category": "pmax",
                    "icon": "fa-align-left",
                    "color": "purple",
                    "action": f"AI-generate {needed} compelling descriptions",
                    "estimated_time": "1 min (AI-generated)",
                    "quick_win": True,
                    "confidence_score": 90,
                    "risk_level": "low",
                    "benefit_explanation": "More description variety improves ad testing. 4+ descriptions is best practice for Performance Max campaigns.",
                    "optimization_type": "pmax_descriptions",
                    "optimization_data": {
                        'current_descriptions': len(descriptions),
                        'needed_descriptions': needed,
                        'existing_descriptions': [d.get('text', '') for d in descriptions[:4]]
                    },
                    "best_practice": True,
                })

            # Images remain manual (requires user to provide URLs)
            if len(images) < 15:
                needed = max(0, 15 - len(images))
                opportunities.append({
                    "title": f"Add {needed} more image{'' if needed == 1 else 's'} to Performance Max",
                    "description": f"You have {len(images)} images, need 15+. Performance Max requires diverse images (landscape 1.91:1 and square 1:1) for optimal performance.",
                    "priority": "medium",
                    "impact_score": 70,
                    "category": "pmax",
                    "icon": "fa-image",
                    "color": "purple",
                    "action": f"Upload {needed} high-quality images (mix of landscape and square)",
                    "estimated_time": "30 min",
                    "quick_win": False,
                    "confidence_score": 85,
                    "risk_level": "low",
                    "benefit_explanation": "Images are critical for Performance Max ads. Mix landscape (1200x628) and square (1200x1200) images showing your products/services in action.",
                    "optimization_type": "pmax_images",
                    "optimization_data": {
                        'current_images': len(images),
                        'needed_images': needed
                    },
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

    # 4. Ads (AI-generated, auto-complete) - Create RSA ads with AI-generated headlines and descriptions
    if setup_checks['has_campaigns'] and setup_checks['has_ad_groups'] and setup_checks['has_keywords'] and not setup_checks['has_ads']:
        # Collect ad groups and keywords for AI generation
        search_ad_groups = [ag for ag in ad_groups if ag.get('campaign_type', '').upper() == 'SEARCH']
        keywords_by_ad_group = {}
        for ag in search_ad_groups:
            ag_keywords = [kw['keyword'] for kw in keywords if kw.get('ad_group_id') == ag['id']]
            if ag_keywords:
                keywords_by_ad_group[ag['id']] = ag_keywords

        if keywords_by_ad_group:
            opportunities.append({
                "title": "AI-generate ads for your ad groups",
                "description": f"AI will create Responsive Search Ads for {len(keywords_by_ad_group)} ad group{'' if len(keywords_by_ad_group) == 1 else 's'} with 15 headlines and 4 descriptions each, customized to your keywords.",
                "priority": "high",
                "impact_score": 90,
                "category": "ad_copy",
                "icon": "fa-ad",
                "color": "purple",
                "action": "AI-generate RSAs with 15 headlines and 4 descriptions for each ad group",
                "estimated_time": "2 min (AI-generated)",
                "quick_win": True,
                "confidence_score": 90,
                "risk_level": "low",
                "benefit_explanation": "Ads are what users see and click. AI will generate Responsive Search Ads with varied headlines and descriptions that Google can test to find what works best. More variations = better performance.",
                "optimization_type": "create_rsa_ads",
                "optimization_data": {
                    'ad_groups': search_ad_groups,
                    'keywords_by_ad_group': keywords_by_ad_group
                },
                "best_practice": True,
            })

    # 4b. RSA Headline Variations (for existing Search ads - AI-generated, auto-complete)
    # Check if Search campaigns have RSA ads with < 15 headlines
    if setup_checks['has_search_campaigns'] and setup_checks['has_ads'] and len(ads) > 0:
        # Analyze RSA headlines across all ads
        total_headlines = 0
        total_rsas = 0
        sample_headlines = []

        for ad in ads:
            headlines = ad.get('headlines', [])
            if headlines:  # Only count RSAs with headlines
                total_headlines += len(headlines)
                total_rsas += 1
                # Collect sample headlines from first ad for AI context
                if not sample_headlines:
                    sample_headlines = headlines[:10]  # Max 10 samples

        if total_rsas > 0:
            avg_headlines = total_headlines / total_rsas
            # Google allows 3-15 headlines per RSA, 15 is ideal for maximum testing
            if avg_headlines < 15:
                needed = int(15 - avg_headlines)
                opportunities.append({
                    "title": f"Add {needed} more headline{'' if needed == 1 else 's'} to RSA ads for better testing",
                    "description": f"Your RSA ads average {int(avg_headlines)} headlines. AI will generate {needed} more headline variation{'' if needed == 1 else 's'} to reach the 15-headline best practice for maximum ad testing.",
                    "priority": "medium",
                    "impact_score": 65,
                    "category": "ad_copy",
                    "icon": "fa-heading",
                    "color": "blue",
                    "action": f"AI-generate {needed} compelling headline variations based on your existing ads",
                    "estimated_time": "1 min (AI-generated)",
                    "quick_win": True,
                    "confidence_score": 88,
                    "risk_level": "low",
                    "benefit_explanation": "More headline variations give Google's AI more combinations to test. 15 headlines is best practice for RSAs - you're currently averaging {:.0f}. More variations = better testing = improved CTR.".format(avg_headlines),
                    "optimization_type": "rsa_headline_variations",
                    "optimization_data": {
                        'current_avg_headlines': avg_headlines,
                        'needed_headlines': needed,
                        'total_rsas': total_rsas,
                        'existing_headlines': sample_headlines
                    },
                    "best_practice": True,
                })

    # 5. Negative keywords (if few or none - ALWAYS check this)
    # Convert to auto-complete with starter pack
    if setup_checks['has_keywords'] and len(negatives) < 10:
        missing_count = max(0, 10 - len(negatives))
        starter_negatives = ["jobs", "careers", "DIY", "how to", "free", "cheap", "salary", "training", "reviews", "complaints"]
        opportunities.append({
            "title": f"Add {min(missing_count, len(starter_negatives))} starter negative keywords",
            "description": f"You have {len(negatives)} negative keywords. Auto-add {min(missing_count, len(starter_negatives))} essential negatives to block job seekers, DIYers, and non-buyers.",
            "priority": "high",
            "impact_score": 85,
            "category": "negative_keyword",
            "icon": "fa-ban",
            "color": "red",
            "action": f"Auto-add: {', '.join(starter_negatives[:min(missing_count, len(starter_negatives))])}",
            "estimated_time": "1 min (auto-complete)",
            "quick_win": True,
            "confidence_score": 95,
            "risk_level": "low",
            "benefit_explanation": "These terms attract job seekers, DIYers, and researchers - not paying customers. Block them before they drain your budget.",
            "optimization_type": "starter_negative_keywords",
            "optimization_data": {
                'current_count': len(negatives),
                'starter_keywords': starter_negatives[:min(missing_count, len(starter_negatives))],
                'needed_count': min(missing_count, len(starter_negatives))
            },
            "best_practice": True,
        })

    # 6. Extensions (always check what's missing)
    # Create individual auto-complete opportunities for key extensions
    if not setup_checks['has_call_ext']:
        opportunities.append({
            "title": "Add Call Extension for mobile users",
            "description": "Add click-to-call button to mobile ads. Auto-completes with your business phone or placeholder (update in Google Ads UI).",
            "priority": "high",
            "impact_score": 85,
            "category": "extension",
            "icon": "fa-phone",
            "color": "green",
            "action": "Auto-add call extension (edit phone number later if needed)",
            "estimated_time": "1 min (auto-complete)",
            "quick_win": True,
            "confidence_score": 95,
            "risk_level": "low",
            "benefit_explanation": "Call extensions are critical for service businesses. Mobile users expect tap-to-call. 20% average CTR lift.",
            "optimization_type": "extension",
            "optimization_data": {'type': 'call'},
            "best_practice": True,
        })

    if not setup_checks['has_sitelink_ext']:
        opportunities.append({
            "title": "Add Sitelink Extensions to increase ad size",
            "description": "Auto-generate 4-6 quick links below your ads (Services, Contact, Emergency, About). 12% average CTR lift.",
            "priority": "high",
            "impact_score": 80,
            "category": "extension",
            "icon": "fa-link",
            "color": "green",
            "action": "Auto-add standard sitelinks",
            "estimated_time": "1 min (auto-complete)",
            "quick_win": True,
            "confidence_score": 90,
            "risk_level": "low",
            "benefit_explanation": "Sitelinks take up more ad space, pushing competitors down. Users find relevant pages faster.",
            "optimization_type": "extension",
            "optimization_data": {'type': 'sitelink'},
            "best_practice": True,
        })

    if not setup_checks['has_callout_ext']:
        opportunities.append({
            "title": "Add Callout Extensions to highlight USPs",
            "description": "Auto-add callouts like 'Licensed & Insured', '20+ Years Experience', 'Same Day Service'. 8% average CTR lift.",
            "priority": "medium",
            "impact_score": 75,
            "category": "extension",
            "icon": "fa-star",
            "color": "green",
            "action": "Auto-add standard callouts",
            "estimated_time": "1 min (auto-complete)",
            "quick_win": True,
            "confidence_score": 90,
            "risk_level": "low",
            "benefit_explanation": "Builds trust and differentiates from competitors. No extra cost for these clicks.",
            "optimization_type": "extension",
            "optimization_data": {'type': 'callout'},
            "best_practice": True,
        })

    if not setup_checks['has_price_ext']:
        opportunities.append({
            "title": "Add Price Extensions to show pricing",
            "description": "Auto-add standard pricing tiers: Basic Service ($99), Emergency ($199), Inspection ($79), Installation ($499). Shows prices directly in ads.",
            "priority": "medium",
            "impact_score": 70,
            "category": "extension",
            "icon": "fa-dollar-sign",
            "color": "green",
            "action": "Auto-add price extension with standard service tiers",
            "estimated_time": "1 min (auto-complete)",
            "quick_win": True,
            "confidence_score": 85,
            "risk_level": "low",
            "benefit_explanation": "Price extensions build transparency and pre-qualify leads. Users who click already know your pricing range.",
            "optimization_type": "extension",
            "optimization_data": {'type': 'price'},
            "best_practice": True,
        })

    if not setup_checks['has_structured_snippet_ext']:
        opportunities.append({
            "title": "Add Structured Snippet Extension",
            "description": "Auto-add service categories: Repairs, Installation, Maintenance, Emergency Service, Inspection. Shows your service breadth in ads.",
            "priority": "medium",
            "impact_score": 70,
            "category": "extension",
            "icon": "fa-list",
            "color": "green",
            "action": "Auto-add structured snippet with service categories",
            "estimated_time": "1 min (auto-complete)",
            "quick_win": True,
            "confidence_score": 90,
            "risk_level": "low",
            "benefit_explanation": "Structured snippets highlight your service variety. Users see exactly what you offer before clicking.",
            "optimization_type": "extension",
            "optimization_data": {'type': 'structured_snippet'},
            "best_practice": True,
        })

    # Location extension - Now auto-applicable using Google Ads API location feed
    if not setup_checks['has_location_ext']:
        opportunities.append({
            "title": "Add location extension to show your business address",
            "description": "Location extensions display your business address with your ads, making them larger and more credible. Click to auto-configure using your Google Business Profile data.",
            "priority": "high",
            "impact_score": 80,
            "category": "extension",
            "icon": "fa-map-marker-alt",
            "color": "green",
            "action": "Auto-configure location extension from your Google Business Profile",
            "estimated_time": "1 min (auto-configured)",
            "quick_win": True,
            "confidence_score": 95,
            "risk_level": "low",
            "benefit_explanation": "Location extensions make your ad larger and show your business address, pushing competitors down. They increase CTR by 10-15% and are especially important for local service businesses.",
            "optimization_type": "extension",
            "optimization_data": {'type': 'location'},
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

    # SMART BUNDLING: Group complementary optimizations that work better together
    bundles = _create_optimization_bundles(opportunities)

    return {
        "scores": scores,
        "grade": grade,
        "opportunities": opportunities,  # Return all individual line items
        "recommendations": recommendations,
        "account_name": ads_data.get("account_name", "Google Ads Account"),
        "campaign_breakdown": campaign_breakdown,
        "competitive_insights": competitive_insights,
        "quick_wins": quick_wins,
        "bundles": bundles,  # Smart bundling recommendations
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
