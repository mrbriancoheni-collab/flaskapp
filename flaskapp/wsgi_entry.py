"""
wsgi_entry.py — actual WSGI entry point for FieldSprout on CloudLinux.

CloudLinux Python Selector resets passenger_wsgi.py to a 9-line stub on
every restart.  That stub does:
    wsgi = imp.load_source('wsgi', 'wsgi_entry.py')
    application = wsgi.application

So this file is the real entry point.  It must NOT import from passenger_wsgi
(circular import crash) and must be fully self-contained.
"""
import os
import sys
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime

# Resolve the directory containing this file regardless of how it was loaded
APP_ROOT = os.path.dirname(os.path.abspath(__file__))
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

# Set working directory so relative paths inside the app resolve correctly
os.chdir(APP_ROOT)

# Remove stale env vars that break virtualenv Python on some cPanel hosts
os.environ.pop("PYTHONHOME", None)
os.environ.pop("PYTHONPATH", None)

# ---- Early startup log -------------------------------------------------------
LOG_FILE = os.path.join(APP_ROOT, "stderr.log")
try:
    with open(LOG_FILE, "a") as _f:
        _f.write(f"\n=== WSGI STARTUP {datetime.now()} ===\n")
        _f.write(f"APP_ROOT: {APP_ROOT}\n")
        _f.write(f"Python: {sys.version}\n")
        _f.flush()
except Exception:
    pass

try:
    _fh = RotatingFileHandler(LOG_FILE, maxBytes=1_000_000, backupCount=3)
    _fh.setLevel(logging.DEBUG)
    _fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    logging.basicConfig(level=logging.DEBUG, handlers=[_fh])
except Exception:
    pass

# ---- Load .env ---------------------------------------------------------------
_env_file = os.path.join(APP_ROOT, ".env")
if os.path.exists(_env_file):
    with open(_env_file) as _ef:
        for _line in _ef:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                _k = _k.strip()
                _v = _v.strip()
                if _k and not os.environ.get(_k):
                    os.environ[_k] = _v

# ---- Default env vars --------------------------------------------------------
os.environ.setdefault("GOOGLE_ADS_DEVELOPER_TOKEN", "BVH9TCTe66hciT3TrMrKxg")
os.environ.setdefault("STRIPE_MONTHLY_LINK", "https://buy.stripe.com/cNibIU2jC9Jb4xd9zl0ZW04")
os.environ.setdefault("STRIPE_YEARLY_LINK",  "https://buy.stripe.com/eVq5kwaQ81cF7Jp9zl0ZW05")

# ---- Import Flask app --------------------------------------------------------
from app import application as _flask_app  # noqa: E402


# ---- WSGI middleware: fix SCRIPT_NAME / PATH_INFO ----------------------------
def _fix_path_info(wsgi_app):
    """
    Normalize SCRIPT_NAME / PATH_INFO before they reach Flask.

    LiteSpeed (and some Passenger configs) mount the app at '/' by setting
    SCRIPT_NAME='/' and PATH_INFO='' for requests to the root.  Flask routes
    against PATH_INFO, so an empty string matches nothing and returns 404.
    """
    def middleware(environ, start_response):
        if environ.get("SCRIPT_NAME") == "/":
            environ["SCRIPT_NAME"] = ""
        if not environ.get("PATH_INFO"):
            environ["PATH_INFO"] = "/"
        if environ.get("PATH_INFO") in ("/index.php", "/index.html"):
            environ["PATH_INFO"] = "/"
        return wsgi_app(environ, start_response)
    return middleware


# ---- WSGI middleware: diagnostic intercept -----------------------------------
def _diagnostic_wrapper(wsgi_app):
    """
    Return a quick JSON response for deploy-check paths at the raw WSGI layer,
    bypassing Flask entirely so it's always reachable even if Flask is broken.
    """
    import json as _json

    DEPLOY_STAMP = "2026-04-05T00:00:00-WSGI-V5"
    INTERCEPT = {"/_deploy_check", "/deploy_check", "/wsgi-check"}

    def middleware(environ, start_response):
        path = environ.get("PATH_INFO", "") or "/"
        if path in INTERCEPT:
            body = _json.dumps({
                "status": "ok",
                "stamp": DEPLOY_STAMP,
                "path": path,
                "host": environ.get("HTTP_HOST", ""),
                "server_software": environ.get("SERVER_SOFTWARE", ""),
            }).encode()
            start_response("200 OK", [
                ("Content-Type", "application/json"),
                ("Content-Length", str(len(body))),
            ])
            return [body]
        return wsgi_app(environ, start_response)
    return middleware


application = _fix_path_info(_flask_app)
application = _diagnostic_wrapper(application)
