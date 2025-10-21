# app/__init__.py
from __future__ import annotations

import io
import logging
import os as _os
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path

from flask import Flask, request, abort, redirect, url_for, flash, g
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

    def _protect(key):
        if not app.config.get(key):
            val = _os.environ.get(key)
            if val:
                app.config[key] = val.strip() if key.endswith("_TOKEN") else val.replace("-", "").strip()
    app.config["__protect_ads_config__"] = _protect

    app.logger.info(
        "Ads config: dev_token_len=%s, login_cid=%s",
        len(app.config.get("GOOGLE_ADS_DEVELOPER_TOKEN") or ""),
        app.config.get("GOOGLE_ADS_LOGIN_CUSTOMER_ID") or "None",
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

        def _probe_redis(url: str) -> bool:
            if not url:
                return False
            try:
                client = redis.from_url(url, decode_responses=True, socket_timeout=2)
                client.ping()
                return True
            except Exception as e:
                app.logger.warning(f"Redis probe failed: {e}")
                return False

        REDIS_URL = _os.getenv("REDIS_URL", "")
        app.redis = None
        if _probe_redis(REDIS_URL):
            app.redis = redis.from_url(REDIS_URL, decode_responses=True, socket_timeout=3)
            app.logger.info("Connected to Redis")
        else:
            app.logger.warning("Redis not available; continuing without app Redis client")

        if Limiter and get_remote_address:
            preferred = _os.getenv("RATELIMIT_STORAGE_URI") or REDIS_URL
            storage_uri = "memory://"
            if preferred != "memory://" and _probe_redis(preferred):
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

        return {
            "app_name": app.config["APP_NAME"],
            "year": datetime.now().year,
            "current_year": datetime.utcnow().year,
            "csrf_token": _generate_csrf,
            "is_logged_in": is_logged_in,
            "current_user_id": current_user_id,
            "has_endpoint": has_endpoint,
            "ep": ep,
        }

    @app.context_processor
    def ai_flags():
        try:
            from app.auth.utils import is_paid_account as _is_paid
            return {"ai_enabled": _is_paid()}
        except Exception:
            return {"ai_enabled": False}

    # ---- Security headers (nonce + CSP) ------------------------------------
    @app.before_request
    def _set_nonce():
        import secrets
        g.csp_nonce = secrets.token_urlsafe(16)

    @app.after_request
    def _security_headers(resp):
        nonce = getattr(g, "csp_nonce", "")

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
            f"script-src 'self' 'nonce-{nonce}' https://cdn.tailwindcss.com https://cdnjs.cloudflare.com; "
            "connect-src 'self'; frame-ancestors 'self'; base-uri 'self'; form-action 'self'"
        )
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
        from app.public import public_bp
        app.register_blueprint(public_bp)
        app.logger.info("public_bp registered")
    except Exception:
        app.logger.exception("Failed to register public_bp")

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

    try:
        from app.test_email import test_mail_bp
        app.register_blueprint(test_mail_bp)
    except Exception:
        app.logger.exception("Failed to register test_mail_bp")

    # --- Admin (employees only; direct URL; no public link) -----------------
    try:
        from app.admin.routes import admin_bp
        app.register_blueprint(admin_bp)  # url_prefix is set inside the blueprint (/admin)
        app.logger.info("admin_bp registered")
    except Exception:
        app.logger.exception("Failed to register admin_bp")

    # ---- Apply CSRF exemptions AFTER blueprints are registered -------------
    try:
        for ep in (
            "gmb_bp.apply_suggestions",
            "gmb_bp.update_profile",
            "gmb_bp.reviews_ai_draft",
            "gmb_bp.optimize_profile_json",
        ):
            fn = app.view_functions.get(ep)
            if fn:
                csrf.exempt(fn)
        app.logger.info("CSRF exemptions applied for GMB POST endpoints")
    except Exception as e:
        app.logger.warning(f"Could not exempt GMB endpoints from CSRF: {e}")

    # ---- Request hooks (auth + impersonation) ------------------------------
    try:
        from app.auth.session import before_request_hook
        app.before_request(before_request_hook)
    except Exception:
        app.logger.exception("Failed to register before_request_hook (auth/session)")

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
    @app.errorhandler(404)
    def _404(err):
        return (f"404 Not Found: {request.path}", 404)

    @app.errorhandler(Exception)
    def _500(err):
        app.logger.exception("Unhandled exception")
        return ("Internal Server Error", 500)

    @app.context_processor
    def inject_app_and_config():
        from flask import current_app
        return {"app": current_app, "config": current_app.config}

    # ---- Email configuration validation ------------------------------------
    def _check_email_config():
        """Check if email is properly configured and warn if not."""
        mail_server = app.config.get("MAIL_SERVER")
        mail_sender = app.config.get("MAIL_DEFAULT_SENDER")

        if not mail_server or not mail_sender:
            app.logger.warning(
                "⚠️  Email not configured! Set MAIL_SERVER and MAIL_DEFAULT_SENDER. "
                "Email verification and password reset will not work."
            )
            return False

        # Check for port/protocol mismatch
        mail_port = app.config.get("MAIL_PORT", 587)
        use_ssl = app.config.get("MAIL_USE_SSL", False)
        use_tls = app.config.get("MAIL_USE_TLS", True)

        if mail_port == 465 and not use_ssl:
            app.logger.warning(
                "⚠️  Email config issue: Port 465 requires MAIL_USE_SSL=1"
            )
        elif mail_port == 587 and not use_tls:
            app.logger.warning(
                "⚠️  Email config issue: Port 587 typically requires MAIL_USE_TLS=1"
            )

        app.logger.info(f"✓ Email configured: {mail_sender} via {mail_server}:{mail_port}")
        return True

    _check_email_config()

    return app


# WSGI callable for Passenger/cPanel (or any WSGI server)
application = create_app()
