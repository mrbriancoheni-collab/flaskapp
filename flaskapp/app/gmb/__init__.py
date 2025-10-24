# app/gmb/__init__.py
from __future__ import annotations

import os
import json
import secrets
from datetime import datetime, timedelta, date
from typing import Optional, Tuple, Dict, Any, List

import requests
from flask import (
    Blueprint,
    current_app,
    current_app as app,
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

# -----------------------------------------------------------------------------
# Blueprint
# -----------------------------------------------------------------------------
gmb_bp = Blueprint("gmb_bp", __name__, url_prefix="/account/gmb")

# Google OAuth / API endpoints
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"

# GBP scopes (Business manage)
GMB_SCOPE = "https://www.googleapis.com/auth/business.manage"

# -----------------------------------------------------------------------------
# Connection helpers
# -----------------------------------------------------------------------------
def _is_connected(aid: int) -> bool:
    """Connected if a refreshable token exists for GBP-like products."""
    try:
        with db.engine.connect() as conn:
            row = (
                conn.execute(
                    text(
                        """
                        SELECT refresh_token
                          FROM google_oauth_tokens
                         WHERE account_id = :aid
                           AND LOWER(product) IN ('gbp','gmb','mybusiness')
                         ORDER BY id DESC
                         LIMIT 1
                        """
                    ),
                    {"aid": aid},
                )
                .fetchone()
            )
            if not row:
                return False
            refresh_token = row[0] if isinstance(row, (list, tuple)) else getattr(row, "refresh_token", None)
            return bool(refresh_token)
    except Exception:
        current_app.logger.exception("GMB connection check failed")
        return False


def _ai_is_connected() -> bool:
    """True if we can call OpenAI (key present and SDK importable)."""
    key = current_app.config.get("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not key:
        return False
    try:
        import openai  # noqa: F401
        return True
    except Exception:
        return False


def _external_base() -> Optional[str]:
    """
    Prefer product-specific external base, then global.
    Must be absolute URL (https://domain) with no trailing slash.
    """
    return (
        os.getenv("GMB_EXTERNAL_BASE_URL")
        or current_app.config.get("GMB_EXTERNAL_BASE_URL")
        or os.getenv("EXTERNAL_BASE_URL")
        or current_app.config.get("EXTERNAL_BASE_URL")
    )


def _callback_uri() -> str:
    """
    Canonical callback URL for GBP OAuth.
    Resolution order:
      1) GMB_REDIRECT_URI (full URL)
      2) GMB_EXTERNAL_BASE_URL/EXTERNAL_BASE_URL + '/account/gmb/callback'
      3) url_for(..., _external=True)
    """
    explicit = os.getenv("GMB_REDIRECT_URI") or current_app.config.get("GMB_REDIRECT_URI")
    if explicit:
        return explicit

    base = _external_base()
    if base:
        return f"{base}/account/gmb/callback"

    # Fallback (ensure ProxyFix in front if behind a proxy)
    return url_for("gmb_bp.callback", _external=True)


def _oauth_client() -> Tuple[Optional[str], Optional[str], str]:
    """
    Product-specific client id/secret from env/config for GBP.
    """
    cid = current_app.config.get("GOOGLE_GMB_CLIENT_ID") or os.getenv("GOOGLE_GMB_CLIENT_ID")
    csec = current_app.config.get("GOOGLE_GMB_SECRET") or os.getenv("GOOGLE_GMB_SECRET")
    cb = _callback_uri()
    return cid, csec, cb


def _store_tokens(
    aid: int,
    token_json: dict,
    *,
    product: str = "gbp",
    gsc_site: Optional[str] = None,
    ga_property_id: Optional[str] = None,
    ga_property_name: Optional[str] = None,
) -> None:
    """
    Persist both raw credentials_json and first-class token columns.
    Requires table google_oauth_tokens with a UNIQUE(account_id,product).
    """
    access_token = token_json.get("access_token")
    refresh_token = token_json.get("refresh_token")
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

    params = {
        "aid": aid,
        "product": product,
        "creds": json.dumps(token_json),
        "at": access_token,
        "rt": refresh_token,
        "exp": token_expiry,
        "ga_id": ga_property_id,
        "ga_name": ga_property_name,
        "gsc": gsc_site,
    }

    with db.engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO google_oauth_tokens
                  (account_id, product,
                   credentials_json, access_token, refresh_token, token_expiry,
                   ga_property_id, ga_property_name, gsc_site,
                   created_at, updated_at)
                VALUES
                  (:aid, :product,
                   :creds, :at, :rt, :exp,
                   :ga_id, :ga_name, :gsc,
                   NOW(), NOW())
                ON DUPLICATE KEY UPDATE
                  credentials_json = VALUES(credentials_json),
                  access_token     = VALUES(access_token),
                  refresh_token    = COALESCE(VALUES(refresh_token), refresh_token),
                  token_expiry     = VALUES(token_expiry),
                  ga_property_id   = VALUES(ga_property_id),
                  ga_property_name = VALUES(ga_property_name),
                  gsc_site         = VALUES(gsc_site),
                  updated_at       = NOW()
                """
            ),
            params,
        )


def _refresh_token(aid: int) -> Optional[str]:
    """
    Refresh the access token using the stored refresh token.
    Returns the new access token or None if refresh failed.
    """
    try:
        with db.engine.connect() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT refresh_token
                      FROM google_oauth_tokens
                     WHERE account_id = :aid
                       AND LOWER(product) IN ('gbp','gmb','mybusiness')
                     ORDER BY id DESC
                     LIMIT 1
                    """
                ),
                {"aid": aid},
            ).fetchone()

        if not row:
            return None
        refresh_token = row[0] if isinstance(row, (list, tuple)) else getattr(row, "refresh_token", None)
        if not refresh_token:
            return None

        cid, csec, _ = _oauth_client()
        r = requests.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": cid,
                "client_secret": csec,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            timeout=(3, 20),
        )
        r.raise_for_status()
        tj = r.json()
        _store_tokens(aid, tj, product="gbp")
        return tj.get("access_token")
    except Exception:
        current_app.logger.exception("GMB token refresh failed")
        return None


# -----------------------------------------------------------------------------
# AI helpers (Profile optimization & Review replies)
# -----------------------------------------------------------------------------
_SAMPLE_PROFILE: Dict[str, Any] = {
    "name": "Clean Finish Cleaning Service",
    "primary_category": "House Cleaning Service",
    "additional_categories": ["Janitorial Service", "Window Cleaning Service"],
    "description": "Eco-friendly, high-quality residential and commercial cleaning serving Greater Sacramento. Transparent pricing, vetted pros, and a 100% happiness guarantee.",
    "phone": "(916) 555-0198",
    "website": "https://cleanfinish.example.com",
    "address": "8213 Northam Dr, Antelope, CA 95843",
    "service_areas": ["Sacramento", "Roseville", "Citrus Heights", "Elk Grove"],
    "hours_text": "Mon–Fri: 8:00 AM – 6:00 PM\nSat: 9:00 AM – 2:00 PM\nSun: Closed",
    "attributes": ["Eco-friendly", "Women-led", "Locally owned"],
}


def _fallback_profile_suggestions(profile: Dict[str, Any]) -> Dict[str, Any]:
    name = (profile.get("name") or "Your Business").strip()
    primary = (profile.get("primary_category") or "Local Service").strip()
    return {
        "title": f"{name} · {primary}",
        "description": (
            "Clear, keyword-rich overview of services and service areas. Add trust signals "
            "(years in business, guarantees, licensing/insurance). End with a direct call to action."
        ),
        "categories": [primary],
        "keywords": [
            "local service", "near me", "top rated", "reliable", "same day",
            "licensed", "insured", "free estimate", "professional", "trusted"
        ][:12],
    }


def _ai_optimize_profile(profile: Dict[str, Any]) -> Dict[str, Any]:
    """
    Returns a dict: { title, description, categories[], keywords[] }.
    Uses OpenAI if configured; otherwise returns a sensible fallback.
    """
    key = current_app.config.get("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
    model = current_app.config.get("OPENAI_MODEL") or os.getenv("OPENAI_MODEL") or "gpt-4o-mini"
    if not key:
        return _fallback_profile_suggestions(profile)

    system = (
        "You are a Google Business Profile optimizer. Improve clarity, local SEO, and conversion. "
        "Respect GBP content guidelines; no false claims, no keyword stuffing."
    )
    user = f"""Return optimized fields for this Business Profile JSON:

PROFILE:
{json.dumps(profile, ensure_ascii=False, indent=2)}

Requirements:
- title: <= 80 chars; business name plus key differentiator if helpful.
- description: <= 750 chars; plain text; include services, geo areas, trust signals, CTA.
- categories: up to 3 suggestions total; include the primary category first when reasonable.
- keywords: 8–12 concise, lowercase phrases; no punctuation.

Output valid JSON with keys: title, description, categories, keywords.
"""

    try:
        from openai import OpenAI  # type: ignore
    except Exception:
        return _fallback_profile_suggestions(profile)

    try:
        client = OpenAI(api_key=key)
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format={"type": "json_object"},
            temperature=0.2,
            max_tokens=600,
        )
        raw = (resp.choices[0].message.content or "").strip()
        data = json.loads(raw) if raw else {}
        return {
            "title": str(data.get("title", "")).strip(),
            "description": str(data.get("description", "")).strip(),
            "categories": [str(c).strip() for c in (data.get("categories") or [])][:3],
            "keywords": [str(k).strip() for k in (data.get("keywords") or [])][:12],
        }
    except Exception:
        current_app.logger.exception("AI optimize profile failed")
        return _fallback_profile_suggestions(profile)


def _ai_draft_reply(
    review_text: str,
    *,
    author: str = "",
    rating: int = 0,
    tone: str = "friendly",
    business_name: str = "",
) -> str:
    """
    Drafts a short owner reply. Uses OpenAI if configured; otherwise a safe fallback.
    """
    key = current_app.config.get("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
    model = current_app.config.get("OPENAI_MODEL") or os.getenv("OPENAI_MODEL") or "gpt-4o-mini"

    if not key:
        base = "Thanks for the review" if rating >= 4 else "We’re sorry about your experience"
        who = f", {author}" if author else ""
        tail = (
            " — we appreciate your business!" if rating >= 4
            else ". We’ve shared this with the team and would love to make it right. Please contact us."
        )
        return f"{base}{who}{tail}"

    try:
        from openai import OpenAI  # type: ignore
        client = OpenAI(api_key=key)
        sys = (
            "You draft short, warm, professional public owner replies to Google reviews. "
            "Be concise, kind, never include emojis, never share private info. "
            "If the review is negative, apologize and invite the reviewer to contact the business directly."
        )
        user = (
            f"Business: {business_name or 'Our business'}\n"
            f"Reviewer: {author or 'Customer'}\n"
            f"Rating: {rating}/5\n"
            f"Tone: {tone}\n"
            f"Review text:\n\"\"\"\n{review_text.strip()}\n\"\"\"\n"
            "Write a single-paragraph public owner reply (max ~80 words)."
        )

        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": sys}, {"role": "user", "content": user}],
            temperature=0.4,
            max_tokens=180,
        )
        draft = (resp.choices[0].message.content or "").strip()
        if draft:
            return draft
    except Exception:
        current_app.logger.exception("OpenAI draft failed")

    base = "Thanks for the review" if rating >= 4 else "We’re sorry about your experience"
    who = f", {author}" if author else ""
    tail = (
        " — we appreciate your business!" if rating >= 4
        else ". We’ve shared this with the team and would love to make it right. Please contact us."
    )
    return f"{base}{who}{tail}"


# -----------------------------------------------------------------------------
# Session helpers (profile & suggestions)
# -----------------------------------------------------------------------------
def _get_session_profile() -> Optional[Dict[str, Any]]:
    return session.get("gmb_profile")  # type: ignore[return-value]


def _set_session_profile(p: Dict[str, Any]) -> None:
    session["gmb_profile"] = p


def _get_suggestions() -> Optional[Dict[str, Any]]:
    return session.get("gmb_suggestions")  # type: ignore[return-value]


def _set_suggestions(s: Optional[Dict[str, Any]]) -> None:
    session["gmb_suggestions"] = s


# -----------------------------------------------------------------------------
# GBP Performance + Insights
# -----------------------------------------------------------------------------
def _gbp_access_token_for(aid: int) -> Optional[str]:
    """Return a fresh access token using stored refresh token."""
    return _refresh_token(aid)


def _gbp_list_first_location_name(access_token: str) -> Optional[str]:
    """Get first location resource name, e.g. 'locations/1234567890'."""
    try:
        # Find an account
        acc = requests.get(
            "https://mybusinessaccountmanagement.googleapis.com/v1/accounts",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=(3, 20),
        )
        acc.raise_for_status()
        accounts = acc.json().get("accounts") or []
        if not accounts:
            return None
        account_name = accounts[0].get("name")  # 'accounts/XXXX'

        # List one location
        resp = requests.get(
            f"https://mybusinessbusinessinformation.googleapis.com/v1/{account_name}/locations?pageSize=1",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=(3, 30),
        )
        resp.raise_for_status()
        locs = resp.json().get("locations") or []
        if not locs:
            return None
        return locs[0].get("name")  # 'locations/XXXXXXXX'
    except Exception:
        current_app.logger.exception("GBP list first location failed")
        return None


def _gbp_fetch_performance(access_token: str, location_name: str, days: int = 28) -> Dict[str, Any]:
    """Call Business Profile Performance API and return a compact dict."""
    data: Dict[str, Any] = {"location": location_name, "days": days}
    try:
        end = date.today()
        start = end - timedelta(days=days)

        def d(d_):
            return {"year": d_.year, "month": d_.month, "day": d_.day}

        headers = {"Authorization": f"Bearer {access_token}"}

        # 1) Daily metrics time series
        series_body = {
            "dailyMetrics": [
                "BUSINESS_IMPRESSIONS_DESKTOP",
                "BUSINESS_IMPRESSIONS_MOBILE",
                "CALL_CLICKS",
                "WEBSITE_CLICKS",
                "BUSINESS_CONVERSATIONS",
            ],
            "timeRange": {"startDate": d(start), "endDate": d(end)},
        }
        ts = requests.post(
            f"https://businessprofileperformance.googleapis.com/v1/{location_name}:getDailyMetricsTimeSeries",
            headers=headers,
            json=series_body,
            timeout=(5, 60),
        )
        ts.raise_for_status()
        data["timeseries"] = ts.json()

        # 2) Keyword impressions
        kw_body = {"dailyRange": {"startDate": d(start), "endDate": d(end)}, "searchType": "ALL"}
        kw = requests.post(
            f"https://businessprofileperformance.googleapis.com/v1/{location_name}:getSearchKeywordImpressions",
            headers=headers,
            json=kw_body,
            timeout=(5, 60),
        )
        if kw.status_code == 200:
            data["keywordImpressions"] = kw.json()
    except Exception:
        current_app.logger.exception("GBP performance fetch failed")
    return data


def _gbp_metrics_to_prompt(metrics: Dict[str, Any]) -> str:
    """Summarize metrics for the LLM."""
    loc = metrics.get("location", "")
    ts_all = metrics.get("timeseries", {}).get("timeSeries", [])

    def total(metric_name: str) -> int:
        s = 0
        for series in ts_all:
            if series.get("dailyMetric") == metric_name:
                for dp in series.get("timeSeries", []):
                    try:
                        s += int(dp.get("value", 0))
                    except Exception:
                        pass
        return s

    desktop = total("BUSINESS_IMPRESSIONS_DESKTOP")
    mobile = total("BUSINESS_IMPRESSIONS_MOBILE")
    calls = total("CALL_CLICKS")
    web = total("WEBSITE_CLICKS")
    chats = total("BUSINESS_CONVERSATIONS")

    kws = []
    for k in (metrics.get("keywordImpressions", {}).get("searchKeywords") or [])[:10]:
        term = k.get("searchKeyword") or ""
        weekly = k.get("weeklyImpressions") or 0
        kws.append(f"{term} ({weekly})")

    lines = [
        f"Location resource: {loc}",
        f"28-day totals: impressions desktop={desktop}, mobile={mobile}, call_clicks={calls}, website_clicks={web}, chats={chats}",
        "Top keywords: " + (", ".join(kws) if kws else "none"),
    ]
    return "\n".join(lines)


def _openai_insights_from_metrics(text_summary: str) -> str:
    """Generate concise HTML insights from the metrics via OpenAI (fallback safe)."""
    key = current_app.config.get("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
    model = current_app.config.get("OPENAI_MODEL") or os.getenv("OPENAI_MODEL") or "gpt-4o-mini"
    if not key:
        return "<p><b>AI unavailable.</b> Add OPENAI_API_KEY to generate insights.</p>"

    try:
        from openai import OpenAI  # type: ignore
        client = OpenAI(api_key=key)
        system = (
            "You are an expert Google Business Profile strategist. "
            "Return concise HTML with 3 sections: "
            "<ol><li><b>What happened</b> (plain English readout of the last 28 days)</li>"
            "<li><b>What to fix this month</b> (specific, actionable profile edits: categories, services, photos, Q&A, posts)</li>"
            "<li><b>Next experiments</b> (A/B ideas to improve calls, website clicks, and conversions)</li></ol> "
            "Avoid fluff. Use short bullet points."
        )
        user = f"Analyze these GBP metrics and produce the HTML summary:\n\n{text_summary}"

        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.3,
            max_tokens=800,
        )
        html = (resp.choices[0].message.content or "").strip()
        return html or "<p>No insights were generated.</p>"
    except Exception:
        current_app.logger.exception("OpenAI insights call failed")
        return "<p>Could not generate insights right now.</p>"


def _save_insights(aid: int, html: str) -> None:
    """Persist insights HTML (requires table gmb_insights)."""
    try:
        with db.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO gmb_insights (account_id, generated_at, html)
                    VALUES (:aid, NOW(), :html)
                    """
                ),
                {"aid": aid, "html": html},
            )
    except Exception:
        current_app.logger.exception("Saving insights failed")


def _load_latest_insights(aid: int) -> Optional[Dict[str, Any]]:
    try:
        with db.engine.connect() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT generated_at, html
                      FROM gmb_insights
                     WHERE account_id = :aid
                     ORDER BY generated_at DESC
                     LIMIT 1
                    """
                ),
                {"aid": aid},
            ).fetchone()
            if not row:
                return None
            # row[0] datetime, row[1] html
            return {"generated_at": row[0], "html": row[1]}
    except Exception:
        current_app.logger.exception("Loading insights failed")
        return None


# -----------------------------------------------------------------------------
# Routes
# -----------------------------------------------------------------------------
@gmb_bp.route("/", methods=["GET"], endpoint="index")
@login_required
def index():
    aid = current_account_id()
    connected = _is_connected(aid)
    profile = _get_session_profile() if connected else None

    return render_template(
        "gmb/index.html",
        connected=connected,
        profile=profile,
        sample_profile=_SAMPLE_PROFILE,
        suggestions=_get_suggestions(),
        ai_connected=_ai_is_connected(),
    )


@gmb_bp.route("/start", methods=["GET"], endpoint="start")
@login_required
def start():
    """Kick off Google OAuth for GBP."""
    client_id, client_secret, redirect_uri = _oauth_client()
    if not client_id or not client_secret:
        flash("Google OAuth is not configured for Google Business (missing client id/secret).", "error")
        return redirect(url_for("gmb_bp.index"))

    current_app.logger.info("GMB OAuth start: redirect_uri=%s client_id=%s", redirect_uri, client_id)

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,  # must match Google Console exactly
        "response_type": "code",
        "scope": GMB_SCOPE,
        "access_type": "offline",
        "include_granted_scopes": "true",
        "prompt": "consent",
        "state": secrets.token_urlsafe(24),
    }
    session["gmb_oauth_state"] = params["state"]

    from urllib.parse import urlencode
    return redirect(f"{GOOGLE_AUTH_URL}?{urlencode(params)}")


@gmb_bp.route("/callback", methods=["GET"], endpoint="callback")
@login_required
def callback():
    """Exchange code for tokens and store them with product='gbp'."""
    err = request.args.get("error")
    if err:
        flash(f"Google OAuth error: {err}", "error")
        return redirect(url_for("gmb_bp.index"))

    code = request.args.get("code")
    state = request.args.get("state")
    if not code or not state or state != session.get("gmb_oauth_state"):
        flash("Invalid or missing OAuth state.", "error")
        return redirect(url_for("gmb_bp.index"))
    session.pop("gmb_oauth_state", None)

    client_id, client_secret, redirect_uri = _oauth_client()
    if not client_id or not client_secret:
        flash("Google OAuth is not configured for Google Business (missing client id/secret).", "error")
        return redirect(url_for("gmb_bp.index"))

    try:
        token_resp = requests.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
            timeout=(5, 25),
        )
        token_resp.raise_for_status()
        token_json = token_resp.json()
    except Exception:
        current_app.logger.exception("GMB token exchange failed")
        flash("Could not complete Google sign-in (token exchange error).", "error")
        return redirect(url_for("gmb_bp.index"))

    try:
        aid = current_account_id()
        _store_tokens(aid, token_json, product="gbp")
        if not _get_session_profile():
            _set_session_profile(dict(_SAMPLE_PROFILE))
    except Exception:
        current_app.logger.exception("Storing GMB credentials failed")
        flash("Connected, but failed to store credentials. Please try again.", "error")
        return redirect(url_for("gmb_bp.index"))

    flash("Google Business connected!", "success")
    return redirect(url_for("gmb_bp.index"))


@gmb_bp.route("/disconnect", methods=["GET", "POST"], endpoint="disconnect")
@login_required
def disconnect():
    """Local disconnect: remove stored tokens for GBP and clear session data."""
    aid = current_account_id()
    try:
        with db.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    DELETE FROM google_oauth_tokens
                     WHERE account_id = :aid
                       AND LOWER(product) IN ('gbp','gmb','mybusiness')
                    """
                ),
                {"aid": aid},
            )
        session.pop("gmb_profile", None)
        session.pop("gmb_suggestions", None)
        session.pop("gmb_insights_html", None)
        flash("Disconnected Google Business.", "success")
    except Exception:
        current_app.logger.exception("Disconnect GBP failed")
        flash("Could not disconnect right now.", "error")
    return redirect(url_for("gmb_bp.index"))


# --------- Pages referenced from nav/templates ----------
@gmb_bp.route("/reviews", methods=["GET"], endpoint="reviews")
@login_required
def reviews():
    aid = current_account_id()
    connected = _is_connected(aid)
    return render_template("gmb/reviews.html", connected=connected)


@gmb_bp.route("/ai-responses", methods=["GET"], endpoint="ai_responses")
@login_required
def ai_responses():
    aid = current_account_id()
    connected = _is_connected(aid)
    return render_template("gmb/ai_responses.html", connected=connected)


@gmb_bp.route("/requests-email", methods=["GET"], endpoint="requests_email")
@login_required
def requests_email():
    aid = current_account_id()
    connected = _is_connected(aid)
    return render_template("gmb/requests_email.html", connected=connected)


@gmb_bp.route("/requests-sms", methods=["GET"], endpoint="requests_sms")
@login_required
def requests_sms():
    aid = current_account_id()
    connected = _is_connected(aid)
    return render_template("gmb/requests_sms.html", connected=connected)


@gmb_bp.route("/photos", methods=["GET"], endpoint="photos")
@login_required
def photos():
    aid = current_account_id()
    connected = _is_connected(aid)
    return render_template("gmb/photos.html", connected=connected)


# --------- Profile: AI optimize pipeline ----------
@gmb_bp.route("/optimize", methods=["GET"], endpoint="optimize_profile")
@login_required
def optimize_profile():
    """Runs AI optimizer and stores suggestions in session for the UI."""
    aid = current_account_id()
    connected = _is_connected(aid)
    base = _get_session_profile() if connected else _SAMPLE_PROFILE
    suggestions = _ai_optimize_profile(base)
    _set_suggestions(suggestions)
    flash("AI suggestions generated.", "success")
    return redirect(url_for("gmb_bp.index", show="suggestions"))


# app/gmb/__init__.py
@gmb_bp.route("/optimize.json", methods=["POST"], endpoint="optimize_profile_json")
@login_required
def optimize_profile_json():
    connected = _is_connected(current_account_id())
    base = _get_session_profile() if connected else _SAMPLE_PROFILE
    try:
        suggestions = _ai_optimize_profile(base)
        _set_suggestions(suggestions)
        return jsonify(ok=True, suggestions=suggestions), 200
    except Exception as e:
        current_app.logger.exception("optimize_profile_json failed")
        return jsonify(ok=False, error=str(e)), 500


@gmb_bp.route("/apply-suggestions", methods=["POST"], endpoint="apply_suggestions")
@login_required
def apply_suggestions():
    """
    Apply selected suggestion fields to the in-memory profile (session).
    Does NOT push to Google until /update is called.
    """
    aid = current_account_id()
    if not _is_connected(aid):
        flash("Connect Google Business to apply suggestions.", "error")
        return redirect(url_for("gmb_bp.index"))

    suggestions = _get_suggestions() or {}
    if not suggestions:
        flash("No suggestions to apply. Run the AI Optimizer first.", "error")
        return redirect(url_for("gmb_bp.index", show="suggestions"))

    applied_any = bool(
        request.form.get("apply_title")
        or request.form.get("apply_description")
        or request.form.getlist("apply_categories")
    )
    if not applied_any:
        flash("Select at least one suggestion to apply.", "warning")
        return redirect(url_for("gmb_bp.index", show="suggestions"))

    profile = _get_session_profile() or {}

    if request.form.get("apply_title"):
        title = (suggestions.get("title") or "").strip()
        if title:
            profile["name"] = title

    if request.form.get("apply_description"):
        desc = (suggestions.get("description") or "").strip()
        if desc:
            profile["description"] = desc

    selected_cats = [c.strip() for c in request.form.getlist("apply_categories") if c.strip()]
    if selected_cats:
        profile["primary_category"] = selected_cats[0]
        profile["additional_categories"] = selected_cats[1:]

    _set_session_profile(profile)
    flash("Applied selected suggestions to the form. Review and click Save to persist.", "success")
    return redirect(url_for("gmb_bp.index"))


@gmb_bp.route("/update", methods=["POST"], endpoint="update_profile")
@login_required
def update_profile():
    """
    Save posted profile fields.
    TODO: If connected, push to Google Business Profile API.
    """
    aid = current_account_id()
    allow_demo = (request.args.get("demo") == "1")
    if not _is_connected(aid) and not allow_demo:
        flash("Connect Google Business to save profile changes.", "error")
        return redirect(url_for("gmb_bp.index"))

    def _csv(name: str) -> List[str]:
        raw = (request.form.get(name) or "").strip()
        return [s.strip() for s in raw.split(",") if s.strip()]

    payload: Dict[str, Any] = {
        "name": request.form.get("name") or "",
        "primary_category": request.form.get("primary_category") or "",
        "additional_categories": _csv("additional_categories"),
        "description": request.form.get("description") or "",
        "phone": request.form.get("phone") or "",
        "website": request.form.get("website") or "",
        "address": request.form.get("address") or "",
        "service_areas": _csv("service_areas"),
        "hours_text": request.form.get("hours") or "",
        "attributes": _csv("attributes"),
    }

    # TODO: call GBP Business Information API to update live profile if connected.
    _set_session_profile(payload)
    flash("Profile saved.", "success")
    return redirect(url_for("gmb_bp.index"))


# --------- API: AI draft for a single review ----------
@gmb_bp.route("/reviews/ai-draft", methods=["POST"], endpoint="reviews_ai_draft")
@login_required
def reviews_ai_draft():
    """
    JSON API:
    {
      "text": "...review text...",
      "author": "Jane D.",
      "rating": 5,
      "tone": "friendly" | "professional" | "apologetic" | ...,
      "business_name": "Acme Pest Control"
    }
    -> { "ok": true, "draft": "..." }
    """
    try:
        payload = request.get_json(force=True, silent=False) or {}
        review_text = (payload.get("text") or "").strip()
        if not review_text:
            return jsonify(ok=False, error="Missing review text"), 400

        author = (payload.get("author") or "").strip()
        try:
            rating = int(payload.get("rating") or 0)
        except Exception:
            rating = 0
        tone = (payload.get("tone") or "friendly").strip().lower()
        business_name = (payload.get("business_name") or "").strip()

        draft = _ai_draft_reply(
            review_text,
            author=author,
            rating=rating,
            tone=tone,
            business_name=business_name,
        )
        return jsonify(ok=True, draft=draft)
    except Exception as e:
        current_app.logger.exception("reviews_ai_draft failed")
        return jsonify(ok=False, error=str(e)), 500


# --------- Insights pages ----------
@gmb_bp.route("/insights", methods=["GET"], endpoint="insights")
@login_required
def insights():
    """
    Show last saved insights (if any) and allow regeneration.
    """
    aid = current_account_id()
    connected = _is_connected(aid)
    latest = _load_latest_insights(aid)
    session_html = session.get("gmb_insights_html")
    return render_template(
        "gmb/insights.html",
        connected=connected,
        latest=latest,
        session_html=session_html,
    )


@gmb_bp.route("/insights/regenerate", methods=["POST"], endpoint="insights_regenerate")
@login_required
def insights_regenerate():
    """Refresh token, pull perf, call OpenAI, persist."""
    aid = current_account_id()
    if not _is_connected(aid):
        flash("Connect Google Business first.", "warning")
        return redirect(url_for("gmb_bp.insights"))

    at = _gbp_access_token_for(aid)
    if not at:
        flash("Could not refresh Google token.", "error")
        return redirect(url_for("gmb_bp.insights"))

    loc = _gbp_list_first_location_name(at)
    if not loc:
        flash("No locations found on this account.", "error")
        return redirect(url_for("gmb_bp.insights"))

    metrics = _gbp_fetch_performance(at, loc, days=28)
    summary = _gbp_metrics_to_prompt(metrics)
    html = _openai_insights_from_metrics(summary)

    _save_insights(aid, html)
    session["gmb_insights_html"] = html

    flash("Insights updated.", "success")
    return redirect(url_for("gmb_bp.insights"))


# --------- AI Insights (New unified recommendation system) ----------
@gmb_bp.route("/insights.json", methods=["POST"], endpoint="insights_json")
@login_required
def insights_json():
    """Generate AI-powered optimization insights for GMB profile."""
    aid = current_account_id()

    try:
        payload = request.get_json(force=True) or {}
    except Exception:
        return jsonify({"ok": False, "error": "invalid_json"}), 400

    profile_data = payload.get("profile") or {}
    regenerate = bool(payload.get("regenerate", False))

    # Import insights service
    from app.services.gmb_insights import generate_gmb_insights

    try:
        insights = generate_gmb_insights(aid, profile_data, regenerate=regenerate)
        return jsonify(insights)
    except Exception as e:
        current_app.logger.exception("Error generating GMB insights")
        return jsonify({
            "ok": False,
            "error": str(e),
            "summary": "Failed to generate insights.",
            "recommendations": []
        }), 500


@gmb_bp.route("/apply-recommendation", methods=["POST"], endpoint="apply_recommendation")
@login_required
def apply_recommendation():
    """Apply a GMB recommendation."""
    aid = current_account_id()

    try:
        payload = request.get_json(force=True) or {}
    except Exception:
        return jsonify({"ok": False, "error": "invalid_json"}), 400

    recommendation_id = payload.get("recommendation_id")
    if not recommendation_id:
        return jsonify({"ok": False, "error": "recommendation_id required"}), 400

    # Import insights service
    from app.services.gmb_insights import apply_gmb_recommendation
    from app.auth.utils import current_user_id

    user_id = current_user_id()

    try:
        result = apply_gmb_recommendation(aid, recommendation_id, user_id)
        return jsonify(result)
    except Exception as e:
        current_app.logger.exception("Error applying GMB recommendation")
        return jsonify({"ok": False, "error": str(e)}), 500


@gmb_bp.route("/dismiss-recommendation", methods=["POST"], endpoint="dismiss_recommendation")
@login_required
def dismiss_recommendation():
    """Dismiss a GMB recommendation."""
    aid = current_account_id()

    try:
        payload = request.get_json(force=True) or {}
    except Exception:
        return jsonify({"ok": False, "error": "invalid_json"}), 400

    recommendation_id = payload.get("recommendation_id")
    if not recommendation_id:
        return jsonify({"ok": False, "error": "recommendation_id required"}), 400

    reason = payload.get("reason")

    # Import insights service
    from app.services.gmb_insights import dismiss_gmb_recommendation
    from app.auth.utils import current_user_id

    user_id = current_user_id()

    try:
        result = dismiss_gmb_recommendation(aid, recommendation_id, user_id, reason)
        return jsonify(result)
    except Exception as e:
        current_app.logger.exception("Error dismissing GMB recommendation")
        return jsonify({"ok": False, "error": str(e)}), 500


# --------- Blueprint-level error handler ----------
@gmb_bp.app_errorhandler(Exception)
def _gmb_any_err(e: Exception):
    current_app.logger.exception("Unhandled error in GMB blueprint")
    wants_json = request.accept_mimetypes.get("application/json", 0) >= request.accept_mimetypes.get("text/html", 0)
    if wants_json or request.path.endswith("/ai-draft"):
        return jsonify(ok=False, error=str(e)), 500
    flash("Unexpected error. The incident has been logged.", "error")
    return redirect(url_for("gmb_bp.index"))
