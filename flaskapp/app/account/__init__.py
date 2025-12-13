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
    """
    result = {}
    try:
        with db.engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT DISTINCT ON (product) product, token_expiry
                      FROM google_oauth_tokens
                     WHERE account_id=:aid
                     ORDER BY product, updated_at DESC
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
                    return render_template(
                        "account/dashboard.html",
                        cards=cached["cards"],
                        card_order=cached["card_order"],
                        is_paid=cached["is_paid"],
                        connected_count=cached["connected_count"],
                        total_count=cached["total_count"],
                        connected_percent=cached["connected_percent"],
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
