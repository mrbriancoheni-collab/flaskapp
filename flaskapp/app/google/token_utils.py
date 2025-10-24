# app/google/token_utils.py
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

import requests
from flask import current_app
from sqlalchemy import text

from app import db
import json, os, time
from urllib.parse import urljoin
from flask import current_app, session, request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request as GARequest
from googleapiclient.discovery import build

SCOPES = tuple((os.getenv("GOOGLE_OAUTH_SCOPES") or "https://www.googleapis.com/auth/webmasters.readonly").split())

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"

def _client_config():
    # Use the “installed” style config expected by Flow.from_client_config
    return {
        "web": {
            "client_id": os.environ["GOOGLE_OAUTH_CLIENT_ID"],
            "client_secret": os.environ["GOOGLE_OAUTH_CLIENT_SECRET"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }

def _redirect_uri():
    # Build full redirect URL from the current request host + configured path
    path = os.getenv("GOOGLE_OAUTH_REDIRECT_PATH", "/account/google/gsc/callback")
    # Respect reverse proxy headers via Flask’s request
    base = f"{request.scheme}://{request.host}/"
    return urljoin(base, path.lstrip("/"))

def get_flow(redirect_uri: str = None, state: str = None) -> Flow:
    flow = Flow.from_client_config(
        _client_config(),
        scopes=SCOPES,
        redirect_uri=redirect_uri or _redirect_uri(),
    )
    if state:
        flow.oauth2session.state = state
    return flow

def build_gsc_auth_url(redirect_uri: str) -> str:
    flow = get_flow(redirect_uri=redirect_uri)
    # Use prompt=consent to ensure refresh_token is returned on reconnects
    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent"
    )
    session["gsc_oauth_state"] = state
    session["gsc_oauth_ts"] = int(time.time())
    return auth_url

def exchange_code_for_credentials(code: str, redirect_uri: str, expected_state: str):
    state = session.get("gsc_oauth_state")
    if not state or state != expected_state:
        raise ValueError("Invalid OAuth state.")
    flow = get_flow(redirect_uri=redirect_uri, state=state)
    flow.fetch_token(code=code)
    creds = flow.credentials
    return creds

def creds_from_json(json_str: str) -> Credentials:
    if not json_str:
        return None
    data = json.loads(json_str)
    return Credentials.from_authorized_user_info(data, scopes=SCOPES)

def ensure_fresh_credentials(user) -> Credentials:
    """Load creds from user, refresh if needed, return live Credentials."""
    creds = creds_from_json(user.gsc_token_json or "")
    if not creds:
        return None
    if creds.expired and creds.refresh_token:
        creds.refresh(GARequest())
        # Save refreshed token
        from app import db
        user.gsc_token_json = creds.to_json()
        db.session.commit()
    return creds

def webmasters_client(creds: Credentials):
    return build("webmasters", "v3", credentials=creds, cache_discovery=False)

def list_sites(creds: Credentials):
    svc = webmasters_client(creds)
    # https://developers.google.com/webmaster-tools/search-console-api-original/v3/sites/list
    resp = svc.sites().list().execute()
    return resp.get("siteEntry", []) or []

def pick_property(site_entries):
    """Choose a verified property; prefer domain or https site."""
    verified = [s for s in site_entries if s.get("permissionLevel") in ("siteOwner", "siteFullUser", "siteRestrictedUser")]
    if not verified: 
        return None
    # Prefer verified domain properties “sc-domain:…”, then https, else first
    for s in verified:
        if s["siteUrl"].startswith("sc-domain:"):
            return s["siteUrl"], s["siteUrl"]
    for s in verified:
        if s["siteUrl"].startswith("https://"):
            return s["siteUrl"], s["siteUrl"]
    s = verified[0]
    return s["siteUrl"], s["siteUrl"]

# ---- Search data helpers ----------------------------------------------------

from datetime import date, timedelta

def _daterange_last_28d():
    end = date.today()
    start = end - timedelta(days=28)
    return start.isoformat(), end.isoformat()

def fetch_gsc_summary(creds: Credentials, site_url: str):
    svc = webmasters_client(creds)
    start, end = _daterange_last_28d()
    body = {
        "startDate": start,
        "endDate": end,
        "dimensions": [],
        "rowLimit": 1,
    }
    # https://developers.google.com/webmaster-tools/search-console-api-original/v3/searchanalytics/query
    resp = svc.searchanalytics().query(siteUrl=site_url, body=body).execute()
    clicks = resp.get("responseAggregationType")  # ignore; rows hold totals
    rows = resp.get("rows", [])
    # When no dimensions, some responses omit rows; we can re-query with dimension 'date' and sum.
    if not rows:
        body["dimensions"] = ["date"]
        body["rowLimit"] = 1000
        resp = svc.searchanalytics().query(siteUrl=site_url, body=body).execute()
        rows = resp.get("rows", [])
    t_clicks = sum(r.get("clicks", 0) for r in rows)
    t_impr   = sum(r.get("impressions", 0) for r in rows)
    ctr      = (t_clicks / t_impr) if t_impr else 0.0
    # avg position: mean of positions weighted by impressions
    pos_num  = sum(r.get("impressions", 0) * r.get("position", 0.0) for r in rows)
    avg_pos  = (pos_num / t_impr) if t_impr else 0.0
    return {
        "clicks": int(t_clicks),
        "impressions": int(t_impr),
        "ctr": float(ctr),
        "position": float(avg_pos),
        "period": "Last 28 days",
    }

def fetch_gsc_queries(creds: Credentials, site_url: str, limit: int = 25):
    svc = webmasters_client(creds)
    start, end = _daterange_last_28d()
    body = {
        "startDate": start,
        "endDate": end,
        "dimensions": ["query"],
        "rowLimit": limit,
        "orderBy": [{"dimension": "clicks", "descending": True}],
    }
    resp = svc.searchanalytics().query(siteUrl=site_url, body=body).execute()
    rows = resp.get("rows", []) or []
    out = []
    for r in rows:
        query = (r.get("keys") or [""])[0]
        clicks = r.get("clicks", 0)
        impr   = r.get("impressions", 0)
        ctr    = (clicks / impr) if impr else 0.0
        pos    = r.get("position", 0.0)
        out.append({
            "query": query,
            "clicks": int(clicks),
            "impressions": int(impr),
            "ctr": float(ctr),
            "position": float(pos),
        })
    return out

def fetch_gsc_pages(creds: Credentials, site_url: str, limit: int = 25):
    svc = webmasters_client(creds)
    start, end = _daterange_last_28d()
    body = {
        "startDate": start,
        "endDate": end,
        "dimensions": ["page"],
        "rowLimit": limit,
        "orderBy": [{"dimension": "clicks", "descending": True}],
    }
    resp = svc.searchanalytics().query(siteUrl=site_url, body=body).execute()
    rows = resp.get("rows", []) or []
    out = []
    for r in rows:
        url    = (r.get("keys") or [""])[0]
        clicks = r.get("clicks", 0)
        impr   = r.get("impressions", 0)
        ctr    = (clicks / impr) if impr else 0.0
        pos    = r.get("position", 0.0)
        out.append({
            "url": url,
            "clicks": int(clicks),
            "impressions": int(impr),
            "ctr": float(ctr),
            "position": float(pos),
        })
    return out

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)

def _get_token_row(account_id: int, products: tuple[str, ...]) -> Optional[dict]:
    """
    Fetch the newest token row for any of the given product keys.
    We treat 'ads' and 'glsa' as interchangeable for GLSA.
    """
    with db.engine.connect() as conn:
        row = (
            conn.execute(
                text(
                    """
                    SELECT id, product, access_token, refresh_token, token_expiry, credentials_json
                      FROM google_oauth_tokens
                     WHERE account_id = :aid
                       AND LOWER(product) IN :prods
                     ORDER BY updated_at DESC
                     LIMIT 1
                    """
                ),
                {"aid": account_id, "prods": tuple(p.lower() for p in products)},
            )
            .mappings()
            .first()
        )
        return dict(row) if row else None

def _save_tokens_row(row_id: int, access_token: str, refresh_token: Optional[str], token_expiry: Optional[datetime]) -> None:
    with db.engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE google_oauth_tokens
                   SET access_token = :at,
                       refresh_token = COALESCE(:rt, refresh_token),
                       token_expiry = :exp,
                       updated_at = NOW()
                 WHERE id = :id
                """
            ),
            {"id": row_id, "at": access_token, "rt": refresh_token, "exp": token_expiry},
        )

def ensure_access_token(account_id: int, products: tuple[str, ...]) -> Tuple[str, str]:
    """
    Return (access_token, product_used). Refresh if missing/expired.
    Raises RuntimeError if no usable token found.
    """
    row = _get_token_row(account_id, products)
    if not row:
        raise RuntimeError("No Google OAuth token on file for products: %s" % (products,))

    access = row.get("access_token")
    refresh = row.get("refresh_token")
    expiry = row.get("token_expiry")

    # consider token stale if exp is within 2 minutes
    stale = False
    if expiry:
        try:
            # token_expiry is a DATETIME; treat as naive UTC
            exp_dt = expiry if isinstance(expiry, datetime) else None
            if exp_dt and exp_dt.tzinfo is None:
                exp_dt = exp_dt.replace(tzinfo=timezone.utc)
            if exp_dt and exp_dt - _now_utc() < timedelta(minutes=2):
                stale = True
        except Exception:
            stale = True
    else:
        # no expiry saved; try using the current access (may succeed) but prefer refreshing if we can
        stale = bool(refresh)

    if not stale and access:
        return access, row["product"]

    if not refresh:
        # cannot refresh; return whatever we have and hope it works
        if access:
            return access, row["product"]
        raise RuntimeError("Google token expired and no refresh_token available.")

    # refresh
    client_id = current_app.config.get("GOOGLE_CLIENT_ID")
    client_secret = current_app.config.get("GOOGLE_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise RuntimeError("Google OAuth client not configured.")

    resp = requests.post(
        GOOGLE_TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh,
        },
        timeout=15,
    )
    resp.raise_for_status()
    tj = resp.json()
    new_access = tj.get("access_token")
    expires_in = tj.get("expires_in")
    new_refresh = tj.get("refresh_token") or refresh
    exp_dt = _now_utc() + timedelta(seconds=int(expires_in)) if expires_in else None

    if not new_access:
        raise RuntimeError("Google refresh did not return an access_token.")

    _save_tokens_row(row["id"], new_access, new_refresh, exp_dt)
    return new_access, row["product"]
