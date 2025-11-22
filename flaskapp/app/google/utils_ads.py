# app/google/utils_ads.py
from __future__ import annotations

import os
from typing import Optional, Sequence, List

import requests
from flask import current_app
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app import db

# Google Ads API version management
# Supported versions in order of preference (newest first)
# Google typically supports ~3 versions at a time, deprecating oldest every ~12 months
SUPPORTED_ADS_VERSIONS = ["v19", "v18", "v17"]

# Version can be overridden via env; if "auto", will try versions until one works
_ENV_VERSION = os.getenv("GOOGLE_ADS_API_VERSION", "auto").strip() or "auto"

# Cache for the detected working version
_working_version: Optional[str] = None


def _get_ads_api_version() -> str:
    """
    Get the Google Ads API version to use.
    If env is set to a specific version (e.g., "v18"), use that.
    If env is "auto" or not set, use the cached working version or default to newest.
    """
    global _working_version

    # If explicitly set to a specific version, use it
    if _ENV_VERSION != "auto" and _ENV_VERSION.startswith("v"):
        return _ENV_VERSION

    # Return cached working version if available
    if _working_version:
        return _working_version

    # Default to newest supported version
    return SUPPORTED_ADS_VERSIONS[0]


def _set_working_version(version: str) -> None:
    """Cache a version that's confirmed to work."""
    global _working_version
    _working_version = version


def _get_ads_api_base() -> str:
    """Get the base URL for Google Ads API."""
    return f"https://googleads.googleapis.com/{_get_ads_api_version()}"


# For backward compatibility
GOOGLE_ADS_VERSION = _get_ads_api_version()
ADS_API_BASE = _get_ads_api_base()


# ────────────────────────────────────────────────────────────────────────────
# Core helpers
# ────────────────────────────────────────────────────────────────────────────

def _dev_token() -> str:
    """
    Resolve Google Ads developer token from config/env.
    Raises if missing — you must set this.
    """
    tok = (current_app.config.get("GOOGLE_ADS_DEVELOPER_TOKEN")
           or os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN")
           or "").strip()
    if not tok:
        raise RuntimeError("Missing GOOGLE_ADS_DEVELOPER_TOKEN in config/env.")
    return tok


def _digits_only(s: str | int) -> str:
    return "".join(ch for ch in str(s) if ch.isdigit())


def _default_manager_env() -> Optional[str]:
    """
    Optional global fallback MCC / login-customer-id when per-account
    manager id is empty. Useful if you operate an MCC.
    """
    val = current_app.config.get("GOOGLE_LSA_MANAGER_ID") or os.getenv("GOOGLE_LSA_MANAGER_ID")
    return _digits_only(val) if val else None


# ────────────────────────────────────────────────────────────────────────────
# Schema safety: ensure ACCOUNTS has the columns we need
# ────────────────────────────────────────────────────────────────────────────

def _accounts_has_columns(cols: Sequence[str]) -> bool:
    try:
        with db.engine.connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT COLUMN_NAME
                      FROM information_schema.COLUMNS
                     WHERE TABLE_SCHEMA = DATABASE()
                       AND TABLE_NAME   = 'accounts'
                """)
            ).mappings().all()
            have = {r["COLUMN_NAME"] for r in rows}
            return set(cols).issubset(have)
    except Exception as e:
        current_app.logger.warning("Column check failed for accounts: %s", e)
        return False


def ensure_account_ads_columns() -> None:
    needed = ["google_ads_customer_id", "google_ads_manager_id"]
    if _accounts_has_columns(needed):
        return

    try:
        with db.engine.connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT COLUMN_NAME
                      FROM information_schema.COLUMNS
                     WHERE TABLE_SCHEMA = DATABASE()
                       AND TABLE_NAME='accounts'
                """)
            ).mappings().all()
            existing = {r["COLUMN_NAME"] for r in rows}
    except Exception as e:
        current_app.logger.warning("Could not enumerate columns for accounts: %s", e)
        return

    to_add = [c for c in needed if c not in existing]
    if not to_add:
        return

    alter_clauses = []
    if "google_ads_customer_id" in to_add:
        alter_clauses.append("ADD COLUMN google_ads_customer_id VARCHAR(20) NULL")
    if "google_ads_manager_id" in to_add:
        alter_clauses.append("ADD COLUMN google_ads_manager_id VARCHAR(20) NULL")

    ddl = "ALTER TABLE accounts " + ", ".join(alter_clauses)
    try:
        with db.engine.begin() as conn:
            conn.execute(text(ddl))
        current_app.logger.info("Added missing columns on accounts: %s", ", ".join(to_add))
    except Exception as e:
        current_app.logger.warning("ALTER TABLE accounts failed: %s", e)


# ────────────────────────────────────────────────────────────────────────────
# Persisted context (customer / manager IDs) on ACCOUNTS table
# ────────────────────────────────────────────────────────────────────────────

def resolve_ads_context(aid: int) -> dict:
    ensure_account_ads_columns()
    try:
        with db.engine.connect() as conn:
            row = (
                conn.execute(
                    text("""
                        SELECT
                          google_ads_customer_id,
                          google_ads_manager_id
                        FROM accounts
                        WHERE id=:aid
                        LIMIT 1
                    """),
                    {"aid": aid},
                ).mappings().first()
            )
            if not row:
                return {"customer_id": None, "login_customer_id": _default_manager_env()}

            cust = row.get("google_ads_customer_id")
            mgr = row.get("google_ads_manager_id") or _default_manager_env()
            return {"customer_id": cust, "login_customer_id": mgr}
    except SQLAlchemyError as e:
        current_app.logger.warning("resolve_ads_context: DB error: %s", e)
        return {"customer_id": None, "login_customer_id": _default_manager_env()}


def save_customer_id(aid: int, customer_id: str | int) -> None:
    ensure_account_ads_columns()
    cid = _digits_only(customer_id)
    if not cid:
        raise ValueError("customer_id must contain digits.")
    with db.engine.begin() as conn:
        conn.execute(
            text("""
                UPDATE accounts
                   SET google_ads_customer_id=:cid, updated_at=NOW()
                 WHERE id=:aid
                 LIMIT 1
            """),
            {"aid": aid, "cid": cid},
        )


def save_manager_id(aid: int, manager_id: str | int) -> None:
    ensure_account_ads_columns()
    mid = _digits_only(manager_id)
    if not mid:
        raise ValueError("manager_id must contain digits.")
    with db.engine.begin() as conn:
        conn.execute(
            text("""
                UPDATE accounts
                   SET google_ads_manager_id=:mid, updated_at=NOW()
                 WHERE id=:aid
                 LIMIT 1
            """),
            {"aid": aid, "mid": mid},
        )


# ────────────────────────────────────────────────────────────────────────────
# OAuth tokens (read from your existing google_oauth_tokens table)
# ────────────────────────────────────────────────────────────────────────────

def get_stored_access_token(aid: int, products: Sequence[str] = ("ads", "lsa")) -> Optional[str]:
    with db.engine.connect() as conn:
        for prod in products:
            row = (
                conn.execute(
                    text("""
                        SELECT access_token
                          FROM google_oauth_tokens
                         WHERE account_id=:aid AND product=:prod
                         ORDER BY updated_at DESC
                         LIMIT 1
                    """),
                    {"aid": aid, "prod": prod},
                ).mappings().first()
            )
            if row and row["access_token"]:
                return row["access_token"]
    return None


# ────────────────────────────────────────────────────────────────────────────
# Google Ads “who can I access?” discovery
# ────────────────────────────────────────────────────────────────────────────

def list_accessible_customers(access_token: str, login_customer_id: str | None = None) -> List[str]:
    """
    List accessible Google Ads customers.
    Implements auto-version detection: tries multiple API versions if the current one fails.
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "developer-token": _dev_token(),
        "Content-Type": "application/json",
    }
    if login_customer_id:
        headers["login-customer-id"] = _digits_only(login_customer_id)

    # If env is explicitly set to a specific version, use only that
    if _ENV_VERSION != "auto" and _ENV_VERSION.startswith("v"):
        versions_to_try = [_ENV_VERSION]
    else:
        # Auto mode: try all supported versions, starting with cached working version
        versions_to_try = SUPPORTED_ADS_VERSIONS.copy()
        if _working_version and _working_version in versions_to_try:
            # Move working version to front
            versions_to_try.remove(_working_version)
            versions_to_try.insert(0, _working_version)

    last_error = None
    for version in versions_to_try:
        url = f"https://googleads.googleapis.com/{version}/customers:listAccessibleCustomers"

        try:
            r = requests.get(url, headers=headers, timeout=15)
            r.raise_for_status()

            # Success! Cache this version
            _set_working_version(version)
            current_app.logger.info(f"Google Ads API {version} working, cached as default")

            j = r.json() or {}
            return [rn.split("/", 1)[-1] for rn in j.get("resourceNames", [])]

        except requests.HTTPError as e:
            last_error = e
            if r.status_code == 404:
                # Version deprecated, try next
                current_app.logger.warning(f"Google Ads API {version} returned 404 (deprecated), trying next version")
                continue
            else:
                # Other error (auth, permission, etc.) - don't try other versions
                current_app.logger.error("Ads listAccessibleCustomers failed (%s): %s", r.status_code, r.text)
                raise

    # All versions failed
    current_app.logger.error("All Google Ads API versions failed. Tried: %s", versions_to_try)
    if last_error:
        raise last_error
    raise RuntimeError(f"No working Google Ads API version found (tried: {versions_to_try})")


def pick_and_save_customer_id_after_oauth(aid: int, access_token: str) -> List[str]:
    """
    Convenience:
      - Fetches accessible customer IDs after OAuth.
      - If one ID, saves it immediately for the account.
      - If none or multiple, returns the list so the caller can show a picker.
    Returns the list of IDs (digits-only). The caller decides UI flow for 0 or >1 results.
    """
    ids = list_accessible_customers(access_token)
    if len(ids) == 1:
        save_customer_id(aid, ids[0])
    return ids


# ────────────────────────────────────────────────────────────────────────────
# Request headers + GAQL search (REST)
# ────────────────────────────────────────────────────────────────────────────

def ads_headers(access_token: str, login_customer_id: Optional[str] = None) -> dict:
    """
    Build the Ads API headers.
    - Always include developer token + bearer.
    - Include login-customer-id ONLY when provided (MCC mode).
      Omit for direct mode (no MCC required).
    """
    h = {
        "Authorization": f"Bearer {access_token}",
        "developer-token": _dev_token(),
        "Content-Type": "application/json",
    }
    if login_customer_id:
        h["login-customer-id"] = _digits_only(login_customer_id)
    return h


def google_ads_search(
    access_token: str,
    customer_id: str | int,
    query: str,
    login_customer_id: Optional[str] = None,
    stream: bool = True,
) -> List[dict]:
    """
    Execute a GAQL search (REST).
      - stream=True uses searchStream (recommended for larger result sets).
      - stream=False uses search (paginated).
    Works with or without MCC (login_customer_id).
    Returns a list of results (combined across stream pages if stream=True).
    """
    cid = _digits_only(customer_id)
    headers = ads_headers(access_token, login_customer_id)
    results: List[dict] = []

    if stream:
        url = f"{_get_ads_api_base()}/customers/{cid}/googleAds:searchStream"
        r = requests.post(url, headers=headers, json={"query": query}, timeout=60)
        r.raise_for_status()
        # searchStream returns an array of "results" batches
        payload = r.json() or []
        for batch in payload:
            for row in batch.get("results", []):
                results.append(row)
        return results

    # Non-streaming (handles pagination internally)
    url = f"{_get_ads_api_base()}/customers/{cid}/googleAds:search"
    page_token = None
    while True:
        body = {"query": query}
        if page_token:
            body["pageToken"] = page_token
        r = requests.post(url, headers=headers, json=body, timeout=60)
        r.raise_for_status()
        payload = r.json() or {}
        results.extend(payload.get("results", []))
        page_token = payload.get("nextPageToken")
        if not page_token:
            break
    return results


# ────────────────────────────────────────────────────────────────────────────
# Example: GLSA-friendly query wrapper
# ────────────────────────────────────────────────────────────────────────────

def fetch_leads_last_30d(
    aid: int,
    access_token: Optional[str] = None,
    query_override: Optional[str] = None,
) -> List[dict]:
    """
    Example wrapper you can call from your GLSA endpoints.
    - Resolves customer_id (required) and optional manager (login) ID.
    - Uses direct mode when no MCC is present (omits login-customer-id).
    - Accepts an explicit access_token or resolves from stored tokens (ads/lsa).
    """
    ctx = resolve_ads_context(aid)
    customer_id = ctx["customer_id"]
    if not customer_id:
        # Let the route decide how to message this to the user
        raise ValueError("missing_customer_id")

    login_customer_id = ctx["login_customer_id"]  # may be None (direct mode)

    tok = access_token or get_stored_access_token(aid, ("ads", "lsa"))
    if not tok:
        raise RuntimeError("missing_access_token")

    query = (query_override or """
      SELECT
        customer.id,
        metrics.impressions,
        metrics.clicks,
        campaign.id
      FROM campaign
      WHERE segments.date DURING LAST_30_DAYS
      LIMIT 1000
    """).strip()

    return google_ads_search(
        access_token=tok,
        customer_id=customer_id,
        query=query,
        login_customer_id=login_customer_id,  # None => direct mode
        stream=True,
    )
