# app/extensions.py
from __future__ import annotations
from flask_sqlalchemy import SQLAlchemy
# --- SQLAlchemy (always present) --------------------------------------------
db = SQLAlchemy()
# --- CSRF (optional) --------------------------------------------------------
try:
    from flask_wtf import CSRFProtect  # type: ignore
except Exception:
    class _NoopCSRF:
        """No-op shim so app code can call init_app()/exempt() safely if WTForms isn't installed."""
        def init_app(self, *args, **kwargs):
            pass
        def exempt(self, *args, **kwargs):
            pass
    csrf = _NoopCSRF()
else:
    csrf = CSRFProtect()

# --- Flask-Migrate (optional) -----------------------------------------------
try:
    from flask_migrate import Migrate  # type: ignore
except Exception:
    class _NoopMigrate:
        def init_app(self, *args, **kwargs):
            pass
    migrate = _NoopMigrate()
else:
    migrate = Migrate()

__all__ = ["db", "csrf", "migrate"]
