# app/__init__.py
from __future__ import annotations

import io
import logging
import os as _os
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path

from flask import Flask, request, abort, redirect, url_for, flash, g, render_template_string
from markupsafe import escape
from flask_login import LoginManager

# ---- Optional deps (graceful if not installed) ------------------------------
try:
    from flask_wtf.csrf import generate_csrf as _real_generate_csrf, CSRFError  # type: ignore
    def _generate_csrf() -> str:
        return _real_generate_csrf()
except Exception:  # pragma: no cover
    CSRFError = None
    def _generate_csrf() -> str:
        return ""

try:
    from flask_limiter import Limiter                # pip install flask-limiter
    from flask_limiter.util import get_remote_address
except Exception:  # pragma: no cover
    Limiter = None
    get_remote_address = None

# Shared extensions (singletons) live in app/extensions.py
from app.extensions import db, csrf, migrate


def _mask_uri(uri: str) -> str:
    """Hide password in logs."""
    try:
        if "@" in uri and "://" in uri:
            head, tail = uri.split("://", 1)
            creds, rest = tail.split("@", 1)
            if ":" in creds:
                user, _pwd = creds.split(":", 1)
                return f"{head}://{user}:***@{rest}"
    except Exception:
        pass
    return uri


def create_app():
    app = Flask(
        __name__,
        static_folder="../static",
        template_folder="../templates",
        instance_relative_config=False,
    )

    # ---- Base config --------------------------------------------------------
    app.config.update(
        SECRET_KEY=_os.getenv("SECRET_KEY", "dev-secret-key"),
        APP_NAME=_os.getenv("APP_NAME", "FieldSprout"),

        # Email / token salt (for email verify & password reset)
        SECURITY_PASSWORD_SALT=_os.getenv("SECURITY_PASSWORD_SALT", "change-me"),

        # Password policy (strong by default)
        PASSWORD_MIN_LENGTH=12,
        PASSWORD_REQUIRE_UPPER=True,
        PASSWORD_REQUIRE_LOWER=True,
        PASSWORD_REQUIRE_DIGIT=True,
        PASSWORD_REQUIRE_SYMBOL=True,

        # Paid-plan rules
        PAID_PLANS=tuple(_os.getenv("PAID_PLANS", "pro,team,enterprise").split(",")),
        PAID_STRIPE_STATES=("active", "trialing"),
        ACCOUNT_TABLE_NAME=_os.getenv("ACCOUNT_TABLE_NAME", "accounts"),
        ACCOUNT_PLAN_FIELD=_os.getenv("ACCOUNT_PLAN_FIELD", "plan"),
        ACCOUNT_STRIPE_FIELD=_os.getenv("ACCOUNT_STRIPE_FIELD", "stripe_status"),
        PRICING_ENDPOINT=_os.getenv("PRICING_ENDPOINT", "main_bp.pricing"),

        # AI models + API keys
        OPENAI_MODEL=_os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        CLAUDE_MODEL=_os.getenv("CLAUDE_MODEL", "claude-3-haiku-20240307"),
        OPENAI_API_KEY=_os.getenv("OPENAI_API_KEY", ""),

        # Database
        SQLALCHEMY_DATABASE_URI=_os.getenv(
            "SQLALCHEMY_DATABASE_URI",
            "mysql+pymysql://username:password@127.0.0.1:3306/fieldspark?charset=utf8mb4",
        ),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,

        # Auth helper (what keys mean "logged in" in session)
        AUTH_SESSION_KEYS=tuple(_os.getenv("AUTH_SESSION_KEYS", "user_id,user,uid,email").split(",")),

        # Cookies & template reload
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        TEMPLATES_AUTO_RELOAD=True,
        PREFERRED_URL_SCHEME=_os.getenv("PREFERRED_URL_SCHEME", "https"),

        # Session hardening
        SESSION_REFRESH_EACH_REQUEST=True,
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),

        # Optional request size cap (e.g., 16 MB)
        MAX_CONTENT_LENGTH=int(_os.getenv("MAX_CONTENT_LENGTH", str(16 * 1024 * 1024))),

        # WordPress automation / Cron
        CRON_SECRET=_os.getenv("CRON_SECRET", ""),
        WP_BASE=_os.getenv("WP_BASE", ""),
        WP_USER=_os.getenv("WP_USER", ""),
        WP_APP_PW=_os.getenv("WP_APP_PW", ""),
    )

    # Enable secure cookies for HTTPS (default on for production)
    if _os.getenv("HTTPS", "on").lower() in ("on", "1", "true", "yes"):
        app.config["SESSION_COOKIE_SECURE"] = True

    # (Optional) .env
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass

    # ---- Load config.py if present -----------------------------------------
    def _load_config_file():
        cfg_env = _os.getenv("APP_CONFIG_FILE")
        if cfg_env and Path(cfg_env).exists():
            app.config.from_pyfile(cfg_env)
            app.logger.info(f"Loaded config from APP_CONFIG_FILE={cfg_env}")
            return True

        # Try to load from Config class in app/config.py
        try:
            from app.config import Config
            app.config.from_object(Config)
            app.logger.info("Loaded config from app.config.Config")
            return True
        except ImportError:
            pass

        # Fallback to file-based config
        candidates = [
            Path(__file__).resolve().parent.parent / "config.py",
            Path(__file__).resolve().parent / "config.py",
        ]
        for p in candidates:
            if p.exists():
                app.config.from_pyfile(str(p))
                app.logger.info(f"Loaded config from {p}")
                return True

        app.logger.warning("No config.py found; continuing with env-only configuration")
        return False

    _load_config_file()

    # ---- Bridge GSC env vars into Google OAuth client config ---------------
    from urllib.parse import urlparse
    cid   = _os.getenv("GOOGLE_SEARCH_CONSOLE_CLIENT_ID", "").strip()
    csec  = _os.getenv("GOOGLE_SEARCH_CONSOLE_SECRET", "").strip()
    redir = _os.getenv("GOOGLE_SEARCH_CONSOLE_REDIRECT_URI", "").strip()
    if cid and csec and redir and not app.config.get("GOOGLE_OAUTH_CLIENT_CONFIG"):
        u = urlparse(redir)
        origin = f"{u.scheme}://{u.netloc}" if u.scheme and u.netloc else None
        app.config["GOOGLE_OAUTH_CLIENT_CONFIG"] = {
            "web": {
                "client_id": cid,
                "client_secret": csec,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                "redirect_uris": [redir],
                "javascript_origins": [origin] if origin else [],
            }
        }

    # ---- Ads config passthrough --------------------------------------------
    dev = _os.environ.get("GOOGLE_ADS_DEVELOPER_TOKEN")
    if dev:
        app.config["GOOGLE_ADS_DEVELOPER_TOKEN"] = dev.strip()
    login = _os.environ.get("GOOGLE_ADS_LOGIN_CUSTOMER_ID")
    if login:
        app.config["GOOGLE_ADS_LOGIN_CUSTOMER_ID"] = login.replace("-", "").strip()

    # OAuth credentials for ads-grader
    client_id = _os.environ.get("GOOGLE_ADS_CLIENT_ID")
    if client_id:
        app.config["GOOGLE_ADS_CLIENT_ID"] = client_id.strip()
    client_secret = _os.environ.get("GOOGLE_ADS_CLIENT_SECRET")
    if client_secret:
        app.config["GOOGLE_ADS_CLIENT_SECRET"] = client_secret.strip()
    # Ads-grader uses its own redirect URI (separate from main Google OAuth)
    redirect_uri = _os.environ.get("GOOGLE_ADS_REDIRECT_URI")
    if redirect_uri:
        app.config["GOOGLE_ADS_REDIRECT_URI"] = redirect_uri.strip()
    else:
        # Default redirect URI for ads-grader
        app.config["GOOGLE_ADS_REDIRECT_URI"] = "https://fieldsprout.io/ads-grader/connect/callback"

    def _protect(key):
        if not app.config.get(key):
            val = _os.environ.get(key)
            if val:
                app.config[key] = val.strip() if key.endswith("_TOKEN") else val.replace("-", "").strip()
    app.config["__protect_ads_config__"] = _protect

    app.logger.info(
        "Ads config: dev_token_len=%s, login_cid=%s, client_id=%s, redirect_uri=%s",
        len(app.config.get("GOOGLE_ADS_DEVELOPER_TOKEN") or ""),
        app.config.get("GOOGLE_ADS_LOGIN_CUSTOMER_ID") or "None",
        "SET" if app.config.get("GOOGLE_ADS_CLIENT_ID") else "NOT SET",
        app.config.get("GOOGLE_ADS_REDIRECT_URI") or "default",
    )

    # ---- Logging (stderr + rotating file) ----------------------------------
    try:
        stderr_handler = logging.StreamHandler()
        try:
            if hasattr(stderr_handler.stream, "buffer"):
                stderr_handler.setStream(io.TextIOWrapper(stderr_handler.stream.buffer, encoding="utf-8", errors="replace"))
        except Exception:
            pass

        stderr_handler.setLevel(logging.INFO)
        stderr_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))

        log_path = _os.getenv("APP_ERROR_LOG", _os.path.join(_os.path.expanduser("~"), "app_error.log"))
        _os.makedirs(_os.path.dirname(log_path), exist_ok=True)
        file_handler = RotatingFileHandler(log_path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))

        app.logger.handlers.clear()
        app.logger.addHandler(stderr_handler)
        app.logger.addHandler(file_handler)
        app.logger.setLevel(logging.INFO)
        app.logger.propagate = False
    except Exception:
        app.logger.handlers.clear()
        app.logger.addHandler(logging.StreamHandler())
        app.logger.setLevel(logging.INFO)

    # ---- DB / Extensions init ----------------------------------------------
    db.init_app(app)
    migrate.init_app(app, db)
    try:
        csrf.init_app(app)  # is a no-op shim if flask-wtf not installed
    except Exception as e:
        app.logger.warning(f"CSRF init failed: {e}")

    # ---- ProxyFix middleware for reverse proxy HTTPS detection -------------
    # This ensures Flask correctly detects HTTPS when behind Nginx/Apache
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(
        app.wsgi_app,
        x_for=1,      # Trust X-Forwarded-For
        x_proto=1,    # Trust X-Forwarded-Proto (critical for HTTPS detection)
        x_host=1,     # Trust X-Forwarded-Host
        x_prefix=1    # Trust X-Forwarded-Prefix
    )

    # ---- Flask-Login init ---------------------------------------------------
    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = "auth_bp.login"
    login_manager.session_protection = "strong"

    @login_manager.user_loader
    def load_user(user_id: str):
        try:
            from app.models import User
            return User.query.get(int(user_id))
        except Exception:
            return None

    # ---- Load models early (optional) --------------------------------------
    try:
        from app import models  # noqa: F401
        try:
            from app import models_fbads  # noqa: F401
        except Exception:
            app.logger.debug("models_fbads not loaded (optional)")
    except Exception:
        app.logger.exception("Failed to import app.models early")

    # ---- Redis + Limiter (resilient) ---------------------------------------
    try:
        import redis  # pip install redis

        def _probe_redis(url: str, log_error: bool = True) -> bool:
            """Probe Redis connectivity. Returns True if connection succeeds."""
            if not url:
                return False
            try:
                client = redis.from_url(url, decode_responses=True, socket_timeout=2)
                client.ping()
                return True
            except Exception as e:
                if log_error:
                    app.logger.warning(f"Redis probe failed: {e}")
                return False

        REDIS_URL = _os.getenv("REDIS_URL", "")
        # Probe Redis once and cache the result to avoid duplicate warnings
        redis_available = _probe_redis(REDIS_URL, log_error=True)

        app.redis = None
        if redis_available:
            app.redis = redis.from_url(REDIS_URL, decode_responses=True, socket_timeout=3)
            app.logger.info("Connected to Redis")
        else:
            app.logger.warning("Redis not available; continuing without app Redis client")

        if Limiter and get_remote_address:
            preferred = _os.getenv("RATELIMIT_STORAGE_URI") or REDIS_URL
            storage_uri = "memory://"

            # Reuse cached result if preferred URL is same as REDIS_URL
            if preferred != "memory://":
                if preferred == REDIS_URL:
                    if redis_available:
                        storage_uri = preferred
                else:
                    # Different URL - probe without logging to avoid duplicate warnings
                    if _probe_redis(preferred, log_error=False):
                        storage_uri = preferred

            limiter = Limiter(
                key_func=get_remote_address,
                storage_uri=storage_uri,
                default_limits=["200 per day", "50 per hour"],
                in_memory_fallback_enabled=True,
            )
            limiter.init_app(app)
            app.logger.info(f"Rate limit storage: {storage_uri}")
        else:
            limiter = None
    except Exception as e:
        app.logger.warning(f"Limiter/Redis disabled: {e}")
        limiter = None

    app.logger.info(f"Logger initialized. DB: {_mask_uri(app.config['SQLALCHEMY_DATABASE_URI'])}")

    # ---- Jinja globals / helpers -------------------------------------------
    @app.context_processor
    def inject_globals_and_helpers():
        def is_logged_in():
            from flask import session as _s
            keys = app.config.get("AUTH_SESSION_KEYS", ("user_id", "user", "uid", "email"))
            return any(_s.get(k) for k in keys)

        def current_user_id():
            from flask import session as _s
            keys = app.config.get("AUTH_SESSION_KEYS", ("user_id", "user", "uid", "email"))
            for k in keys:
                val = _s.get(k)
                if val:
                    return val
            return None

        def _variants(name: str):
            return (
                name,
                f"main_bp.{name}",
                f"auth_bp.{name}",
                f"account_bp.{name}",
                f"wp_bp.{name}",
                f"google_bp.{name}",
                f"gmb_bp.{name}",
                f"ads_grader_bp.{name}",
                # optional legacy prefixes:
                f"auth.{name}",
                f"account.{name}",
                f"wp.{name}",
                f"google.{name}",
            )

        def has_endpoint(name: str) -> bool:
            return any(v in app.view_functions for v in _variants(name))

        def ep(name: str) -> str:
            for v in _variants(name):
                if v in app.view_functions:
                    return v
            return name

        def csp_nonce():
            """Return the CSP nonce for inline scripts."""
            return getattr(g, "csp_nonce", "")

        return {
            "app_name": app.config["APP_NAME"],
            "year": datetime.now().year,
            "current_year": datetime.utcnow().year,
            "csrf_token": _generate_csrf,
            "csp_nonce": csp_nonce,
            "is_logged_in": is_logged_in,
            "current_user_id": current_user_id,
            "has_endpoint": has_endpoint,
            "ep": ep,
        }

    @app.context_processor
    def ai_flags():
        """
        Provide AI and payment status flags to all templates.
        Returns is_paid as False for non-logged-in users or any errors.
        """
        try:
            from app.auth.utils import is_paid_account as _is_paid, is_logged_in

            # Only check payment status if user is logged in
            if is_logged_in():
                is_paid = bool(_is_paid())
            else:
                is_paid = False

            return {
                "ai_enabled": is_paid,
                "is_paid": is_paid
            }
        except Exception as e:
            # Log the error but don't break the page
            app.logger.warning(f"Error in ai_flags context processor: {e}")
            return {
                "ai_enabled": False,
                "is_paid": False
            }

    # ---- Security headers (nonce + CSP) ------------------------------------
    @app.before_request
    def _set_nonce():
        import secrets
        g.csp_nonce = secrets.token_urlsafe(16)

    @app.after_request
    def _security_headers(resp):
        nonce = getattr(g, "csp_nonce", "")

        # Security headers
        resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        if app.config.get("PREFERRED_URL_SCHEME", "https") == "https":
            resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains; preload")
        resp.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=(), payment=()")

        resp.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; "
            "img-src 'self' data: https:; "
            "style-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com https://fonts.googleapis.com; "
            "font-src 'self' data: https://fonts.gstatic.com https://cdnjs.cloudflare.com; "
            f"script-src 'self' 'unsafe-inline' 'nonce-{nonce}' https://cdn.tailwindcss.com https://cdnjs.cloudflare.com "
            "https://www.googletagmanager.com https://www.google-analytics.com https://js.stripe.com; "
            "connect-src 'self' https://api.stripe.com https://www.google-analytics.com "
            "https://www.googletagmanager.com https://www.google.com https://*.google.com; "
            "frame-src 'self' https://js.stripe.com https://hooks.stripe.com https://www.googletagmanager.com; "
            "frame-ancestors 'self'; base-uri 'self'; "
            "form-action 'self' https://checkout.stripe.com https://*.stripe.com"
        )

        # Performance: Aggressive caching for static files (CSS, JS, images, fonts)
        if request.path.startswith('/static/'):
            # Cache static files for 1 year (immutable)
            resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            resp.headers["Expires"] = (datetime.utcnow() + timedelta(days=365)).strftime('%a, %d %b %Y %H:%M:%S GMT')
        elif request.path.endswith(('.css', '.js', '.png', '.jpg', '.jpeg', '.gif', '.svg', '.woff', '.woff2', '.ttf', '.ico')):
            # Cache other static assets for 1 week
            resp.headers["Cache-Control"] = "public, max-age=604800"
            resp.headers["Expires"] = (datetime.utcnow() + timedelta(days=7)).strftime('%a, %d %b %Y %H:%M:%S GMT')

        return resp

    # Enable loop controls in Jinja
    app.jinja_env.add_extension('jinja2.ext.loopcontrols')

    # ---- Register blueprints -----------------------------------------------
    try:
        from app.auth import auth_bp
        app.register_blueprint(auth_bp)
        app.logger.info("auth_bp registered")
    except Exception:
        app.logger.exception("Failed to import auth_bp")

    try:
        from app.views import main_bp
        app.register_blueprint(main_bp)
        app.logger.info("main_bp registered")
    except Exception:
        app.logger.exception("Failed to import main_bp")

    try:
        from app.account import account_bp, stripe_webhook
        app.register_blueprint(account_bp)
        app.logger.info("account_bp registered")
        try:
            csrf.exempt(stripe_webhook)
        except Exception as e:
            app.logger.warning(f"Could not exempt Stripe webhook from CSRF: {e}")
    except Exception:
        app.logger.exception("Failed to import account_bp")

    # Budget Intelligence Features
    try:
        from app.account.auto_budget_routes import auto_budget_bp
        app.register_blueprint(auto_budget_bp)
        app.logger.info("auto_budget_bp registered at /account/auto-budget")
    except Exception:
        app.logger.exception("Failed to import/register auto_budget_bp")

    try:
        from app.account.competitive_routes import competitive_bp
        app.register_blueprint(competitive_bp)
        app.logger.info("competitive_bp registered at /account/competitive")
    except Exception:
        app.logger.exception("Failed to import/register competitive_bp")

    try:
        from app.account.budget_groups_routes import budget_groups_bp
        app.register_blueprint(budget_groups_bp)
        app.logger.info("budget_groups_bp registered at /account/budget-groups")
    except Exception:
        app.logger.exception("Failed to import/register budget_groups_bp")

    try:
        from app.onboarding_bp import onboarding_bp
        app.register_blueprint(onboarding_bp)
        app.logger.info("onboarding_bp registered")
    except Exception:
        app.logger.exception("Failed to import/register onboarding_bp")

    try:
        from app.strategy import strategy_bp
        app.register_blueprint(strategy_bp, url_prefix="/account/strategy")
    except Exception:
        app.logger.exception("Failed to register strategy_bp")

    try:
        from app.wp import wp_bp
        app.register_blueprint(wp_bp, url_prefix="/account/wp")
        app.logger.info("wp_bp registered at /account/wp")

        if "wp_bp.edit_lookup" not in app.view_functions:
            def _wp_edit_stub():
                flash("Editing existing pages is coming soon. Redirected to Publisher for now.", "warning")
                return redirect(url_for("wp_bp.publisher"))
            app.add_url_rule(
                "/account/wp/edit",
                endpoint="wp_bp.edit_lookup",
                view_func=_wp_edit_stub,
                methods=["GET"],
            )
            app.logger.info("Stub route registered for wp_bp.edit_lookup -> /account/wp/edit")
    except Exception:
        app.logger.exception("Failed to import wp_bp")

    try:
        from app.wp_legacy_redirect import wp_legacy
        app.register_blueprint(wp_legacy)
        app.logger.info("wp legacy redirects enabled")
    except Exception:
        app.logger.warning("wp legacy redirects not enabled")

    try:
        from app.pov import pov_bp
        app.register_blueprint(pov_bp)
        app.logger.info("pov_bp registered")
    except Exception:
        app.logger.exception("Failed to import/register pov_bp")

    try:
        from app.google import google_bp
        app.register_blueprint(google_bp)
        app.logger.info("google_bp registered at /account/google")
    except Exception:
        app.logger.exception("Failed to import google_bp")

    try:
        from app.google.agents_routes import agents_bp
        app.register_blueprint(agents_bp)
        app.logger.info("agents_bp registered at /account/google/ads/agents")
    except Exception:
        app.logger.exception("Failed to import/register agents_bp")

    try:
        from app.google.account_wizard_routes import account_wizard_bp
        app.register_blueprint(account_wizard_bp)
        app.logger.info("account_wizard_bp registered at /account/google/ads/setup-wizard")
    except Exception:
        app.logger.exception("Failed to import/register account_wizard_bp")

    try:
        from app.google.budget_routes import budget_bp
        app.register_blueprint(budget_bp)
        app.logger.info("budget_bp registered at /account/google/ads/budget")
    except Exception:
        app.logger.exception("Failed to import/register budget_bp")

    try:
        from app.google.alerts_routes import alerts_bp
        app.register_blueprint(alerts_bp)
        app.logger.info("alerts_bp registered at /account/google/ads/alerts")
    except Exception:
        app.logger.exception("Failed to import/register alerts_bp")

    try:
        from app.google.forecasting_routes import forecasting_bp
        app.register_blueprint(forecasting_bp)
        app.logger.info("forecasting_bp registered at /account/google/ads/forecasting")
    except Exception:
        app.logger.exception("Failed to import/register forecasting_bp")

    try:
        from app.google.auto_budget_routes import auto_budget_bp
        app.register_blueprint(auto_budget_bp)
        app.logger.info("auto_budget_bp registered at /account/google/ads/auto-budget")
    except Exception:
        app.logger.exception("Failed to import/register auto_budget_bp")

    try:
        from app.google.competitive_routes import competitive_bp
        app.register_blueprint(competitive_bp)
        app.logger.info("competitive_bp registered at /account/google/ads/competitive")
    except Exception:
        app.logger.exception("Failed to import/register competitive_bp")

    try:
        from app.glsa import glsa_bp
        app.register_blueprint(glsa_bp, url_prefix="/account/glsa")
        app.logger.info("glsa_bp registered at /account/glsa")
    except Exception as e:
        app.logger.exception("Failed to register glsa_bp: %s", e)

    try:
        from app.yelp import yelp_bp
        app.register_blueprint(yelp_bp, url_prefix="/account/yelp")
        app.logger.info("yelp_bp registered at /account/yelp")
    except Exception as e:
        app.logger.exception("Failed to register yelp_bp: %s", e)

    try:
        from app.fbads import fbads_bp
        app.register_blueprint(fbads_bp, url_prefix="/account/fbads")
        app.logger.info("fbads_bp registered at /account/fbads")
    except Exception as e:
        app.logger.warning("fbads_bp not registered: %s", e)

    try:
        from app.legal import legal_bp
        app.register_blueprint(legal_bp)
    except Exception:
        app.logger.exception("Failed to register legal_bp")

    try:
        from app.billing.routes import billing_bp
        app.register_blueprint(billing_bp)
        app.logger.info("billing_bp registered at /billing")
    except Exception:
        app.logger.exception("Failed to register billing_bp")

    try:
        from app.pages import pages_bp
        app.register_blueprint(pages_bp)
        app.logger.info("pages_bp registered (about, contact, security)")
    except Exception:
        app.logger.exception("Failed to register pages_bp")

    try:
        from app.public import public_bp
        app.register_blueprint(public_bp)
        app.logger.info("public_bp registered")
    except Exception:
        app.logger.exception("Failed to register public_bp")

    try:
        from app.social import social_bp
        app.register_blueprint(social_bp)
        app.logger.info("social_bp registered at /social")
    except Exception:
        app.logger.exception("Failed to register social_bp")

    try:
        from app.gmb import gmb_bp
        app.register_blueprint(gmb_bp)  # url_prefix defined in blueprint
        app.logger.info("gmb_bp registered at /account/gmb")
    except Exception:
        app.logger.exception("Failed to register gmb_bp")

    try:
        from app.seo import seo_bp
        app.register_blueprint(seo_bp, url_prefix="/account/seo")
        app.logger.info("seo_bp registered at /account/seo")
    except Exception:
        app.logger.exception("Failed to register seo_bp")

    try:
        from app.reports import reports_bp
        app.register_blueprint(reports_bp, url_prefix="/account/reports")
        app.logger.info("reports_bp registered at /account/reports")
    except Exception:
        app.logger.exception("Failed to register reports_bp")

    try:
        from app.linkedin import linkedin_bp
        app.register_blueprint(linkedin_bp)  # url_prefix defined in blueprint
        app.logger.info("linkedin_bp registered at /account/linkedin")
    except Exception:
        app.logger.exception("Failed to register linkedin_bp")

    try:
        from app.fbads.data_deletion import data_deletion_bp
        app.register_blueprint(data_deletion_bp, url_prefix="/account")
        from app.fbads.data_governance import data_bp
        app.register_blueprint(data_bp, url_prefix="/account")
    except Exception:
        app.logger.exception("Failed to register FB data governance blueprints")

    try:
        from app.maps import maps_bp
        app.register_blueprint(maps_bp, url_prefix="/account/maps")
        app.logger.info("maps_bp registered at /account/maps")
    except Exception:
        app.logger.exception("Failed to register maps_bp")

    try:
        from app.campaigns import campaigns_bp
        app.register_blueprint(campaigns_bp, url_prefix="/account/campaigns")
        app.logger.info("campaigns_bp registered at /account/campaigns")
    except Exception:
        app.logger.exception("Failed to register campaigns_bp")

    try:
        from app.google.ads import gads_bp
        app.register_blueprint(gads_bp)  # no extra prefix here
    except Exception:
        app.logger.exception("Failed to register gads_bp")

    # Disabled old SMTP-based test email route - now using Mailgun API in admin_bp
    # try:
    #     from app.test_email import test_mail_bp
    #     app.register_blueprint(test_mail_bp)
    # except Exception:
    #     app.logger.exception("Failed to register test_mail_bp")

    # --- Admin (employees only; direct URL; no public link) -----------------
    try:
        from app.admin.routes import admin_bp
        app.register_blueprint(admin_bp)  # url_prefix is set inside the blueprint (/admin)
        app.logger.info("admin_bp registered")
    except Exception:
        app.logger.exception("Failed to register admin_bp")

    try:
        from app.admin.agent_config_routes import agent_config_bp
        app.register_blueprint(agent_config_bp)  # url_prefix=/admin/agents
        app.logger.info("agent_config_bp registered at /admin/agents")
    except Exception:
        app.logger.exception("Failed to register agent_config_bp")

    try:
        from app.admin.email_workflow_routes import email_workflow_bp
        app.register_blueprint(email_workflow_bp)  # url_prefix=/admin/email-workflows
        app.logger.info("email_workflow_bp registered at /admin/email-workflows")
    except Exception:
        app.logger.exception("Failed to register email_workflow_bp")

    try:
        from app.admin.servicetitan_routes import servicetitan_bp
        app.register_blueprint(servicetitan_bp)  # url_prefix=/admin/servicetitan
        app.logger.info("servicetitan_bp registered at /admin/servicetitan")
    except Exception:
        app.logger.exception("Failed to register servicetitan_bp")

    try:
        from app.admin.lead_campaigns_routes import lead_campaigns_bp
        app.register_blueprint(lead_campaigns_bp)  # url_prefix=/admin/lead-campaigns
        app.logger.info("lead_campaigns_bp registered at /admin/lead-campaigns")
    except Exception:
        app.logger.exception("Failed to register lead_campaigns_bp")

    try:
        from app.admin.conversations_routes import conversations_bp
        app.register_blueprint(conversations_bp)  # url_prefix=/admin/conversations
        app.logger.info("conversations_bp registered at /admin/conversations")
    except Exception:
        app.logger.exception("Failed to register conversations_bp")

    # --- Email Webhooks (AI auto-responses for inbound emails) -------------
    try:
        from app.email_webhooks import email_webhook_bp
        app.register_blueprint(email_webhook_bp)  # url_prefix=/api/email
        app.logger.info("email_webhook_bp registered at /api/email")
    except Exception:
        app.logger.exception("Failed to register email_webhook_bp")

    # --- Email Tracking (public endpoints for pixel and click tracking) ----
    try:
        from app.email_tracking_routes import email_tracking_bp
        app.register_blueprint(email_tracking_bp)  # url_prefix is /track
        app.logger.info("email_tracking_bp registered at /track")
    except Exception:
        app.logger.exception("Failed to register email_tracking_bp")

    # --- Page View Tracking (public endpoints for user flow analytics) -----
    try:
        from app.page_view_tracking_routes import page_view_tracking_bp
        app.register_blueprint(page_view_tracking_bp)  # url_prefix is /pv
        app.logger.info("page_view_tracking_bp registered at /pv")
    except Exception:
        app.logger.exception("Failed to register page_view_tracking_bp")

    # --- Google Ads Grader (free for all users) -----------------------------
    try:
        from app.ads_grader import ads_grader_bp
        app.register_blueprint(ads_grader_bp)  # url_prefix set in blueprint (/ads-grader)
        app.logger.info("ads_grader_bp registered at /ads-grader")
    except Exception:
        app.logger.exception("Failed to register ads_grader_bp")

    # --- Facebook Ads Grader (free for all users) -----------------------------
    # DISABLED: Pending Facebook app approval for business_management permission
    # try:
    #     from app.fb_ads_grader import fb_ads_grader_bp
    #     app.register_blueprint(fb_ads_grader_bp)  # url_prefix set in blueprint (/account/fbads)
    #     app.logger.info("fb_ads_grader_bp registered at /account/fbads")
    # except Exception:
    #     app.logger.exception("Failed to register fb_ads_grader_bp")

    # ---- Apply CSRF exemptions AFTER blueprints are registered -------------
    try:
        for ep in (
            "gmb_bp.apply_suggestions",
            "gmb_bp.update_profile",
            "gmb_bp.reviews_ai_draft",
            "gmb_bp.optimize_profile_json",
            "google_bp.ads_select_customer",  # AJAX endpoint for selecting Google Ads customer
            "google_bp.ads_list_customers",   # AJAX endpoint for listing Google Ads customers
        ):
            fn = app.view_functions.get(ep)
            if fn:
                csrf.exempt(fn)
        app.logger.info("CSRF exemptions applied for GMB POST endpoints")
    except Exception as e:
        app.logger.warning(f"Could not exempt GMB endpoints from CSRF: {e}")

    # ---- Debug route for session diagnostics (REMOVE IN PRODUCTION) --------
    @app.route('/debug-session')
    def debug_session():
        """
        Diagnostic endpoint to debug session and HTTPS detection issues.
        Visit https://fieldsprout.io/debug-session to see session state.

        IMPORTANT: Remove this route before deploying to production!
        """
        from flask import request, session, jsonify

        return jsonify({
            'session_data': dict(session),
            'cookies': dict(request.cookies),
            'request_scheme': request.scheme,
            'request_is_secure': request.is_secure,
            'request_url': request.url,
            'request_base_url': request.base_url,
            'request_host': request.host,
            'request_headers': dict(request.headers),
            'flask_config': {
                'SESSION_COOKIE_SECURE': app.config.get('SESSION_COOKIE_SECURE'),
                'SESSION_COOKIE_HTTPONLY': app.config.get('SESSION_COOKIE_HTTPONLY'),
                'SESSION_COOKIE_SAMESITE': app.config.get('SESSION_COOKIE_SAMESITE'),
                'PERMANENT_SESSION_LIFETIME': str(app.config.get('PERMANENT_SESSION_LIFETIME')),
                'PREFERRED_URL_SCHEME': app.config.get('PREFERRED_URL_SCHEME'),
            },
            'env_vars': {
                'HTTPS': _os.getenv('HTTPS'),
                'SECRET_KEY_SET': bool(_os.getenv('SECRET_KEY')),
            },
            'auth_status': {
                'has_session_cookie': 'session' in request.cookies,
                'session_keys': list(session.keys()) if session else [],
            }
        })

    # ---- Additional debug route for login check ----------------------------
    @app.route('/debug-login-check')
    def debug_login_check():
        """Check if login_required decorator would pass"""
        from flask import session, jsonify
        from app.auth.utils import is_logged_in, current_user_id, current_account_id

        try:
            logged_in = is_logged_in()
            user_id = current_user_id()
            account_id = current_account_id()
        except Exception as e:
            return jsonify({
                'error': str(e),
                'traceback': __import__('traceback').format_exc()
            })

        return jsonify({
            'is_logged_in': logged_in,
            'current_user_id': user_id,
            'current_account_id': account_id,
            'session_keys': list(session.keys()),
            'would_pass_login_required': logged_in and user_id is not None,
            'would_pass_dashboard_check': logged_in and account_id is not None
        })

    # ---- Request hooks (auth + impersonation) ------------------------------
    try:
        from app.auth.session_helpers import before_request_hook
        app.before_request(before_request_hook)
    except Exception:
        app.logger.exception("Failed to register before_request_hook (auth/session_helpers)")

    # ---- Post-registration safety stubs ------------------------------------
    if "reports_bp.index" not in app.view_functions:
        def _reports_index_stub():
            return (
                "<div style='padding:20px;font-family:system-ui'>"
                "<h1>Reports</h1>"
                "<p>This is a temporary page. Your reports module can replace this endpoint at "
                "<code>reports_bp.index</code>.</p>"
                "<p><a href='/account/dashboard'>Back to Dashboard</a></p>"
                "</div>", 200)
        app.add_url_rule(
            "/account/reports",
            endpoint="reports_bp.index",
            view_func=_reports_index_stub,
            methods=["GET"],
        )
        app.logger.info("Stub endpoint registered for reports_bp.index -> /account/reports")

    if "fbads_bp.leads" not in app.view_functions:
        def _fbads_leads_stub():
            return (
                "<div style='padding:20px;font-family:system-ui'>"
                "<h1>Facebook Leads</h1>"
                "<p>This is a temporary page. Your fbads module can replace this endpoint at "
                "<code>fbads_bp.leads</code>.</p>"
                "<p><a href='/account/fbads'>Back to Facebook</a></p>"
                "</div>", 200)
        app.add_url_rule(
            "/account/fbads/leads",
            endpoint="fbads_bp.leads",
            view_func=_fbads_leads_stub,
            methods=["GET"],
        )
        app.logger.info("Stub endpoint registered for fbads_bp.leads -> /account/fbads/leads")

    if "fbads_bp.optimize" not in app.view_functions:
        def _fbads_optimize_stub():
            return (
                "<div style='padding:20px;font-family:system-ui'>"
                "<h1>Facebook Optimize</h1>"
                "<p>This is a temporary page. Your fbads module can replace this endpoint at "
                "<code>fbads_bp.optimize</code>.</p>"
                "<p><a href='/account/fbads'>Back to Facebook</a></p>"
                "</div>", 200)
        app.add_url_rule(
            "/account/fbads/optimize",
            endpoint="fbads_bp.optimize",
            view_func=_fbads_optimize_stub,
            methods=["GET"],
        )
        app.logger.info("Stub endpoint registered for fbads_bp.optimize -> /account/fbads/optimize")

    # ---- Cron runner (HTTP) -------------------------------------------------
    @app.route("/__cron__/run/<name>", methods=["GET", "POST"])
    def __cron_run(name):
        if name not in ("minutely", "hourly", "daily"):
            return ("unknown task", 404)

        key = request.args.get("key") or request.headers.get("X-Cron-Key")
        if not key or key != app.config.get("CRON_SECRET", ""):
            return abort(403)

        from sqlalchemy import text as _text
        lock_key = f"cron:{name}"
        acquired = False
        try:
            with db.engine.begin() as conn:
                acquired = bool(conn.execute(_text("SELECT GET_LOCK(:k,0)"), {"k": lock_key}).scalar())
                if not acquired:
                    app.logger.info("[CRON] %s skipped (lock busy)", name)
                    return ("busy", 409)

                from app.cron_tasks import run_minutely, run_hourly, run_daily
                if name == "minutely":
                    run_minutely(app, db)
                elif name == "hourly":
                    run_hourly(app, db)
                elif name == "daily":
                    run_daily(app, db)

                app.logger.info("[CRON] %s completed", name)
                return ("ok", 200)
        finally:
            if acquired:
                try:
                    with db.engine.begin() as conn:
                        conn.execute(_text("SELECT RELEASE_LOCK(:k)"), {"k": lock_key})
                except Exception:
                    app.logger.exception("[CRON] release lock failed")

    try:
        csrf.exempt(__cron_run)
    except Exception as e:
        app.logger.warning(f"Could not exempt cron route from CSRF: {e}")

    # ---- Diagnostics --------------------------------------------------------
    @app.route("/__routes__")
    def __routes__():
        lines = []
        for rule in sorted(app.url_map.iter_rules(), key=lambda r: r.rule):
            methods = ",".join(sorted(m for m in rule.methods if m not in ("HEAD", "OPTIONS")))
            lines.append(f"{rule.rule} → {rule.endpoint} [{methods}]")
        return "<pre>" + escape("\n".join(lines)) + "</pre>"

    @app.route("/__health__")
    def __health__():
        return "ok", 200

    @app.route("/__dbcheck__")
    def __dbcheck__():
        info = {
            "connected": False, "driver": "", "database": "",
            "host": "", "port": "", "version": "", "tables_sample": []
        }
        try:
            from sqlalchemy import text as _text
            uri = app.config["SQLALCHEMY_DATABASE_URI"]
            info["driver"] = uri.split("://", 1)[0]
            with db.engine.connect() as conn:
                ver = conn.execute(_text("SELECT VERSION()")).scalar()
                info["version"] = ver
                if "://" in uri:
                    after = uri.split("://", 1)[1]
                    if "/" in after:
                        dbname = after.rsplit("/", 1)[1].split("?")[0]
                        info["database"] = dbname
                rows = conn.execute(_text("SHOW TABLES")).fetchmany(10)
                info["tables_sample"] = [r[0] for r in rows]
            info["connected"] = True
        except Exception as e:
            app.logger.exception("__dbcheck__ failed: %s", e)
        return {"ok": True, "db": info}, 200

    # ---- Flask CLI cron commands -------------------------------------------
    @app.cli.command("cron-minutely")
    def cron_minutely():
        from app.cron_tasks import run_minutely
        run_minutely(app, db)

    @app.cli.command("cron-hourly")
    def cron_hourly():
        from app.cron_tasks import run_hourly
        run_hourly(app, db)

    @app.cli.command("cron-daily")
    def cron_daily():
        from app.cron_tasks import run_daily
        run_daily(app, db)

    # ---- CSRF error handler (friendly UX) ----------------------------------
    if CSRFError is not None:
        @app.errorhandler(CSRFError)
        def handle_csrf_error(e):
            app.logger.warning(f"CSRF failed: {getattr(e, 'description', str(e))}")
            flash("Your session expired or the form was invalid. Please try again.", "error")
            return redirect(request.referrer or url_for("main_bp.home")), 400

    # ---- General error handlers --------------------------------------------
    @app.errorhandler(400)
    def _400(err):
        """Handle 400 Bad Request errors with clean HTML page"""
        return render_template_string("""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>400 Bad Request - {{ app_name }}</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%);
            color: #333;
            margin: 0;
            padding: 0;
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: 100vh;
        }
        .error-container {
            background: white;
            border-radius: 16px;
            padding: 3rem 2rem;
            max-width: 600px;
            width: 90%;
            text-align: center;
            box-shadow: 0 25px 50px -12px rgba(0,0,0,0.25);
        }
        .logo {
            font-size: 2rem;
            font-weight: 800;
            background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            margin-bottom: 2rem;
        }
        .error-icon {
            font-size: 5rem;
            color: #fbbf24;
            margin-bottom: 1rem;
        }
        .error-code {
            font-size: 6rem;
            font-weight: 800;
            margin: 0;
            background: linear-gradient(135deg, #fbbf24 0%, #f59e0b 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            line-height: 1;
        }
        h2 {
            font-size: 1.75rem;
            margin: 1rem 0;
            color: #1f2937;
            font-weight: 700;
        }
        p {
            color: #6b7280;
            line-height: 1.6;
            margin-bottom: 2rem;
            font-size: 1.1rem;
        }
        .help-text {
            background: #f3f4f6;
            border-left: 4px solid #4f46e5;
            padding: 1rem;
            margin: 1.5rem 0;
            text-align: left;
            border-radius: 0.5rem;
        }
        .help-text strong {
            color: #1f2937;
            display: block;
            margin-bottom: 0.5rem;
        }
        .help-text ul {
            margin: 0.5rem 0 0 1.5rem;
            padding: 0;
            color: #4b5563;
        }
        .help-text li {
            margin: 0.25rem 0;
        }
        .btn {
            display: inline-block;
            padding: 0.875rem 2rem;
            background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%);
            color: white;
            text-decoration: none;
            border-radius: 8px;
            font-weight: 600;
            transition: all 0.2s;
            box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1);
            margin: 0 0.5rem;
        }
        .btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 10px 15px -3px rgba(0,0,0,0.1);
        }
        .btn-secondary {
            background: white;
            color: #4f46e5;
            border: 2px solid #4f46e5;
        }
        .btn-secondary:hover {
            background: #f3f4f6;
        }
        .footer {
            margin-top: 2rem;
            padding-top: 1.5rem;
            border-top: 1px solid #e5e7eb;
            color: #9ca3af;
            font-size: 0.875rem;
        }
    </style>
</head>
<body>
    <div class="error-container">
        <div class="logo">{{ app_name }}</div>
        <div class="error-icon">
            <i class="fa-solid fa-triangle-exclamation"></i>
        </div>
        <div class="error-code">400</div>
        <h2>Bad Request</h2>
        <p>Oops! The request you sent couldn't be processed. This usually happens when the data format is incorrect or missing required information.</p>

        <div class="help-text">
            <strong><i class="fa-solid fa-lightbulb"></i> Common causes:</strong>
            <ul>
                <li>Missing or invalid form fields</li>
                <li>Incorrect data format</li>
                <li>Expired or invalid session</li>
            </ul>
        </div>

        <div>
            <a href="/" class="btn">
                <i class="fa-solid fa-home"></i> Return Home
            </a>
            <a href="javascript:history.back()" class="btn btn-secondary">
                <i class="fa-solid fa-arrow-left"></i> Go Back
            </a>
        </div>

        <div class="footer">
            Need help? <a href="/contact" style="color: #4f46e5; text-decoration: none;">Contact Support</a>
        </div>
    </div>
</body>
</html>
        """, app_name=app.config.get('APP_NAME', 'FieldSprout')), 400

    @app.errorhandler(404)
    def _404(err):
        """Handle 404 Not Found errors with clean HTML page"""
        return render_template_string("""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>404 Not Found - {{ app_name }}</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: #333;
            margin: 0;
            padding: 0;
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: 100vh;
        }
        .error-container {
            background: white;
            border-radius: 12px;
            padding: 3rem;
            max-width: 500px;
            text-align: center;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
        }
        h1 {
            font-size: 4rem;
            margin: 0 0 1rem 0;
            color: #667eea;
        }
        h2 {
            font-size: 1.5rem;
            margin: 0 0 1rem 0;
            color: #333;
            font-weight: 600;
        }
        p {
            color: #666;
            line-height: 1.6;
            margin-bottom: 2rem;
        }
        .path {
            font-family: 'Courier New', monospace;
            background: #f5f5f5;
            padding: 0.5rem 1rem;
            border-radius: 4px;
            color: #e91e63;
            font-size: 0.9rem;
            margin: 1rem 0;
            word-break: break-all;
        }
        .btn {
            display: inline-block;
            padding: 0.75rem 2rem;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            text-decoration: none;
            border-radius: 6px;
            font-weight: 600;
            transition: transform 0.2s;
        }
        .btn:hover {
            transform: translateY(-2px);
        }
        .btn-secondary {
            background: white;
            color: #667eea;
            border: 2px solid #667eea;
            margin-left: 0.5rem;
        }
        .buttons {
            display: flex;
            gap: 0.5rem;
            justify-content: center;
            flex-wrap: wrap;
        }
    </style>
</head>
<body>
    <div class="error-container">
        <h1>404</h1>
        <h2>Page Not Found</h2>
        <p>The page you're looking for doesn't exist or has been moved.</p>
        <div class="path">{{ path }}</div>
        <div class="buttons">
            <a href="/" class="btn">Return Home</a>
            <a href="/auth/login" class="btn btn-secondary">Sign In</a>
        </div>
    </div>
</body>
</html>
        """, app_name=app.config.get('APP_NAME', 'FieldSprout'), path=request.path), 404

    @app.errorhandler(500)
    def _500(err):
        """Handle 500 Internal Server Error with clean HTML page"""
        app.logger.exception("Unhandled exception")
        return render_template_string("""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>500 Internal Server Error - {{ app_name }}</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%);
            color: #333;
            margin: 0;
            padding: 0;
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: 100vh;
        }
        .error-container {
            background: white;
            border-radius: 16px;
            padding: 3rem 2rem;
            max-width: 600px;
            width: 90%;
            text-align: center;
            box-shadow: 0 25px 50px -12px rgba(0,0,0,0.25);
        }
        .logo {
            font-size: 2rem;
            font-weight: 800;
            background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            margin-bottom: 2rem;
        }
        .error-icon {
            font-size: 5rem;
            color: #ef4444;
            margin-bottom: 1rem;
            animation: pulse 2s ease-in-out infinite;
        }
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }
        .error-code {
            font-size: 6rem;
            font-weight: 800;
            margin: 0;
            background: linear-gradient(135deg, #ef4444 0%, #dc2626 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            line-height: 1;
        }
        h2 {
            font-size: 1.75rem;
            margin: 1rem 0;
            color: #1f2937;
            font-weight: 700;
        }
        p {
            color: #6b7280;
            line-height: 1.6;
            margin-bottom: 2rem;
            font-size: 1.1rem;
        }
        .status-box {
            background: #fef2f2;
            border: 2px solid #fecaca;
            border-radius: 0.5rem;
            padding: 1rem;
            margin: 1.5rem 0;
        }
        .status-box strong {
            color: #991b1b;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 0.5rem;
            font-size: 1rem;
        }
        .status-box p {
            margin: 0.5rem 0 0 0;
            font-size: 0.95rem;
            color: #7f1d1d;
        }
        .help-text {
            background: #f3f4f6;
            border-left: 4px solid #4f46e5;
            padding: 1rem;
            margin: 1.5rem 0;
            text-align: left;
            border-radius: 0.5rem;
        }
        .help-text strong {
            color: #1f2937;
            display: block;
            margin-bottom: 0.5rem;
        }
        .help-text ul {
            margin: 0.5rem 0 0 1.5rem;
            padding: 0;
            color: #4b5563;
        }
        .help-text li {
            margin: 0.25rem 0;
        }
        .btn {
            display: inline-block;
            padding: 0.875rem 2rem;
            background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%);
            color: white;
            text-decoration: none;
            border-radius: 8px;
            font-weight: 600;
            transition: all 0.2s;
            box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1);
            margin: 0 0.5rem 0.5rem 0.5rem;
        }
        .btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 10px 15px -3px rgba(0,0,0,0.1);
        }
        .btn-secondary {
            background: white;
            color: #4f46e5;
            border: 2px solid #4f46e5;
        }
        .btn-secondary:hover {
            background: #f3f4f6;
        }
        .footer {
            margin-top: 2rem;
            padding-top: 1.5rem;
            border-top: 1px solid #e5e7eb;
            color: #9ca3af;
            font-size: 0.875rem;
        }
    </style>
</head>
<body>
    <div class="error-container">
        <div class="logo">{{ app_name }}</div>
        <div class="error-icon">
            <i class="fa-solid fa-server"></i>
        </div>
        <div class="error-code">500</div>
        <h2>Internal Server Error</h2>
        <p>We're sorry! Something went wrong on our end. Our team has been automatically notified and we're working to fix this issue.</p>

        <div class="status-box">
            <strong>
                <i class="fa-solid fa-bell"></i>
                We've Been Notified
            </strong>
            <p>Our engineering team has received an alert about this error and is investigating.</p>
        </div>

        <div class="help-text">
            <strong><i class="fa-solid fa-wrench"></i> What you can do:</strong>
            <ul>
                <li>Wait a few moments and try again</li>
                <li>Clear your browser cache and cookies</li>
                <li>Try a different browser</li>
                <li>If the issue persists, contact our support team</li>
            </ul>
        </div>

        <div>
            <a href="/" class="btn">
                <i class="fa-solid fa-home"></i> Return Home
            </a>
            <a href="/login" class="btn btn-secondary">
                <i class="fa-solid fa-right-to-bracket"></i> Sign In
            </a>
            <a href="javascript:location.reload()" class="btn btn-secondary">
                <i class="fa-solid fa-rotate-right"></i> Try Again
            </a>
        </div>

        <div class="footer">
            Need urgent help? <a href="/contact" style="color: #4f46e5; text-decoration: none; font-weight: 600;">Contact Support</a>
        </div>
    </div>
</body>
</html>
        """, app_name=app.config.get('APP_NAME', 'FieldSprout')), 500

    @app.errorhandler(Exception)
    def _handle_exception(err):
        """Catch-all exception handler"""
        app.logger.exception("Unhandled exception")
        # If it's an HTTP exception, let Flask handle it normally
        if hasattr(err, 'code'):
            return err
        # Otherwise, return 500
        return _500(err)

    @app.context_processor
    def inject_app_and_config():
        from flask import current_app
        return {"app": current_app, "config": current_app.config}

    # ---- Register CLI commands ---------------------------------------------
    try:
        from app.commands import register_commands
        register_commands(app)
        app.logger.info("CLI commands registered (run-agents)")
    except Exception as e:
        app.logger.warning(f"Failed to register CLI commands: {e}")

    # ---- Initialize Background Scheduler -----------------------------------
    try:
        from app.background_jobs import init_scheduler
        init_scheduler(app)
        app.logger.info("Background job scheduler initialized")
    except Exception as e:
        app.logger.warning(f"Failed to initialize scheduler: {e}")

    return app


# WSGI callable for Passenger/cPanel (or any WSGI server)
application = create_app()
