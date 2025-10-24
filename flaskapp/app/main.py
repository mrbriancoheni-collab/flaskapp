# app/main.py
import os
from flask import Flask, g, request, abort, send_file

app = Flask(__name__, template_folder="../templates", static_folder="../static")
app.config["ENV"] = "production"
app.config["DEBUG"] = False
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "change-me")
app.config["PREFERRED_URL_SCHEME"] = "https"

# ---- Redis + Limiter (resilient) ----
import redis

REDIS_URL = os.getenv("REDIS_URL", "")
redis_client = None

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

# Try to establish an app-wide Redis client (optional utility)
if _probe_redis(REDIS_URL):
    redis_client = redis.from_url(REDIS_URL, decode_responses=True, socket_timeout=3)
    app.logger.info("Connected to Redis")
else:
    app.logger.warning("Redis not available; continuing without app Redis client")

# Flask-Limiter: choose storage URI with fallback-to-memory
try:
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address

    preferred = os.getenv("RATELIMIT_STORAGE_URI") or REDIS_URL
    storage_uri = preferred if _probe_redis(preferred) else "memory://"

    limiter = Limiter(
        key_func=get_remote_address,
        storage_uri=storage_uri,
        default_limits=["200 per day", "50 per hour"],
        in_memory_fallback_enabled=True,  # extra safety
    )
    limiter.init_app(app)
    app.logger.info(f"Rate limit storage: {storage_uri}")
except Exception as e:
    app.logger.warning(f"Rate limiter disabled: {e}")
    limiter = None

# --- DB session per request ---
from app.db import SessionLocal

@app.before_request
def _open_db_session():
    g.db = SessionLocal()

@app.teardown_request
def _close_db_session(exc):
    db = getattr(g, "db", None)
    if db is not None:
        db.close()

# --- Blueprints (if/when converted to Flask) ---
try:
    from app.routers.ui import bp as ui_bp
    app.register_blueprint(ui_bp)
except Exception:
    pass
try:
    from app.routers.google_ads import bp as google_ads_bp
    app.register_blueprint(google_ads_bp)
except Exception:
    pass
try:
    from app.routers.reporting import bp as reporting_bp
    app.register_blueprint(reporting_bp)
except Exception:
    pass

# --- File download (confined to EXPORTS_DIR) ---
EXPORTS_DIR = os.getenv("EXPORTS_DIR", os.path.expanduser("~/flaskapp/exports"))

@app.route("/download/local")
def download_local():
    path = request.args.get("path", "").strip()
    if not path:
        abort(400, description="Missing ?path=")
    import os as _os
    abs_path = _os.path.abspath(path if _os.path.isabs(path) else _os.path.join(EXPORTS_DIR, path))
    exports_root = _os.path.abspath(EXPORTS_DIR)
    if not abs_path.startswith(exports_root + _os.sep) and abs_path != exports_root:
        abort(403, description="Access denied")
    if not _os.path.isfile(abs_path):
        abort(404, description="File not found")
    filename = _os.path.basename(abs_path)
    return send_file(abs_path, as_attachment=True, download_name=filename)

# --- Optional: quick Redis ping for testing (remove in prod) ---
@app.get("/_redis_ping")
def _redis_ping():
    if not redis_client:
        abort(503, description="Redis not configured/available")
    return {"pong": True}
